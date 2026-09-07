"""Lógica del directorio de extensiones (unifica puestos + extras)."""
import logging
import unicodedata

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def department_rows(db: Session, *, include_unofficial: bool) -> list[dict]:
    """Esqueleto ordenado (DFS preorden) del conjunto de departamentos RENDERIZADO.

    Devuelve [{id, name, is_official, depth, ancestors}] con `depth` y `ancestors`
    recalculados sobre lo que se va a pintar, no sobre el árbol completo.

    Invariante duro: un departamento OFICIAL nunca desaparece. Si su ancestro no
    oficial está oculto, se recuelga del ancestro superviviente más cercano; así
    el prefijo de la banda nunca nombra un departamento invisible.
    """
    from itcj2.core.services.departments_service import build_tree

    out: list[dict] = []

    def walk(nodes, ancestors):
        for node in nodes:
            if include_unofficial or node["is_official"]:
                out.append({
                    "id": node["id"],
                    "name": node["name"],
                    "is_official": node["is_official"],
                    "depth": len(ancestors),
                    "ancestors": list(ancestors),
                })
                walk(node["children"], ancestors + [{"id": node["id"], "name": node["name"]}])
            else:
                # Oculto: sus hijos visibles se recuelgan del ancestro superviviente.
                walk(node["children"], ancestors)

    walk(build_tree(db), [])
    return out


# Puestos legacy que NO siguen la convención head_{dept.code} y no se pueden
# renombrar sin tocar el approval chain de bajas de inventario en helpdesk
# (AWAITING_DIRECTOR/AWAITING_SUBDIRECTOR — ver database/DML/core/config_2026_07/
# subtree/03_fix_subdirector_head_codes.sql para el detalle y los otros 2 que
# sí se renombraron).
_LEGACY_HEAD_CODES = {"director", "subdirector_admin_services"}

_RANK_ORDER = {"head": 0, "secretary": 1, "other": 2}

_TITLE_CONNECTORS = {
    "de", "del", "la", "el", "los", "las", "y",
    "depto", "departamento", "division", "coordinacion", "coord", "subdireccion",
}

_MAX = {"label": 120, "holder_name": 120, "extension": 10, "notes": 200, "email": 150}

_KEEP = object()   # centinela: "no toques el correo" ("" y None significan BORRARLO)


def _is_head_position(position) -> bool:
    """True si `position` es el jefe de su departamento (code == head_{dept.code})."""
    dept = position.department
    if not dept:
        return False
    return position.code == f"head_{dept.code}" or position.code in _LEGACY_HEAD_CODES


def _position_rank(position) -> str:
    """head > secretary > other, SIEMPRE por código, nunca por título.

    `head_union_delegation` se titula «Secretario General»: cualquier heurística
    por título lo degradaría a secretaria y lo sacaría del primer lugar del grupo.

    El prefijo `secretary_` (y no el estricto `secretary_{dept.code}` que usa
    helpdesk) es deliberado: el estricto deja fuera a secretary_direction_1 y
    secretary_direction_2.
    """
    if _is_head_position(position):
        return "head"
    code = (getattr(position, "code", "") or "").strip().lower()
    return "secretary" if code == "secretary" or code.startswith("secretary_") else "other"


def _norm(text: str) -> str:
    """minúsculas + sin acentos + espacios colapsados + sin punto final."""
    if not text:
        return ""
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(stripped.lower().split()).rstrip(".")


def short_title(title: str, department_name: str) -> str:
    """Quita del título la cola que repite el nombre del departamento.

    «Secretaria del Depto. de Sistemas y Computación» dentro del grupo
    «Sistemas y Computación» se muestra como «Secretaria»; el título completo
    sigue en el atributo title= y en el índice de búsqueda.

    Sin fuzzy matching a propósito: `secretary_info_resources` se titula
    «Secretaria del Depto. de Centro de Información» mientras su departamento se
    llama «Recursos de Información». Ese caso DEBE conservar el título completo.

    Ojo: core_departments.name guarda el nombre CORTO; el largo con
    «Departamento de …» vive en la columna `description` y aquí nunca se ve.
    """
    if not title or not department_name:
        return title
    n_title, n_dept = _norm(title), _norm(department_name)
    if not n_dept or not n_title.endswith(n_dept):
        return title

    words = title.split()
    kept = words[: max(0, len(words) - len(n_dept.split()))]
    while kept and _norm(kept[-1]).rstrip(".") in _TITLE_CONNECTORS:
        kept.pop()
    result = " ".join(kept).strip(" ,.;:")
    return result if len(result) >= 3 else title


def _position_holders(db: Session, position_ids) -> dict[int, dict]:
    """{position_id: {user_id, full_name, email, holders_count}} en UNA query.

    Sustituye el N+1 de 2 queries por puesto (103 en total, 344ms en frío).

    Dos detalles que NO son negociables:
    - El ORDER BY debe EMPEZAR por la expresión del DISTINCT ON o Postgres aborta
      con "SELECT DISTINCT ON expressions must match initial ORDER BY expressions".
    - holders_count usa count(UserPosition.id) y particiona por Position.id. Con
      count(*) un puesto sin ocupante reportaría 1, y particionando por
      UserPosition.position_id todos los puestos sin ocupante caerían en una
      única partición NULL.
    """
    from sqlalchemy import func
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.core.models.user import User
    from itcj2.core.services.departments_service import _active_position_window

    if not position_ids:
        return {}

    holders_count = func.count(UserPosition.id).over(partition_by=Position.id)
    rows = (
        db.query(
            Position.id.label("position_id"),
            User.id.label("user_id"),
            # NO concatenar first+last: User.full_name es hybrid_property con
            # .expression y rinde "Apellido [Materno] Nombre", que es el orden que
            # esta misma columna ya mostraba y el que usa todo el sistema.
            User.full_name.label("full_name"),
            User.email.label("user_email"),
            holders_count.label("holders_count"),
        )
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(User, User.id == UserPosition.user_id)
        .filter(Position.id.in_(position_ids), _active_position_window())
        .distinct(Position.id)
        .order_by(Position.id, UserPosition.start_date.asc(), UserPosition.user_id.asc())
        .all()
    )
    return {
        r.position_id: {
            "user_id": r.user_id,
            "full_name": r.full_name or "",
            "email": r.user_email,
            "holders_count": int(r.holders_count or 0),
        }
        for r in rows
    }


def _resolve_email(position, holder):
    """(email, email_source) — fail-closed.

    El correo del puesto gana siempre. El del ocupante solo se publica si el
    puesto es unipersonal Y tiene exactamente un ocupante vigente: la invariante
    "1 ocupante por puesto no múltiple" NO la garantiza la base (los DML insertan
    core_user_positions directo, sin pasar por assign_user_to_position).
    """
    if position.email:
        return position.email, "position"
    if holder and position.allows_multiple is False:
        if holder["holders_count"] == 1:
            return (holder["email"], "holder") if holder["email"] else ("", "")
        logger.warning(
            "puesto %s no permite múltiples pero tiene %s ocupantes vigentes: "
            "sin correo de respaldo",
            position.id, holder["holders_count"],
        )
    return "", ""


def _position_row(position, holder):
    dept_name = position.department.name if position.department else "—"
    email, email_source = _resolve_email(position, holder)
    rank = _position_rank(position)
    return {
        "source": "position",
        "department_id": position.department_id,
        "department": dept_name,
        "title": position.title,
        "short_title": short_title(position.title, dept_name),
        "rank": rank,
        "holder": (holder or {}).get("full_name", ""),
        "extension": position.phone_extension or "",
        "email": email,
        "email_source": email_source,
        "notes": position.phone_notes or "",
        "position_id": position.id,
        "entry_id": None,
        "is_head": rank == "head",
    }


def _entry_row(entry):
    return {
        "source": "entry",
        "department_id": entry.department_id,
        "department": entry.department.name if entry.department else "—",
        "title": entry.label,
        "short_title": entry.label,
        "rank": "other",
        "holder": entry.holder_name or "",
        "extension": entry.extension,
        "email": entry.email or "",
        "email_source": "entry" if entry.email else "",
        "notes": entry.notes or "",
        "position_id": entry.position_id,
        "entry_id": entry.id,
        "is_head": False,
    }


def group_by_department(rows, dept_meta, *, include_empty_unofficial: bool = False):
    """Agrupa filas iterando el ESQUELETO, no las filas.

    Antes los grupos se derivaban de las filas, así que un departamento sin filas
    no podía aparecer nunca — y eso es justo lo que hace falta para que quien
    captura vea el hueco donde meter la extensión de un depto no oficial recién
    hecho visible.

    Los oficiales vacíos siguen sin aparecer. Dentro de cada grupo: jefe primero,
    luego secretaría, luego el resto, y a igualdad por extensión.
    """
    by_dept: dict = {}
    for r in rows:
        by_dept.setdefault(r["department_id"], []).append(r)

    out = []
    for meta in dept_meta:
        group_rows = sorted(
            by_dept.get(meta["id"], []),
            key=lambda x: (_RANK_ORDER.get(x.get("rank", "other"), 2), x["extension"]),
        )
        if not group_rows and not (include_empty_unofficial and not meta["is_official"]):
            continue
        out.append({
            "department_id": meta["id"],
            "department": meta["name"],
            "is_official": meta["is_official"],
            "depth": meta["depth"],
            "ancestors": meta["ancestors"],
            "rows": group_rows,
        })
    return out


def list_directory(db: Session, *, q=None, department_id=None, source="all",
                   include_unofficial: bool, include_empty_unofficial: bool = False):
    """Lista unificada agrupada por departamento, en orden jerárquico.

    `include_unofficial` es keyword OBLIGATORIO y sin default a propósito: un call
    site olvidado revienta con TypeError en el test, mientras que un default
    degradaría en silencio al comportamiento viejo.

    Este módulo NO conoce settings_service: el ajuste se resuelve una sola vez por
    request, en la capa de pages.
    """
    from itcj2.core.models.position import Position
    from itcj2.apps.directory.models import DirectoryEntry

    depts = department_rows(db, include_unofficial=include_unofficial)
    dept_ids = {d["id"] for d in depts}

    # Rescate por filtro explícito: el ajuste gobierna la vista POR DEFECTO, pero
    # un departamento pedido a mano nunca se descarta. Sin esto, las filas de un
    # depto oculto quedan inalcanzables para quien tiene que editarlas.
    if department_id and department_id not in dept_ids:
        rescued = [d for d in department_rows(db, include_unofficial=True)
                   if d["id"] == department_id]
        if rescued:
            depts = depts + rescued
            dept_ids.add(department_id)

    if department_id:
        depts = [d for d in depts if d["id"] == department_id]

    rows = []
    if source in ("all", "position"):
        pos_query = db.query(Position).filter(
            Position.phone_extension.isnot(None),
            Position.is_active == True,  # noqa: E712
        )
        if department_id:
            pos_query = pos_query.filter(Position.department_id == department_id)
        positions = pos_query.all()
        holders = _position_holders(db, [p.id for p in positions])
        rows.extend(_position_row(p, holders.get(p.id)) for p in positions)

    if source in ("all", "entry"):
        ent_query = db.query(DirectoryEntry).filter(DirectoryEntry.is_active == True)  # noqa: E712
        if department_id:
            ent_query = ent_query.filter(DirectoryEntry.department_id == department_id)
        rows.extend(_entry_row(e) for e in ent_query.all())

    if q:
        ql = q.strip().lower()
        rows = [
            r for r in rows
            if ql in (
                f"{r['title']} {r['holder']} {r['extension']} {r['email']} "
                f"{r['notes']} {r['department']}"
            ).lower()
        ]

    # Un grupo fantasma solo tiene sentido en la vista SIN filtrar: si no,
    # `{% if not groups %}` («Sin resultados») se vuelve inalcanzable y una
    # búsqueda sin coincidencias imprimiría todas las cabeceras con contador 0.
    filtered = bool(q) or bool(department_id) or source != "all"
    return group_by_department(
        rows, depts, include_empty_unofficial=include_empty_unofficial and not filtered
    )


# ── Escritura ────────────────────────────────────────────────────────────────
def _clean(value, field):
    """strip -> None si queda vacío, con cota de longitud.

    Hoy nadie acotaba: 11 caracteres en la extensión daban DataError/500.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _MAX[field]:
        raise ValueError(f"El campo «{field}» admite máximo {_MAX[field]} caracteres")
    return text


def _clean_email(value):
    from itcj2.core.utils.email_tools import is_valid_email
    cleaned = _clean(value, "email")
    if cleaned and not is_valid_email(cleaned):
        raise ValueError(f"«{cleaned}» no es un correo válido")
    return cleaned


def _require_visible_department(db, department_id):
    from itcj2.core.models.department import Department
    dept = db.get(Department, department_id)
    if not dept or not dept.is_active:
        raise ValueError(f"El departamento {department_id} no existe o está inactivo")
    return dept


def set_position_contact(db: Session, position_id, *, extension, notes, email=_KEEP):
    """Escribe extensión, notas y correo del puesto en core_positions (fuente única).

    El correo se valida y se comprueba contra el índice UNIQUE en el servicio de
    core, para que /itcj/config y el directorio compartan una sola regla.

    `email` lleva centinela y no None porque en este dominio ""/None significan
    BORRAR el correo, así que el wrapper de compatibilidad no tendría otra forma
    de decir «consérvalo».
    """
    from sqlalchemy.exc import IntegrityError
    from itcj2.core.models.position import Position
    from itcj2.core.services.positions_service import validate_position_email

    pos = db.get(Position, position_id)
    if not pos:
        raise ValueError(f"El puesto {position_id} no existe")

    pos.phone_extension = _clean(extension, "extension")
    pos.phone_notes = _clean(notes, "notes")
    if email is not _KEEP:
        pos.email = validate_position_email(db, email, exclude_position_id=position_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("El correo ya está asignado a otro puesto")
    db.refresh(pos)
    return pos


def set_position_extension(db: Session, position_id, extension, notes, by_user_id):
    """Wrapper de compatibilidad (5 posicionales). NO escribe ni revalida el correo."""
    return set_position_contact(db, position_id, extension=extension, notes=notes)


def create_entry(db: Session, *, department_id, label, extension, position_id=None,
                 holder_name=None, notes=None, email=None, by_user_id=None):
    from itcj2.apps.directory.models import DirectoryEntry

    _require_visible_department(db, department_id)
    entry = DirectoryEntry(
        department_id=department_id,
        position_id=position_id,
        label=_clean(label, "label"),
        holder_name=_clean(holder_name, "holder_name"),
        extension=_clean(extension, "extension"),
        notes=_clean(notes, "notes"),
        email=_clean_email(email),
        created_by_id=by_user_id,
    )
    if not entry.label:
        raise ValueError("La etiqueta es obligatoria")
    if not entry.extension:
        raise ValueError("La extensión es obligatoria")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_entry(db: Session, entry_id, *, label=None, extension=None, position_id=None,
                 holder_name=None, notes=None, department_id=None, email=None):
    from itcj2.apps.directory.models import DirectoryEntry

    entry = db.get(DirectoryEntry, entry_id)
    if not entry:
        raise ValueError(f"La entrada {entry_id} no existe")
    if label is not None:
        entry.label = _clean(label, "label")
        if not entry.label:
            raise ValueError("La etiqueta es obligatoria")
    if extension is not None:
        entry.extension = _clean(extension, "extension")
        if not entry.extension:
            raise ValueError("La extensión es obligatoria")
    if holder_name is not None:
        entry.holder_name = _clean(holder_name, "holder_name")
    if notes is not None:
        entry.notes = _clean(notes, "notes")
    # El modal SIEMPRE manda el campo, así que "" significa borrar el correo.
    if email is not None:
        entry.email = _clean_email(email)
    if position_id is not None:
        entry.position_id = position_id
    if department_id is not None:
        _require_visible_department(db, department_id)
        entry.department_id = department_id
    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry_id):
    from itcj2.apps.directory.models import DirectoryEntry
    entry = db.get(DirectoryEntry, entry_id)
    if not entry:
        raise ValueError(f"La entrada {entry_id} no existe")
    db.delete(entry)
    db.commit()

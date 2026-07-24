"""Lógica del directorio de extensiones (unifica puestos + extras)."""
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def official_departments(db: Session) -> list[dict]:
    """Deptos OFICIALES activos en orden jerárquico (DFS preorden), con `depth` del árbol completo.

    Reusa el árbol ya calculado en departments_service (contrato C3); solo filtra
    los no-oficiales, preservando el orden relativo del recorrido del árbol.
    """
    from itcj2.core.services.departments_service import list_parent_options
    return [d for d in list_parent_options(db) if d["is_official"]]


def official_department_order(db: Session) -> dict[int, int]:
    """{department_id: índice} — orden jerárquico de deptos oficiales."""
    return {d["id"]: i for i, d in enumerate(official_departments(db))}


# Puestos legacy que NO siguen la convención head_{dept.code} y no se pueden
# renombrar sin tocar el approval chain de bajas de inventario en helpdesk
# (AWAITING_DIRECTOR/AWAITING_SUBDIRECTOR — ver database/DML/core/config_2026_07/
# subtree/03_fix_subdirector_head_codes.sql para el detalle y los otros 2 que
# sí se renombraron).
_LEGACY_HEAD_CODES = {"director", "subdirector_admin_services"}


def _is_head_position(position) -> bool:
    """True si `position` es el jefe de su departamento (code == head_{dept.code})."""
    dept = position.department
    if not dept:
        return False
    return position.code == f"head_{dept.code}" or position.code in _LEGACY_HEAD_CODES


def _position_row(position, holder_name):
    return {
        "source": "position",
        "department_id": position.department_id,
        "department": position.department.name if position.department else "—",
        "title": position.title,
        "holder": holder_name or "",
        "extension": position.phone_extension or "",
        "notes": position.phone_notes or "",
        "position_id": position.id,
        "entry_id": None,
        "is_head": _is_head_position(position),
    }


def _entry_row(entry):
    return {
        "source": "entry",
        "department_id": entry.department_id,
        "department": entry.department.name if entry.department else "—",
        "title": entry.label,
        "holder": entry.holder_name or "",
        "extension": entry.extension,
        "notes": entry.notes or "",
        "position_id": entry.position_id,
        "entry_id": entry.id,
        "is_head": False,
    }


def group_by_department(rows, dept_order: dict[int, int]):
    """Agrupa filas por departamento OFICIAL, en orden jerárquico.

    Descarta filas de deptos no-oficiales (o sin depto). Dentro de cada grupo,
    el puesto de jefe del depto (`is_head`) va primero; el resto ordenado por
    extensión.
    """
    groups = {}
    for r in rows:
        dep_id = r["department_id"]
        if dep_id not in dept_order:
            continue
        groups.setdefault((dep_id, r["department"]), []).append(r)
    out = []
    for (dep_id, dep_name) in sorted(groups, key=lambda k: dept_order[k[0]]):
        group_rows = sorted(
            groups[(dep_id, dep_name)],
            key=lambda x: (0 if x["is_head"] else 1, x["extension"]),
        )
        out.append({"department_id": dep_id, "department": dep_name, "rows": group_rows})
    return out


def list_directory(db: Session, *, q=None, department_id=None, source="all"):
    """Lista unificada agrupada por departamento oficial, en orden jerárquico."""
    from itcj2.core.models.position import Position, UserPosition
    from itcj2.apps.directory.models import DirectoryEntry

    depts = official_departments(db)
    dept_order = {d["id"]: i for i, d in enumerate(depts)}
    dept_depth = {d["id"]: d["depth"] for d in depts}
    rows = []

    if source in ("all", "position"):
        pos_query = db.query(Position).filter(
            Position.phone_extension.isnot(None),
            Position.is_active == True,  # noqa: E712
        )
        if department_id:
            pos_query = pos_query.filter(Position.department_id == department_id)
        for pos in pos_query.all():
            assignment = (
                db.query(UserPosition)
                .filter_by(position_id=pos.id, is_active=True)
                .first()
            )
            holder = ""
            if assignment and assignment.user:
                holder = assignment.user.full_name
            rows.append(_position_row(pos, holder))

    if source in ("all", "entry"):
        ent_query = db.query(DirectoryEntry).filter(DirectoryEntry.is_active == True)  # noqa: E712
        if department_id:
            ent_query = ent_query.filter(DirectoryEntry.department_id == department_id)
        for ent in ent_query.all():
            rows.append(_entry_row(ent))

    if q:
        ql = q.strip().lower()
        rows = [
            r for r in rows
            if ql in f"{r['title']} {r['holder']} {r['extension']} {r['notes']} {r['department']}".lower()
        ]

    groups = group_by_department(rows, dept_order)
    for g in groups:
        g["depth"] = dept_depth.get(g["department_id"], 0)
    return groups


def set_position_extension(db: Session, position_id, extension, notes, by_user_id):
    """Escribe la extensión/notas de un puesto en core_positions (fuente única)."""
    from itcj2.core.models.position import Position
    pos = db.get(Position, position_id)
    if not pos:
        raise ValueError(f"El puesto {position_id} no existe")
    pos.phone_extension = (extension or "").strip() or None
    pos.phone_notes = (notes or "").strip() or None
    db.commit()
    db.refresh(pos)
    return pos


def create_entry(db: Session, *, department_id, label, extension, position_id=None, holder_name=None, notes=None, by_user_id=None):
    from itcj2.core.models.department import Department
    from itcj2.apps.directory.models import DirectoryEntry
    if not db.get(Department, department_id):
        raise ValueError(f"El departamento {department_id} no existe")
    entry = DirectoryEntry(
        department_id=department_id,
        position_id=position_id,
        label=(label or "").strip(),
        holder_name=(holder_name or "").strip() or None,
        extension=(extension or "").strip(),
        notes=(notes or "").strip() or None,
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


def update_entry(db: Session, entry_id, *, label=None, extension=None, position_id=None, holder_name=None, notes=None, department_id=None):
    from itcj2.apps.directory.models import DirectoryEntry
    entry = db.get(DirectoryEntry, entry_id)
    if not entry:
        raise ValueError(f"La entrada {entry_id} no existe")
    if label is not None:
        entry.label = label.strip()
    if extension is not None:
        entry.extension = extension.strip()
    if holder_name is not None:
        entry.holder_name = holder_name.strip() or None
    if notes is not None:
        entry.notes = notes.strip() or None
    if position_id is not None:
        entry.position_id = position_id
    if department_id is not None:
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

"""Páginas del Directorio de Extensiones (HTMX, sin recarga)."""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_login, require_perms
from itcj2.apps.directory.pages.render import render_directory
# settings_service va a NIVEL DE MÓDULO (no import local) porque los tests lo
# parchean como `...pages.directory.settings_service.*`: mock hace getattr sobre
# este módulo y, si falla, intenta importarlo como módulo y revienta en el propio
# decorador. No importa nada de apps/, así que no hay riesgo circular.
from itcj2.apps.directory.services import directory_service, settings_service
from itcj2.core.services.positions_service import (
    PositionEmailConflict, PositionEmailInvalid,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_MANAGE_PERM = "directory.entries.api.manage"
_SETTINGS_PERM = "directory.settings.api.manage"

_MANAGE = require_perms("directory", [_MANAGE_PERM])
_SETTINGS = require_perms("directory", [_SETTINGS_PERM])

_NBSP = "  "   # sangría real: el <option> colapsa los espacios ASCII



def _is_student(user: dict) -> bool:
    """Los alumnos traen 'cn' (número de control) en el JWT — igual que el redirect raíz."""
    return bool(user.get("cn"))


def _dir_error(resp, message: str, field: str | None = None):
    """Pone el error de dominio en los headers, percent-encoded (ASCII puro).

    Starlette codifica los headers en latin-1, asi que un em dash lanza
    UnicodeEncodeError y convierte un error de dominio en un 500 — y la app ya usa
    «—» en su propia copy. Sanear a latin-1 arregla el 500 pero deja bytes altos
    que el cliente no puede decodificar como UTF-8, asi que se percent-encodea:
    ASCII puro, sin perder acentos. El JS lo pasa por decodeURIComponent.
    """
    text = message or "Ocurrió un error."
    resp.headers["X-Dir-Error"] = quote(text, safe="")
    if field:
        resp.headers["X-Dir-Field"] = field
    return resp


def _view_flags(db: Session, user: dict) -> dict:
    """Permisos + ajuste global, resueltos UNA vez por request.

    Pasa por authz_cache (Redis, TTL 300s) en vez de golpear la BD: la lectura del
    directorio no pide permiso, así que los cientos de usuarios de staff que nunca
    tendrán `manage` pagaban ~18-20 queries en CADA render, incluido cada tecleo
    del buscador. Los admins nunca lo pagaron (bypass antes de la query).

    Se consulta también has_assignment porque require_perms comprueba las dos
    cosas: mirar solo permisos daría un can_manage optimista frente al 403 real.
    """
    from itcj2.core.services import authz_cache

    is_admin = user.get("role") == "admin"
    perms: set = set()
    if not is_admin:
        try:
            uid = int(user["sub"])
            if authz_cache.cached_has_assignment(db, uid, "directory"):
                perms = authz_cache.cached_perms(db, uid, "directory")
        except Exception:
            logger.exception("error computing view flags for user %s", user.get("sub"))

    can_manage = is_admin or _MANAGE_PERM in perms
    show = settings_service.show_unofficial(db)
    return {
        "can_manage": can_manage,
        "can_settings": is_admin or _SETTINGS_PERM in perms,
        "show_unofficial": show,
        "include_empty_unofficial": show and can_manage,
    }


def _dept_label(db: Session, department_id):
    """Nombre del departamento filtrado, para el copy del estado vacío."""
    if not department_id:
        return None
    from itcj2.core.models.department import Department
    dept = db.get(Department, department_id)
    return dept.name if dept else None


def _hidden_departments_with_rows(db: Session, *, exclude_ids):
    """Deptos NO visibles que ya tienen filas: mismo predicado que `list_directory`.

    «Tiene filas» = puesto activo con phone_extension, o entrada activa. Con otro
    predicado el <select> ofrecería departamentos que la lista no pinta.
    """
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import Position
    from itcj2.apps.directory.models import DirectoryEntry

    with_positions = db.query(Position.department_id).filter(
        Position.is_active.is_(True), Position.phone_extension.isnot(None)
    )
    with_entries = db.query(DirectoryEntry.department_id).filter(
        DirectoryEntry.is_active.is_(True)
    )
    return (
        db.query(Department)
        .filter(
            Department.is_active.is_(True),
            Department.id.notin_(exclude_ids or {-1}),
            Department.id.in_(with_positions.union(with_entries)),
        )
        .order_by(Department.name)
        .all()
    )


def _departments(db: Session, *, include_unofficial: bool, can_manage: bool):
    """Opciones de los <select>. `dir_label` lleva la sangría con NBSP real.

    A quien gestiona se le añaden, AL FINAL y marcados «(oculto)», los no oficiales
    que YA tienen filas: es la ruta de rescate del invariante de alcanzabilidad.
    Van al final y aplanados —no intercalados— porque su `depth` viene del
    esqueleto COMPLETO y el de los visibles del esqueleto RENDERIZADO: mezclarlos
    descuadraría la sangría de cualquier oficial recolgado.
    """
    from itcj2.core.models.department import Department

    meta = directory_service.department_rows(db, include_unofficial=include_unofficial)
    visible_ids = {m["id"] for m in meta}
    by_id = {
        d.id: d
        for d in db.query(Department).filter(Department.id.in_(visible_ids or {-1})).all()
    }

    out = []
    for m in meta:
        dept = by_id.get(m["id"])
        if not dept:
            continue
        dept.dir_label = f"{_NBSP * m['depth']}{m['name']}"
        out.append(dept)

    if can_manage:
        for dept in _hidden_departments_with_rows(db, exclude_ids=visible_ids):
            dept.dir_label = f"{dept.name} (oculto)"
            out.append(dept)
    return out


def _dept_options(db: Session, flags: dict) -> dict:
    """Los DOS conjuntos de <option>, siempre juntos y desde un solo sitio.

    `departments`       -> select de FILTRO: visibles + ocultos-con-filas si gestiona.
    `entry_departments` -> select de ALTA: SOLO visibles. Con el toggle apagado no
                           debe poder crearse nada nuevo en un departamento oculto.
    """
    return {
        "departments": _departments(
            db, include_unofficial=flags["show_unofficial"], can_manage=flags["can_manage"]
        ),
        "entry_departments": _departments(
            db, include_unofficial=flags["show_unofficial"], can_manage=False
        ),
    }


def _render_list(request: Request, db: Session, user: dict, *, q=None, department_id=None,
                 source="all", extra=None, template="directory/partials/dir_list.html"):
    flags = _view_flags(db, user)
    groups = directory_service.list_directory(
        db, q=q, department_id=department_id, source=source,
        include_unofficial=flags["show_unofficial"],
        include_empty_unofficial=flags["include_empty_unofficial"],
    )
    ctx = {
        "groups": groups,
        "q": q or "",
        "filter_dept": department_id,
        "effective_filter_dept": department_id,
        "source": source,
        "dept_label": _dept_label(db, department_id),
        "hidden_count": settings_service.hidden_row_count(db) if flags["can_settings"] else 0,
        **flags,
        **(extra or {}),
    }
    # Condición INVERTIDA a propósito: solo el parcial desnudo de cada búsqueda se
    # ahorra los <select>. Cualquier template que PINTE los controles los necesita;
    # con una lista blanca, el siguiente template que los monte volvería a caer en
    # el mismo hueco silencioso.
    if not template.endswith("partials/dir_list.html"):
        ctx.update(_dept_options(db, flags))
    return render_directory(request, template, ctx)


def _form_email(value):
    """Normaliza el correo que llega del formulario.

    GOTCHA VERIFICADO: con `str | None = Form(None)` un campo vacio llega como
    None, no como "" — FastAPI aplica el default cuando el valor es vacio, y pasa
    igual con el cuerpo crudo del navegador. Como los dos modales SIEMPRE mandan
    el campo, aqui None significa «el usuario lo dejo vacio» = borrar, y por eso
    se convierte a "": los servicios distinguen None («no tocar») de "" («borrar»).
    """
    return value or ""


def _int_or_none(value):
    return int(value) if value else None


# ── Vistas (gate de página: login + no-estudiante) ───────────────────────────
@router.get("/")
async def index(request: Request, user: dict = Depends(require_page_login),
                db: Session = Depends(get_db)):
    if _is_student(user):
        return RedirectResponse("/itcj/m/", status_code=302)
    # Mismo contexto que el parcial, por construcción: si index() lo armara aparte,
    # cada clave nueva del contrato volvería a quedarse fuera en silencio.
    return _render_list(request, db, user, template="directory/index.html")


@router.get("/list")
async def list_partial(
    request: Request,
    q: str = "",
    filter_dept: str | None = None,
    source: str = "all",
    user: dict = Depends(require_page_login),
    db: Session = Depends(get_db),
):
    if _is_student(user):
        return RedirectResponse("/itcj/m/", status_code=302)
    return _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)


# ── Edición (gate require_perms manage; admin bypasea) ────────────────────────
def _fail(request, db, user, exc, *, q, filter_dept, source):
    """Error de dominio: 200 + partial re-renderizado + X-Dir-Error.

    El rollback va ANTES de re-renderizar: es la misma Session y sin él el
    re-render heredaría la transacción abortada.
    """
    db.rollback()
    resp = _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)
    field = "email" if isinstance(exc, (PositionEmailConflict, PositionEmailInvalid)) else None
    return _dir_error(resp, str(exc), field)


@router.post("/entries")
async def create_entry(
    request: Request,
    department_id: int = Form(...),
    label: str = Form(...),
    extension: str = Form(...),
    position_id: int | None = Form(None),
    holder_name: str | None = Form(None),
    notes: str | None = Form(None),
    email: str | None = Form(None),
    q: str = Form(""),
    filter_dept: str | None = Form(None),
    source: str = Form("all"),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.create_entry(
            db, department_id=department_id, label=label, extension=extension,
            position_id=position_id, holder_name=holder_name, notes=notes,
            email=_form_email(email), by_user_id=int(user["sub"]),
        )
    except (PositionEmailConflict, PositionEmailInvalid, ValueError, IntegrityError) as exc:
        return _fail(request, db, user, exc, q=q, filter_dept=filter_dept, source=source)
    return _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    request: Request,
    label: str | None = Form(None),
    extension: str | None = Form(None),
    position_id: int | None = Form(None),
    holder_name: str | None = Form(None),
    notes: str | None = Form(None),
    email: str | None = Form(None),
    department_id: int | None = Form(None),
    q: str = Form(""),
    filter_dept: str | None = Form(None),
    source: str = Form("all"),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.update_entry(
            db, entry_id, label=label, extension=extension, position_id=position_id,
            holder_name=holder_name, notes=notes, department_id=department_id,
            email=_form_email(email),
        )
    except (PositionEmailConflict, PositionEmailInvalid, ValueError, IntegrityError) as exc:
        return _fail(request, db, user, exc, q=q, filter_dept=filter_dept, source=source)
    return _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: int,
    request: Request,
    q: str = Form(""),
    filter_dept: str | None = Form(None),
    source: str = Form("all"),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.delete_entry(db, entry_id)
    except (ValueError, IntegrityError) as exc:
        return _fail(request, db, user, exc, q=q, filter_dept=filter_dept, source=source)
    return _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)


@router.patch("/positions/{position_id}/extension")
async def patch_position_extension(
    position_id: int,
    request: Request,
    extension: str | None = Form(None),
    notes: str | None = Form(None),
    email: str | None = Form(None),
    q: str = Form(""),
    filter_dept: str | None = Form(None),
    source: str = Form("all"),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    """Extensión, notas y correo del puesto. La ruta conserva su nombre histórico
    (la consumen index.js y los tests) aunque ahora también escriba el correo."""
    try:
        directory_service.set_position_contact(
            db, position_id, extension=extension, notes=notes, email=_form_email(email),
        )
    except (PositionEmailConflict, PositionEmailInvalid, ValueError, IntegrityError) as exc:
        return _fail(request, db, user, exc, q=q, filter_dept=filter_dept, source=source)
    return _render_list(request, db, user, q=(q or None),
                        department_id=_int_or_none(filter_dept), source=source)


# ── Ajuste global (gate propio: settings, NO entries) ─────────────────────────
@router.post("/settings/unofficial")
async def set_unofficial_visibility(
    request: Request,
    show_unofficial: str = Form(...),
    q: str = Form(""),
    filter_dept: str | None = Form(None),
    source: str = Form("all"),
    user: dict = _SETTINGS,
    db: Session = Depends(get_db),
):
    """Estado DESEADO explícito, nunca 'lee e invierte'.

    Un toggle ciego no es idempotente: dos admins, un doble clic o un reintento de
    htmx dejan el valor equivocado.
    """
    desired = str(show_unofficial).lower() in ("true", "1", "on", "yes")
    settings_service.set_show_unofficial(db, desired, by_user_id=int(user["sub"]))

    dept = _int_or_none(filter_dept)
    warning = None
    if dept is not None:
        visible = {
            d["id"] for d in directory_service.department_rows(db, include_unofficial=desired)
        }
        if dept not in visible:
            # Sin esto el usuario aterriza en «Sin resultados» con un filtro que ya
            # no puede ver ni quitar.
            dept = None
            warning = "Se limpió el filtro: el departamento ya no es visible"

    resp = _render_list(
        request, db, user, q=(q or None), department_id=dept, source=source,
        template="directory/partials/dir_list_with_sync.html",
    )
    return _dir_error(resp, warning) if warning else resp

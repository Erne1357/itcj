"""Páginas del Directorio de Extensiones (HTMX, sin recarga)."""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_login, require_perms
from itcj2.apps.directory.pages.render import render_directory
from itcj2.apps.directory.services import directory_service

logger = logging.getLogger(__name__)

router = APIRouter()

_MANAGE = require_perms("directory", ["directory.entries.api.manage"])


def _is_student(user: dict) -> bool:
    """Los alumnos traen 'cn' (número de control) en el JWT — igual que el redirect raíz."""
    return bool(user.get("cn"))


def _can_manage(db: Session, user: dict) -> bool:
    if user.get("role") == "admin":
        return True
    from itcj2.core.services.authz_service import get_user_permissions_for_app
    try:
        perms = get_user_permissions_for_app(db, int(user["sub"]), "directory")
    except Exception:
        return False
    return "directory.entries.api.manage" in perms


def _departments(db: Session):
    from itcj2.core.models.department import Department
    return db.query(Department).filter_by(is_active=True).order_by(Department.name).all()


def _render_list(request: Request, db: Session, user: dict, *, q=None, department_id=None, source="all"):
    groups = directory_service.list_directory(db, q=q, department_id=department_id, source=source)
    ctx = {"groups": groups, "can_manage": _can_manage(db, user)}
    return render_directory(request, "directory/partials/dir_list.html", ctx)


# ── Vistas (gate de página: login + no-estudiante) ───────────────────────────
@router.get("/")
async def index(request: Request, user: dict = Depends(require_page_login), db: Session = Depends(get_db)):
    if _is_student(user):
        return RedirectResponse("/itcj/m/", status_code=302)
    groups = directory_service.list_directory(db)
    ctx = {
        "groups": groups,
        "can_manage": _can_manage(db, user),
        "departments": _departments(db),
    }
    return render_directory(request, "directory/index.html", ctx)


@router.get("/list")
async def list_partial(
    request: Request,
    q: str = "",
    department_id: int | None = None,
    source: str = "all",
    user: dict = Depends(require_page_login),
    db: Session = Depends(get_db),
):
    if _is_student(user):
        return RedirectResponse("/itcj/m/", status_code=302)
    return _render_list(request, db, user, q=(q or None), department_id=department_id, source=source)


# ── Edición (gate require_perms manage; admin bypasea) ────────────────────────
@router.post("/entries")
async def create_entry(
    request: Request,
    department_id: int = Form(...),
    label: str = Form(...),
    extension: str = Form(...),
    position_id: int | None = Form(None),
    holder_name: str | None = Form(None),
    notes: str | None = Form(None),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.create_entry(
            db, department_id=department_id, label=label, extension=extension,
            position_id=position_id, holder_name=holder_name, notes=notes,
            by_user_id=int(user["sub"]),
        )
    except ValueError as exc:
        resp = _render_list(request, db, user)
        resp.headers["X-Dir-Error"] = str(exc)
        return resp
    return _render_list(request, db, user)


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    request: Request,
    label: str | None = Form(None),
    extension: str | None = Form(None),
    position_id: int | None = Form(None),
    holder_name: str | None = Form(None),
    notes: str | None = Form(None),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.update_entry(
            db, entry_id, label=label, extension=extension,
            position_id=position_id, holder_name=holder_name, notes=notes,
        )
    except ValueError as exc:
        resp = _render_list(request, db, user)
        resp.headers["X-Dir-Error"] = str(exc)
        return resp
    return _render_list(request, db, user)


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int, request: Request, user: dict = _MANAGE, db: Session = Depends(get_db)):
    try:
        directory_service.delete_entry(db, entry_id)
    except ValueError as exc:
        resp = _render_list(request, db, user)
        resp.headers["X-Dir-Error"] = str(exc)
        return resp
    return _render_list(request, db, user)


@router.patch("/positions/{position_id}/extension")
async def patch_position_extension(
    position_id: int,
    request: Request,
    extension: str | None = Form(None),
    notes: str | None = Form(None),
    user: dict = _MANAGE,
    db: Session = Depends(get_db),
):
    try:
        directory_service.set_position_extension(db, position_id, extension, notes, int(user["sub"]))
    except ValueError as exc:
        resp = _render_list(request, db, user)
        resp.headers["X-Dir-Error"] = str(exc)
        return resp
    return _render_list(request, db, user)

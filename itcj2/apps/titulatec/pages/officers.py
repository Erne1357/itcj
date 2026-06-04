"""Gestión de Encargados (Servicios Escolares): usuarios + carreras por carrera."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.officers")
router = APIRouter(prefix="/admin/officers", tags=["titulatec-pages-officers"])

ROLE_ASSIGNED = "titulatec_school_services"  # rol que reciben los encargados


def _managed_department_id(user_id: int) -> int | None:
    from itcj2.core.services import positions_service
    from itcj2.database import SessionLocal
    with SessionLocal() as db:
        managed = positions_service.get_user_primary_managed_department(db, user_id)
    # returns dict with nested "department" key: {"department": {"id": ...}, "position": {...}, ...}
    return managed["department"]["id"] if managed else None


def _body_ctx(db, department_id: int) -> dict:
    from itcj2.apps.titulatec.services.officer_service import OfficerService
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    return {
        "officers": OfficerService.list_officers(db, department_id),
        "dept_users": [
            {"id": uid, "name": db.get(User, uid).full_name}
            for uid in sorted(OfficerService.department_user_ids(db, department_id))
        ],
        "programs": [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()],
    }


@router.get("", name="titulatec.pages.officers.home")
async def home(request: Request,
               user: dict = Depends(require_page_app("titulatec", perms=["titulatec.officers.page.list"]))):
    from itcj2.database import SessionLocal
    dep = _managed_department_id(int(user["sub"]))
    if dep is None:
        return render_titulatec(request, "titulatec/admin/officers.html", {"no_department": True})
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, dep)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/officers.html", ctx)


@router.post("", name="titulatec.pages.officers.create")
async def create(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=["titulatec.officers.api.manage"]))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.officer_service import OfficerService
    form = await request.form()
    name = (form.get("name") or "").strip()
    program_ids = {int(x) for x in form.getlist("program_ids") if x}
    user_ids = {int(x) for x in form.getlist("user_ids") if x}
    dep = _managed_department_id(int(user["sub"]))
    if dep is None or not name:
        return Response(status_code=400, headers={"X-Tt-Error": "Faltan datos o departamento."})
    db = SessionLocal()
    try:
        try:
            OfficerService.create_officer(db, department_id=dep, assigned_role=ROLE_ASSIGNED,
                                          name=name, program_ids=program_ids, user_ids=user_ids)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": str(exc)})
        ctx = _body_ctx(db, dep)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/officers_body.html", ctx)


@router.post("/{position_id}", name="titulatec.pages.officers.update")
async def update(position_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=["titulatec.officers.api.manage"]))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.officer_service import OfficerService
    form = await request.form()
    program_ids = {int(x) for x in form.getlist("program_ids") if x}
    user_ids = {int(x) for x in form.getlist("user_ids") if x}
    dep = _managed_department_id(int(user["sub"]))
    db = SessionLocal()
    try:
        try:
            OfficerService.set_users(db, position_id, user_ids, department_id=dep, assigned_role=ROLE_ASSIGNED)
            OfficerService.set_programs(db, position_id, program_ids)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": str(exc)})
        ctx = _body_ctx(db, dep)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/officers_body.html", ctx)


@router.post("/{position_id}/deactivate", name="titulatec.pages.officers.deactivate")
async def deactivate(position_id: int, request: Request,
                     user: dict = Depends(require_page_app("titulatec", perms=["titulatec.officers.api.manage"]))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.officer_service import OfficerService
    dep = _managed_department_id(int(user["sub"]))
    db = SessionLocal()
    try:
        OfficerService.deactivate_officer(db, position_id)
        ctx = _body_ctx(db, dep)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/officers_body.html", ctx)

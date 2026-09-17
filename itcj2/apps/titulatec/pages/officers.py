"""Gestión de Encargados (Servicios Escolares): usuarios + carreras por carrera."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.officers")
router = APIRouter(prefix="/admin/officers", tags=["titulatec-pages-officers"])

ROLE_ASSIGNED = "titulatec_school_services"  # rol que reciben los encargados


_DEPT_CODE_SCHOOL_SERVICES = "school_services"


def _managed_department_id(user_id: int) -> int | None:
    """Departamento que el usuario gestiona, con respaldo para el rol admin.

    Via normal: jefe con puesto `head_%`/`subdirector_%`/`director`
    (`positions_service.get_user_primary_managed_department`). El usuario con
    el rol `admin` EN TITULATEC (no el admin global del JWT: `require_page_app`
    no lo bypasea, CLAUDE.md raiz §6) puede no tener NINGUN puesto -- es el caso
    del usuario `admin` de bootstrap -- y sin este respaldo la pestana
    Encargados le queda inutilizable ("sin departamento"). Se le asigna
    Servicios Escolares (`core_departments.code = 'school_services'`), dueno
    real de esta pestana.
    Tener SOLO `titulatec.officers.api.manage` NO activa este respaldo: hace
    falta el rol `admin` en la app. Sin esa distincion,
    `test_officers_authz.py::test_sin_departamento_gestionado_no_muta` y
    `..._no_desactiva` (actor con esos permisos pero sin departamento) se
    romperian, porque mutarian sobre Servicios Escolares en vez de seguir
    devolviendo 400 sin escribir nada.
    """
    from itcj2.core.services import positions_service
    from itcj2.database import SessionLocal
    with SessionLocal() as db:
        managed = positions_service.get_user_primary_managed_department(db, user_id)
        if managed is not None:
            # dict con "department" anidado: {"department": {"id": ...}, "position": {...}, ...}
            return managed["department"]["id"]

        from itcj2.core.services.authz_service import user_roles_in_app
        if "admin" not in user_roles_in_app(db, user_id, "titulatec"):
            return None

        from itcj2.core.models.department import Department
        dept = db.query(Department).filter_by(code=_DEPT_CODE_SCHOOL_SERVICES).first()
        return dept.id if dept else None


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
    if dep is None:
        return Response(status_code=400, headers={"X-Tt-Error": "No gestionas ningun departamento."})
    db = SessionLocal()
    try:
        # Conjunto B (propio), NO el amplio: `set_users`/`set_programs` escriben
        # sobre `core_positions`, compartida con las demas apps del organigrama.
        # Un puesto compartido del mismo depto (secretaria, jefatura, division)
        # cumple el conjunto amplio y la UI no lo lista: colgarle carreras amplia
        # en silencio el alcance de su ocupante, y colgarle usuarios les arrastra
        # sus `PositionAppRole` en TODAS las apps.
        # 404 y no 403: fuera del alcance del jefe no confirmamos que el id exista.
        if OfficerService.get_owned_position(db, position_id, dep) is None:
            return Response(status_code=404)
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
    if dep is None:
        return Response(status_code=400, headers={"X-Tt-Error": "No gestionas ningun departamento."})
    db = SessionLocal()
    try:
        # Conjunto B: solo puestos que ESTA app creo. `deactivate_position` toca
        # `core_positions`, compartida con las demas apps del organigrama.
        if OfficerService.get_owned_position(db, position_id, dep) is None:
            return Response(status_code=404)
        OfficerService.deactivate_officer(db, position_id)
        ctx = _body_ctx(db, dep)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/officers_body.html", ctx)

"""
Páginas del módulo de inventario de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/inventory.py.

Rutas:
  GET /help-desk/inventory/dashboard              → Dashboard de inventario
  GET /help-desk/inventory/items                  → Lista de equipos
  GET /help-desk/inventory/items/create           → Formulario de registro
  GET /help-desk/inventory/items/{id}             → Detalle de equipo
  GET /help-desk/inventory/my-equipment           → Equipos del usuario actual
  GET /help-desk/inventory/assign                 → Asignación de equipos
  GET /help-desk/inventory/reports/warranty       → Reporte de garantías
  GET /help-desk/inventory/reports/maintenance    → Reporte de mantenimientos
  GET /help-desk/inventory/reports/lifecycle      → Reporte de ciclo de vida
  GET /help-desk/inventory/groups                 → Lista de grupos
  GET /help-desk/inventory/groups/{id}            → Detalle de grupo
  GET /help-desk/inventory/pending                → Equipos pendientes
  GET /help-desk/inventory/bulk-register          → Registro masivo
  GET /help-desk/inventory/retirement-requests    → Solicitudes de baja
  GET /help-desk/inventory/retirement-requests/create → Nueva solicitud de baja
  GET /help-desk/inventory/retirement-requests/{id}   → Detalle de solicitud de baja
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.inventory")

router = APIRouter(prefix="/inventory", tags=["helpdesk-pages-inventory"])

# Dependencia para cualquier usuario con acceso a helpdesk (sin permiso específico)
_require_helpdesk = require_page_app("helpdesk")


def _helpdesk_roles(user_id: int) -> set:
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        return user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()


@router.get("/dashboard", name="helpdesk.pages.inventory.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.page.list"])),
):
    """Dashboard principal de inventario: estadísticas, alertas y actividad reciente."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/dashboard.html", {
        "user_roles": user_roles,
        "active_page": "inventory_dashboard",
    })


@router.get("/items", name="helpdesk.pages.inventory.items_list")
async def items_list(
    request: Request,
    user: dict = Depends(_require_helpdesk),
):
    """Lista de equipos del inventario (admin/secretaría: todos; jefe depto: su depto)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/items/items_list.html", {
        "user_roles": user_roles,
        "can_view_all": can_view_all,
        "active_page": "inventory_items",
    })


@router.get("/items/create", name="helpdesk.pages.inventory.item_create")
async def item_create(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.create"])),
):
    """Formulario para registrar nuevo equipo."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/items/item_create.html", {
        "user_roles": user_roles,
        "active_page": "inventory_items",
    })


@router.get("/items/{item_id}", name="helpdesk.pages.inventory.item_detail")
async def item_detail(
    request: Request,
    item_id: int,
    user: dict = Depends(_require_helpdesk),
):
    """Detalle completo de un equipo con historial."""
    from itcj2.core.services.authz_service import _get_users_with_position
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        current_user = _db.get(User, user_id)
        current_dept = current_user.get_current_department() if current_user else None
        is_comp_center = current_dept and (current_dept.code == 'comp_center' or current_dept.name == 'CENTRO DE COMPUTO')

        secretary_comp_center_ids = _get_users_with_position(_db, ["secretary_comp_center"])
    finally:
        _db.close()

    can_edit = (
        "admin" in user_roles
        or "tech_soporte" in user_roles
        or "tech_desarrollo" in user_roles
        or user_id in secretary_comp_center_ids
        or is_comp_center
    )

    return render_helpdesk(request, "helpdesk/inventory/items/item_detail.html", {
        "item_id": item_id,
        "user_roles": user_roles,
        "can_edit": can_edit,
        "is_admin": "admin" in user_roles,
        "active_page": "inventory_items",
    })


@router.get("/my-equipment", name="helpdesk.pages.inventory.my_equipment")
async def my_equipment(
    request: Request,
    user: dict = Depends(_require_helpdesk),
):
    """Equipos asignados al usuario actual (solo lectura)."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/assignment/my_equipment.html", {
        "user_roles": user_roles,
        "active_page": "inventory_my_equipment",
    })


@router.get("/assign", name="helpdesk.pages.inventory.assign_equipment")
async def assign_equipment(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.assign"])),
):
    """Interfaz para asignar equipos a usuarios."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/assignment/assign_equipment.html", {
        "user_roles": user_roles,
        "active_page": "inventory_assign",
    })


@router.get("/groups", name="helpdesk.pages.inventory.groups_list")
async def groups_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory_groups.page.list"])),
):
    """Lista de grupos de equipos (salones, laboratorios)."""
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    _db = SessionLocal()
    try:
        user_dept = get_user_department(_db, user_id)
        department_id = user_dept.id if user_dept else None
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/groups/groups_list.html", {
        "user_roles": user_roles,
        "can_view_all": can_view_all,
        "department_id": department_id,
        "active_page": "inventory_groups",
    })


@router.get("/groups/{group_id}", name="helpdesk.pages.inventory.group_detail")
async def group_detail(
    request: Request,
    group_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory_groups.page.list"])),
):
    """Detalle de un grupo con sus equipos."""
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    _db = SessionLocal()
    try:
        user_dept = get_user_department(_db, user_id)
        department_id = user_dept.id if user_dept else None
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/groups/group_detail.html", {
        "group_id": group_id,
        "user_roles": user_roles,
        "department_id": department_id,
        "active_page": "inventory_groups",
    })


@router.get("/pending", name="helpdesk.pages.inventory.pending_items")
async def pending_items(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.pending"])),
):
    """Equipos pendientes de asignación (limbo del Centro de Cómputo)."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/items/pending_items.html", {
        "user_roles": user_roles,
        "active_page": "inventory_pending",
    })


@router.get("/bulk-register", name="helpdesk.pages.inventory.bulk_register")
async def bulk_register(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.bulk.create"])),
):
    """Registro masivo de equipos (mismo template que item_create con bulk_mode=True)."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/items/item_create.html", {
        "bulk_mode": True,
        "user_roles": user_roles,
        "active_page": "inventory_items",
    })


@router.get("/reports", name="helpdesk.pages.inventory.reports")
async def reports(
    request: Request,
    tab: str = "equipos",
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """
    Página unificada de reportes de inventario.
    Acepta ?tab=equipos|movimientos|garantias|mantenimiento|ciclo-vida|verificacion
    """
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/reports/reports.html", {
        "user_roles": user_roles,
        "active_page": "inventory_reports",
        "active_tab": tab,
    })


@router.get("/reports/warranty", name="helpdesk.pages.inventory.warranty_report")
async def warranty_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Redirige a /reports?tab=garantias."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/help-desk/inventory/reports?tab=garantias", status_code=302)


@router.get("/reports/maintenance", name="helpdesk.pages.inventory.maintenance_report")
async def maintenance_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Redirige a /reports?tab=mantenimiento."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/help-desk/inventory/reports?tab=mantenimiento", status_code=302)


@router.get("/reports/lifecycle", name="helpdesk.pages.inventory.lifecycle_report")
async def lifecycle_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Redirige a /reports?tab=ciclo-vida."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/help-desk/inventory/reports?tab=ciclo-vida", status_code=302)


@router.get("/reports/verification", name="helpdesk.pages.inventory.verification_report")
async def verification_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.page.verification"])),
):
    """Redirige a /reports?tab=verificacion."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/help-desk/inventory/reports?tab=verificacion", status_code=302)


@router.get("/campaigns", name="helpdesk.pages.inventory.campaigns_list")
async def campaigns_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.campaign.page.list"])),
):
    """Lista de campañas de inventario (CC/Admin/Jefe de dpto)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access
    from itcj2.core.services.departments_service import get_user_department

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
        user_dept = get_user_department(_db, user_id) if "department_head" in user_roles else None
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/campaigns/campaigns_list.html", {
        "user_roles": user_roles,
        "can_view_all": can_view_all,
        "can_create": "admin" in user_roles or can_view_all,
        "user_dept_id": user_dept.id if user_dept else None,
        "active_page": "inventory_campaigns",
    })


@router.get("/campaigns/create", name="helpdesk.pages.inventory.campaign_create")
async def campaign_create(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.campaign.api.create"])),
):
    """Formulario para crear una nueva campaña de inventario."""
    from itcj2.database import SessionLocal
    from itcj2.core.models.department import Department
    from itcj2.core.models.academic_period import AcademicPeriod

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        departments = (
            _db.query(Department)
            .filter_by(is_active=True)
            .order_by(Department.name)
            .all()
        )
        periods = (
            _db.query(AcademicPeriod)
            .filter(AcademicPeriod.status != "ARCHIVED")
            .order_by(AcademicPeriod.start_date.desc())
            .all()
        )
        departments_data = [{"id": d.id, "name": d.name, "code": d.code} for d in departments]
        periods_data = [{"id": p.id, "name": p.name} for p in periods]
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/campaigns/campaign_create.html", {
        "user_roles": user_roles,
        "departments": departments_data,
        "periods": periods_data,
        "active_page": "inventory_campaigns",
    })


@router.get("/campaigns/{campaign_id}/validate", name="helpdesk.pages.inventory.campaign_validate")
async def campaign_validate(
    request: Request,
    campaign_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.campaign.api.validate"])),
):
    """Vista de validación del jefe de departamento."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/campaigns/campaign_validate.html", {
        "campaign_id": campaign_id,
        "user_roles": user_roles,
        "active_page": "inventory_campaigns",
    })


@router.get("/campaigns/{campaign_id}", name="helpdesk.pages.inventory.campaign_detail")
async def campaign_detail(
    request: Request,
    campaign_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.campaign.page.list"])),
):
    """Detalle completo de una campaña de inventario."""
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        can_manage = has_full_inventory_access(_db, user_id, user_roles)
        can_validate = "department_head" in user_roles
        is_admin = "admin" in user_roles
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/campaigns/campaign_detail.html", {
        "campaign_id": campaign_id,
        "user_roles": user_roles,
        "can_manage": can_manage,
        "can_validate": can_validate,
        "is_admin": is_admin,
        "active_page": "inventory_campaigns",
    })


@router.get("/retirement-requests", name="helpdesk.pages.inventory.retirement_requests_list")
async def retirement_requests_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.retirement.page.list"])),
):
    """Lista de solicitudes de baja del inventario."""
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
        can_approve = "admin" in user_roles
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/retirement/retirement_requests_list.html", {
        "user_roles": user_roles,
        "can_view_all": can_view_all,
        "can_approve": can_approve,
        "active_page": "inventory_retirement_requests",
    })


@router.get("/retirement-requests/create", name="helpdesk.pages.inventory.retirement_request_create")
async def retirement_request_create(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.retirement.page.create"])),
):
    """Formulario para crear nueva solicitud de baja."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/retirement/retirement_request_create.html", {
        "user_roles": user_roles,
        "active_page": "inventory_retirement_requests",
    })


@router.get("/retirement-requests/{request_id}", name="helpdesk.pages.inventory.retirement_request_detail")
async def retirement_request_detail(
    request: Request,
    request_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.retirement.page.detail"])),
):
    """Detalle de una solicitud de baja."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_service import _get_users_with_position

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    can_approve = "admin" in user_roles

    _db = SessionLocal()
    try:
        mat_ids = {u.id for u in _get_users_with_position(_db, ["head_mat_services"])}
        sub_ids = {u.id for u in _get_users_with_position(_db, ["secretary_sub_admin_services"])}
        dir_ids = {u.id for u in _get_users_with_position(_db, ["director"])}
    finally:
        _db.close()

    sign_perms = []
    if user_id in mat_ids:
        sign_perms.append("helpdesk.retirement.sign.recursos_materiales")
    if user_id in sub_ids:
        sign_perms.append("helpdesk.retirement.sign.subdirector")
    if user_id in dir_ids:
        sign_perms.append("helpdesk.retirement.sign.director")

    return render_helpdesk(request, "helpdesk/inventory/retirement/retirement_request_detail.html", {
        "request_id": request_id,
        "user_roles": user_roles,
        "can_approve": can_approve,
        "sign_perms": sign_perms,
        "active_page": "inventory_retirement_requests",
    })


@router.get("/verification", name="helpdesk.pages.inventory.verification")
async def verification(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.page.verification"])),
):
    """
    Página de verificación física de inventario.
    Solo Admin y Secretaría del Centro de Cómputo.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
        from itcj2.core.models.department import Department
        departments = (
            _db.query(Department)
            .filter_by(is_active=True)
            .order_by(Department.name)
            .all()
        )
        departments_data = [{"id": d.id, "name": d.name} for d in departments]
    finally:
        _db.close()

    return render_helpdesk(request, "helpdesk/inventory/reports/verification.html", {
        "user_roles": user_roles,
        "can_view_all": can_view_all,
        "departments": departments_data,
        "active_page": "inventory_verification",
    })

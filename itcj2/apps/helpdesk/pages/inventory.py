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
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    can_view_all = "admin" in user_roles or "secretary" in user_roles

    return render_helpdesk(request, "helpdesk/inventory/items_list.html", {
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

    return render_helpdesk(request, "helpdesk/inventory/item_create.html", {
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
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    _db = SessionLocal()
    try:
        secretary_comp_center = _get_users_with_position(_db, ["secretary_comp_center"])
    finally:
        _db.close()
    can_edit = (
        "admin" in user_roles
        or "tech_soporte" in user_roles
        or "tech_desarrollo" in user_roles
        or user_id in secretary_comp_center
    )

    return render_helpdesk(request, "helpdesk/inventory/item_detail.html", {
        "item_id": item_id,
        "user_roles": user_roles,
        "can_edit": can_edit,
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

    return render_helpdesk(request, "helpdesk/inventory/my_equipment.html", {
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

    return render_helpdesk(request, "helpdesk/inventory/assign_equipment.html", {
        "user_roles": user_roles,
        "active_page": "inventory_assign",
    })


@router.get("/reports/warranty", name="helpdesk.pages.inventory.warranty_report")
async def warranty_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Reporte de garantías de equipos."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/reports/warranty.html", {
        "user_roles": user_roles,
        "active_page": "inventory_reports",
    })


@router.get("/reports/maintenance", name="helpdesk.pages.inventory.maintenance_report")
async def maintenance_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Reporte de mantenimientos."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/reports/maintenance.html", {
        "user_roles": user_roles,
        "active_page": "inventory_reports",
    })


@router.get("/reports/lifecycle", name="helpdesk.pages.inventory.lifecycle_report")
async def lifecycle_report(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.stats"])),
):
    """Reporte de ciclo de vida (antigüedad) de equipos."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/inventory/reports/lifecycle.html", {
        "user_roles": user_roles,
        "active_page": "inventory_reports",
    })


@router.get("/groups", name="helpdesk.pages.inventory.groups_list")
async def groups_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory_groups.page.list"])),
):
    """Lista de grupos de equipos (salones, laboratorios)."""
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

    return render_helpdesk(request, "helpdesk/inventory/groups_list.html", {
        "user_roles": user_roles,
        "can_view_all": "admin" in user_roles,
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

    return render_helpdesk(request, "helpdesk/inventory/group_detail.html", {
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

    return render_helpdesk(request, "helpdesk/inventory/pending_items.html", {
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

    return render_helpdesk(request, "helpdesk/inventory/item_create.html", {
        "bulk_mode": True,
        "user_roles": user_roles,
        "active_page": "inventory_items",
    })

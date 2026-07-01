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


# Estados de equipo (fuente única para el filtro server-side). El color de cada
# estado lo dan clases de Bootstrap en el fragmento; aquí solo etiquetas.
_ITEM_STATUS_OPTIONS = [
    ("", "Todos"),
    ("ACTIVE", "Activo"),
    ("MAINTENANCE", "Mantenim."),
    ("DAMAGED", "Dañado"),
    ("LOST", "Extraviado"),
]
_ITEM_ASSIGNED_OPTIONS = [
    ("", "Todos"),
    ("yes", "Asignados"),
    ("no", "Globales"),
]


def _query_items_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta la lista de equipos del inventario para la vista.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search/category/status/assigned/department)
    server-side y pagina. El scope replica EXACTAMENTE el del endpoint API
    ``GET /inventory/items``: acceso completo = admin / técnicos / secretaría CC /
    usuario del Centro de Cómputo; jefe de depto = solo su departamento; el resto
    solo ve los equipos que tiene asignados (o un depto explícito).
    """
    from sqlalchemy import or_

    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
    from itcj2.apps.helpdesk.utils.inventory_access import (
        has_full_inventory_access,
        is_comp_center_user,
    )
    from itcj2.core.models.department import Department
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.database import SessionLocal

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    category = (p.get("category", "") or "").strip() or None
    status = (p.get("status", "") or "").strip() or None
    assigned = (p.get("assigned", "") or "").strip() or None
    dept_param = (p.get("department", "") or "").strip() or None
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    _db = SessionLocal()
    try:
        can_view_all = (
            has_full_inventory_access(_db, user_id, user_roles)
            or is_comp_center_user(_db, user_id)
        )
        user_dept = get_user_department(_db, user_id)
        user_dept_id = user_dept.id if user_dept else None

        q = _db.query(InventoryItem).filter_by(is_active=True)
        if can_view_all:
            if dept_param and dept_param.isdigit():
                q = q.filter(InventoryItem.department_id == int(dept_param))
        elif "department_head" in user_roles:
            q = q.filter(InventoryItem.department_id == (user_dept_id or -1))
        elif dept_param and dept_param.isdigit():
            q = q.filter(InventoryItem.department_id == int(dept_param))
        else:
            q = q.filter(InventoryItem.assigned_to_user_id == user_id)

        if category and category.isdigit():
            q = q.filter(InventoryItem.category_id == int(category))
        if status:
            q = q.filter(InventoryItem.status == status.upper())
        if assigned == "yes":
            q = q.filter(InventoryItem.assigned_to_user_id.isnot(None))
        elif assigned == "no":
            q = q.filter(InventoryItem.assigned_to_user_id.is_(None))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                InventoryItem.inventory_number.ilike(like),
                InventoryItem.brand.ilike(like),
                InventoryItem.model.ilike(like),
                InventoryItem.supplier_serial.ilike(like),
                InventoryItem.itcj_serial.ilike(like),
                InventoryItem.id_tecnm.ilike(like),
            ))

        q = q.order_by(InventoryItem.id.asc())
        total = q.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        items = (
            q.offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        items_data = [i.to_dict(include_relations=True) for i in items]

        categories = (
            _db.query(InventoryCategory)
            .filter_by(is_active=True)
            .order_by(InventoryCategory.name)
            .all()
        )
        categories_data = [{"id": c.id, "name": c.name} for c in categories]

        if can_view_all:
            departments = (
                _db.query(Department)
                .filter_by(is_active=True)
                .order_by(Department.name)
                .all()
            )
            departments_data = [{"id": d.id, "name": d.name} for d in departments]
        else:
            departments_data = []
    finally:
        _db.close()

    return {
        "items": items_data,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "showing_from": (page - 1) * per_page + 1 if total else 0,
        "showing_to": min(page * per_page, total),
        "can_view_all": can_view_all,
        "categories": categories_data,
        "departments": departments_data,
        "f_search": search or "",
        "f_category": category or "",
        "f_status": status or "",
        "f_assigned": assigned or "",
        "f_department": dept_param or "",
    }


@router.get("/items", name="helpdesk.pages.inventory.items_list")
async def items_list(
    request: Request,
    user: dict = Depends(_require_helpdesk),
):
    """Lista de equipos del inventario (admin/secretaría: todos; jefe depto: su depto).

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-items-results) + contador OOB.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_items_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/inventory/items/_items_list_results.html", ctx)

    # Campos de la barra de filtros (macro filter_bar). El de departamento solo
    # aparece si el usuario ve todos los departamentos.
    category_options = [("", "Todas")] + [
        (str(c["id"]), c["name"]) for c in ctx["categories"]
    ]
    filter_fields = [{
        "name": "category", "label": "Categoría", "icon": "fa-tag",
        "col": "col-6 col-md-3", "selected": ctx["f_category"], "options": category_options,
    }, {
        "name": "status", "label": "Estado", "icon": "fa-toggle-on",
        "col": "col-6 col-md-2", "selected": ctx["f_status"], "options": _ITEM_STATUS_OPTIONS,
    }, {
        "name": "assigned", "label": "Asignación", "icon": "fa-user",
        "col": "col-6 col-md-2", "selected": ctx["f_assigned"], "options": _ITEM_ASSIGNED_OPTIONS,
    }]
    if ctx["can_view_all"]:
        dept_options = [("", "Todos los deptos.")] + [
            (str(d["id"]), d["name"]) for d in ctx["departments"]
        ]
        filter_fields.append({
            "name": "department", "label": "Depto.", "icon": "fa-building",
            "col": "col-6 col-md-2", "selected": ctx["f_department"], "options": dept_options,
        })

    ctx.update({
        "user_roles": user_roles,
        "active_page": "inventory_items",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/inventory/items/items_list.html", ctx)


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


# Tipos de grupo (fuente única, reusada por el filtro server-side). Los colores
# son clases semánticas de Bootstrap (paleta azul; el color lo dan las clases,
# nunca hex). El fragmento _groups_list_results.html tiene su propio mapa de
# icono/etiqueta para pintar cada tarjeta.
_GROUP_TYPE_OPTIONS = [
    ("", "Todos tipos"),
    ("CLASSROOM", "Salón"),
    ("LABORATORY", "Laboratorio"),
    ("OFFICE", "Oficina"),
    ("MEETING_ROOM", "Sala"),
    ("WORKSHOP", "Taller"),
    ("OTHER", "Otro"),
]


def _query_groups_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta la lista de grupos para la vista de inventario.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search/type/department) server-side y pagina.
    El scope (todos los grupos vs. solo los del depto del usuario) replica el del
    endpoint API de grupos: acceso completo = admin/técnicos/secretaría CC.
    """
    from sqlalchemy import or_

    from itcj2.apps.helpdesk.models import InventoryGroup
    from itcj2.apps.helpdesk.utils.inventory_access import has_full_inventory_access
    from itcj2.core.models.department import Department
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.database import SessionLocal

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    gtype = (p.get("type", "") or "").strip() or None
    dept_param = (p.get("department", "") or "").strip() or None
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    per_page = 24

    _db = SessionLocal()
    try:
        can_view_all = has_full_inventory_access(_db, user_id, user_roles)
        user_dept = get_user_department(_db, user_id)
        user_dept_id = user_dept.id if user_dept else None

        q = _db.query(InventoryGroup).filter_by(is_active=True)
        if can_view_all:
            if dept_param and dept_param.isdigit():
                q = q.filter(InventoryGroup.department_id == int(dept_param))
        else:
            # Sin acceso global: solo grupos de su departamento (o ninguno).
            q = q.filter(InventoryGroup.department_id == (user_dept_id or -1))

        if gtype:
            q = q.filter(InventoryGroup.group_type == gtype)
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                InventoryGroup.name.ilike(like),
                InventoryGroup.code.ilike(like),
                InventoryGroup.description.ilike(like),
            ))

        total = q.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        groups = (
            q.order_by(InventoryGroup.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        groups_data = [g.to_dict(include_capacities=True) for g in groups]

        # Departamentos: para el filtro (solo si ve todos) y para el select del modal.
        if can_view_all:
            departments = (
                _db.query(Department)
                .filter_by(is_active=True)
                .order_by(Department.name)
                .all()
            )
        else:
            departments = [user_dept] if user_dept else []
        departments_data = [{"id": d.id, "name": d.name} for d in departments]
    finally:
        _db.close()

    return {
        "groups": groups_data,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "can_view_all": can_view_all,
        "department_id": user_dept_id,
        "departments": departments_data,
        "f_search": search or "",
        "f_type": gtype or "",
        "f_department": dept_param or "",
    }


@router.get("/groups", name="helpdesk.pages.inventory.groups_list")
async def groups_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory_groups.page.list"])),
):
    """Lista de grupos de equipos (salones, laboratorios).

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (grid server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-groups-results) + contador OOB.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_groups_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/inventory/groups/_groups_list_results.html", ctx)

    # Campos de la barra de filtros (macro filter_bar). El de departamento solo
    # aparece si el usuario ve todos los departamentos.
    filter_fields = []
    if ctx["can_view_all"]:
        dept_options = [("", "Todos los deptos.")] + [
            (str(d["id"]), d["name"]) for d in ctx["departments"]
        ]
        filter_fields.append({
            "name": "department", "label": "Depto.", "icon": "fa-building",
            "col": "col-6 col-md-3", "selected": ctx["f_department"], "options": dept_options,
        })
    filter_fields.append({
        "name": "type", "label": "Tipo", "icon": "fa-layer-group",
        "col": "col-6 col-md-3", "selected": ctx["f_type"], "options": _GROUP_TYPE_OPTIONS,
    })

    ctx.update({
        "user_roles": user_roles,
        "active_page": "inventory_groups",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/inventory/groups/groups_list.html", ctx)


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


_PENDING_SORT_OPTIONS = [
    ("newest", "Más recientes"),
    ("oldest", "Más antiguos"),
    ("category", "Por categoría"),
]


def _query_pending_ctx(request: Request) -> dict:
    """Consulta los equipos pendientes de asignación (limbo del Centro de Cómputo).

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search/category/sort) server-side y pagina.
    El scope (equipos en estado PENDING_ASSIGNMENT del depto Centro de Cómputo)
    replica el del endpoint API de pendientes.
    """
    from sqlalchemy import or_

    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
    from itcj2.core.models.department import Department
    from itcj2.database import SessionLocal

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    category = (p.get("category", "") or "").strip() or None
    sort = (p.get("sort", "") or "").strip() or "newest"
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    _db = SessionLocal()
    try:
        cc_department = _db.query(Department).filter_by(code="comp_center").first()
        cc_dept_id = cc_department.id if cc_department else -1

        q = _db.query(InventoryItem).filter(
            InventoryItem.status == "PENDING_ASSIGNMENT",
            InventoryItem.department_id == cc_dept_id,
            InventoryItem.is_active.is_(True),
        )
        if category and category.isdigit():
            q = q.filter(InventoryItem.category_id == int(category))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                InventoryItem.inventory_number.ilike(like),
                InventoryItem.brand.ilike(like),
                InventoryItem.model.ilike(like),
                InventoryItem.supplier_serial.ilike(like),
                InventoryItem.itcj_serial.ilike(like),
            ))

        if sort == "oldest":
            q = q.order_by(InventoryItem.created_at.asc())
        elif sort == "category":
            q = q.join(InventoryCategory, InventoryItem.category_id == InventoryCategory.id).order_by(
                InventoryCategory.name.asc(), InventoryItem.created_at.desc()
            )
        else:
            q = q.order_by(InventoryItem.created_at.desc())

        total = q.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        items = (
            q.offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        items_data = [i.to_dict(include_relations=True) for i in items]

        # Total global (sin filtros) y nº de categorías, para las tarjetas de stats.
        stat_total = _db.query(InventoryItem).filter(
            InventoryItem.status == "PENDING_ASSIGNMENT",
            InventoryItem.department_id == cc_dept_id,
            InventoryItem.is_active.is_(True),
        ).count()
        stat_categories = _db.query(InventoryItem.category_id).filter(
            InventoryItem.status == "PENDING_ASSIGNMENT",
            InventoryItem.department_id == cc_dept_id,
            InventoryItem.is_active.is_(True),
        ).distinct().count()

        categories = (
            _db.query(InventoryCategory)
            .filter_by(is_active=True)
            .order_by(InventoryCategory.name)
            .all()
        )
        categories_data = [{"id": c.id, "name": c.name} for c in categories]
    finally:
        _db.close()

    return {
        "items": items_data,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "stat_total": stat_total,
        "stat_categories": stat_categories,
        "categories": categories_data,
        "f_search": search or "",
        "f_category": category or "",
        "f_sort": sort,
    }


@router.get("/pending", name="helpdesk.pages.inventory.pending_items")
async def pending_items(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.read.pending"])),
):
    """Equipos pendientes de asignación (limbo del Centro de Cómputo).

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-pending-results) + contadores OOB.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_pending_ctx(request)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/inventory/items/_pending_items_results.html", ctx)

    category_options = [("", "Todas las categorías")] + [
        (str(c["id"]), c["name"]) for c in ctx["categories"]
    ]
    filter_fields = [{
        "name": "category", "label": "Categoría", "icon": "fa-tag",
        "col": "col-6 col-md-3", "selected": ctx["f_category"], "options": category_options,
    }, {
        "name": "sort", "label": "Orden", "icon": "fa-sort",
        "col": "col-6 col-md-2", "selected": ctx["f_sort"], "options": _PENDING_SORT_OPTIONS,
    }]

    ctx.update({
        "user_roles": user_roles,
        "active_page": "inventory_pending",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/inventory/items/pending_items.html", ctx)


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


# Estados de campaña (fuente única para el filtro server-side). El color de cada
# estado lo dan clases de Bootstrap en el fragmento; aquí solo etiquetas.
_CAMPAIGN_STATUS_OPTIONS = [
    ("", "Todos"),
    ("OPEN", "Abierta"),
    ("PENDING_VALIDATION", "Pendiente validación"),
    ("VALIDATED", "Validada"),
    ("REJECTED", "Rechazada"),
]


def _query_campaigns_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta la lista de campañas de inventario para la vista.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search=folio/status/department) server-side y
    pagina. El scope replica el del endpoint API de campañas: los jefes de
    departamento que NO son admin/Centro de Cómputo ven solo su departamento; el
    resto (admin/CC/técnicos/secretaría CC) ve todas y puede filtrar por depto.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService
    from itcj2.apps.helpdesk.utils.inventory_access import (
        has_full_inventory_access,
        is_comp_center_user,
    )
    from itcj2.core.models.department import Department
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.database import SessionLocal

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    status = (p.get("status", "") or "").strip() or None
    dept_param = (p.get("department", "") or "").strip() or None
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    _db = SessionLocal()
    try:
        full_access = has_full_inventory_access(_db, user_id, user_roles)
        is_admin_or_cc = "admin" in user_roles or is_comp_center_user(_db, user_id)
        # Solo el jefe de depto SIN acceso global queda acotado a su departamento.
        is_dept_head_scoped = "department_head" in user_roles and not is_admin_or_cc
        can_view_all = not is_dept_head_scoped

        forced_dept_id = None
        if is_dept_head_scoped:
            user_dept = get_user_department(_db, user_id)
            forced_dept_id = user_dept.id if user_dept else -1

        filters = {
            "folio": search,
            "status": status,
            "department_id": (
                int(dept_param) if (can_view_all and dept_param and dept_param.isdigit()) else None
            ),
            "page": page,
            "per_page": per_page,
        }
        result = CampaignService.get_campaigns(_db, filters=filters, department_id=forced_dept_id)
        campaigns = result["campaigns"]
        total = result["total"]
        total_pages = max(1, result["total_pages"])

        # Departamentos para el filtro (solo si el usuario ve todos).
        if can_view_all:
            departments = (
                _db.query(Department)
                .filter_by(is_active=True)
                .order_by(Department.name)
                .all()
            )
            departments_data = [{"id": d.id, "name": d.name} for d in departments]
        else:
            departments_data = []
    finally:
        _db.close()

    return {
        "campaigns": campaigns,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "can_view_all": can_view_all,
        "can_create": "admin" in user_roles or full_access,
        "f_search": search or "",
        "f_status": status or "",
        "f_department": dept_param or "",
        "departments": departments_data,
    }


@router.get("/campaigns", name="helpdesk.pages.inventory.campaigns_list")
async def campaigns_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.campaign.page.list"])),
):
    """Lista de campañas de inventario (CC/Admin/Jefe de dpto).

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-campaigns-results) + contador OOB.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_campaigns_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/inventory/campaigns/_campaigns_list_results.html", ctx)

    # Campos de la barra de filtros (macro filter_bar). El de departamento solo
    # aparece si el usuario ve todos los departamentos.
    filter_fields = [{
        "name": "status", "label": "Estado", "icon": "fa-tag",
        "col": "col-6 col-md-3", "selected": ctx["f_status"], "options": _CAMPAIGN_STATUS_OPTIONS,
    }]
    if ctx["can_view_all"]:
        dept_options = [("", "Todos los deptos.")] + [
            (str(d["id"]), d["name"]) for d in ctx["departments"]
        ]
        filter_fields.append({
            "name": "department", "label": "Depto.", "icon": "fa-building",
            "col": "col-6 col-md-3", "selected": ctx["f_department"], "options": dept_options,
        })

    ctx.update({
        "user_roles": user_roles,
        "active_page": "inventory_campaigns",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/inventory/campaigns/campaigns_list.html", ctx)


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


# Estados de solicitud de baja (fuente única para el filtro server-side). El color
# de cada estado lo dan clases de Bootstrap en el fragmento; aquí solo etiquetas.
_RETIREMENT_STATUS_OPTIONS = [
    ("", "Todos"),
    ("DRAFT", "Borrador"),
    ("PENDING", "Pendiente de envío"),
    ("AWAITING_RECURSOS_MATERIALES", "Firma — Rec. Materiales"),
    ("AWAITING_SUBDIRECTOR", "Firma — Subdirector"),
    ("AWAITING_DIRECTOR", "Firma — Director"),
    ("AWAITING_COMP_CENTER", "Autorización — Jefe CC"),
    ("APPROVED", "Aprobada"),
    ("REJECTED", "Rechazada"),
    ("CANCELLED", "Cancelada"),
]
_RETIREMENT_SCOPE_OPTIONS = [("all", "Todas"), ("mine", "Mis solicitudes")]


def _query_retirement_ctx(request: Request, user_id: int) -> dict:
    """Consulta las solicitudes de baja para la vista de inventario.

    Reusada por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento).
    Aplica los filtros de la barra (search/status/scope) server-side y pagina.
    El scope (todas vs. solo las propias) replica el del endpoint API de bajas:
    acceso completo (`_is_admin`) = admin / secretaría CC / usuario del Centro de
    Cómputo; el resto solo ve las suyas.
    """
    from sqlalchemy import func, or_

    from itcj2.apps.helpdesk.api.inventory.retirement_requests import _is_admin
    from itcj2.apps.helpdesk.models.inventory_retirement_request import (
        InventoryRetirementRequest,
        InventoryRetirementRequestItem,
    )
    from itcj2.database import SessionLocal

    p = request.query_params
    search = (p.get("search", "") or "").strip() or None
    status = (p.get("status", "") or "").strip() or None
    scope = (p.get("scope", "") or "").strip() or "all"
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1
    per_page = 20

    _db = SessionLocal()
    try:
        can_view_all = _is_admin(_db, user_id)

        q = _db.query(InventoryRetirementRequest)
        if not can_view_all:
            q = q.filter(InventoryRetirementRequest.requested_by_id == user_id)
            scope = "mine"
        elif scope == "mine":
            q = q.filter(InventoryRetirementRequest.requested_by_id == user_id)

        if status:
            q = q.filter(InventoryRetirementRequest.status == status.upper())
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                InventoryRetirementRequest.folio.ilike(like),
                InventoryRetirementRequest.reason.ilike(like),
            ))

        q = q.order_by(InventoryRetirementRequest.created_at.desc())

        total = q.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        rows = (
            q.offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # Conteo de equipos por solicitud (una sola consulta agrupada para la página).
        req_ids = [r.id for r in rows]
        counts = {}
        if req_ids:
            counts = dict(
                _db.query(
                    InventoryRetirementRequestItem.request_id,
                    func.count(InventoryRetirementRequestItem.id),
                )
                .filter(InventoryRetirementRequestItem.request_id.in_(req_ids))
                .group_by(InventoryRetirementRequestItem.request_id)
                .all()
            )

        requests_data = [{
            "id": r.id,
            "folio": r.folio,
            "status": r.status,
            "reason": r.reason,
            "items_count": counts.get(r.id, 0),
            "requested_by_name": r.requested_by.full_name if r.requested_by else "—",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
    finally:
        _db.close()

    return {
        "requests": requests_data,
        "total": total,
        "current_page": page,
        "total_pages": total_pages,
        "can_view_all": can_view_all,
        "f_search": search or "",
        "f_status": status or "",
        "f_scope": scope,
    }


@router.get("/retirement-requests", name="helpdesk.pages.inventory.retirement_requests_list")
async def retirement_requests_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.retirement.page.list"])),
):
    """Lista de solicitudes de baja del inventario.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa (tabla server-side).
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-retirement-results) + contador OOB.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_retirement_ctx(request, user_id)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/inventory/retirement/_retirement_requests_list_results.html", ctx)

    # Campos de la barra de filtros (macro filter_bar). El de visibilidad solo
    # aparece si el usuario ve todas las solicitudes (no solo las suyas).
    filter_fields = [{
        "name": "status", "label": "Estado", "icon": "fa-tag",
        "col": "col-6 col-md-3", "selected": ctx["f_status"], "options": _RETIREMENT_STATUS_OPTIONS,
    }]
    if ctx["can_view_all"]:
        filter_fields.append({
            "name": "scope", "label": "Visibilidad", "icon": "fa-eye",
            "col": "col-6 col-md-3", "selected": ctx["f_scope"], "options": _RETIREMENT_SCOPE_OPTIONS,
        })

    ctx.update({
        "user_roles": user_roles,
        "can_approve": "admin" in user_roles,
        "active_page": "inventory_retirement_requests",
        "filter_fields": filter_fields,
    })
    return render_helpdesk(request, "helpdesk/inventory/retirement/retirement_requests_list.html", ctx)


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
        mat_ids = set(_get_users_with_position(_db, ["head_mat_services"]))
        sub_ids = set(_get_users_with_position(_db, ["subdirector_admin_services"]))
        dir_ids = set(_get_users_with_position(_db, ["director"]))
        cc_ids  = set(_get_users_with_position(_db, ["head_comp_center"]))
    finally:
        _db.close()

    sign_perms = []
    if user_id in mat_ids:
        sign_perms.append("helpdesk.retirement.sign.recursos_materiales")
    if user_id in sub_ids:
        sign_perms.append("helpdesk.retirement.sign.subdirector")
    if user_id in dir_ids:
        sign_perms.append("helpdesk.retirement.sign.director")
    if user_id in cc_ids:
        sign_perms.append("helpdesk.retirement.sign.comp_center")

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

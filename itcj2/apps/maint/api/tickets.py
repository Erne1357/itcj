"""Tickets API — maint."""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.tickets import (
    CreateTicketRequest,
    UpdateTicketRequest,
    ResolveTicketRequest,
    RateTicketRequest,
    CancelTicketRequest,
    RouteTicketRequest,
)
from itcj2.apps.maint.services import ticket_service
from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

router = APIRouter(tags=["maint-tickets"])
logger = logging.getLogger(__name__)


# ==================== DEPARTAMENTOS DEL SOLICITANTE ====================
@router.get("/my-departments")
async def my_departments(
    user: dict = require_perms("maint", ["maint.tickets.api.create"]),
    db: DbSession = None,
):
    """Lista los departamentos activos del usuario logueado (vía UserPosition).

    Usado por el formulario de creación de ticket para:
      - Si len==1: usar automáticamente sin mostrar selector.
      - Si len>1: mostrar selector obligatorio.
      - Si len==0: dejar nulo (warning UI opcional).
    """
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import UserPosition, Position
    uid = int(user["sub"])
    rows = (
        db.query(Department.id, Department.code, Department.name)
        .join(Position, Position.department_id == Department.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == uid,
            UserPosition.is_active == True,
        )
        .distinct()
        .order_by(Department.name.asc())
        .all()
    )
    return {
        "success": True,
        "data": [{"id": r[0], "code": r[1], "name": r[2]} for r in rows],
    }


# ==================== LISTAR TICKETS ====================
@router.get("")
@router.get("/")
async def list_tickets(
    status: str = None,
    category_id: int = None,
    priority: str = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
    assigned_to: str = None,
    requester: str = None,
    unrated: int = None,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    """Filtros de pestaña: `assigned_to=me` (técnico activo), `requester=me`
    (Mis solicitudes), `unrated=1` (Por calificar: resueltos sin calificación)."""
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "maint")

    result = ticket_service.list_tickets(
        db=db,
        user_id=user_id,
        user_roles=user_roles,
        status=status,
        category_id=category_id,
        priority=priority,
        search=search,
        page=page,
        per_page=per_page,
        assigned_to_me=(assigned_to == "me"),
        requester_me=(requester == "me"),
        unrated=bool(unrated),
    )
    return {
        **{k: v for k, v in result.items() if k != "tickets"},
        "tickets": [ticket_service.serialize_ticket_summary(t) for t in result["tickets"]],
    }


# ==================== CREAR TICKET ====================
@router.post("", status_code=201)
@router.post("/")
async def create_ticket(
    body: CreateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.create"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])

    # --- Determinar solicitante ---
    requester_id = user_id
    department_for_ticket = body.department_id
    if body.requester_id is not None and body.requester_id != user_id:
        # El creador quiere crear en nombre de otro: verificar permiso
        from itcj2.core.services.authz_service import get_user_permissions_for_app
        if user.get("role") != "admin":
            user_perms = get_user_permissions_for_app(db, user_id, "maint", include_positions=True)
            if "maint.tickets.api.create.behalf" not in user_perms:
                raise HTTPException(
                    status_code=403,
                    detail="No tienes permiso para crear solicitudes en nombre de otro usuario",
                )

        # Mantenimiento atiende a TODO el instituto: el solicitante puede ser de
        # cualquier departamento. El depto del ticket se deriva del solicitante
        # (su puesto activo), NO del creador. Pasamos department_id=None para que
        # el service lo resuelva a partir del requester.
        requester_id = body.requester_id
        department_for_ticket = None

    ticket = ticket_service.create_ticket(
        db=db,
        requester_id=requester_id,
        category_id=body.category_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        location=body.location,
        custom_fields=body.custom_fields,
        created_by_id=user_id,
        department_id=department_for_ticket,
    )
    try:
        MaintNotificationHelper.notify_ticket_created(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_created failed for ticket %s: %s", ticket.id, exc)
    return {"ticket_id": ticket.id, "ticket_number": ticket.ticket_number, "due_at": ticket.due_at.isoformat() if ticket.due_at else None}


# ==================== BOARD DE ASIGNACIÓN ====================
@router.get("/board")
async def assignment_board(
    status: str = None,
    area_code: str = None,
    page: int = 1,
    per_page: int = 50,
    user: dict = require_perms("maint", ["maint.assignments.page.list"]),
    db: DbSession = None,
):
    """
    Tablero de asignación para coordinadores.

    Devuelve tickets en estados PENDING / ASSIGNED / IN_PROGRESS con sus técnicos
    activos asignados. Opcionalmente filtra por área (area_code) para mostrar solo
    tickets de la categoría correspondiente al área del coordinador.

    El endpoint se ubica en tickets_router (antes de /{ticket_id}) para evitar que
    FastAPI interprete "board" como un ticket_id entero.
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.services import assignment_service as asgn_svc
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    user_id = int(user["sub"])
    is_global_admin = user.get("role") == "admin"
    user_roles = list(user_roles_in_app(db, user_id, "maint")) if not is_global_admin else ["admin"]

    board_statuses = ["PENDING", "ASSIGNED", "IN_PROGRESS"]
    if status and status in board_statuses:
        filter_statuses: list | str = status
    else:
        filter_statuses = board_statuses

    # Coordinadores (área y general) solo ven sus tickets (coordinator_id == ellos).
    # Admin ve todos.
    coordinator_filter: int | None = None
    if not is_global_admin:
        coord_roles = {"maint_area_coordinator", "maint_general_coordinator"}
        if coord_roles & set(user_roles) and "dispatcher" not in user_roles and "admin" not in user_roles:
            coordinator_filter = user_id

    pagination = ticket_service.list_tickets(
        db=db,
        user_id=user_id,
        user_roles=user_roles,
        status=filter_statuses,
        page=page,
        per_page=per_page,
        coordinator_id=coordinator_filter,
    )

    tickets_data = []
    for ticket in pagination["tickets"]:
        active_technicians = [
            {
                "user_id": t.user_id,
                "assigned_at": t.assigned_at.isoformat() if getattr(t, "assigned_at", None) else None,
            }
            for t in ticket.technicians
            if t.unassigned_at is None
        ]
        coordinator_data = None
        try:
            if ticket.coordinator:
                coordinator_data = {"id": ticket.coordinator.id, "name": ticket.coordinator.full_name}
        except Exception:
            if ticket.coordinator_id:
                coordinator_data = {"id": ticket.coordinator_id, "name": None}

        tickets_data.append({
            "id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "status": ticket.status,
            "priority": ticket.priority,
            "category_code": ticket.category.code if ticket.category else None,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "active_technicians": active_technicians,
            "coordinator": coordinator_data,
        })

    suggested_technicians: list = []
    try:
        if area_code:
            techs = asgn_svc.get_technicians_by_area(db, area_code)
            suggested_technicians = [
                {"user_id": t.id, "name": t.full_name}
                for t in techs
            ]
        elif "maint_area_coordinator" in user_roles:
            coord_areas = CoordinatorService.get_coordinator_areas(db, user_id)
            seen_ids: set[int] = set()
            for ac in coord_areas:
                for t in asgn_svc.get_technicians_by_area(db, ac):
                    if t.id not in seen_ids:
                        seen_ids.add(t.id)
                        suggested_technicians.append({"user_id": t.id, "name": t.full_name, "area": ac})
    except Exception as exc:
        logger.warning("Error calculando sugerencia de técnicos en board: %s", exc)

    return {
        "success": True,
        "data": tickets_data,
        "suggested_technicians": suggested_technicians,
        "total": pagination["total"],
        "page": page,
        "per_page": per_page,
        "total_pages": pagination["pages"],
    }


# ==================== TRIAGE: TICKETS POR ENRUTAR ====================
@router.get("/triage")
async def triage_tickets(
    user: dict = require_perms("maint", ["maint.assignments.page.triage"]),
    db: DbSession = None,
):
    """
    Vista de bandeja de triage para secretaría y coordinadores generales.

    - dispatcher / admin sin rol coordinador: tickets con coordinator_id IS NULL y status PENDING.
    - maint_general_coordinator: unrouted (coordinator_id IS NULL) + mine (coordinator_id == self).
    - admin (global): unrouted = todos coordinator_id IS NULL; mine = [].

    Respuesta: {"success": True, "data": {"unrouted": [...], "mine": [...]}}
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.models.ticket import MaintTicket

    user_id = int(user["sub"])
    is_global_admin = user.get("role") == "admin"
    user_roles = set(user_roles_in_app(db, user_id, "maint"))

    def _serialize_triage_ticket(t: MaintTicket) -> dict:
        coord = None
        try:
            if t.coordinator:
                coord = {"id": t.coordinator.id, "name": t.coordinator.full_name}
        except Exception:
            if t.coordinator_id:
                coord = {"id": t.coordinator_id, "name": None}
        return {
            "id": t.id,
            "ticket_number": t.ticket_number,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "category_code": t.category.code if t.category else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "coordinator": coord,
        }

    # Tickets sin enrutar (coordinator_id IS NULL, status PENDING)
    unrouted_query = (
        db.query(MaintTicket)
        .filter(
            MaintTicket.coordinator_id.is_(None),
            MaintTicket.status == "PENDING",
        )
        .order_by(MaintTicket.created_at.asc())
    )
    unrouted = [_serialize_triage_ticket(t) for t in unrouted_query.all()]

    # Tickets en la cola propia del coordinador
    mine: list = []
    if not is_global_admin and "maint_general_coordinator" in user_roles:
        mine_query = (
            db.query(MaintTicket)
            .filter(
                MaintTicket.coordinator_id == user_id,
                MaintTicket.status.in_(["PENDING", "ASSIGNED", "IN_PROGRESS"]),
            )
            .order_by(MaintTicket.created_at.asc())
        )
        mine = [_serialize_triage_ticket(t) for t in mine_query.all()]

    return {"success": True, "data": {"unrouted": unrouted, "mine": mine}}


# ==================== DESTINOS DE ENRUTADO ====================
@router.get("/route-targets")
async def route_targets(
    user: dict = require_perms("maint", ["maint.assignments.api.route"]),
    db: DbSession = None,
):
    """
    Devuelve los destinos de enrutado válidos según el rol del usuario que consulta:
    - dispatcher: solo coordinadores generales.
    - maint_general_coordinator: coordinadores de área + coordinadores generales.
    - admin: todos (generales + área).

    Respuesta: {"success": True, "data": [...{user_id, name, is_general, areas}...]}
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    user_id = int(user["sub"])
    is_global_admin = user.get("role") == "admin"
    user_roles = set(user_roles_in_app(db, user_id, "maint"))

    if is_global_admin or "admin" in user_roles:
        # Admin ve todos
        coords = CoordinatorService.list_coordinators(db)
    elif "dispatcher" in user_roles:
        # Secretaría solo ve generales
        generals = CoordinatorService.list_general_coordinators(db)
        coords = [{"user_id": c["user_id"], "name": c["name"], "is_general": True, "areas": []} for c in generals]
    elif "maint_general_coordinator" in user_roles:
        # General ve todos (generales + área)
        coords = CoordinatorService.list_coordinators(db)
    elif "maint_area_coordinator" in user_roles:
        # M5: el coordinador de área solo puede DEVOLVER a un coordinador general.
        generals = CoordinatorService.list_general_coordinators(db)
        coords = [{"user_id": c["user_id"], "name": c["name"], "is_general": True, "areas": []} for c in generals]
    else:
        coords = []

    return {"success": True, "data": coords, "total": len(coords)}


# ==================== AUTOCOMPLETE ALMACÉN (resolución) ====================
# Debe ir ANTES de "/{ticket_id}" para que FastAPI no interprete
# "warehouse-products" como un ticket_id entero (causaba 422).
@router.get("/warehouse-products")
async def search_warehouse_products(
    search: str = None,
    limit: int = 20,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    """Autocomplete de productos del almacén para la resolución de tickets."""
    from itcj2.apps.warehouse.services.product_service import get_available_for_autocomplete
    products = get_available_for_autocomplete(db, "equipment_maint", search, min(limit, 50))
    return {"products": products}


# ==================== VER DETALLE ====================
@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)
    return ticket_service.serialize_ticket_detail(ticket)


# ==================== EDITAR TICKET ====================
@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    body: UpdateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.edit"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)

    user_roles = set(user_roles_in_app(db, user_id, "maint"))
    if ticket.requester_id != user_id and not (user_roles & {"admin", "dispatcher"}):
        raise HTTPException(status_code=403, detail="Solo el solicitante puede editar su ticket")

    updated = ticket_service.update_pending_ticket(
        db=db,
        ticket_id=ticket_id,
        updated_by_id=user_id,
        category_id=body.category_id,
        priority=body.priority,
        title=body.title,
        description=body.description,
        location=body.location,
        custom_fields=body.custom_fields,
    )
    return ticket_service.serialize_ticket_summary(updated)


# ==================== ENRUTAR TICKET ====================
@router.post("/{ticket_id}/route")
async def route_ticket(
    ticket_id: int,
    body: RouteTicketRequest,
    user: dict = require_perms("maint", ["maint.assignments.api.route"]),
    db: DbSession = None,
):
    """
    Enruta (o re-enruta) un ticket a un coordinador.
    Secretaría (dispatcher) solo puede enrutar a coordinadores generales.
    Coordinador general puede enrutar a cualquier coordinador o a sí mismo.
    Admin puede enrutar a cualquier coordinador.
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.services.assignment_service import route_ticket as _route

    user_id = int(user["sub"])
    is_global_admin = user.get("role") == "admin"
    performer_roles = set(user_roles_in_app(db, user_id, "maint"))

    try:
        ticket = _route(
            db=db,
            ticket_id=ticket_id,
            target_coordinator_id=body.coordinator_id,
            performed_by_id=user_id,
            performer_roles=performer_roles,
            is_global_admin=is_global_admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error al enrutar ticket %s: %s", ticket_id, e)
        raise HTTPException(status_code=500, detail="Error interno al enrutar ticket")

    # H6: notificar al coordinador destino (in-app + WS a su canal personal).
    try:
        MaintNotificationHelper.notify_ticket_routed(
            db, ticket, ticket.coordinator_id, routed_by_id=user_id
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_routed failed for ticket %s: %s", ticket.id, exc)

    coordinator_data = None
    try:
        if ticket.coordinator:
            coordinator_data = {"id": ticket.coordinator.id, "name": ticket.coordinator.full_name}
    except Exception:
        if ticket.coordinator_id:
            coordinator_data = {"id": ticket.coordinator_id, "name": None}

    return {
        "success": True,
        "message": "Ticket enrutado correctamente",
        "data": {
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "status": ticket.status,
            "coordinator": coordinator_data,
        },
    }


# ==================== INICIAR PROGRESO ====================
@router.post("/{ticket_id}/start")
async def start_ticket(
    ticket_id: int,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = list(user_roles_in_app(db, user_id, "maint"))
    if user.get("role") == "admin" and "admin" not in user_roles:
        user_roles.append("admin")  # M10: admin global (JWT) uniforme en start/resolve/cancel
    ticket = ticket_service.start_progress(db, ticket_id, user_id, user_roles)
    try:
        MaintNotificationHelper.notify_ticket_in_progress(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_in_progress failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}


# ==================== RESOLVER TICKET ====================
@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int,
    body: ResolveTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = set(user_roles_in_app(db, user_id, "maint"))
    if user.get("role") == "admin":
        user_roles.add("admin")  # M10: admin global (JWT) uniforme en start/resolve/cancel

    ticket = ticket_service.get_ticket_by_id(db, ticket_id)

    is_active_tech = any(
        t.user_id == user_id and t.unassigned_at is None
        for t in ticket.technicians
    )
    can_resolve = is_active_tech or bool(user_roles & {'dispatcher', 'admin'})
    if not can_resolve:
        raise HTTPException(
            status_code=403,
            detail="Solo los técnicos asignados o dispatchers pueden resolver tickets",
        )

    # D-F: dispatcher/admin conservan la vía rápida ASSIGNED → RESOLVED;
    # técnicos/coordinadores deben pasar por IN_PROGRESS antes de resolver.
    is_fast_resolver = bool(user_roles & {'dispatcher', 'admin'})

    resolved, warnings = ticket_service.resolve_ticket(
        db=db,
        ticket_id=ticket_id,
        resolved_by_id=user_id,
        success=body.success,
        maintenance_type=body.maintenance_type,
        service_origin=body.service_origin,
        resolution_notes=body.resolution_notes,
        time_invested_minutes=body.time_invested_minutes,
        observations=body.observations,
        materials_used=body.materials_used,
        is_fast_resolver=is_fast_resolver,
    )
    try:
        MaintNotificationHelper.notify_ticket_resolved(db, resolved)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_resolved failed for ticket %s: %s", resolved.id, exc)
    response = {"status": resolved.status, "ticket_number": resolved.ticket_number}
    if warnings:
        response["warnings"] = warnings
    return response


# ==================== MATERIALES DE ALMACÉN ====================
@router.get("/{ticket_id}/materials")
async def get_ticket_materials(
    ticket_id: int,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.ticket_material import WarehouseTicketMaterial
    user_id = int(user["sub"])
    ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)
    materials = (
        db.query(WarehouseTicketMaterial)
        .filter_by(source_app="maint", source_ticket_id=ticket_id)
        .all()
    )
    return {
        "materials": [
            {
                "product_id": m.product_id,
                "product_name": m.product.name if m.product else None,
                "product_unit": m.product.unit_of_measure if m.product else None,
                "quantity_used": str(m.quantity_used),
                "notes": m.notes,
                "added_at": m.added_at.isoformat() if m.added_at else None,
                "added_by": m.added_by.full_name if m.added_by else None,
            }
            for m in materials
        ]
    }




# ==================== CALIFICAR TICKET ====================
@router.post("/{ticket_id}/rate")
async def rate_ticket(
    ticket_id: int,
    body: RateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.rate"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.rate_ticket(
        db=db,
        ticket_id=ticket_id,
        requester_id=user_id,
        rating_attention=body.rating_attention,
        rating_speed=body.rating_speed,
        rating_efficiency=body.rating_efficiency,
        comment=body.comment,
    )
    try:
        MaintNotificationHelper.notify_ticket_rated(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_rated failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}


# ==================== CANCELAR TICKET ====================
@router.post("/{ticket_id}/cancel")
async def cancel_ticket(
    ticket_id: int,
    body: CancelTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.cancel"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = list(user_roles_in_app(db, user_id, "maint"))
    if user.get("role") == "admin" and "admin" not in user_roles:
        user_roles.append("admin")  # M10: admin global (JWT) uniforme en start/resolve/cancel
    ticket = ticket_service.cancel_ticket(
        db=db,
        ticket_id=ticket_id,
        user_id=user_id,
        reason=body.reason,
        user_roles=user_roles,
    )
    try:
        MaintNotificationHelper.notify_ticket_canceled(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_canceled failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}

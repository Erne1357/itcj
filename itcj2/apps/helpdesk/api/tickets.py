"""
Tickets API v2 — 8 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/tickets/base.py
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.tickets import (
    ResolveTicketRequest,
    RateTicketRequest,
    CancelTicketRequest,
    UpdateTicketRequest,
)

router = APIRouter(tags=["helpdesk-tickets"])
logger = logging.getLogger(__name__)


# ==================== CREAR TICKET ====================
@router.post("", status_code=201)
async def create_ticket(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.create"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        data = {}
        for key in form:
            if key in ("photo", "files") or key.startswith("custom_field_"):
                continue
            value = form[key]
            if key in ("category_id", "requester_id"):
                data[key] = int(value) if value else None
            elif key == "inventory_item_ids":
                try:
                    data[key] = json.loads(value)
                except Exception:
                    data[key] = []
            elif key == "custom_fields":
                try:
                    data["custom_fields"] = json.loads(value)
                except Exception:
                    pass
            else:
                data[key] = value

        if "inventory_item_ids[]" in form:
            ids_raw = form.getlist("inventory_item_ids[]")
            data["inventory_item_ids"] = [int(x) for x in ids_raw]

        photo_file = form.get("photo")

        custom_fields = data.get("custom_fields", {})
        custom_field_files = {}
        for key in form:
            if key.startswith("custom_field_") and not key.startswith("custom_field_file_"):
                field_key = key.replace("custom_field_", "")
                custom_fields[field_key] = form[key]
        for key in form:
            if key.startswith("custom_field_") and hasattr(form[key], "read"):
                field_key = key.replace("custom_field_", "")
                custom_field_files[field_key] = form[key]
    else:
        data = await request.json()
        photo_file = None
        custom_fields = data.get("custom_fields", {})
        custom_field_files = {}

    # Validar campos requeridos
    required_fields = ["area", "category_id", "title", "description"]
    missing = [f for f in required_fields if f not in data or not data[f]]
    if missing:
        raise HTTPException(400, detail={
            "error": "missing_fields",
            "message": f'Faltan campos requeridos: {", ".join(missing)}',
        })

    if len(data["title"].strip()) < 5:
        raise HTTPException(400, detail={"error": "invalid_title", "message": "El título debe tener al menos 5 caracteres"})

    if len(data["description"].strip()) < 20:
        raise HTTPException(400, detail={"error": "invalid_description", "message": "La descripción debe tener al menos 20 caracteres"})

    # Validar inventory_item_ids
    inventory_item_ids = data.get("inventory_item_ids", [])
    if inventory_item_ids:
        if not isinstance(inventory_item_ids, list):
            raise HTTPException(400, detail={"error": "invalid_equipment_format", "message": "inventory_item_ids debe ser un array"})

        from itcj2.apps.helpdesk.models import InventoryItem
        for item_id in inventory_item_ids:
            item = db.get(InventoryItem, item_id)
            if not item or not item.is_active:
                raise HTTPException(400, detail={"error": "invalid_equipment", "message": f"El equipo {item_id} no es válido"})

    # Determinar requester_id
    requester_id = data.get("requester_id")
    if requester_id and requester_id != user_id:
        can_create_for_other = False
        if "admin" in user_roles:
            can_create_for_other = True
        else:
            from itcj2.core.models.position import UserPosition
            user_positions = db.query(UserPosition).filter_by(user_id=user_id, is_active=True).all()
            for up in user_positions:
                if up.position and up.position.department and up.position.department.code == "comp_center":
                    can_create_for_other = True
                    break

        if not can_create_for_other:
            raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para crear tickets para otros usuarios"})

        from itcj2.core.models.user import User
        requester = db.get(User, requester_id)
        if not requester or not requester.is_active:
            raise HTTPException(400, detail={"error": "invalid_requester", "message": "El usuario solicitante no es válido"})
    else:
        requester_id = user_id

    # Check tickets sin evaluar
    from itcj2.apps.helpdesk.models.ticket import Ticket
    MAX_UNRATED_TICKETS = 3
    unrated_count = db.query(Ticket).filter(
        Ticket.requester_id == requester_id,
        Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED"]),
        Ticket.rating_attention.is_(None),
    ).count()
    if unrated_count >= MAX_UNRATED_TICKETS:
        raise HTTPException(403, detail={
            "error": "ticket_creation_restricted",
            "message": f"Tienes {unrated_count} tickets sin evaluar. Debes evaluar tus tickets resueltos antes de crear uno nuevo.",
        })

    try:
        ticket = ticket_service.create_ticket(
            requester_id=requester_id,
            area=data["area"],
            category_id=data["category_id"],
            title=data["title"].strip(),
            description=data["description"].strip(),
            priority=data.get("priority", "MEDIA"),
            location=data.get("location"),
            office_folio=data.get("office_folio"),
            inventory_item_ids=inventory_item_ids,
            photo_file=photo_file,
            custom_fields=custom_fields,
            custom_field_files=custom_field_files,
            created_by_id=user_id,
        )

        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {user_id}")

        from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        try:
            HelpdeskNotificationHelper.notify_ticket_created(db, ticket)
            db.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket creado: {notif_error}")

        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_created
            await broadcast_ticket_created({
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "title": ticket.title,
                "area": ticket.area,
                "priority": ticket.priority,
                "status": ticket.status,
                "requester": ticket.requester.full_name if ticket.requester else "Desconocido",
                "department_id": ticket.requester_department_id,
            })
        except Exception as ws_err:
            logger.warning(f"WS broadcast ticket_created error: {ws_err}")

        return {"message": "Ticket creado exitosamente", "ticket": ticket.to_dict(include_relations=True)}

    except Exception as e:
        logger.error(f"Error al crear ticket: {e}")
        raise HTTPException(500, detail={"error": "creation_failed", "message": str(e)})


# ==================== LISTAR TICKETS ====================
@router.get("")
def list_tickets(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    params = request.query_params
    status = params.get("status")
    if status:
        status_list = [s.strip().upper() for s in status.split(",") if s.strip()]
        status = status_list if status_list else None

    area = params.get("area")
    priority = params.get("priority")
    assigned_to_me = params.get("assigned_to_me", "false").lower() == "true"
    assigned_to_team = params.get("assigned_to_team")
    created_by_me = params.get("created_by_me", "false").lower() == "true"
    department_id = int(params["department_id"]) if params.get("department_id") else None
    search = (params.get("search", "") or "").strip() or None
    page = int(params.get("page", "1"))
    requested_per_page = int(params.get("per_page", "20"))
    include_metrics = params.get("include_metrics", "false").lower() == "true"

    if requested_per_page <= 0:
        per_page = 1000
    elif "admin" in user_roles or "tech_desarrollo" in user_roles or "tech_soporte" in user_roles:
        per_page = min(requested_per_page, 1000)
    else:
        per_page = min(requested_per_page, 100)

    try:
        result = ticket_service.list_tickets(
            user_id=user_id,
            user_roles=user_roles,
            status=status,
            area=area,
            priority=priority,
            assigned_to_me=assigned_to_me,
            assigned_to_team=assigned_to_team,
            created_by_me=created_by_me,
            department_id=department_id,
            search=search,
            page=page,
            per_page=per_page,
            include_metrics=include_metrics,
        )
        return result
    except Exception as e:
        logger.error(f"Error al listar tickets: {e}")
        raise HTTPException(500, detail={"error": "list_failed", "message": str(e)})


# ==================== OBTENER TICKET POR ID ====================
@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(
        db,
        ticket_id=ticket_id,
        user_id=user_id,
        check_permissions=True,
    )
    return {"ticket": ticket.to_dict(include_relations=True)}


# ==================== INICIAR TRABAJO EN TICKET ====================
@router.post("/{ticket_id}/start")
async def start_ticket(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])

    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    if ticket.assigned_to_user_id != user_id:
        raise HTTPException(403, detail={"error": "not_assigned", "message": "El ticket no está asignado a ti"})

    ticket = ticket_service.change_status(
        db,
        ticket_id=ticket_id,
        new_status="IN_PROGRESS",
        changed_by_id=user_id,
        notes="Técnico comenzó a trabajar en el ticket",
    )

    logger.info(f"Ticket {ticket.ticket_number} iniciado por técnico {user_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    try:
        HelpdeskNotificationHelper.notify_ticket_in_progress(db, ticket)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de ticket iniciado: {notif_error}")

    try:
        from itcj2.sockets.helpdesk import broadcast_ticket_status_changed
        assignee_id = ticket.assigned_to_user_id if hasattr(ticket, "assigned_to_user_id") else None
        await broadcast_ticket_status_changed(
            ticket.id, assignee_id, ticket.area,
            {
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "old_status": "ASSIGNED",
                "new_status": "IN_PROGRESS",
                "area": ticket.area,
            },
            department_id=ticket.requester_department_id,
        )
    except Exception as ws_err:
        logger.warning(f"WS broadcast ticket_status_changed (start) error: {ws_err}")

    return {"message": "Ticket iniciado exitosamente", "ticket": ticket.to_dict()}


# ==================== RESOLVER TICKET ====================
@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int,
    body: ResolveTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.apps.helpdesk.models.ticket import Ticket as TicketModel

    user_id = int(user["sub"])
    data = body.model_dump()

    ticket_check = db.get(TicketModel, ticket_id)
    if not ticket_check:
        raise HTTPException(404, detail={"error": "not_found", "message": "Ticket no encontrado"})

    required_fields = ["success", "resolution_notes", "time_invested_minutes"]
    if ticket_check.area == "SOPORTE":
        required_fields.extend(["maintenance_type", "service_origin"])

    missing = [f for f in required_fields if data.get(f) is None]
    if missing:
        raise HTTPException(400, detail={
            "error": "missing_fields",
            "message": f'Faltan campos requeridos: {", ".join(missing)}',
        })

    ticket = ticket_service.resolve_ticket(
        db,
        ticket_id=ticket_id,
        resolved_by_id=user_id,
        success=data["success"],
        resolution_notes=data["resolution_notes"],
        time_invested_minutes=data["time_invested_minutes"],
        maintenance_type=data.get("maintenance_type"),
        service_origin=data.get("service_origin"),
        observations=data.get("observations"),
    )

    logger.info(f"Ticket {ticket.ticket_number} resuelto por técnico {user_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    try:
        HelpdeskNotificationHelper.notify_ticket_resolved(db, ticket)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de ticket resuelto: {notif_error}")

    try:
        from itcj2.sockets.helpdesk import broadcast_ticket_status_changed
        assignee_id = ticket.assigned_to_user_id if hasattr(ticket, "assigned_to_user_id") else None
        await broadcast_ticket_status_changed(
            ticket.id, assignee_id, ticket.area,
            {
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "old_status": "IN_PROGRESS",
                "new_status": ticket.status,
                "area": ticket.area,
            },
            department_id=ticket.requester_department_id,
        )
    except Exception as ws_err:
        logger.warning(f"WS broadcast ticket_status_changed (resolve) error: {ws_err}")

    return {"message": "Ticket resuelto exitosamente", "ticket": ticket.to_dict()}


# ==================== CALIFICAR TICKET ====================
@router.post("/{ticket_id}/rate")
def rate_ticket(
    ticket_id: int,
    body: RateTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])

    ticket = ticket_service.rate_ticket(
        db,
        ticket_id=ticket_id,
        requester_id=user_id,
        rating_attention=body.rating_attention,
        rating_speed=body.rating_speed,
        rating_efficiency=body.rating_efficiency,
        comment=body.comment,
    )

    logger.info(f"Ticket {ticket.ticket_number} calificado")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    try:
        HelpdeskNotificationHelper.notify_ticket_rated(db, ticket)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de ticket calificado: {notif_error}")

    return {"message": "Ticket calificado exitosamente", "ticket": ticket.to_dict()}


# ==================== CANCELAR TICKET ====================
@router.post("/{ticket_id}/cancel")
async def cancel_ticket(
    ticket_id: int,
    body: CancelTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])

    ticket = ticket_service.cancel_ticket(
        db,
        ticket_id=ticket_id,
        user_id=user_id,
        reason=body.reason,
    )

    logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    try:
        HelpdeskNotificationHelper.notify_ticket_canceled(db, ticket)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de ticket cancelado: {notif_error}")

    try:
        from itcj2.sockets.helpdesk import broadcast_ticket_status_changed
        assignee_id = ticket.assigned_to_user_id if hasattr(ticket, "assigned_to_user_id") else None
        await broadcast_ticket_status_changed(
            ticket.id, assignee_id, ticket.area,
            {
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "old_status": ticket.status,
                "new_status": "CANCELED",
                "area": ticket.area,
            },
            department_id=ticket.requester_department_id,
        )
    except Exception as ws_err:
        logger.warning(f"WS broadcast ticket_status_changed (cancel) error: {ws_err}")

    return {"message": "Ticket cancelado exitosamente", "ticket": ticket.to_dict()}


# ==================== EDITAR TICKET PENDIENTE ====================
@router.patch("/{ticket_id}")
def update_ticket(
    ticket_id: int,
    body: UpdateTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center:
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para editar tickets"})

    ticket = ticket_service.update_pending_ticket(
        db,
        ticket_id=ticket_id,
        updated_by_id=user_id,
        area=body.area,
        category_id=body.category_id,
        priority=body.priority,
        title=body.title,
        description=body.description,
        location=body.location,
    )

    logger.info(f"Ticket {ticket.ticket_number} editado por usuario {user_id}")
    return {"message": "Ticket actualizado exitosamente", "ticket": ticket.to_dict(include_relations=True)}

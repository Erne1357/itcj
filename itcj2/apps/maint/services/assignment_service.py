import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.maint.models.ticket import MaintTicket
from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician
from itcj2.apps.maint.models.technician_area import MaintTechnicianArea
from itcj2.apps.maint.models.status_log import MaintStatusLog
from itcj2.apps.maint.models.action_log import MaintTicketActionLog
from itcj2.apps.maint.utils.timezone_utils import now_local
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import user_roles_in_app

logger = logging.getLogger(__name__)


# ==================== ASIGNAR TÉCNICO(S) ====================

def assign_technicians(
    db: Session,
    ticket_id: int,
    assigned_by_id: int,
    user_ids: list[int],
    notes: str = None,
    assigner_roles: set | list | None = None,
    is_global_admin: bool = False,
) -> list[MaintTicketTechnician]:
    """
    Agrega uno o más técnicos a un ticket.
    Los técnicos ya activamente asignados son ignorados (idempotente).
    El ticket pasa a ASSIGNED si estaba PENDING.

    Parámetros adicionales:
        assigner_roles: roles del usuario que asigna en la app maint.
            Si None, se resuelven consultando la BD (overhead extra).
        is_global_admin: True si user["role"] == "admin" (del JWT);
            bypasea todas las restricciones de área.
    """
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService

    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not ticket.is_open:
        raise HTTPException(status_code=400, detail='No se puede asignar técnicos a un ticket cerrado o cancelado')

    if ticket.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED'):
        raise HTTPException(status_code=400, detail='El ticket ya fue resuelto')

    if not user_ids:
        raise HTTPException(status_code=400, detail='Debe especificar al menos un técnico')

    # Resolver roles del asignador si no se pasaron
    if assigner_roles is None:
        assigner_roles = user_roles_in_app(db, assigned_by_id, 'maint')

    assigner_roles_set = set(assigner_roles)

    # Restricción de propiedad de enrutado: el coordinador solo puede asignar
    # si el ticket está enrutado a él mismo. Admin y dispatcher omiten esta regla.
    is_coord_role = bool(
        assigner_roles_set & {"maint_area_coordinator", "maint_general_coordinator"}
    )
    if is_coord_role and not is_global_admin and "admin" not in assigner_roles_set:
        if ticket.coordinator_id != assigned_by_id:
            raise HTTPException(
                status_code=403,
                detail="El ticket no está enrutado a ti. Solo puedes asignar técnicos a tickets que tengas en tu cola.",
            )

    # IDs ya activamente asignados
    active_ids = {t.user_id for t in ticket.technicians if t.unassigned_at is None}

    new_assignments = []
    for user_id in user_ids:
        if user_id in active_ids:
            continue  # Ya asignado, ignorar

        technician = db.get(User, user_id)
        if not technician:
            raise HTTPException(status_code=404, detail=f'Usuario {user_id} no encontrado')

        # Validar que tenga el rol de técnico o admin en maint
        tech_roles = set(user_roles_in_app(db, user_id, 'maint'))
        if not (tech_roles & {'tech_maint', 'admin'}):
            raise HTTPException(
                status_code=400,
                detail=f'El usuario {user_id} no tiene rol de técnico en la app de mantenimiento',
            )

        # Restricción dura por área: solo coordinadores de área tienen límite
        if not CoordinatorService.can_assign_technician(
            db=db,
            assigner_id=assigned_by_id,
            assigner_roles=assigner_roles_set,
            technician_id=user_id,
            is_global_admin=is_global_admin,
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    f'No puedes asignar al técnico {technician.full_name} (id={user_id}): '
                    'no pertenece a tu(s) área(s) de coordinación'
                ),
            )

        assignment = MaintTicketTechnician(
            ticket_id=ticket_id,
            user_id=user_id,
            assigned_by_id=assigned_by_id,
            notes=notes,
        )
        db.add(assignment)
        db.add(MaintTicketActionLog(
            ticket_id=ticket_id,
            action='TECHNICIAN_ASSIGNED',
            performed_by_id=assigned_by_id,
            detail={'user_id': user_id, 'user_name': technician.full_name},
        ))
        new_assignments.append(assignment)

    if not new_assignments:
        raise HTTPException(status_code=400, detail='Todos los técnicos indicados ya están asignados')

    # Avanzar estado si aún está PENDING
    if ticket.status == 'PENDING':
        old_status = ticket.status
        ticket.status = 'ASSIGNED'
        ticket.updated_at = now_local()
        ticket.updated_by_id = assigned_by_id
        db.add(MaintStatusLog(
            ticket_id=ticket_id,
            from_status=old_status,
            to_status='ASSIGNED',
            changed_by_id=assigned_by_id,
            notes=f'{len(new_assignments)} técnico(s) asignados',
        ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number}: {len(new_assignments)} técnico(s) asignados por {assigned_by_id}")
        return new_assignments
    except Exception as e:
        db.rollback()
        logger.error(f"Error al asignar técnico(s): {e}")
        raise HTTPException(status_code=500, detail='Error al asignar técnicos')


# ==================== REMOVER TÉCNICO ====================

def unassign_technician(
    db: Session,
    ticket_id: int,
    unassigned_by_id: int,
    user_id: int,
    reason: str = None,
) -> MaintTicketTechnician:
    """
    Remueve la asignación activa de un técnico en el ticket.
    Si no quedan técnicos activos, el ticket regresa a PENDING.
    """
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    # Buscar la asignación activa del técnico
    active_assignment = next(
        (t for t in ticket.technicians if t.user_id == user_id and t.unassigned_at is None),
        None,
    )
    if not active_assignment:
        raise HTTPException(status_code=404, detail='El técnico no tiene una asignación activa en este ticket')

    now = now_local()
    active_assignment.unassigned_at = now
    active_assignment.unassigned_by_id = unassigned_by_id
    active_assignment.unassigned_reason = reason

    technician = db.get(User, user_id)
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='TECHNICIAN_UNASSIGNED',
        performed_by_id=unassigned_by_id,
        detail={
            'user_id': user_id,
            'user_name': technician.full_name if technician else str(user_id),
            'reason': reason,
        },
    ))

    # Si no quedan técnicos activos, regresar a PENDING
    remaining_active = [t for t in ticket.technicians if t.unassigned_at is None and t.id != active_assignment.id]
    if not remaining_active and ticket.status == 'ASSIGNED':
        old_status = ticket.status
        ticket.status = 'PENDING'
        ticket.updated_at = now
        ticket.updated_by_id = unassigned_by_id
        db.add(MaintStatusLog(
            ticket_id=ticket_id,
            from_status=old_status,
            to_status='PENDING',
            changed_by_id=unassigned_by_id,
            notes='Sin técnicos asignados',
        ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number}: técnico {user_id} removido por {unassigned_by_id}")
        return active_assignment
    except Exception as e:
        db.rollback()
        logger.error(f"Error al remover técnico: {e}")
        raise HTTPException(status_code=500, detail='Error al remover técnico')


# ==================== ÁREAS DE TÉCNICO ====================

def assign_technician_area(
    db: Session,
    assigned_by_id: int,
    user_id: int,
    area_code: str,
) -> MaintTechnicianArea:
    """Registra un área de especialidad para un técnico (informativa)."""
    # Catálogo dinámico (maint_area) con fallback defensivo si la BD/tabla falla.
    from itcj2.apps.maint.utils.catalog_cache import get_area_codes
    valid_areas = get_area_codes(db) or {
        'TRANSPORT', 'GENERAL', 'ELECTRICAL', 'CARPENTRY', 'AC', 'GARDENING', 'PAINTING',
    }
    if area_code not in valid_areas:
        raise HTTPException(
            status_code=400,
            detail=f'Área inválida. Valores: {", ".join(sorted(valid_areas))}',
        )

    technician = db.get(User, user_id)
    if not technician:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    existing = db.query(MaintTechnicianArea).filter_by(user_id=user_id, area_code=area_code).first()
    if existing:
        raise HTTPException(status_code=400, detail='El técnico ya tiene registrada esta área')

    area = MaintTechnicianArea(user_id=user_id, area_code=area_code, updated_by_id=assigned_by_id)
    db.add(area)

    try:
        db.commit()
        return area
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al asignar área')


def remove_technician_area(
    db: Session,
    user_id: int,
    area_code: str = None,
) -> int:
    """
    Remueve una o todas las áreas de un técnico.
    Retorna el número de áreas eliminadas.
    """
    query = db.query(MaintTechnicianArea).filter_by(user_id=user_id)
    if area_code:
        query = query.filter_by(area_code=area_code)

    count = query.count()
    if count == 0:
        raise HTTPException(status_code=404, detail='No se encontraron áreas para remover')

    query.delete(synchronize_session=False)
    try:
        db.commit()
        return count
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail='Error al remover área')


def get_technician_areas(db: Session, user_id: int) -> list[MaintTechnicianArea]:
    return db.query(MaintTechnicianArea).filter_by(user_id=user_id).all()


def get_technicians_by_area(db: Session, area_code: str) -> list:
    """Retorna técnicos con el área de especialidad indicada."""
    from itcj2.core.models.user import User as UserModel
    return (
        db.query(UserModel)
        .join(MaintTechnicianArea, MaintTechnicianArea.user_id == UserModel.id)
        .filter(MaintTechnicianArea.area_code == area_code)
        .all()
    )


# ==================== ENRUTAR TICKET A COORDINADOR ====================

def route_ticket(
    db: Session,
    ticket_id: int,
    target_coordinator_id: int,
    performed_by_id: int,
    performer_roles: set | list,
    is_global_admin: bool = False,
) -> MaintTicket:
    """
    Enruta (o re-enruta) un ticket a un coordinador.

    Reglas por performer:
    - Admin global o rol admin: puede enrutar a cualquier coordinador (general o área).
    - Rol dispatcher: solo puede enrutar a coordinadores GENERALES.
    - Rol maint_general_coordinator: puede enrutar a cualquier coordinador (general o área),
      incluido a sí mismo.
    - Rol maint_area_coordinator (sin general/dispatcher/admin): no puede enrutar → PermissionError.

    El status del ticket NO cambia. Solo se actualiza coordinator_id.
    Registra MaintTicketActionLog con action='TICKET_ROUTED'.

    Raises:
        HTTPException 404: ticket no encontrado.
        HTTPException 409: ticket cerrado o cancelado.
        HTTPException 400: target_coordinator_id no es coordinador válido.
        PermissionError: el performer no tiene permiso para este enrutado.
    """
    from itcj2.apps.maint.services.coordinator_service import CoordinatorService
    from itcj2.core.models.user import User

    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    if ticket.status in ("CLOSED", "CANCELED"):
        raise HTTPException(
            status_code=409,
            detail="No se puede enrutar un ticket cerrado o cancelado",
        )

    roles = set(performer_roles)

    # Evaluar permiso del performer primero (fail-fast sin extra queries)
    if is_global_admin or "admin" in roles:
        # Admin global: puede enrutar a cualquier coordinador
        pass
    elif "maint_area_coordinator" in roles and "dispatcher" not in roles and "maint_general_coordinator" not in roles:
        # Coordinador de área (sin otros roles privilegiados): no puede enrutar tickets
        raise PermissionError(
            "Los coordinadores de área no pueden enrutar tickets"
        )
    elif "dispatcher" not in roles and "maint_general_coordinator" not in roles:
        raise PermissionError(
            "No tienes permiso para enrutar tickets"
        )

    # Validar que target existe
    target_user = db.get(User, target_coordinator_id)
    if not target_user:
        raise HTTPException(
            status_code=400,
            detail=f"El usuario {target_coordinator_id} no existe",
        )

    # Validar que target_coordinator_id es un coordinador (general o de área)
    if not is_global_admin:
        target_is_coord = CoordinatorService.is_coordinator(db, target_coordinator_id)
        if not target_is_coord:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"El usuario {target_coordinator_id} ({target_user.full_name}) "
                    "no es coordinador general ni de área en la app maint"
                ),
            )

    # Restricción adicional para dispatcher: solo puede enrutar a coordinadores GENERALES
    if "dispatcher" in roles and not is_global_admin and "admin" not in roles:
        target_is_general = CoordinatorService.is_general_coordinator(db, target_coordinator_id)
        if not target_is_general:
            raise PermissionError(
                "La secretaría solo puede enrutar a un coordinador general"
            )

    from_coordinator_id = ticket.coordinator_id
    ticket.coordinator_id = target_coordinator_id
    ticket.updated_at = now_local()
    ticket.updated_by_id = performed_by_id

    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action="TICKET_ROUTED",
        performed_by_id=performed_by_id,
        detail={
            "from_coordinator_id": from_coordinator_id,
            "to_coordinator_id": target_coordinator_id,
            "to_coordinator_name": target_user.full_name,
            "by": performed_by_id,
        },
    ))

    try:
        db.commit()
        db.refresh(ticket)
        logger.info(
            "Ticket %s enrutado a coordinador %s por %s",
            ticket.ticket_number,
            target_coordinator_id,
            performed_by_id,
        )
        return ticket
    except Exception as e:
        db.rollback()
        logger.error("Error al enrutar ticket %s: %s", ticket_id, e)
        raise HTTPException(status_code=500, detail="Error interno al enrutar ticket")

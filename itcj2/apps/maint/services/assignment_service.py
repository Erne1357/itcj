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
) -> list[MaintTicketTechnician]:
    """
    Agrega uno o más técnicos a un ticket.
    Los técnicos ya activamente asignados son ignorados (idempotente).
    El ticket pasa a ASSIGNED si estaba PENDING.
    """
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not ticket.is_open:
        raise HTTPException(status_code=400, detail='No se puede asignar técnicos a un ticket cerrado o cancelado')

    if ticket.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED'):
        raise HTTPException(status_code=400, detail='El ticket ya fue resuelto')

    if not user_ids:
        raise HTTPException(status_code=400, detail='Debe especificar al menos un técnico')

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
    VALID_AREAS = {'TRANSPORT', 'GENERAL', 'ELECTRICAL', 'CARPENTRY', 'AC', 'GARDENING'}
    if area_code not in VALID_AREAS:
        raise HTTPException(
            status_code=400,
            detail=f'Área inválida. Valores: {", ".join(sorted(VALID_AREAS))}',
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

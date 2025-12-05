from datetime import datetime, timedelta
from typing import Optional, Dict
from .timezone_utils import now_local, ensure_local_timezone

def calculate_business_hours(start: datetime, end: datetime) -> float:
    """
    Calcula las horas transcurridas en horario laboral (Lun-Vie, 8 AM - 6 PM).
    
    Args:
        start: Fecha/hora de inicio
        end: Fecha/hora de fin
    
    Returns:
        Horas en horario laboral
    """
    if not start or not end:
        return 0.0
    
    # Asegurar que ambas fechas estén en timezone local
    start = ensure_local_timezone(start)
    end = ensure_local_timezone(end)
    
    # Ahora ya podemos comparar de forma segura
    if start >= end:
        return 0.0
    
    # Configuración de horario laboral
    WORK_START = 8  # 8 AM
    WORK_END = 18   # 6 PM
    WORK_HOURS_PER_DAY = WORK_END - WORK_START  # 10 horas
    
    total_hours = 0.0
    current = start
    
    while current.date() <= end.date():
        # Saltar fines de semana (0=Monday, 6=Sunday)
        if current.weekday() >= 5:  # Sábado o Domingo
            current += timedelta(days=1)
            current = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
            continue
        
        # Determinar hora de inicio del día
        day_start = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
        day_end = current.replace(hour=WORK_END, minute=0, second=0, microsecond=0)
        
        # Ajustar si el inicio es antes o después del horario laboral
        if current < day_start:
            current = day_start
        elif current >= day_end:
            current += timedelta(days=1)
            current = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
            continue
        
        # Calcular horas trabajadas en este día
        if current.date() == end.date():
            # Último día
            effective_end = min(end, day_end)
            hours = (effective_end - current).total_seconds() / 3600
            total_hours += max(0, hours)
            break
        else:
            # Día completo
            hours = (day_end - current).total_seconds() / 3600
            total_hours += max(0, hours)
            
            # Siguiente día
            current += timedelta(days=1)
            current = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
    
    return round(total_hours, 2)


def calculate_sla_deadline(created_at: datetime, priority: str) -> datetime:
    """
    Calcula la fecha límite de SLA basada en la prioridad del ticket.
    
    Args:
        created_at: Fecha de creación del ticket
        priority: Prioridad del ticket (URGENTE, ALTA, MEDIA, BAJA)
        
    Returns:
        datetime: Fecha límite de resolución
    """
    sla_hours = {
        'URGENTE': 4,    # 4 horas
        'ALTA': 24,      # 24 horas  
        'MEDIA': 72,     # 72 horas (3 días)
        'BAJA': 168      # 168 horas (7 días)
    }
    
    hours_to_add = sla_hours.get(priority, 72)  # Default: 72 horas
    
    return created_at + timedelta(hours=hours_to_add)


def is_within_sla(created_at: datetime, resolved_at: Optional[datetime], priority: str) -> bool:
    """
    Verifica si un ticket fue resuelto dentro del SLA.
    
    Args:
        created_at: Fecha de creación
        resolved_at: Fecha de resolución (None si aún no está resuelto)
        priority: Prioridad del ticket
        
    Returns:
        bool: True si está dentro del SLA
    """
    deadline = calculate_sla_deadline(created_at, priority)
    current_time = resolved_at or now_local()
    
    return current_time <= deadline


def get_technician_total_time(user_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Dict:
    """
    Calcula el tiempo total invertido por un técnico considerando:
    - Tickets donde fue el asignado principal (time_invested_minutes del ticket)
    - Tickets donde colaboró (time_invested_minutes de la tabla collaborator)

    Args:
        user_id: ID del técnico
        start_date: Fecha de inicio del rango (opcional)
        end_date: Fecha fin del rango (opcional)

    Returns:
        Dict con:
            - total_minutes: Total de minutos invertidos
            - total_hours: Total de horas (redondeado)
            - as_lead_minutes: Minutos como asignado principal
            - as_collaborator_minutes: Minutos como colaborador
            - tickets_count: Número de tickets en los que trabajó
    """
    from itcj.core.extensions import db
    from itcj.apps.helpdesk.models import Ticket, TicketCollaborator

    # Query para tiempo como asignado principal
    lead_query = db.session.query(
        db.func.sum(Ticket.time_invested_minutes).label('total_time'),
        db.func.count(Ticket.id).label('count')
    ).filter(
        Ticket.assigned_to_user_id == user_id,
        Ticket.resolved_at.isnot(None)
    )

    if start_date:
        lead_query = lead_query.filter(Ticket.resolved_at >= start_date)
    if end_date:
        lead_query = lead_query.filter(Ticket.resolved_at <= end_date)

    lead_result = lead_query.first()
    lead_minutes = lead_result.total_time or 0
    lead_count = lead_result.count or 0

    # Query para tiempo como colaborador
    collab_query = db.session.query(
        db.func.sum(TicketCollaborator.time_invested_minutes).label('total_time'),
        db.func.count(TicketCollaborator.id).label('count')
    ).filter(
        TicketCollaborator.user_id == user_id
    )

    # Filtrar por fecha si se proporciona (usando la fecha de resolución del ticket)
    if start_date or end_date:
        collab_query = collab_query.join(Ticket, Ticket.id == TicketCollaborator.ticket_id)
        if start_date:
            collab_query = collab_query.filter(Ticket.resolved_at >= start_date)
        if end_date:
            collab_query = collab_query.filter(Ticket.resolved_at <= end_date)

    collab_result = collab_query.first()
    collab_minutes = collab_result.total_time or 0
    collab_count = collab_result.count or 0

    # Calcular totales
    total_minutes = lead_minutes + collab_minutes
    total_hours = round(total_minutes / 60, 2)

    # Contar tickets únicos donde trabajó
    unique_tickets_query = db.session.query(Ticket.id).filter(
        db.or_(
            Ticket.assigned_to_user_id == user_id,
            Ticket.id.in_(
                db.session.query(TicketCollaborator.ticket_id).filter(
                    TicketCollaborator.user_id == user_id
                )
            )
        ),
        Ticket.resolved_at.isnot(None)
    )

    if start_date:
        unique_tickets_query = unique_tickets_query.filter(Ticket.resolved_at >= start_date)
    if end_date:
        unique_tickets_query = unique_tickets_query.filter(Ticket.resolved_at <= end_date)

    unique_count = unique_tickets_query.count()

    return {
        'total_minutes': total_minutes,
        'total_hours': total_hours,
        'as_lead_minutes': lead_minutes,
        'as_lead_hours': round(lead_minutes / 60, 2),
        'as_collaborator_minutes': collab_minutes,
        'as_collaborator_hours': round(collab_minutes / 60, 2),
        'tickets_count': unique_count,
        'tickets_as_lead': lead_count,
        'tickets_as_collaborator': collab_count
    }


# Ejemplo de uso:
# start = datetime(2025, 1, 10, 17, 0)  # Viernes 5 PM
# end = datetime(2025, 1, 13, 10, 0)    # Lunes 10 AM
# hours = calculate_business_hours(start, end)
# print(hours)  # Output: 2.0 (1 hora el viernes + 2 horas el lunes)
#
# # Obtener tiempo total de un técnico
# tech_time = get_technician_total_time(user_id=123)
# print(f"Total: {tech_time['total_hours']} horas en {tech_time['tickets_count']} tickets")
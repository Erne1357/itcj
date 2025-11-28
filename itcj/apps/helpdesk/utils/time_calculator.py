from datetime import datetime, timedelta
from typing import Optional
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


# Ejemplo de uso:
# start = datetime(2025, 1, 10, 17, 0)  # Viernes 5 PM
# end = datetime(2025, 1, 13, 10, 0)    # Lunes 10 AM
# hours = calculate_business_hours(start, end)
# print(hours)  # Output: 2.0 (1 hora el viernes + 2 horas el lunes)
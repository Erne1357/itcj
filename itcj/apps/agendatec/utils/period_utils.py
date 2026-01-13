"""
Utilidades para manejo de períodos académicos en AgendaTec.

Estas funciones reemplazan las antiguas de core/utils/admit_window.py
que estaban basadas en variables de entorno.
"""
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
from itcj.core.services import period_service


def is_student_window_open() -> bool:
    """
    Verifica si la ventana de admisión de estudiantes está abierta.

    Checa:
    - Que exista un período activo
    - Que la fecha/hora actual esté dentro de la ventana de admisión

    Returns:
        True si la ventana está abierta, False en caso contrario
    """
    return period_service.is_student_window_open()


def get_student_window() -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Obtiene las fechas de inicio y fin de la ventana de admisión del período activo.

    Returns:
        Tupla (start_date, deadline) donde:
        - start_date: Fecha de inicio del período activo
        - deadline: Fecha límite de admisión (student_admission_deadline)

        Retorna (None, None) si no hay período activo o no tiene configuración.
    """
    period = period_service.get_active_period()
    if not period:
        return None, None

    config = period_service.get_agendatec_config(period.id)
    if not config:
        return None, None

    return period.start_date, config.student_admission_deadline


def get_enabled_days_for_active_period() -> list[datetime]:
    """
    Obtiene la lista de días habilitados para el período activo.

    Returns:
        Lista de objetos date con los días habilitados.
        Lista vacía si no hay período activo o no tiene días habilitados.
    """
    period = period_service.get_active_period()
    if not period:
        return []

    enabled_days = period_service.get_enabled_days(period.id)
    return [day.day for day in enabled_days]


def fmt_spanish(dt: Optional[datetime]) -> str:
    """
    Formatea una fecha en español para mostrar al usuario.

    Args:
        dt: Fecha/hora a formatear

    Returns:
        String formateado como "26/08/2025 16:30"
        String vacío si dt es None
    """
    if not dt:
        return ""
    # Formato simple y claro: DD/MM/YYYY HH:MM
    return dt.strftime("%d/%m/%Y %H:%M")

# itcj/core/services/period_service.py
"""
Servicio para gestión de períodos académicos.

Este servicio centraliza toda la lógica de negocio relacionada con períodos académicos,
incluyendo obtención del período activo, validación de ventanas de admisión, y gestión
de días habilitados.
"""
from __future__ import annotations
from typing import Optional, List
from datetime import datetime, date
from zoneinfo import ZoneInfo

from itcj.core.extensions import db
from itcj.core.models.academic_period import AcademicPeriod


# ==================== TIMEZONE ====================

def _get_tz():
    """Obtiene el timezone configurado para la aplicación"""
    return ZoneInfo("America/Ciudad_Juarez")


# ==================== PERÍODO ACTIVO ====================

def get_active_period() -> Optional[AcademicPeriod]:
    """
    Obtiene el período académico activo actual.

    Returns:
        AcademicPeriod | None: El período con status='ACTIVE' o None si no hay ninguno
    """
    return db.session.query(AcademicPeriod).filter_by(status="ACTIVE").first()


def get_period_by_id(period_id: int) -> Optional[AcademicPeriod]:
    """
    Obtiene un período académico por su ID.

    Args:
        period_id: ID del período

    Returns:
        AcademicPeriod | None: El período o None si no existe
    """
    return db.session.query(AcademicPeriod).filter_by(id=period_id).first()


# ==================== VALIDACIONES ====================

def is_student_window_open() -> bool:
    """
    Verifica si la ventana de admisión para estudiantes está abierta.

    Condiciones que deben cumplirse:
    - Debe existir un período activo
    - El período debe tener status='ACTIVE'
    - La fecha/hora actual debe ser <= student_admission_deadline

    Returns:
        bool: True si la ventana está abierta, False en caso contrario
    """
    period = get_active_period()
    if not period:
        return False

    return period.is_student_window_open()


def is_period_active(period_id: int) -> bool:
    """
    Verifica si un período específico está activo.

    Args:
        period_id: ID del período a verificar

    Returns:
        bool: True si el período existe y está activo
    """
    period = get_period_by_id(period_id)
    return period is not None and period.status == "ACTIVE"


# ==================== DÍAS HABILITADOS ====================

def get_enabled_days(period_id: Optional[int] = None) -> List[date]:
    """
    Obtiene los días habilitados de un período académico.

    Si no se especifica period_id, obtiene los días del período activo.

    Args:
        period_id: ID del período (opcional, por defecto el activo)

    Returns:
        List[date]: Lista de fechas habilitadas (puede ser vacía)
    """
    from itcj.apps.agendatec.models.period_enabled_day import PeriodEnabledDay

    if period_id is None:
        period = get_active_period()
        if not period:
            return []
        period_id = period.id

    enabled_days = db.session.query(PeriodEnabledDay).filter_by(
        period_id=period_id
    ).all()

    return [ed.day for ed in enabled_days]


def is_day_enabled(day: date, period_id: Optional[int] = None) -> bool:
    """
    Verifica si un día específico está habilitado en un período.

    Args:
        day: Fecha a verificar
        period_id: ID del período (opcional, por defecto el activo)

    Returns:
        bool: True si el día está habilitado
    """
    enabled_days = get_enabled_days(period_id)
    return day in enabled_days


# ==================== GESTIÓN DE PERÍODOS ====================

def activate_period(period_id: int, user_id: Optional[int] = None) -> AcademicPeriod:
    """
    Activa un período y desactiva todos los demás.

    IMPORTANTE: Solo un período puede estar activo a la vez.

    Args:
        period_id: ID del período a activar
        user_id: ID del usuario que realiza la acción (para auditoría)

    Returns:
        AcademicPeriod: El período activado

    Raises:
        ValueError: Si el período no existe
    """
    # Desactivar todos los períodos
    db.session.query(AcademicPeriod).update({"status": "INACTIVE"})

    # Activar el período seleccionado
    period = get_period_by_id(period_id)
    if not period:
        raise ValueError(f"Período con ID {period_id} no encontrado")

    period.status = "ACTIVE"
    period.updated_at = datetime.now(_get_tz())

    db.session.commit()

    return period


def deactivate_period(period_id: int) -> bool:
    """
    Desactiva un período específico.

    Args:
        period_id: ID del período a desactivar

    Returns:
        bool: True si se desactivó, False si no existe
    """
    period = get_period_by_id(period_id)
    if not period:
        return False

    period.status = "INACTIVE"
    period.updated_at = datetime.now(_get_tz())

    db.session.commit()

    return True


def archive_period(period_id: int) -> bool:
    """
    Archiva un período (para períodos pasados que ya no se usarán).

    Args:
        period_id: ID del período a archivar

    Returns:
        bool: True si se archivó, False si no existe
    """
    period = get_period_by_id(period_id)
    if not period:
        return False

    period.status = "ARCHIVED"
    period.updated_at = datetime.now(_get_tz())

    db.session.commit()

    return True


# ==================== ESTADÍSTICAS ====================

def count_requests_in_period(period_id: int) -> int:
    """
    Cuenta el total de solicitudes en un período.

    Args:
        period_id: ID del período

    Returns:
        int: Número de solicitudes
    """
    from itcj.apps.agendatec.models.request import Request

    return db.session.query(Request).filter_by(period_id=period_id).count()


def get_all_periods(include_archived: bool = False) -> List[AcademicPeriod]:
    """
    Obtiene todos los períodos académicos.

    Args:
        include_archived: Si True, incluye períodos archivados

    Returns:
        List[AcademicPeriod]: Lista de períodos ordenados por fecha de inicio descendente
    """
    query = db.session.query(AcademicPeriod)

    if not include_archived:
        query = query.filter(AcademicPeriod.status != "ARCHIVED")

    return query.order_by(AcademicPeriod.start_date.desc()).all()

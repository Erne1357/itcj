"""
Utilidades de períodos académicos para AgendaTec.
Fuente: itcj/apps/agendatec/utils/period_utils.py
"""
from datetime import datetime
from typing import Optional, Tuple

from itcj2.database import SessionLocal


def is_student_window_open() -> bool:
    """Verifica si la ventana de admisión de estudiantes está abierta."""
    from itcj2.core.services import period_service

    db = SessionLocal()
    try:
        return period_service.is_student_window_open(db)
    finally:
        db.close()


def get_student_window() -> Tuple[Optional[datetime], Optional[datetime]]:
    """Obtiene las fechas de inicio y fin de la ventana de admisión del período activo."""
    from itcj2.core.services import period_service

    db = SessionLocal()
    try:
        period = period_service.get_active_period(db)
        if not period:
            return None, None
        config = period_service.get_agendatec_config(db, period.id)
        if not config:
            return None, None
        return config.student_admission_start, config.student_admission_deadline
    finally:
        db.close()


def get_window_status() -> dict:
    """Obtiene el estado detallado de la ventana de admisión."""
    from itcj2.core.services import period_service

    db = SessionLocal()
    try:
        period = period_service.get_active_period(db)
        if not period:
            return {"is_open": False, "reason": "no_active_period", "starts_at": None, "ends_at": None}
        config = period_service.get_agendatec_config(db, period.id)
        if not config:
            return {"is_open": False, "reason": "no_config", "starts_at": None, "ends_at": None}
        return config.get_window_status()
    finally:
        db.close()


def get_enabled_days_for_active_period() -> list:
    """Obtiene la lista de días habilitados para el período activo."""
    from itcj2.core.services import period_service

    db = SessionLocal()
    try:
        period = period_service.get_active_period(db)
        if not period:
            return []
        return period_service.get_enabled_days(db, period.id)
    finally:
        db.close()


def fmt_spanish(dt: Optional[datetime]) -> str:
    """Formatea una fecha en español para mostrar al usuario."""
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M")

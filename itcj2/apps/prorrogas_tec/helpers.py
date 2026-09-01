"""
Helpers compartidos para la app agendatec en FastAPI.

Equivale a los helpers de Flask en:
- itcj/apps/agendatec/routes/api/coord/helpers.py
- itcj/apps/agendatec/routes/api/admin/helpers.py
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional, Set
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.core.models.user import User

# ---------------------------------------------------------------------------
# Fechas y rangos
# ---------------------------------------------------------------------------

def get_app_tz() -> ZoneInfo:
    return ZoneInfo("America/Ciudad_Juarez")


def parse_date_str(s: str) -> Optional[date]:
    """Parsea string YYYY-MM-DD a date, o None si inválido."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def parse_datetime_str(s: str) -> Optional[datetime]:
    """Parsea ISO datetime string, agrega timezone si falta."""
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=get_app_tz())
        return dt
    except (ValueError, AttributeError):
        return None


def parse_time_str(s: str) -> Optional[time]:
    """Parsea HH:MM a time, o None si inválido."""
    try:
        h, m = map(int, s.split(":"))
        return datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()
    except Exception:
        return None


def parse_range_from_params(
    from_str: Optional[str],
    to_str: Optional[str],
) -> tuple[datetime, datetime]:
    """
    FastAPI version of range_from_query().
    Toma strings 'from' y 'to', retorna (start, end) como datetimes.
    Default: últimos 7 días.
    """
    def _parse(s, default):
        if s:
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                pass
        return default

    now = datetime.now()
    end = _parse(to_str, now)
    start = _parse(from_str, end - timedelta(days=7))

    # Normalizar para incluir el día completo si solo vino la fecha
    if from_str and len(from_str) == 10:
        start = datetime.combine(start.date(), datetime.min.time())
    if to_str and len(to_str) == 10:
        end = datetime.combine(end.date(), datetime.max.time())

    return start, end


def paginate_query(query, limit: int, offset: int) -> tuple:
    """Aplica paginación a una query SQLAlchemy. Retorna (items, total)."""
    total = query.order_by(None).count()
    items = query.limit(limit).offset(offset).all()
    return items, total


def get_dialect_name(db: Session) -> str:
    """Obtiene el nombre del dialecto de la base de datos."""
    try:
        bind = db.get_bind()
        return (bind and bind.dialect and bind.dialect.name) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Validación de ventana de admisión (equivale a @api_closed)
# ---------------------------------------------------------------------------

def require_admission_open() -> None:
    """
    Verifica que la ventana de admisión del período activo esté abierta.
    Equivale al decorador @api_closed de Flask.
    Lanza HTTPException(503) si está cerrada.
    """
    from itcj2.apps.prorrogas_tec.services import period_service as prorrogas_period_service
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        period = prorrogas_period_service.get_active_period(db)
        if not period:
            raise HTTPException(status_code=503, detail="no_active_period")
        config = prorrogas_period_service.get_prorrogas_config(db, period.period_id)
        if not config or not config.is_student_window_open():
            raise HTTPException(status_code=503, detail="admission_closed")
    finally:
        db.close()

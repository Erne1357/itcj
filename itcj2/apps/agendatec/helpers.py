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

from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User


# ---------------------------------------------------------------------------
# Coordinador
# ---------------------------------------------------------------------------

def get_coordinator_for_user(user_id: int, db: Session) -> Optional[Coordinator]:
    """Retorna el Coordinator del usuario dado, o None."""
    return db.query(Coordinator).filter_by(user_id=user_id).first()


def get_coordinator_id_for_user(user_id: int, db: Session) -> Optional[int]:
    """Retorna el coordinator_id del usuario, o None."""
    coord = get_coordinator_for_user(user_id, db)
    return coord.id if coord else None


def get_coord_program_ids(coord_id: int, db: Session) -> Set[int]:
    """Retorna el conjunto de program_ids asignados a un coordinador."""
    rows = (
        db.query(ProgramCoordinator.program_id)
        .filter(ProgramCoordinator.coordinator_id == coord_id)
        .all()
    )
    return {r[0] for r in rows}


def require_coordinator(user_id: int, db: Session) -> int:
    """
    Obtiene el coordinator_id del usuario o lanza 404.
    Útil como helper en endpoints de coordinador.
    """
    coord_id = get_coordinator_id_for_user(user_id, db)
    if not coord_id:
        raise HTTPException(status_code=404, detail="coordinator_not_found")
    return coord_id


# ---------------------------------------------------------------------------
# Ventanas de disponibilidad
# ---------------------------------------------------------------------------

def split_or_delete_windows(
    coord_id: int,
    d: date,
    time_ge: time,
    time_lt: time,
    db: Session,
) -> dict:
    """
    Para cada AvailabilityWindow que solape [time_ge, time_lt):
    - Elimina la ventana original.
    - Recrea hasta dos ventanas 'no solapadas':
        [start_time, time_ge) y [time_lt, end_time)
    conservando slot_minutes.

    Returns:
        Dict con windows_deleted y windows_created.
    """
    from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow

    overlapping = (
        db.query(AvailabilityWindow)
        .filter(
            AvailabilityWindow.coordinator_id == coord_id,
            AvailabilityWindow.day == d,
            ~(
                (AvailabilityWindow.end_time <= time_ge)
                | (AvailabilityWindow.start_time >= time_lt)
            ),
        )
        .all()
    )

    recreated = 0
    deleted = 0

    for w in overlapping:
        left_start = w.start_time
        left_end = min(w.end_time, time_ge)
        right_start = max(w.start_time, time_lt)
        right_end = w.end_time

        db.delete(w)
        deleted += 1

        if left_start < left_end:
            db.add(
                AvailabilityWindow(
                    coordinator_id=coord_id,
                    day=d,
                    start_time=left_start,
                    end_time=left_end,
                    slot_minutes=w.slot_minutes,
                )
            )
            recreated += 1

        if right_start < right_end:
            db.add(
                AvailabilityWindow(
                    coordinator_id=coord_id,
                    day=d,
                    start_time=right_start,
                    end_time=right_end,
                    slot_minutes=w.slot_minutes,
                )
            )
            recreated += 1

    return {"windows_deleted": deleted, "windows_created": recreated}


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
    from itcj2.core.services import period_service
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        period = period_service.get_active_period(db)
        if not period:
            raise HTTPException(status_code=503, detail="no_active_period")
        config = period_service.get_agendatec_config(db, period.id)
        if not config or not config.is_student_window_open():
            raise HTTPException(status_code=503, detail="admission_closed")
    finally:
        db.close()

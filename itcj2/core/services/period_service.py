"""
Servicio para gestión de períodos académicos.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional, List
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from itcj2.core.models.academic_period import AcademicPeriod


def _get_tz():
    return ZoneInfo("America/Ciudad_Juarez")


def get_active_period(db: Session) -> Optional[AcademicPeriod]:
    return db.query(AcademicPeriod).filter_by(status="ACTIVE").first()


def get_period_by_id(db: Session, period_id: int) -> Optional[AcademicPeriod]:
    return db.get(AcademicPeriod, period_id)


def is_student_window_open(db: Session) -> bool:
    period = get_active_period(db)
    if not period:
        return False
    config = get_agendatec_config(db, period.id)
    if not config:
        return False
    return config.is_student_window_open()


def is_period_active(db: Session, period_id: int) -> bool:
    period = get_period_by_id(db, period_id)
    return period is not None and period.status == "ACTIVE"


def get_enabled_days(db: Session, period_id: Optional[int] = None) -> List[date]:
    from itcj2.apps.agendatec.models.period_enabled_day import PeriodEnabledDay

    if period_id is None:
        period = get_active_period(db)
        if not period:
            return []
        period_id = period.id

    enabled_days = db.query(PeriodEnabledDay).filter_by(period_id=period_id).all()
    return [ed.day for ed in enabled_days]


def is_day_enabled(db: Session, day: date, period_id: Optional[int] = None) -> bool:
    return day in get_enabled_days(db, period_id)


def activate_period(db: Session, period_id: int, user_id: Optional[int] = None) -> AcademicPeriod:
    db.query(AcademicPeriod).update({"status": "INACTIVE"})

    period = get_period_by_id(db, period_id)
    if not period:
        raise ValueError(f"Período con ID {period_id} no encontrado")

    period.status = "ACTIVE"
    period.updated_at = datetime.now(_get_tz())
    db.commit()
    return period


def deactivate_period(db: Session, period_id: int) -> bool:
    period = get_period_by_id(db, period_id)
    if not period:
        return False
    period.status = "INACTIVE"
    period.updated_at = datetime.now(_get_tz())
    db.commit()
    return True


def archive_period(db: Session, period_id: int) -> bool:
    period = get_period_by_id(db, period_id)
    if not period:
        return False
    period.status = "ARCHIVED"
    period.updated_at = datetime.now(_get_tz())
    db.commit()
    return True


def get_agendatec_config(db: Session, period_id: Optional[int] = None):
    from itcj2.apps.agendatec.models.agendatec_period_config import AgendaTecPeriodConfig

    if period_id is None:
        period = get_active_period(db)
        if not period:
            return None
        period_id = period.id

    return db.query(AgendaTecPeriodConfig).filter_by(period_id=period_id).first()


def create_agendatec_config(
    db: Session,
    period_id: int,
    student_admission_start: datetime,
    student_admission_deadline: datetime,
    max_cancellations: int = 2,
    allow_drop: bool = True,
    allow_appointment: bool = True,
    created_by_id: Optional[int] = None,
):
    from itcj2.apps.agendatec.models.agendatec_period_config import AgendaTecPeriodConfig

    period = get_period_by_id(db, period_id)
    if not period:
        raise ValueError(f"Período con ID {period_id} no encontrado")

    existing = get_agendatec_config(db, period_id)
    if existing:
        raise ValueError(f"Ya existe configuración de AgendaTec para el período {period_id}")

    config = AgendaTecPeriodConfig(
        period_id=period_id,
        student_admission_start=student_admission_start,
        student_admission_deadline=student_admission_deadline,
        max_cancellations_per_student=max_cancellations,
        allow_drop_requests=allow_drop,
        allow_appointment_requests=allow_appointment,
        created_by_id=created_by_id,
    )
    db.add(config)
    db.commit()
    return config


def update_agendatec_config(db: Session, period_id: int, **kwargs):
    config = get_agendatec_config(db, period_id)
    if not config:
        raise ValueError(f"No existe configuración de AgendaTec para el período {period_id}")

    allowed = [
        "student_admission_start", "student_admission_deadline",
        "max_cancellations_per_student", "allow_drop_requests", "allow_appointment_requests",
    ]
    for key in allowed:
        if key in kwargs:
            setattr(config, key, kwargs[key])

    config.updated_at = datetime.now(_get_tz())
    db.commit()
    return config


def count_requests_in_period(db: Session, period_id: int) -> int:
    from itcj2.apps.agendatec.models.request import Request
    return db.query(Request).filter_by(period_id=period_id).count()


def get_all_periods(db: Session, include_archived: bool = False) -> List[AcademicPeriod]:
    query = db.query(AcademicPeriod)
    if not include_archived:
        query = query.filter(AcademicPeriod.status != "ARCHIVED")
    return query.order_by(AcademicPeriod.start_date.desc()).all()

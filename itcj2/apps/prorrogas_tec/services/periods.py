"""Semestre (`core_academic_periods`) al que pertenece un día."""
from __future__ import annotations

from datetime import date

from itcj2.apps.prorrogas_tec.services.formatting import semestre_label
from itcj2.core.models.academic_period import AcademicPeriod


def period_for(db, day: date) -> AcademicPeriod | None:
    """Semestre cuyo rango contiene ``day`` (el más reciente si hubiera traslape)."""
    return (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.start_date <= day, AcademicPeriod.end_date >= day)
        .order_by(AcademicPeriod.start_date.desc())
        .first()
    )


def period_label(p: AcademicPeriod) -> str:
    return semestre_label(p.start_date, p.end_date)

"""Días habilitados para el cotejo, por convocatoria (Servicios Escolares)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session


class ReviewDayService:
    @staticmethod
    def list_days(db: Session, cohort_id: int) -> list[date]:
        from itcj2.apps.titulatec.models import CohortReviewDay
        rows = (db.query(CohortReviewDay).filter_by(cohort_id=cohort_id)
                .order_by(CohortReviewDay.date).all())
        return [r.date for r in rows]

    @staticmethod
    def is_allowed(db: Session, cohort_id: int, day: date) -> bool:
        from itcj2.apps.titulatec.models import CohortReviewDay
        return (db.query(CohortReviewDay)
                .filter_by(cohort_id=cohort_id, date=day).first()) is not None

    @staticmethod
    def set_days(db: Session, cohort_id: int, dates: set, created_by_id: int) -> None:
        """Sincroniza las fechas del cohort = `dates` (set[date])."""
        from itcj2.apps.titulatec.models import CohortReviewDay
        current = {r.date for r in
                   db.query(CohortReviewDay).filter_by(cohort_id=cohort_id).all()}
        for d in current - set(dates):
            db.query(CohortReviewDay).filter_by(cohort_id=cohort_id, date=d).delete()
        for d in set(dates) - current:
            db.add(CohortReviewDay(cohort_id=cohort_id, date=d, created_by_id=created_by_id))
        db.commit()

    @staticmethod
    def toggle(db: Session, cohort_id: int, day: date, created_by_id: int) -> bool:
        """Alterna una fecha. True si quedó habilitada, False si se quitó."""
        from itcj2.apps.titulatec.models import CohortReviewDay
        row = db.query(CohortReviewDay).filter_by(cohort_id=cohort_id, date=day).first()
        if row:
            db.delete(row)
            db.commit()
            return False
        db.add(CohortReviewDay(cohort_id=cohort_id, date=day, created_by_id=created_by_id))
        db.commit()
        return True

    @staticmethod
    def months_with_days(db: Session, cohort_id: int) -> list[tuple]:
        """[(year, month), ...] distinct, ordenados, con al menos una fecha."""
        days = ReviewDayService.list_days(db, cohort_id)
        return sorted({(d.year, d.month) for d in days})

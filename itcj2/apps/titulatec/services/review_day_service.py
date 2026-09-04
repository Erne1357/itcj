"""Días habilitados para el cotejo, por convocatoria (Servicios Escolares).

Cerrar, no borrar
-----------------
`toggle()` hacía `db.delete(row)`. Desde que un día puede tener **ventanas** de
encargados y esas ventanas **citas de alumnos**, borrarlo es un default
destructivo: la FK de `ReviewWindow` apunta aquí con ``ON DELETE RESTRICT``, así
que el DELETE ni siquiera pasaría, y si pasara se llevaría por delante la cita
de alguien. Ahora se escribe `is_closed`.

Y la columna hay que **consultarla**: `list_days` e `is_allowed` filtran los días
cerrados salvo que se pida `include_closed=True` (la vista de configuración de la
jefatura sí los necesita, para poder reabrirlos). Una columna que nadie filtra no
cierra nada.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session


class ReviewDayService:
    @staticmethod
    def list_days(db: Session, cohort_id: int, *, include_closed: bool = False) -> list[date]:
        from itcj2.apps.titulatec.models import CohortReviewDay
        q = db.query(CohortReviewDay).filter_by(cohort_id=cohort_id)
        if not include_closed:
            q = q.filter(CohortReviewDay.is_closed.is_(False))
        return [r.date for r in q.order_by(CohortReviewDay.date).all()]

    @staticmethod
    def list_rows(db: Session, cohort_id: int, *, include_closed: bool = False) -> list:
        """Las filas completas, que es lo que necesita la UI de espacios.

        `list_days` devuelve solo fechas y no basta cuando hay que leer el
        override de horario del día o su id.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay
        q = db.query(CohortReviewDay).filter_by(cohort_id=cohort_id)
        if not include_closed:
            q = q.filter(CohortReviewDay.is_closed.is_(False))
        return q.order_by(CohortReviewDay.date).all()

    @staticmethod
    def get(db: Session, cohort_id: int, day: date):
        from itcj2.apps.titulatec.models import CohortReviewDay
        return (db.query(CohortReviewDay)
                .filter_by(cohort_id=cohort_id, date=day).first())

    @staticmethod
    def is_allowed(db: Session, cohort_id: int, day: date) -> bool:
        """Un día CERRADO no está habilitado, aunque su fila siga existiendo."""
        row = ReviewDayService.get(db, cohort_id, day)
        return bool(row) and not row.is_closed

    @staticmethod
    def assert_allowed(db: Session, cohort_id: int, day: date) -> None:
        """Guard para los services. Vivía en `pages/`, que dejaba fuera a
        cualquier otro llamador de `AppointmentService`."""
        from itcj2.apps.titulatec.services.appointment_errors import DayNotAllowed
        if not ReviewDayService.is_allowed(db, cohort_id, day):
            raise DayNotAllowed()

    @staticmethod
    def set_days(db: Session, cohort_id: int, dates: set, created_by_id: int) -> None:
        """Deja habilitados exactamente `dates`. Los que sobran se CIERRAN.

        Cerrar y no borrar: un día que ya tiene citas conserva su historia y su
        fila; simplemente deja de ofrecerse.
        """
        from itcj2.apps.titulatec.models import CohortReviewDay
        objetivo = set(dates)
        filas = db.query(CohortReviewDay).filter_by(cohort_id=cohort_id).all()
        actuales = {r.date: r for r in filas}

        for d, row in actuales.items():
            row.is_closed = d not in objetivo
        for d in objetivo - set(actuales):
            db.add(CohortReviewDay(cohort_id=cohort_id, date=d,
                                   created_by_id=created_by_id))
        db.commit()

    @staticmethod
    def toggle(db: Session, cohort_id: int, day: date, created_by_id: int) -> bool:
        """Alterna una fecha. True si quedó habilitada, False si se cerró."""
        from itcj2.apps.titulatec.models import CohortReviewDay
        row = ReviewDayService.get(db, cohort_id, day)
        if row is None:
            db.add(CohortReviewDay(cohort_id=cohort_id, date=day,
                                   created_by_id=created_by_id))
            db.commit()
            return True
        row.is_closed = not row.is_closed
        db.commit()
        return not row.is_closed

    @staticmethod
    def months_with_days(db: Session, cohort_id: int) -> list[tuple]:
        """[(year, month), ...] distinct, ordenados, con al menos una fecha."""
        days = ReviewDayService.list_days(db, cohort_id)
        return sorted({(d.year, d.month) for d in days})

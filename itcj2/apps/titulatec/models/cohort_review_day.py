"""Fechas habilitadas para el cotejo de documentos, por convocatoria."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, String, Time, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class CohortReviewDay(Base):
    """Un día habilitado para cotejo en una convocatoria. La jefa los configura.

    Sobre los overrides de franja
    -----------------------------
    Las cinco columnas de horario son **nullable a propósito**: NULL significa
    «hereda de la convocatoria». Así los días que ya existían siguen siendo
    válidos sin backfill, y la jefatura solo toca los que de verdad se salen
    del patrón.

    Sobre `is_closed`
    -----------------
    Sustituye al borrado. `ReviewDayService.toggle()` hacía `db.delete(row)`, y
    con ventanas y citas colgando eso es un default destructivo: borrar un día
    no puede borrar la cita de un alumno. Las FK de `ReviewWindow` apuntan aquí
    con ``ON DELETE RESTRICT`` para que la base lo impida de verdad.

    Y la columna hay que **consultarla**: `list_days` e `is_allowed` filtran
    ``is_closed = False`` salvo que se les pida `include_closed=True`. Una
    columna que nadie filtra no cierra nada.
    """
    __tablename__ = "titulatec_cohort_review_days"
    __table_args__ = (
        UniqueConstraint("cohort_id", "date", name="uq_titulatec_cohort_review_days_cohort_date"),
        # Tolerantes a NULL: `NULL > NULL` es NULL, y un CHECK solo falla con FALSE.
        CheckConstraint("end_time IS NULL OR start_time IS NULL OR end_time > start_time",
                        name="ck_titulatec_cohort_review_days_time_order"),
        CheckConstraint("slot_minutes IS NULL OR slot_minutes BETWEEN 5 AND 480",
                        name="ck_titulatec_cohort_review_days_slot_minutes"),
        CheckConstraint("capacity IS NULL OR capacity >= 1",
                        name="ck_titulatec_cohort_review_days_capacity"),
    )

    id = Column(Integer, primary_key=True)
    cohort_id = Column(
        Integer, ForeignKey("titulatec_cohorts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date = Column(Date, nullable=False)

    # --- Override del día (NULL = hereda de la convocatoria) -----------------
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    slot_minutes = Column(Integer, nullable=True)
    capacity = Column(Integer, nullable=True)
    location = Column(String(120), nullable=True)

    is_closed = Column(Boolean, nullable=False, server_default=text("FALSE"), index=True)

    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    windows = relationship("ReviewWindow", back_populates="review_day",
                           cascade="all, delete-orphan")

    def __repr__(self) -> str:
        estado = " CERRADO" if self.is_closed else ""
        return f"<CohortReviewDay c{self.cohort_id} {self.date}{estado}>"

"""Fechas habilitadas para el cotejo de documentos, por convocatoria."""
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Integer, UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class CohortReviewDay(Base):
    """Un día habilitado para cotejo en una convocatoria. La jefa los configura."""
    __tablename__ = "titulatec_cohort_review_days"
    __table_args__ = (
        UniqueConstraint("cohort_id", "date", name="uq_titulatec_cohort_review_days_cohort_date"),
    )

    id = Column(Integer, primary_key=True)
    cohort_id = Column(
        Integer, ForeignKey("titulatec_cohorts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date = Column(Date, nullable=False)
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<CohortReviewDay c{self.cohort_id} {self.date}>"

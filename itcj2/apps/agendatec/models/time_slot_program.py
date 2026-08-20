"""Scope por carrera de un slot (proyección materializada)."""
from sqlalchemy import BigInteger, Column, ForeignKey, Integer

from itcj2.models.base import Base


class TimeSlotProgram(Base):
    """Carreras que pueden reservar este slot.

    Proyección de `AvailabilityWindowProgram`, materializada para que la query
    del alumno sea un INNER JOIN barato en vez de resolver la ventana al vuelo
    (no hay FK slot→ventana, así que ese join iría por rangos de hora).

    La ausencia de filas NO significa "todas": el default se materializa como
    filas explícitas. Un slot sin filas es invisible para todos, que es la
    razón de la guarda `coordinator_has_no_programs` en SlotService y del
    chequeo post-backfill de la migración.

    `ondelete="CASCADE"` en `slot_id` es lo que permite que el split borre
    slots con `.delete(synchronize_session=False)` — SQL directo, sin cargar
    objetos — y la BD limpie esta tabla sola.
    """

    __tablename__ = "agendatec_time_slot_programs"

    slot_id = Column(
        BigInteger,
        ForeignKey("agendatec_time_slots.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    program_id = Column(
        Integer,
        ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<TimeSlotProgram s={self.slot_id} p={self.program_id}>"

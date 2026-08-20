"""Scope por carrera de una ventana de disponibilidad."""
from sqlalchemy import Column, ForeignKey, Integer

from itcj2.models.base import Base


class AvailabilityWindowProgram(Base):
    """Carreras a las que aplica una ventana de disponibilidad.

    Es la CONFIGURACIÓN que guardó el coordinador: la fuente de verdad de a
    quién ofrece ese rango horario. La proyección que consulta el alumno vive
    en `TimeSlotProgram`; ambas las escribe `SlotService`, nunca por separado.

    Un coordinador que no toca el selector obtiene una fila por cada carrera
    que coordina — el default se materializa explícitamente, no como ausencia
    de filas.
    """

    __tablename__ = "agendatec_availability_window_programs"

    window_id = Column(
        Integer,
        ForeignKey("agendatec_availability_windows.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    program_id = Column(
        Integer,
        ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AvailabilityWindowProgram w={self.window_id} p={self.program_id}>"

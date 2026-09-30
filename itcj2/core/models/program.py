from sqlalchemy import CheckConstraint, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Nivel academico de una carrera. Sin Enum por convencion del proyecto: el
# dominio se cierra con el CheckConstraint de __table_args__ (mismo texto que
# la migracion tt20260930a, para que create_all de CI y esa migracion nunca
# diverjan).
PROGRAM_LEVELS = ("licenciatura", "maestria", "doctorado")

# Perfil de titulacion "posgrado" de TitulaTec (TrackService, tarea aparte):
# una carrera es de posgrado si su nivel es maestria o doctorado. Nadie fuera
# de TrackService debe comparar Program.level directamente.
POSTGRADUATE_LEVELS = ("maestria", "doctorado")


class Program(Base):
    __tablename__ = "core_programs"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)
    level = Column(
        String(20), nullable=False, server_default="licenciatura",
        comment="Nivel academico de la carrera: licenciatura | maestria | doctorado",
    )

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    program_coordinators = relationship(
        "ProgramCoordinator", back_populates="program",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    coordinators = relationship(
        "Coordinator",
        secondary="core_program_coordinator",
        back_populates="programs",
        viewonly=True,
    )
    requests = relationship(
        "Request", back_populates="program",
        cascade="all, delete", passive_deletes=True,
    )
    appointments = relationship(
        "itcj2.apps.agendatec.models.appointment.Appointment",
        back_populates="program",
        cascade="all, delete", passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "level IN ('licenciatura','maestria','doctorado')",
            name="ck_core_programs_level",
        ),
    )

    @property
    def is_postgraduate(self) -> bool:
        """True si el nivel de la carrera es posgrado (maestria|doctorado).

        Uso interno de `TrackService` (itcj2/apps/titulatec/services, tarea
        aparte): nadie mas debe comparar `level` directamente.
        """
        return self.level in POSTGRADUATE_LEVELS

    def __repr__(self) -> str:
        return f"<Program {self.name}>"

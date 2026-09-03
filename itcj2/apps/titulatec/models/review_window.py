"""Ventana de atención de un encargado dentro de un día de cotejo.

La jefatura de Servicios Escolares pone los **días** (`CohortReviewDay`); cada
encargado abre en ellos sus propias **ventanas**, con su horario, la duración de
sus franjas y cuántas personas caben en cada una.

El dueño es el USUARIO, no el puesto
------------------------------------
Verificado en la BD: el puesto ``aux_school_services`` tiene
``allows_multiple = TRUE`` y **nueve** ocupantes sembrados
(``aux_prof_studies_div``, once). Con dueño = puesto esas nueve personas
compartirían una sola ventana y «cada encargado configura *sus* espacios» sería
inimplementable.

``owner_position_id`` se guarda **desnormalizado** para alcance y auditoría: es
el ancla que ya usa ``scope_service._program_ids_for_user``, que cuelga de
``core_program_positions`` ⋈ ``PositionAppRole`` con ``_active_position_filter()``.
La ventana sirve a las carreras de su dueño; no lleva ``program_ids`` propios
porque duplicaría la verdad que ya vive en ``ProgramPosition``.

Las franjas NO se materializan
------------------------------
Se derivan de ``(start_time, end_time, slot_minutes)`` en `SlotService`. Sin
tabla de slots no hay nada que mantener ni que desincronizar; el precio es que
cambiar ``slot_minutes`` con citas dentro deja citas fuera de la rejilla, y eso
la UI lo muestra en una banda «Fuera de la rejilla» en vez de esconderlo.

Ojo con la UNIQUE
-----------------
``(review_day_id, owner_user_id, start_time)`` impide repetir hora de inicio,
pero **no** impide ventanas SOLAPADAS del mismo dueño (09:00-12:00 junto a
10:00-14:00). Eso lo valida `ReviewWindowService.assert_no_overlap` bajo el
mismo lock, porque la alternativa (``EXCLUDE USING gist``) exige `btree_gist`,
que no está instalado.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    String, Time, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class ReviewWindow(Base):
    __tablename__ = "titulatec_review_windows"
    __table_args__ = (
        UniqueConstraint("review_day_id", "owner_user_id", "start_time",
                         name="uq_titulatec_review_windows_day_user_start"),
        CheckConstraint("end_time > start_time",
                        name="ck_titulatec_review_windows_time_order"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 480",
                        name="ck_titulatec_review_windows_slot_minutes"),
        CheckConstraint("capacity >= 1",
                        name="ck_titulatec_review_windows_capacity"),
        Index("ix_titulatec_review_windows_day_user",
              "review_day_id", "owner_user_id"),
    )

    id = Column(Integer, primary_key=True)
    # RESTRICT y no CASCADE: borrar un día no puede borrar la cita de un alumno.
    # Por eso el día se CIERRA (`is_closed`) en vez de borrarse.
    review_day_id = Column(
        Integer, ForeignKey("titulatec_cohort_review_days.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    owner_user_id = Column(BigInteger, ForeignKey("core_users.id"),
                           nullable=False, index=True)
    owner_position_id = Column(Integer, ForeignKey("core_positions.id"), nullable=True)

    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    slot_minutes = Column(Integer, nullable=False, server_default=text("30"))
    capacity = Column(Integer, nullable=False, server_default=text("1"))   # POR FRANJA
    location = Column(String(120), nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'open'"))  # open|paused
    note = Column(String(255), nullable=True)

    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=func.now())

    review_day = relationship("CohortReviewDay", back_populates="windows")
    appointments = relationship("ReviewAppointment", back_populates="window")

    def __repr__(self) -> str:
        return (f"<ReviewWindow d{self.review_day_id} u{self.owner_user_id} "
                f"{self.start_time}-{self.end_time} "
                f"/{self.slot_minutes}min x{self.capacity}>")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "review_day_id": self.review_day_id,
            "owner_user_id": self.owner_user_id,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "slot_minutes": self.slot_minutes,
            "capacity": self.capacity,
            "location": self.location,
            "status": self.status,
        }

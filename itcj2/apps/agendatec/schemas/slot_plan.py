"""Estructuras del plan de re-división de un rango horario.

Todas guardan PRIMITIVOS, no objetos ORM: `/preview` hace rollback antes de
serializar el plan, y objetos expirados reventarían al leerlos.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import List, Tuple


@dataclass
class SplitOffender:
    """Slot reservado que impide la re-división.

    `reason` es lo que la UI traduce a un mensaje concreto, para que el
    coordinador no tenga que adivinar por qué se rechazó.
    """

    slot_id: int
    start: time
    end: time
    reason: str          # "not_on_grid" | "does_not_fit" | "would_grow"


@dataclass
class KeptAsIs:
    """Slot reservado que NO admite la duración nueva y se deja intacto.

    Ocurre cuando la duración pedida es mayor o igual a la que ya tiene:
    acortarlo es imposible y alargarlo pisaría el siguiente. En vez de rechazar
    el rango entero, ese bloque conserva su geometría y el resto sí se
    re-divide. El preview los lista para que el coordinador sepa qué no cambió.
    """

    slot_id: int
    start: time
    end: time
    current_minutes: int


@dataclass
class ShortenedSlot:
    """Slot reservado que cambia de duración.

    `slot_id` es obligatorio: `apply_split` localiza el slot por PK, nunca por
    (coordinator_id, day, start_time). El `uq_time_slot` del DDL no existe en
    la BD real, así que esa terna puede estar duplicada y un `.one()` reventaría
    con MultipleResultsFound — con el advisory lock tomado.
    """

    slot_id: int
    old_start: time
    old_end: time
    new_start: time
    new_end: time


@dataclass
class AffectedAppointment:
    """Cita SCHEDULED cuyo horario cambia. Subconjunto de ShortenedSlot.

    Se separa a propósito: un slot con cita DONE o NO_SHOW sigue con
    is_booked=True y DEBE acortarse, pero NO debe notificarse. Colapsar ambos
    conceptos haría que esos rangos nunca se re-dividieran y que /preview
    reportara más slots creados de los que el POST realmente crea.
    """

    slot_id: int
    appointment_id: int
    request_id: int
    student_id: int
    student_name: str
    program_name: str
    old_start: time
    old_end: time
    new_start: time
    new_end: time


@dataclass
class SplitPlan:
    """Qué haría el split. No muta nada.

    Base común de `POST /coord/day-config` y de su `/preview`, para que no
    puedan divergir.
    """

    start_efectivo: time
    end: time
    new_minutes: int
    to_shorten: List[ShortenedSlot] = field(default_factory=list)        # TODOS los que cambian
    to_notify: List[AffectedAppointment] = field(default_factory=list)   # solo los SCHEDULED
    kept_as_is: List[KeptAsIs] = field(default_factory=list)             # no admiten la duración
    to_delete_ids: List[int] = field(default_factory=list)
    to_create: List[Tuple[time, time]] = field(default_factory=list)
    occupied: List[Tuple[time, time]] = field(default_factory=list)      # huecos que la grilla salta
    preserved_with_history: List[int] = field(default_factory=list)
    offenders: List[SplitOffender] = field(default_factory=list)
    out_of_scope: List[AffectedAppointment] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.offenders)


@dataclass
class SplitResult:
    """Lo que efectivamente ocurrió al aplicar el plan."""

    slots_created: int = 0
    slots_deleted: int = 0
    slots_shortened: int = 0
    affected: List[AffectedAppointment] = field(default_factory=list)

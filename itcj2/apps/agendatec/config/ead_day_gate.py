"""TEMPORAL — días reservados a una modalidad concreta (periodo ago-2026).

TODO(retirar tras el periodo 20263): este módulo entero es un parche de ciclo.
Borrarlo y quitar sus 3 llamadas (`api/availability.py` x2,
`services/request_service.py` x1) devuelve el sistema a "los días los decide
la configuración de cada coordinador", que es el comportamiento correcto y el
que ya implementa el filtro por carrera de `list_days_for_program`.

Contexto: en el periodo 20263 la institución habilitó el **sábado 29 de agosto
de 2026 en exclusiva para altas/bajas de EAD**, mientras que los días entre
semana son para el resto de las modalidades. El filtro genérico por carrera
("solo muestro un día si el coordinador configuró horarios para tu carrera")
refleja esa política solo si TODOS los coordinadores configuran bien; este
candado la impone aunque alguien se equivoque al configurar.

Regla, en las dos direcciones:

    carrera EAD      -> SOLO los días de `_EAD_ONLY_DAYS`
    carrera NO EAD   -> NUNCA los días de `_EAD_ONLY_DAYS`

Se aplica en los tres puntos donde un día puede filtrarse hacia el alumno
(lista de días, lista de horarios de un día, y la validación del slot al
crear la cita) para que el candado sea real y no cosmético: un POST armado a
mano contra `/requests` topa con la misma regla que el botón que se ocultó.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

# Días que pertenecen EN EXCLUSIVA a las carreras EAD. Vacío ⇒ candado inerte
# (todo lo de abajo se vuelve la identidad) y el sistema queda solo con el
# filtro genérico por configuración del coordinador.
_EAD_ONLY_DAYS: frozenset[date] = frozenset({
    date(2026, 8, 29),
})

# Marca de modalidad en `core_programs.name`. Se compara el ÚLTIMO token, no un
# `endswith("EAD")` a secas: así "…EAD" cuenta y un futuro "Ing. …EADX" o una
# carrera que casualmente termine en esas 3 letras no se cuela.
_EAD_TOKEN = "EAD"


def is_ead_program(program_name: str | None) -> bool:
    """¿El nombre de la carrera la marca como modalidad EAD?

    Un nombre ausente o vacío cuenta como NO-EAD: es la dirección conservadora
    (no le abre el día exclusivo a una carrera que no se pudo identificar).
    """
    if not program_name:
        return False
    tokens = program_name.strip().split()
    return bool(tokens) and tokens[-1].upper() == _EAD_TOKEN


def day_allowed_for_program(day: date, program_name: str | None) -> bool:
    """¿Puede esta carrera usar este día?

    Fuera de `_EAD_ONLY_DAYS` no opina: devuelve True y deja que decidan el
    periodo habilitado y la configuración del coordinador.
    """
    if day in _EAD_ONLY_DAYS:
        return is_ead_program(program_name)
    return not is_ead_program(program_name)


def filter_days_for_program(days: Iterable[date], program_name: str | None) -> list[date]:
    """Aplica `day_allowed_for_program` a un iterable de días. Devuelve ordenado."""
    return sorted(d for d in days if day_allowed_for_program(d, program_name))

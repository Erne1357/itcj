"""«AAAA-MM-DD» del `<input type=date>` del respaldo «Constancia previa…» (D9).

m36 (`triage-minors.md`): antes vivía TRIPLICADO como `_parse_issued_on` en
`pages/admin.py`, `pages/appointments.py` y `pages/library_admin.py` -- las
tres rutas de respaldo «Constancia previa…» (expediente, panel de atender y
bandeja de Biblioteca). Comparados byte a byte (diff de los tres cuerpos
antes de mover nada): los tres eran gemelos EXACTOS -mismo `strip()`, mismo
`None` con el campo vacío, mismo `ValueError` con el mismo mensaje en una
fecha que no parsea-, así que no hubo que elegir "el más estricto": ninguno
difería del otro, y ningún llamador cambia de comportamiento al centralizar.
"""
from __future__ import annotations

from datetime import date


def parse_issued_on(raw: str | None) -> date | None:
    """«AAAA-MM-DD» -> `date`, o `None` si viene vacío (el service dice
    «Escribe la fecha...», con su propio mensaje). Texto que no es una fecha
    ISO real -campo manipulado a mano- cae en un mensaje propio, igual de
    legible."""
    texto = (raw or "").strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ValueError("La fecha de la constancia previa no es válida.")

"""Fechas en español de ventanilla, sin depender del locale del proceso.

`calendar.day_name` y `%B` salen en el locale del proceso, que en el contenedor
es `C` y devuelve "Monday"/"September" en una UI en español. Las listas van
escritas a mano por eso.

Este módulo nace con el rediseño de la inscripción pública (2026-09-17). Hay
dos copias previas de las mismas listas, en `pages/appointments.py:56` y en
`pages/admin.py:991` (esta última abreviada); **no se tocan aquí** porque el
alcance de ese cambio es otro. Si alguna vez se consolidan, este es el destino.
"""
from __future__ import annotations

from datetime import date

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dia_mes(d: date) -> str:
    """'28 de septiembre'. El año se omite: lo pone `dia_largo` cuando importa."""
    return f"{d.day} de {MESES[d.month]}"


def dia_largo(d: date, *, hoy: date | None = None) -> str:
    """'lunes 28 de septiembre'.

    Añade el año SOLO si no es el año en curso: "lunes 28 de septiembre de 2027".
    Un año repetido en cada fecha es ruido; un año distinto callado es un error
    que el egresado paga viniendo el día equivocado.
    """
    hoy = hoy or date.today()
    base = f"{DIAS[d.weekday()]} {dia_mes(d)}"
    return base if d.year == hoy.year else f"{base} de {d.year}"


def faltan_dias(d: date, *, hoy: date | None = None) -> int:
    """Días completos de hoy a `d`. Negativo si ya pasó."""
    return (d - (hoy or date.today())).days


def cuenta_regresiva(d: date, *, hoy: date | None = None) -> str:
    """'Mañana' · 'Faltan 11 días' · '' si la fecha ya pasó o es hoy.

    Cadena vacía cuando no hay nada que contar: la plantilla decide si pinta la
    pastilla con `{% if %}`, en vez de mostrar "Faltan 0 días".
    """
    n = faltan_dias(d, hoy=hoy)
    if n <= 0:
        return ""
    if n == 1:
        return "Mañana"
    return f"Faltan {n} días"

"""Fechas en español de ventanilla, sin depender del locale del proceso.

`calendar.day_name` y `%B` salen en el locale del proceso, que en el contenedor
es `C` y devuelve "Monday"/"September" en una UI en español. Las listas van
escritas a mano por eso.

Este módulo nace con el rediseño de la inscripción pública (2026-09-17). Hay
dos copias previas de las mismas listas, en `pages/appointments.py:56` y en
`pages/admin.py:991` (esta última abreviada); **no se tocan aquí** porque el
alcance de ese cambio es otro. Si alguna vez se consolidan, este es el destino.

Con hora (spec 2026-09-27 §B3): la ventana de la convocatoria pasó de `Date` a
`DateTime`, así que todo lo de aquí acepta `date` o `datetime`. «Ahora» es
`db_now()` —hora local de `APP_TZ`, la misma que guarda la base—, nunca el
reloj del proceso.
"""
from __future__ import annotations

from datetime import date, datetime

from itcj2.core.utils.timezone import db_now

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _fecha(d: date | datetime) -> date:
    """La fecha de un `date` o de un `datetime` (sin la hora)."""
    return d.date() if isinstance(d, datetime) else d


def dia_mes(d: date | datetime) -> str:
    """'28 de septiembre'. El año se omite: lo pone `dia_largo` cuando importa."""
    d = _fecha(d)
    return f"{d.day} de {MESES[d.month]}"


def dia_largo(d: date | datetime, *, hoy: date | None = None) -> str:
    """'lunes 28 de septiembre'.

    Añade el año SOLO si no es el año en curso: "lunes 28 de septiembre de 2027".
    Un año repetido en cada fecha es ruido; un año distinto callado es un error
    que el egresado paga viniendo el día equivocado.
    """
    d = _fecha(d)
    hoy = hoy or db_now().date()
    base = f"{DIAS[d.weekday()]} {dia_mes(d)}"
    return base if d.year == hoy.year else f"{base} de {d.year}"


def hora(dt: datetime) -> str:
    """'14:00'. Sin segundos: el cierre por omisión (23:59:59) se lee '23:59'."""
    return f"{dt.hour:02d}:{dt.minute:02d}"


def dia_mes_hora(dt: datetime) -> str:
    """'12 de octubre a las 14:00'."""
    return f"{dia_mes(dt)} a las {hora(dt)}"


def faltan_dias(d: date | datetime, *, hoy: date | None = None) -> int:
    """Días de calendario de hoy a la fecha de `d`. Negativo si ya pasó."""
    return (_fecha(d) - (hoy or db_now().date())).days


def cuenta_regresiva(d: date | datetime, *, ahora: datetime | None = None) -> str:
    """'Faltan 11 días' · 'Mañana' · 'Hoy a las 14:00' · '' si ya pasó.

    Los días se cuentan por FECHA, no por bloques de 24 horas: abrir el día 11 a
    las 00:00 es «Faltan 11 días» aunque falten 10 días y unas horas, igual que
    con un `date`. Con `datetime`, el mismo día y todavía en el futuro se dice
    la hora («Hoy a las 23:59»); con `date` no hay hora que decir y «hoy» es
    cadena vacía, como siempre.

    Cadena vacía cuando no hay nada que contar: la plantilla decide si pinta la
    pastilla con `{% if %}`, en vez de mostrar "Faltan 0 días".
    """
    ahora = ahora or db_now()
    n = faltan_dias(d, hoy=ahora.date())
    if isinstance(d, datetime):
        if d <= ahora:
            return ""
        if n == 0:
            return f"Hoy a las {hora(d)}"
    elif n <= 0:
        return ""
    if n == 1:
        return "Mañana"
    return f"Faltan {n} días"

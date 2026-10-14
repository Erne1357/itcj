"""Dias habiles (lunes a viernes) para el ritmo y el pronostico del tablero.

Puro: sin BD ni calendario de feriados. El pronostico lo dice con todas sus
letras («sin contar feriados»), asi que aqui un dia habil es solo lun-vie.
"""
from __future__ import annotations

from datetime import date, timedelta


def is_business_day(d: date) -> bool:
    """Lunes a viernes."""
    return d.weekday() < 5


def add_business_days(d: date, n: int) -> date:
    """El `n`-esimo dia habil ESTRICTAMENTE posterior a `d` (n >= 1).

    Sabado + 1 = lunes, viernes + 1 = lunes, lunes + 1 = martes.
    `n == 0` devuelve `d` si es habil y, si no, el siguiente habil.
    """
    if n < 0:
        raise ValueError("n debe ser >= 0")
    if n == 0:
        while not is_business_day(d):
            d += timedelta(days=1)
        return d
    restantes = n
    while restantes > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            restantes -= 1
    return d


def last_business_days(today: date, n: int) -> list[date]:
    """Los `n` dias habiles que terminan en `today` (o en el habil anterior si
    `today` es fin de semana), en orden ascendente."""
    dias: list[date] = []
    d = today
    while len(dias) < n:
        if is_business_day(d):
            dias.append(d)
        d -= timedelta(days=1)
    dias.reverse()
    return dias

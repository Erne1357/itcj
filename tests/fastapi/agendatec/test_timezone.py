"""Las comparaciones de hora deben ser aware, en America/Ciudad_Juarez.

El proceso corre en UTC dentro del contenedor. Comparar `datetime.now()` naive
contra horas de slot locales desplaza los guards 6 o 7 horas según el horario
de verano — que es lo que hacía `slot_time_passed` rechazar o aceptar rangos
incorrectos.
"""
from datetime import date, datetime, time

from itcj2.apps.agendatec.helpers import app_dt, get_app_tz, now_app


def test_now_app_is_aware():
    n = now_app()
    assert n.tzinfo is not None, "now_app() debe devolver un datetime aware"


def test_now_app_uses_app_tz():
    assert now_app().utcoffset() == datetime.now(get_app_tz()).utcoffset()


def test_app_tz_is_utc_minus_6_in_summer():
    """Cd. Juárez conserva el DST de EEUU: en agosto es MDT (UTC-06:00).

    Es el bug que tenía periods.js hardcodeando -07:00.
    """
    agosto = app_dt(date(2026, 8, 15), time(12, 0))
    assert agosto.utcoffset().total_seconds() == -6 * 3600


def test_app_tz_is_utc_minus_7_in_winter():
    enero = app_dt(date(2026, 1, 15), time(12, 0))
    assert enero.utcoffset().total_seconds() == -7 * 3600


def test_app_dt_is_comparable_with_now_app():
    """El motivo de que exista app_dt(): comparar contra un naive lanza TypeError."""
    slot_start = app_dt(date(2026, 9, 1), time(9, 0))
    assert (now_app() > slot_start) in (True, False)   # no debe lanzar


def test_naive_combine_would_raise():
    """Documenta por qué no basta con datetime.combine()."""
    naive = datetime.combine(date(2026, 9, 1), time(9, 0))
    try:
        now_app() > naive
    except TypeError:
        return
    raise AssertionError("se esperaba TypeError al comparar aware contra naive")

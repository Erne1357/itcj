"""`utils/dates_es.py` con hora: la ventana de la convocatoria pasó de `Date` a
`DateTime` (spec 2026-09-27 §B3).

Sin BD ni TestClient: son funciones puras. `ahora`/`hoy` se pasan explícitos
para que ninguna aserción dependa del reloj del proceso.

Contrato de `cuenta_regresiva` con `datetime`:

- «Faltan N días» cuando la FECHA está a 2 o más días de la de `ahora` (mismo
  cómputo por fecha que la versión con `date`: abrir el día 11 a las 00:00 es
  «Faltan 11 días» aunque sean 10 días y unas horas).
- «Mañana» si cae en la fecha de mañana.
- «Hoy a las HH:MM» si es hoy y todavía no pasa.
- `""` si ya pasó: la plantilla decide con `{% if %}` si pinta la pastilla.
"""
from datetime import date, datetime

import pytest

from itcj2.apps.titulatec.utils.dates_es import (
    cuenta_regresiva, dia_largo, dia_mes, dia_mes_hora, hora,
)

AHORA = datetime(2026, 10, 5, 10, 30)          # lunes 5 de octubre, 10:30


# ---------------------------------------------------------------------------
# hora / dia_mes_hora
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dt,esperado", [
    (datetime(2026, 10, 12, 14, 0), "14:00"),
    (datetime(2026, 10, 12, 9, 5), "09:05"),
    (datetime(2026, 10, 12, 0, 0), "00:00"),
    # El cierre por omisión se guarda a las 23:59:59 y se LEE «23:59».
    (datetime(2026, 10, 12, 23, 59, 59), "23:59"),
])
def test_hora(dt, esperado):
    assert hora(dt) == esperado


def test_dia_mes_hora():
    assert dia_mes_hora(datetime(2026, 10, 12, 14, 0)) == "12 de octubre a las 14:00"
    assert dia_mes_hora(datetime(2026, 10, 12, 23, 59, 59)) == (
        "12 de octubre a las 23:59")


# ---------------------------------------------------------------------------
# dia_mes / dia_largo aceptan date y datetime
# ---------------------------------------------------------------------------
def test_dia_mes_y_dia_largo_aceptan_datetime_y_usan_su_fecha():
    dt = datetime(2026, 10, 5, 9, 0)

    assert dia_mes(dt) == dia_mes(dt.date()) == "5 de octubre"
    assert dia_largo(dt, hoy=date(2026, 9, 27)) == "lunes 5 de octubre"
    assert dia_largo(dt, hoy=date(2025, 9, 27)) == "lunes 5 de octubre de 2026"


# ---------------------------------------------------------------------------
# cuenta_regresiva con datetime: los cuatro casos
# ---------------------------------------------------------------------------
def test_cuenta_regresiva_con_datetime_faltan_n_dias():
    assert cuenta_regresiva(datetime(2026, 10, 16, 0, 0), ahora=AHORA) == (
        "Faltan 11 días")
    assert cuenta_regresiva(datetime(2026, 10, 7, 9, 0), ahora=AHORA) == (
        "Faltan 2 días")


def test_cuenta_regresiva_con_datetime_manana_es_por_fecha_no_por_24_horas():
    # Mañana a las 00:00 son 13 h y media, y mañana 23:59:59 son más de 24 h:
    # las dos son «Mañana» porque caen en la fecha de mañana.
    assert cuenta_regresiva(datetime(2026, 10, 6, 0, 0), ahora=AHORA) == "Mañana"
    assert cuenta_regresiva(datetime(2026, 10, 6, 23, 59, 59), ahora=AHORA) == "Mañana"


def test_cuenta_regresiva_con_datetime_hoy_a_las():
    assert cuenta_regresiva(datetime(2026, 10, 5, 14, 0), ahora=AHORA) == (
        "Hoy a las 14:00")
    assert cuenta_regresiva(datetime(2026, 10, 5, 23, 59, 59), ahora=AHORA) == (
        "Hoy a las 23:59")


def test_cuenta_regresiva_con_datetime_ya_paso_es_vacia():
    assert cuenta_regresiva(datetime(2026, 10, 5, 10, 0), ahora=AHORA) == ""
    assert cuenta_regresiva(datetime(2026, 10, 1, 23, 59, 59), ahora=AHORA) == ""
    assert cuenta_regresiva(AHORA, ahora=AHORA) == "", "el instante exacto ya no cuenta"


def test_cuenta_regresiva_por_omision_usa_db_now(monkeypatch):
    """Sin `ahora`, el reloj es `db_now()` (hora local de APP_TZ), no el del
    proceso."""
    import itcj2.apps.titulatec.utils.dates_es as mod

    monkeypatch.setattr(mod, "db_now", lambda: AHORA)

    assert cuenta_regresiva(datetime(2026, 10, 5, 14, 0)) == "Hoy a las 14:00"
    assert cuenta_regresiva(date(2026, 10, 6)) == "Mañana"


# ---------------------------------------------------------------------------
# cuenta_regresiva con date: compatibilidad
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("d,esperado", [
    (date(2026, 10, 16), "Faltan 11 días"),
    (date(2026, 10, 7), "Faltan 2 días"),
    (date(2026, 10, 6), "Mañana"),
    (date(2026, 10, 5), ""),          # hoy: nada que contar (como siempre)
    (date(2026, 10, 1), ""),
])
def test_cuenta_regresiva_con_date_conserva_el_comportamiento(d, esperado):
    assert cuenta_regresiva(d, ahora=AHORA) == esperado

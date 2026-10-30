from datetime import date, datetime
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.importacion.normaliza import (
    NoInterpretable, mapear_carrera, parse_bandera, parse_control, parse_fechas, parse_importes,
)


@pytest.mark.parametrize("raw, esperado", [
    (datetime(2026, 1, 23), [date(2026, 1, 23)]),
    ("12 de enero de 2026", [date(2026, 1, 12)]),
    ("13  de septiembre 2024", [date(2024, 9, 13)]),
    ("29 de febrero", [date(2024, 2, 29)]),
    ("14/01/2025, 20/01/25, 27/01/25", [date(2025, 1, 14), date(2025, 1, 20), date(2025, 1, 27)]),
    ("16 de agosto de 2024       30 de agosto de 2024", [date(2024, 8, 16), date(2024, 8, 30)]),
    (45679, [date(2025, 1, 22)]),
    (None, []),
])
def test_fechas(raw, esperado):
    assert parse_fechas(raw, anio=2024) == esperado


@pytest.mark.parametrize("raw, esperado", [
    (3150, [D("3150.00")]), ("$1,550,00", [D("1550.00")]), ("$3,.000.00", [D("3000.00")]),
    ("$1,500", [D("1500.00")]), ("$9,461.00", [D("9461.00")]),
    ("$1,100,00  $1,000,00   $1,000,00", [D("1100.00"), D("1000.00"), D("1000.00")]), (None, []),
])
def test_importes(raw, esperado):
    assert parse_importes(raw) == esperado


@pytest.mark.parametrize("raw, motivo", [("Prórroga cancelada", "importe ilegible"), ("ayer", "fecha ilegible")])
def test_no_interpretable(raw, motivo):
    with pytest.raises(NoInterpretable) as e:
        (parse_importes if motivo == "importe ilegible" else lambda r: parse_fechas(r, anio=2025))(raw)
    assert e.value.motivo == motivo


def test_bandera_y_control():
    assert parse_bandera(1) is True and parse_bandera(None) is True and parse_bandera("") is True
    assert parse_bandera(0) is False
    for malo in (-1, ".", " x"):
        with pytest.raises(NoInterpretable):
            parse_bandera(malo)
    assert parse_control(22111234) == "22111234" and parse_control(" d21111234 ") == "D21111234"
    with pytest.raises(NoInterpretable):
        parse_control(12345)


def test_carreras():
    assert mapear_carrera("Ingeniería  Industrial") == "Ing. Industrial"
    assert mapear_carrera("Ingeniería en Gestion Empresarial") == "Ing. Gestión Empresarial"
    assert mapear_carrera("TIC´S") == mapear_carrera("TIC'S") == "Ing. Tics"


def test_carrera_sin_equivalencia_es_problema():  # Review Focus 3
    with pytest.raises(NoInterpretable) as e:
        mapear_carrera("Ingeniería Espacial")
    assert e.value.motivo == "carrera sin equivalencia"

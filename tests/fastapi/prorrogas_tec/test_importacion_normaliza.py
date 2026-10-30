from datetime import date, datetime
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.importacion.normaliza import (
    NoInterpretable, mapear_carrera, normalizar, parse_bandera, parse_control, parse_fechas, parse_importes,
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


@pytest.mark.parametrize("raw", ["1.5", "1,5", "12.5", "1,", "1,55,000", "$", "0", "12345678901"])
def test_importes_ilegibles(raw):
    with pytest.raises(NoInterpretable) as e:
        parse_importes(raw)
    assert e.value.motivo == "importe ilegible"


@pytest.mark.parametrize("raw, esperado", [
    ("1,500", [D("1500.00")]), ("1.550,00", [D("1550.00")]), ("$3,.000.00", [D("3000.00")]),
    ("$999.99             $9,999.99", [D("999.99"), D("9999.99")]),
])
def test_importes_validos(raw, esperado):
    assert parse_importes(raw) == esperado


@pytest.mark.parametrize("raw, anio", [("29 de febrero", 2025), ("32/01/2025", 2025), ("1/1/202", 2025),
                                       ("1/1/1999", 2025)])
def test_fechas_ilegibles(raw, anio):
    with pytest.raises(NoInterpretable) as e:
        parse_fechas(raw, anio=anio)
    assert e.value.motivo == "fecha ilegible"


def test_banderas_con_espacios():
    assert parse_bandera("1 ") is True and parse_bandera(" ") is True


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), 22111234.5])
def test_control_float_invalido(raw):
    with pytest.raises(NoInterpretable) as e:
        parse_control(raw)
    assert e.value.motivo == "número de control inválido"


def test_apostrofos():
    assert normalizar("TIC´S") == normalizar("TIC'S") == normalizar("TIC’S")
    assert mapear_carrera("Ingeniería en TIC'S") == "Ing. Tics"


TABLA = [
    (["Contador Público"], "Contador publico"),
    (["Doctorado en Ciencias de la Ingeniería"], "Doctorado en Ciencias de la Ingeniería"),
    (["Ingeniería Electromecánica"], "Electromecánica"),
    (["Ingeniería Electrónica", "Ingeniería en Electrónica"], "Electrónica"),
    (["Ingeniería Eléctrica"], "Eléctrica"),
    (["Ingeniería Industrial", "Ingeniería Industrial (Curso de verano)"], "Ing. Industrial"),
    (["Ingeniería Industrial EAD"], "Ing. Industrial EAD"),
    (["Ingeniería Mecánica"], "Mecánica"),
    (["Ingeniería en Ciberseguridad"], "Ciberseguridad"),
    (["Ingeniería en Gestión Empresarial"], "Ing. Gestión Empresarial"),
    (["Ingeniería en Gestión Empresarial EAD", "Ingeniería en Gestión Empresaria EAD",
      "Ingeniería en Gestíon Empresarial EAD"], "Ing. Gestión Empresarial EAD"),
    (["Ingeniería en Logística"], "Ing. Logistica"),
    (["Ingeniería en Mecatrónica"], "Mecatrónica"),
    (["Ingeniería en Semiconductores"], "Semiconductores"),
    (["Ingeniería en Sistemas Computacionales", "Ingenierpia en Sistemas Computacionales"],
     "Ing. Sistemas computacionales"),
    (["Ingeniería en Sistemas Computacionales EAD"], "Ing. Sistemas computacionales EAD"),
    (["TIC'S", "TIC´S", "Ingeniería en TIC´S"], "Ing. Tics"),
    (["Licenciatura en Administración", "Licenciatura en Administración de Empresas"], "Lic. Administracion"),
    (["Maestría en Ingeniería Administrativa"], "Maestría en Ingeniería Administrativa"),
    (["Maestría en Ingeniería Industrial"], "Maestría en Ingeniería Industrial"),
    (["Maestría en Negocios Internacionales"], "Maestría en Administración de Negocios Internacionales"),
]


def test_toda_la_tabla_de_carreras():
    for variantes, oficial in TABLA:
        for v in variantes:
            assert mapear_carrera(v) == oficial

from datetime import date
from io import BytesIO

import pytest
from PIL import Image

from itcj2.apps.prorrogas_tec.documents.catalog import (
    COMMON_FIELDS, DOC_TYPES, sample_signature_png, sample_values,
)


def test_hay_seis_formatos_en_orden():
    assert list(DOC_TYPES) == ["formato_solicitud", "carta_aceptacion", "carta_rechazo",
                               "carta_compromiso_1", "carta_compromiso_2", "carta_compromiso_3"]


@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_obligatorios_imagenes_y_comunes_son_permitidos(code):
    t = DOC_TYPES[code]
    assert t.required <= t.allowed and t.images <= t.allowed and COMMON_FIELDS <= t.allowed


def test_compromiso_de_dos_pagos():
    t = DOC_TYPES["carta_compromiso_2"]
    assert {"pago1_monto", "pago1_fecha", "pago2_monto", "pago2_fecha", "firma_estudiante"} <= t.required
    assert "pago3_fecha" not in t.allowed


def test_compromiso_de_un_pago_no_exige_el_monto_del_pago():
    t = DOC_TYPES["carta_compromiso_1"]
    assert "pago1_fecha" in t.required and "pago1_monto" in t.allowed - t.required


def test_rechazo_exige_motivo():
    assert DOC_TYPES["carta_rechazo"].required == frozenset({"nombre", "no_control", "motivo_rechazo"})


@pytest.mark.parametrize("code", list(DOC_TYPES))
def test_los_datos_de_ejemplo_cubren_todo_lo_permitido(code):
    values, images = sample_values(code, today=date(2026, 1, 13))
    assert DOC_TYPES[code].allowed <= set(values) | set(images)


def test_ejemplo_de_tres_pagos_reparte_3650():
    values, _ = sample_values("carta_compromiso_3", today=date(2026, 1, 13))
    assert [values[f"pago{i}_monto"] for i in (1, 2, 3)] == ["$1,217.00", "$1,217.00", "$1,216.00"]
    assert values["pago1_fecha"] == "13 de febrero de 2026" and values["fecha"] == "13/enero/2026"


def test_la_firma_de_ejemplo_es_un_png():
    assert Image.open(BytesIO(sample_signature_png())).format == "PNG"

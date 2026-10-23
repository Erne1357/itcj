"""Validación pura del Formato B (spec §5.1). Sin BD."""
from datetime import date

import pytest

from itcj2.apps.titulatec.services.format_b_validation import (
    EDITABLE_FIELDS,
    FIELD_LABELS,
    FormatBValidationError,
    ValidationCtx,
    normalize_phone,
    validate_all,
    validate_step,
)

CTX = ValidationCtx(today=date(2026, 10, 21), modality_ids=frozenset({1, 2, 3, 4}), requires_project=True)

STEP1 = {
    "gender": "female", "age": "24", "mobile_phone": "6561234567", "phone": "",
    "postal_code": "32000", "neighborhood": "Centro", "street": "Av. Juarez",
    "ext_number": "123", "int_number": "",
}
STEP2 = {"modality_id": "2", "study_plan": "isic-2010-224", "admission_date": "2019-08", "graduation_date": "2024-12"}
STEP3 = {"project_name": "Sistema de gestion de titulacion"}


def _errs(step, raw, ctx=CTX):
    return validate_step(step, raw, ctx)[1]


def test_editable_fields_exactos():
    assert EDITABLE_FIELDS == {
        1: ("gender", "age", "mobile_phone", "phone", "postal_code", "neighborhood", "street", "ext_number", "int_number"),
        2: ("modality_id", "study_plan", "admission_date", "graduation_date"),
        3: ("project_name",),
    }
    assert FIELD_LABELS["first_name"] == "Nombre(s)"
    assert FIELD_LABELS["modality_id"] == "Tipo de titulación"
    assert FIELD_LABELS["program_id"] == "Carrera"
    for fields in EDITABLE_FIELDS.values():
        for f in fields:
            assert f in FIELD_LABELS


@pytest.mark.parametrize("step,raw", [(1, STEP1), (2, STEP2), (3, STEP3)])
def test_un_caso_valido_por_paso(step, raw):
    values, errors = validate_step(step, raw, CTX)
    assert errors == {}
    assert set(values) == set(EDITABLE_FIELDS[step])


def test_valores_normalizados_paso1():
    values, _ = validate_step(1, STEP1, CTX)
    assert values["age"] == 24 and values["phone"] is None and values["int_number"] is None


@pytest.mark.parametrize("field", ["gender", "age", "mobile_phone", "postal_code", "neighborhood", "street", "ext_number"])
@pytest.mark.parametrize("empty", ["", "   ", None])
def test_obligatorios_paso1_vacios(field, empty):
    assert field in _errs(1, {**STEP1, field: empty})


@pytest.mark.parametrize("field", ["modality_id", "study_plan", "admission_date", "graduation_date"])
@pytest.mark.parametrize("empty", ["", "  "])
def test_obligatorios_paso2_vacios(field, empty):
    assert field in _errs(2, {**STEP2, field: empty})


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_proyecto_vacio_error(empty):
    assert "project_name" in _errs(3, {"project_name": empty})


def test_genero_invalido():
    assert "gender" in _errs(1, {**STEP1, "gender": "x"})
    for g in ("male", "female", "unspecified"):
        assert _errs(1, {**STEP1, "gender": g}) == {}


@pytest.mark.parametrize("raw,expected", [
    ("(656) 123-4567", "6561234567"),
    ("+52 656 123 4567", "6561234567"),
    ("656.123.4567", "6561234567"),
    ("", None), ("   ", None), (None, None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_celular_normalizado_y_longitud():
    values, errors = validate_step(1, {**STEP1, "mobile_phone": "(656) 123-4567"}, CTX)
    assert errors == {} and values["mobile_phone"] == "6561234567"
    assert _errs(1, {**STEP1, "mobile_phone": "+52 656 123 4567"}) == {}
    assert _errs(1, {**STEP1, "mobile_phone": "12345678"})["mobile_phone"] == "El celular debe tener 10 dígitos"
    assert "mobile_phone" in _errs(1, {**STEP1, "mobile_phone": "65612abc67"})


def test_telefono_opcional():
    assert _errs(1, {**STEP1, "phone": ""}) == {}
    assert "phone" in _errs(1, {**STEP1, "phone": "123"})
    values, errors = validate_step(1, {**STEP1, "phone": "656 123 4567"}, CTX)
    assert errors == {} and values["phone"] == "6561234567"


@pytest.mark.parametrize("cp,ok", [("3200", False), ("320000", False), ("32A00", False), ("32000", True)])
def test_codigo_postal(cp, ok):
    assert (("postal_code" not in _errs(1, {**STEP1, "postal_code": cp}))) is ok


@pytest.mark.parametrize("ext,ok", [("S/N", True), ("s/n", True), ("12-A", True), ("12 B", True), ("12345678901", False), ("1#", False)])
def test_ext_number(ext, ok):
    assert ("ext_number" not in _errs(1, {**STEP1, "ext_number": ext})) is ok


def test_int_number_max_10():
    assert _errs(1, {**STEP1, "int_number": "A-12"}) == {}
    assert "int_number" in _errs(1, {**STEP1, "int_number": "x" * 11})


@pytest.mark.parametrize("age,ok", [("17", False), ("18", True), ("99", True), ("100", False), ("abc", False), ("20.5", False)])
def test_edad(age, ok):
    assert ("age" not in _errs(1, {**STEP1, "age": age})) is ok


def test_texto_largo_y_corto():
    assert "street" in _errs(1, {**STEP1, "street": "a"})
    assert "street" in _errs(1, {**STEP1, "street": "a" * 121})
    values, _ = validate_step(1, {**STEP1, "street": "  Av.   Juarez  "}, CTX)
    assert values["street"] == "Av. Juarez"


def test_study_plan_mayusculas_y_limites():
    values, errors = validate_step(2, {**STEP2, "study_plan": " isic-2010-224 "}, CTX)
    assert errors == {} and values["study_plan"] == "ISIC-2010-224"
    assert "study_plan" in _errs(2, {**STEP2, "study_plan": "a"})
    assert "study_plan" in _errs(2, {**STEP2, "study_plan": "a" * 41})


def test_fechas_a_primer_dia():
    values, _ = validate_step(2, STEP2, CTX)
    assert values["admission_date"] == date(2019, 8, 1)
    assert values["graduation_date"] == date(2024, 12, 1)
    assert values["modality_id"] == 2


def test_ingreso_igual_o_posterior_a_egreso():
    assert _errs(2, {**STEP2, "admission_date": "2024-12", "graduation_date": "2024-12"})
    assert _errs(2, {**STEP2, "admission_date": "2025-01", "graduation_date": "2024-12"})


def test_egreso_contra_hoy():
    assert "graduation_date" in _errs(2, {**STEP2, "graduation_date": "2026-11"})
    assert _errs(2, {**STEP2, "graduation_date": "2026-10"}) == {}


def test_ingreso_antes_de_1980():
    assert "admission_date" in _errs(2, {**STEP2, "admission_date": "1979-12"})
    assert "admission_date" not in _errs(2, {**STEP2, "admission_date": "1980-01"})


@pytest.mark.parametrize("bad", ["2019", "2019-13", "abcd-ef", "2019-8x"])
def test_mes_malformado(bad):
    assert "admission_date" in _errs(2, {**STEP2, "admission_date": bad})


def test_modalidad_fuera_de_catalogo():
    assert "modality_id" in _errs(2, {**STEP2, "modality_id": "99"})
    assert "modality_id" in _errs(2, {**STEP2, "modality_id": "abc"})


def test_proyecto_largo():
    assert "project_name" in _errs(3, {"project_name": "a" * 9})
    assert _errs(3, {"project_name": "a" * 10}) == {}
    assert "project_name" in _errs(3, {"project_name": "a" * 501})


def test_sin_proyecto_si_modalidad_no_lo_requiere():
    ctx = ValidationCtx(today=CTX.today, modality_ids=CTX.modality_ids, requires_project=False)
    values, errors = validate_step(3, {"project_name": ""}, ctx)
    assert errors == {} and values == {"project_name": None}


def test_requires_project_none_exige_proyecto():
    ctx = ValidationCtx(today=CTX.today, modality_ids=CTX.modality_ids, requires_project=None)
    assert "project_name" in _errs(3, {"project_name": ""}, ctx)


def _saved():
    return {
        "gender": "female", "age": 24, "mobile_phone": "6561234567", "phone": None,
        "postal_code": "32000", "neighborhood": "Centro", "street": "Av. Juarez",
        "ext_number": "123", "int_number": None,
        "modality_id": 2, "study_plan": "ISIC-2010-224",
        "admission_date": date(2019, 8, 1), "graduation_date": date(2024, 12, 1),
        "project_name": "Sistema de gestion de titulacion",
    }


def test_validate_all_ok():
    assert validate_all(_saved(), CTX) is None


def test_validate_all_primer_paso_con_error():
    vals = {**_saved(), "study_plan": None, "project_name": None}
    with pytest.raises(FormatBValidationError) as exc:
        validate_all(vals, CTX)
    assert exc.value.step == 2
    assert "study_plan" in exc.value.errors and "project_name" not in exc.value.errors
    assert isinstance(exc.value, ValueError)


def test_validate_all_paso1():
    with pytest.raises(FormatBValidationError) as exc:
        validate_all({**_saved(), "age": None}, CTX)
    assert exc.value.step == 1


def test_validate_all_sin_proyecto_requerido():
    ctx = ValidationCtx(today=CTX.today, modality_ids=CTX.modality_ids, requires_project=False)
    assert validate_all({**_saved(), "project_name": None}, ctx) is None

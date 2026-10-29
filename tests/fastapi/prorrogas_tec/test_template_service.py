import hashlib

import pytest

from itcj2.apps.prorrogas_tec.documents.catalog import default_template_path
from itcj2.apps.prorrogas_tec.services.template_service import MAX_TEMPLATE_BYTES, TemplateError, TemplateService

RECHAZO_OK = ("{{nombre}}", "{{no_control}}", "{{motivo_rechazo}}")


def _up(db, docx, *, doc_type="carta_rechazo", year=2026, filename="rechazo.docx", actor=None):
    return TemplateService.upload(db, doc_type=doc_type, year=year, filename=filename, data=docx, actor_id=actor)


def test_sube_plantilla_valida(db_session, docx_con, almacen, make_user):
    data = docx_con(*RECHAZO_OK)
    t = _up(db_session, data, actor=make_user().id)
    assert t.placeholders == ["motivo_rechazo", "no_control", "nombre"]
    assert t.sha256 == hashlib.sha256(data).hexdigest() and t.size_bytes == len(data)
    assert TemplateService.abs_path(t.file_path).read_bytes() == data
    assert t.file_path.startswith("templates/2026/carta_rechazo-")


@pytest.mark.parametrize("kwargs, data, code", [
    ({"filename": "x.docx"}, b"%PDF-1.7 no soy docx", "docx_invalido"),   # Review Focus 3
    ({"filename": "x.pdf"}, b"%PDF-1.7", "extension_invalida"),
    ({"doc_type": "otro"}, b"", "tipo_invalido"),
    ({"year": 1999}, b"", "anio_invalido"),
])
def test_rechaza_entradas_invalidas(db_session, kwargs, data, code):
    with pytest.raises(TemplateError) as e:
        _up(db_session, data, **kwargs)
    assert e.value.code == code


def test_rechaza_archivo_muy_grande_antes_de_abrirlo(db_session):
    with pytest.raises(TemplateError) as e:
        _up(db_session, b"0" * (MAX_TEMPLATE_BYTES + 1))
    assert e.value.code == "archivo_muy_grande"


def test_rechaza_errata_en_marcador(db_session, docx_con):  # Review Focus 4
    with pytest.raises(TemplateError) as e:
        _up(db_session, docx_con(*RECHAZO_OK, "{{nombr}}"))
    assert e.value.code == "placeholders_desconocidos" and e.value.detail["desconocidos"] == ["nombr"]


def test_rechaza_si_faltan_obligatorios(db_session, docx_con):
    with pytest.raises(TemplateError) as e:
        _up(db_session, docx_con("{{nombre}}", "{{no_control}}"))
    assert e.value.code == "placeholders_faltantes" and e.value.detail["faltantes"] == ["motivo_rechazo"]


# Años 2089–2095 a propósito: las pruebas corren contra la BD de dev dentro de un
# savepoint, y ahí puede haber plantillas reales COMMITEADAS de 2024–2027.
def test_resolve_anio_luego_anterior_luego_sistema(db_session, docx_con):
    data, t = TemplateService.resolve(db_session, "carta_rechazo", 2090)
    assert t is None and data == default_template_path("carta_rechazo").read_bytes()
    _up(db_session, docx_con(*RECHAZO_OK, "a"), year=2091)               # un año POSTERIOR no aplica
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1] is None
    v2089 = _up(db_session, docx_con(*RECHAZO_OK, "b"), year=2089)
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1].id == v2089.id
    _up(db_session, docx_con(*RECHAZO_OK, "c"), year=2090)
    newest = _up(db_session, docx_con(*RECHAZO_OK, "d"), year=2090)     # mismo NOW(): desempata el id
    assert TemplateService.resolve(db_session, "carta_rechazo", 2090)[1].id == newest.id


def test_years_incluye_el_actual_y_ordena_desc(db_session, docx_con):
    _up(db_session, docx_con(*RECHAZO_OK), year=2093)
    ys = TemplateService.years(db_session, current_year=2095)
    assert ys[0] == 2095 and 2093 in ys and ys == sorted(set(ys), reverse=True)

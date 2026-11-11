from datetime import date
from types import SimpleNamespace

import pytest

from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.identity import folio, institutional_email, normalize_control, nombre_corto
from itcj2.apps.prorrogas_tec.services.periods import period_for, period_label


def test_semestre_que_contiene_el_dia(db_session, periodo):
    assert period_for(db_session, date(2091, 2, 1)).id == periodo.id
    assert period_for(db_session, date(2091, 7, 1)) is None


def test_etiqueta_del_semestre(periodo):
    assert period_label(periodo) == "enero – junio 2091"


def test_correo_institucional():
    assert institutional_email("22111670") == "L22111670@cdjuarez.tecnm.mx"
    assert institutional_email("M23111966") == "M23111966@cdjuarez.tecnm.mx"
    assert institutional_email("D80060093") is None and institutional_email("B20410631") is None


def test_normaliza_y_valida_el_numero_de_control():
    assert normalize_control(" m23111966 ") == "M23111966"
    for malo in ("123", "AB12345678", ""):
        with pytest.raises(ValueError):
            normalize_control(malo)


@pytest.mark.parametrize("codigo, etiqueta, esperado", [
    ("20263", "agosto – diciembre 2026", "PR-20263-00012"),  # el código de core manda
    (None, "enero – junio 2025", "PR-20251-00012"),  # históricas sin semestre de core: de la etiqueta
    (None, "agosto – diciembre 2024", "PR-20243-00012"),
    (None, "junio – agosto 2027", "PR-20272-00012"),
    (None, "agosto 2026 – enero 2027", "PR-20263-00012"),
])
def test_folio_lleva_el_codigo_del_semestre(codigo, etiqueta, esperado):
    req = SimpleNamespace(id=12, period_id=1 if codigo else None,
                          period=SimpleNamespace(code=codigo) if codigo else None, period_label=etiqueta)
    assert folio(req) == esperado


def test_la_bitacora_rechaza_tipos_desconocidos(db_session):
    with pytest.raises(ValueError):
        log_event(db_session, event_type="inventado")


def test_semestre_ignora_los_archivados(db_session, periodo):
    from itcj2.core.models.academic_period import AcademicPeriod

    db_session.add(AcademicPeriod(code="TARCH1", name="Prórrogas archivado", start_date=date(2091, 1, 20),
                                  end_date=date(2091, 6, 10), status="ARCHIVED"))
    db_session.flush()
    assert period_for(db_session, date(2091, 2, 1)).id == periodo.id


def test_nombre_corto_para_la_barra():
    assert nombre_corto("JUAN CARLOS", "PÉREZ") == "Pérez Juan"
    assert nombre_corto("MARÍA", "DE LA CRUZ") == "De La Cruz María"
    assert [nombre_corto(None, "PÉREZ"), nombre_corto("JUAN", None), nombre_corto(None, None)] == ["Pérez", "Juan", ""]

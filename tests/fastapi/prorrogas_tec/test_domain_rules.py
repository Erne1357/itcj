from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.identity import folio, institutional_email, normalize_control
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


def test_folio():
    assert folio(12) == "PR-00012"


def test_la_bitacora_rechaza_tipos_desconocidos(db_session):
    with pytest.raises(ValueError):
        log_event(db_session, event_type="inventado")

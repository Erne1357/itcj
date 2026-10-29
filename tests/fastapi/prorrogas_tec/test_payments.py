from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.account import load
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService

HOY = date(2091, 3, 10)


def _plan(con_plan, req):
    return con_plan(req, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 4, 1))])


def test_registrar_aplica_y_recalcula(db_session, aceptada, secretaria, con_plan):
    _plan(con_plan, aceptada)
    PaymentService.record(db_session, aceptada.id, secretaria.id, folio=" C-77 ", paid_on=date(2091, 3, 1),
                          amount=D("1000"), now=HOY)
    c = load(db_session, aceptada, HOY)
    assert c.pagado == D("1000.00") and c.situacion == "al_corriente"


def test_segundo_recibo_que_excede_el_saldo_es_sobrepago(db_session, aceptada, secretaria, con_plan):  # Review Focus 1
    _plan(con_plan, aceptada)
    PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-1", paid_on=HOY, amount=D("1500"), now=HOY)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-2", paid_on=HOY, amount=D("501"), now=HOY)
    assert e.value.code == "sobrepago"


def test_folio_unico_entre_vigentes_y_reusable_tras_anular(db_session, aceptada, make_aceptada, secretaria, con_plan):  # RF 3
    otra = _plan(con_plan, make_aceptada())
    _plan(con_plan, aceptada)
    p = PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, otra.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)
    assert e.value.code == "folio_duplicado" and e.value.status == 409
    PaymentService.void(db_session, p.id, secretaria.id, motivo="Folio de otro alumno", now=HOY)
    PaymentService.record(db_session, otra.id, secretaria.id, folio="C-9", paid_on=HOY, amount=D("10"), now=HOY)


def test_anular_regresa_la_situacion(db_session, aceptada, secretaria, con_plan):  # Review Focus 2
    _plan(con_plan, aceptada)
    p = PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-3", paid_on=date(2091, 1, 20),
                              amount=D("1000"), now=HOY)
    PaymentService.void(db_session, p.id, secretaria.id, motivo="Monto equivocado", now=HOY)
    assert load(db_session, aceptada, HOY).situacion == "atrasada"
    with pytest.raises(ServiceError) as e:
        PaymentService.void(db_session, p.id, secretaria.id, motivo="otra vez", now=HOY)
    assert e.value.code == "ya_anulado"


@pytest.mark.parametrize("kw, code", [
    ({"folio": "  "}, "folio_invalido"), ({"folio": "X" * 41}, "folio_invalido"),
    ({"amount": D("0")}, "monto_invalido"), ({"paid_on": date(2091, 3, 11)}, "fecha_invalida"),
])
def test_recibo_invalido(db_session, aceptada, secretaria, con_plan, kw, code):
    _plan(con_plan, aceptada)
    datos = dict(folio="C-5", paid_on=HOY, amount=D("10"))
    datos.update(kw)
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, now=HOY, **datos)
    assert e.value.code == code


def test_sin_plan_no_hay_recibos(db_session, aceptada, secretaria):
    with pytest.raises(ServiceError) as e:
        PaymentService.record(db_session, aceptada.id, secretaria.id, folio="C-6", paid_on=HOY, amount=D("1"), now=HOY)
    assert e.value.code == "sin_plan"


def test_api_registrar_y_anular(client_as, secretaria, aceptada, con_plan):
    from itcj2.core.utils.timezone import db_now
    _plan(con_plan, aceptada)
    c = client_as(secretaria)
    e = c.post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/recibos",
               json={"folio": "C-8", "fecha": db_now().date().isoformat(), "monto": "250.50"}).json()
    rid = e["recibos"][0]["id"]
    assert e["cuenta"]["pagado"] == "250.50"
    e = c.post(f"/api/prorrogas/v2/estudiantes/{aceptada.id}/recibos/{rid}/anular", json={"motivo": "Duplicado"}).json()
    assert e["cuenta"]["pagado"] == "0.00" and e["recibos"][0]["anulado"]

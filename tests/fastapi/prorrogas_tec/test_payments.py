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


def _saldar(db, req, actor, numero, folio, dia=HOY):
    return PaymentService.settle_next(db, req.id, actor.id, numero=numero, folio=folio, paid_on=dia, now=HOY)


def test_saldar_cobra_el_siguiente_completo(db_session, aceptada, cajero, con_plan):
    _plan(con_plan, aceptada)
    pago = _saldar(db_session, aceptada, cajero, 1, " zz-100 ")
    assert (pago.folio, pago.amount, pago.recorded_by_id) == ("ZZ-100", D("1000.00"), cajero.id)
    assert load(db_session, aceptada, HOY).proxima.number == 2


def test_saldar_cobra_solo_lo_que_falta(db_session, aceptada, cajero, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 4, 1))], pagos=["400.00"])
    assert _saldar(db_session, aceptada, cajero, 1, "ZZ-101").amount == D("600.00")


def test_saldar_dos_veces_no_cobra_doble(db_session, aceptada, cajero, con_plan):  # Review Focus 1
    _plan(con_plan, aceptada)
    _saldar(db_session, aceptada, cajero, 1, "ZZ-102")
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, "ZZ-103")
    assert (e.value.code, e.value.status) == ("pago_cambio", 409)
    assert load(db_session, aceptada, HOY).pagado == D("1000.00")


@pytest.mark.parametrize("numero", [2, 9])
def test_saldar_fuera_de_orden(db_session, aceptada, cajero, con_plan, numero):
    _plan(con_plan, aceptada)
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, numero, "ZZ-104")
    assert e.value.code == "pago_cambio"


def test_saldar_sin_plan(db_session, aceptada, cajero):
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, "ZZ-105")
    assert e.value.code == "sin_plan"


def test_folio_duplicado_sin_distinguir_mayusculas(db_session, aceptada, make_aceptada, cajero, con_plan):  # Review Focus 2
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    otra = _plan(con_plan, make_aceptada())
    _plan(con_plan, aceptada)
    db_session.add(ProrrogaPayment(request_id=otra.id, folio="zz-dup", paid_on=HOY, amount=D("1")))  # captura vieja
    db_session.flush()
    with pytest.raises(ServiceError) as e:
        _saldar(db_session, aceptada, cajero, 1, " ZZ-DUP ")
    assert (e.value.code, e.value.message) == ("folio_duplicado", "Ese folio ya está registrado.")


def test_cobra_aunque_no_haya_firmado(db_session, aceptada, cajero, con_plan):
    from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
    _plan(con_plan, aceptada)
    db_session.add(ProrrogaDocument(request_id=aceptada.id, doc_type="carta_compromiso_2", version=1, context={},
                                    file_path="x.pdf", sha256="0" * 64))
    db_session.flush()
    assert _saldar(db_session, aceptada, cajero, 1, "ZZ-106").amount == D("1000.00")


@pytest.mark.parametrize("dia1, dia2, ultimo", [
    (date(2091, 3, 1), date(2091, 3, 2), 1),
    (date(2091, 3, 5), date(2091, 3, 1), 0),  # capturado después, pero pagado antes
    (date(2091, 3, 1), date(2091, 3, 1), 1),  # misma fecha: gana el id mayor
])
def test_solo_se_anula_el_ultimo(db_session, aceptada, cajero, con_plan, dia1, dia2, ultimo):
    _plan(con_plan, aceptada)
    pagos = [_saldar(db_session, aceptada, cajero, 1, "ZZ-110", dia=dia1),
             _saldar(db_session, aceptada, cajero, 2, "ZZ-111", dia=dia2)]
    with pytest.raises(ServiceError) as e:
        PaymentService.void(db_session, pagos[1 - ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    assert (e.value.code, e.value.status) == ("no_es_el_ultimo", 409)
    PaymentService.void(db_session, pagos[ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    PaymentService.void(db_session, pagos[1 - ultimo].id, cajero.id, motivo="Se capturó mal", now=HOY)
    assert load(db_session, aceptada, HOY).pagado == D("0")

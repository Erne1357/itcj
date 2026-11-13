from datetime import date, datetime
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.account import cuenta, load, load_many
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.formatting import parse_monto

PLAN = [(1, D("1217.00"), date(2091, 2, 1)), (2, D("1217.00"), date(2091, 3, 1)), (3, D("1216.00"), date(2091, 4, 1))]


def test_sin_plan():
    c = cuenta(None, [], D("0"), date(2091, 3, 1))
    assert c.situacion == "sin_plan" and c.saldo is None and c.faltantes == 0


def test_pago_parcial_cubre_en_orden_y_la_que_vence_hoy_no_atrasa():
    c = cuenta(D("3650.00"), PLAN, D("1500.00"), date(2091, 3, 1))
    assert [p.estado for p in c.parcialidades] == ["pagada", "parcial", "pendiente"]
    assert c.parcialidades[1].cubierto == D("283.00") and c.saldo == D("2150.00")
    assert c.situacion == "al_corriente" and c.faltantes == 2 and c.proxima.number == 2


def test_atrasada_desde_la_mas_vieja():
    c = cuenta(D("3650.00"), PLAN, D("0"), date(2091, 3, 2))
    assert [p.estado for p in c.parcialidades] == ["vencida", "vencida", "pendiente"]
    assert c.situacion == "atrasada" and c.vencida_desde == date(2091, 2, 1)


def test_dos_parcialidades_de_un_jalon_y_liquidada():
    assert [p.estado for p in cuenta(D("3650.00"), PLAN, D("2434.00"), date(2091, 3, 5)).parcialidades] == \
        ["pagada", "pagada", "pendiente"]
    c = cuenta(D("3650.00"), PLAN, D("3650.00"), date(2091, 5, 1))
    assert c.situacion == "liquidada" and c.faltantes == 0 and c.proxima is None


@pytest.mark.parametrize("raw", ["0", "-5", "12.345", "1,217", "abc", "NaN", None, True,
                                 "1e3", "+5", "١٢٣", "inf", "", "12.500", "123456789.00", "1e999999", 0.1 + 0.2])
def test_monto_invalido(raw):
    with pytest.raises(ServiceError) as e:
        parse_monto(raw)
    assert e.value.code == "monto_invalido"


def test_parse_monto_acepta_numero_y_cadena():
    assert parse_monto("1217.5") == D("1217.50") and parse_monto(1217) == D("1217.00")


@pytest.mark.parametrize("raw,esperado", [("12", "12.00"), (12.5, "12.50"), (D("99999999.99"), "99999999.99"),
                                          (" 12 ", "12.00")])
def test_parse_monto_validos(raw, esperado):
    assert str(parse_monto(raw)) == esperado


def test_load_many_ignora_sustituidas_y_anuladas(db_session, aceptada, make_aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("500.00", date(2091, 5, 1))], pagos=["1000.00", "200.00"])
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
    db_session.query(ProrrogaPayment).filter_by(request_id=aceptada.id, amount=D("200.00")).update(
        {"voided_at": datetime(2091, 1, 2)})
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    db_session.add(ProrrogaInstallment(request_id=aceptada.id, number=3, amount=D("777.00"),
                                       due_date=date(2020, 1, 1), superseded_at=datetime(2091, 1, 2)))
    db_session.flush()
    otra = make_aceptada()
    hoy = date(2091, 3, 1)
    cuentas = load_many(db_session, [aceptada, otra], hoy)
    assert [p.number for p in cuentas[aceptada.id].parcialidades] == [1, 2]
    assert cuentas[aceptada.id].pagado == D("1000.00") and cuentas[otra.id].situacion == "sin_plan"
    assert load(db_session, aceptada, hoy) == cuentas[aceptada.id]


def test_load_many_vacio_no_consulta_y_con_datos_usa_2_consultas(db_session, make_aceptada, con_plan):
    from sqlalchemy import event

    hoy = date(2091, 3, 1)
    reqs = [con_plan(make_aceptada(), [("100.00", date(2091, 5, 1))], pagos=["50.00"]) for _ in range(3)]
    reqs.append(make_aceptada())
    engine = db_session.get_bind()
    n = []

    def contar(*a, **kw):
        n.append(1)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        assert load_many(db_session, [], hoy) == {}
        assert n == []
        load_many(db_session, reqs, hoy)
        assert len(n) == 2
    finally:
        event.remove(engine, "before_cursor_execute", contar)

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import event

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
from itcj2.apps.prorrogas_tec.services.account import cobertura
from itcj2.apps.prorrogas_tec.services.stats_service import StatsService

PLAN = [(1, D("1000"), date(2025, 2, 1)), (2, D("1000"), date(2025, 3, 1)), (3, D("500"), date(2025, 4, 1))]
SEM_APP = "enero – junio 2091"


def test_cobertura_fifo_con_fechas():  # Review Focus 5
    recibos = [(date(2025, 1, 30), D("1500")), (date(2025, 3, 10), D("500"))]
    assert cobertura(PLAN, recibos) == [date(2025, 1, 30), date(2025, 3, 10), None]
    assert cobertura(PLAN, [(date(2025, 2, 1), D("2500"))]) == [date(2025, 2, 1)] * 3


def test_resumen_del_semestre(db_session, make_historica):
    a = make_historica(parcialidades=[("1000.00", date(2025, 2, 1)), ("1000.00", date(2025, 3, 1))], pagadas=(0,))
    make_historica(parcialidades=[("500.00", date(2025, 2, 15))], pagadas=(0,))
    r = StatsService.resumen(db_session, "enero – junio 2089", date(2096, 11, 1))
    c = r["cumplimiento"]
    assert (c["vencidas"], c["a_tiempo"], c["tarde"], c["sin_pago"], c["estudiantes_sin_pago"]) == (3, 2, 0, 1, 1)
    assert r["kpis"]["monto_total"] == "2500.00" and r["aceptacion"]["pct_aceptadas"] == 100
    assert r["total"] == 2 and a.period_label == "enero – junio 2089"
    assert r["incluye_historico"] is True  # M6


def test_resumen_hace_tres_consultas(db_session, make_historica):
    make_historica()
    n = []
    listener = lambda *a, **k: n.append(1)  # noqa: E731
    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", listener)
    try:
        StatsService.resumen(db_session, "enero – junio 2089", date(2096, 11, 1))
    finally:
        event.remove(bind, "before_cursor_execute", listener)
    assert len(n) == 3


def test_app_respuesta_rechazo_replan_y_cancelada(db_session, make_aceptada, con_plan):
    hoy = date(2096, 11, 1)
    base = StatsService.resumen(db_session, SEM_APP, hoy)["total"]
    a = make_aceptada()
    a.created_at = datetime(2091, 3, 3, 10, 0)  # sábado; su lunes es 2091-02-26
    a.decided_at = a.created_at + timedelta(days=2)
    con_plan(a, [("500.00", date(2091, 3, 10))])
    db_session.add(ProrrogaInstallment(request_id=a.id, number=2, amount=D("100"), due_date=date(2091, 3, 5),
                                       superseded_at=a.decided_at))
    r = make_aceptada()
    r.status = "rechazada"
    r.created_at = datetime(2091, 3, 4, 10, 0)
    r.decided_at = r.created_at + timedelta(days=2)
    c = make_aceptada()
    c.status = "cancelada"
    db_session.flush()
    res = StatsService.resumen(db_session, SEM_APP, hoy)
    assert res["total"] == base + 2
    assert res["kpis"]["respuesta_promedio_dias"] == 2.0
    assert res["kpis"]["replanteadas"] == 1
    assert res["incluye_historico"] is False  # M6: solo de la app
    assert res["aceptacion"] == {"aceptadas": 1, "rechazadas": 1, "pct_aceptadas": 50}
    assert res["linea"]["semanal"][0] == {"inicio": "2091-02-26", "aceptadas": 1, "rechazadas": 1}
    assert res["linea"]["mensual"][0]["mes"] == "2091-03"
    assert any(s["label"] == SEM_APP for s in StatsService.semestres(db_session)["items"])


def test_api_permiso_y_csv(client_as, secretaria, estudiante, make_historica):
    make_historica()
    c = client_as(secretaria)
    assert c.get("/api/prorrogas/v2/estadisticas/semestres").status_code == 200
    csv = c.get("/api/prorrogas/v2/estadisticas/detalle.csv", params={"semestre": "enero – junio 2089"})
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbfCarrera,")
    assert client_as(estudiante).get("/api/prorrogas/v2/estadisticas").status_code == 403

from datetime import date

import pytest

from itcj2.apps.prorrogas_tec.models.plan import ProrrogaPayment
from itcj2.core.utils.timezone import db_now

API = "/api/prorrogas/v2/caja"
PLAN = [("1000.00", date(2091, 5, 1))]


def _hoy():
    return db_now().date().isoformat()


def test_lista_y_semestres(client_as, cajero, periodo, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(cajero)
    assert c.get(f"{API}?semestre={periodo.id}").json()["items"][0]["id"] == aceptada.id
    assert periodo.id in [s["id"] for s in c.get(f"{API}/semestres").json()["items"]]


def test_saldar_y_anular(client_as, cajero, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(cajero)
    d = c.post(f"{API}/{aceptada.id}/saldar", json={"numero": 1, "folio": "zz-200", "fecha": _hoy()}).json()
    assert d["situacion"] == "liquidada" and d["pagos"][0]["recibo"]["folio"] == "ZZ-200"
    rid = d["pagos"][0]["recibo"]["id"]
    d = c.post(f"{API}/{aceptada.id}/recibos/{rid}/anular", json={"motivo": "Se capturó mal"}).json()
    assert d["situacion"] == "al_corriente" and d["pagos"][0]["recibo"] is None


def test_saldar_fuera_de_orden_da_409(client_as, cajero, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("1000.00", date(2091, 5, 1))])
    r = client_as(cajero).post(f"{API}/{aceptada.id}/saldar", json={"numero": 2, "folio": "ZZ-201", "fecha": _hoy()})
    assert r.status_code == 409 and r.json()["error"] == "pago_cambio"


def test_anular_recibo_de_otra_solicitud_es_404(client_as, cajero, db_session, aceptada, make_aceptada, con_plan):
    con_plan(aceptada, PLAN)
    otra = con_plan(make_aceptada(), PLAN, pagos=["1000.00"])
    pago = db_session.query(ProrrogaPayment).filter_by(request_id=otra.id).one()
    r = client_as(cajero).post(f"{API}/{aceptada.id}/recibos/{pago.id}/anular", json={"motivo": "Se capturó mal"})
    assert r.status_code == 404 and r.json()["error"] == "recibo_no_encontrado"


def test_fuera_de_caja_es_404(client_as, cajero, make_historica):
    h = make_historica()
    c = client_as(cajero)
    for ruta in (f"/{h.id}", f"/{h.id}/referencia.pdf", f"/{h.id}/parcialidades/1/recibo.pdf"):
        assert c.get(API + ruta).status_code == 404


def test_caja_abre_referencia_y_recibo(client_as, cajero, db_session, aceptada, con_plan):
    from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment
    from itcj2.apps.prorrogas_tec.services import storage
    from itcj2.apps.prorrogas_tec.services.reference_service import ReferenceService
    c = client_as(cajero)
    assert c.get(f"{API}/{aceptada.id}/referencia.pdf").status_code == 404
    ReferenceService.save(db_session, aceptada, b"%PDF-1.4 r", aceptada.student_id)  # antes del plan: referencia_fija
    con_plan(aceptada, PLAN)
    assert c.get(f"{API}/{aceptada.id}/referencia.pdf").content == b"%PDF-1.4 r"
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=aceptada.id, number=1).one()
    i.receipt_path = f"recibos/0/{aceptada.id}-1-abc.pdf"
    storage.write_atomic(i.receipt_path, b"%PDF-1.4 s")
    db_session.flush()
    assert c.get(f"{API}/{aceptada.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 s"


@pytest.mark.parametrize("quien", ["secretaria_sin_cobro", "lector", "estudiante"])
@pytest.mark.parametrize("metodo, ruta, cuerpo", [
    ("get", "", None), ("get", "/{id}", None), ("get", "/{id}/referencia.pdf", None),
    ("get", "/{id}/parcialidades/1/recibo.pdf", None),
    ("post", "/{id}/saldar", {"numero": 1, "folio": "ZZ-202", "fecha": "2091-01-20"}),
    ("post", "/{id}/recibos/1/anular", {"motivo": "Se capturó mal"}),
])
def test_solo_caja_entra(request, client_as, aceptada, quien, metodo, ruta, cuerpo):
    c = client_as(request.getfixturevalue(quien))
    kw = {"json": cuerpo} if cuerpo else {}
    assert getattr(c, metodo)(API + ruta.format(id=aceptada.id), **kw).status_code == 403


def test_admin_global_cobra(client_as, make_user, aceptada, con_plan):
    con_plan(aceptada, PLAN)
    c = client_as(make_user(first_name="GLOBAL", last_name="ADMIN"), role="admin")
    assert c.post(f"{API}/{aceptada.id}/saldar", json={"numero": 1, "folio": "ZZ-203", "fecha": _hoy()}).status_code == 200

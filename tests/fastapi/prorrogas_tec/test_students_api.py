from datetime import date

API = "/api/prorrogas/v2/estudiantes"


def test_lista_con_situacion_pagos_y_conteos(client_as, secretaria, aceptada, make_aceptada, con_plan, periodo):
    con_plan(aceptada, [("1000.00", date(2020, 1, 1)), ("1000.00", date(2091, 5, 1))], pagos=["400.00"])
    al_dia = con_plan(make_aceptada(), [("500.00", date(2091, 5, 1))])
    r = client_as(secretaria).get(f"{API}?period_id={periodo.id}&per_page=100")
    assert r.status_code == 200
    filas = {i["id"]: i for i in r.json()["items"]}
    assert filas[aceptada.id]["situacion"] == "atrasada" and filas[aceptada.id]["pagos"] == ["vencida", "pendiente"]
    assert filas[al_dia.id]["situacion"] == "al_corriente" and filas[al_dia.id]["pagados"] == 0
    assert r.json()["conteos"]["con_adeudo"] >= 1
    solo = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=con_adeudo&per_page=100").json()["items"]
    assert aceptada.id in [i["id"] for i in solo] and al_dia.id not in [i["id"] for i in solo]


def test_busqueda_por_control(client_as, secretaria, aceptada, periodo):
    items = client_as(secretaria).get(f"{API}?period_id={periodo.id}&q={aceptada.control_number}").json()["items"]
    assert [i["id"] for i in items] == [aceptada.id]


def test_expediente(client_as, secretaria, aceptada, con_plan):
    con_plan(aceptada, [("1000.00", date(2091, 2, 1)), ("2000.00", date(2091, 4, 1))], pagos=["1000.00"])
    e = client_as(secretaria).get(f"{API}/{aceptada.id}").json()
    assert e["cuenta"]["saldo"] == "2000.00" and e["plan"]["conservadas"] == [1] and e["plan"]["max_nuevas"] == 2
    assert e["recibos"][0]["folio"].startswith("T-") and e["carta"] is None and e["bloqueo"]["avisar_desbloqueo"] is False


def test_pendiente_no_tiene_expediente_y_el_estudiante_no_entra(client_as, secretaria, estudiante, solicitud):
    assert client_as(secretaria).get(f"{API}/{solicitud.id}").status_code == 404
    assert client_as(estudiante).get(f"{API}/{solicitud.id}").status_code == 403


from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402

from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument  # noqa: E402
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService  # noqa: E402
from itcj2.core.utils.timezone import db_now  # noqa: E402

PLAN = [("1000.00", date(2091, 5, 1))]


def _fila(client_as, secretaria, periodo, req):
    items = client_as(secretaria).get(f"{API}?period_id={periodo.id}&per_page=100").json()["items"]
    return next(i for i in items if i["id"] == req.id)


def test_filtro_invalido(client_as, secretaria, periodo):
    r = client_as(secretaria).get(f"{API}?period_id={periodo.id}&filtro=xyz")
    assert r.status_code == 400 and r.json()["error"] == "filtro_invalido"


def test_limites_de_paginacion(client_as, secretaria, periodo):
    def get(qs):
        return client_as(secretaria).get(f"{API}?period_id={periodo.id}&{qs}").json()
    assert get("per_page=0")["per_page"] == 1
    assert get("per_page=500")["per_page"] == 100
    assert get("page=0")["page"] == 1


@pytest.mark.parametrize("hace,esperado", [(None, True), (timedelta(hours=23), False), (timedelta(hours=25), True)])
def test_puede_recordar_por_ventana_de_24h(client_as, secretaria, periodo, aceptada, con_plan, hace, esperado):
    con_plan(aceptada, PLAN)
    aceptada.last_reminded_at = None if hace is None else db_now() - hace
    assert _fila(client_as, secretaria, periodo, aceptada)["puede_recordar"] is esperado
    e = client_as(secretaria).get(f"{API}/{aceptada.id}").json()
    assert e["recordatorio"]["puede"] is esperado


def test_no_puede_recordar_sin_plan_ni_liquidada(client_as, secretaria, periodo, aceptada, make_aceptada, con_plan):
    liquidada = con_plan(make_aceptada(), PLAN, pagos=["1000.00"])
    for req in (aceptada, liquidada):
        assert _fila(client_as, secretaria, periodo, req)["puede_recordar"] is False
        assert client_as(secretaria).get(f"{API}/{req.id}").json()["recordatorio"]["puede"] is False


def test_avisar_desbloqueo(client_as, secretaria, periodo, aceptada, con_plan):
    con_plan(aceptada, PLAN, pagos=["1000.00"])
    aceptada.block_exported_at = db_now()
    assert _fila(client_as, secretaria, periodo, aceptada)["avisar_desbloqueo"] is True
    assert client_as(secretaria).get(f"{API}/{aceptada.id}").json()["bloqueo"]["avisar_desbloqueo"] is True
    aceptada.unblock_notified_at = db_now()
    assert _fila(client_as, secretaria, periodo, aceptada)["avisar_desbloqueo"] is False
    assert client_as(secretaria).get(f"{API}/{aceptada.id}").json()["bloqueo"]["avisar_desbloqueo"] is False


def test_carta_vigente(client_as, secretaria, db_session, aceptada):
    d = ProrrogaDocument(request_id=aceptada.id, doc_type="carta_compromiso_1", version=1, context={},
                         file_path="x.pdf", sha256="0" * 64)
    db_session.add(d)
    db_session.flush()
    e = client_as(secretaria).get(f"{API}/{aceptada.id}").json()
    assert e["carta"] == {"doc_id": d.id, "tipo": "carta_compromiso_1", "version": 1, "firmada": False}


def test_periodos(client_as, secretaria, periodo, aceptada):
    r = client_as(secretaria).get(f"{API}/periodos").json()
    assert periodo.id in [i["id"] for i in r["items"]]
    assert r["actual"] in [i["id"] for i in r["items"]]
    assert all(i["label"] for i in r["items"])


def test_periodos_sin_aceptadas(db_session, periodo):
    r = StudentsService.periodos(db_session, date(2091, 3, 1))
    assert periodo.id not in [i["id"] for i in r["items"]]


def test_puede_replantear(db_session, aceptada, make_aceptada, con_plan):
    con_plan(aceptada, PLAN)
    ver = lambda dia: StudentsService.expediente(db_session, aceptada.id, dia)["plan"]["puede_replantear"]  # noqa: E731
    assert ver(date(2091, 6, 20)) is True
    assert ver(date(2091, 6, 21)) is False
    liq = con_plan(make_aceptada(), PLAN, pagos=["1000.00"])
    assert StudentsService.expediente(db_session, liq.id, date(2091, 6, 20))["plan"]["puede_replantear"] is False

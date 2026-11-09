from datetime import date, timedelta
from itertools import count

import pytest

from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
from itcj2.apps.prorrogas_tec.models.period import ProrrogaPeriod
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.utils.timezone import db_now

API = "/api/prorrogas/v2/configuracion/periodos"
BIEN = {"abre": "2091-01-02", "cierra": "2091-02-01", "pago1": "2091-03-01", "pago2": "2091-05-01"}
_seq = count(1)


def _semestre(db, inicio, fin):
    n = next(_seq)
    p = AcademicPeriod(code=f"C{n:05d}", name=f"Configuración {n}", start_date=inicio, end_date=fin, status="INACTIVE")
    db.add(p)
    db.flush()
    return p


def _item(r, periodo):
    return next(i for i in r.json()["items"] if i["id"] == periodo.id)


def test_guarda_y_corrige_el_mismo_periodo(client_as, secretaria, db_session, periodo):
    c = client_as(secretaria)
    assert _item(c.get(API), periodo)["periodo"] is None
    r = c.post(f"{API}/{periodo.id}", json=BIEN)
    assert r.status_code == 200 and _item(r, periodo)["periodo"] == BIEN
    otra = {**BIEN, "pago2": "2091-06-01"}
    assert _item(c.post(f"{API}/{periodo.id}", json=otra), periodo)["periodo"] == otra
    assert db_session.query(ProrrogaPeriod).filter_by(period_id=periodo.id).count() == 1


@pytest.mark.parametrize("cambio", [
    {"cierra": "2091-01-02"},               # cierra el día que abre
    {"pago1": "2091-01-02"},                # pago 1 el día que abre
    {"pago2": "2091-03-01"},                # pago 2 el día del pago 1
    {"pago2": "2091-06-20"},                # pago 2 el día que termina el semestre
])
def test_fechas_fuera_de_orden(client_as, secretaria, db_session, periodo, cambio):
    r = client_as(secretaria).post(f"{API}/{periodo.id}", json={**BIEN, **cambio})
    assert r.status_code == 400 and r.json()["error"] == "fechas_invalidas"
    assert db_session.query(ProrrogaPeriod).filter_by(period_id=periodo.id).first() is None


def test_abre_antes_de_que_empiece_el_semestre(client_as, secretaria, periodo):  # reinscripción
    datos = {**BIEN, "abre": "2090-12-15"}
    assert client_as(secretaria).post(f"{API}/{periodo.id}", json=datos).status_code == 200


def test_las_ventanas_no_se_enciman(client_as, secretaria, db_session, periodo):
    otro = _semestre(db_session, date(2091, 8, 1), date(2091, 12, 15))
    c = client_as(secretaria)
    assert c.post(f"{API}/{periodo.id}", json=BIEN).status_code == 200
    datos = {"abre": "2091-02-01", "cierra": "2091-03-01", "pago1": "2091-09-01", "pago2": "2091-10-01"}  # comparte un día
    r = c.post(f"{API}/{otro.id}", json=datos)
    assert r.status_code == 409 and r.json()["error"] == "periodo_encimado"
    assert c.post(f"{API}/{otro.id}", json={**datos, "abre": "2091-02-02"}).status_code == 200


def test_semestre_inexistente_o_archivado(client_as, secretaria, periodo):
    c = client_as(secretaria)
    assert c.post(f"{API}/999999999", json=BIEN).status_code == 404
    periodo.status = "ARCHIVED"
    assert c.post(f"{API}/{periodo.id}", json=BIEN).status_code == 404
    assert periodo.id not in [i["id"] for i in c.get(API).json()["items"]]


def test_el_estudiante_no_entra(client_as, estudiante, periodo):
    c = client_as(estudiante)
    assert c.get(API).status_code == 403
    assert c.post(f"{API}/{periodo.id}", json=BIEN).status_code == 403


def test_pestana_configuracion(client_as, secretaria):
    page = client_as(secretaria).get("/prorrogas/secretaria/configuracion").text
    for texto in ("Configuración", "Abre solicitudes", "Fecha del pago 2", "El periodo en orden", "configuracion.js"):
        assert texto in page


def test_el_semestre_actual_va_primero(db_session, periodo_hoy):
    from itcj2.apps.prorrogas_tec.services.periods import configuracion

    assert configuracion(db_session, db_now().date())["items"][0]["id"] == periodo_hoy.id


def test_sin_periodo_nadie_solicita(db_session, alumno_unido, periodo_hoy):
    assert RequestService.access(db_session, alumno_unido.id)[1] is None
    db_session.query(ProrrogaPeriod).filter_by(period_id=periodo_hoy.id).delete()
    assert RequestService.access(db_session, alumno_unido.id) == (None, "no_hay_semestre")


@pytest.mark.parametrize("abre_en, cierra_en", [(1, 10), (-10, -1)])
def test_fuera_de_la_ventana_nadie_solicita(db_session, alumno_unido, periodo_hoy, abre_en, cierra_en):
    hoy = db_now().date()
    f = db_session.query(ProrrogaPeriod).filter_by(period_id=periodo_hoy.id).one()
    f.opens_on, f.closes_on = hoy + timedelta(days=abre_en), hoy + timedelta(days=cierra_en)
    db_session.flush()
    assert RequestService.access(db_session, alumno_unido.id)[1] == "no_hay_semestre"


def test_antes_de_iniciar_el_semestre_ya_se_solicita(db_session, alumno_unido, periodo_hoy):  # reinscripción
    hoy = db_now().date()
    db_session.query(ProrrogaPeriod).filter_by(period_id=periodo_hoy.id).delete()
    siguiente = _semestre(db_session, hoy + timedelta(days=61), hoy + timedelta(days=200))
    db_session.add(ProrrogaPeriod(period_id=siguiente.id, opens_on=hoy - timedelta(days=2), closes_on=hoy + timedelta(days=5),
                                  payment_1_on=hoy + timedelta(days=90), payment_2_on=hoy + timedelta(days=120)))
    db_session.flush()
    period, code = RequestService.access(db_session, alumno_unido.id)
    assert code is None and period.id == siguiente.id


def test_la_union_previa_a_la_apertura_no_cuenta(db_session, estudiante, periodo_hoy):
    db_session.add(ProrrogaJoin(user_id=estudiante.id, via="qr", joined_at=db_now() - timedelta(days=3)))
    db_session.flush()
    assert RequestService.access(db_session, estudiante.id)[1] == "sin_acceso"


def test_el_expediente_sugiere_las_fechas_del_periodo(db_session, aceptada, periodo):
    ver = lambda: StudentsService.expediente(db_session, aceptada.id, date(2091, 2, 15))["plan"]["fechas_sugeridas"]  # noqa: E731
    assert ver() == []
    db_session.add(ProrrogaPeriod(period_id=periodo.id, opens_on=date(2091, 1, 2), closes_on=date(2091, 2, 1),
                                  payment_1_on=date(2091, 3, 1), payment_2_on=date(2091, 5, 1)))
    db_session.flush()
    assert ver() == ["2091-03-01", "2091-05-01"]

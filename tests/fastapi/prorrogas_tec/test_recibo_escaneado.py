import hashlib
from datetime import date
from io import BytesIO

import pytest

from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
from itcj2.apps.prorrogas_tec.models.plan import ProrrogaInstallment, ProrrogaPayment
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS

API = "/api/prorrogas/v2/estudiante/solicitudes"
PDF = b"%PDF-1.4 recibo de prueba"


@pytest.fixture()
def duena(db_session, aceptada, grant, make_role):
    from itcj2.core.models.user import User
    u = db_session.get(User, aceptada.student_id)
    grant(u, make_role("student", STUDENT_PERMS))
    return u


@pytest.fixture()
def cubierta(aceptada, con_plan):
    return con_plan(aceptada, [("1000.00", date(2091, 5, 1)), ("1000.00", date(2091, 6, 1))], pagos=["1000.00"])


def _subir(c, rid, numero=1, data=PDF):
    return c.post(f"{API}/{rid}/parcialidades/{numero}/recibo",
                  files={"archivo": ("mi recibo.pdf", BytesIO(data), "application/pdf")})


def test_sube_lee_y_reemplaza(client_as, duena, cubierta, db_session):
    c = client_as(duena)
    r = _subir(c, cubierta.id)
    assert r.status_code == 200 and r.json()["cuenta"]["parcialidades"][0]["recibo_subido"]
    assert r.json()["cuenta"]["parcialidades"][1]["recibo_subido"] is None
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=cubierta.id, number=1).one()
    sha = hashlib.sha256(PDF).hexdigest()[:12]
    assert i.receipt_path == f"recibos/{cubierta.period_id}/{cubierta.id}-1-{sha}.pdf"
    assert db_session.query(ProrrogaEvent).filter_by(request_id=cubierta.id, event_type="recibo_subido").one().payload == {"numero": 1}
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == PDF
    assert _subir(c, cubierta.id, data=b"%PDF-1.4 otro").status_code == 200
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == b"%PDF-1.4 otro"


@pytest.mark.parametrize("data, code", [
    (b"", "recibo_invalido"),
    (b"MZ no soy un pdf", "recibo_invalido"),
    (b"%PDF-" + b"0" * (5 * 1024 * 1024), "recibo_muy_grande"),
])
def test_archivo_rechazado(client_as, duena, cubierta, data, code):  # Review Focus 5
    r = _subir(client_as(duena), cubierta.id, data=data)
    assert r.status_code == 400 and r.json()["error"] == code


def test_recibo_ajeno_no_existe(client_as, estudiante, cubierta):  # Review Focus 5
    c = client_as(estudiante)
    assert _subir(c, cubierta.id).status_code == 404
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404


@pytest.mark.parametrize("numero", [2, 9])
def test_solo_si_esta_cubierta(client_as, duena, cubierta, numero):
    r = _subir(client_as(duena), cubierta.id, numero=numero)
    assert r.status_code == 409 and r.json()["error"] == "recibo_no_aplica"


def test_historica_sin_semestre_no_aplica(client_as, duena, db_session, make_historica):
    h = make_historica(control_number="99430020", pagadas=(0,))
    h.student_id = duena.id
    db_session.flush()
    assert _subir(client_as(duena), h.id).json()["error"] == "recibo_no_aplica"


def test_se_lee_tras_anular_pero_no_se_sube(client_as, duena, cubierta, db_session):
    c = client_as(duena)
    _subir(c, cubierta.id)
    pago = db_session.query(ProrrogaPayment).filter_by(request_id=cubierta.id).one()
    PaymentService.void(db_session, pago.id, duena.id, motivo="Se capturó mal", now=date(2091, 3, 1))
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").content == PDF
    assert _subir(c, cubierta.id).json()["error"] == "recibo_no_aplica"


def test_sin_recibo_o_archivo_borrado_es_404(client_as, duena, cubierta, db_session):  # Review Focus 5
    c = client_as(duena)
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404
    i = db_session.query(ProrrogaInstallment).filter_by(request_id=cubierta.id, number=1).one()
    i.receipt_path = "recibos/0/no-existe.pdf"
    db_session.flush()
    assert c.get(f"{API}/{cubierta.id}/parcialidades/1/recibo.pdf").status_code == 404

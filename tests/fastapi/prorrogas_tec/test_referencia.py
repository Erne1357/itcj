from io import BytesIO

import pytest

from itcj2.core.utils.timezone import db_now
from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS

API = "/api/prorrogas/v2/estudiante/solicitudes"
PDF = b"%PDF-1.4 referencia de prueba"


@pytest.fixture()
def duena(db_session, solicitud, grant, make_role):
    from itcj2.core.models.user import User
    u = db_session.get(User, solicitud.student_id)
    grant(u, make_role("student", STUDENT_PERMS))
    return u


def _subir(c, rid, data=PDF):
    return c.post(f"{API}/{rid}/referencia", files={"archivo": ("r.pdf", BytesIO(data), "application/pdf")})


def test_sube_y_baja_su_referencia(client_as, duena, solicitud):
    c = client_as(duena)
    r = _subir(c, solicitud.id)
    assert r.status_code == 200 and r.json()["referencia"]
    assert c.get(f"{API}/{solicitud.id}/referencia.pdf").content == PDF


@pytest.mark.parametrize("data, code", [
    (b"", "referencia_invalida"),
    (b"MZ no soy un pdf", "referencia_invalida"),
    (b"%PDF-" + b"0" * (5 * 1024 * 1024), "referencia_muy_grande"),
])
def test_archivo_rechazado(client_as, duena, solicitud, data, code):  # Review Focus 4
    r = _subir(client_as(duena), solicitud.id, data)
    assert r.status_code == 400 and r.json()["error"] == code


def test_referencia_ajena_no_existe(client_as, estudiante, solicitud):  # Review Focus 4
    c = client_as(estudiante)
    assert _subir(c, solicitud.id).status_code == 404
    assert c.get(f"{API}/{solicitud.id}/referencia.pdf").status_code == 404


def test_con_plan_ya_no_se_cambia(client_as, duena, solicitud, db_session):
    solicitud.plan_confirmed_at = db_now()
    db_session.flush()
    r = _subir(client_as(duena), solicitud.id)
    assert r.status_code == 409 and r.json()["error"] == "referencia_fija"

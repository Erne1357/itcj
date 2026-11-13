import base64
from datetime import date
from decimal import Decimal as D

import pytest

from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService

pytestmark = pytest.mark.usefixtures("pdf_falso", "avisos")
URL = "/api/prorrogas/v2/estudiante/solicitudes/{rid}/documentos/{did}/firmar"


def _carta(db, req):
    return next(d for d in DocumentService.current(db, req) if d.doc_type.startswith("carta_compromiso_"))


def _plan(db, req, sec, total="1000"):
    PlanService.confirm(db, req.id, sec.id, total=D(total), parcialidades=[(D(total), date(2091, 5, 1))],
                        now=date(2026, 11, 1))
    return _carta(db, req)


def _firma(png):
    return {"firma": "data:image/png;base64," + base64.b64encode(png).decode()}


def test_firma_usa_el_contexto_congelado(db_session, client_as, aceptada, secretaria, grant, make_role, firma_png):  # RF 5
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    carta = _plan(db_session, aceptada, secretaria)
    aceptada.student_name = "NOMBRE CAMBIADO"
    db_session.flush()
    r = client_as(alumno).post(URL.format(rid=aceptada.id, did=carta.id), json=_firma(firma_png))
    assert r.status_code == 200
    nueva = _carta(db_session, aceptada)
    assert nueva.version == carta.version + 1 and nueva.signed_at is not None
    assert nueva.context["nombre"] == carta.context["nombre"] != "NOMBRE CAMBIADO"
    assert carta.context["nombre"] in nueva.context["firma_estudiante_leyenda"]
    again = client_as(alumno).post(URL.format(rid=aceptada.id, did=nueva.id), json=_firma(firma_png))
    assert again.status_code == 409 and again.json()["error"] == "ya_firmado"


def test_carta_sustituida_no_se_firma(db_session, client_as, aceptada, secretaria, grant, make_role, firma_png):  # RF 5
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    vieja = _plan(db_session, aceptada, secretaria)
    _plan(db_session, aceptada, secretaria, total="1200")          # replanteo: la vieja queda sustituida
    r = client_as(alumno).post(URL.format(rid=aceptada.id, did=vieja.id), json=_firma(firma_png))
    assert r.status_code == 409 and r.json()["error"] == "documento_no_vigente"


def test_estado_trae_cuenta_y_por_firmar(db_session, client_as, aceptada, secretaria, grant, make_role):
    from tests.fastapi.prorrogas_tec.conftest import STUDENT_PERMS
    from itcj2.core.models.user import User
    alumno = db_session.get(User, aceptada.student_id)
    grant(alumno, make_role("student", STUDENT_PERMS))
    carta = _plan(db_session, aceptada, secretaria)
    s = client_as(alumno).get("/api/prorrogas/v2/estudiante/estado").json()["solicitudes"][0]
    assert s["por_firmar"] == carta.id and s["cuenta"]["total"] == "1000.00" and s["recibos"] == []


def test_no_firma_lo_ajeno(db_session, client_as, aceptada, secretaria, estudiante, firma_png):
    carta = _plan(db_session, aceptada, secretaria)
    r = client_as(estudiante).post(URL.format(rid=aceptada.id, did=carta.id), json=_firma(firma_png))
    assert r.status_code == 404

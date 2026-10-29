import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401
from itcj2.models.base import Base

NUEVAS = {"prorrogas_installments", "prorrogas_payments", "prorrogas_templates", "prorrogas_requests", "prorrogas_documents", "prorrogas_signatures",
          "prorrogas_invitations", "prorrogas_joins", "prorrogas_events"}


def test_las_tablas_de_prorrogas_son_las_del_spec():
    assert {t for t in Base.metadata.tables if t.startswith("prorrogas_")} == NUEVAS


def _solicitud(user, periodo, **kw):
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
    return ProrrogaRequest(student_id=user.id, period_id=periodo.id, control_number="99100001",
                           student_name="PRUEBA", requested_terms=1, **kw)


def test_una_sola_solicitud_abierta_por_semestre(db_session, make_user, periodo):  # Review Focus 1
    u = make_user(control_number="99100001")
    db_session.add(_solicitud(u, periodo))
    db_session.flush()
    db_session.add(_solicitud(u, periodo))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_una_rechazada_no_cuenta_como_abierta(db_session, make_user, periodo):
    u = make_user(control_number="99100002")
    db_session.add(_solicitud(u, periodo, status="rechazada"))
    db_session.add(_solicitud(u, periodo))
    db_session.flush()


def test_estado_desconocido_lo_rechaza_la_bd(db_session, make_user, periodo):
    db_session.add(_solicitud(make_user(control_number="99100003"), periodo, status="otro"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("url", ["/prorrogas/admin/home", "/prorrogas/admin/periods", "/prorrogas/student/home",
                                 "/api/prorrogas/v2/periods/", "/api/prorrogas/v2/request2/mine"])
def test_las_rutas_del_fork_ya_no_existen(client, url):
    assert client.get(url, follow_redirects=False).status_code == 404

import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401
from itcj2.models.base import Base

NUEVAS = {"prorrogas_installments", "prorrogas_payments", "prorrogas_templates", "prorrogas_requests", "prorrogas_documents", "prorrogas_signatures",
          "prorrogas_invitations", "prorrogas_joins", "prorrogas_events", "prorrogas_periods"}


def test_las_tablas_de_prorrogas_son_las_del_spec():
    assert {t for t in Base.metadata.tables if t.startswith("prorrogas_")} == NUEVAS


def _solicitud(user, periodo, **kw):
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
    return ProrrogaRequest(student_id=user.id, period_id=periodo.id, control_number="99100001",
                           student_name="PRUEBA", requested_terms=1, **kw)


def test_una_sola_solicitud_por_semestre(db_session, make_user, periodo):  # aunque la primera se rechazara
    u = make_user(control_number="99100001")
    db_session.add(_solicitud(u, periodo, status="rechazada"))
    db_session.flush()
    db_session.add(_solicitud(u, periodo))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cerrada_sin_plan_es_un_estado_valido(db_session, make_user, periodo):
    db_session.add(_solicitud(make_user(control_number="99100004"), periodo, status="cerrada_sin_plan"))
    db_session.flush()


def test_columnas_del_plan_5():
    t = Base.metadata.tables
    assert {"reference_path", "reference_uploaded_at"} <= set(t["prorrogas_requests"].c.keys())
    assert "last_reminder_days" in t["prorrogas_installments"].c


def test_estado_desconocido_lo_rechaza_la_bd(db_session, make_user, periodo):
    db_session.add(_solicitud(make_user(control_number="99100003"), periodo, status="otro"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("url", ["/prorrogas/admin/home", "/prorrogas/admin/periods", "/prorrogas/student/home",
                                 "/api/prorrogas/v2/periods/", "/api/prorrogas/v2/request2/mine"])
def test_las_rutas_del_fork_ya_no_existen(client, url):
    assert client.get(url, follow_redirects=False).status_code == 404


def test_columnas_de_caja():
    assert {"receipt_path", "receipt_uploaded_at"} <= set(Base.metadata.tables["prorrogas_installments"].c.keys())

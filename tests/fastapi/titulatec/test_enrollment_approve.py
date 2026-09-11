"""Bandeja de solicitudes: alcance, vacíos distinguibles, aprobar y rechazar.

`officer_programs()` devuelve un conjunto VACÍO en silencio cuando el usuario no
tiene carreras (riesgo 3 del diseño): la bandeja tiene que distinguir eso de "no
hay solicitudes", o el encargado ve una pantalla vacía y cree que no hay trabajo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

URL = "/titulatec/admin/solicitudes"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)


def _make_req(db_session, cohort, *, control, kind="unknown", status="pending_review",
              program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADO", last_name="ANTIGUO", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria de 2005",
        phone="6561234567", contact_email="egresado@example.invalid",
        has_efirma=False, kind=kind, status=status,
        verify_send_count=1, verify_sent_at=datetime.now() - timedelta(hours=1),
        verify_sent_to="egresado@example.invalid",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def test_la_bandeja_lista_las_solicitudes_del_alcance(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99550001")

    resp = client_as(head).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "99550001" in resp.text
    assert "ANTIGUO" in resp.text


def test_body_acepta_los_mismos_query_params_que_la_pagina(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99550002", status="pending_review")
    _make_req(db_session, cohort, control="99550003", status="rejected")
    c = client_as(head)

    pagina = c.get(f"{URL}?status=rejected&cohort_id={cohort.id}")
    body = c.get(f"{URL}/body?status=rejected&cohort_id={cohort.id}")

    assert pagina.status_code == 200 and body.status_code == 200
    assert "99550003" in body.text
    assert "99550002" not in body.text
    assert 'id="tt-requests-body"' in body.text


def test_sin_carreras_asignadas_no_dice_no_hay_solicitudes(
    client_as, db_session, make_officer, make_cohort,
):
    """El vacío por alcance NO se puede confundir con el vacío por falta de datos."""
    officer, _pos = make_officer(
        programs=[], perm_codes=("titulatec.enrollment_request.page.list",))
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99550004")

    resp = client_as(officer).get(URL)

    assert resp.status_code == 200, resp.text[:500]
    assert "no tienes carreras asignadas" in resp.text.lower()
    assert "no hay solicitudes" not in resp.text.lower()
    assert "99550004" not in resp.text


def test_el_menu_admin_ofrece_solicitudes_y_encuestas_con_su_solo_codigo():
    """`admin_nav_items` hace `perms & need` (OR): una fila, un código."""
    from itcj2.apps.titulatec.pages.nav import _ADMIN_NAV

    filas = {url: need for _label, _icon, url, need in _ADMIN_NAV}
    assert filas["/titulatec/admin/solicitudes"] == {"titulatec.enrollment_request.page.list"}
    assert filas["/titulatec/admin/encuestas"] == {"titulatec.survey.page.list"}

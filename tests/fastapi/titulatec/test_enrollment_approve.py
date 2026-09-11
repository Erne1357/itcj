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


NIP = "4917"


def test_aprobar_sin_nip_o_con_formato_invalido_se_rechaza(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550010")
    c = client_as(head)

    sin_nip = c.post(f"{URL}/{req.id}/aprobar", data={"nip": "", "program_id": ""})
    corto = c.post(f"{URL}/{req.id}/aprobar", data={"nip": "12", "program_id": ""})
    letras = c.post(f"{URL}/{req.id}/aprobar", data={"nip": "abcd", "program_id": ""})

    assert sin_nip.status_code == 400
    assert corto.status_code == 400
    assert letras.status_code == 400
    db_session.refresh(req)
    assert req.status == "pending_review"


def test_aprobar_crea_al_usuario_con_hash_nip_y_cambio_obligatorio(
    client_as, db_session, make_head, make_cohort, make_program,
    seed_phase_defs, titulatec_app,
):
    """D15: usuario = número de control, contraseña = NIP, `must_change_password`.

    NUNCA se llama `set_initial_credential`, que pondría el número de control
    (dato público) como contraseña.
    """
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    program = make_program("Ingenieria Ficticia B")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550011")

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                data={"nip": NIP, "program_id": str(program.id)})

    assert resp.status_code == 200, resp.text[:500]
    user = db_session.query(User).filter_by(control_number="99550011").first()
    assert user is not None
    assert user.username == "99550011"
    assert verify_nip(NIP, user.password_hash)
    assert not verify_nip("99550011", user.password_hash)
    assert user.must_change_password is True

    db_session.refresh(req)
    assert req.status == "converted"
    assert req.converted_process_id is not None

    from itcj2.apps.titulatec.models import TitulationProcess
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == user.id
    assert proc.program_id == program.id

    # La bandeja que vuelve del swap imprime el folio del proceso creado: es lo
    # que el oficial necesita ver para saber que la aprobacion aterrizo, y lo que
    # `admin-requests.spec.js` (Tarea 27) localiza con `getByText(folio)`.
    assert proc.folio in resp.text


def test_el_nip_no_aparece_en_el_process_event_ni_en_la_respuesta(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app, caplog,
):
    """El NIP es la contraseña del alumno: fuera de logs, X-Tt-Error y payload."""
    import json
    import logging

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550012")

    with caplog.at_level(logging.DEBUG):
        resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                    data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 200, resp.text[:500]
    assert NIP not in resp.text
    assert NIP not in "".join(resp.headers.values())
    assert NIP not in caplog.text

    from itcj2.apps.titulatec.models import ProcessEvent
    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=req.converted_process_id).all())
    assert eventos
    for ev in eventos:
        assert NIP not in json.dumps(ev.payload or {})


def test_rechazar_exige_motivo_y_deja_reintentar(
    client_as, db_session, make_head, make_cohort,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550013")
    c = client_as(head)

    sin_motivo = c.post(f"{URL}/{req.id}/rechazar", data={"note": "   "})
    assert sin_motivo.status_code == 400

    con_motivo = c.post(f"{URL}/{req.id}/rechazar",
                        data={"note": "No aparece en el padrón de 2005."})
    assert con_motivo.status_code == 200, con_motivo.text[:500]
    db_session.refresh(req)
    assert req.status == "rejected"
    assert req.review_note == "No aparece en el padrón de 2005."
    assert req.reviewed_by_id == head.id

    # El índice parcial deja re-intentar tras un rechazo.
    otra = _make_req(db_session, cohort, control="99550013")
    assert otra.id != req.id

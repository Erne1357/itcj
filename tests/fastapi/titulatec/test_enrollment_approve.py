"""Bandeja de solicitudes: alcance, vacíos distinguibles, aprobar y rechazar.

`officer_programs()` devuelve un conjunto VACÍO en silencio cuando el usuario no
tiene carreras (riesgo 3 del diseño): la bandeja tiene que distinguir eso de "no
hay solicitudes", o el encargado ve una pantalla vacía y cree que no hay trabajo.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import unquote

URL = "/titulatec/admin/solicitudes"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)

# Ronda de revisión 1, Finding 1: encargado con los mismos permisos de mutación
# que la jefa pero SIN `process.api.read.all` — `officer_programs()` le da un
# `set[int]`, no "ALL", así que el guard de alcance sí tiene algo que probar.
SCOPED_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
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


# ---------------------------------------------------------------------------
# Ronda de revisión 1 — Finding 1 (crítico): `aprobar`/`rechazar`/`reenviar`
# actuaban sobre `req_id` sin mirar el alcance por carrera, aunque la bandeja
# ya lo ocultara. El dropdown de carreras del formulario tampoco estaba
# acotado. Ver `_officer_scope`/`_program_in_scope`/`_load_scoped_request` en
# `pages/requests_admin.py`.
# ---------------------------------------------------------------------------
def test_encargado_no_alcanza_las_mutaciones_de_otra_carrera(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    """`api.approve`/`.api.reject` por sí solos aprobaban CUALQUIER `req_id`."""
    prog_a = make_program("Ingenieria Alcance A")
    prog_b = make_program("Ingenieria Alcance B")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    ajena = _make_req(db_session, cohort, control="99550050", program=prog_b)
    c = client_as(officer)

    aprobar = c.post(f"{URL}/{ajena.id}/aprobar", data={"nip": "1234", "program_id": ""})
    rechazar = c.post(f"{URL}/{ajena.id}/rechazar", data={"note": "motivo cualquiera"})
    reenviar = c.post(f"{URL}/{ajena.id}/reenviar")

    assert aprobar.status_code == 404
    assert rechazar.status_code == 404
    assert reenviar.status_code == 404
    db_session.refresh(ajena)
    assert ajena.status == "pending_review"


def test_una_solicitud_sin_carrera_tampoco_esta_al_alcance_del_encargado(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    """`program_id IS NULL` solo la resuelve quien tiene alcance total — mismo
    criterio que ya aplicaba la bandeja (`_body_ctx`)."""
    prog_a = make_program("Ingenieria Alcance A2")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    sin_carrera = _make_req(db_session, cohort, control="99550051")  # program=None

    resp = client_as(officer).post(f"{URL}/{sin_carrera.id}/aprobar",
                                   data={"nip": "1234", "program_id": ""})

    assert resp.status_code == 404


def test_solicitud_inexistente_responde_igual_que_una_fuera_de_alcance(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    """La negación por alcance debe ser indistinguible de "no existe": mismo
    status, sin `X-Tt-Error` que delate cuál de los dos motivos fue."""
    prog_a = make_program("Ingenieria Alcance A3")
    prog_b = make_program("Ingenieria Alcance B3")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    ajena = _make_req(db_session, cohort, control="99550052", program=prog_b)
    c = client_as(officer)

    fantasma = c.post(f"{URL}/{ajena.id + 500000}/aprobar",
                      data={"nip": "1234", "program_id": ""})
    fuera_de_alcance = c.post(f"{URL}/{ajena.id}/aprobar",
                              data={"nip": "1234", "program_id": ""})

    assert fantasma.status_code == fuera_de_alcance.status_code == 404
    assert not fantasma.headers.get("X-Tt-Error")
    assert not fuera_de_alcance.headers.get("X-Tt-Error")


def test_encargado_si_puede_aprobar_una_solicitud_de_su_propia_carrera(
    client_as, db_session, make_officer, make_cohort, make_program,
    seed_phase_defs, titulatec_app,
):
    """El guard no debe ser tan estricto que bloquee lo que sí es del alcance."""
    seed_phase_defs()
    prog_a = make_program("Ingenieria Alcance Propia")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550053", program=prog_a)

    resp = client_as(officer).post(f"{URL}/{req.id}/aprobar",
                                   data={"nip": "1234", "program_id": str(prog_a.id)})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(req)
    assert req.status == "converted"


def test_aprobar_rechaza_una_carrera_fuera_de_alcance_aunque_la_solicitud_si_sea_propia(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    """La solicitud SÍ está en el alcance del encargado; la carrera que ELIGE en
    el formulario no. El dropdown ya no debería ofrecerla (ver el test de
    abajo), pero la ruta la rechaza igual si de todos modos llega en el POST."""
    prog_a = make_program("Ingenieria Propia Dropdown")
    prog_b = make_program("Ingenieria Ajena Dropdown")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550054", program=prog_a)

    resp = client_as(officer).post(f"{URL}/{req.id}/aprobar",
                                   data={"nip": "1234", "program_id": str(prog_b.id)})

    assert resp.status_code == 400
    assert "alcance" in unquote(resp.headers.get("X-Tt-Error", "")).lower()
    db_session.refresh(req)
    assert req.status == "pending_review"


def test_el_dropdown_de_aprobar_solo_ofrece_carreras_del_alcance(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    prog_a = make_program("Ingenieria Visible En Dropdown")
    prog_b = make_program("Ingenieria Oculta Del Dropdown")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    _make_req(db_session, cohort, control="99550055", program=prog_a)

    resp = client_as(officer).get(f"{URL}/body")

    assert resp.status_code == 200
    assert "Ingenieria Visible En Dropdown" in resp.text
    assert "Ingenieria Oculta Del Dropdown" not in resp.text


# ---------------------------------------------------------------------------
# Ronda de revisión 1 — Finding 2 (importante): `import_rows` sin
# `commit=False` dejaba huérfanos si algo fallaba después. Mismo patrón que el
# regresivo de `_convert` en `test_enrollment_verify.py`
# (`test_fallo_entre_import_rows_y_el_commit_final_no_deja_usuario_ni_proceso_huerfanos`).
# ---------------------------------------------------------------------------
def test_fallo_entre_import_rows_y_el_commit_final_no_deja_usuario_ni_proceso_huerfanos(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    monkeypatch,
):
    """Sin `commit=False` en la llamada a `import_rows` dentro de `approve`, ese
    `import_rows` commitea por su cuenta ANTES de que `approve` llegue a
    `req.status="converted"`. Un fallo real en lo único que queda entre ese
    commit y el final (`StudentProfileService.set_fields`, forzado aquí con
    monkeypatch) dejaría un `User` y un `TitulationProcess` REALES y
    COMMITEADOS aunque la aprobación completa fallara. `approve` debe ser
    dueña única de su transacción, igual que `_convert`.
    """
    import itcj2.core.services.student_profile_service as sps_mod
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    def _boom(db, user_id, **fields):
        raise RuntimeError("mutación deliberada: fallo tras import_rows")

    monkeypatch.setattr(sps_mod.StudentProfileService, "set_fields", staticmethod(_boom))

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550060")

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 400
    assert NIP not in resp.text
    assert NIP not in "".join(resp.headers.values())
    assert db_session.query(User).filter_by(control_number="99550060").first() is None, (
        "no debe quedar un usuario huerfano si la aprobacion no termino")
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0, (
        "no debe quedar un proceso huerfano si la aprobacion no termino")


# ---------------------------------------------------------------------------
# Ronda de revisión 1 — Finding 3 (importante, hallado por el revisor): el
# correo de "acceso con NIP" podía prometer una contraseña que no era la real
# cuando el número de control ya tenía `password_hash`. Cero cobertura antes:
# todos los `approve` de este archivo usaban un control_number NUEVO.
# ---------------------------------------------------------------------------
def test_aprobar_con_usuario_existente_conserva_su_password_y_avisa_por_folio(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    monkeypatch,
):
    """Si el control ya resuelve a un `User` CON `password_hash` (p. ej. de un
    CSV de otra convocatoria), el NIP capturado aquí NO abre esa cuenta:
    `approve` preserva el hash existente (romperlo sería secuestro de cuenta,
    dado que el formulario público deja declarar un control ajeno) y avisa por
    folio (`send_enrollment_done`, al institucional) — NUNCA
    `send_enrollment_approved`, que prometería al correo PERSONAL un acceso
    que no funciona.
    """
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip, verify_nip
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99550061"
    existing_hash = hash_nip("9999")
    user = User(username=control, control_number=control,
               first_name="YA", last_name="EXISTIA",
               password_hash=existing_hash, is_active=True,
               must_change_password=False)
    db_session.add(user)
    db_session.flush()
    req = _make_req(db_session, cohort, control=control)

    sent = []
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        lambda *a, **k: sent.append("approved"))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_done",
                        lambda *a, **k: sent.append("done"))

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 200, resp.text[:500]
    db_session.refresh(user)
    assert user.password_hash == existing_hash
    assert verify_nip("9999", user.password_hash)
    assert not verify_nip(NIP, user.password_hash)
    assert sent == ["done"]


def test_aprobar_rechaza_si_la_persona_ya_tiene_proceso_en_otra_convocatoria(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
):
    """Rama sin cobertura antes de esta ronda: `otro is not None`."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    control = "99550062"
    otra_cohort = make_cohort(status="open")
    esta_cohort = make_cohort(status="open")
    user = User(username=control, control_number=control,
               first_name="YA", last_name="INSCRITO",
               password_hash="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(TitulationProcess(
        folio=f"TT-OTRA-{control}", student_id=user.id, cohort_id=otra_cohort.id,
        status="active", current_phase=1))
    db_session.flush()
    req = _make_req(db_session, esta_cohort, control=control)

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 400
    assert "otra convocatoria" in unquote(resp.headers.get("X-Tt-Error", "")).lower()
    db_session.refresh(req)
    assert req.status == "pending_review"

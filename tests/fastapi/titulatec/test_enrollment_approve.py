"""Bandeja de solicitudes y `approve()`: alcance, vacíos, aprobar y rechazar.

Desde 2026-09-15 aprobar tiene DOS caminos, decididos con la BD AL APROBAR (no
con el `kind` que se guardó al enviar el formulario):

- SIN cuenta en `core_users`: NIP obligatorio -> usuario + `hash_nip` + proceso +
  perfil -> `converted`, y usuario + NIP al correo personal.
- CON cuenta: sin NIP -> liga de activación de 21 días al correo personal ->
  `approved`. La cuenta no se toca (ni credencial, ni `is_active`, ni perfil):
  la inscripción ocurre al abrir la liga (`test_enrollment_verify.py`).

`officer_programs()` devuelve un conjunto VACÍO en silencio cuando el usuario no
tiene carreras (riesgo 3 del diseño): la bandeja tiene que distinguir eso de "no
hay solicitudes", o el encargado ve una pantalla vacía y cree que no hay trabajo.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from urllib.parse import unquote

import pytest

URL = "/titulatec/admin/solicitudes"
NIP = "4917"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)

# Encargado con los mismos permisos de mutación que la jefa pero SIN
# `process.api.read.all`: `officer_programs()` le da un `set[int]`, no "ALL".
SCOPED_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
)

MSG_SIN_CONTRASENA = ("Esa cuenta no tiene contraseña; dala de alta desde la "
                      "convocatoria y rechaza esta solicitud.")


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos sin tocar Graph: `(asunto, destinatarios, html)`."""
    enviados = []

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return enviados


@pytest.fixture()
def orden_commit_correo(db_session, monkeypatch):
    """Registra, en orden, cada `db_session.commit()` y cada envío por Graph."""
    orden, enviados = [], []
    commit_real = db_session.commit

    def _commit():
        orden.append("commit")
        return commit_real()

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        orden.append("correo")
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    return orden, enviados


def _make_req(db_session, cohort, *, control, kind="unknown", status="pending_review",
              program=None, **kw):
    """Solicitud tal como la deja `create()`: en revisión, sin liga ni envíos."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADO", last_name="ANTIGUO", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria de 2005",
        phone="6561234567", contact_email="egresado@example.invalid",
        has_efirma=False, kind=kind, status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control, *, password=True, is_active=True, must_change=False):
    """Cuenta que YA existe en `core_users`."""
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control,
                first_name="YA", last_name="EXISTIA",
                password_hash=hash_nip("9999") if password else None,
                is_active=is_active, must_change_password=must_change)
    db_session.add(user)
    db_session.flush()
    return user


def _token_de_la_liga(html: str) -> str:
    return html.split("/inscripcion/verificar?t=", 1)[1].split('"', 1)[0]


# ---------------------------------------------------------------------------
# Listado y alcance
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Aprobar SIN cuenta: NIP, usuario nuevo, correo con usuario y NIP
# ---------------------------------------------------------------------------
def test_aprobar_sin_cuenta_exige_un_nip_de_4_digitos(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
):
    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550010")
    c = client_as(head)

    for nip in ("", "12", "abcd", "12345"):
        resp = c.post(f"{URL}/{req.id}/aprobar", data={"nip": nip, "program_id": ""})
        assert resp.status_code == 400, nip
        assert unquote(resp.headers["X-Tt-Error"]) == "El NIP debe ser exactamente 4 dígitos."
    db_session.refresh(req)
    assert req.status == "pending_review"


def test_aprobar_sin_cuenta_crea_al_usuario_con_hash_nip_y_cambio_obligatorio(
    client_as, db_session, make_head, make_cohort, make_program,
    seed_phase_defs, titulatec_app,
):
    """D15: usuario = número de control, contraseña = NIP, `must_change_password`.

    NUNCA se llama `set_initial_credential`, que pondría el número de control
    (dato público) como contraseña.
    """
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    program = make_program("Ingenieria Ficticia B")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550011")
    c = client_as(head)

    resp = c.post(f"{URL}/{req.id}/aprobar",
                  data={"nip": NIP, "program_id": str(program.id)})

    assert resp.status_code == 200, resp.text[:500]
    user = db_session.query(User).filter_by(control_number="99550011").first()
    assert user is not None
    assert user.username == "99550011"
    assert verify_nip(NIP, user.password_hash)
    assert not verify_nip("99550011", user.password_hash)
    assert user.must_change_password is True
    assert user.is_active is True

    db_session.refresh(req)
    assert req.status == "converted"
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == user.id
    assert proc.program_id == program.id

    # El folio queda a la vista en la pestaña de inscritas: es lo que el oficial
    # necesita para saber que la aprobación aterrizó.
    inscritas = c.get(f"{URL}/body?status=converted")
    assert proc.folio in inscritas.text


def test_aprobar_sin_cuenta_manda_usuario_y_nip_al_correo_personal_despues_del_commit(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    orden_commit_correo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    orden, enviados = orden_commit_correo
    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550012")

    ok, _folio = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is True
    assert orden and orden[0] == "commit", orden
    assert orden.count("correo") == 1
    (_asunto, destinatarios, html), = enviados
    assert destinatarios == ["egresado@example.invalid"]
    assert NIP in html and "99550012" in html
    assert "/inscripcion/verificar" not in html, "una cuenta nueva no recibe liga"


def test_aprobar_sin_cuenta_nace_graduate_y_tira_el_cache_tras_el_commit(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app,
    orden_commit_correo, monkeypatch,
):
    """La cuenta nueva nace con el alias legado `graduate` y con los roles de app
    que deja `import_rows`. `approve` es dueña de la transacción (`commit=False`),
    así que el caché de authz lo tira ELLA, después de su commit."""
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.services import authz_cache
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    orden, _enviados = orden_commit_correo
    monkeypatch.setattr(authz_cache, "invalidate_user_app",
                        lambda user_id, app_key: orden.append((user_id, app_key)))
    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550070")

    ok, _folio = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is True
    user = db_session.query(User).filter_by(control_number="99550070").one()
    assert user.role_id == db_session.query(Role.id).filter_by(name="graduate").scalar()
    roles = {(k, n) for k, n in (db_session.query(App.key, Role.name)
                                 .join(UserAppRole, UserAppRole.app_id == App.id)
                                 .join(Role, Role.id == UserAppRole.role_id)
                                 .filter(UserAppRole.user_id == user.id).all())}
    assert roles == {("itcj", "graduate"), ("titulatec", "graduate")}
    invalidaciones = [i for i, x in enumerate(orden) if isinstance(x, tuple)]
    assert invalidaciones and min(invalidaciones) > orden.index("commit"), orden
    assert {orden[i] for i in invalidaciones} == {(user.id, "itcj"), (user.id, "titulatec")}


def test_el_nip_no_aparece_en_el_process_event_ni_en_la_respuesta(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app, caplog,
):
    """El NIP es la contraseña del alumno: fuera de logs, X-Tt-Error y payload."""
    import json
    import logging

    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550013")

    with caplog.at_level(logging.DEBUG):
        resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                    data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 200, resp.text[:500]
    assert NIP not in resp.text
    assert NIP not in "".join(resp.headers.values())
    assert NIP not in caplog.text

    db_session.refresh(req)
    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=req.converted_process_id).all())
    assert eventos
    for ev in eventos:
        assert NIP not in json.dumps(ev.payload or {})


# ---------------------------------------------------------------------------
# Aprobar CON cuenta: liga de activación, la cuenta no se toca
# ---------------------------------------------------------------------------
def test_aprobar_con_cuenta_emite_la_liga_al_correo_personal_y_queda_approved(
    db_session, make_cohort, make_user, make_program, orden_commit_correo,
):
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, _token_cache_get,
    )

    orden, enviados = orden_commit_correo
    actor = make_user()
    program = make_program("Ingenieria Con Cuenta")
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, "99550020")
    hash_antes = cuenta.password_hash
    req = _make_req(db_session, cohort, control="99550020", kind="known")

    ok, _detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=program.id, actor_id=actor.id)

    assert ok is True
    assert req.status == "approved"
    assert req.program_id == program.id
    assert req.reviewed_by_id == actor.id and req.reviewed_at is not None
    assert req.verify_sent_to == "egresado@example.invalid"
    assert req.verify_send_count == 1
    assert req.verify_sent_at is not None
    assert req.verified_at is None
    vence = datetime.now() + timedelta(days=21)
    assert abs((req.verify_expires_at - vence).total_seconds()) < 120

    assert orden and orden[0] == "commit", "la liga salió antes de commitear"
    (_asunto, destinatarios, html), = enviados
    assert destinatarios == ["egresado@example.invalid"]
    token = _token_de_la_liga(html)
    assert hashlib.sha256(token.encode("utf-8")).hexdigest() == req.verify_token_hash
    assert token != req.verify_token_hash, "en la BD solo vive el sha256"
    assert _token_cache_get(req.verify_token_hash) == token, (
        "sin el claro en Redis el reenvío público no podría mandar la misma liga")
    assert NIP not in html

    db_session.refresh(cuenta)
    assert cuenta.password_hash == hash_antes
    assert cuenta.must_change_password is False
    assert db_session.get(StudentProfile, cuenta.id) is None
    assert (db_session.query(TitulationProcess)
            .filter_by(student_id=cuenta.id).count()) == 0, (
        "la inscripción ocurre al abrir la liga, no al aprobar")


def test_aprobar_con_cuenta_no_pide_nip(
    client_as, db_session, make_head, make_cohort, correo_falso,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99550021")
    req = _make_req(db_session, cohort, control="99550021", kind="known")

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar", data={"program_id": ""})

    assert resp.status_code == 200, resp.headers.get("X-Tt-Error")
    db_session.refresh(req)
    assert req.status == "approved"


def test_aprobar_una_cuenta_desactivada_no_la_reactiva(
    db_session, make_cohort, make_user, correo_falso,
):
    """El acceso llega SOLO por la liga: aprobar la emite y nada más. La
    reactivación es de `verify()` (`test_enrollment_verify.py`)."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort(status="open")
    cuenta = _cuenta(db_session, "99550071", is_active=False)
    req = _make_req(db_session, cohort, control="99550071", kind="known")

    ok, _ = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is True and req.status == "approved"
    db_session.refresh(cuenta)
    assert cuenta.is_active is False


def test_aprobar_con_cuenta_sin_contrasena_devuelve_el_error_sin_cambios(
    client_as, db_session, make_head, make_cohort, correo_falso,
):
    """La población con `password_hash` NULL es real (`repair_missing_credentials`
    existe por ella). Mandarle una liga la inscribiría a una cuenta que nadie
    puede abrir; darle credencial desde aquí es el secuestro que la revisión
    final encontró. Se da de alta desde la convocatoria."""
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    _cuenta(db_session, "99550022", password=False)
    req = _make_req(db_session, cohort, control="99550022")

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar", data={"nip": NIP})

    assert resp.status_code == 400
    assert unquote(resp.headers["X-Tt-Error"]) == MSG_SIN_CONTRASENA
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.verify_token_hash is None
    assert correo_falso == []


def test_aprobar_rechaza_si_la_persona_ya_tiene_proceso_en_otra_convocatoria(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    control = "99550023"
    otra_cohort = make_cohort(status="open")
    esta_cohort = make_cohort(status="open")
    user = _cuenta(db_session, control)
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
    assert correo_falso == []


@pytest.mark.parametrize("con_cuenta", [False, True], ids=["sin-cuenta", "con-cuenta"])
def test_aprobar_con_la_convocatoria_cerrada_no_cambia_nada(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    con_cuenta,
):
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="closed")
    if con_cuenta:
        _cuenta(db_session, "99550024")
    req = _make_req(db_session, cohort, control="99550024")

    ok, detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is False
    assert detalle == "Esa convocatoria está cerrada; abre su ventana primero."
    assert req.status == "pending_review"
    assert req.verify_token_hash is None
    assert (db_session.query(User).filter_by(control_number="99550024").count()
            == (1 if con_cuenta else 0))
    assert correo_falso == []


def test_una_cuenta_que_aparecio_despues_de_enviar_va_por_la_rama_con_cuenta(
    db_session, make_cohort, make_user, correo_falso,
):
    """Regla 2: "¿tiene cuenta?" se decide con la BD al aprobar. Si al enviar no
    existía pero un CSV la creó después, crearle otra con NIP chocaría con la
    cuenta real (y el NIP pisaría su contraseña)."""
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort(status="open")
    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        {"control_number": "99550025", "first_name": "EGRESADA", "last_name": "TARDIA",
         "middle_name": None, "program_id": None, "program_text": "Ingenieria",
         "phone": "6560000000", "contact_email": "tardia@example.invalid",
         "has_efirma": False},
        client_ip=None)
    assert (outcome, req.kind) == ("created", "unknown")
    cuenta = _cuenta(db_session, "99550025")        # la creó un CSV entretanto

    ok, _ = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is True
    assert req.status == "approved"
    assert req.kind == "unknown", "`kind` no decide nada: solo se muestra"
    db_session.refresh(cuenta)
    assert not verify_nip(NIP, cuenta.password_hash)
    assert [d for _a, d, _h in correo_falso] == [["tardia@example.invalid"]]


@pytest.mark.parametrize("status,motivo", [
    ("approved", "Esa solicitud ya fue aprobada; usa Reenviar liga."),
    ("converted", "Esa solicitud ya se resolvió."),
    ("rejected", "Esa solicitud ya se resolvió."),
])
def test_aprobar_una_solicitud_ya_aprobada_o_resuelta_devuelve_el_motivo(
    db_session, make_cohort, make_user, correo_falso, status, motivo,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    actor = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550026", status=status)

    ok, detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert (ok, detalle) == (False, motivo)
    db_session.refresh(req)
    assert req.status == status
    assert correo_falso == []


@pytest.mark.parametrize("status", ["unverified", "verified"])
def test_una_solicitud_legado_se_puede_aprobar(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    status,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550027", status=status)

    ok, _ = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is True
    assert req.status == "converted"


@pytest.mark.parametrize("con_cuenta", [False, True], ids=["sin-cuenta", "con-cuenta"])
def test_doble_aprobacion_manda_un_solo_correo(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    con_cuenta,
):
    """Doble clic, o dos oficiales en la misma bandeja: la segunda pasada ve el
    estado ya escrito (lock + refresh) y no manda nada. Sin eso la persona
    recibía dos NIP distintos y solo servía el último."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="open")
    if con_cuenta:
        _cuenta(db_session, "99550028")
    req = _make_req(db_session, cohort, control="99550028")

    primero = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)
    segundo = EnrollmentRequestService.approve(
        db_session, req.id, nip="1111", program_id=None, actor_id=actor.id)

    assert primero[0] is True and segundo[0] is False
    assert len(correo_falso) == 1


def test_approve_toma_lock_y_refresca_antes_de_leer_status():
    """Mismo patrón que `verify()`: un gate de estado sin lock deja pasar a las
    dos peticiones de un doble clic antes de que ninguna escriba."""
    import inspect

    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    src = inspect.getsource(EnrollmentRequestService.approve)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status")


def test_si_no_se_crea_el_proceso_approve_no_deja_nada_escrito(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    """Invariante de `approve()`: si devuelve `(False, ...)` no queda NADA en la
    sesión. Antes lo garantizaba por accidente el `close()` de la ruta, que en
    las pruebas no hace nada."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services import import_service
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(lambda *a, **k: {"processes_created": 0}))
    seed_phase_defs()
    actor = make_user()
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550029")

    ok, detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=actor.id)

    assert ok is False
    assert detalle == "No se pudo crear el proceso; revisa los datos de la solicitud."
    assert db_session.query(User).filter_by(control_number="99550029").first() is None
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert correo_falso == []


# ---------------------------------------------------------------------------
# Rechazar
# ---------------------------------------------------------------------------
def test_rechazar_exige_motivo_y_deja_reintentar(
    client_as, db_session, make_head, make_cohort, correo_falso,
):
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550030")
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
    otra = _make_req(db_session, cohort, control="99550030")
    assert otra.id != req.id


# ---------------------------------------------------------------------------
# Alcance por carrera en las mutaciones (Finding 1, ronda 1 de revisión)
# ---------------------------------------------------------------------------
def test_encargado_no_alcanza_las_mutaciones_de_otra_carrera(
    client_as, db_session, make_officer, make_cohort, make_program,
):
    prog_a = make_program("Ingenieria Alcance A")
    prog_b = make_program("Ingenieria Alcance B")
    officer, _pos = make_officer([prog_a], perm_codes=SCOPED_PERMS)
    cohort = make_cohort(status="open")
    ajena = _make_req(db_session, cohort, control="99550050", program=prog_b)
    c = client_as(officer)

    aprobar = c.post(f"{URL}/{ajena.id}/aprobar", data={"nip": "1234", "program_id": ""})
    rechazar = c.post(f"{URL}/{ajena.id}/rechazar", data={"note": "motivo cualquiera"})
    reenviar = c.post(f"{URL}/{ajena.id}/reenviar")

    for resp in (aprobar, rechazar, reenviar):
        assert resp.status_code == 404
        assert not resp.headers.get("X-Tt-Error")
    db_session.refresh(ajena)
    assert ajena.status == "pending_review"


def test_una_solicitud_sin_carrera_tampoco_esta_al_alcance_del_encargado(
    client_as, db_session, make_officer, make_cohort, make_program,
):
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
# Transacción de la aprobación (Finding 2, ronda 1 de revisión)
# ---------------------------------------------------------------------------
def test_fallo_entre_import_rows_y_el_commit_final_no_deja_usuario_ni_proceso_huerfanos(
    client_as, db_session, make_head, make_cohort, seed_phase_defs, titulatec_app,
    monkeypatch,
):
    """`import_rows(commit=False)`: si algo revienta después (aquí, el perfil),
    la ruta hace `rollback()` y no queda un `User`/`TitulationProcess` a medias."""
    import itcj2.core.services.student_profile_service as sps_mod
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    def _boom(db, user_id, **fields):
        raise RuntimeError("mutación deliberada: fallo tras import_rows")

    seed_phase_defs()
    head = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99550060")
    # La ruta hace `db.rollback()`: sin este checkpoint se llevaría también los
    # datos del fixture.
    db_session.commit()
    monkeypatch.setattr(sps_mod.StudentProfileService, "set_fields", staticmethod(_boom))

    resp = client_as(head).post(f"{URL}/{req.id}/aprobar",
                                data={"nip": NIP, "program_id": ""})

    assert resp.status_code == 400
    assert NIP not in resp.text
    assert NIP not in "".join(resp.headers.values())
    assert db_session.query(User).filter_by(control_number="99550060").first() is None
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0
    db_session.refresh(req)
    assert req.status == "pending_review"

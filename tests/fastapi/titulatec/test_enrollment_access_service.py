"""Acceso en dos pasos (spec 2026-09-24): SE aprueba, Centro de Cómputo da el NIP.

Máquina de estados que fija este archivo (nivel servicio):

    approve() [SE, oficial]  SIN cuenta -> awaiting_access   (sin usuario, sin correo)
    approve() [CC, alterno]  SIN cuenta -> converted         (usuario + NIP, como antes)
    grant_access() [CC]      awaiting_access -> converted    (usuario + NIP al correo personal)
                                          \\-> approved      (D10: apareció una cuenta; liga)
    return_to_review() [CC]  awaiting_access -> pending_review (return_note, sin correo)
    reject()                 awaiting_access -> rejected

Invariantes: `(False, motivo)` no deja nada escrito; el NIP nunca sale (log,
retorno, payload); correo e invalidación de authz SIEMPRE después del commit;
toda transición toma el lock de la solicitud y refresca antes de leer estado.
"""
from __future__ import annotations

import inspect
import json
import logging
from datetime import date, datetime, timedelta

import pytest

NIP = "5738"
MSG_EN_COMPUTO = "Ya está en Centro de Cómputo para su acceso."
MSG_NO_ESPERA = "Esa solicitud ya no está esperando acceso."
MSG_NOTA = "Escribe el motivo de la devolución."
MSG_NOTA_LARGA = "El motivo de la devolución no puede pasar de 2000 caracteres."
MSG_NIP = "El NIP debe ser exactamente 4 dígitos."


# ---------------------------------------------------------------------------
# Fixtures locales (patrón de la suite: no se importan de otro archivo)
# ---------------------------------------------------------------------------
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
def espia_helper(monkeypatch):
    """Sustituye TODOS los `send_*` del helper por un registro de llamadas."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    llamadas = []
    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(
            TitulaTecEmailHelper, nombre,
            staticmethod(lambda *a, _n=nombre, **k: llamadas.append(_n) or True))
    return llamadas


@pytest.fixture()
def orden(db_session, monkeypatch):
    """Registra en orden cada commit, cada correo y cada invalidación de authz."""
    from itcj2.core.services import authz_cache

    pasos, enviados = [], []
    commit_real = db_session.commit

    def _commit():
        pasos.append("commit")
        return commit_real()

    class _Resp:
        status_code = 202
        text = ""

    def _fake_send(access_token, subject, content_html, to_list, save_to_sent=True):
        pasos.append("correo")
        enviados.append((subject, list(to_list), content_html))
        return _Resp()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: "token-de-prueba")
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _fake_send)
    monkeypatch.setattr(authz_cache, "invalidate_user_app",
                        lambda user_id, app_key: pasos.append(("authz", user_id, app_key)))
    return pasos, enviados


# `modo_alterno` vive en conftest.py (C7/I-1 de la revision final: una sola
# copia compartida en vez de 4 duplicadas por archivo).


def _svc():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


def _make_req(db_session, cohort, *, control, status="pending_review", program=None,
              reviewed_by=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="DE COMPUTO", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="acceso@example.invalid",
        has_efirma=True, kind="unknown", status=status, verify_send_count=0,
        reviewed_by_id=getattr(reviewed_by, "id", reviewed_by),
        reviewed_at=datetime.now() - timedelta(hours=2) if reviewed_by else None,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control, *, password=True, must_change=False):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control,
                first_name="YA", last_name="EXISTIA",
                password_hash=hash_nip("9999") if password else None,
                is_active=True, must_change_password=must_change)
    db_session.add(user)
    db_session.flush()
    return user


def _usuarios(db_session, control):
    from itcj2.core.models.user import User
    return db_session.query(User).filter_by(control_number=control).count()


def _en_espera(db_session, make_cohort, make_user, *, control, cohort=None, **kw):
    """Solicitud que SE ya aprobó y espera a Centro de Cómputo."""
    se = make_user(first_name="SERVICIOS", last_name="ESCOLARES")
    cohort = cohort or make_cohort(status="open")
    req = _make_req(db_session, cohort, control=control, status="awaiting_access",
                    reviewed_by=se, **kw)
    return req, se, cohort


def _cuerpo(metodo) -> str:
    src = inspect.getsource(metodo)
    _, _, cuerpo = src.partition('"""')
    _, _, cuerpo = cuerpo.partition('"""')
    return cuerpo


# ---------------------------------------------------------------------------
# Modo y etiqueta de quien revisa
# ---------------------------------------------------------------------------
def test_el_modo_oficial_es_el_de_por_omision_y_lo_revisa_servicios_escolares():
    svc = _svc()
    assert svc.reviewer_mode() == "school_services"
    assert svc.reviewer_label() == "Servicios Escolares"


def test_en_modo_alterno_la_etiqueta_es_centro_de_computo(modo_alterno):
    assert _svc().reviewer_label() == "Centro de Cómputo"


def test_el_modo_sale_de_la_variable_de_entorno(monkeypatch):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_ENROLLMENT_REVIEWER", "computer_center")
    assert _svc().reviewer_mode() == "computer_center"


# ---------------------------------------------------------------------------
# approve() en modo OFICIAL, sin cuenta: pasa a Cómputo, sin usuario ni correo
# ---------------------------------------------------------------------------
def test_aprobar_sin_cuenta_en_modo_oficial_pasa_a_computo_sin_usuario_ni_correo(
    db_session, make_cohort, make_user, make_program, seed_phase_defs, titulatec_app,
    espia_helper,
):
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    se = make_user()
    program = make_program("Ingenieria En Computo")
    cohort = make_cohort(status="open")
    req = _make_req(db_session, cohort, control="99560001")

    ok, detalle = _svc().approve(db_session, req.id, nip="", program_id=program.id,
                                 actor_id=se.id)

    assert (ok, detalle) == (True, "")
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert req.program_id == program.id
    assert req.reviewed_by_id == se.id and req.reviewed_at is not None
    assert req.access_granted_at is None and req.verify_token_hash is None
    assert _usuarios(db_session, "99560001") == 0
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0
    assert espia_helper == [], "el alumno no se entera del paso intermedio"


def test_aprobar_en_modo_oficial_no_valida_el_nip(db_session, make_cohort, make_user,
                                                 espia_helper):
    """El NIP ya no es de SE: un valor basura no bloquea la aprobación."""
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99560002")

    ok, _ = _svc().approve(db_session, req.id, nip="abc", program_id=None, actor_id=se.id)

    assert ok is True and req.status == "awaiting_access"


def test_aprobar_una_solicitud_que_ya_esta_en_computo_da_su_propio_motivo(
    db_session, make_cohort, make_user, espia_helper,
):
    req, se, _ = _en_espera(db_session, make_cohort, make_user, control="99560003")

    assert _svc().approve(db_session, req.id, nip=NIP, program_id=None,
                          actor_id=se.id) == (False, MSG_EN_COMPUTO)
    assert req.status == "awaiting_access"
    assert espia_helper == []


def test_una_devuelta_por_computo_se_puede_volver_a_aprobar(
    db_session, make_cohort, make_user, espia_helper,
):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99560004",
                    returned_by_id=se.id, returned_at=datetime.now(),
                    return_note="Faltaba la carrera.")

    ok, _ = _svc().approve(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert ok is True and req.status == "awaiting_access"
    assert req.return_note == "Faltaba la carrera.", "la nota de CC queda como historia"


# ---------------------------------------------------------------------------
# approve() en modo ALTERNO, sin cuenta: CC crea el usuario de una vez
# ---------------------------------------------------------------------------
def test_aprobar_sin_cuenta_en_modo_alterno_crea_usuario_y_manda_el_nip(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, orden,
    modo_alterno,
):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip

    pasos, enviados = orden
    seed_phase_defs()
    cc = make_user(first_name="CENTRO", last_name="COMPUTO")
    req = _make_req(db_session, make_cohort(status="open"), control="99560010")

    ok, folio = _svc().approve(db_session, req.id, nip=NIP, program_id=None,
                               actor_id=cc.id)

    assert ok is True and folio
    assert req.status == "converted"
    assert req.reviewed_by_id == cc.id
    assert req.access_granted_by_id == cc.id and req.access_granted_at is not None
    assert req.access_sent_at is not None, "el correo salió: se sella"
    user = db_session.query(User).filter_by(control_number="99560010").one()
    assert verify_nip(NIP, user.password_hash) and user.must_change_password is True
    assert pasos[0] == "commit"
    assert pasos.count("correo") == 1
    (_a, destinatarios, html), = enviados
    assert destinatarios == ["acceso@example.invalid"] and NIP in html


def test_aprobar_en_modo_alterno_sin_cuenta_exige_el_nip(
    db_session, make_cohort, make_user, correo_falso, modo_alterno,
):
    cc = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99560011")

    for nip in ("", "12", "abcd", "12345"):
        assert _svc().approve(db_session, req.id, nip=nip, program_id=None,
                              actor_id=cc.id) == (False, MSG_NIP)
    assert req.status == "pending_review"
    assert _usuarios(db_session, "99560011") == 0
    assert correo_falso == []


# ---------------------------------------------------------------------------
# grant_access(): SIN cuenta -> usuario + NIP
# ---------------------------------------------------------------------------
def test_dar_acceso_crea_la_cuenta_con_el_nip_y_conserva_la_revision_de_se(
    db_session, make_cohort, make_user, make_program, seed_phase_defs, titulatec_app,
    correo_falso,
):
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess

    seed_phase_defs()
    program = make_program("Ingenieria Con NIP De Computo")
    req, se, cohort = _en_espera(db_session, make_cohort, make_user, control="99560020",
                                 program=program)
    revisado_en = req.reviewed_at
    cc = make_user(first_name="CENTRO", last_name="COMPUTO")

    ok, folio = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)

    assert ok is True
    db_session.refresh(req)
    assert req.status == "converted"
    assert (req.reviewed_by_id, req.reviewed_at) == (se.id, revisado_en), (
        "dar acceso no reescribe quién aprobó")
    assert req.access_granted_by_id == cc.id and req.access_granted_at is not None
    assert req.access_sent_at is not None
    assert _svc().access_mail_unsent(req) is False, "el correo salió"
    user = db_session.query(User).filter_by(control_number="99560020").one()
    assert user.username == "99560020"
    assert verify_nip(NIP, user.password_hash)
    assert user.must_change_password is True and user.is_active is True
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == user.id and proc.cohort_id == cohort.id
    assert proc.program_id == program.id and proc.folio == folio
    perfil = db_session.get(StudentProfile, user.id)
    assert perfil.contact_email == "acceso@example.invalid"
    assert perfil.has_efirma is True
    ev = (db_session.query(ProcessEvent)
          .filter_by(process_id=proc.id, event_type="enrollment_self_service").one())
    assert ev.actor_id == cc.id
    assert ev.payload["approved_by_id"] == se.id
    assert ev.payload["granted_by_id"] == cc.id
    (_a, destinatarios, html), = correo_falso
    assert destinatarios == ["acceso@example.invalid"]
    assert NIP in html and "99560020" in html


def test_dar_acceso_commitea_y_despues_tira_authz_y_manda_el_correo(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, orden,
):
    from itcj2.core.models.user import User

    pasos, _enviados = orden
    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560021")
    cc = make_user()

    ok, _ = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)

    assert ok is True
    user = db_session.query(User).filter_by(control_number="99560021").one()
    primer_commit = pasos.index("commit")
    authz = [i for i, p in enumerate(pasos) if isinstance(p, tuple)]
    assert authz and min(authz) > primer_commit, pasos
    assert {pasos[i][1:] for i in authz} == {(user.id, "itcj"), (user.id, "titulatec")}
    assert pasos.index("correo") > primer_commit
    assert pasos.count("correo") == 1


def test_dar_acceso_llama_una_sola_vez_al_correo_de_alta(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560022")

    ok, _ = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert ok is True
    assert espia_helper == ["send_enrollment_approved"]


def test_si_el_correo_no_sale_access_sent_at_queda_vacio(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: False))
    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560023")

    ok, _ = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert ok is True, "el acceso no depende de que el correo salga"
    assert req.status == "converted"
    assert req.access_granted_at is not None
    assert req.access_sent_at is None
    assert _svc().access_mail_unsent(req) is True, "la bandeja marca «correo no enviado»"


def test_dar_acceso_exige_un_nip_de_4_digitos_y_no_escribe_nada(
    db_session, make_cohort, make_user, correo_falso,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560024")
    cc = make_user()

    for nip in ("", "12", "abcd", "12345", None):
        assert _svc().grant_access(db_session, req.id, nip=nip,
                                   actor_id=cc.id) == (False, MSG_NIP)
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.access_granted_at is None
    assert _usuarios(db_session, "99560024") == 0
    assert correo_falso == []


@pytest.mark.parametrize("status", ["pending_review", "approved", "converted",
                                    "rejected", "unverified"])
def test_solo_se_da_acceso_a_una_solicitud_en_espera(
    db_session, make_cohort, make_user, correo_falso, status,
):
    req = _make_req(db_session, make_cohort(status="open"), control="99560025",
                    status=status)

    assert _svc().grant_access(db_session, req.id, nip=NIP,
                               actor_id=make_user().id) == (False, MSG_NO_ESPERA)
    db_session.refresh(req)
    assert req.status == status and req.access_granted_at is None
    assert _usuarios(db_session, "99560025") == 0
    assert correo_falso == []


@pytest.mark.parametrize("nip", ["１２３４", "١٢٣٤", "12３4"])
def test_el_nip_son_4_digitos_ascii_no_cualquier_digito_unicode(
    db_session, make_cohort, make_user, correo_falso, nip,
):
    """`\\d` de `re` acepta dígitos de ancho completo o arábigos: un NIP así no
    se puede teclear en el login. Una sola regla (`_NIP_RE`, `[0-9]{4}`)."""
    from itcj2.apps.titulatec.services import enrollment_request_service as mod

    assert mod._NIP_RE.pattern == "[0-9]{4}"
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560032")

    assert _svc().grant_access(db_session, req.id, nip=nip,
                               actor_id=make_user().id) == (False, MSG_NIP)
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert _usuarios(db_session, "99560032") == 0
    assert correo_falso == []


def test_la_regla_del_nip_vive_en_un_solo_lugar():
    """`re.fullmatch(r"\\d{4}", ...)` estaba copiado en `_create_account` y en
    `reassign_nip`: dos copias de una regla divergen."""
    import inspect as _inspect

    from itcj2.apps.titulatec.services import enrollment_request_service as mod

    src = _inspect.getsource(mod)
    assert r"\d{4}" not in src
    assert src.count("_NIP_RE.fullmatch(") == 2


def test_dar_acceso_a_una_solicitud_inexistente(db_session):
    assert _svc().grant_access(db_session, 987654321, nip=NIP, actor_id=1) == (
        False, "La solicitud ya no existe.")


def test_dar_acceso_con_la_convocatoria_cerrada_no_cambia_nada(
    db_session, make_cohort, make_user, correo_falso,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560026",
                             cohort=make_cohort(status="closed"))

    assert _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id) == (
        False, "Esa convocatoria está cerrada.")
    assert req.status == "awaiting_access"
    assert _usuarios(db_session, "99560026") == 0
    assert correo_falso == []


def test_dar_acceso_con_la_ventana_publica_vencida_si_procede(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """Review Focus 2 / D5: pasada `closes_at` se sigue dando acceso a lo que
    entró a tiempo; solo `status='closed'` pausa."""
    from itcj2.apps.titulatec.services.cohort_service import CohortService

    seed_phase_defs()
    hoy = date.today()
    cohort = make_cohort(status="open", opens_at=hoy - timedelta(days=30),
                         closes_at=hoy - timedelta(days=1))
    assert CohortService.is_public_enrollment_open(cohort) is False
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560027",
                             cohort=cohort)

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert ok is True, detalle
    assert req.status == "converted"
    assert len(correo_falso) == 1


def test_doble_clic_en_dar_acceso_manda_un_solo_nip(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560028")
    cc = make_user()

    primero = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)
    segundo = _svc().grant_access(db_session, req.id, nip="1111", actor_id=cc.id)

    assert primero[0] is True and segundo == (False, MSG_NO_ESPERA)
    assert len(correo_falso) == 1


def test_el_nip_no_sale_ni_en_el_log_ni_en_el_retorno_ni_en_el_payload(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    caplog,
):
    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560029")

    with caplog.at_level(logging.DEBUG):
        resultado = _svc().grant_access(db_session, req.id, nip=NIP,
                                        actor_id=make_user().id)

    assert resultado[0] is True
    assert NIP not in repr(resultado)
    assert NIP not in caplog.text
    # Control positivo: sin esto, un caplog que no captura nada (nivel mal
    # puesto, handler que no llegó) daria el mismo "NIP not in caplog.text"
    # por una razon completamente distinta. `_deliver` (email_helper.py:132)
    # SI debe dejar esta linea con el correo mockeado (`correo_falso`).
    assert "enrollment_approved" in caplog.text
    eventos = (db_session.query(ProcessEvent)
               .filter_by(process_id=req.converted_process_id).all())
    assert eventos
    for ev in eventos:
        assert NIP not in json.dumps(ev.payload or {})


def test_si_no_se_crea_el_proceso_dar_acceso_no_deja_nada_escrito(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    from itcj2.apps.titulatec.services import import_service

    monkeypatch.setattr(import_service.ImportService, "import_rows",
                        staticmethod(lambda *a, **k: {"processes_created": 0}))
    seed_phase_defs()
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560030")

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP,
                                      actor_id=make_user().id)

    assert ok is False
    assert detalle == "No se pudo crear el proceso; revisa los datos de la solicitud."
    assert _usuarios(db_session, "99560030") == 0
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.access_granted_at is None
    assert correo_falso == []


def test_una_excepcion_tras_import_rows_sube_y_el_rollback_no_deja_huerfanos(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    """La ruta hace `rollback()` ante una excepción: no puede quedar un `User` ni
    un proceso a medias, y la solicitud sigue esperando acceso."""
    import itcj2.core.services.student_profile_service as sps_mod
    from itcj2.apps.titulatec.models import TitulationProcess

    def _boom(db, user_id, **fields):
        raise RuntimeError("mutación deliberada: fallo tras import_rows")

    seed_phase_defs()
    req, _se, cohort = _en_espera(db_session, make_cohort, make_user, control="99560031")
    cc = make_user()
    db_session.commit()          # checkpoint: el rollback no se lleva el fixture
    monkeypatch.setattr(sps_mod.StudentProfileService, "set_fields", staticmethod(_boom))

    with pytest.raises(RuntimeError):
        _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)
    db_session.rollback()

    assert _usuarios(db_session, "99560031") == 0
    assert db_session.query(TitulationProcess).filter_by(cohort_id=cohort.id).count() == 0
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert correo_falso == []


# ---------------------------------------------------------------------------
# grant_access(): CON cuenta (D10) -> liga, el NIP se ignora
# ---------------------------------------------------------------------------
def test_si_aparecio_una_cuenta_dar_acceso_se_desvia_a_la_liga(
    db_session, make_cohort, make_user, correo_falso,
):
    """Review Focus 1: un CSV o un alta manual creó la cuenta entre la aprobación
    de SE y el NIP de CC. Crear otra reventaría con `IntegrityError` de
    `core_users.username`; el NIP pisaría la contraseña real."""
    from itcj2.core.utils.security import verify_nip

    req, se, _ = _en_espera(db_session, make_cohort, make_user, control="99560040")
    cuenta = _cuenta(db_session, "99560040")
    hash_antes = cuenta.password_hash
    cc = make_user()

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)

    assert (ok, detalle) == (True, "")
    assert req.status == "approved"
    assert req.verify_token_hash is not None and req.verify_send_count == 1
    assert req.reviewed_by_id == se.id
    assert req.access_granted_by_id == cc.id and req.access_granted_at is not None
    assert req.access_sent_at is None, "la liga se sella en verify_sent_at"
    assert req.verify_sent_at is not None
    assert _svc().access_mail_unsent(req) is False, (
        "sin access_sent_at, pero D10 no manda NIP: no es «correo no enviado»")
    db_session.refresh(cuenta)
    assert cuenta.password_hash == hash_antes and not verify_nip(NIP, cuenta.password_hash)
    assert _usuarios(db_session, "99560040") == 1
    (_a, destinatarios, html), = correo_falso
    assert destinatarios == ["acceso@example.invalid"]
    assert "/inscripcion/verificar?t=" in html and NIP not in html


def test_con_cuenta_dar_acceso_ignora_un_nip_invalido(
    db_session, make_cohort, make_user, correo_falso,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560041")
    _cuenta(db_session, "99560041")

    ok, _ = _svc().grant_access(db_session, req.id, nip="", actor_id=make_user().id)

    assert ok is True and req.status == "approved"


def test_con_cuenta_sin_contrasena_dar_acceso_no_escribe_nada(
    db_session, make_cohort, make_user, correo_falso,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560042")
    _cuenta(db_session, "99560042", password=False)

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert ok is False
    # Revisión final: el de SE («dala de alta desde la convocatoria y
    # rechaza») es una instrucción que CC no puede cumplir.
    assert detalle == MSG_CC_SIN_CONTRASENA
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert req.verify_token_hash is None and req.access_granted_at is None
    assert correo_falso == []


MSG_CC_SIN_CONTRASENA = ("Esa cuenta no tiene contraseña; devuélvela a Servicios "
                         "Escolares con esa nota para que la dé de alta desde la "
                         "convocatoria.")
MSG_CC_OTRA_CONVOCATORIA = ("Esa persona ya tiene un proceso en otra convocatoria; "
                            "devuélvela a Servicios Escolares con esa nota.")


def test_con_cuenta_en_otra_convocatoria_cc_recibe_su_propia_instruccion(
    db_session, make_cohort, make_user, make_process, correo_falso,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560043")
    cuenta = _cuenta(db_session, "99560043")
    make_process(cuenta, cohort=make_cohort(status="open"))

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert (ok, detalle) == (False, MSG_CC_OTRA_CONVOCATORIA)
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.verify_token_hash is None
    assert correo_falso == []


def test_en_modo_alterno_dar_acceso_con_cuenta_sin_contrasena_no_manda_a_devolver(
    db_session, make_cohort, make_user, correo_falso, modo_alterno,
):
    """En el alterno no existe «devolver»: la sobrante `awaiting_access` da el
    mismo motivo que `approve()` le da a CC en ese modo."""
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560044")
    _cuenta(db_session, "99560044", password=False)

    ok, detalle = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)

    assert ok is False
    assert "devuélvela" not in detalle
    assert detalle == ("Esa cuenta no tiene contraseña; dala de alta desde la "
                       "convocatoria y rechaza esta solicitud.")


# ---------------------------------------------------------------------------
# return_to_review(): CC devuelve a SE con nota, sin correo
# ---------------------------------------------------------------------------
def test_devolver_regresa_a_por_revisar_con_la_nota_y_sin_correo(
    db_session, make_cohort, make_user, espia_helper,
):
    req, se, _ = _en_espera(db_session, make_cohort, make_user, control="99560050")
    revisado_en = req.reviewed_at
    cc = make_user()

    ok, detalle = _svc().return_to_review(db_session, req.id,
                                          note="  La carrera no coincide.  ",
                                          actor_id=cc.id)

    assert (ok, detalle) == (True, "")
    db_session.refresh(req)
    assert req.status == "pending_review"
    assert req.return_note == "La carrera no coincide."
    assert req.returned_by_id == cc.id and req.returned_at is not None
    assert (req.reviewed_by_id, req.reviewed_at) == (se.id, revisado_en)
    assert espia_helper == [], "devolver no avisa al alumno"


def test_devolver_exige_nota(db_session, make_cohort, make_user, espia_helper):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560051")

    for nota in ("", "   ", None):
        assert _svc().return_to_review(db_session, req.id, note=nota,
                                       actor_id=make_user().id) == (False, MSG_NOTA)
    db_session.refresh(req)
    assert req.status == "awaiting_access" and req.returned_at is None


def test_devolver_rechaza_una_nota_de_mas_de_2000_sin_escribir(
    db_session, make_cohort, make_user, espia_helper,
):
    """Brief: «nota obligatoria (≤2000)». Pasarse se rechaza con motivo; recortar
    en silencio le perdería a CC el final de lo que escribió."""
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560052")

    assert _svc().return_to_review(db_session, req.id, note="x" * 2001,
                                   actor_id=make_user().id) == (False, MSG_NOTA_LARGA)
    db_session.refresh(req)
    assert req.status == "awaiting_access"
    assert req.returned_at is None and req.return_note is None


def test_devolver_acepta_una_nota_de_2000_exactos_tras_quitar_espacios(
    db_session, make_cohort, make_user, espia_helper,
):
    req, _se, _ = _en_espera(db_session, make_cohort, make_user, control="99560054")

    ok, _ = _svc().return_to_review(db_session, req.id, note="  " + "x" * 2000 + "  ",
                                    actor_id=make_user().id)

    assert ok is True and req.return_note == "x" * 2000


@pytest.mark.parametrize("status", ["pending_review", "approved", "converted", "rejected"])
def test_solo_se_devuelve_una_solicitud_en_espera(
    db_session, make_cohort, make_user, espia_helper, status,
):
    req = _make_req(db_session, make_cohort(status="open"), control="99560053",
                    status=status)

    assert _svc().return_to_review(db_session, req.id, note="motivo",
                                   actor_id=make_user().id) == (False, MSG_NO_ESPERA)
    db_session.refresh(req)
    assert req.status == status and req.returned_at is None


def test_devolver_una_solicitud_inexistente(db_session):
    assert _svc().return_to_review(db_session, 987654321, note="motivo",
                                   actor_id=1) == (False, "La solicitud ya no existe.")


# ---------------------------------------------------------------------------
# reject(): SE puede cancelar una solicitud que espera acceso
# ---------------------------------------------------------------------------
def test_rechazar_una_solicitud_en_espera_de_acceso(
    db_session, make_cohort, make_user, correo_falso,
):
    req, se, _ = _en_espera(db_session, make_cohort, make_user, control="99560060")

    assert _svc().reject(db_session, req.id, note="La persona pidió cancelar.",
                         actor_id=se.id) is True
    assert req.status == "rejected"
    (_a, destinatarios, html), = correo_falso
    assert destinatarios == ["acceso@example.invalid"]
    assert "Servicios Escolares" in html


def test_en_modo_alterno_el_rechazo_lo_firma_centro_de_computo(
    db_session, make_cohort, make_user, correo_falso, modo_alterno,
):
    req = _make_req(db_session, make_cohort(status="open"), control="99560061")

    assert _svc().reject(db_session, req.id, note="No aparece en el padrón.",
                         actor_id=make_user().id) is True
    (_a, _d, html), = correo_falso
    assert "Centro de Cómputo" in html
    assert "Servicios Escolares" not in html


# ---------------------------------------------------------------------------
# Concurrencia: lock + refresh ANTES de leer el estado, en cada método nuevo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nombre", ["grant_access", "return_to_review"])
def test_cada_transicion_nueva_toma_lock_y_refresca_antes_de_leer_status(nombre):
    cuerpo = _cuerpo(getattr(_svc(), nombre))
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("req.status"), nombre


# ---------------------------------------------------------------------------
# reassign_nip(): el correo con el NIP no salió (D8)
# ---------------------------------------------------------------------------
MSG_NO_REASIGNABLE = ("Solo se reasigna el NIP de una cuenta que creó esta solicitud "
                      "y que nunca ha iniciado sesión.")


def _con_acceso(db_session, make_cohort, make_user, *, control):
    """Solicitud a la que CC ya dio acceso y cuyo correo NO salió.

    El fallo del correo se simula solo durante `grant_access` y se restaura lo
    que hubiera antes (el espía o `correo_falso` del test siguen armados)."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    original = TitulaTecEmailHelper.__dict__["send_enrollment_approved"]
    TitulaTecEmailHelper.send_enrollment_approved = staticmethod(lambda *a, **k: False)
    try:
        req, _se, _ = _en_espera(db_session, make_cohort, make_user, control=control)
        ok, _ = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)
    finally:
        TitulaTecEmailHelper.send_enrollment_approved = original
    assert ok is True and req.access_sent_at is None
    user = db_session.query(User).filter_by(control_number=control).one()
    return req, user


def _eventos_reset(db_session, req):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db_session.query(ProcessEvent)
            .filter_by(process_id=req.converted_process_id,
                       event_type="enrollment_access_reset").all())


def test_reasignar_nip_reescribe_la_contrasena_y_reenvia(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    caplog,
):
    from itcj2.core.utils.security import verify_nip

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560070")
    otro_cc = make_user(first_name="OTRO", last_name="COMPUTO")
    assert _svc().access_mail_unsent(req) is True

    with caplog.at_level(logging.DEBUG):
        resultado = _svc().reassign_nip(db_session, req.id, nip="2604", actor_id=otro_cc.id)

    assert resultado == (True, "")
    db_session.refresh(user)
    assert verify_nip("2604", user.password_hash)
    assert not verify_nip(NIP, user.password_hash)
    assert user.must_change_password is True
    assert req.status == "converted"
    assert req.access_granted_by_id == otro_cc.id
    assert req.access_sent_at is not None, "el correo nuevo sí salió: se sella"
    assert _svc().access_mail_unsent(req) is False
    (_a, destinatarios, html), = correo_falso
    assert destinatarios == ["acceso@example.invalid"] and "2604" in html
    (ev,) = _eventos_reset(db_session, req)
    assert ev.actor_id == otro_cc.id
    assert ev.payload == {"request_id": req.id}
    assert "2604" not in caplog.text
    # Control positivo (mismo motivo que arriba): la captura de logs si
    # funciona, y `_deliver` si dejo su linea con el correo mockeado.
    assert "enrollment_approved" in caplog.text


def test_reasignar_nip_commitea_antes_de_mandar_y_sin_correo_sigue_no_enviado(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, monkeypatch,
):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    seed_phase_defs()
    req, _user = _con_acceso(db_session, make_cohort, make_user, control="99560071")
    pasos = []
    commit_real = db_session.commit

    def _commit():
        pasos.append("commit")
        return commit_real()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: pasos.append("correo") or False))

    assert _svc().reassign_nip(db_session, req.id, nip="2605",
                               actor_id=make_user().id) == (True, "")
    assert pasos == ["commit", "correo"]
    assert req.access_sent_at is None, "sin correo, sigue «no enviado»"


def test_reasignar_exige_un_nip_de_4_digitos(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560072")
    antes = user.password_hash

    for nip in ("", "12", "abcd", None, "１２３４"):
        assert _svc().reassign_nip(db_session, req.id, nip=nip,
                                   actor_id=make_user().id) == (False, MSG_NIP)
    db_session.refresh(user)
    assert user.password_hash == antes
    assert _eventos_reset(db_session, req) == []
    assert espia_helper == []


def _intentar_sin_escribir(db_session, req, user, espia_helper, actor):
    antes = user.password_hash
    sellado = (req.access_granted_by_id, req.access_granted_at)
    assert _svc().reassign_nip(db_session, req.id, nip="2606",
                               actor_id=actor.id) == (False, MSG_NO_REASIGNABLE)
    db_session.refresh(user)
    db_session.refresh(req)
    assert user.password_hash == antes
    assert (req.access_granted_by_id, req.access_granted_at) == sellado
    assert espia_helper == []


def test_no_se_reasigna_si_la_persona_ya_entro(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """Review Focus 5: `must_change_password=False` = ya cambió su NIP."""
    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560073")
    user.must_change_password = False
    db_session.flush()

    _intentar_sin_escribir(db_session, req, user, espia_helper, make_user())
    assert _eventos_reset(db_session, req) == []


def test_no_se_reasigna_si_la_persona_ya_inicio_sesion(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """Revisión final C1: `must_change_password` NO dice «no ha entrado». En un
    egresado nunca se limpia (nada lo obliga a cambiar el NIP), así que una
    cuenta que lleva semanas en TitulaTec lo sigue teniendo en True. La señal es
    `last_login`, que sella `authenticate` en cada inicio de sesión."""
    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560081")
    user.last_login = datetime.now() - timedelta(days=3)
    db_session.flush()
    assert user.must_change_password is True, "premisa: la marca sigue puesta"
    assert _svc().can_reassign_nip(req, user) is False

    _intentar_sin_escribir(db_session, req, user, espia_helper, make_user())
    assert _eventos_reset(db_session, req) == []


def test_reasignar_revoca_las_sesiones_de_la_cuenta_en_la_misma_transaccion(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
    monkeypatch,
):
    """Quien tuviera sesión con el NIP anterior (p. ej. el dueño del correo mal
    escrito) la pierde: `bump_version` sube `session_epoch` ANTES del commit."""
    from itcj2.core.services import session_service

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560082")
    db_session.refresh(user)
    epoca = user.session_epoch
    pasos = []
    bump_real, commit_real = session_service.bump_version, db_session.commit

    def _bump(user_id, db=None):
        pasos.append(("bump", user_id, db is db_session))
        return bump_real(user_id, db=db)

    def _commit():
        pasos.append("commit")
        return commit_real()

    monkeypatch.setattr(session_service, "bump_version", _bump)
    monkeypatch.setattr(db_session, "commit", _commit)

    assert _svc().reassign_nip(db_session, req.id, nip="2609",
                               actor_id=make_user().id) == (True, "")

    assert pasos[0] == ("bump", user.id, True), pasos
    assert pasos[1] == "commit"
    db_session.refresh(user)
    assert user.session_epoch == epoca + 1


def test_reasignar_no_escribe_si_no_pudo_revocar_las_sesiones(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
    monkeypatch,
):
    """`bump_version` nunca lanza: devuelve `None`. Cambiar la credencial sin
    revocar las sesiones vivas es justo lo que el remedio quiere evitar."""
    from itcj2.core.services import session_service

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560083")
    antes = user.password_hash
    db_session.commit()          # checkpoint: el rollback no se lleva el fixture
    monkeypatch.setattr(session_service, "bump_version", lambda user_id, db=None: None)

    with pytest.raises(RuntimeError):
        _svc().reassign_nip(db_session, req.id, nip="2610", actor_id=make_user().id)
    db_session.rollback()

    db_session.refresh(user)
    assert user.password_hash == antes
    assert _eventos_reset(db_session, req) == []
    assert espia_helper == []


def test_reasignar_sin_correo_no_manda_nada_y_deja_access_sent_at_vacio(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """«No enviar correo; lo dicto por teléfono» (ruling 2026-09-25): el caso del
    correo mal escrito, donde reenviar le entregaría el NIP nuevo al mismo buzón
    equivocado."""
    from itcj2.core.utils.security import verify_nip

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560084")

    assert _svc().reassign_nip(db_session, req.id, nip="2611", actor_id=make_user().id,
                               send_mail=False) == (True, "")

    assert espia_helper == []
    db_session.refresh(user)
    db_session.refresh(req)
    assert verify_nip("2611", user.password_hash)
    assert req.access_sent_at is None
    (ev,) = _eventos_reset(db_session, req)
    assert ev.payload == {"request_id": req.id}


def test_el_correo_de_la_reasignacion_dice_que_reemplaza_al_anterior(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    seed_phase_defs()
    req, _user = _con_acceso(db_session, make_cohort, make_user, control="99560085")

    assert _svc().reassign_nip(db_session, req.id, nip="2612",
                               actor_id=make_user().id) == (True, "")

    (_asunto, _dest, html), = correo_falso
    assert "Este NIP reemplaza al que te enviamos antes" in html
    assert "2612" in html


def test_reassign_nip_bloquea_la_cuenta_antes_de_decidir():
    """La cuenta se lee con `FOR UPDATE` (y sin la copia del mapa de identidad)
    y la elegibilidad se decide bajo ese bloqueo: sin él, un cambio de
    contraseña concurrente quedaría pisado por el NIP."""
    cuerpo = _cuerpo(_svc().reassign_nip)
    bloqueo = cuerpo.index(".with_for_update()")
    assert ".populate_existing()" in cuerpo
    assert bloqueo < cuerpo.index("can_reassign_nip(req")
    assert bloqueo < cuerpo.index("_request_created_account(")
    assert cuerpo.index("bump_version(") < cuerpo.index("db.commit()")


def _d10_con_liga(db_session, make_cohort, make_user, correo_falso, *, control):
    """Fila D10 REAL: una cuenta del CSV apareció entre SE y CC y `grant_access`
    le emitió la liga. `(req, cuenta, token, cohort)`.

    La cuenta nace como la deja el CSV (`set_initial_credential`: contraseña =
    número de control y `must_change_password=True`, `import_service.py`), así
    que el guardia «la persona todavía no entra» no la distingue. El token sale
    del correo de la liga, como lo recibiría la persona."""
    import re
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.import_service import set_initial_credential

    req, _se, cohort = _en_espera(db_session, make_cohort, make_user, control=control)
    cuenta = User(username=control, control_number=control,
                  first_name="DEL", last_name="CSV", is_active=True)
    set_initial_credential(cuenta)
    db_session.add(cuenta)
    db_session.flush()

    ok, _ = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=make_user().id)
    assert ok is True and req.status == "approved"
    (_a, _d, html), = correo_falso
    token = re.search(r"verificar\?t=([A-Za-z0-9_\-]+)", html).group(1)
    correo_falso.clear()
    return req, cuenta, token, cohort


def _d10_convertida(db_session, make_cohort, make_user, correo_falso, *, control):
    """`_d10_con_liga` + la persona abrió la liga: `verify()` real la convirtió."""
    req, cuenta, token, _cohort = _d10_con_liga(db_session, make_cohort, make_user,
                                                correo_falso, control=control)
    _, outcome = _svc().verify(db_session, token)
    assert outcome == "converted"
    correo_falso.clear()   # el aviso con folio de `verify()`, si salió
    return req, cuenta


def test_no_se_reasigna_la_cuenta_d10_que_abrio_su_liga(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """Review Focus 5 / invariante 1, con la fila que existe en producción: la
    cuenta NO la creó la solicitud aunque `_convert` le haya creado el proceso."""
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    req, cuenta = _d10_convertida(db_session, make_cohort, make_user, correo_falso,
                                  control="99560074")
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    assert proc.student_id == cuenta.id, (
        "«la cuenta es la del proceso» NO la distingue: el proceso es de ELLA")
    assert cuenta.must_change_password is True and req.access_granted_at is not None
    assert req.verify_token_hash is not None, (
        "verify() conserva el hash al convertir (idempotencia ante Safe Links); las "
        "marcas puras dependen de eso para dejar fuera a D10")
    assert _svc().can_reassign_nip(req, cuenta) is False
    assert _svc().access_mail_unsent(req) is False

    _intentar_sin_escribir(db_session, req, cuenta, correo_falso, make_user())
    assert _eventos_reset(db_session, req) == []


def test_aunque_la_liga_usada_muriera_la_cuenta_d10_no_recibe_nip(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """Si un día `verify()` borra el hash al convertir («la liga usada muere»),
    la marca pura ya no distingue la fila D10. `reassign_nip` exige además la
    señal POSITIVA de que ESTA solicitud creó la cuenta."""
    seed_phase_defs()
    req, cuenta = _d10_convertida(db_session, make_cohort, make_user, correo_falso,
                                  control="99560078")
    req.verify_token_hash = None          # el endurecimiento hipotético
    db_session.flush()
    assert _svc().can_reassign_nip(req, cuenta) is True, "la marca pura sola ya no basta"

    _intentar_sin_escribir(db_session, req, cuenta, correo_falso, make_user())
    assert _eventos_reset(db_session, req) == []


def test_la_senal_de_cuenta_creada_debe_ser_de_esta_solicitud(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """El `enrollment_self_service` con NIP de OTRA solicitud no cuenta."""
    from itcj2.apps.titulatec.models import ProcessEvent

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560079")
    ev = (db_session.query(ProcessEvent)
          .filter_by(process_id=req.converted_process_id,
                     event_type="enrollment_self_service").one())
    ev.payload = {**ev.payload, "request_id": req.id + 100000}
    db_session.flush()

    _intentar_sin_escribir(db_session, req, user, espia_helper, make_user())
    assert _eventos_reset(db_session, req) == []


def test_una_d10_que_la_liga_devolvio_a_revision_no_marca_correo_no_enviado(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """La rama de fallo de `verify()` devuelve la fila a `pending_review` y
    conserva el sello `access_granted_*` de CC, sin `access_sent_at`: el
    predicado «granted lleno y sent vacío» la marcaría mal."""
    seed_phase_defs()
    req, cuenta, token, cohort = _d10_con_liga(db_session, make_cohort, make_user,
                                               correo_falso, control="99560080")
    cohort.status = "closed"
    db_session.flush()

    _, outcome = _svc().verify(db_session, token)

    assert outcome == "pending_review"
    assert req.access_granted_at is not None and req.access_sent_at is None
    assert _svc().access_mail_unsent(req) is False
    assert _svc().can_reassign_nip(req, cuenta) is False


def test_no_se_reasigna_una_fila_legado_sin_access_granted_at(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """Review Focus 5: convertida por el flujo de antes (SE daba el NIP)."""
    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560075")
    req.access_granted_at = None
    req.access_granted_by_id = None
    db_session.flush()

    _intentar_sin_escribir(db_session, req, user, espia_helper, make_user())


def test_no_se_reasigna_si_la_cuenta_del_control_no_es_la_del_proceso(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, espia_helper,
):
    """La cuenta que hoy tiene ese control no es la que creó la solicitud (se
    borró y otra la reemplazó): jamás se le escribe credencial."""
    from itcj2.apps.titulatec.models import TitulationProcess

    seed_phase_defs()
    req, user = _con_acceso(db_session, make_cohort, make_user, control="99560076")
    proc = db_session.get(TitulationProcess, req.converted_process_id)
    proc.student_id = make_user(first_name="AJENA").id
    db_session.flush()

    _intentar_sin_escribir(db_session, req, user, espia_helper, make_user())


@pytest.mark.parametrize("status", ["awaiting_access", "approved", "pending_review",
                                    "rejected"])
def test_solo_se_reasigna_una_convertida(db_session, make_cohort, make_user,
                                         espia_helper, status):
    req = _make_req(db_session, make_cohort(status="open"), control="99560077",
                    status=status, access_granted_at=datetime.now())

    assert _svc().reassign_nip(db_session, req.id, nip="2607",
                               actor_id=make_user().id) == (False, MSG_NO_REASIGNABLE)
    assert espia_helper == []


def test_reasignar_una_solicitud_inexistente(db_session):
    assert _svc().reassign_nip(db_session, 987654321, nip="2608", actor_id=1) == (
        False, "La solicitud ya no existe.")


def test_can_reassign_nip_es_puro_y_decide_el_boton():
    from types import SimpleNamespace as NS

    ahora = datetime.now()
    ok_req = NS(status="converted", access_granted_at=ahora, verify_token_hash=None)
    ok_user = NS(must_change_password=True, last_login=None)
    can = _svc().can_reassign_nip

    assert can(ok_req, ok_user) is True
    assert can(ok_req, None) is False
    assert can(ok_req, NS(must_change_password=False, last_login=None)) is False
    assert can(ok_req, NS(must_change_password=True, last_login=ahora)) is False, (
        "ya inició sesión: must_change_password no lo distingue (C1)")
    assert can(NS(status="approved", access_granted_at=ahora,
                  verify_token_hash=None), ok_user) is False
    assert can(NS(status="converted", access_granted_at=None,
                  verify_token_hash=None), ok_user) is False
    assert can(NS(status="converted", access_granted_at=ahora,
                  verify_token_hash="a" * 64), ok_user) is False


def test_access_mail_unsent_es_puro_y_decide_la_marca_correo_no_enviado():
    """El predicado de «correo no enviado» (D8) que consume la bandeja de CC.
    NO es «`access_granted_at` lleno y `access_sent_at` vacío»: eso también lo
    cumplen las filas D10 (liga) y las D10 que la liga devolvió a revisión."""
    from types import SimpleNamespace as NS

    ahora = datetime.now()
    marca = _svc().access_mail_unsent

    def fila(**kw):
        base = dict(status="converted", access_granted_at=ahora, access_sent_at=None,
                    verify_token_hash=None)
        base.update(kw)
        return NS(**base)

    assert marca(fila()) is True
    assert marca(fila(access_sent_at=ahora)) is False
    assert marca(fila(access_granted_at=None)) is False, "legado: SE daba el NIP"
    assert marca(fila(verify_token_hash="a" * 64)) is False, "D10 convertida por la liga"
    for status in ("approved", "pending_review", "awaiting_access", "rejected"):
        assert marca(fila(status=status)) is False, status


def test_reassign_nip_toma_lock_y_refresca_antes_de_leer_status():
    cuerpo = _cuerpo(_svc().reassign_nip)
    lock_pos = cuerpo.index("pg_advisory_xact_lock")
    refresh_pos = cuerpo.index("db.refresh(req)")
    assert lock_pos < refresh_pos < cuerpo.index("can_reassign_nip(req")

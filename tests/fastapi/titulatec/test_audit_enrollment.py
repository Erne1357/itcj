"""Bitácora de solicitudes de inscripción y accesos (spec 2026-10-07 §5, filas
«enrollment» y «access»; Tarea 5).

Cada acción explícita deja UNA fila `source='action'` en la transacción del
cambio (la red ORM escribe además filas `source='data'`, que aquí no se miran).
Nunca hay secretos en la fila (D9): ni NIP, ni liga, ni contacto completo.
La alta pública sale con `actor_kind='public'`.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from tests.fastapi.titulatec._sii_fake import pide_nip, sii  # noqa: F401
from tests.fastapi.titulatec.conftest import audit_query

# La bitácora de dev ya trae filas reales: solo las de ESTA prueba (`id > marca`).
pytestmark = pytest.mark.usefixtures("audit_mark")

ENROLL_URL = "/titulatec/inscripcion"
# NIP con cero a la izquierda y buscado como cifra AISLADA: un NIP corto
# aparece como subcadena de ids y timestamps.
NIP = "0482"
NIP_AISLADO = re.compile(r"(?<!\d)" + NIP + r"(?!\d)")


def _svc():
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService


def _acciones(db_session, action, **filtros):
    from itcj2.apps.titulatec.models import TitulatecAuditLog
    return (audit_query(db_session)
            .filter_by(source="action", action=action, **filtros)
            .order_by(TitulatecAuditLog.id).all())


def _fila_unica(db_session, action, req):
    filas = _acciones(db_session, action, entity_id=req.id)
    assert len(filas) == 1, [f.action for f in filas]
    return filas[0]


def _volcado(fila) -> str:
    """Todo lo que la fila guarda, en un solo texto (para buscar secretos)."""
    return repr([fila.reason, fila.subject_label, fila.before, fila.after,
                 fila.payload, fila.actor_label, fila.route])


def _sin_secretos(fila):
    texto = _volcado(fila)
    assert not NIP_AISLADO.search(texto), texto
    for prohibido in ("verify_token", "token_hash", "password", "contact_email",
                      "example.invalid", "6561234567", "t="):
        assert prohibido not in texto, (prohibido, texto)


def _make_req(db_session, cohort, *, control, status="pending_review", program=None, **kw):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="EGRESADA", last_name="AUDITADA", middle_name=None,
        program_id=getattr(program, "id", program), program_text="Ingenieria Ficticia",
        phone="6561234567", contact_email="auditoria@example.invalid",
        has_efirma=False, kind="unknown", status=status, verify_send_count=0,
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row


def _cuenta(db_session, control, *, password=True):
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control,
                first_name="YA", last_name="EXISTIA",
                password_hash=hash_nip(NIP) if password else None,
                is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def correo_ok(monkeypatch):
    """Ningún correo sale de verdad; el helper responde que salió."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        monkeypatch.setattr(TitulaTecEmailHelper, nombre,
                            staticmethod(lambda *a, **k: True))


# ---------------------------------------------------------------------------
# Alta pública
# ---------------------------------------------------------------------------
def test_alta_publica_queda_public_sin_contacto_ni_ip_en_payload(
    client, db_session, make_cohort, make_program, correo_ok,
):
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest

    cohort = make_cohort(status="open")
    (db_session.query(Cohort).filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()
    programa = make_program("Ingeniería Ficticia (bitácora)")
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data={
        "control_number": "99860001", "first_name": "ALUMNA", "last_name": "PUBLICA",
        "middle_name": "", "program_id": str(programa.id), "phone": "6561234567",
        "contact_email": "auditoria@example.invalid",
        "contact_email_confirm": "auditoria@example.invalid",
        "has_efirma": "0", "has_english": "1", "website": "",
    }, headers={"X-Real-IP": "203.0.113.77"}, follow_redirects=False)
    assert resp.status_code == 200, resp.text[:400]

    req = db_session.query(EnrollmentRequest).filter_by(control_number="99860001").one()
    fila = _fila_unica(db_session, "enrollment.request_created", req)
    assert fila.actor_kind == "public" and fila.actor_id is None
    assert fila.entity_type == "enrollment_request"
    assert fila.subject_label.startswith("99860001 · ")
    assert fila.ip == "203.0.113.77"            # va en SU columna
    texto = _volcado(fila)
    assert "203.0.113.77" not in repr(fila.payload)
    assert "auditoria@example.invalid" not in texto and "6561234567" not in texto
    _sin_secretos(fila)


# ---------------------------------------------------------------------------
# Aprobar
# ---------------------------------------------------------------------------
def test_aprobar_con_cuenta_registra_camino_existing_account(
    db_session, make_cohort, make_user, correo_ok,
):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860002")
    _cuenta(db_session, "99860002")

    r = _svc().approve_detailed(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert r.ok, r
    fila = _fila_unica(db_session, "enrollment.approved", req)
    assert fila.payload["path"] == "existing_account"
    assert fila.actor_id == se.id
    assert fila.subject_label.startswith("99860002 · ")
    assert fila.before == {"status": "pending_review"} and fila.after == {"status": "approved"}
    _sin_secretos(fila)


def test_aprobar_a_accesos_registra_camino_awaiting_access(
    db_session, make_cohort, make_user, correo_ok,
):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860003")

    r = _svc().approve_detailed(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert r.ok, r
    fila = _fila_unica(db_session, "enrollment.approved", req)
    assert fila.payload["path"] == "awaiting_access"
    assert fila.after == {"status": "awaiting_access"}
    _sin_secretos(fila)


def test_aprobar_cuenta_nueva_no_duplica_el_evento_de_proceso(
    db_session, make_cohort, make_user, modo_alterno, correo_ok,
):
    """La cuenta nueva ya escribe `enrollment_self_service`: lo refleja el espejo."""
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860004")

    r = _svc().approve_detailed(db_session, req.id, nip=NIP, program_id=None, actor_id=se.id)

    assert r.ok, r
    assert _acciones(db_session, "enrollment.approved", entity_id=req.id) == []
    espejo = (audit_query(db_session)
              .filter_by(source="process_event").all())
    assert espejo, "el espejo del enrollment_self_service debe existir"
    assert all(NIP_AISLADO.search(repr(f.payload)) is None for f in espejo)


def test_aprobar_fallido_no_deja_fila(db_session, make_cohort, make_user, correo_ok):
    """Cuenta sin contraseña: la aprobación falla ANTES de escribir; nada de «aprobado» fantasma."""
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860005")
    _cuenta(db_session, "99860005", password=False)

    r = _svc().approve_detailed(db_session, req.id, nip="", program_id=None, actor_id=se.id)

    assert not r.ok
    assert _acciones(db_session, "enrollment.approved", entity_id=req.id) == []


# ---------------------------------------------------------------------------
# Rechazar / reabrir / devolver
# ---------------------------------------------------------------------------
def test_rechazar_guarda_motivo_y_estados(db_session, make_cohort, make_user, correo_ok):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860006")

    assert _svc().reject(db_session, req.id, note="  No aparece en el padrón.  ",
                         actor_id=se.id) is True

    fila = _fila_unica(db_session, "enrollment.rejected", req)
    assert fila.reason == "No aparece en el padrón."
    assert fila.before == {"status": "pending_review"} and fila.after == {"status": "rejected"}
    assert fila.actor_id == se.id
    _sin_secretos(fila)


def test_rechazar_sin_motivo_no_deja_fila(db_session, make_cohort, make_user):
    req = _make_req(db_session, make_cohort(status="open"), control="99860007")
    assert _svc().reject(db_session, req.id, note="  ", actor_id=make_user().id) is False
    assert _acciones(db_session, "enrollment.rejected", entity_id=req.id) == []


def test_reabrir_guarda_motivo(db_session, make_cohort, make_user, correo_ok):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860008",
                    status="rejected", review_note="x", reviewed_at=datetime.now())

    ok = _svc().reopen(db_session, req.id, note="Trajo su constancia.", actor_id=se.id)

    assert ok == (True, "")
    fila = _fila_unica(db_session, "enrollment.reopened", req)
    assert fila.reason == "Trajo su constancia."
    assert fila.before == {"status": "rejected"} and fila.after == {"status": "pending_review"}
    _sin_secretos(fila)


def test_reabrir_rechazado_por_regla_no_deja_fila(db_session, make_cohort, make_user):
    req = _make_req(db_session, make_cohort(status="open"), control="99860009")  # no rechazada
    ok = _svc().reopen(db_session, req.id, note="algo", actor_id=make_user().id)
    assert ok[0] is False
    assert _acciones(db_session, "enrollment.reopened", entity_id=req.id) == []


def test_devolver_a_revision_registra_access_returned(
    db_session, make_cohort, make_user, correo_ok,
):
    se, cc = make_user(), make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860010",
                    status="awaiting_access", reviewed_by_id=se.id,
                    reviewed_at=datetime.now() - timedelta(hours=1))

    ok = _svc().return_to_review(db_session, req.id, note="Falta su CURP.", actor_id=cc.id)

    assert ok == (True, "")
    fila = _fila_unica(db_session, "access.returned", req)
    assert fila.reason == "Falta su CURP." and fila.actor_id == cc.id
    assert fila.before == {"status": "awaiting_access"}
    assert fila.after == {"status": "pending_review"}
    _sin_secretos(fila)


def test_dar_acceso_con_cuenta_que_aparecio_registra_approved_via_access(
    db_session, make_cohort, make_user, correo_ok,
):
    """D10 (revisión final M6): Centro de Cómputo da acceso y la cuenta ya
    existe (un CSV o un alta manual la creó entretanto): la solicitud pasa de
    `awaiting_access` a `approved` y sale la liga. Antes solo lo contaban filas
    `data.update` ocultas; ahora es UNA acción del módulo, sin el NIP tecleado."""
    se, cc = make_user(), make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860030",
                    status="awaiting_access", reviewed_by_id=se.id,
                    reviewed_at=datetime.now() - timedelta(hours=1))
    _cuenta(db_session, "99860030")

    ok = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)

    assert ok == (True, "")
    fila = _fila_unica(db_session, "enrollment.approved", req)
    assert fila.payload == {"path": "existing_account", "via": "access",
                            "cohort_id": req.cohort_id}
    assert fila.actor_id == cc.id
    assert fila.before == {"status": "awaiting_access"}
    assert fila.after == {"status": "approved"}
    assert fila.subject_label.startswith("99860030 · ")
    _sin_secretos(fila)


def test_dar_acceso_frenado_con_cuenta_no_deja_fila(db_session, make_cohort, make_user,
                                                     correo_ok):
    """La cuenta que apareció no tiene contraseña: `_issue_link_for_account`
    la frena ANTES de escribir; nada de «aprobado» fantasma."""
    se, cc = make_user(), make_user()
    req = _make_req(db_session, make_cohort(status="open"), control="99860031",
                    status="awaiting_access", reviewed_by_id=se.id,
                    reviewed_at=datetime.now() - timedelta(hours=1))
    _cuenta(db_session, "99860031", password=False)

    ok = _svc().grant_access(db_session, req.id, nip=NIP, actor_id=cc.id)

    assert ok[0] is False
    assert _acciones(db_session, "enrollment.approved", entity_id=req.id) == []


# ---------------------------------------------------------------------------
# Reenvíos
# ---------------------------------------------------------------------------
def _aprobada_con_liga(db_session, make_cohort, make_user, control):
    se = make_user()
    req = _make_req(db_session, make_cohort(status="open"), control=control)
    _cuenta(db_session, control)
    r = _svc().approve_detailed(db_session, req.id, nip="", program_id=None, actor_id=se.id)
    assert r.ok, r
    db_session.refresh(req)
    return req, se


def test_reenviar_liga_desde_bandeja_registra_by_admin_sin_la_liga(
    db_session, make_cohort, make_user, correo_ok,
):
    req, se = _aprobada_con_liga(db_session, make_cohort, make_user, "99860011")
    con_nueva = make_user()

    from itcj2.apps.titulatec.services.audit_context import audit_context
    with audit_context("user", actor_id=con_nueva.id):
        assert _svc().resend_link(db_session, req.id) == (True, "")

    fila = _fila_unica(db_session, "enrollment.link_resent", req)
    assert fila.payload["by"] == "admin" and fila.actor_id == con_nueva.id
    _sin_secretos(fila)


def test_reenviar_liga_publico_registra_by_public(
    db_session, make_cohort, make_user, correo_ok, monkeypatch,
):
    from itcj2.apps.titulatec.services import enrollment_request_service as mod

    req, _se = _aprobada_con_liga(db_session, make_cohort, make_user, "99860012")
    req.verify_sent_at = datetime.now() - timedelta(hours=2)
    db_session.flush()
    monkeypatch.setattr(mod, "_token_cache_get", lambda h: "claro-de-prueba")

    out = _svc().resend(db_session, "99860012", "auditoria@example.invalid")

    assert out == "sent"
    fila = _fila_unica(db_session, "enrollment.link_resent", req)
    assert fila.payload["by"] == "public" and fila.actor_kind == "system"
    assert "claro-de-prueba" not in _volcado(fila)
    _sin_secretos(fila)


def test_reenviar_liga_publico_noop_no_deja_fila(db_session, make_cohort, make_user):
    req = _make_req(db_session, make_cohort(status="open"), control="99860013")
    assert _svc().resend(db_session, "99860013", "auditoria@example.invalid") == "noop"
    assert _acciones(db_session, "enrollment.link_resent", entity_id=req.id) == []


def test_reenviar_aviso_de_acceso_registra_notice_resent(
    db_session, make_cohort, make_user, correo_ok,
):
    from itcj2.apps.titulatec.models import TitulationProcess

    cohort = make_cohort(status="open")
    user = _cuenta(db_session, "99860014")
    req = _make_req(db_session, cohort, control="99860014", status="converted",
                    nip_source="sii")
    proc = TitulationProcess(student_id=user.id, cohort_id=cohort.id, status="active",
                           folio="AUD-2026-500014")
    db_session.add(proc)
    db_session.flush()
    req.converted_process_id = proc.id
    db_session.flush()

    assert _svc().resend_access_notice(db_session, req.id) == (True, "")

    fila = _fila_unica(db_session, "enrollment.notice_resent", req)
    _sin_secretos(fila)


def test_reenviar_aviso_rechazado_por_regla_no_deja_fila(db_session, make_cohort):
    req = _make_req(db_session, make_cohort(status="open"), control="99860015")
    assert _svc().resend_access_notice(db_session, req.id)[0] is False
    assert _acciones(db_session, "enrollment.notice_resent", entity_id=req.id) == []


# ---------------------------------------------------------------------------
# Reconsulta al SII
# ---------------------------------------------------------------------------
def test_reconsulta_forzada_registra_la_peticion(
    db_session, monkeypatch, make_user, make_cohort,
):
    from itcj2.apps.titulatec.services import eligibility_service as elig
    from itcj2.apps.titulatec.services.sii.client import SiiConfig
    from itcj2.apps.titulatec.services.audit_context import audit_context
    from itcj2.celery_app import celery_app

    req = _make_req(db_session, make_cohort(status="open"), control="99860016")
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: None)
    se = make_user()

    with audit_context("user", actor_id=se.id):
        assert elig.enqueue_check(req.id, force=True, db=db_session) is True

    fila = _fila_unica(db_session, "enrollment.sii_recheck_requested", req)
    assert fila.actor_id == se.id and fila.entity_type == "enrollment_request"
    assert fila.subject_label.startswith("99860016 · ")
    _sin_secretos(fila)


def test_consulta_no_forzada_o_no_encolada_no_registra(
    db_session, monkeypatch, make_cohort,
):
    from itcj2.apps.titulatec.services import eligibility_service as elig
    from itcj2.apps.titulatec.services.sii.client import SiiConfig
    from itcj2.celery_app import celery_app

    req = _make_req(db_session, make_cohort(status="open"), control="99860017")
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "fake"))
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: None)

    assert elig.enqueue_check(req.id, db=db_session) is True          # sin force
    monkeypatch.setattr(SiiConfig, "backend", staticmethod(lambda: "disabled"))
    assert elig.enqueue_check(req.id, force=True, db=db_session) is False  # no encoló

    assert _acciones(db_session, "enrollment.sii_recheck_requested", entity_id=req.id) == []

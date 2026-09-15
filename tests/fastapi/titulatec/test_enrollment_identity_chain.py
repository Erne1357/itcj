"""Cadena de identidad de la inscripción pública (2026-09-15).

El formulario público deja que CUALQUIERA teclee un número de control ajeno —son
8 dígitos impresos en la credencial— y un correo propio. Desde que toda
solicitud pasa por la bandeja, la liga de activación de una cuenta existente
viaja al correo que tecleó el solicitante. RIESGO ACEPTADO POR EL USUARIO:
quien escriba un control ajeno con su correo y pase la revisión puede dejar
inscrita a esa persona.

CONTENCIÓN QUE FIJA ESTE ARCHIVO, para que ese riesgo no escale:
- nada sale por correo antes de que un oficial revise;
- sobre una cuenta existente jamás se escribe `password_hash`,
  `must_change_password` ni `core_student_profile` a partir de la solicitud,
  ni al aprobar ni al abrir la liga. `is_active` es la única excepción aprobada
  (2026-09-15): abrir la liga la reactiva, aprobar no;
- una cuenta sin contraseña no recibe liga;
- al abrirse la liga, el aviso con folio va al buzón INSTITUCIONAL de la cuenta
  (la alarma), nunca al correo que se tecleó;
- ya no existe una segunda liga ("confirma tu correo de contacto") que un extraño
  pueda canjear contra el perfil de otra persona.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import pytest

ENROLL_URL = "/titulatec/inscripcion"
NIP = "4821"
ATACANTE = "atacante@evil.invalid"


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


def _solo_esta_convocatoria(db_session, cohort):
    """Deja `cohort` como la ÚNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _victima(db_session, control, *, password=True, is_active=False):
    """Cuenta real de otra persona: con perfil propio y desactivada a propósito.
    Aprobar no la reactiva; abrir la liga sí (única excepción aprobada, 2026-09-15)."""
    from itcj2.core.models.user import User
    from itcj2.core.services.student_profile_service import StudentProfileService
    from itcj2.core.utils.security import hash_nip

    user = User(username=control, control_number=control,
                first_name="VICTIMA", last_name="REAL",
                password_hash=hash_nip("2468") if password else None,
                is_active=is_active, must_change_password=False)
    db_session.add(user)
    db_session.flush()
    StudentProfileService.set_fields(db_session, user.id,
                                     contact_email="suyo@example.invalid",
                                     phone="6560000000")
    db_session.flush()
    return user


def _foto(db_session, user):
    """Lo que la solicitud NO puede tocar de la cuenta ni del perfil."""
    from itcj2.core.models.student_profile import StudentProfile

    db_session.refresh(user)
    perfil = db_session.get(StudentProfile, user.id)
    if perfil is not None:
        db_session.refresh(perfil)
    return {
        "password_hash": user.password_hash,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "contact_email": getattr(perfil, "contact_email", None),
        "phone": getattr(perfil, "phone", None),
        "contact_email_verified_at": getattr(perfil, "contact_email_verified_at", None),
    }


def _form(**kw):
    base = {
        "control_number": "99884001", "first_name": "ALUMNA", "last_name": "INVENTADA",
        "middle_name": "", "program_id": "__other__", "program_text": "Ingenieria Ficticia",
        "phone": "6561234567", "contact_email": ATACANTE, "contact_email_confirm": ATACANTE,
        "has_efirma": "0", "website": "",
    }
    base.update(kw)
    return base


def _solicitud_del_atacante(db_session, cohort, control):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        {"control_number": control, "first_name": "VICTIMA", "last_name": "REAL",
         "middle_name": None, "program_id": None, "program_text": "Ingenieria",
         "phone": "6569999999", "contact_email": ATACANTE, "has_efirma": True},
        client_ip="203.0.113.90")
    assert outcome == "created"
    return req


# ===========================================================================
# Nada sale antes de la revisión
# ===========================================================================
def test_el_formulario_con_un_control_ajeno_no_manda_nada_a_nadie(
    client, db_session, make_cohort, correo_falso,
):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    _victima(db_session, "99884010")
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL, data=_form(control_number="99884010"),
                       headers={"X-Real-IP": "203.0.113.91"}, follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    req = db_session.query(EnrollmentRequest).filter_by(control_number="99884010").one()
    assert req.status == "pending_review"
    assert req.verify_token_hash is None and req.contact_token_hash is None
    assert correo_falso == [], "ni la víctima ni el extraño reciben nada sin revisión"


# ===========================================================================
# Aprobar y abrir la liga no tocan la cuenta ni el perfil
# ===========================================================================
def test_la_cuenta_ajena_solo_recibe_proceso_y_rol_y_el_aviso_va_a_su_institucional(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    oficial = make_user()
    cohort = make_cohort(status="open")
    victima = _victima(db_session, "99884020")
    antes = _foto(db_session, victima)
    req = _solicitud_del_atacante(db_session, cohort, "99884020")

    ok, _ = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=oficial.id)

    assert ok is True and req.status == "approved"
    assert _foto(db_session, victima) == antes, "aprobar escribió sobre la cuenta ajena"
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == [ATACANTE], (
        "la liga va al correo que se tecleó: es el riesgo aceptado, y es lo ÚNICO "
        "que ese correo recibe")
    assert NIP not in html
    token = html.split("/inscripcion/verificar?t=", 1)[1].split('"', 1)[0]
    correo_falso.clear()

    _, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "converted"
    despues = _foto(db_session, victima)
    assert despues["is_active"] is True, (
        "abrir la liga reactiva la cuenta: es la única excepción aprobada")
    assert dict(despues, is_active=antes["is_active"]) == antes, (
        "abrir la liga escribió sobre la cuenta ajena algo más que `is_active`")
    assert (db_session.query(TitulationProcess)
            .filter_by(student_id=victima.id, cohort_id=cohort.id).count()) == 1
    assert [d for _a, d, _h in correo_falso] == [[student_email(victima)]], (
        "el aviso con folio es la alarma de la dueña de la cuenta: va a su "
        "institucional, nunca al correo del solicitante")


def test_una_cuenta_sin_contrasena_no_recibe_liga(
    db_session, make_cohort, make_user, correo_falso,
):
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    oficial = make_user()
    cohort = make_cohort(status="open")
    victima = _victima(db_session, "99884021", password=False)
    antes = _foto(db_session, victima)
    req = _solicitud_del_atacante(db_session, cohort, "99884021")

    ok, detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=oficial.id)

    assert ok is False
    assert detalle == ("Esa cuenta no tiene contraseña; dala de alta desde la "
                       "convocatoria y rechaza esta solicitud.")
    assert req.status == "pending_review"
    assert req.verify_token_hash is None
    assert _foto(db_session, victima) == antes
    assert correo_falso == []


def test_ninguna_etapa_emite_una_liga_de_contacto(
    db_session, make_cohort, make_user, seed_phase_defs, titulatec_app, correo_falso,
):
    """La segunda liga era canjeable contra `core_student_profile` con la sola
    prueba del buzón que un extraño tecleó (B1 de la revisión final)."""
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    oficial = make_user()
    cohort = make_cohort(status="open")
    _victima(db_session, "99884022")
    req = _solicitud_del_atacante(db_session, cohort, "99884022")
    assert req.contact_token_hash is None

    EnrollmentRequestService.approve(db_session, req.id, nip=NIP, program_id=None,
                                     actor_id=oficial.id)
    assert req.contact_token_hash is None
    token = correo_falso[0][2].split("/inscripcion/verificar?t=", 1)[1].split('"', 1)[0]

    EnrollmentRequestService.verify(db_session, token)
    assert req.contact_token_hash is None and req.contact_expires_at is None
    assert not [a for a, _d, _h in correo_falso if "contacto" in a.lower()]


# ===========================================================================
# Ligas de contacto que ya se mandaron: la guarda de canje sigue viva
# ===========================================================================
def test_confirmar_el_contacto_de_una_solicitud_sin_verificar_no_toca_el_perfil(
    client, db_session, make_cohort, make_student,
):
    """Filas anteriores a este cambio pueden traer un token de contacto vivo.
    Canjearlo sobre una solicitud cuya liga nunca se abrió no puede escribir en
    `core_student_profile` —tabla del core, compartida con las demás apps— ni
    sellarla como verificada."""
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.apps.titulatec.models import EnrollmentRequest

    victima = make_student(control_number="99884012")
    cohort = make_cohort(status="open")
    raw = secrets.token_urlsafe(32)
    req = EnrollmentRequest(
        cohort_id=cohort.id, control_number="99884012",
        first_name="ALUMNA", last_name="INVENTADA", phone="6561234567",
        contact_email=ATACANTE, has_efirma=False, kind="known", status="unverified",
        contact_token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        contact_expires_at=datetime.now() + timedelta(days=7),
    )
    db_session.add(req)
    db_session.flush()
    assert req.verified_at is None
    client.cookies.clear()

    resp = client.get(f"{ENROLL_URL}/correo?t={raw}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos confirmar" in resp.text.lower()
    perfil = db_session.get(StudentProfile, victima.id)
    assert perfil is None or perfil.contact_email != ATACANTE
    assert perfil is None or perfil.contact_email_verified_at is None

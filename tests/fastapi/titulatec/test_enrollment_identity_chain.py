"""Cadena de identidad de la inscripcion publica (B1 y B2 de la revision final).

El formulario publico deja que CUALQUIERA teclee un numero de control ajeno --son
8 digitos impresos en la credencial-- y un correo personal propio. De ahi salen
dos ligas con propositos distintos, y confundirlas es la vulnerabilidad:

- La liga de VERIFICACION va al buzon INSTITUCIONAL (`verify_recipient`, D17).
  Abrirla prueba posesion del NUMERO DE CONTROL.
- La liga de CONTACTO va al correo personal que se tecleo. Abrirla prueba
  posesion de ESE BUZON, y nada mas.

INVARIANTE QUE FIJA ESTE ARCHIVO: nada que dependa del numero de control --el
perfil de `core_student_profile`, la credencial de `core_users`, el NIP por
correo-- puede moverse con la sola prueba del segundo buzon. La prueba del
institucional es la unica que vale para eso, y para un `known` esa prueba es
`req.verified_at`.

Corolario operativo: la liga de contacto NI SIQUIERA SE EMITE hasta que la
institucional se abre. Un token que no existe no se puede canjear, asi que el
extrano nunca recibe correo alguno y la redencion tiene una segunda guarda.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import pytest

ENROLL_URL = "/titulatec/inscripcion"
ADMIN_URL = "/titulatec/admin/solicitudes"
NIP = "4821"

LIST_PERMS = (
    "titulatec.enrollment_request.page.list",
    "titulatec.enrollment_request.api.approve",
    "titulatec.enrollment_request.api.reject",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
)


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envios sin tocar Graph: `(asunto, destinatarios, html)`."""
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
    """Deja `cohort` como la UNICA abierta (ver test_enrollment_public.py)."""
    from itcj2.apps.titulatec.models import Cohort
    (db_session.query(Cohort)
     .filter(Cohort.id != cohort.id)
     .update({Cohort.status: "closed"}, synchronize_session=False))
    db_session.flush()


def _form(**kw):
    base = {
        "control_number": "99884001",
        "first_name": "ALUMNA",
        "last_name": "INVENTADA",
        "middle_name": "",
        "program_id": "__other__",
        "program_text": "Ingenieria Ficticia",
        "phone": "6561234567",
        "contact_email": "atacante@evil.invalid",
        "has_efirma": "0",
        "website": "",
    }
    base.update(kw)
    return base


def _make_req(db_session, cohort, *, control, kind="known", status="unverified",
              email="atacante@evil.invalid", **kw):
    """Solicitud a mano + su token de verificacion en claro."""
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import VERIFY_TTL_HOURS

    token = secrets.token_urlsafe(32)
    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=control,
        first_name="ALUMNA", last_name="INVENTADA", middle_name=None,
        program_id=kw.pop("program_id", None), program_text="Ingenieria de 2005",
        phone="6561234567", contact_email=email,
        has_efirma=False, kind=kind, status=status,
        verify_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        verify_expires_at=datetime.now() + timedelta(hours=VERIFY_TTL_HOURS),
        verify_sent_at=datetime.now() - timedelta(hours=1),
        verify_send_count=1, verify_sent_to="alumna@cdjuarez.tecnm.mx",
    )
    for k, v in kw.items():
        setattr(row, k, v)
    db_session.add(row)
    db_session.flush()
    return row, token


def _con_token_de_contacto(db_session, req):
    """Le pone a `req` un token de contacto VIVO y devuelve el claro.

    Reproduce a mano exactamente lo que `create()` emitia para todo `known`
    antes de este arreglo: es el estado desde el que se montaba el ataque.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import CONTACT_TTL_HOURS

    raw = secrets.token_urlsafe(32)
    req.contact_token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    req.contact_expires_at = datetime.now() + timedelta(hours=CONTACT_TTL_HOURS)
    db_session.flush()
    return raw


# ===========================================================================
# B1 - Reescritura anonima del correo de contacto verificado de un tercero
# ===========================================================================
def test_el_token_de_contacto_no_se_emite_antes_de_abrir_la_liga_institucional(
    db_session, make_cohort, make_student, correo_falso,
):
    """B1, emision. `create()` de un `known` manda UNA sola liga: la institucional.

    Antes emitia tambien la de contacto y se la mandaba a `req.contact_email`
    --el valor crudo del cable--, asi que el extrano recibia un token canjeable
    contra el perfil de otra persona sin que nadie probara nada.
    """
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    victima = make_student(control_number="99884010")
    institucional = student_email(victima)
    cohort = make_cohort(status="open")

    req, outcome = EnrollmentRequestService.create(
        db_session, cohort,
        {"control_number": "99884010", "first_name": "ALUMNA",
         "last_name": "INVENTADA", "middle_name": "", "program_id": None,
         "program_text": "Ingenieria Ficticia", "phone": "6561234567",
         "contact_email": "atacante@evil.invalid", "has_efirma": False},
        client_ip="203.0.113.90")

    assert outcome == "created" and req.kind == "known"
    assert req.contact_token_hash is None, (
        "la liga de contacto NO puede existir antes de que se abra la "
        "institucional: es la unica prueba del numero de control")
    assert req.contact_expires_at is None

    destinatarios = [d for _a, dests, _h in correo_falso for d in dests]
    assert destinatarios == [institucional], (
        "el extrano no debe recibir NINGUN correo de esta solicitud")


def test_la_liga_de_contacto_nunca_sale_al_correo_que_tecleo_un_extrano(
    client, db_session, make_cohort, make_student, correo_falso,
):
    """B1 de punta a punta, por HTTP y sin sesion: el ataque completo."""
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.models import EnrollmentRequest

    victima = make_student(control_number="99884011")
    institucional = student_email(victima)
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    client.cookies.clear()

    resp = client.post(ENROLL_URL,
                       data=_form(control_number="99884011",
                                  contact_email="atacante@evil.invalid"),
                       headers={"X-Real-IP": "203.0.113.91"},
                       follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    req = (db_session.query(EnrollmentRequest)
           .filter_by(control_number="99884011").first())
    assert req is not None
    assert req.contact_token_hash is None
    destinatarios = [d for _a, dests, _h in correo_falso for d in dests]
    assert "atacante@evil.invalid" not in destinatarios
    assert destinatarios == [institucional]


def test_confirmar_el_contacto_de_una_solicitud_sin_verificar_no_toca_el_perfil(
    client, db_session, make_cohort, make_student,
):
    """B1, redencion. Segunda guarda, independiente de la emision.

    Aunque un token de contacto exista (fila vieja emitida antes de este
    arreglo, o cualquier camino futuro que lo emita de mas), canjearlo sobre
    una solicitud cuya liga institucional NUNCA se abrio no puede escribir en
    `core_student_profile` --una tabla del core, compartida con las demas
    apps-- ni sellarla como verificada.
    """
    from itcj2.core.models.student_profile import StudentProfile

    victima = make_student(control_number="99884012")
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, _tok = _make_req(db_session, cohort, control="99884012",
                          kind="known", status="unverified",
                          email="atacante@evil.invalid")
    assert req.verified_at is None
    raw = _con_token_de_contacto(db_session, req)
    client.cookies.clear()

    resp = client.get(f"{ENROLL_URL}/correo?t={raw}", follow_redirects=False)

    assert resp.status_code == 200, resp.text[:400]
    assert "no pudimos confirmar" in resp.text.lower()
    perfil = db_session.get(StudentProfile, victima.id)
    assert perfil is None or perfil.contact_email != "atacante@evil.invalid", (
        "dos peticiones anonimas reescribieron el correo de contacto de un tercero")
    assert perfil is None or perfil.contact_email_verified_at is None


def test_al_abrir_la_liga_institucional_sale_la_liga_de_contacto_y_entonces_si_confirma(
    db_session, make_cohort, make_student, seed_phase_defs, titulatec_app,
    correo_falso,
):
    """El camino bueno no se rompe: la liga de contacto se emite en `verify()`.

    Es el unico punto del flujo que SOLO puede alcanzar quien tiene el buzon
    institucional, asi que es donde pertenece la emision.
    """
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    alumna = make_student(control_number="99884013")
    alumna.password_hash = "hash-que-ya-existe"
    db_session.flush()
    cohort = make_cohort(status="open")
    _solo_esta_convocatoria(db_session, cohort)
    req, token = _make_req(db_session, cohort, control="99884013",
                           kind="known", status="unverified",
                           email="personal@example.invalid")

    req2, outcome = EnrollmentRequestService.verify(db_session, token)

    assert outcome == "converted", outcome
    assert req2.contact_token_hash is not None, (
        "abrir la institucional es lo que emite la liga de contacto")
    contactos = [dests for asunto, dests, _h in correo_falso
                 if "correo de contacto" in asunto]
    assert contactos == [["personal@example.invalid"]]

    # Y el canje ahora si escribe el perfil.
    raw = None
    for _asunto, _dests, html in correo_falso:
        if "/inscripcion/correo?t=" in html:
            raw = html.split("/inscripcion/correo?t=")[1].split('"')[0]
    assert raw, "la liga de contacto no traia token"
    assert EnrollmentRequestService.confirm_contact(db_session, raw) is True
    perfil = db_session.get(StudentProfile, alumna.id)
    assert perfil.contact_email == "personal@example.invalid"
    assert perfil.contact_email_verified_at is not None


# ===========================================================================
# B2 - El registro envenenado es a donde se manda el NIP
# ===========================================================================
def test_aprobar_una_solicitud_sin_verificar_se_rechaza(
    db_session, make_cohort, make_head, seed_phase_defs, titulatec_app,
):
    """`unverified` = nadie abrio NINGUNA liga: no hay ni un dato probado.

    Vale para los dos `kind`: del conocido no esta probado el numero de control,
    y del desconocido no esta probado ni el buzon que se tecleo.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _tok = _make_req(db_session, cohort, control="99884020",
                          kind="known", status="unverified")

    ok, detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=jefa.id)

    assert ok is False
    assert "liga" in detalle.lower(), detalle
    db_session.refresh(req)
    assert req.status == "unverified"


def test_aprobar_un_conocido_sin_liga_abierta_no_fija_credencial_ni_reactiva_ni_manda_nip(
    db_session, make_cohort, make_head, seed_phase_defs, titulatec_app, monkeypatch,
):
    """B2, el nucleo. Cuenta preexistente con `password_hash` NULL.

    Esa poblacion es real: `import_service.repair_missing_credentials` existe
    precisamente por ella. Si `approve()` le fija el NIP y se lo manda al correo
    personal de la solicitud, el extrano acaba con usuario = numero de control
    de la victima y contrasena = NIP en el login compartido del instituto.
    """
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99884021"
    victima = User(username=control, control_number=control,
                   first_name="VICTIMA", last_name="REAL",
                   password_hash=None, is_active=False,
                   must_change_password=False)
    db_session.add(victima)
    db_session.flush()
    # Llego a la bandeja por el camino documentado: 3 envios al institucional
    # sin respuesta (`resend()`), asi que `verified_at` sigue NULL.
    req, _tok = _make_req(db_session, cohort, control=control, kind="known",
                          status="pending_review", email="atacante@evil.invalid",
                          verify_send_count=3)

    enviados = []
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: enviados.append("nip")))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_done",
                        staticmethod(lambda *a, **k: enviados.append("folio")))

    ok, _detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=jefa.id)

    db_session.refresh(victima)
    assert victima.password_hash is None, (
        "se le fijo el NIP a una cuenta ajena desde una solicitud sin verificar")
    assert victima.is_active is False, "se reactivo una cuenta desactivada"
    assert victima.must_change_password is False
    assert "nip" not in enviados, (
        "el NIP viajo al correo personal que escribio un desconocido")
    assert ok is True and enviados == ["folio"], (
        "el flujo de buzon institucional muerto sigue vivo: crea el proceso y "
        "avisa el folio al institucional, sin credencial")


def test_aprobar_un_conocido_sin_liga_abierta_no_pisa_el_correo_del_perfil(
    db_session, make_cohort, make_head, seed_phase_defs, titulatec_app, monkeypatch,
):
    """Ni el correo ni el telefono del perfil salen de una solicitud sin probar."""
    from itcj2.core.models.student_profile import StudentProfile
    from itcj2.core.models.user import User
    from itcj2.core.services.student_profile_service import StudentProfileService
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99884022"
    victima = User(username=control, control_number=control,
                   first_name="VICTIMA", last_name="REAL",
                   password_hash="hash-que-ya-existe", is_active=True)
    db_session.add(victima)
    db_session.flush()
    StudentProfileService.set_fields(db_session, victima.id,
                                     contact_email="suyo@example.invalid",
                                     phone="6560000000")
    req, _tok = _make_req(db_session, cohort, control=control, kind="known",
                          status="pending_review", email="atacante@evil.invalid")

    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_done",
                        staticmethod(lambda *a, **k: True))

    ok, _detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=jefa.id)

    assert ok is True
    perfil = db_session.get(StudentProfile, victima.id)
    assert perfil.contact_email == "suyo@example.invalid"
    assert perfil.phone == "6560000000"


def test_aprobar_un_conocido_con_liga_abierta_si_fija_la_credencial_y_manda_el_nip(
    db_session, make_cohort, make_head, seed_phase_defs, titulatec_app, monkeypatch,
):
    """Control positivo: con `verified_at` la aprobacion hace su trabajo entero."""
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99884023"
    alumna = User(username=control, control_number=control,
                  first_name="ALUMNA", last_name="REAL",
                  password_hash=None, is_active=False)
    db_session.add(alumna)
    db_session.flush()
    req, _tok = _make_req(db_session, cohort, control=control, kind="known",
                          status="pending_review", email="personal@example.invalid",
                          verified_at=datetime.now())

    enviados = []
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: enviados.append("nip")))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_done",
                        staticmethod(lambda *a, **k: enviados.append("folio")))

    ok, _detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=jefa.id)

    assert ok is True
    db_session.refresh(alumna)
    assert verify_nip(NIP, alumna.password_hash)
    assert alumna.is_active is True
    assert enviados == ["nip"]


def test_aprobar_un_desconocido_sin_cuenta_sigue_funcionando_igual(
    db_session, make_cohort, make_head, seed_phase_defs, titulatec_app, monkeypatch,
):
    """El desconocido NO se toca: es el caso que la bandeja existe para resolver.

    No hay fila en `core_users` que secuestrar, el correo personal es la unica
    direccion que existe en el mundo para esa persona (D16: un egresado de 2005
    no tiene institucional vivo) y la liga de verificacion ya fue a ese mismo
    buzon. La autenticacion aqui es el juicio del oficial, fuera de banda.
    """
    from itcj2.core.models.user import User
    from itcj2.core.utils.security import verify_nip
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    seed_phase_defs()
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99884024"
    req, _tok = _make_req(db_session, cohort, control=control, kind="unknown",
                          status="pending_review", email="egresado@example.invalid",
                          verified_at=datetime.now())

    enviados = []
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_approved",
                        staticmethod(lambda *a, **k: enviados.append("nip")))
    monkeypatch.setattr(TitulaTecEmailHelper, "send_enrollment_done",
                        staticmethod(lambda *a, **k: enviados.append("folio")))

    ok, _detalle = EnrollmentRequestService.approve(
        db_session, req.id, nip=NIP, program_id=None, actor_id=jefa.id)

    assert ok is True
    nueva = db_session.query(User).filter_by(control_number=control).first()
    assert nueva is not None and verify_nip(NIP, nueva.password_hash)
    assert enviados == ["nip"]


# ===========================================================================
# B2 - La bandeja no puede ofrecer lo que el servicio rechaza
# ===========================================================================
def test_la_bandeja_no_ofrece_aprobar_una_solicitud_sin_verificar(
    client_as, db_session, make_cohort, make_head, titulatec_app,
):
    """El boton y el servicio tienen que decir lo mismo.

    Rechazar y reenviar SI siguen ofreciendose: son justo lo que el oficial
    puede hacer con una solicitud que nadie ha confirmado.
    """
    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    req, _tok = _make_req(db_session, cohort, control="99884030",
                          kind="known", status="unverified")

    resp = client_as(jefa).get(f"{ADMIN_URL}/body")

    assert resp.status_code == 200
    html = resp.text
    assert f"/solicitudes/{req.id}/aprobar" not in html, (
        "la bandeja ofrece aprobar una solicitud que approve() rechaza")
    assert f"/solicitudes/{req.id}/rechazar" in html
    assert f"/solicitudes/{req.id}/reenviar" in html


def test_la_bandeja_avisa_cuando_el_nip_capturado_no_se_va_a_aplicar(
    client_as, db_session, make_cohort, make_head, titulatec_app,
):
    """El oficial teclea un NIP: tiene que saber cuando NO sera la contrasena.

    Es la mitad de B2 que no es codigo: la bandeja le daba una senal
    equivocada, no ausente.
    """
    from itcj2.core.models.user import User

    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    control = "99884031"
    db_session.add(User(username=control, control_number=control,
                        first_name="VICTIMA", last_name="REAL",
                        password_hash=None, is_active=False))
    db_session.flush()
    req, _tok = _make_req(db_session, cohort, control=control, kind="known",
                          status="pending_review", email="atacante@evil.invalid")

    resp = client_as(jefa).get(f"{ADMIN_URL}/body")

    assert resp.status_code == 200
    html = resp.text
    assert f"/solicitudes/{req.id}/aprobar" in html, "sigue siendo aprobable"
    assert "el NIP no se aplica" in html, (
        "nada le dice al oficial que el NIP que teclee sera ignorado")


def test_la_bandeja_no_pinta_verificado_un_correo_distinto_al_del_perfil(
    client_as, db_session, make_cohort, make_head, make_student, titulatec_app,
):
    """La palomita verde tiene que hablar del correo que esta a su lado.

    `contact_verified` salia de "el perfil tiene sello", sin comparar la
    direccion: un correo nuevo, jamas verificado, se pintaba en verde porque la
    persona habia verificado OTRO en una convocatoria anterior.
    """
    from itcj2.core.services.student_profile_service import StudentProfileService

    jefa = make_head(perm_codes=LIST_PERMS)
    cohort = make_cohort(status="open")
    alumna = make_student(control_number="99884032")
    StudentProfileService.set_fields(db_session, alumna.id,
                                     contact_email="el.viejo@example.invalid")
    StudentProfileService.mark_contact_verified(db_session, alumna.id)
    req, _tok = _make_req(db_session, cohort, control="99884032",
                          kind="known", status="pending_review",
                          email="el.nuevo@example.invalid")

    resp = client_as(jefa).get(f"{ADMIN_URL}/body")

    assert resp.status_code == 200
    fila = resp.text.split("el.nuevo@example.invalid", 1)[1][:600]
    assert "correo personal sin verificar" in fila, (
        "se pinta verificado un correo que nadie confirmo nunca")

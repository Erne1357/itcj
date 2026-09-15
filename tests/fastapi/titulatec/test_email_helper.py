"""El helper de correo de TitulaTec: destinatario de cada correo y fallo tolerante.

Lo que se prueba de verdad
--------------------------
1. A qué buzón va cada correo. El módulo mezcla dos destinos a propósito, así
   que cada uno tiene que estar fijado por un test o una futura "unificación"
   lo cambia sin poner nada en rojo:
   - al correo PERSONAL de la solicitud (`req.contact_email`): la liga de
     activación, el usuario + NIP de una cuenta nueva y el rechazo;
   - al INSTITUCIONAL de la cuenta (`student_email(user)`): "ya tienes un
     proceso" y el aviso con folio al activarse la inscripción, que es la
     alarma de la dueña de la cuenta.
   El destinatario lo decide el helper, no el llamador: ningún método recibe
   un `to` que alguien pueda llenar con el correo equivocado.
2. Que sin token de Graph el helper devuelve False SIN lanzar. Si una excepción
   escapara, tumbaría la acción entera por un problema de correo.
3. E9 — la liga al log en dev, nunca en producción.

Parcheo
-------
`_send` y `_acquire_token` importan de `itcj2.core.utils.msgraph_mail` DENTRO de
la función, así que el patch va en el módulo FUENTE, no en el consumidor.
"""
import inspect
import logging

import pytest

LIGA = "https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=abc"


@pytest.fixture()
def correo_falso(monkeypatch):
    """Captura los envíos. Devuelve la lista de (asunto, destinatarios, html)."""
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
def sin_token(monkeypatch):
    """Graph sin OAuth completado — el estado REAL de titulatec hoy."""
    def _explota(*a, **kw):
        raise AssertionError("Sin token no se puede intentar enviar.")

    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent",
                        lambda app_key: None)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", _explota)


@pytest.fixture()
def solicitud(db_session, make_cohort):
    """Fábrica de `EnrollmentRequest` local: datos inventados, sin PII."""
    from itcj2.apps.titulatec.models import EnrollmentRequest

    def _make(*, control_number, kind, cohort=None,
              contact_email="personal@example.invalid", status="pending_review"):
        cohort = cohort if cohort is not None else make_cohort()
        req = EnrollmentRequest(
            cohort_id=cohort.id, control_number=control_number,
            first_name="JUAN", last_name="PEREZ", middle_name="LOPEZ",
            phone="6560000000", contact_email=contact_email,
            has_efirma=False, kind=kind, status=status,
        )
        db_session.add(req)
        db_session.flush()
        return req

    return _make


# ---------------------------------------------------------------------------
# Correo PERSONAL de la solicitud
# ---------------------------------------------------------------------------
def test_la_liga_de_activacion_va_al_correo_personal_de_la_solicitud(
    db_session, make_student, solicitud, correo_falso,
):
    """Riesgo aceptado: la liga de una cuenta existente viaja al correo que se
    tecleó. La contención vive en el servicio (ver
    `test_enrollment_identity_chain.py`); aquí se fija que el helper no la mande
    a otro lado, ni siquiera al institucional."""
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="99123457")
    req = solicitud(control_number="99123457", kind="known", status="approved",
                    contact_email="personal.real@example.invalid")

    ok = TitulaTecEmailHelper.send_verify_enrollment(db_session, req, link=LIGA)

    assert ok is True
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == ["personal.real@example.invalid"]
    assert destinatarios != [student_email(alumno)]
    assert "verificar?t=abc" in html


def test_ningun_correo_de_la_solicitud_acepta_un_destinatario_del_llamador():
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    for nombre in [n for n in dir(TitulaTecEmailHelper) if n.startswith("send_")]:
        params = inspect.signature(getattr(TitulaTecEmailHelper, nombre)).parameters
        assert "to" not in params, f"{nombre} deja que el llamador elija el destinatario"


def test_el_helper_ya_no_resuelve_destinatarios_ni_manda_ligas_de_contacto():
    """`verify_recipient` resolvía el institucional para la liga de un alumno
    conocido: esa regla ya no aplica. La liga de contacto ya no se emite."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    assert not hasattr(TitulaTecEmailHelper, "verify_recipient")
    assert not hasattr(TitulaTecEmailHelper, "send_confirm_contact")


def test_el_correo_de_alta_lleva_usuario_y_nip(db_session, make_student, solicitud,
                                               correo_falso):
    """D16. Va al PERSONAL: el egresado de 2005 no tiene institucional vivo."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="90000002")
    req = solicitud(control_number="90000002", kind="unknown",
                    contact_email="egresado@example.invalid", status="converted")

    ok = TitulaTecEmailHelper.send_enrollment_approved(db_session, req, alumno,
                                                       nip="4821")

    assert ok is True
    _asunto, destinatarios, html = correo_falso[0]
    assert destinatarios == ["egresado@example.invalid"]
    assert "90000002" in html
    assert "4821" in html


def test_el_rechazo_va_al_correo_personal_con_el_motivo(db_session, solicitud, correo_falso):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="90000008", kind="unknown", status="rejected",
                    contact_email="rechazada@example.invalid")
    req.review_note = "No aparece en el padrón."
    db_session.flush()

    assert TitulaTecEmailHelper.send_enrollment_rejected(db_session, req) is True
    (_asunto, destinatarios, html), = correo_falso
    assert destinatarios == ["rechazada@example.invalid"]
    assert "No aparece en el padrón." in html


def test_el_nombre_del_solicitante_va_escapado(db_session, solicitud, correo_falso):
    """Un anónimo escribe `first_name`. En un correo HTML eso es inyección."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="90000003", kind="unknown", status="approved")
    req.first_name = '<script>alert(1)</script>'
    db_session.flush()

    TitulaTecEmailHelper.send_verify_enrollment(db_session, req, link=LIGA)

    _asunto, _dest, html = correo_falso[0]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Sin token de Graph: False, sin excepción, y E9 en dev
# ---------------------------------------------------------------------------
def test_sin_token_devuelve_false_y_no_lanza(db_session, solicitud, sin_token,
                                             monkeypatch):
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_is_production", lambda: True)

    req = solicitud(control_number="90000004", kind="unknown", status="approved")

    assert email_helper.TitulaTecEmailHelper.send_verify_enrollment(
        db_session, req, link=LIGA) is False


def test_en_dev_sin_token_la_liga_queda_en_el_log(db_session, solicitud, sin_token,
                                                  monkeypatch, caplog):
    """E9. Sin esto el flujo es imposible de probar a mano en local."""
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_is_production", lambda: False)

    req = solicitud(control_number="90000005", kind="unknown", status="approved")
    liga = "https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=zzz"

    with caplog.at_level(logging.WARNING,
                         logger="itcj2.apps.titulatec.services.email_helper"):
        email_helper.TitulaTecEmailHelper.send_verify_enrollment(db_session, req, link=liga)

    assert "[TT-VERIFY-LINK]" in caplog.text
    assert liga in caplog.text


def test_en_produccion_la_liga_no_se_escribe_jamas(db_session, solicitud, sin_token,
                                                   monkeypatch, caplog):
    """Un token de un solo uso en el log es una credencial en texto claro."""
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_is_production", lambda: True)

    req = solicitud(control_number="90000006", kind="unknown", status="approved")
    liga = "https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=secreto"

    with caplog.at_level(logging.DEBUG,
                         logger="itcj2.apps.titulatec.services.email_helper"):
        email_helper.TitulaTecEmailHelper.send_verify_enrollment(db_session, req, link=liga)

    assert "secreto" not in caplog.text
    assert "[TT-VERIFY-LINK]" not in caplog.text


def test_una_plantilla_rota_no_tumba_nada(db_session, solicitud, correo_falso,
                                          monkeypatch):
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_render", lambda name, ctx: None)

    req = solicitud(control_number="90000007", kind="unknown")

    assert email_helper.TitulaTecEmailHelper.send_enrollment_rejected(db_session, req) is False
    assert correo_falso == []


# ---------------------------------------------------------------------------
# Correo INSTITUCIONAL de la cuenta
# ---------------------------------------------------------------------------
def test_already_enrolled_lleva_el_folio_al_institucional(
        db_session, make_student, make_process, correo_falso):
    """Este correo confirma una inscripción que ya existe: mandarlo a una
    dirección que declaró un desconocido sería contarle a un extraño que esa
    persona se está titulando (E8)."""
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="99123458")
    proceso = make_process(student=alumno)

    ok = TitulaTecEmailHelper.send_already_enrolled(db_session, alumno, proceso)

    assert ok is True
    _asunto, dest, html = correo_falso[0]
    assert proceso.folio in html
    assert "proceso de titulación" in html.lower()
    assert dest == [student_email(alumno)], (
        "el folio de un proceso vivo solo puede ir al buzón institucional")


def test_enrollment_done_lleva_el_folio_al_institucional(
        db_session, make_student, make_process, solicitud, correo_falso):
    """Al abrirse la liga de activación: el folio, AL INSTITUCIONAL.

    Es la alarma de la dueña de la cuenta: la liga viajó al correo que tecleó el
    solicitante, así que el aviso NO puede salir de `req.contact_email`. La
    solicitud trae a propósito un `contact_email` distinto del institucional
    para que el `assert` tenga algo que distinguir.
    """
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="99123459")
    proceso = make_process(student=alumno)
    req = solicitud(control_number="99123459", kind="known", status="converted",
                    contact_email="otro.personal@example.invalid")

    ok = TitulaTecEmailHelper.send_enrollment_done(db_session, req, proceso)

    assert ok is True
    _asunto, dest, html = correo_falso[0]
    assert proceso.folio in html
    assert "inscri" in html.lower()
    assert dest == [student_email(alumno)], (
        "el folio y la invitación a entrar solo pueden ir al buzón institucional")
    assert req.contact_email not in dest

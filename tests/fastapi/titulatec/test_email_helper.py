"""El helper de correo de TitulaTec: destinatario correcto y fallo tolerante.

Lo que se prueba de verdad
--------------------------
1. D17 — el token de un alumno CONOCIDO sale a su correo institucional, que sale
   de la BD, no de la petición. El control son 8 dígitos públicos: si el token
   viajara al buzón tecleado, cualquiera inscribiría a un tercero y —por D5— lo
   dejaría bloqueado para inscribirse de verdad.
2. Que sin token de Graph el helper devuelve False SIN lanzar. El correo de
   titulatec no está dado de alta (`instance/apps/titulatec/email/` vacío): si
   una excepción escapara, tumbaría la inscripción entera por un problema de
   correo, y la solicitud es justo lo que no se puede perder.
3. E9 — la liga al log en dev, nunca en producción.

Parcheo
-------
`_send` y `_acquire_token` importan de `itcj2.core.utils.msgraph_mail` DENTRO de
la función, así que el patch va en el módulo FUENTE, no en el consumidor.
"""
import logging

import pytest


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
              contact_email="personal@example.invalid", status="unverified"):
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
# D17: a qué buzón va el token
# ---------------------------------------------------------------------------
def test_el_conocido_recibe_el_token_en_su_institucional(db_session, make_student,
                                                         solicitud):
    from itcj2.core.utils.email_tools import student_email
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="99123456")
    req = solicitud(control_number="99123456", kind="known",
                    contact_email="cualquiera@example.invalid")

    destino = TitulaTecEmailHelper.verify_recipient(db_session, req)

    assert destino == student_email(alumno), (
        "El token de un CONOCIDO sale de la BD (institucional), nunca del correo "
        "que se tecleó en el formulario público."
    )
    assert destino != req.contact_email


def test_el_desconocido_recibe_el_token_en_el_que_declaro(db_session, solicitud):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="90000001", kind="unknown",
                    contact_email="egresado2005@example.invalid")

    assert TitulaTecEmailHelper.verify_recipient(db_session, req) == \
        "egresado2005@example.invalid"


def test_un_conocido_sin_usuario_en_la_bd_no_tiene_destino(db_session, solicitud):
    """`kind='known'` cuyo usuario desapareció: cae a la bandeja, no al personal."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="99999998", kind="known")

    assert TitulaTecEmailHelper.verify_recipient(db_session, req) is None


def test_send_verify_enrollment_manda_al_buzon_que_se_le_da(db_session, solicitud,
                                                            correo_falso):
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="99123457", kind="known")
    ok = TitulaTecEmailHelper.send_verify_enrollment(
        db_session, req, to="99123457@cdjuarez.tecnm.mx",
        link="https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=abc",
    )

    assert ok is True
    asunto, destinatarios, html = correo_falso[0]
    assert destinatarios == ["99123457@cdjuarez.tecnm.mx"]
    assert "verificar?t=abc" in html
    assert "TitulaTec" in asunto


def test_el_correo_de_alta_lleva_usuario_y_nip(db_session, make_student, solicitud,
                                               correo_falso):
    """D16. Va al PERSONAL: el egresado de 2005 no tiene institucional vivo."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    alumno = make_student(control_number="90000002")
    req = solicitud(control_number="90000002", kind="unknown",
                    contact_email="egresado@example.invalid", status="approved")

    ok = TitulaTecEmailHelper.send_enrollment_approved(db_session, req, alumno,
                                                       nip="4821")

    assert ok is True
    _asunto, destinatarios, html = correo_falso[0]
    assert destinatarios == ["egresado@example.invalid"]
    assert "90000002" in html
    assert "4821" in html


def test_el_nombre_del_solicitante_va_escapado(db_session, solicitud, correo_falso):
    """Un anónimo escribe `first_name`. En un correo HTML eso es inyección."""
    from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

    req = solicitud(control_number="90000003", kind="unknown")
    req.first_name = '<script>alert(1)</script>'
    db_session.flush()

    TitulaTecEmailHelper.send_confirm_contact(
        db_session, req, to=req.contact_email, link="https://example.invalid/x")

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

    req = solicitud(control_number="90000004", kind="unknown")

    assert email_helper.TitulaTecEmailHelper.send_verify_enrollment(
        db_session, req, to=req.contact_email, link="https://example.invalid/x") is False


def test_en_dev_sin_token_la_liga_queda_en_el_log(db_session, solicitud, sin_token,
                                                  monkeypatch, caplog):
    """E9. Sin esto el flujo es imposible de probar a mano en local."""
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_is_production", lambda: False)

    req = solicitud(control_number="90000005", kind="unknown")
    liga = "https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=zzz"

    with caplog.at_level(logging.WARNING,
                         logger="itcj2.apps.titulatec.services.email_helper"):
        email_helper.TitulaTecEmailHelper.send_verify_enrollment(
            db_session, req, to=req.contact_email, link=liga)

    assert "[TT-VERIFY-LINK]" in caplog.text
    assert liga in caplog.text


def test_en_produccion_la_liga_no_se_escribe_jamas(db_session, solicitud, sin_token,
                                                   monkeypatch, caplog):
    """Un token de un solo uso en el log es una credencial en texto claro."""
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_is_production", lambda: True)

    req = solicitud(control_number="90000006", kind="unknown")
    liga = "https://enlinea.cdjuarez.tecnm.mx/titulatec/inscripcion/verificar?t=secreto"

    with caplog.at_level(logging.DEBUG,
                         logger="itcj2.apps.titulatec.services.email_helper"):
        email_helper.TitulaTecEmailHelper.send_verify_enrollment(
            db_session, req, to=req.contact_email, link=liga)

    assert "secreto" not in caplog.text
    assert "[TT-VERIFY-LINK]" not in caplog.text


def test_una_plantilla_rota_no_tumba_nada(db_session, solicitud, correo_falso,
                                          monkeypatch):
    from itcj2.apps.titulatec.services import email_helper
    monkeypatch.setattr(email_helper, "_render", lambda name, ctx: None)

    req = solicitud(control_number="90000007", kind="unknown")

    assert email_helper.TitulaTecEmailHelper.send_enrollment_rejected(db_session, req) is False
    assert correo_falso == []

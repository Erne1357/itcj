from types import SimpleNamespace

import pytest

from itcj2.apps.prorrogas_tec.services import notify
from itcj2.core.models.notification import Notification
from itcj2.core.utils import msgraph_mail


def test_las_pruebas_no_ven_el_buzon_real():  # tests/conftest.py::_sin_buzones_reales
    assert msgraph_mail.acquire_token_silent("prorrogas_tec") is None


def test_sin_cuenta_de_correo_no_truena(monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    assert notify.send_email(template="decision_aceptada.html", context={"folio": "PR-00001", "link": "x"},
                             subject="s", to="a@example.invalid") is False


@pytest.mark.parametrize("plantilla", ["invitacion.html", "decision_aceptada.html", "decision_rechazada.html",
                                       "carta_lista.html", "plan_modificado.html", "recordatorio.html",
                                       "firma_pendiente.html", "referencia_pendiente.html", "recibo_inconsistente.html",
                                       "pago_registrado.html", "liquidada.html"])
def test_cada_correo_se_arma_con_logo_liga_y_sin_genero(plantilla):
    from itcj2.templates import templates
    html = templates.env.get_template(f"prorrogas_tec/email/{plantilla}").render(
        folio="PR-1", link="https://x/prorrogas/estudiante", logo_url="https://x/logo.png", comentario="Motivo",
        adjunto=True, total="$10.00", pagos=[{"etiqueta": "Pago único", "fecha": "01 de mayo de 2091", "monto": "$10.00"}],
        saldo="$10.00", proxima_fecha="01 de mayo de 2091", proxima_monto="$10.00", vencido=False, numero=1,
        motivo="No coincide", monto="$10.00", fecha="01 de mayo de 2091", folio_caja="ZZ-1")
    assert "https://x/prorrogas/estudiante" in html and 'src="https://x/logo.png"' in html
    assert "secretaria" not in html.lower() and "alumno" not in html.lower()


def test_el_tono_de_cada_correo_llega_a_la_base():
    from itcj2.templates import templates
    html = templates.env.get_template("prorrogas_tec/email/decision_aceptada.html").render(link="x", adjunto=False)
    assert "border:1px solid #6799E0;background-color:#FFFFFF;color:#1A130E;" in html  # etiqueta "ok", no la neutra
    assert "Puedes descargar tu carta de aceptación en Mi prórroga." in html


def test_envia_con_graph_y_lleva_la_liga(monkeypatch):
    sent = {}
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: "tok")

    def fake_send(token, subject, html, to, *a, inline=None, **k):
        sent.update(subject=subject, html=html, to=to, inline=inline)
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr(msgraph_mail, "graph_send_mail", fake_send)
    ok = notify.send_email(template="invitacion.html", context={"link": "https://x/prorrogas/unirse/invitacion/abc"},
                           subject="Invitación al módulo de Prórrogas", to="L99000000@cdjuarez.tecnm.mx")
    assert ok and sent["to"] == ["L99000000@cdjuarez.tecnm.mx"] and "unirse/invitacion/abc" in sent["html"]
    (cid, png), = sent["inline"]  # el logo va dentro del correo, no por URL
    assert f'src="cid:{cid}"' in sent["html"] and png.startswith(b"\x89PNG")


def test_el_aviso_en_la_plataforma_sale_aunque_falle_el_correo(db_session, solicitud, monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante")
    n = db_session.query(Notification).filter_by(user_id=solicitud.student_id, app_name="prorrogas_tec").one()
    assert n.type == "prorroga_aceptada" and n.title == "Tu prórroga fue aceptada"


def test_un_aviso_que_falla_no_envenena_la_sesion(db_session, solicitud, monkeypatch):
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
    from itcj2.core.services.notification_service import NotificationService

    def roto(db, *a, **k):
        db.add(Notification(user_id=None, app_name="prorrogas_tec", type="x", title="x"))
        db.flush()  # viola NOT NULL

    monkeypatch.setattr(NotificationService, "create", roto)
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante")
    assert db_session.query(ProrrogaRequest).filter_by(id=solicitud.id).one()


def test_si_el_correo_falla_queda_en_el_historial(db_session, solicitud, monkeypatch):
    from itcj2.apps.prorrogas_tec.models.event import ProrrogaEvent
    from itcj2.apps.prorrogas_tec.services.events import last_mail_failed
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    assert notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante") is False
    db_session.flush()
    ev = db_session.query(ProrrogaEvent).filter_by(request_id=solicitud.id, event_type="correo_no_enviado").one()
    assert ev.payload == {"aviso": "aceptada"} and last_mail_failed(db_session, solicitud.id)


def test_sin_correo_capturado_basta_el_aviso(db_session, solicitud):
    solicitud.email = None
    assert notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante") is True


def test_notify_student_no_lanza_si_el_historial_falla(db_session, solicitud, monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)

    def roto(*a, **k):
        raise RuntimeError("bitácora caída")

    monkeypatch.setattr(notify, "log_event", roto)
    assert notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante") is False


def _post_falso(monkeypatch):
    sent = {}
    monkeypatch.setattr(msgraph_mail.requests, "post",
                        lambda url, headers, json, timeout: sent.update(json) or SimpleNamespace(status_code=202))
    return sent


def test_sin_adjuntos_el_envio_no_cambia(monkeypatch):  # lo comparten AgendaTec, Mantenimiento y TitulaTec
    sent = _post_falso(monkeypatch)
    msgraph_mail.graph_send_mail("t", "s", "<p>", ["a@example.invalid"])
    assert "attachments" not in sent["message"]


def test_imagen_inline_va_con_cid(monkeypatch):
    sent = _post_falso(monkeypatch)
    msgraph_mail.graph_send_mail("t", "s", "<p>", ["a@example.invalid"], inline=[("logo.png", b"\x89PNG")])
    a, = sent["message"]["attachments"]
    assert (a["contentId"], a["isInline"], a["contentType"]) == ("logo.png", True, "image/png")


def test_con_adjunto_va_en_base64(monkeypatch):
    import base64
    sent = _post_falso(monkeypatch)
    msgraph_mail.graph_send_mail("t", "s", "<p>", ["a@example.invalid"], attachments=[("c.pdf", b"%PDF")])
    a, = sent["message"]["attachments"]
    assert a["@odata.type"] == "#microsoft.graph.fileAttachment" and a["name"] == "c.pdf"
    assert a["contentType"] == "application/pdf" and base64.b64decode(a["contentBytes"]) == b"%PDF"


def test_la_aceptacion_ya_no_manda_a_acordar_el_monto():
    from itcj2.templates import templates
    html = templates.env.get_template("prorrogas_tec/email/decision_aceptada.html").render(folio="PR-1", link="x")
    assert "Acude" not in html and "referencia bancaria" in html
    assert "Acude" not in notify._CUERPOS["aceptada"]


def test_cobro_o_subida_de_recibo_no_apagan_el_aviso_de_correo_fallido(db_session, solicitud, monkeypatch):  # M3
    from itcj2.apps.prorrogas_tec.services.events import last_mail_failed, log_event
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    notify.notify_student(db_session, solicitud, kind="aceptada", link="/prorrogas/estudiante")
    db_session.flush()
    for t in ("recibo_registrado", "recibo_anulado", "recibo_subido"):
        log_event(db_session, event_type=t, request_id=solicitud.id)
    db_session.flush()
    assert last_mail_failed(db_session, solicitud.id)

from types import SimpleNamespace

from itcj2.apps.prorrogas_tec.services import notify
from itcj2.core.models.notification import Notification
from itcj2.core.utils import msgraph_mail


def test_sin_cuenta_de_correo_no_truena(monkeypatch):
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: None)
    assert notify.send_email(template="decision_aceptada.html", context={"folio": "PR-00001", "link": "x"},
                             subject="s", to="a@example.invalid") is False


def test_envia_con_graph_y_lleva_la_liga(monkeypatch):
    sent = {}
    monkeypatch.setattr(msgraph_mail, "acquire_token_silent", lambda app: "tok")

    def fake_send(token, subject, html, to, *a, **k):
        sent.update(subject=subject, html=html, to=to)
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr(msgraph_mail, "graph_send_mail", fake_send)
    ok = notify.send_email(template="invitacion.html", context={"link": "https://x/prorrogas/unirse/invitacion/abc"},
                           subject="Invitación al módulo de Prórrogas", to="L99000000@cdjuarez.tecnm.mx")
    assert ok and sent["to"] == ["L99000000@cdjuarez.tecnm.mx"] and "unirse/invitacion/abc" in sent["html"]


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

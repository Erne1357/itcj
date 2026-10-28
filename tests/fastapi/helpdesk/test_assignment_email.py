"""Correo al técnico asignado (T5): servicio, tarea Celery y hooks de api/assignments.

Nunca se envía correo real: `acquire_token_silent` y `graph_send_mail` siempre
van parcheados. Prefijo de datos: `aa5_`.
"""
from unittest.mock import AsyncMock, MagicMock

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.helpdesk_settings import HelpdeskSettings
from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.sockets import helpdesk as hd_sockets

from ._catalog import ensure_helpdesk_category

SVC = "itcj2.apps.helpdesk.services.assignment_email_service"


@pytest.fixture()
def auth_headers():
    now = int(time.time())
    tok = jwt.encode({"sub": "1", "role": "admin", "cn": None, "name": "aa5", "iat": now,
                      "exp": now + 3600}, get_settings().SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={tok}"}


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _user(db, last, email="aa5@example.com", active=True):
    u = User(first_name="aa5", last_name=last, email=email, is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _set_list(db, ids):
    row = db.get(HelpdeskSettings, 1)
    if row is None:
        row = HelpdeskSettings(id=1, auto_assign_enabled=False, assignment_email_user_ids=[])
        db.add(row)
    row.assignment_email_user_ids = list(ids)
    db.commit()


def _ticket(db, number, requester, tech=None, **kw):
    cat = ensure_helpdesk_category(db, code="aa5_cat")
    t = Ticket(
        ticket_number=number, requester_id=requester.id, area="DESARROLLO",
        category_id=cat.id, priority="ALTA", title=kw.pop("title", "aa5 titulo"),
        description="aa5 descripcion de prueba suficientemente larga.",
        status="ASSIGNED" if tech else "PENDING",
        assigned_to_user_id=tech.id if tech else None,
        created_by_id=requester.id, updated_by_id=requester.id, **kw,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture()
def env(db_session, monkeypatch):
    """Parchea SessionLocal (la tarea usa la sesión del test) y Graph."""
    class _Ctx:
        def __enter__(self):
            return db_session

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _Ctx())
    token = MagicMock(return_value="tok")
    send = MagicMock(return_value=MagicMock(status_code=202))
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.acquire_token_silent", token)
    monkeypatch.setattr("itcj2.core.utils.msgraph_mail.graph_send_mail", send)
    return token, send


# ---------------- servicio ----------------

def test_enqueue_solo_si_esta_en_la_lista(db_session, monkeypatch):
    from itcj2.apps.helpdesk.services.assignment_email_service import enqueue_assignment_email
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    delay = MagicMock()
    monkeypatch.setattr(send_assignment_email, "delay", delay)
    u = _user(db_session, "A")
    _set_list(db_session, [])
    assert enqueue_assignment_email(db_session, 1, u.id) is False
    delay.assert_not_called()
    _set_list(db_session, [u.id])
    assert enqueue_assignment_email(db_session, 1, u.id) is True
    delay.assert_called_once_with(1, u.id)


def test_enqueue_traga_error_de_redis(db_session, monkeypatch):
    from itcj2.apps.helpdesk.services.assignment_email_service import enqueue_assignment_email
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    monkeypatch.setattr(send_assignment_email, "delay", MagicMock(side_effect=ConnectionError("redis")))
    u = _user(db_session, "B")
    _set_list(db_session, [u.id])
    assert enqueue_assignment_email(db_session, 1, u.id) is False


def test_asunto_usa_subject_template_si_existe(db_session):
    from itcj2.apps.helpdesk.services.assignment_email_service import build_assignment_email
    from itcj2.apps.helpdesk.utils import catalog_cache
    u = _user(db_session, "C")
    t = _ticket(db_session, "AA5-0001", u, u)
    tpl = db_session.query(NotificationTemplate).filter_by(code="ticket_assigned").first()
    if tpl is None:
        tpl = NotificationTemplate(code="ticket_assigned", name="aa5", body_template="x",
                                   is_active=True)
        db_session.add(tpl)
    tpl.is_active = True
    tpl.subject_template = "AA5 {{ ticket.ticket_number }}"
    db_session.commit()
    catalog_cache.invalidate_notification_templates()
    try:
        subject, _ = build_assignment_email(db_session, t, u)
        assert subject == "AA5 AA5-0001"
    finally:
        catalog_cache.invalidate_notification_templates()


def test_html_escapa_titulo(db_session):
    from itcj2.apps.helpdesk.services.assignment_email_service import build_assignment_email
    u = _user(db_session, "D")
    t = _ticket(db_session, "AA5-0002", u, u, title="<script>alert(1)</script>")
    _, html = build_assignment_email(db_session, t, u)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert f"/help-desk/user/tickets/{t.id}" in html


# ---------------- tarea ----------------

def test_tarea_envia_si_sigue_asignado(db_session, env, monkeypatch):
    monkeypatch.setattr("itcj2.apps.helpdesk.utils.catalog_cache.get_notification_template",
                        lambda db, code: None)
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    _, send = env
    u = _user(db_session, "E", email="tec-e@example.com")
    t = _ticket(db_session, "AA5-0003", u, u)
    _set_list(db_session, [u.id])
    res = send_assignment_email.run(t.id, u.id)
    assert res["sent"] is True
    args = send.call_args.args
    assert args[0] == "tok"
    assert args[1] == "[Help Desk ITCJ] Ticket #AA5-0003 asignado a ti"
    assert args[3] == ["tec-e@example.com"]


def test_tarea_no_envia_si_fue_reasignado(db_session, env):
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    _, send = env
    a, b = _user(db_session, "F1"), _user(db_session, "F2")
    t = _ticket(db_session, "AA5-0004", a, b)
    _set_list(db_session, [a.id, b.id])
    res = send_assignment_email.run(t.id, a.id)
    assert res["skipped"] == "reassigned"
    send.assert_not_called()


def test_tarea_sin_token_no_reintenta(db_session, env, monkeypatch):
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    token, send = env
    token.return_value = None
    retry = MagicMock(side_effect=AssertionError("no debe reintentar"))
    monkeypatch.setattr(send_assignment_email, "retry", retry)
    u = _user(db_session, "G")
    t = _ticket(db_session, "AA5-0005", u, u)
    _set_list(db_session, [u.id])
    assert send_assignment_email.run(t.id, u.id)["skipped"] == "no_token"
    send.assert_not_called()


def test_tarea_reintenta_en_error_graph(db_session, env, monkeypatch):
    from itcj2.tasks.helpdesk_tasks import send_assignment_email
    _, send = env
    send.return_value = MagicMock(status_code=500)
    retry = MagicMock(side_effect=RuntimeError("retry-called"))
    monkeypatch.setattr(send_assignment_email, "retry", retry)
    u = _user(db_session, "H")
    t = _ticket(db_session, "AA5-0006", u, u)
    _set_list(db_session, [u.id])
    with pytest.raises(RuntimeError, match="retry-called"):
        send_assignment_email.run(t.id, u.id)
    retry.assert_called_once()


# ---------------- endpoints ----------------

@pytest.fixture()
def api(db_session, monkeypatch):
    enq = MagicMock(return_value=True)
    monkeypatch.setattr(f"{SVC}.enqueue_assignment_email", enq)
    monkeypatch.setattr(hd_sockets, "broadcast_ticket_assigned", AsyncMock())
    monkeypatch.setattr(hd_sockets, "broadcast_ticket_reassigned", AsyncMock())
    monkeypatch.setattr(hd_sockets, "broadcast_ticket_self_assigned", AsyncMock())
    monkeypatch.setattr(
        "itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_assigned",
        MagicMock())
    monkeypatch.setattr(
        "itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_reassigned",
        MagicMock())
    return enq


def _fake(monkeypatch, name, ticket):
    a = MagicMock()
    a.ticket = ticket
    a.to_dict.return_value = {}
    monkeypatch.setattr(f"itcj2.apps.helpdesk.services.assignment_service.{name}",
                        MagicMock(return_value=a))


def test_asignar_a_persona_encola(client, db_session, auth_headers, api, monkeypatch):
    u = _user(db_session, "I")
    t = _ticket(db_session, "AA5-0007", u, u)
    _fake(monkeypatch, "assign_ticket", t)
    r = client.post("/api/help-desk/v2/assignments",
                    json={"ticket_id": t.id, "assigned_to_user_id": u.id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    api.assert_called_once_with(db_session, t.id, u.id)


def test_asignar_a_equipo_no_encola(client, db_session, auth_headers, api, monkeypatch):
    u = _user(db_session, "J")
    t = _ticket(db_session, "AA5-0008", u)
    _fake(monkeypatch, "assign_ticket", t)
    r = client.post("/api/help-desk/v2/assignments",
                    json={"ticket_id": t.id, "assigned_to_team": "desarrollo"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    api.assert_not_called()


def test_reasignar_encola_al_nuevo(client, db_session, auth_headers, api, monkeypatch):
    u = _user(db_session, "K")
    t = _ticket(db_session, "AA5-0009", u, u)
    _fake(monkeypatch, "reassign_ticket", t)
    r = client.post(f"/api/help-desk/v2/assignments/{t.id}/reassign",
                    json={"assigned_to_user_id": u.id}, headers=auth_headers)
    assert r.status_code == 200, r.text
    api.assert_called_once_with(db_session, t.id, u.id)


def test_autoasignarse_no_encola(client, db_session, auth_headers, api, monkeypatch):
    from .test_ticket_split_api import _grant_role
    u = _user(db_session, "L")
    _grant_role(db_session, u, "tech_desarrollo")
    t = _ticket(db_session, "AA5-0010", u, u)
    _fake(monkeypatch, "self_assign_ticket", t)
    now = int(time.time())
    tok = jwt.encode({"sub": str(u.id), "role": None, "cn": None, "name": "aa5", "iat": now,
                      "exp": now + 3600}, get_settings().SECRET_KEY, algorithm="HS256")
    r = client.post(f"/api/help-desk/v2/assignments/{t.id}/self-assign",
                    headers={"Cookie": f"itcj_token={tok}"})
    assert r.status_code == 200, r.text
    api.assert_not_called()

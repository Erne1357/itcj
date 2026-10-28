"""Motor de asignación automática dentro de `POST /api/help-desk/v2/tickets` (plan T7).

Se fija: con regla el ticket sale ASSIGNED (respuesta ya refleja el estado final) con
broadcast `actor_id=None` y correo encolado; motor apagado -> PENDING; y que ningún fallo
del motor, del broadcast o del encolado cambia el 201 de creación. Prefijo `aa7_`.
"""
import time
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.services.helpdesk_settings_service import update_settings
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.sockets import helpdesk as hd_sockets

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority, ensure_role

EMAIL_TARGET = "itcj2.apps.helpdesk.services.assignment_email_service.enqueue_assignment_email"
ENGINE_TARGET = "itcj2.apps.helpdesk.services.auto_assign_service.AutoAssignService.try_auto_assign"


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def hooks(monkeypatch):
    """Broadcasts con AsyncMock y correo parcheado: nada real."""
    assigned = AsyncMock()
    monkeypatch.setattr(hd_sockets, "broadcast_ticket_assigned", assigned)
    monkeypatch.setattr(hd_sockets, "broadcast_ticket_created", AsyncMock())
    with patch(EMAIL_TARGET, return_value=True) as email:
        yield {"assigned": assigned, "email": email}


def _commit(db, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@pytest.fixture()
def mundo(db_session):
    db = db_session
    app = db.query(App).filter_by(key="helpdesk").first() or _commit(
        db, App(key="helpdesk", name="Help desk", is_active=True))
    dev = ensure_role(db, "tech_desarrollo")
    admin = _commit(db, User(first_name="aa7", last_name="aa7_admin", is_active=True))
    tech = _commit(db, User(first_name="aa7", last_name="aa7_tech", is_active=True))
    db.add(UserAppRole(user_id=tech.id, app_id=app.id, role_id=dev.id))
    db.query(AssignmentRule).update({"is_active": False})
    ensure_helpdesk_priority(db, "MEDIA")
    cat = ensure_helpdesk_category(db, "aa7_cat", "DESARROLLO")
    db.commit()
    return {"admin": admin, "tech": tech, "cat": cat}


def _regla(db, m):
    return _commit(db, AssignmentRule(
        area="DESARROLLO", category_id=None, priority=None, strategy="round_robin",
        technician_ids=[m["tech"].id], is_active=True, created_by_id=m["admin"].id))


def _post(client, m):
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(m["admin"].id), "role": "admin", "cn": None, "name": "T",
         "iat": now, "exp": now + 3600},
        get_settings().SECRET_KEY, algorithm="HS256")
    return client.post("/api/help-desk/v2/tickets", headers={"Cookie": f"itcj_token={token}"}, json={
        "area": "DESARROLLO", "category_id": m["cat"].id, "priority": "MEDIA",
        "title": "aa7 ticket de prueba",
        "description": "aa7 descripcion con longitud suficiente para validar.",
    })


def test_con_regla_sale_asignado(client, db_session, mundo, hooks):
    update_settings(db_session, user_id=mundo["admin"].id, auto_assign_enabled=True)
    _regla(db_session, mundo)

    resp = _post(client, mundo)

    assert resp.status_code == 201, resp.text
    t = resp.json()["ticket"]
    assert t["status"] == "ASSIGNED"
    assert t["assigned_to"]["id"] == mundo["tech"].id
    hooks["assigned"].assert_awaited_once()
    assert hooks["assigned"].await_args.kwargs["actor_id"] is None
    hooks["email"].assert_called_once()
    assert hooks["email"].call_args.args[1:] == (t["id"], mundo["tech"].id)


def test_motor_apagado_sale_pending(client, db_session, mundo, hooks):
    update_settings(db_session, user_id=mundo["admin"].id, auto_assign_enabled=False)
    _regla(db_session, mundo)

    resp = _post(client, mundo)

    assert resp.status_code == 201, resp.text
    assert resp.json()["ticket"]["status"] == "PENDING"
    hooks["assigned"].assert_not_awaited()
    hooks["email"].assert_not_called()


def test_motor_que_lanza_no_rompe_la_creacion(client, db_session, mundo, hooks):
    update_settings(db_session, user_id=mundo["admin"].id, auto_assign_enabled=True)
    _regla(db_session, mundo)

    with patch(ENGINE_TARGET, side_effect=RuntimeError("boom")):
        resp = _post(client, mundo)

    assert resp.status_code == 201, resp.text
    assert resp.json()["ticket"]["status"] == "PENDING"


def test_fallo_de_broadcast_o_correo_no_rompe_la_creacion(client, db_session, mundo, hooks):
    update_settings(db_session, user_id=mundo["admin"].id, auto_assign_enabled=True)
    _regla(db_session, mundo)
    hooks["assigned"].side_effect = RuntimeError("ws")
    hooks["email"].side_effect = RuntimeError("celery")

    resp = _post(client, mundo)

    assert resp.status_code == 201, resp.text
    assert resp.json()["ticket"]["status"] == "ASSIGNED"

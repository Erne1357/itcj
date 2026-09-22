"""
Tests API de "Partir ticket": `POST /api/help-desk/v2/tickets/{ticket_id}/split`.

Cubre el guard (401 sin cookie / 403 sin el permiso `helpdesk.tickets.api.split`),
que el permiso propio abre la puerta tanto por rol (`admin`) como por
`PositionAppPerm` directo (la forma real de la posición `secretary_comp_center`
en el DML, sin necesitar un rol de helpdesk), el camino feliz (201, un
`ticket_created` por cada parte NUEVA a `_admin_room()` con `actor_id` y
`split_from`), la notificación `TICKET_SPLIT` (solicitante + técnico asignado,
nunca al actor) y que un 400 del servicio llega como `resp.json()["error"]`
con el texto "Parte ...".

Infraestructura de `client`/`fake_emit`/`_jwt_cookie`/`_user`/`_dept`/`_ticket`/
`_emitted_rooms` copiada de `test_broadcast_single_emit.py:53-145`; `_perm` y
el patrón de puesto con `PositionAppPerm` directo, de `test_ticket_guards_scope.py`.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.notification import Notification
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.sockets import helpdesk as hd_sockets

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

SPLIT_PERM = "helpdesk.tickets.api.split"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, `get_db` apunta a la sesión transaccional del
    test (mismo patrón que test_broadcast_single_emit.py)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def fake_emit(monkeypatch):
    """Reemplaza sio.emit por un AsyncMock: captura cada emit sin tocar Redis de
    verdad."""
    mock = AsyncMock()
    monkeypatch.setattr(hd_sockets.sio, "emit", mock)
    return mock


def _jwt_cookie(user_id: int, role: str | None = None) -> dict:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": role, "cn": None, "name": "Test",
        "iat": now, "exp": now + 24 * 3600,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _dept(db, code) -> Department:
    d = Department(code=code, name=code, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _grant_role(db, user, role_name) -> Role:
    """Rol DIRECTO del usuario en helpdesk (`UserAppRole`), sin permisos
    propios — da acceso a la app pero NO al permiso de partir (test de 403)."""
    app = db.query(App).filter_by(key="helpdesk").first()
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name)
        db.add(role)
        db.commit()
        db.refresh(role)
    exists = db.query(UserAppRole).filter_by(user_id=user.id, app_id=app.id, role_id=role.id).first()
    if not exists:
        db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
        db.commit()
    return role


def _perm(db, app, code) -> Permission:
    """Get-or-create de `Permission` — en CI (BD vacía por create_all) la fila
    del permiso no existe hasta que el DML corre, así que el test la siembra."""
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _grant_position_perm(db, user, department, *, code) -> Position:
    """Puesto con el permiso DIRECTO vía `PositionAppPerm` (patrón de
    `test_ticket_guards_scope.py::_grant`) — la forma real en que
    `secretary_comp_center` recibe `helpdesk.tickets.api.split` en el DML real,
    sin ningún rol de helpdesk."""
    app = db.query(App).filter_by(key="helpdesk").first()
    pos = Position(code=f"tksplit_pos_{user.id}", title="Secretaria",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    perm = _perm(db, app, code)
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _ticket(db, number, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=None,
        area="SOPORTE",
        category_id=category.id,
        priority="MEDIA",
        title=f"{number} - ticket de prueba",
        description="Descripción de prueba con longitud suficiente para pasar validaciones.",
        status="PENDING",
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    defaults.update(overrides)
    t = Ticket(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _emitted_rooms(mock, event: str) -> list:
    """Salas (`to=`) a las que se emitió `event`, en el orden en que ocurrieron."""
    return [c.kwargs.get("to") for c in mock.call_args_list if c.args and c.args[0] == event]


def _part(category, **overrides) -> dict:
    data = dict(
        area="SOPORTE",
        category_id=category.id,
        priority="MEDIA",
        title="Cuenta de correo institucional",
        description="El usuario necesita una cuenta de correo institucional nueva.",
    )
    data.update(overrides)
    return data


# ─────────────────────────────────── tests ────────────────────────────────────

class TestSplitAuthGuard:

    def test_no_cookie_returns_401(self, client, db_session):
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        requester = _user(db_session, "ReqNoAuth")
        ticket = _ticket(db_session, "TKS-NOAUTH-1", requester, category)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={"original": _part(category), "parts": [_part(category)]},
        )
        assert resp.status_code == 401

    def test_user_without_split_permission_returns_403(self, client, db_session):
        """El actor tiene acceso a la app (rol `tech_soporte`) pero ese rol no
        trae el permiso de partir — debe caer en el segundo check de
        `require_perms` (intersección de `cached_perms`), no en el de app."""
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        requester = _user(db_session, "ReqNoPerm")
        actor = _user(db_session, "ActorNoPerm")
        _grant_role(db_session, actor, "tech_soporte")
        ticket = _ticket(db_session, "TKS-NOPERM-1", requester, category)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={"original": _part(category), "parts": [_part(category)]},
            headers=_jwt_cookie(actor.id, role=None),
        )
        assert resp.status_code == 403


class TestSplitPermissionGrantsAccess:

    def test_position_app_perm_alone_grants_access(self, client, db_session, fake_emit):
        """El permiso llega por `PositionAppPerm` directo (sin rol de helpdesk)
        — confirma que `helpdesk.tickets.api.split` es el código que el
        endpoint realmente exige, igual que lo recibirá `secretary_comp_center`
        vía el DML."""
        dept = _dept(db_session, "tks_dept_posperm")
        requester = _user(db_session, "ReqPosPerm")
        secretary = _user(db_session, "SecPosPerm")
        _grant_position_perm(db_session, secretary, dept, code=SPLIT_PERM)
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(db_session, "TKS-POSPERM-1", requester, category,
                          requester_department_id=dept.id)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de SII nueva")],
            },
            headers=_jwt_cookie(secretary.id, role=None),
        )
        assert resp.status_code == 201, resp.text


class TestSplitHappyPath:

    def test_admin_splits_ticket_into_three(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tks_dept_admin")
        requester = _user(db_session, "ReqAdminSplit")
        admin_actor = _user(db_session, "AdminSplitActor")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-ADMIN-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [
                    _part(category, title="Cuenta de correo institucional"),
                    _part(category, title="Cuenta de SII nueva"),
                ],
            },
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        body = resp.json()
        assert body["success"] is True
        assert "dividido en 3 tickets" in body["message"]
        assert body["data"]["original"]["ticket_number"] == "TKS-ADMIN-1"
        assert len(body["data"]["tickets"]) == 2

        # Un broadcast `ticket_created` por PARTE NUEVA (2), no por el original.
        rooms = _emitted_rooms(fake_emit, "ticket_created")
        assert rooms.count(hd_sockets._admin_room()) == 2

        split_events = [c for c in fake_emit.call_args_list if c.args and c.args[0] == "ticket_created"]
        for c in split_events:
            assert c.args[1]["actor_id"] == admin_actor.id
            assert c.args[1]["split_from"] == "TKS-ADMIN-1"

    def test_get_ticket_exposes_split_children_after_split(self, client, db_session, fake_emit):
        """No-regresión ligera del contrato de Task 1: el detalle del original
        debe listar las partes nuevas en `split_children` tras partir.

        `GET /tickets/{id}` re-chequea con `can_user_view_ticket`, que lee
        roles de BD (no el claim `role` del JWT) — el bypass de admin global
        solo abre el guard `require_perms`, así que aquí hace falta el rol
        real (mismo patrón que `test_ticket_guards_scope.py::
        test_admin_still_sees_global_counts`)."""
        dept = _dept(db_session, "tks_dept_children")
        requester = _user(db_session, "ReqChildren")
        admin_actor = _user(db_session, "AdminChildrenActor")
        _grant_role(db_session, admin_actor, "admin")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-CHILDREN-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text
        new_ticket_id = resp.json()["data"]["tickets"][0]["id"]

        detail = client.get(
            f"/api/help-desk/v2/tickets/{ticket.id}",
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert detail.status_code == 200
        child_ids = {c["id"] for c in detail.json()["ticket"]["split_children"]}
        assert child_ids == {new_ticket_id}


class TestSplitNotifications:

    def test_requester_and_technician_notified_but_not_actor(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tks_dept_notif")
        requester = _user(db_session, "ReqNotif")
        tech = _user(db_session, "TechNotif")
        admin_actor = _user(db_session, "AdminNotifActor")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-NOTIF-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_user_id=tech.id,
            requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        notifs = db_session.query(Notification).filter_by(
            type="TICKET_SPLIT", ticket_id=ticket.id,
        ).all()
        recipients = {n.user_id for n in notifs}
        assert recipients == {requester.id, tech.id}
        assert len(notifs) == 2  # exactamente una por destinatario, nada duplicado

    def test_actor_as_requester_gets_no_notification(self, client, db_session, fake_emit):
        """Quien parte ya sabe que lo partió: nunca se notifica al actor,
        aunque sea el propio solicitante."""
        dept = _dept(db_session, "tks_dept_selfnotif")
        requester = _user(db_session, "ReqSelfNotif")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-SELFNOTIF-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        notifs = db_session.query(Notification).filter_by(
            type="TICKET_SPLIT", ticket_id=ticket.id,
        ).all()
        assert notifs == []


class TestSplitServiceValidationError:

    def test_invalid_part_returns_400_with_parte_message(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tks_dept_400")
        requester = _user(db_session, "Req400")
        admin_actor = _user(db_session, "Admin400Actor")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-400-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="ab")],  # < 5 caracteres → 400 del servicio
            },
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 400
        assert "Parte" in resp.json()["error"]

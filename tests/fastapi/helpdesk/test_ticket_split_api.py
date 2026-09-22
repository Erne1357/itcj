"""
Tests API de "Partir ticket": `POST /api/help-desk/v2/tickets/{ticket_id}/split`.

Cubre el guard (401 sin cookie / 403 sin ninguno de los dos permisos
`helpdesk.tickets.api.split.{all,own}` / 403 CON `.split.all` pero sin
visibilidad sobre ese ticket), que el permiso propio abre la puerta tanto por
rol (`admin`) como por `PositionAppPerm` directo (la forma real de la posición
`secretary_comp_center` en el DML, sin necesitar un rol de helpdesk, con el
alcance departamental que la deja ver el ticket), el camino feliz (201, un
`ticket_created` por cada parte NUEVA a `_admin_room()` con `actor_id` y
`split_from`), la notificación `TICKET_SPLIT` (solicitante + técnico asignado,
nunca al actor) y que un 400 del servicio llega como `resp.json()["error"]`
con el texto "Parte ...".

Fase 2 (`TestSplitOwnScope`): con SOLO `.split.own` (roles `tech_desarrollo` /
`tech_soporte` en el DML real) el técnico solo puede partir un ticket asignado
A ÉL o sin asignar en la cola de SU equipo (`assigned_to_team`) — "los
técnicos ven todo el instituto" (`can_user_view_ticket`) NO aplica a este
alcance a propósito (D17 del spec), así que estos tests NO pasan por ese
camino: usan `_grant_role_with_perm` (rol + `RolePermission`, la forma real en
que un rol trae el permiso) en vez de `_grant_position_perm`.

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
from sqlalchemy import text

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.notification import Notification
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.sockets import helpdesk as hd_sockets

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

SPLIT_PERM_ALL = "helpdesk.tickets.api.split.all"
SPLIT_PERM_OWN = "helpdesk.tickets.api.split.own"
# Alcance departamental: lo que hace que una secretaría VEA los tickets de su
# departamento (`ticket_service.department_scope_ids`). El permiso de partir
# abre la operación, no el ticket.
READ_DEPT_PERM = "helpdesk.tickets.api.read.department"


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
    propios — da acceso a la app pero NO al permiso de partir (test de 403).

    Simula a propósito un rol "pelón": en el DML real `tech_desarrollo` y
    `tech_soporte` SÍ traen `.split.own` (ver `_grant_role_with_perm`); esta
    versión sirve para probar el camino "tiene la app pero no el permiso"."""
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


def _grant_role_with_perm(db, user, role_name, codes) -> Role:
    """Rol del usuario en helpdesk (`UserAppRole`) CON `codes` unidos por
    `RolePermission` — la forma real en que `tech_desarrollo`/`tech_soporte`
    reciben `helpdesk.tickets.api.split.own` en el DML real (02_assign_split_
    permission.sql, sección `.own`)."""
    role = _grant_role(db, user, role_name)
    app = db.query(App).filter_by(key="helpdesk").first()
    for code in codes:
        perm = _perm(db, app, code)
        exists = db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first()
        if not exists:
            db.add(RolePermission(role_id=role.id, perm_id=perm.id))
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


def _grant_position_perm(db, user, department, *, codes) -> Position:
    """Puesto con permisos DIRECTOS vía `PositionAppPerm` (patrón de
    `test_ticket_guards_scope.py::_grant`) — la forma real en que
    `secretary_comp_center` recibe `helpdesk.tickets.api.split.all` en el DML
    real, sin ningún rol de helpdesk."""
    app = db.query(App).filter_by(key="helpdesk").first()
    pos = Position(code=f"tksplit_pos_{user.id}", title="Secretaria",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    for code in codes:
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
        """El actor tiene acceso a la app (rol `tech_soporte`) pero ese rol NO
        trae ningún permiso propio en este test (`_grant_role` a secas, sin
        `RolePermission` — a diferencia del DML real, que sí le da `.split.own`)
        — debe caer en el segundo check de `require_perms` (intersección de
        `cached_perms` contra `.split.all`/`.split.own`), no en el de app."""
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

    def test_split_permission_without_visibility_returns_403(self, client, db_session):
        """Tener `helpdesk.tickets.api.split.all` abre la OPERACIÓN, no el ticket.

        El actor tiene el permiso por puesto pero NINGÚN alcance sobre este
        ticket: no es el solicitante, no está asignado y el ticket es de otro
        departamento (el suyo no lo cubre — ni siquiera tiene
        `read.department`). Sin el chequeo de visibilidad del endpoint, el
        servicio hace `db.get(Ticket, ticket_id)` a secas y cualquier futuro
        titular del permiso (p. ej. un jefe de departamento, la concesión
        natural que sigue) podría partir cualquier ticket del instituto
        adivinando el id. (Test de la fase 1, adaptado al code `.split.all`.)"""
        own_dept = _dept(db_session, "tks_dept_novis_propio")
        other_dept = _dept(db_session, "tks_dept_novis_ajeno")
        requester = _user(db_session, "ReqNoVis")
        actor = _user(db_session, "ActorNoVis")
        _grant_position_perm(db_session, actor, own_dept, codes=[SPLIT_PERM_ALL])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(db_session, "TKS-NOVIS-1", requester, category,
                          requester_department_id=other_dept.id)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de SII nueva")],
            },
            headers=_jwt_cookie(actor.id, role=None),
        )
        assert resp.status_code == 403, resp.text
        # Y nada se partió: ni partes nuevas ni edición del original.
        assert db_session.query(Ticket).filter_by(split_from_ticket_id=ticket.id).count() == 0
        db_session.refresh(ticket)
        assert ticket.title == "TKS-NOVIS-1 - ticket de prueba"


class TestSplitPermissionGrantsAccess:

    def test_position_app_perm_alone_grants_access(self, client, db_session, fake_emit):
        """El permiso llega por `PositionAppPerm` directo (sin rol de helpdesk)
        — confirma que `helpdesk.tickets.api.split.all` es el código que el
        endpoint realmente exige para este alcance, igual que lo recibirá
        `secretary_comp_center` vía el DML.

        El puesto lleva además `read.department` (lo que el DML ya le concede a
        las 28 secretarías) porque `.split.all` exige VER el ticket, no solo el
        permiso: ese es el alcance por el que la secretaría alcanza legítimamente
        un ticket de su departamento que levantó alguien más."""
        dept = _dept(db_session, "tks_dept_posperm")
        requester = _user(db_session, "ReqPosPerm")
        secretary = _user(db_session, "SecPosPerm")
        _grant_position_perm(db_session, secretary, dept, codes=[SPLIT_PERM_ALL, READ_DEPT_PERM])
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


class TestSplitOwnScope:
    """Fase 2: con SOLO `helpdesk.tickets.api.split.own` (roles `tech_desarrollo`
    / `tech_soporte` en el DML real), el técnico solo puede partir un ticket
    asignado A ÉL o sin asignar en la cola de SU equipo. El equipo sale de sus
    ROLES en helpdesk (`user_roles_in_app`), no del JWT (D17 del spec)."""

    def test_technician_splits_own_assigned_ticket(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tks_dept_own_assigned")
        requester = _user(db_session, "ReqOwnAssigned")
        tech = _user(db_session, "TechOwnAssigned")
        _grant_role_with_perm(db_session, tech, "tech_soporte", [SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-OWNASSIGNED-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_user_id=tech.id,
            requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(tech.id, role=None),
        )
        assert resp.status_code == 201, resp.text

    def test_technician_cannot_split_other_technicians_ticket(self, client, db_session, fake_emit):
        """`.split.own` no es "puedo VER" (los técnicos ven todo el instituto,
        `can_user_view_ticket`) — es "es MÍO". El ticket de otro técnico cae
        en 403 aunque el actor lo pudiera abrir en modo lectura."""
        dept = _dept(db_session, "tks_dept_own_other")
        requester = _user(db_session, "ReqOwnOther")
        tech = _user(db_session, "TechOwnOther")
        other_tech = _user(db_session, "OtherTechOwnOther")
        _grant_role_with_perm(db_session, tech, "tech_soporte", [SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-OWNOTHER-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_user_id=other_tech.id,
            requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(tech.id, role=None),
        )
        assert resp.status_code == 403, resp.text
        assert db_session.query(Ticket).filter_by(split_from_ticket_id=ticket.id).count() == 0
        db_session.refresh(ticket)
        assert ticket.title == "TKS-OWNOTHER-1 - ticket de prueba"

    def test_technician_splits_own_team_queue_ticket(self, client, db_session, fake_emit):
        """Sin técnico asignado pero en la cola de SU equipo (`assigned_to_team`
        == su equipo, resuelto vía rol `tech_soporte` -> 'soporte') también
        cuenta como suyo."""
        dept = _dept(db_session, "tks_dept_team_own")
        requester = _user(db_session, "ReqTeamOwn")
        tech = _user(db_session, "TechTeamOwn")
        _grant_role_with_perm(db_session, tech, "tech_soporte", [SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-TEAMOWN-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_team="soporte",
            requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(tech.id, role=None),
        )
        assert resp.status_code == 201, resp.text

    def test_technician_cannot_split_other_team_queue_ticket(self, client, db_session, fake_emit):
        """La cola de DESARROLLO no es suya aunque esté sin asignar: un técnico
        de soporte no puede partirla."""
        dept = _dept(db_session, "tks_dept_team_other")
        requester = _user(db_session, "ReqTeamOther")
        tech = _user(db_session, "TechTeamOther")
        _grant_role_with_perm(db_session, tech, "tech_soporte", [SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-TEAMOTHER-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_team="desarrollo",
            requester_department_id=dept.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(tech.id, role=None),
        )
        assert resp.status_code == 403, resp.text
        assert db_session.query(Ticket).filter_by(split_from_ticket_id=ticket.id).count() == 0

    def test_technician_nonexistent_ticket_returns_404_not_403(self, client, db_session):
        """Un ticket inexistente debe ser 404, no 403: el chequeo de existencia
        va ANTES que el de pertenencia también en la rama `.split.own` (mismo
        orden que `ticket_service.get_ticket_by_id` sigue para `.split.all`)."""
        tech = _user(db_session, "TechOwn404")
        _grant_role_with_perm(db_session, tech, "tech_soporte", [SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db_session, area="SOPORTE")

        resp = client.post(
            "/api/help-desk/v2/tickets/999999999/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(tech.id, role=None),
        )
        assert resp.status_code == 404, resp.text


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


class TestSplitNotificationCommitFailure:

    def test_notification_commit_failure_rolls_back_and_still_returns_201(
        self, client, db_session, fake_emit, monkeypatch,
    ):
        """Si el `db.commit()` que sigue a `notify_ticket_split` falla (p. ej.
        un error transitorio de BD), el endpoint debe loguearlo, hacer
        `db.rollback()` y responder 201 de todas formas: la división ya la
        comiteó el servicio (primer `commit`, exitoso). Sin el rollback la
        sesión queda con la transacción realmente abortada, y el
        `to_dict(include_relations=True)` que sigue (dispara SELECT de
        relaciones `lazy='dynamic'`, p. ej. `collaborators`) truena con
        `PendingRollbackError` sin nadie que lo atrape -> 500 para una
        división que ya estaba comiteada.

        Se fuerza el fallo del SEGUNDO `commit` (el del endpoint) con un
        statement roto de verdad (`SELECT 1/0`) en la MISMA transacción —
        deja la transacción realmente abortada, igual que un commit fallido
        de Postgres de verdad, no solo una excepción de Python fabricada. El
        PRIMER `commit` (el del servicio) pasa normal.
        """
        dept = _dept(db_session, "tks_dept_notiffail")
        requester = _user(db_session, "ReqNotifFail")
        admin_actor = _user(db_session, "AdminNotifFailActor")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TKS-NOTIFFAIL-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        real_commit = db_session.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            if calls["n"] == 1:
                # commit del SERVICIO (ticket_split_service.split_ticket): pasa normal.
                return real_commit()
            # commit del ENDPOINT tras notify_ticket_split: falla de verdad y
            # aborta la transacción real de Postgres, como un error transitorio.
            return db_session.execute(text("SELECT 1/0"))

        monkeypatch.setattr(db_session, "commit", flaky_commit)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/split",
            json={
                "original": _part(category, title="Cuenta de Moodle"),
                "parts": [_part(category, title="Cuenta de correo institucional")],
            },
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["data"]["tickets"]) == 1
        new_number = body["data"]["tickets"][0]["ticket_number"]

        # El split en sí (comiteado por el PRIMER commit, exitoso) sigue ahí.
        persisted = db_session.query(Ticket).filter_by(ticket_number=new_number).first()
        assert persisted is not None

        # El aviso (flush dentro de la transacción que el SEGUNDO commit
        # abortó) se deshizo con el rollback: cero filas.
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

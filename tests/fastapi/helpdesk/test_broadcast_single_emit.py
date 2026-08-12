"""
Verifica "exactamente un broadcast de socket por evento" tras eliminar el doble
emit (notification_helper + capa API) para assigned / reassigned / self_assigned /
created / status_changed — y la EXCEPCIÓN de comentarios, donde el broadcast vive
a propósito en `notification_helper.notify_comment_added`: `api/ticket_comments.py`
(el caller async, CON pareja) dejó de emitirlo; `api/comments.py` (el caller SYNC,
SIN pareja, no puede await-earlo) sigue dependiendo del helper.

Antes del fix: cada uno de esos 5 eventos se emitía dos veces — una vez desde la
capa API (await-eada) y otra desde `notification_helper` vía `_async_broadcast`
(fire-and-forget). `broadcast_ticket_assigned` sola abanica a 5 salas, así que una
asignación producía 10 emits en vez de 5.

Estrategia: monkeypatchear `itcj2.sockets.helpdesk.sio.emit` con un AsyncMock y
comparar las salas (`to=`) contra las que arma el propio módulo con sus helpers
`_tech_room`/`_ticket_room`/etc. — el test no hardcodea números mágicos de sala,
así que sigue siendo válido si el abanico de salas cambia a futuro; lo que
protege es que cada sala reciba el evento UNA sola vez, no dos.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.services import assignment_service
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.sockets import helpdesk as hd_sockets

from ._catalog import (
    ensure_helpdesk_category,
    ensure_helpdesk_priority,
    ensure_status_transition,
)

TODAY = date.today()


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, `get_db` apunta a la sesión transaccional del
    test (mismo patrón que test_ticket_guards_scope.py)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def fake_emit(monkeypatch):
    """Reemplaza sio.emit por un AsyncMock: captura cada emit sin tocar Redis de
    verdad. Los broadcast_* de itcj2/sockets/helpdesk.py llaman a `sio.emit`
    directamente (mismo objeto `sio` importado a nivel de módulo), así que
    parchear el atributo alcanza a todos ellos."""
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
    """Rol DIRECTO del usuario en helpdesk (`UserAppRole`) — necesario para los
    checks que leen `user_roles_in_app`/`cached_roles` de BD (p.ej. que el
    técnico asignado tenga el rol del área, o `require_roles` en self-assign),
    que el bypass de JWT `role: admin` NO cubre."""
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


# ─────────────────────────────────── tests ────────────────────────────────────

class TestAssignSingleBroadcast:
    def test_assign_hits_each_room_exactly_once(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tbs_dept_assign")
        requester = _user(db_session, "ReqAssign")
        tech = _user(db_session, "TechAssign")
        # Actor real en core_users: Assignment.assigned_by_id es FK NOT NULL —
        # un id inventado (p.ej. 999) revienta con IntegrityError al insertar.
        admin_actor = _user(db_session, "AdminActor")
        _grant_role(db_session, tech, "tech_soporte")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TBS-ASSIGN-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        resp = client.post(
            "/api/help-desk/v2/assignments",
            json={"ticket_id": ticket.id, "assigned_to_user_id": tech.id},
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        rooms = _emitted_rooms(fake_emit, "ticket_assigned")
        expected = {
            hd_sockets._tech_room(tech.id),
            hd_sockets._ticket_room(ticket.id),
            hd_sockets._team_room("soporte"),
            hd_sockets._dept_room(dept.id),
            hd_sockets._admin_room(),
        }
        # Antes del fix esto era 10 emits (5 salas x 2): assert de longitud +
        # comparación exacta de conjuntos cubre tanto "no duplicados" como "no
        # faltan salas".
        assert sorted(rooms) == sorted(expected), rooms

        # actor_id viaja en el payload — el cliente lo usa para ignorar el eco
        # de su propia acción (causa 3 del bug reportado).
        for c in fake_emit.call_args_list:
            if c.args[0] == "ticket_assigned":
                assert c.args[1]["actor_id"] == admin_actor.id


class TestReassignSingleBroadcast:
    def test_reassign_hits_each_room_exactly_once(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tbs_dept_reassign")
        requester = _user(db_session, "ReqReassign")
        tech1 = _user(db_session, "Tech1Reassign")
        tech2 = _user(db_session, "Tech2Reassign")
        admin_actor = _user(db_session, "AdminActorReassign")
        _grant_role(db_session, tech1, "tech_soporte")
        _grant_role(db_session, tech2, "tech_soporte")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TBS-REASSIGN-1", requester, category,
            area="SOPORTE", requester_department_id=dept.id,
        )

        # Asignación inicial vía SERVICE directo (sin API, sin tocar fake_emit)
        # para dejar el ticket en estado ASSIGNED antes de reasignar.
        assignment_service.assign_ticket(
            db_session, ticket_id=ticket.id, assigned_by_id=requester.id,
            assigned_to_user_id=tech1.id,
        )

        resp = client.post(
            f"/api/help-desk/v2/assignments/{ticket.id}/reassign",
            json={"assigned_to_user_id": tech2.id, "reason": "reasignación de prueba"},
            headers=_jwt_cookie(admin_actor.id, role="admin"),
        )
        assert resp.status_code == 200, resp.text

        rooms = _emitted_rooms(fake_emit, "ticket_reassigned")
        expected = {
            hd_sockets._tech_room(tech2.id),
            hd_sockets._ticket_room(ticket.id),
            hd_sockets._team_room("soporte"),
            hd_sockets._dept_room(dept.id),
            hd_sockets._admin_room(),
        }
        assert sorted(rooms) == sorted(expected), rooms


class TestSelfAssignSingleBroadcast:
    def test_self_assign_hits_each_room_exactly_once(self, client, db_session, fake_emit):
        requester = _user(db_session, "ReqSelfAssign")
        tech = _user(db_session, "TechSelfAssign")
        _grant_role(db_session, tech, "tech_soporte")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ticket = _ticket(
            db_session, "TBS-SELFASSIGN-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_team="soporte",
        )

        resp = client.post(
            f"/api/help-desk/v2/assignments/{ticket.id}/self-assign",
            headers=_jwt_cookie(tech.id),
        )
        assert resp.status_code == 200, resp.text

        rooms = _emitted_rooms(fake_emit, "ticket_self_assigned")
        expected = {
            hd_sockets._team_room("soporte"),
            hd_sockets._ticket_room(ticket.id),
            hd_sockets._admin_room(),
        }
        assert sorted(rooms) == sorted(expected), rooms


class TestCreatedSingleBroadcast:
    def test_create_ticket_hits_each_room_exactly_once(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tbs_dept_created")
        requester = _user(db_session, "ReqCreated")

        # Puesto activo para que create_ticket selle requester_department_id
        # (mismo patrón que test_create_ticket_department.py).
        pos = Position(code="tbs_pos_created", title="x", department_id=dept.id,
                        is_active=True, allows_multiple=True)
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)
        db_session.add(UserPosition(user_id=requester.id, position_id=pos.id,
                                     start_date=TODAY - timedelta(days=1), is_active=True))
        db_session.commit()

        category = ensure_helpdesk_category(db_session, code="tbs_cat_created", area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")

        resp = client.post(
            "/api/help-desk/v2/tickets",
            json={
                "area": "SOPORTE",
                "category_id": category.id,
                "title": "Ticket de prueba doble broadcast",
                "description": "Descripción con longitud suficiente para pasar la validación mínima.",
                "priority": "MEDIA",
            },
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        rooms = _emitted_rooms(fake_emit, "ticket_created")
        expected = {
            hd_sockets._team_room("soporte"),
            hd_sockets._dept_room(dept.id),
            hd_sockets._admin_room(),
        }
        assert sorted(rooms) == sorted(expected), rooms


class TestStatusChangedSingleBroadcast:
    def test_start_ticket_hits_each_room_exactly_once(self, client, db_session, fake_emit):
        dept = _dept(db_session, "tbs_dept_start")
        requester = _user(db_session, "ReqStart")
        tech = _user(db_session, "TechStart")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ensure_helpdesk_priority(db_session, "MEDIA")
        ticket = _ticket(
            db_session, "TBS-START-1", requester, category,
            area="SOPORTE", status="ASSIGNED", assigned_to_user_id=tech.id,
            requester_department_id=dept.id,
        )

        # El catalogo de estados vive en BD y get_status_codes NO tiene fallback
        # al dict literal: con helpdesk_ticket_status vacia (CI) cualquier cambio
        # responde 400 "Estado invalido". En dev la tabla la carga database/DML/,
        # que es gitignored y nunca llega al checkout del pipeline.
        ensure_status_transition(db_session, "ASSIGNED", "IN_PROGRESS")

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/start",
            headers=_jwt_cookie(tech.id, role="admin"),
        )
        assert resp.status_code == 200, resp.text

        rooms = _emitted_rooms(fake_emit, "ticket_status_changed")
        expected = {
            hd_sockets._ticket_room(ticket.id),
            hd_sockets._tech_room(tech.id),
            hd_sockets._team_room("soporte"),
            hd_sockets._dept_room(dept.id),
            hd_sockets._admin_room(),
        }
        assert sorted(rooms) == sorted(expected), rooms


class TestCommentBroadcastException:
    """`api/comments.py::create_comment` (SYNC, sin pareja async) sigue
    emitiendo `ticket_comment_added` a través de `notify_comment_added` — es la
    EXCEPCIÓN a la regla de "un solo broadcast en la capa API": aquí el
    broadcast vive a propósito en el helper porque este caller no puede
    await-earlo (endpoint sync)."""

    def test_sync_comment_endpoint_still_broadcasts(self, client, db_session, monkeypatch):
        mock_broadcast = AsyncMock()
        # `notify_comment_added` hace `from itcj2.sockets.helpdesk import
        # broadcast_ticket_comment_added` DENTRO de la función — import local,
        # resuelto en cada llamada — así que parchear el nombre en el módulo
        # `itcj2.sockets.helpdesk` es lo único necesario.
        monkeypatch.setattr(hd_sockets, "broadcast_ticket_comment_added", mock_broadcast)

        requester = _user(db_session, "ReqComment")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ticket = _ticket(db_session, "TBS-COMMENT-1", requester, category, area="SOPORTE")

        resp = client.post(
            f"/api/help-desk/v2/comments/ticket/{ticket.id}",
            json={"content": "Comentario de prueba suficientemente largo", "is_internal": False},
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        mock_broadcast.assert_called_once()
        _, kwargs = mock_broadcast.call_args
        assert kwargs.get("actor_id") == requester.id

    def test_async_comment_endpoint_does_not_double_broadcast(self, client, db_session, monkeypatch):
        """`api/ticket_comments.py::add_comment` (async, CON pareja) ya NO debe
        emitir por su cuenta — solo lo hace `notify_comment_added` (helper).

        `notify_comment_added` dispara el broadcast fire-and-forget (`_async_broadcast`
        + `loop.create_task`), así que parchear `sio.emit` sería una carrera contra
        el scheduler. Parcheamos `broadcast_ticket_comment_added` en su lugar: la
        llamada que construye la coroutine ocurre de forma SÍNCRONA en el momento
        en que cada caller la invoca (await-eada o no), así que `call_count` es
        determinista — bajo el bug viejo (los dos callers activos) esto daría 2,
        no 1.
        """
        mock_broadcast = AsyncMock()
        monkeypatch.setattr(hd_sockets, "broadcast_ticket_comment_added", mock_broadcast)

        requester = _user(db_session, "ReqComment2")
        category = ensure_helpdesk_category(db_session, area="SOPORTE")
        ticket = _ticket(db_session, "TBS-COMMENT-2", requester, category, area="SOPORTE")

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/comments",
            json={"content": "Otro comentario de prueba con longitud suficiente"},
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 201, resp.text

        mock_broadcast.assert_called_once()

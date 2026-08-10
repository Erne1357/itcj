"""`GET /api/help-desk/v2/stats/tickets/{id}/summary` — resumen para el modal
de enlace desde stats/analysis (ver comentarios de la tarjeta de calificación,
filas de outliers/clustering).

Reutiliza el mismo scope que el resto de `/stats/*` (`_resolve_stats_scope`):
  - acceso total (admin global o `helpdesk.stats.api.read`) -> ve cualquier
    ticket, sin importar depto. OJO: el resolver devuelve `dept_ids=set()`
    (VACÍO) para acceso total — hay que probar que el endpoint no lo confunde
    con "sin scope" y rechaza al admin.
  - solo `.subtree` -> acotado al subárbol del departamento que otorga la app;
    fail-closed si el ticket cae fuera (incluye tickets sin depto).

Cubre: 200 dentro de scope, 200 admin global (caso set() vacío), 403 fuera de
scope, 403 con ticket sin departamento resoluble, 404 inexistente, que basten
los permisos de stats (sin ningún `helpdesk.tickets.api.read.*`), y que el
payload traiga todas las claves declaradas.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

API = "/api/help-desk/v2/stats"
SUBTREE = "helpdesk.stats.api.read.subtree"
FULL = "helpdesk.stats.api.read"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jwt_cookie(user_id: int, role=None) -> dict:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": role, "cn": None, "name": "Test",
        "iat": now, "exp": now + 24 * 3600,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _helpdesk(db) -> App:
    app = db.query(App).filter_by(key="helpdesk").first()
    assert app is not None, "helpdesk app debe existir en la BD dev"
    return app


def _perm(db, app, code) -> Permission:
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _dept(db, code, parent_id=None) -> Department:
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db) -> Category:
    c = db.query(Category).filter_by(code="tksum_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="tksum_cat", name="tksum", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department, **extra) -> Ticket:
    fields = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id if department else None,
        area="SOPORTE",
        category_id=_category(db).id,
        priority="MEDIA",
        title=f"Título {number}",
        description="x" * 10,
        status="PENDING",
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    fields.update(extra)
    t = Ticket(**fields)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _grant(db, user, department, *, code) -> Position:
    """Ancla `user` en `department` con un puesto que otorga `code` (1 o varios)."""
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    pos = Position(code=f"tksumpos_{user.id}", title="Jefe",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    from datetime import date, timedelta
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=1),
        is_active=True,
    ))
    for c in codes:
        perm = _perm(db, app, c)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _tree(db, prefix):
    """root -> mine -> child ; root -> sibling (rama hermana, NO descendiente de mine)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


# ───────────────────────────────────── tests ─────────────────────────────────────

class TestWithinScope:

    def test_200_for_department_head_own_department(self, client, db_session):
        _, mine, _, _ = _tree(db_session, "tsm1")
        boss = _user(db_session, "Boss1")
        stranger = _user(db_session, "Stranger1")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM1-1", stranger, mine)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["id"] == t.id

    def test_200_for_child_department_in_subtree(self, client, db_session):
        _, mine, child, _ = _tree(db_session, "tsm2")
        boss = _user(db_session, "Boss2")
        stranger = _user(db_session, "Stranger2")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM2-1", stranger, child)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200

    def test_stats_permissions_alone_are_enough_no_ticket_perms_needed(self, client, db_session):
        """El endpoint solo exige permisos de `stats`, NUNCA
        `helpdesk.tickets.api.read.*` — a diferencia de `GET /tickets/{id}`."""
        _, mine, _, _ = _tree(db_session, "tsm3")
        boss = _user(db_session, "Boss3")
        stranger = _user(db_session, "Stranger3")
        # SOLO el permiso de stats. Nada de tickets.api.read.*.
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM3-1", stranger, mine)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200


class TestGlobalAdminEmptySetCase:

    def test_200_for_global_admin_regardless_of_department(self, client, db_session):
        """`_resolve_stats_scope` devuelve `(True, set())` para admin global: el
        conjunto vacío NO debe interpretarse como fail-closed."""
        _, mine, _, sibling = _tree(db_session, "tsm4")
        stranger = _user(db_session, "Stranger4")
        admin = _user(db_session, "Admin4")
        t = _ticket(db_session, "TSM4-1", stranger, sibling)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(admin.id, role="admin"))
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == t.id

    def test_200_for_full_stats_permission_regardless_of_department(self, client, db_session):
        _, mine, _, sibling = _tree(db_session, "tsm5")
        boss = _user(db_session, "Boss5")
        stranger = _user(db_session, "Stranger5")
        # El puesto vive en `mine`, pero `.read` (acceso total) no se acota
        # por procedencia: debe ver un ticket de la rama hermana también.
        _grant(db_session, boss, mine, code=FULL)
        t = _ticket(db_session, "TSM5-1", stranger, sibling)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200


class TestOutsideScope:

    def test_403_for_sibling_branch(self, client, db_session):
        _, mine, _, sibling = _tree(db_session, "tsm6")
        boss = _user(db_session, "Boss6")
        stranger = _user(db_session, "Stranger6")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM6-1", stranger, sibling)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 403
        assert resp.json()["error"]["error"] == "forbidden"

    def test_403_when_ticket_has_no_department_and_user_is_scoped(self, client, db_session):
        """Fail-closed: un ticket sin `requester_department_id` no autoriza a
        nadie acotado por subárbol, aunque su dept_ids no esté vacío."""
        _, mine, _, _ = _tree(db_session, "tsm7")
        boss = _user(db_session, "Boss7")
        stranger = _user(db_session, "Stranger7")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM7-1", stranger, None)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 403


class TestNotFound:

    def test_404_for_missing_ticket(self, client, db_session):
        admin = _user(db_session, "Admin8")
        resp = client.get(f"{API}/tickets/999999999/summary", headers=_jwt_cookie(admin.id, role="admin"))
        assert resp.status_code == 404
        assert resp.json()["error"]["error"] == "not_found"


class TestPayloadShape:

    def test_all_declared_keys_present(self, client, db_session):
        _, mine, _, _ = _tree(db_session, "tsm9")
        boss = _user(db_session, "Boss9")
        requester = _user(db_session, "Requester9")
        tech = _user(db_session, "Tech9")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(
            db_session, "TSM9-1", requester, mine,
            assigned_to_user_id=tech.id,
            status="CLOSED",
            time_invested_minutes=90,
            rating_attention=5,
            rating_speed=4,
            rating_comment="Muy buena atención",
        )

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        data = resp.json()["data"]

        expected_keys = {
            "id", "ticket_number", "title", "description", "status", "priority",
            "area", "category_name", "requester_name", "assigned_to_name",
            "department_name", "created_at", "resolved_at", "resolution_hours",
            "time_invested_hours", "rating_attention", "rating_speed", "rating_comment",
        }
        assert expected_keys == set(data.keys())

        assert data["ticket_number"] == "TSM9-1"
        assert data["requester_name"] == requester.full_name
        assert data["assigned_to_name"] == tech.full_name
        assert data["department_name"] == mine.name
        assert data["category_name"] == "tksum"
        assert data["time_invested_hours"] == 1.5
        assert data["rating_attention"] == 5
        assert data["rating_speed"] == 4
        assert data["rating_comment"] == "Muy buena atención"

    def test_description_is_truncated_to_400_chars(self, client, db_session):
        _, mine, _, _ = _tree(db_session, "tsm10")
        boss = _user(db_session, "Boss10")
        requester = _user(db_session, "Requester10")
        _grant(db_session, boss, mine, code=SUBTREE)
        t = _ticket(db_session, "TSM10-1", requester, mine, description="a" * 900)

        resp = client.get(f"{API}/tickets/{t.id}/summary", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        desc = resp.json()["data"]["description"]
        assert len(desc) == 401  # 400 chars + el carácter de truncado "…"
        assert desc.endswith("…")

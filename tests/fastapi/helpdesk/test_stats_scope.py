"""Scope por subárbol (org-scoped authz) en `/api/help-desk/v2/stats/*`.

Hoy `/stats/*` está limitado a `helpdesk.stats.api.read` (admin + secretaría de
centro de cómputo). Se agregó `helpdesk.stats.api.read.subtree` (y su análogo de
página `helpdesk.stats.page.list.subtree`), asignado al rol `department_head`:
el jefe de departamento debe ver las estadísticas de SU SUBÁRBOL y NUNCA las
globales — nunca "sin filtro" cuando no tiene el permiso de acceso total.

Cubre:
  (a) con SOLO `.subtree`, los agregados cuentan el propio departamento y su
      sub-departamento, pero NO la rama hermana ni el padre.
  (b) con `helpdesk.stats.api.read` (acceso total), cuenta TODOS los
      departamentos, sin importar el subárbol.
  (c) sin ningún permiso de stats, el resolver de scope es fail-closed: NUNCA
      "sin filtro" (probado directo contra `_resolve_stats_scope`, no vía
      HTTP, porque el guard `require_perms` ya bloquearía con 403 antes de
      llegar al cuerpo — este test fija el contrato interno para cualquier
      otro consumidor futuro del helper).
  (d) `/stats/department/{id}` de un sub-departamento propio NO da 403 (el
      igualitario viejo lo negaba); el de otra rama SÍ.
  (e) un puesto vencido (fila con `is_active=True` pero `end_date` pasado) NO
      autoriza — ni por rol `department_head` ni por scope de departamento.
"""
from datetime import date, timedelta
from uuid import uuid4

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
from itcj2.core.models.position import Position, PositionAppPerm, PositionAppRole, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

API = "/api/help-desk/v2/stats"
SUBTREE = "helpdesk.stats.api.read.subtree"
FULL = "helpdesk.stats.api.read"
OWN_TICKETS = "helpdesk.tickets.api.read.own"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, pero `get_db` apunta a la sesión transaccional
    de Postgres del test (mismo patrón que `db_session`: rollback al final)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jwt_cookie(user_id: int) -> dict:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": None, "cn": None, "name": "Test",
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


def _role(db, name) -> Role:
    r = db.query(Role).filter_by(name=name).first()
    if not r:
        r = Role(name=name)
        db.add(r)
        db.commit()
        db.refresh(r)
    return r


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
    c = db.query(Category).filter_by(code="sts_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="sts_cat", name="sts", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department) -> Ticket:
    t = Ticket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        area="SOPORTE",
        category_id=_category(db).id,
        priority="MEDIA",
        title=number,
        description="x",
        status="PENDING",
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _grant(db, user, department, *, code, start_date=None, end_date=None) -> Position:
    """Ancla `user` en `department` con un puesto que otorga `code` (1 o varios)."""
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    pos = Position(code=f"stspos_{user.id}_{uuid4().hex[:8]}", title="Jefe",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=start_date or (date.today() - timedelta(days=1)),
        end_date=end_date,
        is_active=True,
    ))
    for c in codes:
        perm = _perm(db, app, c)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _grant_head(db, user, department, *, code, start_date=None, end_date=None) -> Position:
    """Como `_grant`, pero además otorga el ROL `department_head` (necesario
    para `/stats/department/{id}`, que gatea por rol además del permiso)."""
    pos = _grant(db, user, department, code=code, start_date=start_date, end_date=end_date)
    app = _helpdesk(db)
    role = _role(db, "department_head")
    db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db.commit()
    return pos


def _tree(db, prefix):
    """root -> mine -> child ; root -> sibling (rama hermana, NO descendiente de mine)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


# ───────────────────────────── (a) solo .subtree ─────────────────────────────

class TestSubtreeScope:

    def test_by_department_counts_own_and_child_not_sibling_or_parent(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sts1")
        boss = _user(db_session, "Boss1")
        stranger = _user(db_session, "Stranger1")
        _grant(db_session, boss, mine, code=SUBTREE)

        _ticket(db_session, "STS1-MINE", stranger, mine)
        _ticket(db_session, "STS1-CHILD", stranger, child)
        _ticket(db_session, "STS1-SIB", stranger, sibling)
        _ticket(db_session, "STS1-ROOT", stranger, root)

        resp = client.get(f"{API}/by-department", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        rows = {r["department_id"]: r for r in resp.json()["data"]}

        assert rows[mine.id]["total"] == 1
        assert rows[child.id]["total"] == 1
        assert sibling.id not in rows
        assert root.id not in rows

    def test_global_total_matches_subtree_only(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sts1b")
        boss = _user(db_session, "Boss1b")
        stranger = _user(db_session, "Stranger1b")
        _grant(db_session, boss, mine, code=SUBTREE)

        _ticket(db_session, "STS1B-MINE", stranger, mine)
        _ticket(db_session, "STS1B-CHILD", stranger, child)
        _ticket(db_session, "STS1B-SIB", stranger, sibling)
        _ticket(db_session, "STS1B-ROOT", stranger, root)

        resp = client.get(f"{API}/global", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 2


# ─────────────────────────── (b) acceso total (.read) ───────────────────────────

class TestFullAccess:

    def test_by_department_counts_every_branch(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sts2")
        boss = _user(db_session, "Boss2")
        stranger = _user(db_session, "Stranger2")
        # El depto del puesto es irrelevante para el acceso total: `.read` no
        # se acota por procedencia.
        _grant(db_session, boss, mine, code=FULL)

        _ticket(db_session, "STS2-MINE", stranger, mine)
        _ticket(db_session, "STS2-CHILD", stranger, child)
        _ticket(db_session, "STS2-SIB", stranger, sibling)
        _ticket(db_session, "STS2-ROOT", stranger, root)

        resp = client.get(f"{API}/by-department", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        rows = {r["department_id"]: r for r in resp.json()["data"]}

        assert rows[mine.id]["total"] == 1
        assert rows[child.id]["total"] == 1
        assert rows[sibling.id]["total"] == 1
        assert rows[root.id]["total"] == 1


# ─────────────────────── (c) sin permiso de stats: fail-closed ───────────────────────

class TestFailClosedResolver:

    def test_no_stats_permission_resolves_to_empty_scope_never_unfiltered(self, db_session):
        from itcj2.apps.helpdesk.api.stats import _resolve_stats_scope

        plain = _user(db_session, "Plain3")
        # Tiene ALGO en helpdesk (acceso a la app, un permiso ajeno) pero NADA
        # de stats — el resolver no debe confundir "tiene la app" con "ve todo".
        _grant(db_session, plain, _dept(db_session, "sts3_dept"), code=OWN_TICKETS)

        user = {"sub": str(plain.id), "role": None}
        has_full, dept_ids = _resolve_stats_scope(db_session, user)

        assert has_full is False
        assert dept_ids == set()


# ───────────────────── (d) /stats/department/{id}: subárbol, no igualdad ─────────────────────

class TestDepartmentEndpointSubtree:

    def test_child_of_own_department_is_not_403_but_sibling_is(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sts4")
        boss = _user(db_session, "Boss4")
        _grant_head(db_session, boss, mine, code=[SUBTREE, OWN_TICKETS])

        resp_child = client.get(f"{API}/department/{child.id}", headers=_jwt_cookie(boss.id))
        assert resp_child.status_code == 200

        resp_sibling = client.get(f"{API}/department/{sibling.id}", headers=_jwt_cookie(boss.id))
        assert resp_sibling.status_code == 403


# ───────────────────── (e) puesto vencido no autoriza ─────────────────────

class TestExpiredPositionDoesNotAuthorize:

    def test_expired_position_denied_current_position_allowed(self, client, db_session):
        old_dept = _dept(db_session, "sts5_old")
        mine = _dept(db_session, "sts5_mine")
        boss = _user(db_session, "Boss5")

        # Puesto VENCIDO: is_active=True en la fila (nunca se desactivó a
        # mano), pero end_date ya pasó. El resolver ad-hoc viejo (solo
        # `is_active=True`, sin ventana de fechas ni ORDER BY) podía seguir
        # devolviéndolo; el canónico debe excluirlo.
        _grant_head(
            db_session, boss, old_dept,
            code=[SUBTREE, OWN_TICKETS],
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() - timedelta(days=30),
        )
        # Puesto VIGENTE actual, en otro departamento.
        _grant_head(db_session, boss, mine, code=[SUBTREE, OWN_TICKETS])

        resp_old = client.get(f"{API}/department/{old_dept.id}", headers=_jwt_cookie(boss.id))
        assert resp_old.status_code == 403

        resp_mine = client.get(f"{API}/department/{mine.id}", headers=_jwt_cookie(boss.id))
        assert resp_mine.status_code == 200

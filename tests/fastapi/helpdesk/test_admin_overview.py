"""Tests de `AdminDashboardService` / `GET /api/help-desk/v2/dashboard/admin-overview`
(rediseño de `/help-desk/admin/home`, WS5).

Reusa exactamente los mismos resolvers de scope que el resto del app:
  - Tickets: `_resolve_stats_scope` (`api/stats.py`), igual que `/stats/*`.
  - Inventario: `visible_department_ids` (`utils/inventory_access.py`), igual
    que los widgets de `api/inventory/dashboard.py`.

Cubre:
  (a) los conteos de tickets e inventario respetan el subárbol visible del
      usuario (no cuentan la rama hermana).
  (b) sin ningún permiso de scope resoluble (solo `helpdesk.dashboard.admin`),
      el endpoint responde 200 con TODOS los conteos en 0 — nunca 403, nunca
      "todos" (fail-closed).
  (c) el contexto que arma la página (`_query_admin_overview_ctx`) también cae
      en 0 sin alcance resoluble, así que `/help-desk/admin/home` sigue
      renderizando (200) en vez de tronar.
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_retirement_request import (
    InventoryRetirementRequest,
    InventoryRetirementRequestItem,
)
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

API = "/api/help-desk/v2/dashboard/admin-overview"

DASHBOARD_ADMIN = "helpdesk.dashboard.admin"
STATS_SUBTREE = "helpdesk.stats.api.read.subtree"
INVENTORY_SUBTREE = "helpdesk.inventory.api.read.subtree"
RETIREMENT_SUBTREE = "helpdesk.inventory.retirement.api.read.subtree"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
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
    c = db.query(Category).filter_by(code="ov_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="ov_cat", name="ov_cat", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _inv_category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="ov_inv_cat").first()
    if not c:
        c = InventoryCategory(code="ov_inv_cat", name="ov_inv_cat", inventory_prefix="OV", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department, status="PENDING") -> Ticket:
    t = Ticket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        area="SOPORTE",
        category_id=_category(db).id,
        priority="MEDIA",
        title=number,
        description="x",
        status=status,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _item(db, number, department, *, last_verified_at=None, warranty_expiration=None) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_inv_category(db).id,
        department_id=department.id,
        status="ACTIVE",
        is_active=True,
        registered_by_id=1,
        last_verified_at=last_verified_at,
        warranty_expiration=warranty_expiration,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _retirement_request(db, folio, requester, item, status) -> InventoryRetirementRequest:
    req = InventoryRetirementRequest(
        folio=folio, status=status, reason="baja de prueba", requested_by_id=requester.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    db.add(InventoryRetirementRequestItem(request_id=req.id, item_id=item.id))
    db.commit()
    return req


def _grant(db, user, department, *, code) -> Position:
    """Ancla `user` en `department` con un puesto que otorga `code` (1 o varios)."""
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    pos = Position(code=f"ovpos_{user.id}_{uuid4().hex[:8]}", title="Jefe",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=1),
        end_date=None,
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


# ───────────────────────── (a) scope de subárbol respetado ─────────────────────────

class TestSubtreeScopeRespected:

    def test_ticket_and_inventory_counts_only_cover_own_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "ov1")
        boss = _user(db_session, "Boss1")
        stranger = _user(db_session, "Stranger1")
        _grant(db_session, boss, mine, code=[
            DASHBOARD_ADMIN, STATS_SUBTREE, INVENTORY_SUBTREE, RETIREMENT_SUBTREE,
        ])

        # Tickets sin asignar (PENDING): 2 en mine, 1 en child, 1 en sibling (fuera).
        _ticket(db_session, "OV1-M1", stranger, mine)
        _ticket(db_session, "OV1-M2", stranger, mine)
        _ticket(db_session, "OV1-C1", stranger, child)
        _ticket(db_session, "OV1-S1", stranger, sibling)

        # Equipos "críticos" (>90 días sin verificar): 1 en mine, 1 en child, 1 en sibling (fuera).
        old = datetime.now() - timedelta(days=120)
        _item(db_session, "OV1-EQ-M", mine, last_verified_at=old)
        _item(db_session, "OV1-EQ-C", child, last_verified_at=old)
        _item(db_session, "OV1-EQ-S", sibling, last_verified_at=old)

        # Garantías por vencer (<=30 días): 1 en mine, 1 en sibling (fuera).
        soon = date.today() + timedelta(days=10)
        _item(db_session, "OV1-WR-M", mine, warranty_expiration=soon)
        _item(db_session, "OV1-WR-S", sibling, warranty_expiration=soon)

        # Bajas pendientes: 1 con equipo en mine, 1 con equipo en sibling (fuera,
        # y solicitada por un tercero para no colar por "propia").
        item_mine = _item(db_session, "OV1-RT-M", mine)
        item_sibling = _item(db_session, "OV1-RT-S", sibling)
        _retirement_request(db_session, "OV1-BAJA-M", stranger, item_mine, "AWAITING_COMP_CENTER")
        _retirement_request(db_session, "OV1-BAJA-S", stranger, item_sibling, "PENDING")

        resp = client.get(API, headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert data["kpis"]["pending"] == 3
        assert data["kpis"]["total"] == 3

        by_key = {row["key"]: row["count"] for row in data["attention"]}
        assert by_key["unassigned"] == 3
        assert by_key["verification_critical"] == 2
        assert by_key["warranty_expiring"] == 1
        assert by_key["retirement_pending"] == 1

        recent_numbers = {t["ticket_number"] for t in data["recent_tickets"]}
        assert "OV1-S1" not in recent_numbers
        assert {"OV1-M1", "OV1-M2", "OV1-C1"} <= recent_numbers


# ───────────────────── (b) fail-closed sin alcance resoluble (API) ─────────────────────

class TestFailClosedApi:

    def test_only_dashboard_permission_returns_200_with_zero_counts(self, client, db_session):
        dept = _dept(db_session, "ov2_dept")
        stranger = _user(db_session, "Stranger2")
        plain = _user(db_session, "Plain2")
        # Solo el permiso de la página/endpoint — nada de scope de stats ni de
        # inventario. NO debe ver "todo".
        _grant(db_session, plain, dept, code=DASHBOARD_ADMIN)

        # Un ticket y un equipo en SU MISMO departamento — ninguno debe contarse:
        # el fail-closed es sobre el permiso, no sobre "no hay datos".
        _ticket(db_session, "OV2-T1", stranger, dept)
        _item(db_session, "OV2-EQ1", dept, last_verified_at=datetime.now() - timedelta(days=200))

        resp = client.get(API, headers=_jwt_cookie(plain.id))
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert data["kpis"]["total"] == 0
        assert data["kpis"]["pending"] == 0
        assert data["kpis"]["created_today"] == 0
        assert data["recent_tickets"] == []
        assert data["recent_inventory_events"] == []
        for row in data["attention"]:
            assert row["count"] == 0

    def test_no_helpdesk_permission_at_all_is_403(self, client, db_session):
        nadie = _user(db_session, "Nadie2")
        resp = client.get(API, headers=_jwt_cookie(nadie.id))
        assert resp.status_code == 403


# ───────────────── (c) el contexto de página cae en 0 (no truena) ─────────────────

class TestPageContextFailsClosed:

    def test_query_admin_overview_ctx_zero_without_scope(self, db_session, monkeypatch):
        from itcj2.apps.helpdesk.pages import admin as admin_pages

        dept = _dept(db_session, "ov3_dept")
        plain = _user(db_session, "Plain3")
        _grant(db_session, plain, dept, code=DASHBOARD_ADMIN)

        monkeypatch.setattr("itcj2.database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None, raising=False)

        ctx = admin_pages._query_admin_overview_ctx({"sub": str(plain.id), "role": None})

        assert ctx["kpis"]["total"] == 0
        assert ctx["recent_tickets"] == []
        assert all(row["count"] == 0 for row in ctx["attention"])

    def test_home_page_renders_200_with_zero_counts(self, db_session, monkeypatch):
        dept = _dept(db_session, "ov4_dept")
        plain = _user(db_session, "Plain4")
        _grant(db_session, plain, dept, code=DASHBOARD_ADMIN)

        monkeypatch.setattr("itcj2.database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None, raising=False)

        app = create_app()
        app.dependency_overrides[get_db] = lambda: db_session
        with TestClient(app) as c:
            resp = c.get("/help-desk/admin/home", headers=_jwt_cookie(plain.id))
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert 'data-hd-page="admin_home"' in resp.text

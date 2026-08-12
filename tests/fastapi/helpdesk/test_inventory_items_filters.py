"""Filtros nuevos de inventario/items (registro/garantía/verificación/marca/
mantenimiento/orden) — GET /api/help-desk/v2/inventory/items (JSON) y la
página GET /help-desk/inventory/items comparten EXACTAMENTE la misma lógica de
filtrado (`_apply_item_common_filters` / `_apply_item_sort` en
itcj2/apps/helpdesk/api/inventory/items.py), así que ambos caminos deben
coincidir en resultados para el mismo query string.

También cubre: los nuevos estados RETIRED/PENDING_ASSIGNMENT en el filtro de
estado, y que `?department=` siga intersectando el scope visible (nunca lo
sustituye) tras el refactor que introdujo los helpers compartidos.
"""
from datetime import date, datetime, timedelta

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models import InventoryItem
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_inventory_category

ITEMS_SUBTREE = "helpdesk.inventory.api.read.subtree"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, `get_db` apunta a la sesión transaccional del
    test (mismo patrón que `tests/fastapi/helpdesk/test_inventory_api_scope.py`)."""
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


def _item(db, number, department, registered_by, **kwargs) -> InventoryItem:
    status = kwargs.pop("status", "ACTIVE")
    it = InventoryItem(
        inventory_number=number,
        category_id=ensure_inventory_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status=status,
        is_active=True,
        **kwargs,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _grant(db, user, department, *, code) -> None:
    """Ancla `user` en `department` con un puesto que otorga `code`."""
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    from uuid import uuid4
    pos = Position(code=f"iflt_{user.id}_{uuid4().hex[:8]}", title="Jefe", department_id=department.id,
                    is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    for c in codes:
        perm = _perm(db, app, c)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _tree(db, prefix):
    """root -> mine -> child ; root -> sibling (rama hermana)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


def _full_access(db, prefix):
    """Departamento AISLADO (recién creado, sin equipos preexistentes) + usuario
    con `.read.subtree` anclado ahí. Deliberadamente NO usa `.read.all`: contra
    la Postgres real de dev (harness de `tests/fastapi/conftest.py`) un acceso
    verdaderamente global vería TODO el inventario ya sembrado (miles de filas
    reales), contaminando cualquier assert de contenido. Anclar en un depto
    nuevo consigue el mismo "ve todo lo que yo cree" sin esa fuga — mismo
    mecanismo que `_grant` en test_inventory_api_scope.py.
    Devuelve (department, user, cookie)."""
    dept = _dept(db, f"{prefix}_dept")
    user = _user(db, f"{prefix}Full")
    _grant(db, user, dept, code=ITEMS_SUBTREE)
    return dept, user, _jwt_cookie(user.id)


# ─────────────────────────────── estado: nuevos valores ───────────────────────────────

class TestStatusOptions:
    def test_page_status_filter_includes_retired_and_pending_assignment(self, client, db_session):
        _, _, cookie = _full_access(db_session, "sto1")
        resp = client.get("/help-desk/inventory/items", headers=cookie)
        assert resp.status_code == 200
        assert 'value="RETIRED"' in resp.text
        assert 'value="PENDING_ASSIGNMENT"' in resp.text


# ─────────────────────────────── reg_start / reg_end ───────────────────────────────

class TestRegisteredAtFilter:
    def test_reg_start_and_reg_end_narrow_to_window(self, client, db_session):
        dept, reg, cookie = _full_access(db_session, "rf1")
        now = datetime.now()
        _item(db_session, "RF1-OLD", dept, reg, registered_at=now - timedelta(days=10))
        mid = _item(db_session, "RF1-MID", dept, reg, registered_at=now - timedelta(days=5))
        _item(db_session, "RF1-NEW", dept, reg, registered_at=now)

        reg_start = (now - timedelta(days=7)).date().isoformat()
        reg_end = (now - timedelta(days=1)).date().isoformat()
        resp = client.get(
            f"/api/help-desk/v2/inventory/items?reg_start={reg_start}&reg_end={reg_end}",
            headers=cookie,
        )
        assert resp.status_code == 200
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"RF1-MID"}


# ─────────────────────────────── warranty ───────────────────────────────

class TestWarrantyFilter:
    def _seed(self, db, prefix):
        dept, reg, cookie = _full_access(db, prefix)
        today = date.today()
        valid = _item(db, f"{prefix}-VALID", dept, reg, warranty_expiration=today + timedelta(days=200))
        expiring = _item(db, f"{prefix}-EXPIRING", dept, reg, warranty_expiration=today + timedelta(days=10))
        expired = _item(db, f"{prefix}-EXPIRED", dept, reg, warranty_expiration=today - timedelta(days=5))
        none_ = _item(db, f"{prefix}-NONE", dept, reg)
        return cookie

    def test_valid(self, client, db_session):
        cookie = self._seed(db_session, "wf1")
        resp = client.get("/api/help-desk/v2/inventory/items?warranty=valid", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"wf1-VALID", "wf1-EXPIRING"}

    def test_expiring(self, client, db_session):
        cookie = self._seed(db_session, "wf2")
        resp = client.get("/api/help-desk/v2/inventory/items?warranty=expiring", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"wf2-EXPIRING"}

    def test_expired(self, client, db_session):
        cookie = self._seed(db_session, "wf3")
        resp = client.get("/api/help-desk/v2/inventory/items?warranty=expired", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"wf3-EXPIRED"}

    def test_none(self, client, db_session):
        cookie = self._seed(db_session, "wf4")
        resp = client.get("/api/help-desk/v2/inventory/items?warranty=none", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"wf4-NONE"}


# ─────────────────────────────── verified ───────────────────────────────

class TestVerifiedFilter:
    def _seed(self, db, prefix):
        dept, reg, cookie = _full_access(db, prefix)
        now = datetime.now()
        _item(db, f"{prefix}-NEVER", dept, reg)
        _item(db, f"{prefix}-RECENT", dept, reg, last_verified_at=now - timedelta(days=5))
        _item(db, f"{prefix}-OUTDATED", dept, reg, last_verified_at=now - timedelta(days=60))
        _item(db, f"{prefix}-CRITICAL", dept, reg, last_verified_at=now - timedelta(days=120))
        return cookie

    def test_never(self, client, db_session):
        cookie = self._seed(db_session, "vf1")
        resp = client.get("/api/help-desk/v2/inventory/items?verified=never", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"vf1-NEVER"}

    def test_recent(self, client, db_session):
        cookie = self._seed(db_session, "vf2")
        resp = client.get("/api/help-desk/v2/inventory/items?verified=recent", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"vf2-RECENT"}

    def test_outdated(self, client, db_session):
        cookie = self._seed(db_session, "vf3")
        resp = client.get("/api/help-desk/v2/inventory/items?verified=outdated", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"vf3-OUTDATED"}

    def test_critical(self, client, db_session):
        cookie = self._seed(db_session, "vf4")
        resp = client.get("/api/help-desk/v2/inventory/items?verified=critical", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"vf4-CRITICAL"}


# ─────────────────────────────── brand ───────────────────────────────

class TestBrandFilter:
    def test_ilike_matches_partial_case_insensitive(self, client, db_session):
        dept, reg, cookie = _full_access(db_session, "bf1")
        _item(db_session, "BF1-DELL", dept, reg, brand="Dell Inspiron")
        _item(db_session, "BF1-HP", dept, reg, brand="HP LaserJet")

        resp = client.get("/api/help-desk/v2/inventory/items?brand=dell", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"BF1-DELL"}


# ─────────────────────────────── maintenance ───────────────────────────────

class TestMaintenanceFilter:
    def _seed(self, db, prefix):
        dept, reg, cookie = _full_access(db, prefix)
        today = date.today()
        _item(db, f"{prefix}-DUE", dept, reg, next_maintenance_date=today - timedelta(days=2))
        _item(db, f"{prefix}-SOON", dept, reg, next_maintenance_date=today + timedelta(days=10))
        _item(db, f"{prefix}-FAR", dept, reg, next_maintenance_date=today + timedelta(days=90))
        _item(db, f"{prefix}-NONE", dept, reg)
        return cookie

    def test_due(self, client, db_session):
        cookie = self._seed(db_session, "mf1")
        resp = client.get("/api/help-desk/v2/inventory/items?maintenance=due", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"mf1-DUE"}

    def test_soon_includes_due(self, client, db_session):
        cookie = self._seed(db_session, "mf2")
        resp = client.get("/api/help-desk/v2/inventory/items?maintenance=soon", headers=cookie)
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"mf2-DUE", "mf2-SOON"}


# ─────────────────────────────── sort ───────────────────────────────

class TestSortVariants:
    def _seed(self, db, prefix):
        dept, reg, cookie = _full_access(db, prefix)
        now = datetime.now()
        today = date.today()
        _item(
            db, f"{prefix}-A", dept, reg,
            registered_at=now - timedelta(days=3),
            warranty_expiration=today + timedelta(days=50),
            last_verified_at=now - timedelta(days=40),
        )
        _item(
            db, f"{prefix}-B", dept, reg,
            registered_at=now - timedelta(days=1),
            warranty_expiration=today + timedelta(days=10),
            last_verified_at=now - timedelta(days=5),
        )
        _item(
            db, f"{prefix}-C", dept, reg,
            registered_at=now - timedelta(days=5),
            warranty_expiration=today + timedelta(days=100),
            last_verified_at=now - timedelta(days=90),
        )
        return dept, cookie

    def _numbers(self, client, cookie, dept, sort):
        qs = f"department_id={dept.id}"
        if sort:
            qs += f"&sort={sort}"
        resp = client.get(f"/api/help-desk/v2/inventory/items?{qs}", headers=cookie)
        assert resp.status_code == 200
        return [i["inventory_number"] for i in resp.json()["data"]]

    def test_default_is_id_asc(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf0")
        assert self._numbers(client, cookie, dept, "") == ["sf0-A", "sf0-B", "sf0-C"]

    def test_recent(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf1")
        assert self._numbers(client, cookie, dept, "recent") == ["sf1-B", "sf1-A", "sf1-C"]

    def test_oldest(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf2")
        assert self._numbers(client, cookie, dept, "oldest") == ["sf2-C", "sf2-A", "sf2-B"]

    def test_number(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf3")
        assert self._numbers(client, cookie, dept, "number") == ["sf3-A", "sf3-B", "sf3-C"]

    def test_warranty_soonest_first(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf4")
        assert self._numbers(client, cookie, dept, "warranty") == ["sf4-B", "sf4-A", "sf4-C"]

    def test_verified_most_overdue_first(self, client, db_session):
        dept, cookie = self._seed(db_session, "sf5")
        assert self._numbers(client, cookie, dept, "verified") == ["sf5-C", "sf5-A", "sf5-B"]


# ─────────────────────────────── scope: department= sigue intersectando ───────────────────────────────

class TestDepartmentScopeStillEnforced:
    """El refactor a helpers compartidos (`_apply_item_common_filters`/
    `_apply_item_sort`) NO debe tocar el scope departamental: `?department=`
    sigue intersectando `visible_department_ids`, nunca lo sustituye."""

    def test_api_department_outside_subtree_returns_empty_even_with_new_filters(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "dso1")
        boss = _user(db_session, "DsoBoss1")
        registrar = _user(db_session, "DsoReg1")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        _item(db_session, "DSO1-SIB", sibling, registrar, brand="Dell")

        resp = client.get(
            f"/api/help-desk/v2/inventory/items?department_id={sibling.id}&brand=dell",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_page_department_outside_subtree_returns_empty_fragment(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "dso2")
        boss = _user(db_session, "DsoBoss2")
        registrar = _user(db_session, "DsoReg2")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        _item(db_session, "DSO2-SIB", sibling, registrar)

        resp = client.get(
            f"/help-desk/inventory/items?department={sibling.id}",
            headers={**_jwt_cookie(boss.id), "HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "DSO2-SIB" not in resp.text


# ─────────────────────────────── paridad página ↔ API ───────────────────────────────

class TestPageApiParity:
    def test_combined_new_filters_match_between_page_and_api(self, client, db_session, monkeypatch):
        # La PÁGINA abre su propia sesión con `SessionLocal()` (pages/inventory.py),
        # una conexión DISTINTA a la del test (`db_session`, Postgres directo con
        # SAVEPOINTs) — sin este parche no vería las filas que este test inserta
        # (no están commiteadas fuera de la transacción del test). Mismo patrón que
        # `tests/fastapi/helpdesk/test_tickets_list_filters.py` (TestPagesGroupsCtx).
        monkeypatch.setattr("itcj2.database.SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None, raising=False)

        dept, reg, cookie = _full_access(db_session, "par1")
        today = date.today()
        _item(db_session, "PAR1-KEEP", dept, reg, brand="Dell Inspiron", warranty_expiration=today + timedelta(days=10))
        _item(db_session, "PAR1-DROP", dept, reg, brand="HP LaserJet", warranty_expiration=today - timedelta(days=5))

        qs = "brand=dell&warranty=expiring"
        api_resp = client.get(f"/api/help-desk/v2/inventory/items?{qs}", headers=cookie)
        assert api_resp.status_code == 200
        api_body = api_resp.json()
        assert {i["inventory_number"] for i in api_body["data"]} == {"PAR1-KEEP"}

        page_resp = client.get(f"/help-desk/inventory/items?{qs}", headers={**cookie, "HX-Request": "true"})
        assert page_resp.status_code == 200
        assert "PAR1-KEEP" in page_resp.text
        assert "PAR1-DROP" not in page_resp.text
        assert f"{api_body['total']} equipo" in page_resp.text

"""Scope por subárbol (org-scoped authz) en widgets/reportes/campañas de inventario.

Sigue al fix de `api/inventory/items.py` (ver test_inventory_api_scope.py): varios
endpoints hermanos seguían anclados al departamento PRIMARIO exacto
(`get_user_department(...).id ==`) o a chequeos por ROL en vez de por PERMISO, en
vez de usar `visible_department_ids` (helpdesk.utils.inventory_access). Un jefe
con `.read.subtree` veía la lista de equipos/campañas de su subárbol pero los
widgets/reportes/detalles hermanos o bien fallaban en 403 para su propio
sub-departamento, o bien (peor) se abrían de más — hacia toda la institución.

Cubre:
  - dashboard.py: quick-stats, status-chart (fail-closed sin puesto vigente),
    category-chart, recent-activity
  - history.py:   item history (403 corregido), /recent (bug tech_desarrollo)
  - stats.py:     GET /department/{id}
  - reports.py:   POST /equipment (sin department_ids no cubre la institución)
  - verification.py: GET /status
  - campaigns.py: GET / (por permiso, no por rol), GET /{id}, /{id}/groups-view
"""
from datetime import date, timedelta
from uuid import uuid4

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models import InventoryHistory, InventoryItem
from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

ITEMS_SUBTREE = "helpdesk.inventory.api.read.subtree"
STATS_SUBTREE = "helpdesk.inventory.api.read.stats.subtree"
EXPORT_SUBTREE = "helpdesk.inventory.api.export.subtree"
STATS_READ = "helpdesk.inventory.api.read.stats"
OWN_DEPT = "helpdesk.inventory.api.read.own_dept"
VERIFY = "helpdesk.inventory.api.verify"
CAMPAIGN_READ = "helpdesk.inventory.campaign.api.read"
CAMPAIGN_SUBTREE = "helpdesk.inventory.campaign.api.read.subtree"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real; `get_db` apunta a la sesión transaccional de
    Postgres del test (rollback al final). El scope por subárbol usa CTEs reales.
    """
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
    u = User(first_name="W", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="wid_cat").first()
    if not c:
        c = InventoryCategory(code="wid_cat", name="Cat", inventory_prefix="WID")
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _item(db, number, department, registered_by, **kw) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status=kw.pop("status", "ACTIVE"),
        is_active=True,
        **kw,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _grant_position(db, user, department, codes) -> None:
    """Ancla `user` en `department` con un puesto que otorga uno o varios permisos.

    Deliberadamente NO asigna ningún ROL — así la prueba confirma que el scope se
    resuelve por PERMISO (procedencia del puesto), no por nombre de rol.
    """
    codes = [codes] if isinstance(codes, str) else list(codes)
    app = _helpdesk(db)
    pos = Position(code=f"widpos_{user.id}_{uuid4().hex[:8]}", title="Jefe", department_id=department.id,
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


def _grant_role_direct(db, user, role_name) -> None:
    """Rol de helpdesk asignado DIRECTO (sin puesto).

    Simula el "puesto vencido" del brief: el usuario conserva el ROL (pasa
    `require_app` y trae "department_head" en `user_roles_in_app`), pero no hay
    ningún `UserPosition` vigente, así que `get_primary_user_department` (y por lo
    tanto cualquier anclaje de `.subtree`) no resuelve NINGÚN departamento.
    """
    app = _helpdesk(db)
    role = db.query(Role).filter_by(name=role_name).first()
    assert role is not None, f"rol {role_name} debe existir en la BD dev"
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.commit()


def _tree(db, prefix):
    """root -> mine -> child ; root -> sibling (rama hermana, NO descendiente de mine)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


def _campaign(db, folio, department, created_by, status="OPEN") -> InventoryCampaign:
    c = InventoryCampaign(folio=folio, department_id=department.id, title=folio,
                           status=status, created_by_id=created_by.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ───────────────────────── dashboard.py: widgets ─────────────────────────

class TestDashboardWidgetsScope:

    def test_quick_stats_matches_items_list_total(self, client, db_session):
        """La tarjeta de resumen del dashboard debe cuadrar con la tabla de la
        misma pantalla: mismo total para un jefe con subárbol."""
        root, mine, child, sibling = _tree(db_session, "dw1")
        boss = _user(db_session, "DBoss1")
        registrar = _user(db_session, "DReg1")
        _grant_position(db_session, boss, mine, [STATS_SUBTREE, ITEMS_SUBTREE])
        _item(db_session, "DW1-MINE", mine, registrar)
        _item(db_session, "DW1-CHILD", child, registrar)
        _item(db_session, "DW1-SIB", sibling, registrar)  # fuera de scope

        resp_widget = client.get(
            "/api/help-desk/v2/inventory/dashboard/widgets/quick-stats",
            headers=_jwt_cookie(boss.id),
        )
        resp_list = client.get(
            "/api/help-desk/v2/inventory/items", headers=_jwt_cookie(boss.id),
        )
        assert resp_widget.status_code == 200
        assert resp_list.status_code == 200
        assert resp_widget.json()["data"]["total_items"] == 2
        assert resp_list.json()["total"] == 2

    def test_status_chart_without_active_position_is_empty_not_global(self, client, db_session):
        """Puesto vencido (rol directo, sin UserPosition): antes devolvía el
        conteo GLOBAL del instituto (gate fail-open); ahora debe ser vacío."""
        root, mine, child, sibling = _tree(db_session, "dw2")
        boss = _user(db_session, "DBoss2")
        registrar = _user(db_session, "DReg2")
        _grant_role_direct(db_session, boss, "department_head")
        _item(db_session, "DW2-OTHER1", mine, registrar)
        _item(db_session, "DW2-OTHER2", sibling, registrar)

        resp = client.get(
            "/api/help-desk/v2/inventory/dashboard/widgets/status-chart",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        total_counted = sum(resp.json()["data"]["datasets"][0]["data"])
        assert total_counted == 0

    def test_category_chart_scoped_to_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "dw3")
        boss = _user(db_session, "DBoss3")
        registrar = _user(db_session, "DReg3")
        _grant_position(db_session, boss, mine, [ITEMS_SUBTREE, STATS_SUBTREE])
        _item(db_session, "DW3-MINE", mine, registrar)
        _item(db_session, "DW3-CHILD", child, registrar)
        _item(db_session, "DW3-SIB", sibling, registrar)

        resp = client.get(
            "/api/help-desk/v2/inventory/dashboard/widgets/category-chart",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        total = sum(resp.json()["data"]["datasets"][0]["data"])
        assert total == 2

    def test_recent_activity_scoped_to_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "dw4")
        boss = _user(db_session, "DBoss4")
        registrar = _user(db_session, "DReg4")
        _grant_position(db_session, boss, mine, ITEMS_SUBTREE)
        mine_item = _item(db_session, "DW4-MINE", mine, registrar)
        sibling_item = _item(db_session, "DW4-SIB", sibling, registrar)
        db_session.add(InventoryHistory(item_id=mine_item.id, event_type="REGISTERED", performed_by_id=registrar.id))
        db_session.add(InventoryHistory(item_id=sibling_item.id, event_type="REGISTERED", performed_by_id=registrar.id))
        db_session.commit()

        resp = client.get(
            "/api/help-desk/v2/inventory/dashboard/widgets/recent-activity",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        item_ids = {e["item"]["id"] for e in resp.json()["data"] if e.get("item")}
        assert sibling_item.id not in item_ids
        assert mine_item.id in item_ids


# ───────────────────────── history.py ─────────────────────────

class TestHistoryScope:

    def test_item_history_of_child_department_not_403(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "hw1")
        boss = _user(db_session, "HBoss1")
        registrar = _user(db_session, "HReg1")
        _grant_position(db_session, boss, mine, ITEMS_SUBTREE)
        child_item = _item(db_session, "HW1-CHILD", child, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/history/item/{child_item.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200

    def test_item_history_of_sibling_department_is_403(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "hw2")
        boss = _user(db_session, "HBoss2")
        registrar = _user(db_session, "HReg2")
        _grant_position(db_session, boss, mine, ITEMS_SUBTREE)
        sibling_item = _item(db_session, "HW2-SIB", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/history/item/{sibling_item.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_recent_events_tech_desarrollo_not_403(self, client, db_session):
        """Bug adyacente: la lista de excepciones de /recent omitía tech_desarrollo
        y tech_soporte, así que un técnico (acceso completo) caía al 403."""
        tech = _user(db_session, "HTech3")
        _grant_role_direct(db_session, tech, "tech_desarrollo")

        resp = client.get(
            "/api/help-desk/v2/inventory/history/recent",
            headers=_jwt_cookie(tech.id),
        )
        assert resp.status_code == 200

    def test_recent_events_scoped_to_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "hw4")
        boss = _user(db_session, "HBoss4")
        registrar = _user(db_session, "HReg4")
        _grant_position(db_session, boss, mine, ITEMS_SUBTREE)
        mine_item = _item(db_session, "HW4-MINE", mine, registrar)
        sibling_item = _item(db_session, "HW4-SIB", sibling, registrar)
        db_session.add(InventoryHistory(item_id=mine_item.id, event_type="REGISTERED", performed_by_id=registrar.id))
        db_session.add(InventoryHistory(item_id=sibling_item.id, event_type="REGISTERED", performed_by_id=registrar.id))
        db_session.commit()

        resp = client.get(
            "/api/help-desk/v2/inventory/history/recent",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        item_ids = {e["item_id"] for e in resp.json()["data"]}
        assert sibling_item.id not in item_ids
        assert mine_item.id in item_ids


# ───────────────────────── stats.py ─────────────────────────

class TestStatsScope:

    def test_department_stats_of_child_department_ok(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sw1")
        boss = _user(db_session, "SBoss1")
        registrar = _user(db_session, "SReg1")
        _grant_position(db_session, boss, mine, [OWN_DEPT, STATS_SUBTREE])
        _item(db_session, "SW1-CHILD", child, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/stats/department/{child.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_department_stats_of_sibling_department_is_403(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sw2")
        boss = _user(db_session, "SBoss2")
        registrar = _user(db_session, "SReg2")
        _grant_position(db_session, boss, mine, [OWN_DEPT, STATS_SUBTREE])
        _item(db_session, "SW2-SIB", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/stats/department/{sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403


# ───────────────────────── reports.py ─────────────────────────

class TestReportsScope:

    def test_equipment_report_without_department_ids_stays_within_scope(self, client, db_session):
        """Sin `department_ids` en el body, el reporte NO debe cubrir toda la
        institución: debe caer al scope visible del usuario."""
        root, mine, child, sibling = _tree(db_session, "rw1")
        boss = _user(db_session, "RBoss1")
        registrar = _user(db_session, "RReg1")
        _grant_position(db_session, boss, mine, [STATS_SUBTREE, EXPORT_SUBTREE, STATS_READ])
        _item(db_session, "RW1-MINE", mine, registrar)
        _item(db_session, "RW1-CHILD", child, registrar)
        _item(db_session, "RW1-SIB", sibling, registrar)

        resp = client.post(
            "/api/help-desk/v2/inventory/reports/equipment",
            json={},
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {i["inventory_number"] for i in resp.json()["items"]}
        assert numbers == {"RW1-MINE", "RW1-CHILD"}

    def test_equipment_report_requested_ids_outside_scope_is_empty(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "rw2")
        boss = _user(db_session, "RBoss2")
        registrar = _user(db_session, "RReg2")
        _grant_position(db_session, boss, mine, [STATS_SUBTREE, STATS_READ])
        _item(db_session, "RW2-SIB", sibling, registrar)

        resp = client.post(
            "/api/help-desk/v2/inventory/reports/equipment",
            json={"department_ids": [sibling.id]},
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ───────────────────────── verification.py ─────────────────────────

class TestVerificationScope:

    def test_status_department_id_outside_scope_returns_empty(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "vw1")
        boss = _user(db_session, "VBoss1")
        registrar = _user(db_session, "VReg1")
        _grant_position(db_session, boss, mine, [VERIFY, ITEMS_SUBTREE])
        _item(db_session, "VW1-SIB", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/verification/status?department_id={sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_status_within_subtree_is_visible(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "vw2")
        boss = _user(db_session, "VBoss2")
        registrar = _user(db_session, "VReg2")
        _grant_position(db_session, boss, mine, [VERIFY, ITEMS_SUBTREE])
        _item(db_session, "VW2-CHILD", child, registrar)

        resp = client.get(
            "/api/help-desk/v2/inventory/verification/status",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"VW2-CHILD"}


# ───────────────────────── campaigns.py (scope de lectura) ─────────────────────────

class TestCampaignsReadScope:

    def test_list_campaigns_scoped_by_permission_not_role(self, client, db_session):
        """Sin el ROL department_head (solo el PERMISO vía puesto): antes veía
        TODAS las campañas de todos los departamentos."""
        root, mine, child, sibling = _tree(db_session, "cw1")
        boss = _user(db_session, "CBoss1")
        _grant_position(db_session, boss, mine, [CAMPAIGN_READ, CAMPAIGN_SUBTREE])
        _campaign(db_session, "CW1-MINE", mine, boss)
        _campaign(db_session, "CW1-CHILD", child, boss)
        _campaign(db_session, "CW1-SIB", sibling, boss)

        resp = client.get(
            "/api/help-desk/v2/inventory/campaigns", headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        folios = {c["folio"] for c in resp.json()["campaigns"]}
        assert folios == {"CW1-MINE", "CW1-CHILD"}

    def test_campaign_detail_of_sibling_department_is_404(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "cw2")
        boss = _user(db_session, "CBoss2")
        _grant_position(db_session, boss, mine, [CAMPAIGN_READ, CAMPAIGN_SUBTREE])
        foreign = _campaign(db_session, "CW2-SIB", sibling, boss)

        resp = client.get(
            f"/api/help-desk/v2/inventory/campaigns/{foreign.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 404

    def test_campaign_detail_within_subtree_ok(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "cw3")
        boss = _user(db_session, "CBoss3")
        _grant_position(db_session, boss, mine, [CAMPAIGN_READ, CAMPAIGN_SUBTREE])
        c = _campaign(db_session, "CW3-CHILD", child, boss)

        resp = client.get(
            f"/api/help-desk/v2/inventory/campaigns/{c.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["folio"] == "CW3-CHILD"

    def test_campaign_groups_view_of_sibling_department_is_404(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "cw4")
        boss = _user(db_session, "CBoss4")
        _grant_position(db_session, boss, mine, [CAMPAIGN_READ, CAMPAIGN_SUBTREE])
        foreign = _campaign(db_session, "CW4-SIB", sibling, boss)

        resp = client.get(
            f"/api/help-desk/v2/inventory/campaigns/{foreign.id}/groups-view",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 404

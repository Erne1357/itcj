"""Scope por subárbol (org-scoped authz) en los endpoints REST de inventario.

Cubre los 3 archivos de la auditoría de escalada horizontal:
  - api/inventory/items.py       (GET /inventory/items, GET /inventory/department/{id})
  - api/inventory/selection.py   (for-ticket, by-group, groups-with-items, validate-for-ticket)
  - api/inventory/groups.py      (GET /{id}, GET /{id}/items, GET /department/{id})

Todos deben honrar `visible_department_ids` (helpdesk.utils.inventory_access): un
jefe con `.read.subtree` ve su departamento Y su subárbol, nunca la rama hermana ni
el padre; un `?department_id=` arbitrario NUNCA sustituye el scope visible, solo lo
intersecta (fuera de scope ⇒ vacío, nunca 500 ni datos ajenos).
"""
from datetime import date, timedelta
from uuid import uuid4

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models import InventoryGroup, InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

ITEMS_SUBTREE = "helpdesk.inventory.api.read.subtree"
GROUPS_SUBTREE = "helpdesk.inventory_groups.api.read.subtree"
GROUPS_OWN_DEPT = "helpdesk.inventory_groups.api.read.own_dept"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, pero `get_db` apunta a la sesión transaccional
    de Postgres del test (mismo patrón que db_session: rollback al final, nada se
    persiste). Necesario porque el scope por subárbol usa CTEs reales de Postgres.
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
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="ias_cat").first()
    if not c:
        c = InventoryCategory(code="ias_cat", name="Cat", inventory_prefix="IAS")
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _item(db, number, department, registered_by, *, status="ACTIVE", assigned_to_user_id=None,
          group_id=None) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status=status,
        is_active=True,
        assigned_to_user_id=assigned_to_user_id,
        group_id=group_id,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _group(db, code, department, created_by) -> InventoryGroup:
    g = InventoryGroup(name=code, code=code, department_id=department.id, created_by_id=created_by.id)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _grant(db, user, department, *, code) -> None:
    """Ancla `user` en `department` con un puesto que otorga `code` (perm de scope).

    `code` acepta un string o una lista de códigos (mismo puesto/ancla, varios
    permisos — p. ej. `.own_dept` de grupos + `.subtree` de items, la combinación
    real que hoy habilita ver grupos dentro del subárbol: ver nota en
    TestGroupsScope sobre `visible_department_ids` estando anclado a los perms
    de ITEMS, no a los de GROUPS).
    """
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    # code (varchar 50): NO usar el código de permiso completo (excede el límite).
    pos = Position(code=f"iaspos_{user.id}_{uuid4().hex[:8]}", title="Jefe", department_id=department.id,
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
    """root -> mine -> child ; root -> sibling (rama hermana, NO descendiente de mine)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


# ───────────────────────────── items.py: GET /items ─────────────────────────────

class TestItemsListScope:

    def test_subtree_sees_own_and_child_not_sibling_or_parent(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "il1")
        boss = _user(db_session, "Boss1")
        registrar = _user(db_session, "Reg1")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)

        mine_item = _item(db_session, "IL1-MINE", mine, registrar)
        child_item = _item(db_session, "IL1-CHILD", child, registrar)
        sibling_item = _item(db_session, "IL1-SIB", sibling, registrar)
        root_item = _item(db_session, "IL1-ROOT", root, registrar)

        resp = client.get("/api/help-desk/v2/inventory/items", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        body = resp.json()
        numbers = {i["inventory_number"] for i in body["data"]}

        assert numbers == {"IL1-MINE", "IL1-CHILD"}

    def test_department_id_param_outside_scope_returns_empty(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "il2")
        boss = _user(db_session, "Boss2")
        registrar = _user(db_session, "Reg2")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        _item(db_session, "IL2-SIB", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/items?department_id={sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_department_id_param_within_scope_is_honored(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "il3")
        boss = _user(db_session, "Boss3")
        registrar = _user(db_session, "Reg3")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        child_item = _item(db_session, "IL3-CHILD", child, registrar)
        _item(db_session, "IL3-MINE", mine, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/items?department_id={child.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        numbers = {i["inventory_number"] for i in body["data"]}
        assert numbers == {"IL3-CHILD"}

    def test_plain_user_cannot_escalate_via_department_id(self, client, db_session):
        """require_app("helpdesk") solo exige acceso a la app; sin grants de depto/
        subárbol, ?department_id= arbitrario NO debe abrir el inventario ajeno."""
        _, mine, _, foreign = _tree(db_session, "il4")
        plain = _user(db_session, "Plain4")
        registrar = _user(db_session, "Reg4")
        # Acceso a la app SIN ningún permiso de inventario: un permiso ajeno cualquiera.
        _grant(db_session, plain, mine, code="helpdesk.tickets.api.read.own")
        _item(db_session, "IL4-FOREIGN", foreign, registrar)
        own_item = _item(db_session, "IL4-OWN", mine, registrar, assigned_to_user_id=plain.id)

        resp = client.get(
            f"/api/help-desk/v2/inventory/items?department_id={foreign.id}",
            headers=_jwt_cookie(plain.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

        # Sin param: cae al fallback histórico (solo lo que tiene asignado).
        resp2 = client.get("/api/help-desk/v2/inventory/items", headers=_jwt_cookie(plain.id))
        numbers = {i["inventory_number"] for i in resp2.json()["data"]}
        assert numbers == {"IL4-OWN"}


# ───────────────────── selection.py: for-ticket / groups-with-items ─────────────────────

class TestSelectionScope:

    def test_for_ticket_department_id_outside_scope_returns_empty(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl1")
        boss = _user(db_session, "Boss5")
        registrar = _user(db_session, "Reg5")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        _item(db_session, "SL1-SIB", sibling, registrar, status="ACTIVE")

        resp = client.get(
            f"/api/help-desk/v2/inventory/selection/for-ticket?department_id={sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_for_ticket_department_id_within_subtree_is_honored(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl2")
        boss = _user(db_session, "Boss6")
        registrar = _user(db_session, "Reg6")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        child_item = _item(db_session, "SL2-CHILD", child, registrar, status="ACTIVE")

        resp = client.get(
            f"/api/help-desk/v2/inventory/selection/for-ticket?department_id={child.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"SL2-CHILD"}

    def test_groups_with_items_department_id_outside_scope_returns_empty(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl3")
        boss = _user(db_session, "Boss7")
        registrar = _user(db_session, "Reg7")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        g = _group(db_session, "SL3-GRP", sibling, registrar)
        _item(db_session, "SL3-GITEM", sibling, registrar, status="ACTIVE", group_id=g.id)

        resp = client.get(
            f"/api/help-desk/v2/inventory/selection/groups-with-items?department_id={sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_by_group_403_for_group_outside_scope(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl4")
        boss = _user(db_session, "Boss8")
        registrar = _user(db_session, "Reg8")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        foreign_group = _group(db_session, "SL4-GRP", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/selection/by-group/{foreign_group.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_by_group_ok_for_group_within_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl5")
        boss = _user(db_session, "Boss9")
        registrar = _user(db_session, "Reg9")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        child_group = _group(db_session, "SL5-GRP", child, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/selection/by-group/{child_group.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200

    def test_validate_items_for_ticket_filters_out_of_scope(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "sl6")
        boss = _user(db_session, "Boss10")
        registrar = _user(db_session, "Reg10")
        _grant(db_session, boss, mine, code=ITEMS_SUBTREE)
        mine_item = _item(db_session, "SL6-MINE", mine, registrar, status="ACTIVE")
        foreign_item = _item(db_session, "SL6-FOREIGN", sibling, registrar, status="ACTIVE")

        resp = client.post(
            "/api/help-desk/v2/inventory/selection/validate-for-ticket",
            json={"item_ids": [mine_item.id, foreign_item.id]},
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        valid_numbers = {i["inventory_number"] for i in body["valid_items"]}
        invalid_ids = {i["item_id"] for i in body["invalid_items"]}
        assert valid_numbers == {"SL6-MINE"}
        assert invalid_ids == {foreign_item.id}
        assert body["success"] is False


# ───────────────────────────── groups.py ─────────────────────────────

# `visible_department_ids` ancla el scope de SUBÁRBOL en el permiso de ITEMS
# (`helpdesk.inventory.api.read.subtree`) — no existe (todavía) una versión que
# lea `helpdesk.inventory_groups.api.read.subtree` para expandir un subárbol
# propio. Por eso el jefe realista que hoy "ve items del subárbol pero no sus
# grupos" (brief, issue #6) tiene AMBOS: `.inventory_groups.api.read.own_dept`
# (pasa el guard de grupos) + `.inventory.api.read.subtree` (alimenta el scope
# visible que ahora también gatea grupos). Con esa combinación, migrar
# groups.py a `visible_department_ids` es lo que de verdad cierra la
# divergencia de scopes.
_REALISTIC_GROUPS_SUBTREE_GRANT = [GROUPS_OWN_DEPT, ITEMS_SUBTREE]


class TestGroupsScope:

    def test_group_detail_403_for_foreign_department(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl1")
        boss = _user(db_session, "Boss11")
        registrar = _user(db_session, "Reg11")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)
        foreign_group = _group(db_session, "GL1-GRP", sibling, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/{foreign_group.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_group_detail_ok_within_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl2")
        boss = _user(db_session, "Boss12")
        registrar = _user(db_session, "Reg12")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)
        child_group = _group(db_session, "GL2-GRP", child, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/{child_group.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == child_group.id

    def test_group_items_403_for_foreign_department(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl3")
        boss = _user(db_session, "Boss13")
        registrar = _user(db_session, "Reg13")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)
        foreign_group = _group(db_session, "GL3-GRP", sibling, registrar)
        _item(db_session, "GL3-ITEM", sibling, registrar, group_id=foreign_group.id)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/{foreign_group.id}/items",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_group_items_ok_within_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl3b")
        boss = _user(db_session, "Boss14b")
        registrar = _user(db_session, "Reg14b")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)
        child_group = _group(db_session, "GL3B-GRP", child, registrar)
        _item(db_session, "GL3B-ITEM", child, registrar, group_id=child_group.id)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/{child_group.id}/items",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {i["inventory_number"] for i in resp.json()["data"]}
        assert numbers == {"GL3B-ITEM"}

    def test_groups_by_department_403_for_foreign_department(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl4")
        boss = _user(db_session, "Boss14")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/department/{sibling.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_groups_by_department_ok_within_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "gl5")
        boss = _user(db_session, "Boss15")
        registrar = _user(db_session, "Reg15")
        _grant(db_session, boss, mine, code=_REALISTIC_GROUPS_SUBTREE_GRANT)
        child_group = _group(db_session, "GL5-GRP", child, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/department/{child.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {g["code"] for g in resp.json()["data"]}
        assert numbers == {"GL5-GRP"}

    def test_subtree_only_perm_passes_guard_but_is_inert_without_a_real_scope_grant(self, client, db_session):
        """require_perms es any-of: `.read.subtree` (aunque el permiso todavía no
        exista en la BD real) debe bastar para pasar el GUARD de GET /groups/{id}
        sin el perm `.own_dept` (issue #7 del brief). El brief es explícito en que
        esto es "inocuo" — el guard deja pasar, pero `visible_department_ids` no
        sabe (todavía) anclar scope en este código de permiso, así que sin un
        acceso departamental/subárbol REAL (own_dept o el subtree de items), el
        body sigue negando incluso el propio departamento. Este test fija ESE
        comportamiento (inerte pero no roto): si algún día se pluggea el permiso
        en `visible_department_ids`, este test debe actualizarse a 200.
        """
        root, mine, child, sibling = _tree(db_session, "gl6")
        boss = _user(db_session, "Boss16")
        registrar = _user(db_session, "Reg16")
        _grant(db_session, boss, mine, code=GROUPS_SUBTREE)
        mine_group = _group(db_session, "GL6-GRP", mine, registrar)

        resp = client.get(
            f"/api/help-desk/v2/inventory/groups/{mine_group.id}",
            headers=_jwt_cookie(boss.id),
        )
        # 403 sí, pero por el check de departamento del BODY (no por el guard):
        # confirma que `require_perms` ya no bloquea antes de llegar a la lógica.
        assert resp.status_code == 403
        assert resp.json()["error"]["error"] == "No tiene permiso para ver este grupo"

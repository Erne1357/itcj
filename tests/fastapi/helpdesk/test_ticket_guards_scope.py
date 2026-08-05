"""Guards gruesos de ticket detail/sub-recursos deben aceptar los mismos tres
scopes que ya usa `GET /tickets` (`.read.own` / `.read.all` / `.read.subtree`),
y la autorización FINA (`can_user_view_ticket`) debe seguir cortando fuera de
scope incluso cuando el guard grueso deja pasar. `require_perms`/`require_page_app`
son any-of por intersección de sets — agregar un código a la lista es aditivo
y no-breaking (ver `itcj2/dependencies.py:218`).

Cubre:
  (a) TestTicketDetailSubtreeGuard — el detalle de ticket (`GET /tickets/{id}`)
      solo listaba `.read.own`: un usuario con SOLO `.read.subtree` por puesto
      listaba tickets correctamente (`GET /tickets` ya incluye los 3 scopes)
      pero recibía 403 al abrir el detalle. El guard debe abrir con `.subtree`,
      pero `can_user_view_ticket` sigue negando la rama hermana.
  (b) TestAssignmentHistoryScope — `/assignments/{id}/history` gateaba SOLO por
      `.read.all` (que `department_head` tiene por rol, ver
      `database/DML/helpdesk/03_insert_role_permission.sql:225`) y nunca
      llamaba `can_user_view_ticket`: fuga real del historial de asignaciones
      (quién, cuándo, notas) de tickets de cualquier rama del organigrama.
  (c) TestTicketEquipmentSubtreeScope — `ticket_equipment.py` escopaba por
      IGUALDAD de departamento (`get_user_department(...) == item.department_id`),
      no por subárbol: un jefe con `.read.subtree` no veía, en "tickets de este
      equipo", los tickets de sus sub-departamentos, aunque esos mismos tickets
      sí salen en `GET /tickets` y sí abren en detalle. Dos bugs adyacentes en
      el mismo bloque: se comparaba contra el rol `"technician"` (no existe;
      los reales son `tech_desarrollo`/`tech_soporte` → check muerto) y el
      bypass de la segunda mitad omitía a los técnicos, que
      `can_user_view_ticket` sí deja ver todo.
  (d) TestTicketEquipmentAddRegression — `POST /{ticket_id}/equipment` llamaba
      `TicketInventoryService.add_items_to_ticket(ticket_id, item_ids)` pero la
      firma real es `(db, ticket_id, item_ids)` — truena con TypeError en
      cuanto se ejecuta.
  (e) TestAssignmentStatsScope — `/assignments/stats` con el mismo gate
      `.read.all` devolvía contadores GLOBALES del instituto a cualquiera con
      ese permiso (p. ej. `department_head` vía rol), sin acotarlos a su scope
      de lectura real.
"""
from datetime import date, timedelta
from uuid import uuid4

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.ticket_inventory_item import TicketInventoryItem
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

SUBTREE = "helpdesk.tickets.api.read.subtree"
READ_ALL = "helpdesk.tickets.api.read.all"
READ_OWN = "helpdesk.tickets.api.read.own"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, pero `get_db` apunta a la sesión transaccional
    de Postgres del test (mismo patrón que `test_inventory_api_scope.py`)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jwt_cookie(user_id: int, role: str | None = None) -> dict:
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


def _tree(db, prefix):
    """root -> mine -> child ; root -> sibling (rama hermana, NO descendiente de mine)."""
    root = _dept(db, f"{prefix}_root")
    mine = _dept(db, f"{prefix}_mine", root.id)
    child = _dept(db, f"{prefix}_child", mine.id)
    sibling = _dept(db, f"{prefix}_sibling", root.id)
    return root, mine, child, sibling


def _grant(db, user, department, *, code) -> Position:
    """Ancla a `user` en `department` con un puesto que otorga `code` (permiso
    DIRECTO vía PositionAppPerm). `code` acepta un string o una lista."""
    codes = [code] if isinstance(code, str) else list(code)
    app = _helpdesk(db)
    pos = Position(code=f"tgspos_{user.id}_{uuid4().hex[:8]}", title="Jefe",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    for c in codes:
        perm = _perm(db, app, c)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _grant_role(db, user, role_name, perm_codes=None) -> Role:
    """Rol DIRECTO del usuario en helpdesk (`UserAppRole`), sin puesto — igual
    que un `department_head`/`tech_soporte` que recibe permisos vía
    `core_role_permissions` en el DML real, sin necesidad de un puesto propio
    para probar el guard/las fugas del gate grueso."""
    app = _helpdesk(db)
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name)
        db.add(role)
        db.commit()
        db.refresh(role)
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    for code in (perm_codes or []):
        perm = _perm(db, app, code)
        exists = db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first()
        if not exists:
            db.add(RolePermission(role_id=role.id, perm_id=perm.id))
    db.commit()
    return role


def _category(db) -> Category:
    c = db.query(Category).filter_by(code="tgs_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="tgs_cat", name="tgs", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department, assigned_to=None) -> Ticket:
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
        assigned_to_user_id=assigned_to.id if assigned_to else None,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _inv_category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="tgs_icat").first()
    if not c:
        c = InventoryCategory(code="tgs_icat", name="Cat", inventory_prefix="TGS")
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _item(db, number, department, registered_by) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_inv_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status="ACTIVE",
        is_active=True,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _link(db, ticket, item) -> None:
    db.add(TicketInventoryItem(ticket_id=ticket.id, inventory_item_id=item.id))
    db.commit()


# ───────────────────────── (a) detalle de ticket ─────────────────────────

class TestTicketDetailSubtreeGuard:

    def test_subtree_only_opens_ticket_in_own_subtree(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "tga")
        boss = _user(db_session, "BossA")
        stranger = _user(db_session, "StrangerA")
        _grant(db_session, boss, mine, code=SUBTREE)

        ticket = _ticket(db_session, "TGA-CHILD-1", stranger, child)

        resp = client.get(f"/api/help-desk/v2/tickets/{ticket.id}", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        assert resp.json()["ticket"]["ticket_number"] == "TGA-CHILD-1"

    def test_subtree_only_still_403_on_sibling_branch(self, client, db_session):
        """El guard grueso ahora deja pasar (tiene `.subtree`), pero
        `can_user_view_ticket` sigue cortando fuera del subárbol."""
        root, mine, child, sibling = _tree(db_session, "tgb")
        boss = _user(db_session, "BossB")
        stranger = _user(db_session, "StrangerB")
        _grant(db_session, boss, mine, code=SUBTREE)

        ticket = _ticket(db_session, "TGB-SIB-1", stranger, sibling)

        resp = client.get(f"/api/help-desk/v2/tickets/{ticket.id}", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 403


# ───────────────────────── (b) historial de asignaciones ─────────────────────────

class TestAssignmentHistoryScope:

    def test_read_all_alone_does_not_leak_foreign_branch_history(self, client, db_session):
        """`department_head` tiene `.read.all` por ROL (DML real,
        `03_insert_role_permission.sql:225`). Sin pasar por
        `can_user_view_ticket`, eso filtraba el historial de asignaciones de
        CUALQUIER ticket del instituto."""
        root, mine, child, sibling = _tree(db_session, "tgc")
        boss = _user(db_session, "BossC")
        stranger = _user(db_session, "StrangerC")
        _grant_role(db_session, boss, "department_head", perm_codes=[READ_ALL])

        foreign_ticket = _ticket(db_session, "TGC-SIB-1", stranger, sibling)

        resp = client.get(
            f"/api/help-desk/v2/assignments/{foreign_ticket.id}/history",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_subtree_scope_can_read_own_branch_history(self, client, db_session):
        """El guard también debe abrir con `.subtree` (aditivo, igual que
        `GET /tickets`), y `can_user_view_ticket` debe dejarlo pasar para un
        ticket dentro del subárbol."""
        root, mine, child, sibling = _tree(db_session, "tgd")
        boss = _user(db_session, "BossD")
        stranger = _user(db_session, "StrangerD")
        _grant(db_session, boss, mine, code=SUBTREE)

        own_ticket = _ticket(db_session, "TGD-CHILD-1", stranger, child)

        resp = client.get(
            f"/api/help-desk/v2/assignments/{own_ticket.id}/history",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        assert resp.json()["ticket_id"] == own_ticket.id


# ───────────────────────── (c) ticket_equipment: scope por subárbol ─────────────────────────

class TestTicketEquipmentSubtreeScope:

    def test_department_head_with_subtree_sees_child_department_tickets(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "tge")
        boss = _user(db_session, "BossE")
        registrar = _user(db_session, "RegE")
        stranger = _user(db_session, "StrangerE")
        _grant(db_session, boss, mine, code=SUBTREE)
        _grant_role(db_session, boss, "department_head")

        item = _item(db_session, "TGE-ITEM-1", child, registrar)
        ticket = _ticket(db_session, "TGE-TCK-1", stranger, child)
        _link(db_session, ticket, item)

        resp = client.get(
            f"/api/help-desk/v2/tickets/equipment/{item.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 200
        numbers = {t["ticket_number"] for t in resp.json()["tickets"]}
        assert "TGE-TCK-1" in numbers

    def test_department_head_still_blocked_outside_subtree(self, client, db_session):
        """Guard de no-regresión: el jefe sigue sin poder consultar (ni ver
        metadata de) un equipo de la rama hermana — la propiedad no se vuelve
        global. El mismo `dept_ids` (subárbol ∪ depto propio) que abre el
        subárbol también sigue cerrando la rama hermana."""
        root, mine, child, sibling = _tree(db_session, "tgf2")
        boss = _user(db_session, "BossF2")
        registrar = _user(db_session, "RegF2")
        stranger = _user(db_session, "StrangerF2")
        _grant(db_session, boss, mine, code=SUBTREE)
        _grant_role(db_session, boss, "department_head")

        foreign_item = _item(db_session, "TGF2-ITEM-1", sibling, registrar)
        foreign_ticket = _ticket(db_session, "TGF2-TCK-1", stranger, sibling)
        _link(db_session, foreign_ticket, foreign_item)

        resp = client.get(
            f"/api/help-desk/v2/tickets/equipment/{foreign_item.id}",
            headers=_jwt_cookie(boss.id),
        )
        assert resp.status_code == 403

    def test_technician_role_is_not_blocked_by_dead_role_literal(self, client, db_session):
        """El check comparaba contra el rol `"technician"`, que no existe (los
        reales son `tech_desarrollo`/`tech_soporte`) — la comparación era un
        no-op que bloqueaba a los técnicos reales pese a que
        `can_user_view_ticket` los deja ver cualquier ticket."""
        root, mine, child, sibling = _tree(db_session, "tgf")
        tech = _user(db_session, "TechF")
        registrar = _user(db_session, "RegF")
        stranger = _user(db_session, "StrangerF")
        _grant_role(db_session, tech, "tech_soporte", perm_codes=[READ_OWN])

        item = _item(db_session, "TGF-ITEM-1", sibling, registrar)
        ticket = _ticket(db_session, "TGF-TCK-1", stranger, sibling)
        _link(db_session, ticket, item)

        resp = client.get(
            f"/api/help-desk/v2/tickets/equipment/{item.id}",
            headers=_jwt_cookie(tech.id),
        )
        assert resp.status_code == 200
        numbers = {t["ticket_number"] for t in resp.json()["tickets"]}
        assert "TGF-TCK-1" in numbers


# ───────────────────────── (d) regresión: firma vieja de add_items_to_ticket ─────────────────────────

class TestTicketEquipmentAddRegression:

    def test_add_equipment_does_not_crash_on_missing_db_arg(self, client, db_session):
        """`TicketInventoryService.add_items_to_ticket(db, ticket_id, item_ids)`
        exige `db` como primer argumento (`ticket_inventory_service.py:19`); el
        endpoint lo llamaba como `add_items_to_ticket(ticket_id, item_ids)` —
        truena con TypeError en cuanto se ejecuta (ruta nunca probada en
        runtime)."""
        dept = _dept(db_session, "tgg_dept")
        requester = _user(db_session, "ReqG")
        registrar = _user(db_session, "RegG")
        ticket = _ticket(db_session, "TGG-TCK-1", requester, dept)
        item = _item(db_session, "TGG-ITEM-1", dept, registrar)

        resp = client.post(
            f"/api/help-desk/v2/tickets/{ticket.id}/equipment",
            json={"item_ids": [item.id]},
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added_items"][0]["inventory_item"]["inventory_number"] == "TGG-ITEM-1"


# ───────────────────────── (e) /assignments/stats acotado al scope ─────────────────────────

class TestAssignmentStatsScope:

    def test_department_head_sees_only_own_scope_counts(self, client, db_session):
        root, mine, child, sibling = _tree(db_session, "tgh")
        boss = _user(db_session, "BossH")
        stranger = _user(db_session, "StrangerH")
        _grant_role(db_session, boss, "department_head", perm_codes=[READ_ALL])
        _grant(db_session, boss, mine, code=SUBTREE)

        _ticket(db_session, "TGH-CHILD-1", stranger, child)   # dentro del subárbol
        _ticket(db_session, "TGH-SIB-1", stranger, sibling)     # fuera, rama hermana

        resp = client.get("/api/help-desk/v2/assignments/stats", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        # Solo el PENDING de su subárbol, NO el total del instituto (2).
        assert resp.json()["unassigned"] == 1

    def test_admin_still_sees_global_counts(self, client, db_session):
        """No-regresión: el admin global sigue viendo el conteo del instituto,
        SIN acotarlo a ningún departamento. Se compara por DELTA (no por valor
        absoluto): la BD de dev puede tener PENDING preexistentes de trabajo
        manual, así que el conteo global no parte necesariamente de 0."""
        root, mine, child, sibling = _tree(db_session, "tgi")
        stranger = _user(db_session, "StrangerI")
        admin_user = _user(db_session, "AdminI")
        # El bypass JWT (`role: admin`) solo abre el GUARD (`require_perms`); la
        # decisión de "acceso total" del cuerpo del endpoint usa
        # `user_roles_in_app` (mismo patrón que `ticket_service.list_tickets`),
        # que lee de las tablas de rol/puesto, no del claim del JWT.
        _grant_role(db_session, admin_user, "admin")
        admin_cookie = _jwt_cookie(admin_user.id, role="admin")

        baseline = client.get("/api/help-desk/v2/assignments/stats", headers=admin_cookie).json()["unassigned"]

        _ticket(db_session, "TGI-CHILD-1", stranger, child)
        _ticket(db_session, "TGI-SIB-1", stranger, sibling)

        resp = client.get("/api/help-desk/v2/assignments/stats", headers=admin_cookie)
        assert resp.status_code == 200
        assert resp.json()["unassigned"] == baseline + 2

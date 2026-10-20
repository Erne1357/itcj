"""Sitios "hoja" que aún resolvían el departamento del usuario de forma AGNÓSTICA
de la app (`get_user_department` / `get_primary_user_department` / `get_user_departments`,
todos en `itcj2.core.services.departments_service`) en vez de usar el resolver por
PROCEDENCIA (`app_departments` / `primary_app_department`, mismo módulo).

El bug: con multi-puesto, el desempate agnóstico (puesto más antiguo) puede elegir un
departamento que no tiene NADA que ver con helpdesk, mientras que el puesto que SÍ da
acceso queda fuera. Dos síntomas simétricos, según el sitio:
  - se FILTRA el departamento ajeno (aparece donde no debería), o
  - se OMITE el departamento correcto (el usuario pierde acceso a lo suyo).

Cubre los 7 archivos de ese barrido (ver PLAN / instrucciones de la tarea):
  api/stats.py, api/assignments.py, api/ticket_equipment.py,
  api/inventory/items.py, api/inventory/selection.py, api/inventory/assignments.py,
  pages/inventory.py

En cada uno, como mínimo:
  (a) puesto viejo en depto SIN acceso a helpdesk + puesto nuevo CON acceso: el de
      sin acceso nunca debe verse/operarse.
  (b) dos departamentos CON acceso (procedencias distintas): ambos cuentan.
  (c) el respaldo por asignación DIRECTA (sin puesto que otorgue nada) no se rompe.

(b)/(c) se omiten donde la propia estructura del sitio los vuelve inaplicables o
redundantes con lo que ya cubre `test_app_departments.py` / `test_stats_scope.py`
(se anota en el docstring de cada clase por qué).
"""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models import InventoryGroup, InventoryItem
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, PositionAppRole, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm

TODAY = date.today()

ITEMS_SUBTREE = "helpdesk.inventory.api.read.subtree"
STATS_SUBTREE = "helpdesk.stats.api.read.subtree"
TICKETS_SUBTREE = "helpdesk.tickets.api.read.subtree"
TICKETS_OWN = "helpdesk.tickets.api.read.own"


# ─────────────────────────── infraestructura de test ───────────────────────────

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


# Lo que el DML le da a estos roles en producción, y sin lo cual el andamiaje
# construye un usuario que no existe en ninguna instalación real.
_PERMS_POR_ROL = {
    "department_head": ("helpdesk.tickets.api.read.department",),
    "secretary": ("helpdesk.tickets.api.read.department",),
}


def _role(db, name) -> Role:
    """El rol, con los permisos que el DML le da EN PRODUCCIÓN.

    Ojo con el entorno: en la base de dev los roles ya vienen sembrados desde
    `database/DML/`, pero CI arranca de un `create_all` VACÍO — el DML tiene PII
    y nunca llega al checkout. Un `Role(name=...)` pelado es un rol que en
    ninguna instalación real existe, y desde que el scope departamental se abre
    por PERMISO (`helpdesk.tickets.api.read.department`) y no por el nombre del
    rol, montar el andamiaje así hacía que estos tests probaran un usuario
    imposible: con la etiqueta de jefe y sin ninguno de sus permisos.
    """
    r = db.query(Role).filter_by(name=name).first()
    if not r:
        r = Role(name=name)
        db.add(r)
        db.commit()
        db.refresh(r)
    for code in _PERMS_POR_ROL.get(name, ()):
        perm = _perm(db, _helpdesk(db), code)
        ya = (db.query(RolePermission)
              .filter_by(role_id=r.id, perm_id=perm.id).first())
        if not ya:
            db.add(RolePermission(role_id=r.id, perm_id=perm.id))
            db.commit()
    return r


_seq = [0]


def _position(db, department, user, start_date, *, perm_codes=None, role_name=None, end_date=None):
    """Puesto vigente de `user` en `department` desde `start_date`.

    Sin `perm_codes`/`role_name`: puesto "neutro" (ancla departamento pero no otorga
    NADA en helpdesk) — para simular el puesto ajeno más antiguo del bug.
    """
    _seq[0] += 1
    app = _helpdesk(db)
    pos = Position(
        code=f"asl{_seq[0]}", title="Puesto", department_id=department.id,
        is_active=True, allows_multiple=True,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=start_date, end_date=end_date, is_active=True,
    ))
    for code in (perm_codes or []):
        perm = _perm(db, app, code)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    if role_name:
        role = _role(db, role_name)
        db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
    db.commit()
    return pos


def _direct_perm(db, user, code):
    """Asignación DIRECTA (sin puesto) de `code` en helpdesk — el caso de respaldo."""
    app = _helpdesk(db)
    perm = _perm(db, app, code)
    db.add(UserAppPerm(user_id=user.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _category(db) -> Category:
    c = db.query(Category).filter_by(code="asl_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="asl_cat", name="asl", is_active=True)
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


def _inv_category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="asl_inv_cat").first()
    if not c:
        c = InventoryCategory(code="asl_inv_cat", name="AslCat", inventory_prefix="ASL")
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _item(db, number, department, registered_by, *, status="ACTIVE",
          assigned_to_user_id=None, group_id=None) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_inv_category(db).id,
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


def _u(user) -> dict:
    return {"sub": str(user.id), "role": None}


class _FakeRequest:
    """Sustituye a `Request`: los endpoints solo leen `.query_params.get(...)`."""

    def __init__(self, query_params=None):
        self.query_params = query_params or {}
        self.client = None
        self.state = object()


# ═══════════════════════════ api/stats.py ═══════════════════════════

class TestResolveStatsScope:
    """`_resolve_stats_scope` (usada por /stats/global, /by-department, /by-technician,
    /time-breakdown, /ratings-detail, /analysis/*): el departamento "propio" que se
    sumaba al subárbol venía de `get_primary_user_department` (agnóstico)."""

    def test_leak_older_foreign_position_is_excluded(self, db_session):
        from itcj2.apps.helpdesk.api.stats import _resolve_stats_scope

        foreign = _dept(db_session, "stl1_foreign")   # sin acceso a helpdesk, MÁS VIEJO
        own = _dept(db_session, "stl1_own")            # con .subtree, más nuevo
        boss = _user(db_session, "Stl1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5), perm_codes=[STATS_SUBTREE])

        has_full, dept_ids = _resolve_stats_scope(db_session, _u(boss))

        assert has_full is False
        assert dept_ids == {own.id}, "el depto ajeno (más viejo) se filtró al scope"

    def test_both_granting_departments_count(self, db_session):
        """Secretaria de dos departamentos, cada uno con SU PROPIO puesto otorgante
        (uno vía `.subtree`, el otro vía un permiso de helpdesk sin relación con
        stats): ambos deben contar como "propios", no solo el más viejo."""
        from itcj2.apps.helpdesk.api.stats import _resolve_stats_scope

        dept_a = _dept(db_session, "stl2_a")   # otorga .subtree, MÁS VIEJO
        dept_b = _dept(db_session, "stl2_b")   # otorga otro permiso, MÁS NUEVO
        boss = _user(db_session, "Stl2Boss")

        _position(db_session, dept_a, boss, TODAY - timedelta(days=200), perm_codes=[STATS_SUBTREE])
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), perm_codes=[TICKETS_OWN])

        has_full, dept_ids = _resolve_stats_scope(db_session, _u(boss))

        assert has_full is False
        assert dept_ids == {dept_a.id, dept_b.id}

    def test_fallback_direct_grant_uses_all_user_departments(self, db_session):
        """Acceso vía `UserAppPerm` (sin puesto que ancle): respaldo con TODOS sus
        departamentos, igual que antes de este fix (no debe romperse)."""
        from itcj2.apps.helpdesk.api.stats import _resolve_stats_scope

        dept_x = _dept(db_session, "stl3_x")
        dept_y = _dept(db_session, "stl3_y")
        plain = _user(db_session, "Stl3Plain")

        _position(db_session, dept_x, plain, TODAY - timedelta(days=100))
        _position(db_session, dept_y, plain, TODAY - timedelta(days=50))
        _direct_perm(db_session, plain, STATS_SUBTREE)

        has_full, dept_ids = _resolve_stats_scope(db_session, _u(plain))

        assert has_full is False
        assert dept_ids == {dept_x.id, dept_y.id}


class TestDepartmentStatsEndpoint:
    """`get_department_stats` (`GET /stats/department/{id}`): mismo bug.

    La rama la habilita el PERMISO `helpdesk.tickets.api.read.department`, que es
    lo que el DML le da al rol `department_head` (y también a `secretary`, que es
    por lo que una secretaría dejó de recibir 403 en sus KPIs). El andamiaje lo
    siembra en `_role`.
    """

    def test_leak_older_foreign_position_is_excluded(self, db_session):
        from itcj2.apps.helpdesk.api.stats import get_department_stats

        foreign = _dept(db_session, "std1_foreign")
        own = _dept(db_session, "std1_own")
        boss = _user(db_session, "Std1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(
            db_session, own, boss, TODAY - timedelta(days=5),
            perm_codes=[STATS_SUBTREE], role_name="department_head",
        )

        with pytest.raises(HTTPException) as exc:
            get_department_stats(department_id=foreign.id, user=_u(boss), db=db_session)
        assert exc.value.status_code == 403

        result = get_department_stats(department_id=own.id, user=_u(boss), db=db_session)
        assert result["success"] is True

    def test_both_granting_departments_count(self, db_session):
        from itcj2.apps.helpdesk.api.stats import get_department_stats

        dept_a = _dept(db_session, "std2_a")
        dept_b = _dept(db_session, "std2_b")
        boss = _user(db_session, "Std2Boss")

        _position(
            db_session, dept_a, boss, TODAY - timedelta(days=200),
            perm_codes=[STATS_SUBTREE], role_name="department_head",
        )
        # Solo ROL (sin `.subtree` propio): cuenta igual como "propio" vía
        # `app_departments`, aunque `subtree_scope_for(STATS_SUBTREE)` no lo ancle.
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), role_name="department_head")

        result_a = get_department_stats(department_id=dept_a.id, user=_u(boss), db=db_session)
        assert result_a["success"] is True

        result_b = get_department_stats(department_id=dept_b.id, user=_u(boss), db=db_session)
        assert result_b["success"] is True


# ═══════════════════════════ api/assignments.py ═══════════════════════════

class TestAssignmentStats:
    """`get_assignment_stats` (`GET /assignments/stats`)."""

    def test_leak_older_foreign_position_is_excluded(self, db_session):
        from itcj2.apps.helpdesk.api.assignments import get_assignment_stats

        foreign = _dept(db_session, "asg1_foreign")
        own = _dept(db_session, "asg1_own")
        boss = _user(db_session, "Asg1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5), perm_codes=[TICKETS_SUBTREE])

        _ticket(db_session, "ASG1-FOREIGN", boss, foreign, status="PENDING")
        _ticket(db_session, "ASG1-OWN", boss, own, status="PENDING")

        result = get_assignment_stats(user=_u(boss), db=db_session)
        assert result["unassigned"] == 1

    def test_both_granting_departments_count(self, db_session):
        from itcj2.apps.helpdesk.api.assignments import get_assignment_stats

        dept_a = _dept(db_session, "asg2_a")
        dept_b = _dept(db_session, "asg2_b")
        boss = _user(db_session, "Asg2Boss")

        _position(db_session, dept_a, boss, TODAY - timedelta(days=200), perm_codes=[TICKETS_SUBTREE])
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), perm_codes=[TICKETS_OWN])

        _ticket(db_session, "ASG2-A", boss, dept_a, status="PENDING")
        _ticket(db_session, "ASG2-B", boss, dept_b, status="PENDING")

        result = get_assignment_stats(user=_u(boss), db=db_session)
        assert result["unassigned"] == 2

    def test_fallback_direct_grant_uses_all_user_departments(self, db_session):
        from itcj2.apps.helpdesk.api.assignments import get_assignment_stats

        dept_x = _dept(db_session, "asg3_x")
        dept_y = _dept(db_session, "asg3_y")
        plain = _user(db_session, "Asg3Plain")

        _position(db_session, dept_x, plain, TODAY - timedelta(days=100))
        _position(db_session, dept_y, plain, TODAY - timedelta(days=50))
        _direct_perm(db_session, plain, TICKETS_SUBTREE)

        _ticket(db_session, "ASG3-X", plain, dept_x, status="PENDING")
        _ticket(db_session, "ASG3-Y", plain, dept_y, status="PENDING")

        result = get_assignment_stats(user=_u(plain), db=db_session)
        assert result["unassigned"] == 2


# ═══════════════════════════ api/ticket_equipment.py ═══════════════════════════

class TestTicketsByEquipment:
    """`get_tickets_by_equipment` (`GET /tickets/equipment/{item_id}`): usaba
    `get_user_departments` (multi, pero agnóstico) — el bug aquí es LEAK (incluía
    departamentos que no otorgan nada), no omisión: `get_user_departments` ya
    devolvía todos, otorgantes o no. Por eso (b) es solo un control de regresión;
    la propia mecánica de `app_departments` (respaldo) hace que (c) no aplique de
    forma distinta: sin ningún puesto con rol `department_head`, la rama de
    departamento nunca se activa (ver condición del guard), así que el resolver
    de respaldo no tiene un escenario propio que probar aquí más allá de lo que ya
    cubre `test_app_departments.py`.
    """

    def test_leak_older_foreign_position_is_excluded(self, db_session):
        from itcj2.apps.helpdesk.api.ticket_equipment import get_tickets_by_equipment

        foreign = _dept(db_session, "teq1_foreign")
        own = _dept(db_session, "teq1_own")
        boss = _user(db_session, "Teq1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(
            db_session, own, boss, TODAY - timedelta(days=5),
            perm_codes=[TICKETS_SUBTREE], role_name="department_head",
        )

        foreign_item = _item(db_session, "TEQ1-FOREIGN", foreign, boss)
        own_item = _item(db_session, "TEQ1-OWN", own, boss)

        with pytest.raises(HTTPException) as exc:
            get_tickets_by_equipment(
                item_id=foreign_item.id, request=_FakeRequest(), user=_u(boss), db=db_session,
            )
        assert exc.value.status_code == 403

        result = get_tickets_by_equipment(
            item_id=own_item.id, request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result["item_id"] == own_item.id

    def test_both_granting_departments_count(self, db_session):
        from itcj2.apps.helpdesk.api.ticket_equipment import get_tickets_by_equipment

        dept_a = _dept(db_session, "teq2_a")
        dept_b = _dept(db_session, "teq2_b")
        boss = _user(db_session, "Teq2Boss")

        _position(
            db_session, dept_a, boss, TODAY - timedelta(days=200),
            perm_codes=[TICKETS_SUBTREE], role_name="department_head",
        )
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), role_name="department_head")

        item_a = _item(db_session, "TEQ2-A", dept_a, boss)
        item_b = _item(db_session, "TEQ2-B", dept_b, boss)

        result_a = get_tickets_by_equipment(
            item_id=item_a.id, request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result_a["item_id"] == item_a.id

        result_b = get_tickets_by_equipment(
            item_id=item_b.id, request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result_b["item_id"] == item_b.id


# ═══════════════════════════ api/inventory/items.py ═══════════════════════════

class TestDepartmentEquipment:
    """`get_department_equipment` (`GET /inventory/items/department/{id}`): era una
    igualdad contra UN solo departamento (`get_user_department`), así que el bug es
    doble: filtra el ajeno Y omite el propio si no coincide con el "primario"."""

    def test_leak_and_omission_from_single_department_equality(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import items as items_api

        foreign = _dept(db_session, "die1_foreign")
        own = _dept(db_session, "die1_own")
        boss = _user(db_session, "Die1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5),
                  perm_codes=["helpdesk.inventory.api.read.own_dept"])

        with pytest.raises(HTTPException) as exc:
            items_api.get_department_equipment(department_id=foreign.id, user=_u(boss), db=db_session)
        assert exc.value.status_code == 403

        result = items_api.get_department_equipment(department_id=own.id, user=_u(boss), db=db_session)
        assert result["success"] is True

    def test_both_granting_departments_count(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import items as items_api

        dept_a = _dept(db_session, "die2_a")
        dept_b = _dept(db_session, "die2_b")
        boss = _user(db_session, "Die2Boss")

        _position(db_session, dept_a, boss, TODAY - timedelta(days=200),
                  perm_codes=["helpdesk.inventory.api.read.own_dept"])
        # Otorga un permiso de helpdesk SIN relación con inventario: de todas formas
        # ancla `dept_b` como "propio" por procedencia (app_departments es a nivel
        # app, no de módulo).
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), perm_codes=[TICKETS_OWN])

        result = items_api.get_department_equipment(department_id=dept_b.id, user=_u(boss), db=db_session)
        assert result["success"] is True


class TestItemTickets:
    """`get_item_tickets` (`GET /inventory/items/{item_id}/tickets`): rama
    `department_head` con `get_user_department` (agnóstico, un solo depto)."""

    def test_leak_and_omission_from_single_department_equality(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import items as items_api

        foreign = _dept(db_session, "dit1_foreign")
        own = _dept(db_session, "dit1_own")
        boss = _user(db_session, "Dit1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5), role_name="department_head")

        foreign_item = _item(db_session, "DIT1-FOREIGN", foreign, boss)
        own_item = _item(db_session, "DIT1-OWN", own, boss)

        with pytest.raises(HTTPException) as exc:
            items_api.get_item_tickets(
                item_id=foreign_item.id, request=_FakeRequest(), user=_u(boss), db=db_session,
            )
        assert exc.value.status_code == 403

        result = items_api.get_item_tickets(
            item_id=own_item.id, request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result["success"] is True

    def test_both_granting_departments_count(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import items as items_api

        dept_a = _dept(db_session, "dit2_a")
        dept_b = _dept(db_session, "dit2_b")
        boss = _user(db_session, "Dit2Boss")

        _position(db_session, dept_a, boss, TODAY - timedelta(days=200), role_name="department_head")
        _position(db_session, dept_b, boss, TODAY - timedelta(days=5), role_name="department_head")

        item_b = _item(db_session, "DIT2-B", dept_b, boss)

        result = items_api.get_item_tickets(
            item_id=item_b.id, request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result["success"] is True


# ═══════════════════════════ api/inventory/selection.py ═══════════════════════════

class TestSelectionDefaultDepartment:
    """`get_items_for_ticket` / `get_groups_with_items`: sin `?department_id=`,
    usaban `get_user_department` (agnóstico) como default. El default ajeno no solo
    "no ve lo suyo": cae fuera de `visible_department_ids` y responde vacío en vez
    de fallar, así que el síntoma es "no aparece nada" con 200.
    """

    def test_for_ticket_default_department_uses_granting_position(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import selection as selection_api

        foreign = _dept(db_session, "sed1_foreign")
        own = _dept(db_session, "sed1_own")
        boss = _user(db_session, "Sed1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5), perm_codes=[ITEMS_SUBTREE])

        _item(db_session, "SED1-OWN", own, boss, status="ACTIVE")

        result = selection_api.get_items_for_ticket(
            request=_FakeRequest(), user=_u(boss), db=db_session,
        )
        assert result["success"] is True
        numbers = {i["inventory_number"] for i in result["data"]}
        assert numbers == {"SED1-OWN"}, "el default cayó en el depto ajeno (vacío) en vez del propio"

    def test_groups_with_items_default_department_uses_granting_position(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import selection as selection_api

        foreign = _dept(db_session, "sed2_foreign")
        own = _dept(db_session, "sed2_own")
        boss = _user(db_session, "Sed2Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5), perm_codes=[ITEMS_SUBTREE])

        group = _group(db_session, "SED2-GRP", own, boss)
        _item(db_session, "SED2-ITEM", own, boss, status="ACTIVE", group_id=group.id)

        result = selection_api.get_groups_with_items(
            department_id=None, category_id=None, user=_u(boss), db=db_session,
        )
        assert result["success"] is True
        codes = {g["code"] for g in result["data"]}
        assert codes == {"SED2-GRP"}


# ═══════════════════════════ api/inventory/assignments.py ═══════════════════════════

class TestMeScope:
    """`get_my_scope` (`GET /inventory/assignments/me-scope`): `user_dept` venía de
    `get_user_department` (agnóstico) — campo de presentación/default consumido por
    el frontend (no gatea nada), pero debe reflejar el depto que de verdad da acceso."""

    def test_user_dept_field_uses_granting_position_not_oldest(self, db_session):
        from itcj2.apps.helpdesk.api.inventory import assignments as assignments_api

        foreign = _dept(db_session, "mes1_foreign")
        own = _dept(db_session, "mes1_own")
        boss = _user(db_session, "Mes1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5),
                  perm_codes=["helpdesk.inventory.api.assign"])

        result = assignments_api.get_my_scope(user=_u(boss), db=db_session)

        assert result["success"] is True
        assert result["data"]["user_dept"]["id"] == own.id


# ═══════════════════════════ pages/inventory.py ═══════════════════════════

class TestPagesGroupsCtx:
    """`_query_groups_ctx`: `get_user_department` alimentaba tanto el campo
    `department_id` (default de presentación) como el fallback de la lista de
    departamentos cuando el usuario no tiene scope departamental/subárbol
    (`visible_department_ids` vacío). Usa su propio `SessionLocal()` interno, así
    que se parchea para que abra la sesión transaccional del test (mismo problema
    documentado en `test_inventory_write_scope.py` para `validate_department`).

    No se cubre `_query_items_ctx` (el `get_user_department` de ahí es código
    MUERTO: ni `user_dept` ni `user_dept_id` se usan en el resto de la función ni
    en el dict de retorno — se elimina en vez de migrarse) ni `group_detail`
    (mismo swap trivial de un solo valor que `me-scope`, sin lógica propia que
    valga un test dedicado).
    """

    def _patch_session_local(self, db_session, monkeypatch):
        monkeypatch.setattr(db_session, "close", lambda: None)
        monkeypatch.setattr("itcj2.database.SessionLocal", lambda: db_session)

    def test_department_id_field_uses_granting_position_not_oldest(self, db_session, monkeypatch):
        from itcj2.apps.helpdesk.pages import inventory as inv_pages

        self._patch_session_local(db_session, monkeypatch)

        foreign = _dept(db_session, "pgc1_foreign")
        own = _dept(db_session, "pgc1_own")
        boss = _user(db_session, "Pgc1Boss")

        _position(db_session, foreign, boss, TODAY - timedelta(days=500))
        _position(db_session, own, boss, TODAY - timedelta(days=5),
                  perm_codes=["helpdesk.inventory_groups.api.read.own_dept"])

        ctx = inv_pages._query_groups_ctx(_FakeRequest(), boss.id, set())

        assert ctx["department_id"] == own.id

    def test_no_scope_fallback_lists_all_own_departments(self, db_session, monkeypatch):
        """Sin ningún puesto que otorgue acceso departamental/subárbol de grupos
        (`visible_department_ids` vacío): el selector de creación debe listar TODOS
        sus departamentos (respaldo por procedencia), no solo uno."""
        from itcj2.apps.helpdesk.pages import inventory as inv_pages

        self._patch_session_local(db_session, monkeypatch)

        dept_x = _dept(db_session, "pgc2_x")
        dept_y = _dept(db_session, "pgc2_y")
        plain = _user(db_session, "Pgc2Plain")

        _position(db_session, dept_x, plain, TODAY - timedelta(days=100))
        _position(db_session, dept_y, plain, TODAY - timedelta(days=50))

        ctx = inv_pages._query_groups_ctx(_FakeRequest(), plain.id, set())

        assert ctx["can_view_all"] is False
        dept_ids = {d["id"] for d in ctx["departments"]}
        assert dept_ids == {dept_x.id, dept_y.id}

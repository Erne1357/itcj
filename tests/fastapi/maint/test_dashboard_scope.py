"""
Tests DB-backed (Postgres real vía `db_session`) para la coherencia de scope en
`dashboard_service` y `department_dashboard_service` (fix/org-scope-coherence).

La suite vieja (`test_dashboard_visibility.py`) mockea toda la BD, así que no
puede probar nada que dependa de datos reales (ventanas de vigencia, subtree,
conteos agregados). Este archivo cubre justo eso:

  - issue #3: `department_dashboard_service._resolve_user_departments` ignora
    puestos VENCIDOS (`end_date` pasado) aunque `is_active` siga en True.
  - issue #4: los KPIs de `dashboard_service.get_dashboard` cuentan los tickets
    PROPIOS de un departamento anterior tras un cambio de adscripción (antes
    solo `unrated_resolved` los contaba) y `recent_activity` deja de ser un
    subconjunto distinto del resto del mismo dashboard.
  - issue #6: `dept_filter` de un hijo autorizado por `.read.subtree` NO da 403.
  - issue #7: con `dept_filter` los KPIs se acotan de verdad a ESE
    departamento (y su propio subtree), no a todo el subárbol autorizado.

Plantilla de seeding calcada de `test_ticket_list_scope.py`.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.maint.models.action_log import MaintTicketActionLog
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.models.ticket import MaintTicket
from itcj2.apps.maint.services import dashboard_service
from itcj2.apps.maint.services import department_dashboard_service as dds
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User

SUBTREE = "maint.tickets.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="D", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db):
    c = db.query(MaintCategory).filter_by(code="dsc_cat").first()
    if not c:
        c = MaintCategory(code="dsc_cat", name="dsc", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _ticket(db, number, requester, department, status="PENDING"):
    t = MaintTicket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        category_id=_category(db).id,
        priority="MEDIA",
        title=number,
        description="x",
        status=status,
        created_by_id=requester.id,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def _grant_subtree(db, user, department):
    """Puesto VIGENTE con maint.tickets.api.read.subtree anclado en `department`."""
    app = db.query(App).filter_by(key="maint").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm); db.commit(); db.refresh(perm)
    pos = Position(code=f"dsc_pos_{user.id}_{department.id}", title="Jefa",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _expired_position(db, user, department):
    """Puesto VENCIDO (end_date ayer) sin permiso .subtree — solo para probar
    que _resolve_user_departments ya no lo cuenta pese a is_active=True."""
    pos = Position(code=f"dsc_expos_{user.id}_{department.id}", title="ExJefa",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=30),
        end_date=date.today() - timedelta(days=1),
        is_active=True,
    ))
    db.commit()
    return pos


# ─────────────────────────────────────────────────────────────────────────────
# issue #3 — puesto vencido no resuelve departamento
# ─────────────────────────────────────────────────────────────────────────────

def test_expired_position_does_not_resolve_department(db_session):
    dept = _dept(db_session, "dsc_expired")
    user = _user(db_session, "Expired")
    _expired_position(db_session, user, dept)

    depts = dds._resolve_user_departments(db_session, user.id)

    assert depts == []


def test_active_position_still_resolves_department(db_session):
    """Control: un puesto VIGENTE sigue resolviendo (no rompimos el caso feliz)."""
    dept = _dept(db_session, "dsc_active")
    user = _user(db_session, "Active")
    _grant_subtree(db_session, user, dept)

    depts = dds._resolve_user_departments(db_session, user.id)

    assert {d["id"] for d in depts} == {dept.id}


# ─────────────────────────────────────────────────────────────────────────────
# issue #4 — KPIs de dashboard_service incluyen tickets propios de depto viejo
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_kpis_include_own_ticket_from_previous_department(db_session):
    old = _dept(db_session, "dsc_old")
    new = _dept(db_session, "dsc_new")
    boss = _user(db_session, "Boss")
    _grant_subtree(db_session, boss, new)

    _ticket(db_session, "DSC-OLD-1", boss, old)
    _ticket(db_session, "DSC-NEW-1", boss, new)

    data = dashboard_service.get_dashboard(db_session, user_id=boss.id, user_roles=["department_head"])

    assert data["open_total"] == 2
    assert data["by_status"]["PENDING"] == 2


def test_recent_activity_includes_action_from_previous_department(db_session):
    """`recent_activity` (usa _apply_visibility_to_join) ya no es un subconjunto
    distinto del resto del dashboard: el ticket propio del depto anterior
    también debe aparecer en la actividad reciente."""
    old = _dept(db_session, "dsc_old_log")
    new = _dept(db_session, "dsc_new_log")
    boss = _user(db_session, "Logger")
    _grant_subtree(db_session, boss, new)

    legacy = _ticket(db_session, "DSC-LOG-1", boss, old)
    db_session.add(MaintTicketActionLog(
        ticket_id=legacy.id, action="CREATED", performed_by_id=boss.id,
        detail={"ticket_number": legacy.ticket_number},
    ))
    db_session.commit()

    data = dashboard_service.get_dashboard(db_session, user_id=boss.id, user_roles=["department_head"])

    ticket_numbers = {a["ticket_number"] for a in data["recent_activity"]}
    assert "DSC-LOG-1" in ticket_numbers


# ─────────────────────────────────────────────────────────────────────────────
# issue #6 — dept_filter de un hijo autorizado por subtree no da 403
# ─────────────────────────────────────────────────────────────────────────────

def test_dept_filter_of_authorized_child_does_not_raise(db_session):
    root = _dept(db_session, "dsc_root_ok")
    child = _dept(db_session, "dsc_child_ok", root.id)
    boss = _user(db_session, "RootBoss")
    _grant_subtree(db_session, boss, root)

    # No debe lanzar ValueError: antes daba 403 porque `child` no está en
    # user_dept_ids (solo en el subárbol autorizado por procedencia).
    result = dds.get_summary(
        db_session, user_id=boss.id, is_admin_global=False,
        dept_filter=child.id, scope="all",
    )
    assert "kpis" in result


def test_dept_filter_of_unrelated_department_still_raises(db_session):
    """Guard: el fix no abre CUALQUIER departamento, solo el subárbol autorizado."""
    root = _dept(db_session, "dsc_root_guard")
    stranger_dept = _dept(db_session, "dsc_stranger_guard")
    boss = _user(db_session, "GuardBoss")
    _grant_subtree(db_session, boss, root)

    raised = False
    try:
        dds.get_summary(
            db_session, user_id=boss.id, is_admin_global=False,
            dept_filter=stranger_dept.id, scope="all",
        )
    except ValueError:
        raised = True
    assert raised is True


# ─────────────────────────────────────────────────────────────────────────────
# issue #7 — con dept_filter los KPIs se acotan a ESE departamento
# ─────────────────────────────────────────────────────────────────────────────

def test_dept_filter_scopes_kpis_to_requested_department_only(db_session):
    root = _dept(db_session, "dsc_root_scope")
    child_a = _dept(db_session, "dsc_child_a", root.id)
    child_b = _dept(db_session, "dsc_child_b", root.id)
    boss = _user(db_session, "ScopeBoss")
    stranger = _user(db_session, "ScopeStranger")
    _grant_subtree(db_session, boss, root)

    _ticket(db_session, "DSC-A-1", stranger, child_a)
    _ticket(db_session, "DSC-B-1", stranger, child_b)

    # Sin filtro: ve las dos (todo el subárbol autorizado desde root).
    unfiltered = dds.get_summary(
        db_session, user_id=boss.id, is_admin_global=False,
        dept_filter=None, scope="all",
    )
    assert unfiltered["kpis"]["open_total"] == 2

    # Filtrando a child_a: solo debe contar 1 (el propio subtree de child_a),
    # NO los 2 — antes el filtro quedaba anulado por scope="all" (issue #7).
    filtered = dds.get_summary(
        db_session, user_id=boss.id, is_admin_global=False,
        dept_filter=child_a.id, scope="all",
    )
    assert filtered["kpis"]["open_total"] == 1

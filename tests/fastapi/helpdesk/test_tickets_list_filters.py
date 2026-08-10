"""Filtros nuevos de `/help-desk/admin/tickets-list`: técnico asignado, categoría,
departamento del solicitante, rango de fechas y orden — más la ampliación de la
búsqueda libre a nombre de solicitante/asignado.

Dos niveles:
  - `_parse_tickets_filters` (pages/admin.py) es una función PURA (sin BD) que
    mapea query params → kwargs de `ticket_service.list_tickets` + valores de
    display. Se prueba con dicts planos, sin BD ni HTTP.
  - `ticket_service.list_tickets` se prueba contra Postgres real (`db_session`,
    mismo patrón que `test_ticket_list_scope.py`) para la lógica de filtrado,
    orden y — el caso crítico — que `req_department` INTERSECTA el scope
    departamental visible del usuario y nunca lo sustituye (fail-closed).
"""
from datetime import date, datetime, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.pages.admin import _build_filter_chips, _parse_tickets_filters
from itcj2.apps.helpdesk.services.assignment_service import get_technicians_by_area
from itcj2.apps.helpdesk.services.ticket_service import list_tickets
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "helpdesk.tickets.api.read.subtree"


# ---------------------------------------------------------------------------
# Fixtures compartidas (mismo estilo que test_ticket_list_scope.py)
# ---------------------------------------------------------------------------

def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _user(db, last, is_active=True):
    u = User(first_name="T", last_name=last, is_active=is_active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db, code, area="SOPORTE"):
    c = db.query(Category).filter_by(code=code).first()
    if not c:
        c = Category(area=area, code=code, name=code, is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department, assigned_to=None, assigned_to_team=None,
            category=None, priority="MEDIA", created_at=None, updated_at=None):
    t = Ticket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id if department else None,
        area="SOPORTE",
        category_id=(category or _category(db, "tlf_default")).id,
        priority=priority,
        title=number,
        description="x",
        status="PENDING",
        assigned_to_user_id=assigned_to.id if assigned_to else None,
        assigned_to_team=assigned_to_team,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    if created_at:
        t.created_at = created_at
    if updated_at:
        t.updated_at = updated_at
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _grant_subtree(db, user, department):
    """Ancla al usuario en `department` con un puesto que otorga `.subtree`."""
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm)
        db.commit()
        db.refresh(perm)
    pos = Position(code=f"tlf_pos_{user.id}", title="Jefa", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _make_technician(db, last, area, is_active=True):
    """Usuario con el rol tech_<area> en helpdesk (vía UserAppRole, como lo lee
    `get_technicians_by_area`)."""
    app = db.query(App).filter_by(key="helpdesk").first()
    role_name = f"tech_{area.lower()}"
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name)
        db.add(role)
        db.commit()
        db.refresh(role)
    u = _user(db, last, is_active=is_active)
    db.add(UserAppRole(user_id=u.id, app_id=app.id, role_id=role.id))
    db.commit()
    return u


def _numbers(result):
    return {t["ticket_number"] for t in result["tickets"]}


def _order(result):
    return [t["ticket_number"] for t in result["tickets"]]


# ---------------------------------------------------------------------------
# _parse_tickets_filters — función pura, sin BD
# ---------------------------------------------------------------------------

def test_parse_technician_numeric():
    parsed = _parse_tickets_filters({"technician": "42"})
    assert parsed["kwargs"]["assigned_to_user_id"] == 42
    assert parsed["kwargs"]["unassigned"] is False
    assert parsed["kwargs"]["assigned_to_team"] is None
    assert parsed["display"]["f_technician"] == "42"
    assert parsed["more_active"] is True


def test_parse_technician_unassigned():
    parsed = _parse_tickets_filters({"technician": "unassigned"})
    assert parsed["kwargs"]["unassigned"] is True
    assert parsed["kwargs"]["assigned_to_user_id"] is None
    assert parsed["display"]["f_technician"] == "unassigned"


def test_parse_technician_team_queue():
    parsed = _parse_tickets_filters({"technician": "team:desarrollo"})
    assert parsed["kwargs"]["assigned_to_team"] == "desarrollo"
    assert parsed["kwargs"]["assigned_to_user_id"] is None
    assert parsed["kwargs"]["unassigned"] is False
    assert parsed["display"]["f_technician"] == "team:desarrollo"


def test_parse_technician_invalid_value_ignored():
    parsed = _parse_tickets_filters({"technician": "not-a-thing"})
    assert parsed["kwargs"]["assigned_to_user_id"] is None
    assert parsed["kwargs"]["unassigned"] is False
    assert parsed["kwargs"]["assigned_to_team"] is None
    assert parsed["display"]["f_technician"] == ""
    assert parsed["more_active"] is False


def test_parse_category():
    parsed = _parse_tickets_filters({"category": "7"})
    assert parsed["kwargs"]["category_id"] == 7
    assert parsed["display"]["f_category"] == "7"


def test_parse_req_department():
    parsed = _parse_tickets_filters({"req_department": "9"})
    assert parsed["kwargs"]["department_ids"] == {9}
    assert parsed["display"]["f_req_department"] == "9"


def test_parse_req_department_non_numeric_ignored():
    parsed = _parse_tickets_filters({"req_department": "abc"})
    assert parsed["kwargs"]["department_ids"] is None
    assert parsed["display"]["f_req_department"] == ""


def test_parse_date_range():
    parsed = _parse_tickets_filters({"start": "2026-01-01", "end": "2026-01-31"})
    assert parsed["kwargs"]["created_from"] == date(2026, 1, 1)
    assert parsed["kwargs"]["created_to"] == date(2026, 1, 31)
    assert parsed["display"]["f_start"] == "2026-01-01"
    assert parsed["display"]["f_end"] == "2026-01-31"


def test_parse_invalid_dates_ignored():
    parsed = _parse_tickets_filters({"start": "not-a-date", "end": "also-not"})
    assert parsed["kwargs"]["created_from"] is None
    assert parsed["kwargs"]["created_to"] is None
    assert parsed["display"]["f_start"] == ""
    assert parsed["display"]["f_end"] == ""


def test_parse_sort_variants():
    for raw, expected in [("recent", "recent"), ("", "recent"), ("oldest", "oldest"),
                           ("priority", "priority"), ("stale", "stale"), ("bogus", "recent")]:
        parsed = _parse_tickets_filters({"sort": raw})
        assert parsed["kwargs"]["sort"] == expected, raw


def test_parse_more_active_flag_false_with_only_original_filters():
    parsed = _parse_tickets_filters({"status": "PENDING", "area": "SOPORTE",
                                      "priority": "ALTA", "search": "foo"})
    assert parsed["more_active"] is False


def test_parse_more_active_flag_true_with_any_new_filter():
    for qp in ({"technician": "5"}, {"category": "1"}, {"req_department": "2"},
               {"start": "2026-01-01"}, {"end": "2026-01-01"}, {"sort": "oldest"}):
        assert _parse_tickets_filters(qp)["more_active"] is True, qp


# ---------------------------------------------------------------------------
# list_tickets — filtros nuevos contra Postgres real
# ---------------------------------------------------------------------------

def test_filter_by_technician_numeric(db_session):
    dept = _dept(db_session, "tlf_dept_a")
    requester = _user(db_session, "Req")
    tech_a = _make_technician(db_session, "TechA", "SOPORTE")
    tech_b = _make_technician(db_session, "TechB", "SOPORTE")
    _ticket(db_session, "TLF-A-1", requester, dept, assigned_to=tech_a)
    _ticket(db_session, "TLF-B-1", requester, dept, assigned_to=tech_b)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(),
                           assigned_to_user_id=tech_a.id)

    assert _numbers(result) == {"TLF-A-1"}


def test_filter_unassigned(db_session):
    dept = _dept(db_session, "tlf_dept_b")
    requester = _user(db_session, "Req2")
    tech = _make_technician(db_session, "TechC", "SOPORTE")
    _ticket(db_session, "TLF-UNASG-1", requester, dept)
    _ticket(db_session, "TLF-ASG-1", requester, dept, assigned_to=tech)
    _ticket(db_session, "TLF-TEAM-1", requester, dept, assigned_to_team="soporte")

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), unassigned=True)

    assert _numbers(result) == {"TLF-UNASG-1"}


def test_filter_by_team_queue(db_session):
    dept = _dept(db_session, "tlf_dept_c")
    requester = _user(db_session, "Req3")
    _ticket(db_session, "TLF-QD-1", requester, dept, assigned_to_team="desarrollo")
    _ticket(db_session, "TLF-QS-1", requester, dept, assigned_to_team="soporte")
    _ticket(db_session, "TLF-NONE-1", requester, dept)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(),
                           assigned_to_team="desarrollo")

    assert _numbers(result) == {"TLF-QD-1"}


def test_filter_by_category(db_session):
    dept = _dept(db_session, "tlf_dept_d")
    requester = _user(db_session, "Req4")
    cat_a = _category(db_session, "tlf_cat_a")
    cat_b = _category(db_session, "tlf_cat_b")
    _ticket(db_session, "TLF-CA-1", requester, dept, category=cat_a)
    _ticket(db_session, "TLF-CB-1", requester, dept, category=cat_b)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(),
                           category_id=cat_a.id)

    assert _numbers(result) == {"TLF-CA-1"}


def test_filter_by_date_range(db_session):
    dept = _dept(db_session, "tlf_dept_e")
    requester = _user(db_session, "Req5")
    _ticket(db_session, "TLF-OLD-1", requester, dept, created_at=datetime(2025, 1, 1, 10, 0))
    _ticket(db_session, "TLF-IN-1", requester, dept, created_at=datetime(2026, 1, 15, 10, 0))
    _ticket(db_session, "TLF-NEW-1", requester, dept, created_at=datetime(2026, 3, 1, 10, 0))

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(),
                           created_from=date(2026, 1, 1), created_to=date(2026, 1, 31))

    assert _numbers(result) == {"TLF-IN-1"}


def test_date_range_end_is_inclusive_of_whole_day(db_session):
    dept = _dept(db_session, "tlf_dept_e2")
    requester = _user(db_session, "Req5b")
    _ticket(db_session, "TLF-ENDDAY-1", requester, dept, created_at=datetime(2026, 1, 31, 23, 30))

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(),
                           created_from=date(2026, 1, 31), created_to=date(2026, 1, 31))

    assert _numbers(result) == {"TLF-ENDDAY-1"}


def test_sort_recent_is_default(db_session):
    dept = _dept(db_session, "tlf_dept_f")
    requester = _user(db_session, "Req6")
    _ticket(db_session, "TLF-S1", requester, dept, created_at=datetime(2026, 1, 1))
    _ticket(db_session, "TLF-S2", requester, dept, created_at=datetime(2026, 2, 1))

    result = list_tickets(db_session, user_id=requester.id, user_roles=set())

    assert _order(result) == ["TLF-S2", "TLF-S1"]


def test_sort_oldest(db_session):
    dept = _dept(db_session, "tlf_dept_g")
    requester = _user(db_session, "Req7")
    _ticket(db_session, "TLF-O1", requester, dept, created_at=datetime(2026, 1, 1))
    _ticket(db_session, "TLF-O2", requester, dept, created_at=datetime(2026, 2, 1))

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), sort="oldest")

    assert _order(result) == ["TLF-O1", "TLF-O2"]


def test_sort_priority(db_session):
    dept = _dept(db_session, "tlf_dept_h")
    requester = _user(db_session, "Req8")
    _ticket(db_session, "TLF-P-BAJA", requester, dept, priority="BAJA")
    _ticket(db_session, "TLF-P-URGENTE", requester, dept, priority="URGENTE")
    _ticket(db_session, "TLF-P-MEDIA", requester, dept, priority="MEDIA")

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), sort="priority")

    assert _order(result) == ["TLF-P-URGENTE", "TLF-P-MEDIA", "TLF-P-BAJA"]


def test_sort_stale(db_session):
    dept = _dept(db_session, "tlf_dept_i")
    requester = _user(db_session, "Req9")
    _ticket(db_session, "TLF-ST1", requester, dept, updated_at=datetime(2026, 2, 1))
    _ticket(db_session, "TLF-ST2", requester, dept, updated_at=datetime(2026, 1, 1))

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), sort="stale")

    assert _order(result) == ["TLF-ST2", "TLF-ST1"]


def test_search_by_requester_name(db_session):
    dept = _dept(db_session, "tlf_dept_j")
    requester = _user(db_session, "Zapatero")
    other = _user(db_session, "Otro")
    _ticket(db_session, "TLF-REQ-1", requester, dept)
    _ticket(db_session, "TLF-REQ-2", other, dept)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), search="Zapatero")

    assert _numbers(result) == {"TLF-REQ-1"}


def test_search_by_assignee_name(db_session):
    dept = _dept(db_session, "tlf_dept_k")
    requester = _user(db_session, "Req10")
    tech = _make_technician(db_session, "Marquez", "SOPORTE")
    other_tech = _make_technician(db_session, "Otro2", "SOPORTE")
    _ticket(db_session, "TLF-ASGN-1", requester, dept, assigned_to=tech)
    _ticket(db_session, "TLF-ASGN-2", requester, dept, assigned_to=other_tech)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), search="Marquez")

    assert _numbers(result) == {"TLF-ASGN-1"}


def test_search_still_matches_title_and_ticket_number(db_session):
    """Guard de no-regresión: el join nuevo no debe romper los campos que ya
    buscaba (title/ticket_number/description)."""
    dept = _dept(db_session, "tlf_dept_l")
    requester = _user(db_session, "Req11")
    _ticket(db_session, "TLF-UNIQNUM-1", requester, dept)
    _ticket(db_session, "TLF-OTHER-1", requester, dept)

    result = list_tickets(db_session, user_id=requester.id, user_roles=set(), search="UNIQNUM")

    assert _numbers(result) == {"TLF-UNIQNUM-1"}


# ---------------------------------------------------------------------------
# req_department — INTERSECTA el scope, nunca lo sustituye (invariante de
# seguridad no negociable)
# ---------------------------------------------------------------------------

def test_req_department_denies_department_outside_scope(db_session):
    """Un jefe con subtree en su propio departamento NO puede ver otro
    departamento ajeno pasando ?req_department=<otro>."""
    mine = _dept(db_session, "tlf_scope_mine")
    foreign = _dept(db_session, "tlf_scope_foreign")
    boss = _user(db_session, "Boss")
    stranger = _user(db_session, "Stranger")
    _grant_subtree(db_session, boss, mine)
    _ticket(db_session, "TLF-FOREIGN-1", stranger, foreign)

    result = list_tickets(db_session, user_id=boss.id, user_roles=set(),
                           department_ids={foreign.id})

    assert _numbers(result) == set()


def test_req_department_allows_own_scope(db_session):
    mine = _dept(db_session, "tlf_scope_mine2")
    child = _dept(db_session, "tlf_scope_child2", mine.id)
    boss = _user(db_session, "Boss2")
    stranger = _user(db_session, "Stranger2")
    _grant_subtree(db_session, boss, mine)
    _ticket(db_session, "TLF-MINE-1", stranger, mine)
    _ticket(db_session, "TLF-CHILD-1", stranger, child)

    result = list_tickets(db_session, user_id=boss.id, user_roles=set(),
                           department_ids={mine.id})

    assert _numbers(result) == {"TLF-MINE-1"}  # exacto, sin expandir a subárbol


def test_req_department_fail_closed_without_department(db_session):
    """department_head sin puesto/departamento resoluble: SIN el filtro ya no ve
    tickets ajenos (solo lo propio); CON el filtro tampoco se le abre nada."""
    other_dept = _dept(db_session, "tlf_scope_nogrant")
    boss = _user(db_session, "NoDept")
    stranger = _user(db_session, "Stranger3")
    _ticket(db_session, "TLF-NOGRANT-1", stranger, other_dept)

    result = list_tickets(db_session, user_id=boss.id, user_roles={"department_head"},
                           department_ids={other_dept.id})

    assert _numbers(result) == set()


def test_req_department_owner_still_sees_own_ticket_outside_scope(db_session):
    """La propiedad NUNCA se pierde: si el jefe es el solicitante del ticket, el
    filtro de depto solo lo esconde si NO coincide — pero si coincide (porque el
    ticket se creó ahí) sigue viéndolo, igual que list_tickets sin filtro."""
    foreign = _dept(db_session, "tlf_scope_ownerdept")
    boss = _user(db_session, "OwnerBoss")
    mine = _dept(db_session, "tlf_scope_ownerdept_mine")
    _grant_subtree(db_session, boss, mine)
    own_ticket = _ticket(db_session, "TLF-OWNFOREIGN-1", boss, foreign)

    result = list_tickets(db_session, user_id=boss.id, user_roles=set(),
                           department_ids={foreign.id})

    assert _numbers(result) == {"TLF-OWNFOREIGN-1"}


# ---------------------------------------------------------------------------
# get_technicians_by_area — DISTINCT + solo activos
# ---------------------------------------------------------------------------

def test_get_technicians_by_area_excludes_inactive(db_session):
    active = _make_technician(db_session, "Active1", "DESARROLLO")
    _make_technician(db_session, "Inactive1", "DESARROLLO", is_active=False)

    techs = get_technicians_by_area(db_session, "DESARROLLO")

    ids = [t.id for t in techs]
    assert active.id in ids
    assert len(ids) == len(set(ids))  # sin duplicados


def test_get_technicians_by_area_scoped_to_area(db_session):
    dev = _make_technician(db_session, "DevOnly", "DESARROLLO")
    sup = _make_technician(db_session, "SupOnly", "SOPORTE")

    techs = get_technicians_by_area(db_session, "DESARROLLO")

    ids = {t.id for t in techs}
    assert dev.id in ids
    assert sup.id not in ids


# ---------------------------------------------------------------------------
# _build_filter_chips — labels legibles por lookup puntual
# ---------------------------------------------------------------------------

def test_chips_empty_when_no_filters(db_session):
    raw = {"status": "", "area": None, "priority": None, "search": None,
           "technician": "", "category": "", "req_department": "", "start": "", "end": "", "sort": ""}
    assert _build_filter_chips(db_session, raw) == []


def test_chips_status_area_priority_search_labels(db_session):
    raw = {"status": "PENDING", "area": "SOPORTE", "priority": "ALTA", "search": "foo",
           "technician": "", "category": "", "req_department": "", "start": "", "end": "", "sort": ""}
    chips = _build_filter_chips(db_session, raw)
    by_param = {c["param"]: c["label"] for c in chips}
    assert by_param["status"] == "Estado: Pendiente"
    assert by_param["area"] == "Área: Soporte"
    assert by_param["priority"] == "Prioridad: Alta"
    assert by_param["search"] == "Buscar: foo"


def test_chips_resolve_technician_name(db_session):
    tech = _make_technician(db_session, "ChipTech", "SOPORTE")
    raw = {"status": "", "area": None, "priority": None, "search": None,
           "technician": str(tech.id), "category": "", "req_department": "", "start": "", "end": "", "sort": ""}
    chips = _build_filter_chips(db_session, raw)
    assert any(c["param"] == "technician" and "ChipTech" in c["label"] for c in chips)


def test_chips_resolve_category_and_department_names(db_session):
    cat = _category(db_session, "tlf_chip_cat")
    dept = _dept(db_session, "tlf_chip_dept")
    raw = {"status": "", "area": None, "priority": None, "search": None,
           "technician": "", "category": str(cat.id), "req_department": str(dept.id),
           "start": "2026-01-01", "end": "2026-01-31", "sort": "oldest"}
    chips = _build_filter_chips(db_session, raw)
    by_param = {c["param"]: c["label"] for c in chips}
    assert cat.name in by_param["category"]
    assert dept.name in by_param["req_department"]
    assert by_param["start"] == "Desde: 2026-01-01"
    assert by_param["end"] == "Hasta: 2026-01-31"
    assert by_param["sort"] == "Orden: Más antiguos"

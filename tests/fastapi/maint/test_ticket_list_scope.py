"""`list_tickets` de maint debe otorgar el mismo conjunto que `can_user_view_ticket`.

`can_user_view_ticket` es ADITIVO (propio ∨ asignado ∨ área ∨ coordinación ∨
departamento/subárbol), pero `list_tickets` ramificaba con `if/elif` excluyentes y
la rama departamental no incluía la propiedad. Consecuencias: quien cambia de
departamento pierde de su listado los tickets que él mismo creó (el
`requester_department_id` es un snapshot), y quien tiene dos roles pierde el scope
de uno de ellos — en ambos casos el detalle sí abre y la lista no lo muestra.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.maint.services.ticket_service import can_user_view_ticket, list_tickets
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.models.ticket import MaintTicket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "maint.tickets.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="M", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db):
    c = db.query(MaintCategory).filter_by(code="mls_cat").first()
    if not c:
        c = MaintCategory(code="mls_cat", name="mls", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _ticket(db, number, requester, department):
    t = MaintTicket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        category_id=_category(db).id,
        priority="MEDIA",
        title=number,
        description="x",
        status="PENDING",
        created_by_id=requester.id,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def _grant_subtree(db, user, department):
    app = db.query(App).filter_by(key="maint").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm); db.commit(); db.refresh(perm)
    pos = Position(code=f"mls_pos_{user.id}", title="Jefa", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _numbers(result):
    return {t.ticket_number for t in result["tickets"]}


def test_own_ticket_from_previous_department_still_listed(db_session):
    old = _dept(db_session, "mls_old")
    new = _dept(db_session, "mls_new")
    boss = _user(db_session, "Boss")
    _grant_subtree(db_session, boss, new)

    legacy = _ticket(db_session, "MLS-OLD-1", boss, old)
    _ticket(db_session, "MLS-NEW-1", boss, new)

    numbers = _numbers(list_tickets(db_session, user_id=boss.id, user_roles=set()))

    assert {"MLS-OLD-1", "MLS-NEW-1"} <= numbers
    assert can_user_view_ticket(db_session, legacy, boss.id) is True


def test_requester_me_filter_keeps_previous_department(db_session):
    """El chip "Mis solicitudes" no puede quedarse vacío por un cambio de adscripción."""
    old = _dept(db_session, "mls_r_old")
    new = _dept(db_session, "mls_r_new")
    boss = _user(db_session, "Chip")
    _grant_subtree(db_session, boss, new)
    _ticket(db_session, "MLS-CHIP-1", boss, old)

    result = list_tickets(db_session, user_id=boss.id, user_roles=set(), requester_me=True)

    assert _numbers(result) == {"MLS-CHIP-1"}


def test_subtree_scope_still_excludes_other_branch(db_session):
    """Guard: la propiedad suma, no abre la rama hermana ni el padre."""
    root = _dept(db_session, "mls_root")
    mine = _dept(db_session, "mls_sub", root.id)
    leaf = _dept(db_session, "mls_leaf", mine.id)
    sibling = _dept(db_session, "mls_sibling", root.id)
    boss = _user(db_session, "Head")
    stranger = _user(db_session, "Ajeno")
    _grant_subtree(db_session, boss, mine)

    _ticket(db_session, "MLS-SUB-1", stranger, mine)
    _ticket(db_session, "MLS-LEAF-1", stranger, leaf)
    sibling_ticket = _ticket(db_session, "MLS-SIB-1", stranger, sibling)
    parent_ticket = _ticket(db_session, "MLS-ROOT-1", stranger, root)

    numbers = _numbers(list_tickets(db_session, user_id=boss.id, user_roles=set()))

    assert {"MLS-SUB-1", "MLS-LEAF-1"} <= numbers
    assert "MLS-SIB-1" not in numbers
    assert "MLS-ROOT-1" not in numbers
    assert can_user_view_ticket(db_session, sibling_ticket, boss.id) is False
    assert can_user_view_ticket(db_session, parent_ticket, boss.id) is False


def test_department_scope_is_additive_for_technicians(db_session):
    """Un técnico que además es jefe de departamento ve las dos cosas.

    Antes las ramas eran `if/elif`: la de `tech_maint` ganaba y el scope
    departamental desaparecía de la lista, aunque el detalle sí lo concedía.
    """
    dept = _dept(db_session, "mls_tech_dept")
    tech = _user(db_session, "TechHead")
    stranger = _user(db_session, "Otro")
    _grant_subtree(db_session, tech, dept)

    own = _ticket(db_session, "MLS-TECH-OWN", tech, dept)
    from_dept = _ticket(db_session, "MLS-TECH-DEPT", stranger, dept)

    numbers = _numbers(list_tickets(db_session, user_id=tech.id, user_roles={"tech_maint"}))

    assert {"MLS-TECH-OWN", "MLS-TECH-DEPT"} <= numbers
    assert can_user_view_ticket(db_session, own, tech.id) is True
    assert can_user_view_ticket(db_session, from_dept, tech.id) is True

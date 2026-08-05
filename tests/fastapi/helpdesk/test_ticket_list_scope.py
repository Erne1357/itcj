"""`list_tickets` debe otorgar el MISMO conjunto que `can_user_view_ticket`.

El scope departamental (`.subtree`) es ADITIVO: se SUMA a la visibilidad por
propiedad (soy el solicitante / me lo asignaron), nunca la reemplaza. Cuando una
persona cambia de departamento, sus tickets viejos conservan el
`requester_department_id` con el que se crearon (snapshot), así que un filtro
departamental en AND los borraría de "Mis Tickets".
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.ticket_service import can_user_view_ticket, list_tickets
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "helpdesk.tickets.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db):
    c = db.query(Category).filter_by(code="tls_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="tls_cat", name="tls", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _ticket(db, number, requester, department, assigned_to=None):
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


def _grant_subtree(db, user, department):
    """Ancla al usuario en `department` con un puesto que otorga `.subtree`."""
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm)
        db.commit()
        db.refresh(perm)
    pos = Position(code=f"tls_pos_{user.id}", title="Jefa", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _numbers(result):
    return {t["ticket_number"] for t in result["tickets"]}


def test_own_ticket_from_previous_department_still_listed(db_session):
    """Caso real: la jefa se mudó de Gestión a un sub-depto nuevo. Sus tickets
    viejos siguen sellados con Gestión — deben seguir saliendo en Mis Tickets."""
    old = _dept(db_session, "tls_old")
    new = _dept(db_session, "tls_new")
    boss = _user(db_session, "Boss")
    _grant_subtree(db_session, boss, new)

    legacy = _ticket(db_session, "TLS-OLD-1", boss, old)   # creado antes del cambio
    current = _ticket(db_session, "TLS-NEW-1", boss, new)  # creado después

    result = list_tickets(db_session, user_id=boss.id, user_roles=set(), created_by_me=True)

    assert _numbers(result) == {"TLS-OLD-1", "TLS-NEW-1"}
    # Coherencia lista ↔ detalle: lo que se lista debe abrir, y viceversa.
    assert can_user_view_ticket(db_session, legacy, boss.id) is True
    assert can_user_view_ticket(db_session, current, boss.id) is True


def test_assigned_ticket_outside_scope_is_listed(db_session):
    """`can_user_view_ticket` ya deja ver un ticket asignado a uno mismo aunque
    sea de otro departamento; el listado debe coincidir."""
    mine = _dept(db_session, "tls_mine")
    foreign = _dept(db_session, "tls_foreign")
    boss = _user(db_session, "Assignee")
    other = _user(db_session, "Stranger")
    _grant_subtree(db_session, boss, mine)

    assigned = _ticket(db_session, "TLS-ASG-1", other, foreign, assigned_to=boss)

    result = list_tickets(db_session, user_id=boss.id, user_roles=set())

    assert "TLS-ASG-1" in _numbers(result)
    assert can_user_view_ticket(db_session, assigned, boss.id) is True


def test_subtree_scope_still_excludes_other_branch(db_session):
    """Guard: la propiedad suma, no abre el listado a la rama hermana."""
    root = _dept(db_session, "tls_root")
    mine = _dept(db_session, "tls_sub", root.id)
    leaf = _dept(db_session, "tls_leaf", mine.id)
    sibling = _dept(db_session, "tls_sibling", root.id)
    boss = _user(db_session, "Head")
    stranger = _user(db_session, "Ajeno")
    _grant_subtree(db_session, boss, mine)

    _ticket(db_session, "TLS-SUB-1", stranger, mine)
    _ticket(db_session, "TLS-LEAF-1", stranger, leaf)
    sibling_ticket = _ticket(db_session, "TLS-SIB-1", stranger, sibling)
    parent_ticket = _ticket(db_session, "TLS-ROOT-1", stranger, root)

    numbers = _numbers(list_tickets(db_session, user_id=boss.id, user_roles=set()))

    assert {"TLS-SUB-1", "TLS-LEAF-1"} <= numbers          # su subárbol
    assert "TLS-SIB-1" not in numbers                       # rama hermana
    assert "TLS-ROOT-1" not in numbers                      # nunca hacia arriba
    assert can_user_view_ticket(db_session, sibling_ticket, boss.id) is False
    assert can_user_view_ticket(db_session, parent_ticket, boss.id) is False

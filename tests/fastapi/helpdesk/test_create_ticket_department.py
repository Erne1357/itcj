"""El departamento que se sella al crear un ticket decide todo el scope posterior.

`create_ticket` resolvía el puesto con `filter_by(user_id=..., is_active=True).first()`:
sin ventana de vigencia y sin orden. Un puesto vencido —o, con varios puestos, el
que Postgres devolviera primero— podía sellar `requester_department_id` con un
departamento equivocado, y ese ticket queda invisible para el jefe correcto de
forma permanente: el campo es un snapshot que nadie recalcula.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.ticket_service import create_ticket
from itcj2.apps.helpdesk.models.category import Category
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition

TODAY = date.today()


def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _category(db):
    """Categoría real del catálogo: create_ticket valida área y prioridad en BD."""
    return db.query(Category).filter_by(is_active=True).first()


def _assign(db, user, dept, code, start, end=None):
    pos = Position(code=code, title=code, department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=start, end_date=end, is_active=True))
    db.commit()


def _create(db, user, category):
    return create_ticket(
        db, requester_id=user.id, area=category.area, category_id=category.id,
        title="ctd", description="ctd", priority="MEDIA",
    )


def test_expired_position_does_not_seal_the_ticket(db_session):
    """El puesto vencido no debe ganar sobre el vigente."""
    category = _category(db_session)
    assert category is not None, "el catálogo de categorías está vacío"

    old = _dept(db_session, "ctd_old")
    current = _dept(db_session, "ctd_current")
    u = User(first_name="C", last_name="Sealed", is_active=True)
    db_session.add(u); db_session.commit(); db_session.refresh(u)

    # El vencido se crea primero a propósito: es el que devolvía `.first()`.
    _assign(db_session, u, old, "ctd_pos_old",
            TODAY - timedelta(days=100), end=TODAY - timedelta(days=1))
    _assign(db_session, u, current, "ctd_pos_current", TODAY - timedelta(days=10))

    ticket = _create(db_session, u, category)

    assert ticket.requester_department_id == current.id


def test_position_with_future_start_does_not_seal_the_ticket(db_session):
    category = _category(db_session)
    future = _dept(db_session, "ctd_future")
    active = _dept(db_session, "ctd_active")
    u = User(first_name="C", last_name="Future", is_active=True)
    db_session.add(u); db_session.commit(); db_session.refresh(u)

    _assign(db_session, u, future, "ctd_pos_future", TODAY + timedelta(days=30))
    _assign(db_session, u, active, "ctd_pos_active", TODAY - timedelta(days=5))

    ticket = _create(db_session, u, category)

    assert ticket.requester_department_id == active.id


def test_user_without_active_position_seals_no_department(db_session):
    category = _category(db_session)
    u = User(first_name="C", last_name="Orphan", is_active=True)
    db_session.add(u); db_session.commit(); db_session.refresh(u)

    ticket = _create(db_session, u, category)

    assert ticket.requester_department_id is None

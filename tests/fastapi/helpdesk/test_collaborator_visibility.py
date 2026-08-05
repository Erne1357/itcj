"""Quien colabora en un ticket puede abrirlo.

`GET /tickets/collaborations/me` lista los tickets donde el usuario colaboró, pero
`can_user_view_ticket` no reconocía al colaborador: un residente o prestador de
servicio social veía el ticket en su lista y recibía 403 al hacer clic.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.ticket_service import can_user_view_ticket
from itcj2.apps.helpdesk.services.collaborator_service import (
    get_tickets_where_user_collaborated,
)
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.collaborator import TicketCollaborator
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.models.department import Department
from itcj2.core.models.user import User


def _category(db):
    c = db.query(Category).filter_by(code="col_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="col_cat", name="col", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _user(db, last):
    u = User(first_name="C", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _ticket(db, number, requester, department):
    t = Ticket(
        ticket_number=number, requester_id=requester.id,
        requester_department_id=department.id, area="SOPORTE",
        category_id=_category(db).id, priority="MEDIA", title=number,
        description="x", status="PENDING",
        created_by_id=requester.id, updated_by_id=requester.id,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_collaborator_can_open_the_ticket_it_lists(db_session):
    dept = Department(code="col_dept", name="col", is_active=True)
    db_session.add(dept); db_session.commit(); db_session.refresh(dept)
    owner = _user(db_session, "Owner")
    helper = _user(db_session, "Helper")
    ticket = _ticket(db_session, "COL-0001", owner, dept)

    db_session.add(TicketCollaborator(
        ticket_id=ticket.id, user_id=helper.id,
        collaboration_role="COLLABORATOR", added_by_id=owner.id,
    ))
    db_session.commit()

    listed = get_tickets_where_user_collaborated(db_session, helper.id)
    assert "COL-0001" in {t["ticket_number"] for t in listed["tickets"]}

    # Lo que se lista, se abre.
    assert can_user_view_ticket(db_session, ticket, helper.id) is True


def test_non_collaborator_still_cannot_open_it(db_session):
    dept = Department(code="col_dept2", name="col2", is_active=True)
    db_session.add(dept); db_session.commit(); db_session.refresh(dept)
    owner = _user(db_session, "Owner2")
    stranger = _user(db_session, "Stranger")
    ticket = _ticket(db_session, "COL-0002", owner, dept)

    assert can_user_view_ticket(db_session, ticket, stranger.id) is False

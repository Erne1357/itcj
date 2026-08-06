"""`/department-head/pending-tasks` debe ser fail-closed y subtree-aware.

Dos `# TODO` dejaban el endpoint sin filtro cuando el usuario no tenía puesto
vigente: devolvía las campañas PENDING_VALIDATION y los tickets sin calificar de
TODA la institución. Y cuando sí tenía puesto, filtraba por igualdad contra el
departamento primario, así que un jefe con `.read.subtree` no veía las tareas
pendientes de sus sub-departamentos que su propia lista de tickets sí muestra.
"""
from datetime import date, datetime, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.api.department_head import get_pending_tasks
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

SUBTREE = "helpdesk.tickets.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="D", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db):
    c = db.query(Category).filter_by(code="dhp_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="dhp_cat", name="dhp", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _unrated_ticket(db, number, requester, department):
    t = Ticket(
        ticket_number=number, requester_id=requester.id,
        requester_department_id=department.id, area="SOPORTE",
        category_id=_category(db).id, priority="MEDIA", title=number,
        description="x", status="RESOLVED_SUCCESS",
        resolved_at=datetime.utcnow() - timedelta(days=1),
        created_by_id=requester.id, updated_by_id=requester.id,
    )
    db.add(t); db.commit()
    return t


def _campaign(db, folio, department, creator):
    c = InventoryCampaign(
        folio=folio, department_id=department.id, status="PENDING_VALIDATION",
        title=folio, created_by_id=creator.id,
    )
    db.add(c); db.commit()
    return c


def _grant_subtree(db, user, department):
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = db.query(Permission).filter_by(app_id=app.id, code=SUBTREE).first()
    if not perm:
        perm = Permission(app_id=app.id, code=SUBTREE, name=SUBTREE)
        db.add(perm); db.commit(); db.refresh(perm)
    pos = Position(code=f"dhp_pos_{user.id}", title="Jefe", department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def test_user_without_position_sees_nothing(db_session):
    """Sin puesto vigente no hay departamento que filtrar → fail-CLOSED."""
    other = _dept(db_session, "dhp_other")
    stranger = _user(db_session, "Stranger")
    orphan = _user(db_session, "Orphan")
    _campaign(db_session, "DHP-C-OTHER", other, stranger)
    _unrated_ticket(db_session, "DHP-T-OTHER", stranger, other)

    data = get_pending_tasks(user={"sub": str(orphan.id), "role": "user"}, db=db_session)["data"]

    assert data["campaigns"] == []
    assert data["unrated_tickets"]["count"] == 0


def test_head_sees_own_subtree_but_not_other_branch(db_session):
    root = _dept(db_session, "dhp_root")
    mine = _dept(db_session, "dhp_sub", root.id)
    leaf = _dept(db_session, "dhp_leaf", mine.id)
    sibling = _dept(db_session, "dhp_sibling", root.id)
    boss = _user(db_session, "Head")
    stranger = _user(db_session, "Ajeno")
    _grant_subtree(db_session, boss, mine)

    _campaign(db_session, "DHP-C-MINE", mine, stranger)
    _campaign(db_session, "DHP-C-LEAF", leaf, stranger)
    _campaign(db_session, "DHP-C-SIB", sibling, stranger)
    _unrated_ticket(db_session, "DHP-T-MINE", stranger, mine)
    _unrated_ticket(db_session, "DHP-T-LEAF", stranger, leaf)
    _unrated_ticket(db_session, "DHP-T-SIB", stranger, sibling)

    data = get_pending_tasks(user={"sub": str(boss.id), "role": "user"}, db=db_session)["data"]

    folios = {c["folio"] for c in data["campaigns"]}
    assert folios == {"DHP-C-MINE", "DHP-C-LEAF"}   # subárbol sí, rama hermana no
    assert data["unrated_tickets"]["count"] == 2

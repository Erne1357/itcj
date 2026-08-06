"""Multi-puesto: el departamento que cuenta para una app debe venir de esa app.

Escenario: una persona tiene un puesto en Cafetería (que NO otorga nada en
helpdesk) y otro en Gestión (que sí le da acceso). Los resolvers canónicos
`get_user_departments` / `get_primary_user_department` son AGNÓSTICOS de la app:
devuelven todos los departamentos donde hay un puesto vigente, sin mirar cuál de
ellos concede el acceso. El "primario" se decide por antigüedad, así que puede
salir el departamento que no tiene nada que ver con la app.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.services.ticket_service import create_ticket
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

TODAY = date.today()


def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _position(db, code, dept, user, start, *, helpdesk_perm=None):
    """Puesto en `dept`. Si `helpdesk_perm`, ese puesto concede ese permiso."""
    pos = Position(code=code, title=code, department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=start, is_active=True))
    if helpdesk_perm:
        app = db.query(App).filter_by(key="helpdesk").first()
        perm = db.query(Permission).filter_by(app_id=app.id, code=helpdesk_perm).first()
        if not perm:
            perm = Permission(app_id=app.id, code=helpdesk_perm, name=helpdesk_perm)
            db.add(perm); db.commit(); db.refresh(perm)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def test_ticket_is_sealed_with_a_department_that_grants_the_app(db_session):
    """El ticket NO puede quedar sellado con un departamento que no da acceso.

    El puesto de Cafetería es más antiguo, así que el desempate por `start_date`
    lo elige como "primario" aunque no tenga nada que ver con helpdesk.
    """
    # `database/DML/` (con el catálogo real de categorías) es gitignored y no
    # llega al checkout de CI: se siembra get-or-create dentro de la
    # transacción del test en vez de asumir que la BD ya lo trae.
    category = ensure_helpdesk_category(db_session)
    ensure_helpdesk_priority(db_session, "MEDIA")

    cafeteria = _dept(db_session, "mps_cafeteria")   # sin acceso a helpdesk
    gestion = _dept(db_session, "mps_gestion")       # con acceso a helpdesk

    u = User(first_name="M", last_name="MultiPos", is_active=True)
    db_session.add(u); db_session.commit(); db_session.refresh(u)

    # El de cafetería es MÁS ANTIGUO → gana el desempate del resolver primario.
    _position(db_session, "mps_pos_cafeteria", cafeteria, u, TODAY - timedelta(days=500))
    _position(db_session, "mps_pos_gestion", gestion, u, TODAY - timedelta(days=10),
              helpdesk_perm="helpdesk.tickets.api.create")

    ticket = create_ticket(
        db_session, requester_id=u.id, area=category.area, category_id=category.id,
        title="mps", description="mps", priority="MEDIA",
    )

    assert ticket.requester_department_id == gestion.id, (
        "el ticket quedó sellado con un departamento que no otorga acceso a helpdesk"
    )

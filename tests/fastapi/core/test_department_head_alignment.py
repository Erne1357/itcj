"""A7: Department.get_head_user alineado con departments_service.build_tree
(ventana de puesto activo + orden determinista). Un jefe con puesto VENCIDO o
que aún no inicia deja de aparecer — intent de la rama org-scoped-authz."""
from datetime import date, timedelta

from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User


def _dept_with_head(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    pos = Position(code=f"head_{code}", title="Jefe", department_id=d.id, is_active=True)
    db.add(pos); db.commit(); db.refresh(pos)
    u = User(first_name="H", last_name="Head", is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return d, pos, u


def test_current_head_is_returned(db_session):
    d, pos, u = _dept_with_head(db_session, "hdal_cur")
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id,
                                start_date=date.today() - timedelta(days=1),
                                is_active=True))
    db_session.commit()
    head = d.get_head_user()
    assert head is not None and head.id == u.id


def test_expired_head_no_longer_appears(db_session):
    d, pos, u = _dept_with_head(db_session, "hdal_exp")
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id,
                                start_date=date.today() - timedelta(days=30),
                                end_date=date.today() - timedelta(days=1),
                                is_active=True))
    db_session.commit()
    # Antes get_head_user solo filtraba is_active → devolvía al jefe vencido.
    # Ahora la ventana activa (end_date) lo excluye, como build_tree.
    assert d.get_head_user() is None


def test_future_head_not_yet_active(db_session):
    d, pos, u = _dept_with_head(db_session, "hdal_fut")
    db_session.add(UserPosition(user_id=u.id, position_id=pos.id,
                                start_date=date.today() + timedelta(days=5),
                                is_active=True))
    db_session.commit()
    assert d.get_head_user() is None

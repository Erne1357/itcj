"""Settings singleton y reglas de asignacion automatica (modelos + service)."""
import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.models.helpdesk_settings import HelpdeskSettings
from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings, update_settings
from itcj2.core.models.user import User


def _user(db):
    u = User(first_name="aa1_", last_name="Tec", is_active=True)
    db.add(u)
    db.commit()
    return u


def _sin_fila(db):
    db.query(HelpdeskSettings).delete()
    db.commit()


def test_get_settings_sin_fila_da_defaults(db_session):
    _sin_fila(db_session)
    s = get_settings(db_session)
    assert s.auto_assign_enabled is False
    assert s.assignment_email_user_ids == []
    assert s not in db_session.new


def test_update_settings_crea_y_actualiza(db_session):
    u = _user(db_session)
    _sin_fila(db_session)
    s = update_settings(db_session, user_id=u.id, auto_assign_enabled=True)
    assert s.auto_assign_enabled is True and s.updated_by_id == u.id
    s2 = update_settings(db_session, user_id=u.id, assignment_email_user_ids=[u.id])
    assert s2.assignment_email_user_ids == [u.id]
    assert db_session.query(HelpdeskSettings).count() == 1


def test_singleton_rechaza_id_2(db_session):
    db_session.add(HelpdeskSettings(id=2))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_estrategia_invalida_rechazada(db_session):
    u = _user(db_session)
    db_session.add(AssignmentRule(
        area="DESARROLLO", strategy="foo", technician_ids=[u.id], created_by_id=u.id))
    with pytest.raises(IntegrityError):
        db_session.flush()

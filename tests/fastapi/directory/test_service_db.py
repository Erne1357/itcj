"""Tests de servicio contra Postgres real (fixture db_session, savepoint).

Por qué no MagicMock: estas rutas usan DISTINCT ON, funciones de ventana y un
CHECK de base de datos. Un MagicMock devuelve truthy para todo y no prueba nada.

Por qué los fixtures de abajo: la suite corre en DOS esquemas distintos. En dev el
esquema lo hace Alembic (la migración siembra la fila id=1 y hay usuarios reales);
en CI lo hace Base.metadata.create_all, la tabla nace VACÍA y core_users también
(database/ está gitignored y no llega al checkout). Un test que asuma la fila o un
id de usuario a pelo pasa en dev y revienta CI con UPDATE 0 o violación de FK.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from itcj2.apps.directory.services import directory_service as svc
from itcj2.apps.directory.services import settings_service
from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User


@pytest.fixture
def settings_row(db_session):
    """Garantiza la fila singleton, venga de Alembic o de create_all."""
    db_session.execute(text(
        "INSERT INTO directory_settings (id, show_unofficial_departments) "
        "VALUES (1, false) ON CONFLICT (id) DO NOTHING"
    ))
    db_session.flush()


@pytest.fixture
def some_user_id(db_session):
    """Un id de core_users que EXISTE aquí (updated_by_id es FK)."""
    existing = db_session.execute(text("SELECT id FROM core_users LIMIT 1")).scalar()
    if existing:
        return existing
    user = User(first_name="Test", last_name="Directory")
    db_session.add(user)
    db_session.flush()
    return user.id


# ── helpers de siembra ───────────────────────────────────────────────────────
def _mk_dept(db, code, name, parent_id=None, official=True):
    d = Department(code=code, name=name, parent_id=parent_id,
                   is_active=True, is_official=official)
    db.add(d)
    db.flush()
    return d


def _mk_user(db, suffix, email=None):
    u = User(first_name=f"Ana{suffix}", last_name="Test", email=email)
    db.add(u)
    db.flush()
    return u


def _mk_pos(db, code, *, allows_multiple=False, email=None, ext=None, dept_id=None):
    p = Position(code=code, title=code, is_active=True, allows_multiple=allows_multiple,
                 email=email, phone_extension=ext, department_id=dept_id)
    db.add(p)
    db.flush()
    return p


def _assign(db, user, pos, start=None, end=None, active=True):
    up = UserPosition(user_id=user.id, position_id=pos.id, is_active=active,
                      start_date=start or date.today() - timedelta(days=10), end_date=end)
    db.add(up)
    db.flush()
    return up


# ── settings_service ─────────────────────────────────────────────────────────
def test_show_unofficial_reads_persisted_true(db_session, settings_row):
    db_session.execute(text(
        "UPDATE directory_settings SET show_unofficial_departments = true WHERE id = 1"))
    assert settings_service.show_unofficial(db_session) is True


def test_show_unofficial_defaults_false_without_row(db_session):
    db_session.execute(text("DELETE FROM directory_settings"))
    assert settings_service.show_unofficial(db_session) is False


def test_set_show_unofficial_recreates_missing_row(db_session):
    db_session.execute(text("DELETE FROM directory_settings"))
    settings_service.set_show_unofficial(db_session, True, by_user_id=None)
    assert settings_service.show_unofficial(db_session) is True


def test_set_show_unofficial_records_author_and_timestamp(db_session, settings_row, some_user_id):
    before = db_session.execute(
        text("SELECT updated_at FROM directory_settings WHERE id = 1")).scalar()
    settings_service.set_show_unofficial(db_session, True, by_user_id=some_user_id)
    row = db_session.execute(text(
        "SELECT updated_by_id, updated_at FROM directory_settings WHERE id = 1")).one()
    assert row[0] == some_user_id
    assert row[1] >= before


def test_second_row_rejected_by_check(db_session, settings_row):
    with pytest.raises(Exception):
        db_session.execute(text(
            "INSERT INTO directory_settings (id, show_unofficial_departments) VALUES (2, true)"))
        db_session.flush()

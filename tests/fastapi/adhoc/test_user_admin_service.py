"""Tests de ``itcj2.apps.adhoc.services.user_admin_service``.

Contra Postgres real (fixture ``db_session``), por el mismo motivo que los del
indicator_service: lo que hay que probar aquí es **cómo se resuelven filas del
core** (``core_apps`` por ``key``, ``core_user_app_roles``, la tabla de
asociación ``adhoc_user_areas``), y eso un ``MagicMock`` no lo puede afirmar.

El bug estrella que cubren estos tests: el legacy hardcodeaba ``app_id = 4``
(``api_users.py:22``), que en la BD real de itcj2 es **warehouse**, no Calidad.
Cada método resuelve la app por ``key='adhoc'``.
"""
import uuid

import pytest
from sqlalchemy import text

from itcj2.apps.adhoc.models import AdhocArea, adhoc_user_areas
from itcj2.apps.adhoc.schemas.admin import ADHOC_APP_ROLES
from itcj2.apps.adhoc.services import user_admin_service
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole


# ---------------------------------------------------------------------------
# Helpers de siembra (todo dentro de la transacción que se revierte)
# ---------------------------------------------------------------------------

@pytest.fixture()
def adhoc_app(db_session):
    """La fila de ``core_apps`` con ``key='adhoc'``.

    ``_seed_minimal_reference_data`` de ``tests/fastapi/conftest.py`` solo
    siembra itcj/helpdesk/maint, así que este fixture la crea si falta (en la BD
    de desarrollo ya existe por el DML de la fase F2).
    """
    app = db_session.query(App).filter_by(key="adhoc").one_or_none()
    if app is None:
        app = App(key="adhoc", name="Calidad", is_active=True)
        db_session.add(app)
        db_session.flush()
    return app


@pytest.fixture()
def adhoc_roles(db_session):
    """Los 5 roles de Calidad en ``core_roles`` (nombre global y único)."""
    out = {}
    for name in ADHOC_APP_ROLES:
        role = db_session.query(Role).filter_by(name=name).one_or_none()
        if role is None:
            role = Role(name=name)
            db_session.add(role)
            db_session.flush()
        out[name] = role
    return out


def _make_user(db, first="ANA", last="TEST"):
    user = User(
        username=f"e2e_{uuid.uuid4().hex[:12]}",
        first_name=first,
        last_name=last,
        email=f"{uuid.uuid4().hex[:10]}@test.local",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_area(db, name=None):
    area = AdhocArea(name=name or f"area_{uuid.uuid4().hex[:10]}", color="#4834d4")
    db.add(area)
    db.flush()
    return area


def _grant(db, user, app, role):
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.flush()


# ---------------------------------------------------------------------------
# Resolución de la app
# ---------------------------------------------------------------------------

def test_get_app_resolves_by_key_not_by_hardcoded_id(db_session, adhoc_app):
    """Regresión del ``APP_PRUEBA_ID = 4`` del legacy."""
    resolved = user_admin_service.UserAdminService.get_app(db_session)
    assert resolved.key == "adhoc"
    assert resolved.id == adhoc_app.id

    row_id = db_session.execute(
        text("SELECT id FROM core_apps WHERE key = 'adhoc'")
    ).scalar_one()
    assert resolved.id == row_id


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------

def test_list_users_returns_only_users_with_adhoc_access(db_session, adhoc_app, adhoc_roles):
    inside = _make_user(db_session, first="DENTRO")
    outside = _make_user(db_session, first="FUERA")
    _grant(db_session, inside, adhoc_app, adhoc_roles["consult"])

    rows = user_admin_service.UserAdminService.list_users(db_session)
    ids = {row["id"] for row in rows}

    assert inside.id in ids
    assert outside.id not in ids


def test_list_users_does_not_duplicate_multi_role_users(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["supervisor_doc"])
    _grant(db_session, user, adhoc_app, adhoc_roles["supervisor_inc"])

    rows = [r for r in user_admin_service.UserAdminService.list_users(db_session)
            if r["id"] == user.id]

    assert len(rows) == 1
    assert sorted(rows[0]["roles"]) == ["supervisor_doc", "supervisor_inc"]


def test_list_users_includes_areas(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["consult"])
    area = _make_area(db_session)
    db_session.execute(
        adhoc_user_areas.insert().values(user_id=user.id, area_id=area.id)
    )
    db_session.flush()

    row = next(r for r in user_admin_service.UserAdminService.list_users(db_session)
               if r["id"] == user.id)

    assert [a["id"] for a in row["areas"]] == [area.id]
    assert row["areas"][0]["name"] == area.name
    assert row["full_name"]


# ---------------------------------------------------------------------------
# Asignación de rol
# ---------------------------------------------------------------------------

def test_set_app_role_replaces_every_adhoc_row(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["supervisor_doc"])
    _grant(db_session, user, adhoc_app, adhoc_roles["supervisor_inc"])

    user_admin_service.UserAdminService.set_app_role(db_session, user.id, "consult")

    rows = (db_session.query(UserAppRole)
            .filter_by(user_id=user.id, app_id=adhoc_app.id).all())
    assert len(rows) == 1
    assert rows[0].role_id == adhoc_roles["consult"].id


def test_set_app_role_does_not_touch_other_apps(db_session, adhoc_app, adhoc_roles):
    other_app = db_session.query(App).filter_by(key="helpdesk").one_or_none()
    if other_app is None:
        other_app = App(key="helpdesk", name="Help desk", is_active=True)
        db_session.add(other_app)
        db_session.flush()

    user = _make_user(db_session)
    _grant(db_session, user, other_app, adhoc_roles["consult"])

    user_admin_service.UserAdminService.set_app_role(db_session, user.id, "supervisor_prog")

    assert db_session.query(UserAppRole).filter_by(
        user_id=user.id, app_id=other_app.id).count() == 1
    assert db_session.query(UserAppRole).filter_by(
        user_id=user.id, app_id=adhoc_app.id).count() == 1


def test_set_app_role_is_idempotent(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    user_admin_service.UserAdminService.set_app_role(db_session, user.id, "consult")
    user_admin_service.UserAdminService.set_app_role(db_session, user.id, "consult")

    assert db_session.query(UserAppRole).filter_by(
        user_id=user.id, app_id=adhoc_app.id).count() == 1


def test_set_app_role_rejects_unknown_user(db_session, adhoc_app, adhoc_roles):
    with pytest.raises(LookupError):
        user_admin_service.UserAdminService.set_app_role(db_session, 999_999_999, "consult")


def test_set_app_role_rejects_role_outside_the_app_vocabulary(db_session, adhoc_app):
    user = _make_user(db_session)
    with pytest.raises(ValueError):
        user_admin_service.UserAdminService.set_app_role(db_session, user.id, "student")


# ---------------------------------------------------------------------------
# Asignación de áreas
# ---------------------------------------------------------------------------

def test_set_areas_replaces_the_previous_set(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["consult"])
    a1, a2, a3 = _make_area(db_session), _make_area(db_session), _make_area(db_session)

    user_admin_service.UserAdminService.set_areas(db_session, user.id, [a1.id, a2.id])
    user_admin_service.UserAdminService.set_areas(db_session, user.id, [a3.id])

    rows = db_session.execute(
        adhoc_user_areas.select().where(adhoc_user_areas.c.user_id == user.id)
    ).all()
    assert [r.area_id for r in rows] == [a3.id]


def test_set_areas_accepts_empty_list_as_clear(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["consult"])
    area = _make_area(db_session)
    user_admin_service.UserAdminService.set_areas(db_session, user.id, [area.id])

    user_admin_service.UserAdminService.set_areas(db_session, user.id, [])

    assert db_session.execute(
        adhoc_user_areas.select().where(adhoc_user_areas.c.user_id == user.id)
    ).all() == []


def test_set_areas_rejects_unknown_area(db_session, adhoc_app, adhoc_roles):
    user = _make_user(db_session)
    _grant(db_session, user, adhoc_app, adhoc_roles["consult"])
    with pytest.raises(ValueError):
        user_admin_service.UserAdminService.set_areas(db_session, user.id, [999_999_999])


def test_set_areas_rejects_user_without_adhoc_access(db_session, adhoc_app, adhoc_roles):
    """Las áreas son datos de Calidad: no se le cuelgan a alguien que no está
    en la app (la pantalla solo lista usuarios con acceso)."""
    user = _make_user(db_session)
    area = _make_area(db_session)
    with pytest.raises(ValueError):
        user_admin_service.UserAdminService.set_areas(db_session, user.id, [area.id])


def test_set_areas_rejects_unknown_user(db_session, adhoc_app):
    with pytest.raises(LookupError):
        user_admin_service.UserAdminService.set_areas(db_session, 999_999_999, [])


# ---------------------------------------------------------------------------
# Configuración de correo
# ---------------------------------------------------------------------------

def test_mail_config_get_never_writes(db_session):
    """Regresión del legacy: su ``GET /api/mail/config`` hacía ``add()`` +
    ``commit()`` para autocrear la fila."""
    from itcj2.apps.adhoc.models import AdhocMailConfig

    db_session.query(AdhocMailConfig).delete()
    db_session.flush()

    assert user_admin_service.MailConfigService.get(db_session) is None
    assert db_session.query(AdhocMailConfig).count() == 0


def test_mail_config_set_enabled_updates_the_singleton(db_session):
    from itcj2.apps.adhoc.models import AdhocMailConfig

    db_session.query(AdhocMailConfig).delete()
    db_session.add(AdhocMailConfig(id=1, is_enabled=True))
    db_session.flush()

    cfg = user_admin_service.MailConfigService.set_enabled(db_session, False)

    assert cfg.id == 1 and cfg.is_enabled is False
    assert db_session.query(AdhocMailConfig).count() == 1


def test_mail_config_set_enabled_creates_the_row_when_missing(db_session):
    """El PUT sí puede crearla (no es un método seguro); el GET no."""
    from itcj2.apps.adhoc.models import AdhocMailConfig

    db_session.query(AdhocMailConfig).delete()
    db_session.flush()

    cfg = user_admin_service.MailConfigService.set_enabled(db_session, True)

    assert cfg.id == 1 and cfg.is_enabled is True
    assert db_session.query(AdhocMailConfig).count() == 1

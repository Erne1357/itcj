"""Fixtures de Prórrogas.

Las pruebas corren contra el Postgres de dev dentro de un savepoint
(`tests/fastapi/conftest.py::db_session`): lo que crean se descarta al final,
pero SÍ ven lo que ya esté commiteado en dev. Por eso las pruebas de plantillas
usan años lejanos (2089–2095), donde no hay plantillas reales.
"""
from io import BytesIO
from itertools import count

import pytest

import itcj2.models  # noqa: F401  (resuelve mappers antes de tocar servicios)
from itcj2.database import get_db
from tests.conftest import make_jwt

APP_KEY = "prorrogas_tec"

SECRETARIA_PERMS = [
    "prorrogas_tec.secretaria.page.view",
    "prorrogas_tec.templates.api.read",
    "prorrogas_tec.templates.api.upload",
]

_seq = count(1)


# ---------------------------------------------------------------------------
# Sesión y cliente (mismo arnés que tests/fastapi/titulatec/conftest.py)
# ---------------------------------------------------------------------------

class _TestSession:
    """Proxy sobre la sesión del test que ignora `close()` y el `with`."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """`SessionLocal()` -> la sesión del test (rutas que abren su propia sesión)."""
    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _TestSession(db_session))
    return db_session


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client_as(client):
    """Cliente autenticado como `user`; `role=""` para que no haya atajo de admin."""
    def _as(user, role=""):
        token = make_jwt(user_id=user.id, role=role, name=user.full_name, cn=user.control_number)
        client.cookies.set("itcj_token", token)
        return client

    return _as


# ---------------------------------------------------------------------------
# App, permisos y roles de Prórrogas
# ---------------------------------------------------------------------------

def _invalidate(user_id: int) -> None:
    try:
        from itcj2.core.services.authz_cache import invalidate_user_app
        invalidate_user_app(user_id, APP_KEY)
    except Exception:
        pass


@pytest.fixture()
def prorrogas_app(db_session):
    from itcj2.core.models.app import App

    app = db_session.query(App).filter_by(key=APP_KEY).first()
    if app is None:
        app = App(key=APP_KEY, name="Prórrogas", is_active=True)
        db_session.add(app)
        db_session.flush()
    return app


@pytest.fixture()
def make_role(db_session, prorrogas_app):
    """Rol (por nombre) con los permisos indicados en prorrogas_tec. Idempotente."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    def _make(name, perm_codes=()):
        role = db_session.query(Role).filter_by(name=name).first()
        if role is None:
            role = Role(name=name)
            db_session.add(role)
            db_session.flush()
        for code in perm_codes:
            perm = db_session.query(Permission).filter_by(app_id=prorrogas_app.id, code=code).first()
            if perm is None:
                perm = Permission(app_id=prorrogas_app.id, code=code, name=code[:120])
                db_session.add(perm)
                db_session.flush()
            if db_session.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first() is None:
                db_session.add(RolePermission(role_id=role.id, perm_id=perm.id))
        db_session.flush()
        return role

    return _make


@pytest.fixture()
def grant(db_session, prorrogas_app):
    """`UserAppRole`: rol directo del usuario en prorrogas_tec."""
    from itcj2.core.models.user_app_role import UserAppRole

    def _grant(user, role):
        if db_session.query(UserAppRole).filter_by(
                user_id=user.id, app_id=prorrogas_app.id, role_id=role.id).first() is None:
            db_session.add(UserAppRole(user_id=user.id, app_id=prorrogas_app.id, role_id=role.id))
            db_session.flush()
        _invalidate(user.id)

    return _grant


@pytest.fixture()
def secretaria(make_user, make_role, grant):
    user = make_user(first_name="SECRETARIA", last_name="PRUEBA")
    grant(user, make_role("secretaria", SECRETARIA_PERMS))
    return user


@pytest.fixture()
def estudiante(make_user, make_role, grant):
    user = make_user(first_name="ESTUDIANTE", last_name="PRUEBA", control_number=f"99{next(_seq):06d}")
    grant(user, make_role("student"))
    return user


@pytest.fixture(autouse=True)
def almacen(tmp_path, monkeypatch):
    """Los archivos de plantillas van a `tmp_path`, nunca a `instance/` real."""
    from itcj2.apps.prorrogas_tec.services import template_service

    base = tmp_path / "prorrogas_tec"
    monkeypatch.setattr(template_service, "_base", lambda: base)
    return base


@pytest.fixture()
def make_user(db_session):
    """Usuario sintético. Nombres ficticios, correo .invalid."""
    from itcj2.core.models.user import User

    def _make(first_name="ACTOR", last_name="PRUEBA", middle_name=None, control_number=None,
              username=None, email=None):
        n = next(_seq)
        user = User(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            username=username or f"pr_test_{n}_{id(db_session)}",
            control_number=control_number,
            email=email or f"pr.test.{n}@example.invalid",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture()
def docx_con():
    """`.docx` con un párrafo por línea."""
    from docx import Document

    def _make(*lines: str) -> bytes:
        d = Document()
        for line in lines:
            d.add_paragraph(line)
        buf = BytesIO()
        d.save(buf)
        return buf.getvalue()

    return _make

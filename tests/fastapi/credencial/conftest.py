"""Conftest de tests de la app credencial: mappers de SQLAlchemy y fixtures compartidas.

CI corre contra una base vacía (create_all, sin DML): cada fila (alumno, carrera,
foto, app y permiso de credencial) se crea aquí dentro del savepoint de `db_session`.
Nada asume ids.
"""
import secrets
import uuid

import pytest

import itcj2.models  # noqa: F401
from itcj2.apps.credencial.models import CredentialPhoto
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.program import Program
from itcj2.core.models.student_profile import StudentProfile
from itcj2.core.models.user import User
from itcj2.core.models.user_app_perm import UserAppPerm
from itcj2.database import get_db

FIRST, LAST, MIDDLE = "Xochiquetzal", "Zubizarreta", "Quirarte"
PHOTO_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


@pytest.fixture
def client(app_client, db_session):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "CREDENCIAL_PHOTO_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def student(db_session, photo_dir):
    """Alumno activo con carrera y foto en disco. Devuelve (user, photo, program_name)."""
    program_name = f"Ing. Prueba Credencial {uuid.uuid4().hex[:8]}"
    program = Program(name=program_name)
    user = User(first_name=FIRST, last_name=LAST, middle_name=MIDDLE,
                control_number=f"Z{uuid.uuid4().hex[:9]}", is_active=True)
    db_session.add_all([program, user])
    db_session.flush()
    photo = CredentialPhoto(user_id=user.id, ref=secrets.token_urlsafe(12),
                            file_name=f"{uuid.uuid4().hex}.jpg",
                            width=600, height=789, size_bytes=len(PHOTO_BYTES))
    db_session.add_all([StudentProfile(user_id=user.id, program_id=program.id), photo])
    db_session.flush()
    (photo_dir / photo.file_name).write_bytes(PHOTO_BYTES)
    return user, photo, program_name


@pytest.fixture
def credencial_app(db_session):
    app = db_session.query(App).filter_by(key="credencial").first()
    if app is None:
        app = App(key="credencial", name="Credencial Digital", is_active=True)
        db_session.add(app)
    app.is_active = True
    db_session.flush()
    return app


def grant(db_session, app, user, code):
    """Asigna un permiso directo (lo crea si la base vacía no lo trae)."""
    perm = db_session.query(Permission).filter_by(app_id=app.id, code=code).first()
    if perm is None:
        perm = Permission(app_id=app.id, code=code, name=code)
        db_session.add(perm)
        db_session.flush()
    db_session.add(UserAppPerm(user_id=user.id, app_id=app.id, perm_id=perm.id, allow=True))
    db_session.flush()


@pytest.fixture
def staff(db_session, credencial_app):
    """Personal con el permiso de verificación completa asignado directo."""
    user = User(first_name="Vigilante", last_name="Prueba", username=f"vig_{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    db_session.flush()
    grant(db_session, credencial_app, user, "credencial.verify.page.full")
    return user

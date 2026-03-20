"""
Fixtures globales para tests de FastAPI (itcj2).

Estrategia: mockear los servicios de Flask (auth_service, authz_service,
notification_service, etc.) para que los tests sean independientes de la BD
y del servidor Flask.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# JWT helpers (mismos parámetros que itcj/core/utils/jwt_tools.py)
# ---------------------------------------------------------------------------
TEST_SECRET = "test-secret-key"
JWT_ALGO = "HS256"


def make_jwt(
    user_id: int = 1,
    role: str = "admin",
    cn: str | None = None,
    name: str = "Test User",
    hours: int = 12,
) -> str:
    """Genera un JWT válido para tests."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "cn": cn,
        "name": name,
        "iat": now,
        "exp": now + hours * 3600,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm=JWT_ALGO)


def make_expired_jwt(user_id: int = 1) -> str:
    """Genera un JWT ya expirado."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": "admin",
        "cn": None,
        "name": "Expired User",
        "iat": now - 7200,
        "exp": now - 3600,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm=JWT_ALGO)


# ---------------------------------------------------------------------------
# Fake user data
# ---------------------------------------------------------------------------
FAKE_STUDENT = {
    "id": 100,
    "role": "student",
    "control_number": "20210001",
    "full_name": "GARCIA LOPEZ JUAN",
    "email": "l20210001@cdjuarez.tecnm.mx",
}

FAKE_STAFF = {
    "id": 200,
    "role": "admin",
    "control_number": None,
    "full_name": "MARTINEZ PEREZ MARIA",
    "email": "mmartinez@cdjuarez.tecnm.mx",
    "username": "mmartinez",
}


# ---------------------------------------------------------------------------
# Fake User ORM-like object
# ---------------------------------------------------------------------------
class FakeUser:
    """Simula un modelo User de SQLAlchemy para tests."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.username = kwargs.get("username")
        self.control_number = kwargs.get("control_number")
        self.first_name = kwargs.get("first_name", "TEST")
        self.last_name = kwargs.get("last_name", "USER")
        self.middle_name = kwargs.get("middle_name")
        self.email = kwargs.get("email", "test@test.com")
        self.is_active = kwargs.get("is_active", True)
        self.password_hash = kwargs.get("password_hash", "hashed")
        self.must_change_password = kwargs.get("must_change_password", False)
        self.role = MagicMock(name=kwargs.get("role_name", "admin"))
        self.role_id = kwargs.get("role_id", 1)

    @property
    def full_name(self):
        parts = [self.last_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.first_name)
        return " ".join(parts)


# ---------------------------------------------------------------------------
# App fixture: FastAPI TestClient con mocks
# ---------------------------------------------------------------------------
@pytest.fixture()
def app_client():
    """TestClient de FastAPI con SECRET mockeado y sin Flask-SQLAlchemy real.

    Uso:
        def test_something(app_client):
            resp = app_client.get("/health")
            assert resp.status_code == 200
    """
    # Mockear _init_flask_db para que no intente conectar a PostgreSQL
    with patch("itcj2.main._init_flask_db"):
        # Patchear el SECRET usado en middleware para que coincida con tests
        with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
            from itcj2.main import create_app

            app = create_app()
            with TestClient(app) as client:
                yield client


@pytest.fixture()
def auth_headers() -> dict:
    """Headers con cookie JWT válida para un usuario admin."""
    token = make_jwt(user_id=200, role="admin", name="MARTINEZ PEREZ MARIA")
    return {"Cookie": f"itcj_token={token}"}


@pytest.fixture()
def student_headers() -> dict:
    """Headers con cookie JWT válida para un estudiante."""
    token = make_jwt(user_id=100, role="student", cn="20210001", name="GARCIA LOPEZ JUAN")
    return {"Cookie": f"itcj_token={token}"}


@pytest.fixture()
def no_auth_headers() -> dict:
    """Headers sin autenticación."""
    return {}

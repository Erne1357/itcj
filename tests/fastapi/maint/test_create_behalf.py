"""
Tests para la funcionalidad "crear ticket en nombre de otro usuario".

Estrategia:
- JWT con role='admin' → require_perms hace bypass (sin BD).
- JWT sin role → require_perms necesita consulta real; mockeamos authz_service
  para simular permisos concretos.
- Mockeamos ticket_service.create_ticket y MaintNotificationHelper para no
  tocar la BD ni el mailer.
- Mockeamos la query de validación de pertenencia al depto directamente sobre
  el MagicMock db.
"""
import time
from unittest.mock import MagicMock, patch, PropertyMock

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# ─────────────────────────────────────────────────────────────────────
# Helpers JWT
# ─────────────────────────────────────────────────────────────────────

def _make_jwt(user_id: int, role: str = None) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "cn": None,
        "name": "Test User",
        "iat": now,
        "exp": now + 24 * 3600,  # 24h → por encima del threshold de refresh (2h)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers(user_id: int = 1):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role='admin')}"}


def _plain_headers(user_id: int = 10):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role=None)}"}


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_and_db():
    """App real con get_db override."""
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        client._mock_db = mock_db
        yield app, client, mock_db
    app.dependency_overrides.clear()


VALID_PAYLOAD = {
    "category_id": 1,
    "priority": "MEDIA",
    "title": "Solicitud de prueba",
    "description": "Descripción larga de prueba para el test",
    "department_id": 5,
}


def _mock_ticket():
    """Ticket ficticio devuelto por create_ticket."""
    ticket = MagicMock()
    ticket.id = 99
    ticket.ticket_number = "MANT-2026-000099"
    ticket.due_at = None
    return ticket


# ─────────────────────────────────────────────────────────────────────
# Caso 1: admin crea en nombre de usuario del mismo depto → OK
# ─────────────────────────────────────────────────────────────────────

class TestAdminCreateOnBehalf:
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_admin_creates_behalf_ok(self, mock_create, mock_notify, app_and_db):
        _, client, mock_db = app_and_db

        mock_create.return_value = _mock_ticket()

        # Simular que el requester (user_id=20) pertenece al depto 5:
        # La query devuelve un resultado no vacío
        mock_db.query.return_value.join.return_value.join.return_value.filter.return_value.first.return_value = (5,)

        payload = {**VALID_PAYLOAD, "requester_id": 20}
        r = client.post(
            "/api/maint/v2/tickets",
            json=payload,
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["ticket_number"] == "MANT-2026-000099"

        # Verificar que create_ticket fue llamado con requester_id=20, created_by_id=1
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["requester_id"] == 20
        assert call_kwargs["created_by_id"] == 1

    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_admin_no_requester_id_uses_self(self, mock_create, mock_notify, app_and_db):
        """Sin requester_id, el ticket se crea para el propio usuario."""
        _, client, mock_db = app_and_db
        mock_create.return_value = _mock_ticket()

        r = client.post(
            "/api/maint/v2/tickets",
            json=VALID_PAYLOAD,
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 201, r.text

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["requester_id"] == 1
        assert call_kwargs["created_by_id"] == 1


# ─────────────────────────────────────────────────────────────────────
# Caso 2: requester de OTRO depto → 400
# ─────────────────────────────────────────────────────────────────────

class TestCreateBehalfWrongDept:
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_requester_different_dept_returns_400(self, mock_create, mock_notify, app_and_db):
        _, client, mock_db = app_and_db

        # La query de pertenencia al depto usa: db.query(...).join(...).join(...).filter(...).first()
        # Configurar la cadena de MagicMock para retornar None (no pertenece al depto):
        # Cualquier encadenamiento de .join/.filter termina retornando None en .first()
        q = MagicMock()
        q.join.return_value = q
        q.filter.return_value = q
        q.first.return_value = None          # no pertenece
        mock_db.query.return_value = q

        payload = {**VALID_PAYLOAD, "requester_id": 30}
        r = client.post(
            "/api/maint/v2/tickets",
            json=payload,
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 400, r.text
        body = r.json()
        msg = (body.get("detail") or body.get("error") or "").lower()
        assert "departamento" in msg
        mock_create.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# Caso 3: staff (sin permiso behalf) manda requester_id de otro → 403
# ─────────────────────────────────────────────────────────────────────

class TestStaffNoBehalfPermission:
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_staff_behalf_returns_403(
        self, mock_create, mock_notify, mock_has_assign, mock_get_perms, app_and_db
    ):
        _, client, mock_db = app_and_db

        # El usuario 10 tiene acceso a la app y tiene maint.tickets.api.create
        # pero NO tiene maint.tickets.api.create.behalf
        mock_has_assign.return_value = True
        mock_get_perms.return_value = {
            "maint.tickets.api.create",
            "maint.tickets.api.read.own",
        }

        payload = {**VALID_PAYLOAD, "requester_id": 99}
        r = client.post(
            "/api/maint/v2/tickets",
            json=payload,
            headers=_plain_headers(user_id=10),
        )
        assert r.status_code == 403, r.text
        body = r.json()
        # El handler de HTTPException de main.py usa "error" o "detail" según el path
        msg = (body.get("detail") or body.get("error") or "").lower()
        assert "permiso" in msg or "behalf" in msg or msg != ""
        mock_create.assert_not_called()

    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_staff_own_requester_id_passes(
        self, mock_create, mock_notify, mock_has_assign, mock_get_perms, app_and_db
    ):
        """Staff enviando su propio user_id como requester_id: pasa sin verificar permiso behalf."""
        _, client, mock_db = app_and_db
        mock_has_assign.return_value = True
        mock_get_perms.return_value = {
            "maint.tickets.api.create",
            "maint.tickets.api.read.own",
        }
        mock_create.return_value = _mock_ticket()

        # requester_id == user_id → no activa la rama behalf
        payload = {**VALID_PAYLOAD, "requester_id": 10}
        r = client.post(
            "/api/maint/v2/tickets",
            json=payload,
            headers=_plain_headers(user_id=10),
        )
        assert r.status_code == 201, r.text
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["requester_id"] == 10
        assert call_kwargs["created_by_id"] == 10


# ─────────────────────────────────────────────────────────────────────
# Caso 4: department_head con permiso behalf crea para su depto → OK
# ─────────────────────────────────────────────────────────────────────

class TestDeptHeadCreateBehalf:
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_ticket_created")
    @patch("itcj2.apps.maint.services.ticket_service.create_ticket")
    def test_dept_head_creates_behalf_ok(
        self, mock_create, mock_notify, mock_has_assign, mock_get_perms, app_and_db
    ):
        _, client, mock_db = app_and_db

        mock_has_assign.return_value = True
        mock_get_perms.return_value = {
            "maint.tickets.api.create",
            "maint.tickets.api.create.behalf",
            "maint.tickets.api.read.department",
        }
        mock_create.return_value = _mock_ticket()

        # Simular que requester (user_id=50) pertenece al depto 5
        mock_db.query.return_value.join.return_value.join.return_value.filter.return_value.first.return_value = (5,)

        payload = {**VALID_PAYLOAD, "requester_id": 50}
        r = client.post(
            "/api/maint/v2/tickets",
            json=payload,
            headers=_plain_headers(user_id=7),
        )
        assert r.status_code == 201, r.text
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["requester_id"] == 50
        assert call_kwargs["created_by_id"] == 7


# ─────────────────────────────────────────────────────────────────────
# Caso 5: endpoint GET /api/maint/v2/users requiere permiso behalf
# ─────────────────────────────────────────────────────────────────────

class TestUsersEndpoint:
    def test_no_auth_returns_401(self, app_and_db):
        _, client, _ = app_and_db
        r = client.get("/api/maint/v2/users?department_id=5")
        assert r.status_code == 401

    def test_admin_no_dept_id_returns_400(self, app_and_db):
        _, client, _ = app_and_db
        r = client.get("/api/maint/v2/users", headers=_admin_headers())
        assert r.status_code == 400

    def test_admin_with_dept_id_returns_data(self, app_and_db):
        _, client, mock_db = app_and_db

        # Simular que la query devuelve dos usuarios
        mock_db.query.return_value.join.return_value.join.return_value.filter.return_value\
            .distinct.return_value.order_by.return_value.all.return_value = [
            (1, "Juan", "Pérez", "juan@itcj.edu.mx"),
            (2, "María", "García", "maria@itcj.edu.mx"),
        ]

        r = client.get("/api/maint/v2/users?department_id=5", headers=_admin_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["total"] == 2
        assert body["data"][0]["name"] == "Juan Pérez"

    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    def test_staff_without_behalf_perm_returns_403(
        self, mock_has_assign, mock_get_perms, app_and_db
    ):
        _, client, _ = app_and_db
        mock_has_assign.return_value = True
        mock_get_perms.return_value = {"maint.tickets.api.create", "maint.tickets.api.read.own"}

        r = client.get(
            "/api/maint/v2/users?department_id=5",
            headers=_plain_headers(user_id=10),
        )
        assert r.status_code == 403

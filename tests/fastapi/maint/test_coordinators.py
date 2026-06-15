"""
Tests para la lógica de coordinadores de mantenimiento.

Cubre:
1. can_assign_technician — los 4 casos de regla de área.
2. Endpoint POST /{ticket_id}/assign con coordinador de área:
   - técnico de su área → OK (200)
   - técnico de otra área → 403
3. Coordinador general asigna cualquier técnico → OK
4. Usuario sin permiso de asignación (dispatcher) → 403 (ya no tiene permiso vía DML;
   aquí lo simulamos sin permiso en el JWT).
5. set/get coordinator areas (admin) → OK.
6. list_coordinators devuelve estructura correcta.

Estrategia de mock:
- JWT con role='admin' → require_perms hace bypass (sin BD).
- JWT sin role → mockear has_any_assignment + get_user_permissions_for_app.
- assignment_service.assign_technicians y coordinator_service son testeados en unidad.
- Broadcasts mockeados vía conftest.py (autouse).

Nota: Las respuestas de error HTTP en este proyecto usan
{"error": detail, "status": code} — ver main.py _register_error_handlers.
"""
import time
from unittest.mock import MagicMock, patch, call, ANY

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
        "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers(user_id: int = 1):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role='admin')}"}


def _plain_headers(user_id: int = 10):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role=None)}"}


# ─────────────────────────────────────────────────────────────────────
# Fixture app
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_and_db():
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        client._mock_db = mock_db
        yield app, client, mock_db
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────
# Unit tests: CoordinatorService.can_assign_technician
# ─────────────────────────────────────────────────────────────────────

class TestCanAssignTechnician:
    """Tests en unidad de la lógica de restricción de área."""

    def _db(self):
        return MagicMock()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_admin_global_bypasses_all(self, mock_areas):
        """Admin global siempre puede asignar; no consulta áreas."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        result = CoordinatorService.can_assign_technician(
            db=self._db(),
            assigner_id=1,
            assigner_roles={"dispatcher"},
            technician_id=99,
            is_global_admin=True,
        )
        assert result is True
        mock_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_role_admin_in_roles_bypasses(self, mock_areas):
        """Rol 'admin' en assigner_roles siempre puede asignar."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        result = CoordinatorService.can_assign_technician(
            db=self._db(),
            assigner_id=1,
            assigner_roles={"admin"},
            technician_id=99,
        )
        assert result is True
        mock_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_general_coordinator_can_assign_any(self, mock_areas):
        """Coordinador general puede asignar cualquier técnico sin consultar áreas."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        result = CoordinatorService.can_assign_technician(
            db=self._db(),
            assigner_id=5,
            assigner_roles={"maint_general_coordinator"},
            technician_id=99,
        )
        assert result is True
        mock_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_area_coordinator_same_area_allowed(self, mock_areas):
        """Coordinador de área con intersección → puede asignar."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.apps.maint.models.technician_area import MaintTechnicianArea

        mock_areas.return_value = ["ELECTRICAL", "GENERAL"]

        db = self._db()
        # Técnico con área ELECTRICAL
        tech_area = MagicMock(spec=MaintTechnicianArea)
        tech_area.area_code = "ELECTRICAL"
        db.query.return_value.filter_by.return_value.all.return_value = [tech_area]

        result = CoordinatorService.can_assign_technician(
            db=db,
            assigner_id=10,
            assigner_roles={"maint_area_coordinator"},
            technician_id=50,
        )
        assert result is True

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_area_coordinator_different_area_rejected(self, mock_areas):
        """Coordinador de área sin intersección → no puede asignar."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.apps.maint.models.technician_area import MaintTechnicianArea

        mock_areas.return_value = ["ELECTRICAL"]

        db = self._db()
        # Técnico con área CARPENTRY (sin intersección)
        tech_area = MagicMock(spec=MaintTechnicianArea)
        tech_area.area_code = "CARPENTRY"
        db.query.return_value.filter_by.return_value.all.return_value = [tech_area]

        result = CoordinatorService.can_assign_technician(
            db=db,
            assigner_id=10,
            assigner_roles={"maint_area_coordinator"},
            technician_id=50,
        )
        assert result is False

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_area_coordinator_no_areas_configured_rejected(self, mock_areas):
        """Coordinador de área sin áreas configuradas → no puede asignar a nadie."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        mock_areas.return_value = []  # sin áreas

        result = CoordinatorService.can_assign_technician(
            db=self._db(),
            assigner_id=10,
            assigner_roles={"maint_area_coordinator"},
            technician_id=50,
        )
        assert result is False

    def test_other_role_cannot_assign(self):
        """Roles que no son coordinator ni admin → no pueden asignar."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        result = CoordinatorService.can_assign_technician(
            db=self._db(),
            assigner_id=99,
            assigner_roles={"dispatcher", "tech_maint"},
            technician_id=50,
        )
        assert result is False


# ─────────────────────────────────────────────────────────────────────
# Unit tests: assign_technicians con restricción de área
# ─────────────────────────────────────────────────────────────────────

class TestAssignTechniciansAreaRestriction:
    """Tests de assignment_service.assign_technicians con las nuevas firmas."""

    def _make_ticket(self, status="PENDING", coordinator_id=None):
        ticket = MagicMock()
        ticket.id = 1
        ticket.ticket_number = "MANT-2026-000001"
        ticket.status = status
        ticket.is_open = True
        ticket.technicians = []
        ticket.updated_at = None
        ticket.updated_by_id = None
        # Para que la restricción de propiedad de enrutado pase, el coordinator_id
        # debe coincidir con el assigned_by_id del coordinador que asigna.
        ticket.coordinator_id = coordinator_id
        return ticket

    def _make_technician(self, user_id=50):
        tech = MagicMock()
        tech.id = user_id
        tech.full_name = f"Técnico {user_id}"
        return tech

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_area_coordinator_same_area_ok(self, mock_roles, mock_can_assign):
        """assign_technicians no lanza error cuando can_assign_technician=True."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        # user_roles_in_app es invocado para verificar los roles del técnico destino
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # coordinator_id=10 coincide con assigned_by_id=10 → pasa la restricción de propiedad
        ticket = self._make_ticket(coordinator_id=10)
        tech = self._make_technician(50)
        db.get.side_effect = [ticket, tech]

        assignment_service.assign_technicians(
            db=db,
            ticket_id=1,
            assigned_by_id=10,
            user_ids=[50],
            assigner_roles={"maint_area_coordinator"},
            is_global_admin=False,
        )
        # No lanzó excepción
        mock_can_assign.assert_called_once_with(
            db=db,
            assigner_id=10,
            assigner_roles={"maint_area_coordinator"},
            technician_id=50,
            is_global_admin=False,
        )

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_area_coordinator_different_area_raises_403(self, mock_roles, mock_can_assign):
        """assign_technicians lanza HTTPException 403 cuando can_assign_technician=False."""
        from itcj2.apps.maint.services import assignment_service
        from fastapi import HTTPException

        mock_can_assign.return_value = False
        # user_roles_in_app se llama para obtener roles del técnico destino
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # coordinator_id=10 coincide con assigned_by_id=10 → pasa la restricción de propiedad
        # pero falla la restricción de área (can_assign=False)
        ticket = self._make_ticket(coordinator_id=10)
        tech = self._make_technician(50)
        db.get.side_effect = [ticket, tech]

        with pytest.raises(HTTPException) as exc_info:
            assignment_service.assign_technicians(
                db=db,
                ticket_id=1,
                assigned_by_id=10,
                user_ids=[50],
                assigner_roles={"maint_area_coordinator"},
                is_global_admin=False,
            )
        assert exc_info.value.status_code == 403
        assert "área" in exc_info.value.detail.lower() or "area" in exc_info.value.detail.lower()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_general_coordinator_any_technician_ok(self, mock_roles, mock_can_assign):
        """Coordinador general (can_assign=True) asigna sin restricciones."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # coordinator_id=5 coincide con assigned_by_id=5 → pasa la restricción de propiedad
        ticket = self._make_ticket(coordinator_id=5)
        tech = self._make_technician(99)
        db.get.side_effect = [ticket, tech]

        assignment_service.assign_technicians(
            db=db,
            ticket_id=1,
            assigned_by_id=5,
            user_ids=[99],
            assigner_roles={"maint_general_coordinator"},
            is_global_admin=False,
        )
        mock_can_assign.assert_called_once_with(
            db=db,
            assigner_id=5,
            assigner_roles={"maint_general_coordinator"},
            technician_id=99,
            is_global_admin=False,
        )

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_admin_global_bypasses_area_check(self, mock_roles, mock_can_assign):
        """Admin global: is_global_admin=True → bypasa restricción de propiedad y de área."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # coordinator_id diferente al assigner; admin bypasa igualmente
        ticket = self._make_ticket(coordinator_id=99)
        tech = self._make_technician(77)
        db.get.side_effect = [ticket, tech]

        assignment_service.assign_technicians(
            db=db,
            ticket_id=1,
            assigned_by_id=1,
            user_ids=[77],
            assigner_roles={"admin"},
            is_global_admin=True,
        )
        mock_can_assign.assert_called_once_with(
            db=db,
            assigner_id=1,
            assigner_roles={"admin"},
            technician_id=77,
            is_global_admin=True,
        )


# ─────────────────────────────────────────────────────────────────────
# Integration tests: endpoint POST /tickets/{id}/assign
# ─────────────────────────────────────────────────────────────────────

class TestAssignEndpointAreaGate:
    """Tests HTTP del endpoint de asignación con restricción de área."""

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.assignment_service.assign_technicians")
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_technician_assigned")
    def test_admin_assign_ok(
        self, mock_notify, mock_assign, mock_has_assign, mock_get_perms, mock_roles, app_and_db
    ):
        """Admin REAL de maint puede asignar.

        Tras la auditoría, asignar exige rol/permiso operativo REAL en maint;
        ser admin GLOBAL del sistema (JWT role='admin') ya NO basta por bypass.
        """
        _, client, mock_db = app_and_db

        mock_has_assign.return_value = True
        mock_get_perms.return_value = {"maint.assignments.api.assign"}
        mock_roles.return_value = {"admin"}

        assignment = MagicMock()
        assignment.id = 1
        mock_assign.return_value = [assignment]

        ticket = MagicMock()
        ticket.id = 1
        ticket.ticket_number = "MANT-2026-000001"
        mock_db.get.return_value = ticket

        r = client.post(
            "/api/maint/v2/tickets/1/assign",
            json={"user_ids": [50]},
            headers=_plain_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["assigned_count"] == 1

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.assignment_service.assign_technicians")
    def test_global_admin_without_maint_role_assign_blocked(
        self, mock_assign, mock_has_assign, mock_get_perms, mock_roles, app_and_db
    ):
        """Admin GLOBAL del sistema SIN rol operativo en maint → 403 al asignar.

        Regresión de la auditoría: 'admin global del sistema ≠ operador de maint'.
        """
        _, client, mock_db = app_and_db

        mock_has_assign.return_value = True
        # Jefe de otro depto: tiene perms de solicitante pero NO de asignar.
        mock_get_perms.return_value = {
            "maint.tickets.api.create",
            "maint.tickets.api.read.department",
        }
        mock_roles.return_value = {"department_head"}

        r = client.post(
            "/api/maint/v2/tickets/1/assign",
            json={"user_ids": [50]},
            headers=_admin_headers(user_id=1),  # JWT role='admin' (global)
        )
        assert r.status_code == 403, r.text
        mock_assign.assert_not_called()

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.apps.maint.services.assignment_service.assign_technicians")
    @patch("itcj2.apps.maint.services.notification_helper.MaintNotificationHelper.notify_technician_assigned")
    def test_area_coordinator_wrong_area_returns_403(
        self, mock_notify, mock_assign, mock_has_assign, mock_get_perms, mock_roles, app_and_db
    ):
        """Coordinador de área que intenta asignar a técnico fuera de su área → 403."""
        from fastapi import HTTPException

        _, client, mock_db = app_and_db

        # El usuario 10 tiene permiso de asignar
        mock_has_assign.return_value = True
        mock_get_perms.return_value = {"maint.assignments.api.assign"}
        mock_roles.return_value = {"maint_area_coordinator"}

        # assign_technicians lanza el 403 de restricción de área
        mock_assign.side_effect = HTTPException(
            status_code=403,
            detail="No puedes asignar al técnico X (id=50): no pertenece a tu(s) área(s) de coordinación",
        )

        r = client.post(
            "/api/maint/v2/tickets/1/assign",
            json={"user_ids": [50]},
            headers=_plain_headers(user_id=10),
        )
        assert r.status_code == 403, r.text
        body = r.json()
        # Las respuestas de error usan {"error": detail, "status": code} (ver main.py)
        msg = (body.get("error") or body.get("detail") or "").lower()
        assert "área" in msg or "area" in msg

    def test_no_permission_returns_403(self, app_and_db):
        """Usuario sin permiso maint.assignments.api.assign → 403."""
        from unittest.mock import patch

        _, client, mock_db = app_and_db

        with (
            patch("itcj2.core.services.authz_service.has_any_assignment", return_value=True),
            patch(
                "itcj2.core.services.authz_service.get_user_permissions_for_app",
                return_value={"maint.tickets.api.create"},  # sin permiso de asignar
            ),
        ):
            r = client.post(
                "/api/maint/v2/tickets/1/assign",
                json={"user_ids": [50]},
                headers=_plain_headers(user_id=20),
            )
        assert r.status_code == 403, r.text


# ─────────────────────────────────────────────────────────────────────
# Integration tests: CRUD coordinadores (admin)
# ─────────────────────────────────────────────────────────────────────

class TestCoordinatorsAPI:
    """Tests del CRUD en /api/maint/v2/coordinators (gate: maint.coordinators.api.manage)."""

    # GET /coordinators — listar
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.list_coordinators")
    def test_list_coordinators_admin_ok(self, mock_list, app_and_db):
        _, client, _ = app_and_db

        mock_list.return_value = [
            {"user_id": 1, "name": "General 1", "areas": [], "is_general": True},
            {"user_id": 2, "name": "Area Coord", "areas": ["ELECTRICAL"], "is_general": False},
        ]

        r = client.get("/api/maint/v2/coordinators", headers=_admin_headers(user_id=1))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["total"] == 2
        assert len(body["data"]) == 2

    def test_list_coordinators_no_auth_returns_401(self, app_and_db):
        _, client, _ = app_and_db
        r = client.get("/api/maint/v2/coordinators")
        assert r.status_code == 401

    # GET /coordinators/{user_id}/areas
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_get_coordinator_areas_ok(self, mock_areas, app_and_db):
        _, client, _ = app_and_db
        mock_areas.return_value = ["ELECTRICAL", "CARPENTRY"]

        r = client.get("/api/maint/v2/coordinators/10/areas", headers=_admin_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert set(body["data"]["areas"]) == {"ELECTRICAL", "CARPENTRY"}
        assert body["data"]["user_id"] == 10

    # PUT /coordinators/{user_id}/areas
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.set_coordinator_areas")
    def test_set_coordinator_areas_ok(self, mock_set, app_and_db):
        _, client, _ = app_and_db
        mock_set.return_value = ["TRANSPORT", "GENERAL"]

        r = client.put(
            "/api/maint/v2/coordinators/10/areas",
            json={"area_codes": ["TRANSPORT", "GENERAL"]},
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert set(body["data"]["areas"]) == {"TRANSPORT", "GENERAL"}
        mock_set.assert_called_once_with(
            db=ANY,
            user_id=10,
            area_codes=["TRANSPORT", "GENERAL"],
            performed_by_id=1,
        )

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.set_coordinator_areas")
    def test_set_coordinator_areas_invalid_code_returns_400(self, mock_set, app_and_db):
        _, client, _ = app_and_db
        mock_set.side_effect = ValueError("Áreas inválidas: INVALID_CODE. Válidas: ...")

        r = client.put(
            "/api/maint/v2/coordinators/10/areas",
            json={"area_codes": ["INVALID_CODE"]},
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 400, r.text
        body = r.json()
        # Las respuestas de error usan {"error": detail, "status": code}
        msg = (body.get("error") or body.get("detail") or "").lower()
        assert "inválidas" in msg or "invalid" in msg or "reas" in msg

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.set_coordinator_areas")
    def test_set_coordinator_areas_empty_clears_all(self, mock_set, app_and_db):
        """Enviar lista vacía debe eliminar todas las áreas."""
        _, client, _ = app_and_db
        mock_set.return_value = []

        r = client.put(
            "/api/maint/v2/coordinators/10/areas",
            json={"area_codes": []},
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        mock_set.assert_called_once()
        call_args = mock_set.call_args
        assert call_args.kwargs["area_codes"] == [] or call_args.args[2] == []


# ─────────────────────────────────────────────────────────────────────
# Unit tests: CoordinatorService.set_coordinator_areas
# ─────────────────────────────────────────────────────────────────────

class TestSetCoordinatorAreas:
    """Tests en unidad del service set_coordinator_areas."""

    @patch("itcj2.apps.maint.services.coordinator_service.get_area_codes")
    def test_valid_areas_committed(self, mock_areas):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.core.models.user import User

        mock_areas.return_value = {"ELECTRICAL", "TRANSPORT", "GENERAL"}

        db = MagicMock()
        user = MagicMock(spec=User)
        user.id = 10
        db.get.return_value = user
        db.query.return_value.filter_by.return_value.delete.return_value = 0

        result = CoordinatorService.set_coordinator_areas(
            db=db,
            user_id=10,
            area_codes=["ELECTRICAL", "TRANSPORT"],
            performed_by_id=1,
        )
        assert set(result) == {"ELECTRICAL", "TRANSPORT"}
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.services.coordinator_service.get_area_codes")
    def test_invalid_area_raises_value_error(self, mock_areas):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.core.models.user import User

        mock_areas.return_value = {"ELECTRICAL", "TRANSPORT"}

        db = MagicMock()
        user = MagicMock(spec=User)
        user.id = 10
        db.get.return_value = user

        with pytest.raises(ValueError) as exc_info:
            CoordinatorService.set_coordinator_areas(
                db=db,
                user_id=10,
                area_codes=["INVALID"],
                performed_by_id=1,
            )
        assert "inválidas" in str(exc_info.value).lower() or "INVALID" in str(exc_info.value)

    def test_user_not_found_raises_value_error(self):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService

        db = MagicMock()
        db.get.return_value = None  # usuario no encontrado

        with pytest.raises(ValueError) as exc_info:
            CoordinatorService.set_coordinator_areas(
                db=db,
                user_id=999,
                area_codes=["ELECTRICAL"],
                performed_by_id=1,
            )
        assert "999" in str(exc_info.value) or "no encontrado" in str(exc_info.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Unit tests: CoordinatorService.list_coordinators
# ─────────────────────────────────────────────────────────────────────

class TestListCoordinators:
    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_returns_general_and_area_coordinators(self, mock_get_users):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea
        from itcj2.core.models.user import User

        # _get_users_with_roles_in_app se llama 2 veces (M6): generales, luego de área.
        mock_get_users.side_effect = [[1, 2], [3]]

        db = MagicMock()

        user1 = MagicMock(spec=User)
        user1.id = 1
        user1.full_name = "General A"

        user2 = MagicMock(spec=User)
        user2.id = 2
        user2.full_name = "General B"

        user3 = MagicMock(spec=User)
        user3.id = 3
        user3.full_name = "Area Coord"

        # db.get devuelve en orden los usuarios
        db.get.side_effect = [user1, user2, user3, user3]

        # área coordinators: user 3 con 2 áreas
        area_row1 = MagicMock(spec=MaintCoordinatorArea)
        area_row1.user_id = 3
        area_row1.area_code = "ELECTRICAL"

        area_row2 = MagicMock(spec=MaintCoordinatorArea)
        area_row2.user_id = 3
        area_row2.area_code = "CARPENTRY"

        db.query.return_value.order_by.return_value.all.return_value = [area_row1, area_row2]

        result = CoordinatorService.list_coordinators(db)

        # Debe tener 3 entradas (2 generales + 1 de área)
        assert len(result) == 3

        generals = [c for c in result if c["is_general"]]
        area_coords = [c for c in result if not c["is_general"]]

        assert len(generals) == 2
        assert len(area_coords) == 1
        assert set(area_coords[0]["areas"]) == {"ELECTRICAL", "CARPENTRY"}


# ─────────────────────────────────────────────────────────────────────
# Integration: Board endpoint
# ─────────────────────────────────────────────────────────────────────

class TestAssignmentBoard:
    @patch("itcj2.apps.maint.services.ticket_service.list_tickets")
    @patch("itcj2.core.services.authz_service.get_user_permissions_for_app")
    @patch("itcj2.core.services.authz_service.has_any_assignment")
    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_board_admin_returns_tickets(
        self, mock_roles, mock_has_assign, mock_get_perms, mock_list, app_and_db
    ):
        """Admin REAL de maint puede ver el board; devuelve estructura correcta.

        El board es vista operativa: exige permiso REAL; el admin GLOBAL del
        sistema ya NO lo lee por bypass (allow_global_admin=False).
        """
        _, client, mock_db = app_and_db

        mock_roles.return_value = {"admin"}
        mock_has_assign.return_value = True
        mock_get_perms.return_value = {"maint.assignments.page.list"}

        ticket_mock = MagicMock()
        ticket_mock.id = 1
        ticket_mock.ticket_number = "MANT-2026-000001"
        ticket_mock.title = "Ticket de prueba"
        ticket_mock.status = "PENDING"
        ticket_mock.priority = "MEDIA"
        ticket_mock.category = MagicMock(code="TRANSPORT")
        ticket_mock.created_at = None
        ticket_mock.technicians = []
        ticket_mock.coordinator_id = None
        ticket_mock.coordinator = None

        mock_list.return_value = {
            "tickets": [ticket_mock],
            "total": 1,
            "pages": 1,
            "current_page": 1,
            "per_page": 50,
            "has_next": False,
            "has_prev": False,
        }

        r = client.get(
            "/api/maint/v2/tickets/board",
            headers=_plain_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["total"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["ticket_number"] == "MANT-2026-000001"

    def test_board_no_auth_returns_401(self, app_and_db):
        _, client, _ = app_and_db
        r = client.get("/api/maint/v2/tickets/board")
        assert r.status_code == 401

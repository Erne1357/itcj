"""
Tests para el flujo de enrutado (triage) de tickets de mantenimiento.

Cubre:
1. route_ticket service: secretaría → general OK; secretaría → área coord → PermissionError.
2. route_ticket service: general re-enruta a área coord OK; general se autoenruta OK.
3. route_ticket service: área coord enruta → PermissionError.
4. assign_technicians: sin enrutar a uno mismo → 403; tras enrutar a uno mismo → OK.
5. Endpoint POST /{ticket_id}/route: HTTP 200 OK; HTTP 403 para dispatcher→área.
6. GET /triage: secretaría ve unrouted; general ve su cola.

Estrategia de mock:
- MagicMock DB session; modelos instanciados como MagicMock.
- JWT admin (role='admin') para tests de endpoint HTTP con TestClient.
- Monkeypatch de CoordinatorService para tests de servicio unitario.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
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
# Helpers para construir objetos mock
# ─────────────────────────────────────────────────────────────────────

def _make_ticket(ticket_id: int = 1, status: str = "PENDING", coordinator_id=None):
    ticket = MagicMock()
    ticket.id = ticket_id
    ticket.ticket_number = f"MANT-2026-{ticket_id:06d}"
    ticket.status = status
    ticket.is_open = status not in ("CLOSED", "CANCELED")
    ticket.technicians = []
    ticket.coordinator_id = coordinator_id
    ticket.coordinator = None
    ticket.updated_at = None
    ticket.updated_by_id = None
    ticket.category = MagicMock(code="GENERAL")
    ticket.created_at = None
    return ticket


def _make_user(user_id: int, full_name: str = "Test User", is_active: bool = True):
    user = MagicMock()
    user.id = user_id
    user.full_name = full_name
    user.is_active = is_active
    return user


# ─────────────────────────────────────────────────────────────────────
# Unit tests: route_ticket service
# ─────────────────────────────────────────────────────────────────────

class TestRouteTicketService:
    """Tests en unidad de assignment_service.route_ticket."""

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_general_coordinator")
    def test_dispatcher_to_general_ok(self, mock_is_general, mock_is_coord):
        """Secretaría (dispatcher) puede enrutar a coordinador general."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_general.return_value = True
        mock_is_coord.return_value = True

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=None)
        target_user = _make_user(20, "General Coord")
        db.get.side_effect = [ticket, target_user]

        result = route_ticket(
            db=db,
            ticket_id=1,
            target_coordinator_id=20,
            performed_by_id=5,
            performer_roles={"dispatcher"},
            is_global_admin=False,
        )
        assert ticket.coordinator_id == 20
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_general_coordinator")
    def test_dispatcher_to_area_coord_raises_permission_error(self, mock_is_general, mock_is_coord):
        """Secretaría (dispatcher) no puede enrutar a coordinador de área → PermissionError."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_general.return_value = False  # target NO es general
        mock_is_coord.return_value = True     # pero sí es coordinador de área

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=None)
        target_user = _make_user(30, "Area Coord")
        db.get.side_effect = [ticket, target_user]

        with pytest.raises(PermissionError) as exc_info:
            route_ticket(
                db=db,
                ticket_id=1,
                target_coordinator_id=30,
                performed_by_id=5,
                performer_roles={"dispatcher"},
                is_global_admin=False,
            )
        assert "general" in str(exc_info.value).lower()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    def test_general_coord_to_area_coord_ok(self, mock_is_coord):
        """Coordinador general puede enrutar a coordinador de área."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_coord.return_value = True

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=None)
        target_user = _make_user(30, "Area Coord")
        db.get.side_effect = [ticket, target_user]

        route_ticket(
            db=db,
            ticket_id=1,
            target_coordinator_id=30,
            performed_by_id=10,
            performer_roles={"maint_general_coordinator"},
            is_global_admin=False,
        )
        assert ticket.coordinator_id == 30
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    def test_general_coord_self_route_ok(self, mock_is_coord):
        """Coordinador general puede enrutarse a sí mismo."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_coord.return_value = True

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=None)
        target_user = _make_user(10, "General Self")
        db.get.side_effect = [ticket, target_user]

        route_ticket(
            db=db,
            ticket_id=1,
            target_coordinator_id=10,
            performed_by_id=10,
            performer_roles={"maint_general_coordinator"},
            is_global_admin=False,
        )
        assert ticket.coordinator_id == 10

    def test_area_coord_cannot_route_foreign_ticket(self):
        """M5: coordinador de área NO puede enrutar un ticket que no está en su cola → PermissionError."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        db = MagicMock()
        # ticket enrutado a OTRO coordinador (no al performer 40) → falla por propiedad
        ticket = _make_ticket(coordinator_id=99)
        db.get.return_value = ticket

        with pytest.raises(PermissionError) as exc_info:
            route_ticket(
                db=db,
                ticket_id=1,
                target_coordinator_id=10,
                performed_by_id=40,
                performer_roles={"maint_area_coordinator"},
                is_global_admin=False,
            )
        assert "cola" in str(exc_info.value).lower()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_general_coordinator")
    def test_area_coord_can_return_own_ticket_to_general(self, mock_is_general, mock_is_coord):
        """M5: el coordinador de área puede DEVOLVER un ticket de su cola a un coordinador general."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_coord.return_value = True     # target es coordinador
        mock_is_general.return_value = True   # target es general

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=40)  # enrutado al area coord (performer)
        target_user = _make_user(10, "General Coord")
        db.get.side_effect = [ticket, target_user]

        route_ticket(
            db=db,
            ticket_id=1,
            target_coordinator_id=10,
            performed_by_id=40,
            performer_roles={"maint_area_coordinator"},
            is_global_admin=False,
        )
        assert ticket.coordinator_id == 10
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_coordinator")
    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.is_general_coordinator")
    def test_area_coord_cannot_return_to_non_general(self, mock_is_general, mock_is_coord):
        """M5: devolver a un target que NO es general → PermissionError."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        mock_is_coord.return_value = True      # target es coordinador
        mock_is_general.return_value = False   # pero NO general

        db = MagicMock()
        ticket = _make_ticket(coordinator_id=40)  # propio del performer
        target_user = _make_user(30, "Area Coord 2")
        db.get.side_effect = [ticket, target_user]

        with pytest.raises(PermissionError) as exc_info:
            route_ticket(
                db=db,
                ticket_id=1,
                target_coordinator_id=30,
                performed_by_id=40,
                performer_roles={"maint_area_coordinator"},
                is_global_admin=False,
            )
        assert "general" in str(exc_info.value).lower()

    def test_closed_ticket_raises_409(self):
        """Ticket cerrado no se puede enrutar → HTTPException 409."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        db = MagicMock()
        ticket = _make_ticket(status="CLOSED")
        db.get.return_value = ticket

        with pytest.raises(HTTPException) as exc_info:
            route_ticket(
                db=db,
                ticket_id=1,
                target_coordinator_id=20,
                performed_by_id=1,
                performer_roles={"admin"},
                is_global_admin=True,
            )
        assert exc_info.value.status_code == 409

    def test_ticket_not_found_raises_404(self):
        """Ticket inexistente → HTTPException 404."""
        from itcj2.apps.maint.services.assignment_service import route_ticket

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            route_ticket(
                db=db,
                ticket_id=9999,
                target_coordinator_id=20,
                performed_by_id=1,
                performer_roles={"admin"},
                is_global_admin=True,
            )
        assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# Unit tests: assign_technicians con restricción de propiedad de enrutado
# ─────────────────────────────────────────────────────────────────────

class TestAssignTechniciansRoutingOwnership:
    """Coordinador solo puede asignar si el ticket está enrutado a él."""

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_coordinator_no_routing_ownership_raises_403(self, mock_roles, mock_can_assign):
        """Coordinador de área intenta asignar a ticket NO enrutado a él → 403."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # El ticket está enrutado a coordinador_id=99, pero el asignador es 10
        ticket = MagicMock()
        ticket.id = 1
        ticket.ticket_number = "MANT-2026-000001"
        ticket.status = "PENDING"
        ticket.is_open = True
        ticket.technicians = []
        ticket.coordinator_id = 99  # enrutado a OTRO coordinador
        tech = _make_user(50)
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
        assert "enrutado" in exc_info.value.detail.lower()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_coordinator_with_routing_ownership_ok(self, mock_roles, mock_can_assign):
        """Coordinador de área asigna técnico a ticket enrutado a él → OK."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        # El ticket está enrutado al mismo coordinador_id=10
        ticket = MagicMock()
        ticket.id = 1
        ticket.ticket_number = "MANT-2026-000001"
        ticket.status = "PENDING"
        ticket.is_open = True
        ticket.technicians = []
        ticket.coordinator_id = 10  # enrutado A mí mismo
        ticket.updated_at = None
        ticket.updated_by_id = None
        tech = _make_user(50)
        db.get.side_effect = [ticket, tech]

        # No debe lanzar excepción
        assignment_service.assign_technicians(
            db=db,
            ticket_id=1,
            assigned_by_id=10,
            user_ids=[50],
            assigner_roles={"maint_area_coordinator"},
            is_global_admin=False,
        )

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.can_assign_technician")
    @patch("itcj2.apps.maint.services.assignment_service.user_roles_in_app")
    def test_admin_bypasses_routing_ownership(self, mock_roles, mock_can_assign):
        """Admin global puede asignar aunque el ticket esté enrutado a otro coordinador."""
        from itcj2.apps.maint.services import assignment_service

        mock_can_assign.return_value = True
        mock_roles.return_value = {"tech_maint"}

        db = MagicMock()
        ticket = MagicMock()
        ticket.id = 1
        ticket.ticket_number = "MANT-2026-000001"
        ticket.status = "PENDING"
        ticket.is_open = True
        ticket.technicians = []
        ticket.coordinator_id = 99  # enrutado a otro, pero admin bypasa
        ticket.updated_at = None
        ticket.updated_by_id = None
        tech = _make_user(50)
        db.get.side_effect = [ticket, tech]

        # Admin no debe ver el error de propiedad
        assignment_service.assign_technicians(
            db=db,
            ticket_id=1,
            assigned_by_id=1,
            user_ids=[50],
            assigner_roles={"admin"},
            is_global_admin=True,
        )


# ─────────────────────────────────────────────────────────────────────
# Integration tests: endpoint POST /tickets/{id}/route
# ─────────────────────────────────────────────────────────────────────

class TestRouteEndpoint:
    """Tests HTTP del endpoint POST /{ticket_id}/route."""

    @patch("itcj2.apps.maint.services.assignment_service.route_ticket")
    def test_admin_route_ok(self, mock_route, app_and_db):
        """Admin puede enrutar un ticket → 200."""
        _, client, mock_db = app_and_db

        ticket = _make_ticket(coordinator_id=20)
        coord_user = _make_user(20, "General Coord")
        ticket.coordinator = coord_user
        mock_route.return_value = ticket

        r = client.post(
            "/api/maint/v2/tickets/1/route",
            json={"coordinator_id": 20},
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["data"]["ticket_id"] == 1

    @patch("itcj2.apps.maint.services.assignment_service.route_ticket")
    def test_dispatcher_to_area_coord_returns_403(self, mock_route, app_and_db):
        """Dispatcher → coordinador de área → 403."""
        from itcj2.core.services.authz_service import user_roles_in_app as _roles_fn

        _, client, mock_db = app_and_db

        mock_route.side_effect = PermissionError(
            "La secretaría solo puede enrutar a un coordinador general"
        )

        with (
            patch("itcj2.core.services.authz_service.has_any_assignment", return_value=True),
            patch(
                "itcj2.core.services.authz_service.get_user_permissions_for_app",
                return_value={"maint.assignments.api.route"},
            ),
            patch(
                "itcj2.core.services.authz_service.user_roles_in_app",
                return_value={"dispatcher"},
            ),
        ):
            r = client.post(
                "/api/maint/v2/tickets/1/route",
                json={"coordinator_id": 30},
                headers=_plain_headers(user_id=5),
            )
        assert r.status_code == 403, r.text
        body = r.json()
        msg = (body.get("error") or body.get("detail") or "").lower()
        assert "general" in msg

    def test_no_auth_returns_401(self, app_and_db):
        _, client, _ = app_and_db
        r = client.post("/api/maint/v2/tickets/1/route", json={"coordinator_id": 20})
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Integration tests: GET /tickets/triage
# ─────────────────────────────────────────────────────────────────────

class TestTriageEndpoint:
    """Tests HTTP del endpoint GET /tickets/triage."""

    def test_admin_sees_unrouted_tickets(self, app_and_db):
        """Admin ve tickets sin enrutar en la respuesta de triage."""
        _, client, mock_db = app_and_db

        ticket1 = _make_ticket(1, "PENDING", coordinator_id=None)
        ticket1.category = MagicMock(code="GENERAL")
        ticket1.created_at = None
        ticket1.coordinator = None

        # La query de triage hace db.query(...).filter(...).order_by(...).all()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            ticket1
        ]

        r = client.get(
            "/api/maint/v2/tickets/triage",
            headers=_admin_headers(user_id=1),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert "unrouted" in body["data"]
        assert "mine" in body["data"]

    def test_no_auth_returns_401(self, app_and_db):
        _, client, _ = app_and_db
        r = client.get("/api/maint/v2/tickets/triage")
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Unit tests: nuevos helpers de CoordinatorService
# ─────────────────────────────────────────────────────────────────────

class TestCoordinatorServiceHelpers:
    """Tests de los nuevos helpers is_area_coordinator, is_coordinator, list_general/area."""

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_is_area_coordinator_true(self, mock_roles):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        mock_roles.return_value = {"maint_area_coordinator"}
        assert CoordinatorService.is_area_coordinator(MagicMock(), 5) is True

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_is_area_coordinator_false(self, mock_roles):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        mock_roles.return_value = {"dispatcher"}
        assert CoordinatorService.is_area_coordinator(MagicMock(), 5) is False

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_is_coordinator_general(self, mock_roles):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        mock_roles.return_value = {"maint_general_coordinator"}
        assert CoordinatorService.is_coordinator(MagicMock(), 5) is True

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_is_coordinator_area(self, mock_roles):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        mock_roles.return_value = {"maint_area_coordinator"}
        assert CoordinatorService.is_coordinator(MagicMock(), 5) is True

    @patch("itcj2.core.services.authz_service.user_roles_in_app")
    def test_is_coordinator_neither(self, mock_roles):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        mock_roles.return_value = {"dispatcher"}
        assert CoordinatorService.is_coordinator(MagicMock(), 5) is False

    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_list_general_coordinators(self, mock_get_users):
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.core.models.user import User

        mock_get_users.return_value = [1, 2]
        db = MagicMock()

        u1 = MagicMock(spec=User)
        u1.id = 1
        u1.full_name = "General A"

        u2 = MagicMock(spec=User)
        u2.id = 2
        u2.full_name = "General B"

        db.get.side_effect = [u1, u2]

        result = CoordinatorService.list_general_coordinators(db)
        assert len(result) == 2
        assert all("user_id" in r and "name" in r for r in result)

    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_list_area_coordinators_excludes_generals(self, mock_get_users):
        """list_area_coordinators no incluye coordinadores generales."""
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        from itcj2.apps.maint.models.coordinator_area import MaintCoordinatorArea
        from itcj2.core.models.user import User

        # M6: list_area_coordinators deriva del ROL → el helper se llama 2 veces
        # (generales=[1], luego área=[3]). user 1 es general, user 3 es de área.
        mock_get_users.side_effect = [[1], [3]]

        db = MagicMock()
        u3 = MagicMock(spec=User)
        u3.id = 3
        u3.full_name = "Area Coord"
        db.get.return_value = u3

        area_row = MagicMock(spec=MaintCoordinatorArea)
        area_row.user_id = 3
        area_row.area_code = "ELECTRICAL"

        db.query.return_value.order_by.return_value.all.return_value = [area_row]

        result = CoordinatorService.list_area_coordinators(db)
        assert len(result) == 1
        assert result[0]["user_id"] == 3
        assert "ELECTRICAL" in result[0]["areas"]

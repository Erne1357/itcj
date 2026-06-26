"""
Tests para el endpoint POST /api/help-desk/v2/tickets/{ticket_id}/cancel.

Cubre:
  - comp_center cancela ticket ajeno en estado no-terminal → 200 CANCELED.
  - usuario que NO es comp_center NI solicitante → 403.
  - solicitante cancela su propio ticket → 200 CANCELED.
  - ticket en estado terminal → 400 incluso para comp_center.

Estrategia de auth: todos los tests usan role="admin" en el JWT para que
require_perms() haga bypass completo (no toca BD). La lógica de negocio
(quién puede cancelar qué) la prueba cancel_ticket() del service y las
condiciones mockeadas en _get_user_dept_code.
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_jwt

BASE = "/api/help-desk/v2/tickets"

TERMINAL_STATUSES = ["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED"]


# ---------------------------------------------------------------------------
# Helpers de factory
# ---------------------------------------------------------------------------

def _make_ticket(
    ticket_id: int = 1,
    requester_id: int = 99,
    status: str = "PENDING",
    assigned_to_user_id: int = None,
    area: str = "SOPORTE",
    requester_department_id: int = 5,
):
    """Construye un ticket MagicMock con atributos mínimos necesarios."""
    ticket = MagicMock()
    ticket.id = ticket_id
    ticket.ticket_number = f"TKT-2026-{ticket_id:03d}"
    ticket.requester_id = requester_id
    ticket.status = status
    ticket.assigned_to_user_id = assigned_to_user_id
    ticket.area = area
    ticket.requester_department_id = requester_department_id
    ticket.title = "Ticket de prueba"
    ticket.to_dict.return_value = {
        "id": ticket_id,
        "ticket_number": ticket.ticket_number,
        "status": "CANCELED",
    }
    return ticket


def _make_headers(user_id: int) -> dict:
    """Genera headers con JWT role=admin para que require_perms haga bypass."""
    token = make_jwt(user_id=user_id, role="admin")
    return {"Cookie": f"itcj_token={token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCancelTicketCompCenter:
    """comp_center puede cancelar tickets de cualquier solicitante."""

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="comp_center")
    @patch("itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_canceled_by_comp_center")
    @patch("itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_canceled")
    @patch("itcj2.sockets.helpdesk.broadcast_ticket_status_changed", return_value=MagicMock())
    def test_comp_center_cancels_other_requester_ticket(
        self,
        mock_broadcast,
        mock_notify_canceled,
        mock_notify_comp_center,
        mock_dept_code,
        app_client,
    ):
        """comp_center cancela ticket ajeno en estado PENDING → 200, status CANCELED."""
        comp_center_user_id = 10
        requester_id = 99  # distinto al cancelador

        ticket = _make_ticket(ticket_id=1, requester_id=requester_id, status="PENDING")

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(comp_center_user_id)

        try:
            resp = app_client.post(
                f"{BASE}/1/cancel",
                json={"reason": "Cancelado administrativamente"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Ticket cancelado exitosamente"
        # Verificar que se notificó al solicitante
        mock_notify_comp_center.assert_called_once()
        # Verificar que se notificó al técnico (flujo normal)
        mock_notify_canceled.assert_called_once()

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="comp_center")
    @patch("itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_canceled_by_comp_center")
    @patch("itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_canceled")
    @patch("itcj2.sockets.helpdesk.broadcast_ticket_status_changed", return_value=MagicMock())
    def test_comp_center_cancels_own_ticket_no_double_notif(
        self,
        mock_broadcast,
        mock_notify_canceled,
        mock_notify_comp_center,
        mock_dept_code,
        app_client,
    ):
        """Si comp_center cancela su propio ticket, no se envía la notificación extra al solicitante."""
        user_id = 10  # mismo como requester

        ticket = _make_ticket(ticket_id=2, requester_id=user_id, status="ASSIGNED")

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(user_id)

        try:
            resp = app_client.post(
                f"{BASE}/2/cancel",
                json={"reason": "Ya no lo necesito"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        # comp_center que también es requester: NO se envía la notificación extra
        mock_notify_comp_center.assert_not_called()
        mock_notify_canceled.assert_called_once()


class TestCancelTicketRequester:
    """El solicitante puede cancelar su propio ticket."""

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="informatica")
    @patch("itcj2.apps.helpdesk.services.notification_helper.HelpdeskNotificationHelper.notify_ticket_canceled")
    @patch("itcj2.sockets.helpdesk.broadcast_ticket_status_changed", return_value=MagicMock())
    def test_requester_cancels_own_ticket(
        self,
        mock_broadcast,
        mock_notify_canceled,
        mock_dept_code,
        app_client,
    ):
        """Solicitante cancela su propio ticket → 200."""
        user_id = 99

        ticket = _make_ticket(ticket_id=3, requester_id=user_id, status="IN_PROGRESS")

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(user_id)

        try:
            resp = app_client.post(
                f"{BASE}/3/cancel",
                json={"reason": "Ya no es necesario"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Ticket cancelado exitosamente"


class TestCancelTicketUnauthorized:
    """Usuario sin permisos (no comp_center, no solicitante) → 403."""

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="rh")
    def test_other_dept_non_requester_gets_403(
        self,
        mock_dept_code,
        app_client,
    ):
        """Usuario de otro departamento que no es el solicitante → 403."""
        intruder_id = 55
        requester_id = 99  # distinto al intruder

        ticket = _make_ticket(ticket_id=4, requester_id=requester_id, status="PENDING")

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        # JWT admin para bypassear require_perms, pero user_id != requester_id
        headers = _make_headers(intruder_id)

        try:
            resp = app_client.post(
                f"{BASE}/4/cancel",
                json={"reason": "No debería poder"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 403
        # La app envuelve HTTPException en {"error": ..., "status": ...}
        error_msg = resp.json()["error"].lower()
        assert "solicitante" in error_msg or "centro" in error_msg

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value=None)
    def test_user_without_dept_non_requester_gets_403(
        self,
        mock_dept_code,
        app_client,
    ):
        """Usuario sin puesto activo que no es el solicitante → 403."""
        intruder_id = 66
        requester_id = 99

        ticket = _make_ticket(ticket_id=5, requester_id=requester_id, status="ASSIGNED")

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(intruder_id)

        try:
            resp = app_client.post(
                f"{BASE}/5/cancel",
                json={},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 403


class TestCancelTicketTerminalStatus:
    """Tickets en estado terminal no pueden cancelarse, ni siquiera por comp_center."""

    @pytest.mark.parametrize("terminal_status", TERMINAL_STATUSES)
    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="comp_center")
    def test_comp_center_cannot_cancel_terminal_ticket(
        self,
        mock_dept_code,
        terminal_status,
        app_client,
    ):
        """comp_center intenta cancelar ticket en estado terminal → 400."""
        comp_center_user_id = 10

        ticket = _make_ticket(ticket_id=6, requester_id=99, status=terminal_status)

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(comp_center_user_id)

        try:
            resp = app_client.post(
                f"{BASE}/6/cancel",
                json={"reason": "Intento sobre terminal"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 400
        # La app envuelve HTTPException en {"error": ..., "status": ...}
        error_msg = resp.json()["error"].lower()
        assert "cancelar" in error_msg or "resuelto" in error_msg or "cerrado" in error_msg

    @pytest.mark.parametrize("terminal_status", TERMINAL_STATUSES)
    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="informatica")
    def test_requester_cannot_cancel_terminal_ticket(
        self,
        mock_dept_code,
        terminal_status,
        app_client,
    ):
        """El propio solicitante tampoco puede cancelar un ticket terminal → 400."""
        user_id = 99

        ticket = _make_ticket(ticket_id=7, requester_id=user_id, status=terminal_status)

        mock_db = MagicMock()
        mock_db.get.return_value = ticket

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(user_id)

        try:
            resp = app_client.post(
                f"{BASE}/7/cancel",
                json={"reason": "Quiero cancelar resuelto"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 400


class TestCancelTicketNotFound:
    """Ticket inexistente → 404."""

    @patch("itcj2.apps.helpdesk.api.tickets._get_user_dept_code", return_value="comp_center")
    def test_ticket_not_found(self, mock_dept_code, app_client):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        from itcj2.database import get_db

        def override_db():
            yield mock_db

        app_client.app.dependency_overrides[get_db] = override_db
        headers = _make_headers(10)

        try:
            resp = app_client.post(
                f"{BASE}/9999/cancel",
                json={"reason": "No existe"},
                headers=headers,
            )
        finally:
            app_client.app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 404

    def test_unauthenticated(self, app_client):
        """Sin cookie → 401."""
        resp = app_client.post(f"{BASE}/1/cancel", json={"reason": "x"})
        assert resp.status_code == 401

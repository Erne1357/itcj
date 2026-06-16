"""
Regresión de Fase 2 (auditoría de producción maint) — scope de departamento.

H4 — GET /tickets acepta `requester=me` (Mis solicitudes) y `unrated=1`
     (Por calificar) y los pasa al service como requester_me / unrated.
H5 — list_tickets resuelve TODOS los departamentos del jefe/secretaria
     (multi-puesto) vía _resolve_user_departments + .in_() (antes .first()
     elegía un departamento aleatorio).

Estrategia de mock idéntica a test_routing.py (MagicMock DB, JWT por cookie).
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


def _make_jwt(user_id, role=None):
    settings = get_settings()
    now = int(time.time())
    payload = {"sub": str(user_id), "role": role, "cn": None, "name": "Test",
               "iat": now, "exp": now + 24 * 3600}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers(user_id=1):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role='admin')}"}


@pytest.fixture
def client_and_db():
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        yield client, mock_db
    app.dependency_overrides.clear()


# ───────────────────────── H4: params de pestaña ─────────────────────────

class TestTabParams:

    @patch("itcj2.apps.maint.services.ticket_service.list_tickets")
    @patch("itcj2.core.services.authz_service.user_roles_in_app", return_value=[])
    def test_requester_and_unrated_passed_to_service(self, _mock_roles, mock_list, client_and_db):
        """H4: ?requester=me&unrated=1 → list_tickets(requester_me=True, unrated=True)."""
        client, _ = client_and_db
        mock_list.return_value = {
            "tickets": [], "total": 0, "pages": 0, "current_page": 1, "per_page": 20,
        }

        resp = client.get("/api/maint/v2/tickets?requester=me&unrated=1", headers=_admin_headers())

        assert resp.status_code == 200
        kwargs = mock_list.call_args.kwargs
        assert kwargs["requester_me"] is True
        assert kwargs["unrated"] is True

    @patch("itcj2.apps.maint.services.ticket_service.list_tickets")
    @patch("itcj2.core.services.authz_service.user_roles_in_app", return_value=[])
    def test_defaults_false_without_params(self, _mock_roles, mock_list, client_and_db):
        """Sin params, requester_me y unrated van en False."""
        client, _ = client_and_db
        mock_list.return_value = {
            "tickets": [], "total": 0, "pages": 0, "current_page": 1, "per_page": 20,
        }

        resp = client.get("/api/maint/v2/tickets", headers=_admin_headers())

        assert resp.status_code == 200
        kwargs = mock_list.call_args.kwargs
        assert kwargs["requester_me"] is False
        assert kwargs["unrated"] is False


# ───────────────────────── H5: multi-departamento ─────────────────────────

class TestMultiDeptScope:

    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    @patch("itcj2.apps.maint.services.department_dashboard_service._resolve_user_departments")
    def test_dept_role_resolves_all_departments(self, mock_resolve, mock_paginate):
        """H5: un jefe/secretaria resuelve TODOS sus departamentos (no .first())."""
        from itcj2.apps.maint.services.ticket_service import list_tickets

        mock_resolve.return_value = [
            {"id": 7, "code": "A", "name": "Depto A"},
            {"id": 9, "code": "B", "name": "Depto B"},
        ]
        mock_paginate.return_value = MagicMock(items=[], total=0, pages=0)
        db = MagicMock()

        list_tickets(db=db, user_id=42, user_roles=["department_head"])

        mock_resolve.assert_called_once_with(db, 42)

    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    @patch("itcj2.apps.maint.services.department_dashboard_service._resolve_user_departments")
    def test_admin_skips_dept_resolution(self, mock_resolve, mock_paginate):
        """Un rol de acceso total (admin) NO entra al camino de departamentos."""
        from itcj2.apps.maint.services.ticket_service import list_tickets

        mock_paginate.return_value = MagicMock(items=[], total=0, pages=0)
        db = MagicMock()

        list_tickets(db=db, user_id=1, user_roles=["admin"])

        mock_resolve.assert_not_called()

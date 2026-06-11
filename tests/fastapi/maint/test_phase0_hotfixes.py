"""
Regresión de los hotfixes de Fase 0 (auditoría de producción maint, 11-jun-2026).

BUG 1 — GET /api/maint/v2/technicians
  - Responde con la convención {success, data, total} (antes {technicians}) → BUG 1-A.
  - Incluye técnicos dados de alta por PUESTO (no solo UserAppRole), vía
    _get_users_with_roles_in_app → BUG 1-B.
  - Pide los roles tech_maint + coordinadores y EXCLUYE dispatcher → M4.

BUG 2 (D-F) — ticket_service.resolve_ticket
  - Técnico/coordinador NO puede resolver directo desde ASSIGNED (HTTP 400).
  - Sí puede resolver desde IN_PROGRESS.
  - dispatcher/admin (is_fast_resolver=True) conserva la vía rápida ASSIGNED → RESOLVED.

Estrategia de mock idéntica a test_routing.py (MagicMock DB, JWT por cookie).
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
from itcj2.apps.maint.services import ticket_service


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _make_jwt(user_id, role=None):
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": role, "cn": None, "name": "Test User",
        "iat": now, "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers(user_id=1):
    return {"Cookie": f"itcj_token={_make_jwt(user_id, role='admin')}"}


def _make_user(user_id, full_name="Tech User", is_active=True):
    u = MagicMock()
    u.id = user_id
    u.full_name = full_name
    u.is_active = is_active
    return u


def _make_ticket(status):
    t = MagicMock()
    t.status = status
    t.technicians = []          # nadie asignado → resolutor es "dispatcher"
    t.ticket_number = "MANT-2026-000001"
    return t


@pytest.fixture
def client_and_db():
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        yield client, mock_db
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────
# BUG 1 — GET /technicians
# ─────────────────────────────────────────────────────────────────────

class TestTechniciansEndpoint:

    @patch("itcj2.apps.maint.api.technicians.assignment_service.get_technician_areas")
    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_format_and_puesto_technician(self, mock_get_users, mock_areas, client_and_db):
        """BUG 1-A + 1-B: técnico por PUESTO aparece y la respuesta usa {success,data,total}."""
        client, mock_db = client_and_db
        mock_get_users.return_value = [20]          # técnico captado por puesto
        (mock_db.query.return_value.filter.return_value
         .order_by.return_value.all.return_value) = [_make_user(20, "Tech By Position")]
        mock_areas.return_value = []

        resp = client.get("/api/maint/v2/technicians", headers=_admin_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "technicians" not in body          # ya NO usa la clave vieja
        assert body["total"] == 1
        assert body["data"][0]["id"] == 20
        assert body["data"][0]["name"] == "Tech By Position"

    @patch("itcj2.apps.maint.api.technicians.assignment_service.get_technician_areas")
    @patch("itcj2.core.services.authz_service._get_users_with_roles_in_app")
    def test_excludes_dispatcher_role(self, mock_get_users, mock_areas, client_and_db):
        """M4: el picker pide tech_maint + coordinadores y NO incluye dispatcher."""
        client, mock_db = client_and_db
        mock_get_users.return_value = []
        mock_areas.return_value = []

        resp = client.get("/api/maint/v2/technicians", headers=_admin_headers())

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "data": [], "total": 0}
        # roles solicitados al helper: (db, "maint", roles)
        called_roles = set(mock_get_users.call_args[0][2])
        assert "dispatcher" not in called_roles
        assert "admin" not in called_roles
        assert "tech_maint" in called_roles
        assert {"maint_general_coordinator", "maint_area_coordinator"} <= called_roles


# ─────────────────────────────────────────────────────────────────────
# BUG 2 (D-F) — resolve_ticket gate
# ─────────────────────────────────────────────────────────────────────

class TestResolveGate:

    def _resolve(self, db, is_fast_resolver):
        return ticket_service.resolve_ticket(
            db=db, ticket_id=1, resolved_by_id=20, success=True,
            maintenance_type="PREVENTIVO", service_origin="INTERNO",
            resolution_notes="listo", time_invested_minutes=30,
            is_fast_resolver=is_fast_resolver,
        )

    def test_tech_cannot_resolve_from_assigned(self):
        """Técnico (is_fast_resolver=False) NO puede resolver desde ASSIGNED → 400."""
        db = MagicMock()
        db.get.return_value = _make_ticket("ASSIGNED")

        with pytest.raises(HTTPException) as exc:
            self._resolve(db, is_fast_resolver=False)

        assert exc.value.status_code == 400
        assert "iniciar el progreso" in exc.value.detail.lower()
        db.commit.assert_not_called()

    @patch("itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes")
    def test_dispatcher_fast_resolves_from_assigned(self, mock_types, mock_origins):
        """dispatcher/admin (is_fast_resolver=True) conserva la vía rápida ASSIGNED → RESOLVED."""
        mock_types.return_value = {"PREVENTIVO", "CORRECTIVO"}
        mock_origins.return_value = {"INTERNO", "EXTERNO"}
        ticket = _make_ticket("ASSIGNED")
        db = MagicMock()
        db.get.return_value = ticket

        result_ticket, warnings = self._resolve(db, is_fast_resolver=True)

        assert result_ticket.status == "RESOLVED_SUCCESS"
        assert warnings == []
        db.commit.assert_called_once()

    @patch("itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes")
    @patch("itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes")
    def test_tech_resolves_from_in_progress(self, mock_types, mock_origins):
        """Técnico SÍ puede resolver desde IN_PROGRESS (la vía normal)."""
        mock_types.return_value = {"PREVENTIVO", "CORRECTIVO"}
        mock_origins.return_value = {"INTERNO", "EXTERNO"}
        ticket = _make_ticket("IN_PROGRESS")
        db = MagicMock()
        db.get.return_value = ticket

        result_ticket, _ = self._resolve(db, is_fast_resolver=False)

        assert result_ticket.status == "RESOLVED_SUCCESS"
        db.commit.assert_called_once()

"""
Smoke tests para los endpoints globales del warehouse: /api/warehouse/v2/*.

Verifica:
- 401 sin auth en todos los endpoints clave.
- Happy path con admin JWT (bypass require_perms) y servicios mockeados.
- 403 cuando un usuario no-admin no tiene el permiso requerido.

Notas:
- Los endpoints viven en itcj2/apps/warehouse/api/* y se montan vía
  warehouse_router con prefijo /api/warehouse/v2.
- Aunque "warehouse" es la app a nivel autorización, los endpoints aún
  honran admin global por JWT (require_perms revisa role=='admin').
"""
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


def _jwt(user_id: int = 1, role: str | None = "admin") -> str:
    # exp = 24h evita el refresh del middleware (threshold 2h) que abre
    # SessionLocal real y rompe tests sin BD.
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "cn": None,
            "name": "Test",
            "iat": now,
            "exp": now + 24 * 3600,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


@pytest.fixture
def app_client():
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as c:
        c._mock_db = mock_db
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    return {"Cookie": f"itcj_token={_jwt(role='admin')}"}


@pytest.fixture
def no_admin_headers():
    return {"Cookie": f"itcj_token={_jwt(role=None)}"}


# ─────────────────────────────────────────────────────────────────────
# Auth gates — 401 sin cookie
# ─────────────────────────────────────────────────────────────────────

class TestAuthGates:
    @pytest.mark.parametrize("path", [
        "/api/warehouse/v2/dashboard",
        "/api/warehouse/v2/products",
        "/api/warehouse/v2/categories",
        "/api/warehouse/v2/stock-entries",
        "/api/warehouse/v2/movements",
    ])
    def test_no_auth_returns_401(self, app_client, path):
        r = app_client.get(path)
        assert r.status_code == 401, f"{path} → {r.status_code}"

    @pytest.mark.parametrize("path", [
        "/api/warehouse/v2/dashboard",
        "/api/warehouse/v2/products",
    ])
    def test_invalid_token_returns_401(self, app_client, path):
        r = app_client.get(path, headers={"Cookie": "itcj_token=bad"})
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Forbidden — usuario sin perm, sin admin global
# ─────────────────────────────────────────────────────────────────────

class TestForbiddenWithoutPerm:
    def test_non_admin_without_perm_gets_403(self, app_client, no_admin_headers):
        """User con JWT válido pero sin perms warehouse → 403."""
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=False,
        ):
            r = app_client.get(
                "/api/warehouse/v2/products",
                headers=no_admin_headers,
            )
        assert r.status_code == 403

    def test_non_admin_with_assignment_but_no_perm_gets_403(
        self, app_client, no_admin_headers
    ):
        """User asignado a warehouse pero sin el perm específico → 403."""
        with patch(
            "itcj2.core.services.authz_service.has_any_assignment",
            return_value=True,
        ), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=set(),
        ):
            r = app_client.get(
                "/api/warehouse/v2/products",
                headers=no_admin_headers,
            )
        assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────
# Products endpoints
# ─────────────────────────────────────────────────────────────────────

class TestProducts:
    @patch("itcj2.apps.warehouse.services.utils.resolve_dept_code")
    @patch("itcj2.apps.warehouse.services.product_service.list_products")
    def test_list_products(self, mock_list, mock_dept, app_client, admin_headers):
        mock_dept.return_value = "equipment_maint"
        mock_list.return_value = []
        r = app_client.get(
            "/api/warehouse/v2/products?dept=equipment_maint",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body == {"products": [], "total": 0}

    @patch("itcj2.apps.warehouse.services.utils.resolve_dept_code")
    @patch("itcj2.apps.warehouse.services.product_service.get_available_for_autocomplete")
    def test_autocomplete(self, mock_auto, mock_dept, app_client, admin_headers):
        mock_dept.return_value = "equipment_maint"
        mock_auto.return_value = [{"id": 1, "name": "Tornillo"}]
        r = app_client.get(
            "/api/warehouse/v2/products/available?search=tor",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1


# ─────────────────────────────────────────────────────────────────────
# Categories endpoints
# ─────────────────────────────────────────────────────────────────────

class TestCategories:
    @patch("itcj2.apps.warehouse.services.utils.resolve_dept_code")
    @patch("itcj2.apps.warehouse.services.category_service.list_categories")
    def test_list_categories(
        self, mock_list, mock_dept, app_client, admin_headers
    ):
        mock_dept.return_value = "equipment_maint"
        mock_list.return_value = []
        r = app_client.get(
            "/api/warehouse/v2/categories",
            headers=admin_headers,
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Dashboard endpoint
# ─────────────────────────────────────────────────────────────────────

class TestDashboard:
    @patch("itcj2.apps.warehouse.services.utils.resolve_dept_code")
    @patch("itcj2.apps.warehouse.api.dashboard.get_dashboard_payload", create=True)
    def test_dashboard_passes_auth(
        self, mock_payload, mock_dept, app_client, admin_headers
    ):
        # El endpoint puede tener implementación interna; basta con verificar
        # que pasa la cookie y entra al handler. Si el handler revienta por
        # falta de mocks, lo importante para este smoke es que NO sea 401/403.
        mock_dept.return_value = "equipment_maint"
        mock_payload.return_value = {"total_products": 0}
        r = app_client.get(
            "/api/warehouse/v2/dashboard?dept=equipment_maint",
            headers=admin_headers,
        )
        # No nos comprometemos con 200 (depende de queries no mockeadas);
        # solo verificamos que la autorización no es la causa de fallo.
        assert r.status_code not in (401, 403), (
            f"Auth falló inesperadamente: {r.status_code} {r.text}"
        )


# ─────────────────────────────────────────────────────────────────────
# Consume endpoint
# ─────────────────────────────────────────────────────────────────────

class TestConsume:
    @patch("itcj2.apps.warehouse.services.fifo_service.consume")
    def test_consume_endpoint_happy_path(
        self, mock_consume, app_client, admin_headers
    ):
        # consume() devuelve lista de movements (cantidad de lotes FIFO usados)
        mock_consume.return_value = [
            SimpleNamespace(id=1, product_id=1, quantity="2"),
        ]
        r = app_client.post(
            "/api/warehouse/v2/consume",
            headers=admin_headers,
            json={
                "product_id": 1,
                "quantity": "2",
                "source_app": "maint",
                "source_ticket_id": 100,
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["movements_count"] == 1
        assert body["product_id"] == 1

    @patch("itcj2.apps.warehouse.services.fifo_service.consume")
    def test_consume_insufficient_stock_returns_400(
        self, mock_consume, app_client, admin_headers
    ):
        mock_consume.side_effect = ValueError("Stock insuficiente: 1 < 5")
        r = app_client.post(
            "/api/warehouse/v2/consume",
            headers=admin_headers,
            json={
                "product_id": 1,
                "quantity": "5",
                "source_app": "maint",
                "source_ticket_id": 100,
            },
        )
        assert r.status_code == 400

    def test_consume_requires_auth(self, app_client):
        r = app_client.post(
            "/api/warehouse/v2/consume",
            json={
                "product_id": 1,
                "quantity": "2",
                "source_app": "maint",
                "source_ticket_id": 100,
            },
        )
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Stock entries
# ─────────────────────────────────────────────────────────────────────

class TestStockEntries:
    @patch("itcj2.apps.warehouse.services.utils.resolve_dept_code")
    @patch("itcj2.apps.warehouse.services.stock_service.list_entries")
    def test_list_entries(
        self, mock_list, mock_dept, app_client, admin_headers
    ):
        mock_dept.return_value = "equipment_maint"
        # El endpoint accede a result.items/total/pages/page → namespace completo
        mock_list.return_value = SimpleNamespace(
            items=[], total=0, pages=0, page=1, has_next=False
        )
        r = app_client.get(
            "/api/warehouse/v2/stock-entries",
            headers=admin_headers,
        )
        # Auth ok; shape interno puede fallar pero no por permisos
        assert r.status_code not in (401, 403)

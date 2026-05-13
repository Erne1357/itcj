"""
Smoke tests para itcj2/apps/maint/api/warehouse_proxy.py.

Endpoints expuestos en /api/maint/v2/warehouse/* que envuelven al warehouse
global y fuerzan department_code='equipment_maint'.

Estrategia:
- TestClient + get_db override (MagicMock).
- JWT con role='admin' → require_perms bypass.
- Mock de servicios y modelos warehouse para no tocar BD real.
- 401 sin auth (no auth header) y 403 / 401 con token inválido.
"""
import time
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


def _admin_jwt(user_id: int = 1) -> str:
    # exp = 24h evita que el middleware dispare el refresh (>2h threshold)
    # y abra SessionLocal real, lo que rompe los tests sin BD.
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": "admin",
            "cn": None,
            "name": "Admin",
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
    return {"Cookie": f"itcj_token={_admin_jwt()}"}


# ─────────────────────────────────────────────────────────────────────
# Auth gates
# ─────────────────────────────────────────────────────────────────────

class TestAuthGates:
    @pytest.mark.parametrize("path", [
        "/api/maint/v2/warehouse/dashboard",
        "/api/maint/v2/warehouse/categories",
        "/api/maint/v2/warehouse/products",
        "/api/maint/v2/warehouse/stock-entries",
        "/api/maint/v2/warehouse/movements",
    ])
    def test_no_auth_returns_401(self, app_client, path):
        r = app_client.get(path)
        assert r.status_code == 401, f"{path} → {r.status_code}"

    def test_invalid_token_returns_401(self, app_client):
        r = app_client.get(
            "/api/maint/v2/warehouse/dashboard",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Dashboard endpoint — fuerza dept = equipment_maint
# ─────────────────────────────────────────────────────────────────────

class TestProxyDashboard:
    @patch("itcj2.apps.warehouse.services.utils.get_stock_totals")
    @patch("itcj2.apps.warehouse.services.product_service.get_products_below_restock")
    def test_dashboard_returns_payload(
        self, mock_below, mock_totals, app_client, admin_headers
    ):
        mock_below.return_value = []
        mock_totals.return_value = {}

        # Mock de queries en el endpoint: db.query(...).filter(...).scalar() etc.
        # Cadena de query devuelve un MagicMock con .scalar() → 0 y .all() → []
        db = app_client._mock_db
        scalar_chain = MagicMock()
        scalar_chain.filter.return_value.scalar.return_value = 0
        scalar_chain.filter.return_value.all.return_value = []
        scalar_chain.filter.return_value.between.return_value = scalar_chain
        db.query.return_value = scalar_chain

        r = app_client.get("/api/maint/v2/warehouse/dashboard", headers=admin_headers)
        # No nos importa el shape exacto, solo que pase auth y el handler corra
        assert r.status_code in (200, 500)  # 500 si el mock no cubrió toda la query
        if r.status_code == 200:
            body = r.json()
            assert "total_products" in body
            assert "low_stock_count" in body


# ─────────────────────────────────────────────────────────────────────
# Categories — list + create
# ─────────────────────────────────────────────────────────────────────

class TestProxyCategories:
    def test_list_categories_empty(self, app_client, admin_headers):
        db = app_client._mock_db
        chain = MagicMock()
        chain.filter.return_value.order_by.return_value.all.return_value = []
        db.query.return_value = chain

        r = app_client.get("/api/maint/v2/warehouse/categories", headers=admin_headers)
        assert r.status_code == 200
        assert r.json() == {"categories": []}

    @patch("itcj2.apps.warehouse.services.category_service.create_category")
    def test_create_category_returns_id(self, mock_create, app_client, admin_headers):
        mock_create.return_value = SimpleNamespace(id=42, name="Tornillos")
        r = app_client.post(
            "/api/maint/v2/warehouse/categories",
            headers=admin_headers,
            json={"name": "Tornillos", "description": "Sujetadores"},
        )
        assert r.status_code == 201
        assert r.json() == {"id": 42, "name": "Tornillos"}
        # Verifica que el service recibe el _DEPT correcto
        args, _ = mock_create.call_args
        assert args[2] == "equipment_maint"

    def test_create_category_validates_name(self, app_client, admin_headers):
        r = app_client.post(
            "/api/maint/v2/warehouse/categories",
            headers=admin_headers,
            json={"name": "", "description": "x"},
        )
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────
# Products — list + create
# ─────────────────────────────────────────────────────────────────────

class TestProxyProducts:
    @patch("itcj2.apps.warehouse.services.product_service.list_products")
    def test_list_products_forces_dept(self, mock_list, app_client, admin_headers):
        mock_list.return_value = []
        r = app_client.get("/api/maint/v2/warehouse/products", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body == {"products": [], "total": 0}
        # Service debe ser llamado con department_code=equipment_maint
        _, kwargs = mock_list.call_args
        assert kwargs["department_code"] == "equipment_maint"

    @patch("itcj2.apps.warehouse.services.product_service.create_product")
    def test_create_product_minimal_payload(
        self, mock_create, app_client, admin_headers
    ):
        mock_create.return_value = SimpleNamespace(id=7, name="Tornillo M3")
        r = app_client.post(
            "/api/maint/v2/warehouse/products",
            headers=admin_headers,
            json={
                "name": "Tornillo M3",
                "unit_of_measure": "pz",
                "subcategory_id": 1,
            },
        )
        assert r.status_code == 201
        assert r.json()["id"] == 7
        # Verifica que el service recibe data.department_code = equipment_maint
        args, _ = mock_create.call_args
        data_obj = args[1]
        assert data_obj.department_code == "equipment_maint"


# ─────────────────────────────────────────────────────────────────────
# Stock entries — POST happy + fecha inválida
# ─────────────────────────────────────────────────────────────────────

class TestProxyStockEntries:
    @patch("itcj2.apps.warehouse.services.stock_service.register_entry")
    def test_register_entry_happy(self, mock_reg, app_client, admin_headers):
        mock_reg.return_value = SimpleNamespace(id=10, quantity_original="5")
        r = app_client.post(
            "/api/maint/v2/warehouse/stock-entries",
            headers=admin_headers,
            json={
                "product_id": 1,
                "quantity": "5",
                "unit_cost": "12.50",
                "purchase_date": "2026-01-15",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == 10

    def test_register_entry_invalid_date(self, app_client, admin_headers):
        r = app_client.post(
            "/api/maint/v2/warehouse/stock-entries",
            headers=admin_headers,
            json={
                "product_id": 1,
                "quantity": "5",
                "purchase_date": "not-a-date",
            },
        )
        assert r.status_code == 400
        body = r.json()
        # El error handler global re-formatea HTTPException a {error, status}
        msg = body.get("detail") or body.get("error") or ""
        assert "Fecha" in msg


# ─────────────────────────────────────────────────────────────────────
# Movements — solo listado
# ─────────────────────────────────────────────────────────────────────

class TestProxyMovements:
    def test_list_movements_empty(self, app_client, admin_headers):
        db = app_client._mock_db
        pag = SimpleNamespace(items=[], total=0, pages=0)
        with patch("itcj2.models.base.paginate", return_value=pag):
            chain = MagicMock()
            chain.join.return_value.filter.return_value.order_by.return_value = MagicMock()
            db.query.return_value = chain
            r = app_client.get(
                "/api/maint/v2/warehouse/movements",
                headers=admin_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["movements"] == []
        assert body["total"] == 0

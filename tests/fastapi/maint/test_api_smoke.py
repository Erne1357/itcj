"""
Smoke tests para endpoints maint vía TestClient.

Estrategia:
- Construye la app con create_app() (ignora conftest.app_client roto).
- Override de get_db con MagicMock Session.
- JWT firmado con SECRET_KEY real, role='admin' → require_perms hace bypass.
- Mock de servicios maint que tocan BD (queries complejas).
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


# ─────────────────────────────────────────────────────────────────────
# Fixtures locales (ignoramos tests/conftest.py — está roto)
# ─────────────────────────────────────────────────────────────────────

def _admin_jwt(user_id: int = 1) -> str:
    """JWT con role=admin firmado con SECRET real → require_perms bypass."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": "admin",
        "cn": None,
        "name": "Admin Test",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _no_role_jwt(user_id: int = 999) -> str:
    """JWT sin role admin → require_perms necesita autorización real."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": None,
        "cn": None,
        "name": "Plain User",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@pytest.fixture
def app_client():
    """TestClient con get_db override y app real."""
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


@pytest.fixture
def no_auth_headers():
    return {}


# ─────────────────────────────────────────────────────────────────────
# Health check (sanity)
# ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health(self, app_client):
        r = app_client.get("/health")
        assert r.status_code == 200
        assert r.json()["server"] == "fastapi"


# ─────────────────────────────────────────────────────────────────────
# Auth gates
# ─────────────────────────────────────────────────────────────────────

class TestAuthGates:
    @pytest.mark.parametrize("path", [
        "/api/maint/v2/dashboard",
        "/api/maint/v2/tickets",
        "/api/maint/v2/stats/global",
        "/api/maint/v2/analysis/outliers",
        "/api/maint/v2/reports/tickets",
    ])
    def test_no_auth_returns_401(self, app_client, no_auth_headers, path):
        r = app_client.get(path)
        assert r.status_code == 401, f"{path} → {r.status_code}"

    def test_invalid_token_returns_401(self, app_client):
        r = app_client.get(
            "/api/maint/v2/dashboard",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# Dashboard endpoint
# ─────────────────────────────────────────────────────────────────────

class TestDashboardEndpoint:
    @patch("itcj2.apps.maint.services.dashboard_service.get_dashboard")
    def test_admin_returns_payload(self, mock_get, app_client, admin_headers):
        mock_get.return_value = {
            "by_status": {"PENDING": 1},
            "open_total": 1,
            "overdue": 0,
            "unrated_resolved": 0,
            "by_category": [],
            "by_priority": {"BAJA": 0, "MEDIA": 1, "ALTA": 0, "URGENTE": 0},
            "avg_resolution_minutes_30d": None,
            "top_technicians_30d": [],
            "recent_activity": [],
            "activity_24h": 0,
            "last_ticket": None,
        }
        r = app_client.get("/api/maint/v2/dashboard", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        # Endpoint envuelve respuesta en {"success": True, "data": {...}}
        data = body.get("data", body)
        assert "by_status" in data
        assert data["open_total"] == 1


# ─────────────────────────────────────────────────────────────────────
# Stats endpoints (smoke)
# ─────────────────────────────────────────────────────────────────────

class TestStatsEndpoints:
    @patch("itcj2.apps.maint.services.stats_service.get_global_stats")
    def test_global(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {"from": "2026-04-08", "to": "2026-05-08"},
            "data": {"total": 0, "by_status": {}, "by_priority": {}, "by_category": []},
        }
        r = app_client.get("/api/maint/v2/stats/global", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.stats_service.get_by_technician")
    def test_by_technician(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": []}
        r = app_client.get("/api/maint/v2/stats/by-technician", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.stats_service.get_by_category")
    def test_by_category(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": []}
        r = app_client.get("/api/maint/v2/stats/by-category", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.stats_service.get_heatmap_by_location")
    def test_heatmap_location(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {}, "group_by": "location",
            "axes": {"x": [], "y": []}, "matrix": [],
        }
        r = app_client.get(
            "/api/maint/v2/stats/heatmap?group_by=location",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["group_by"] == "location"

    @patch("itcj2.apps.maint.services.stats_service.get_heatmap_by_building")
    def test_heatmap_building(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {}, "group_by": "building",
            "axes": {"x": [], "y": []}, "matrix": [],
        }
        r = app_client.get(
            "/api/maint/v2/stats/heatmap?group_by=building",
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["group_by"] == "building"


# ─────────────────────────────────────────────────────────────────────
# Analysis endpoints (smoke)
# ─────────────────────────────────────────────────────────────────────

class TestAnalysisEndpoints:
    @patch("itcj2.apps.maint.services.analysis_service.get_outliers")
    def test_outliers(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {}, "metric": "time_invested",
            "data": {"q1": 0, "q3": 0, "outliers_below": [], "outliers_above": [],
                     "count_below": 0, "count_above": 0},
        }
        r = app_client.get(
            "/api/maint/v2/analysis/outliers?metric=time_invested",
            headers=admin_headers,
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.analysis_service.get_kmeans")
    def test_kmeans(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "k": 3, "data": {"clusters": []}}
        r = app_client.get(
            "/api/maint/v2/analysis/kmeans?k=3",
            headers=admin_headers,
        )
        assert r.status_code == 200

    def test_kmeans_invalid_k(self, app_client, admin_headers):
        # k=0 → 422 validation error o 400 from service
        r = app_client.get(
            "/api/maint/v2/analysis/kmeans?k=0",
            headers=admin_headers,
        )
        assert r.status_code in (400, 422)

    @patch("itcj2.apps.maint.services.analysis_service.get_distribution")
    def test_distribution(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {}, "metric": "time_invested", "bins": 10,
            "data": {"bins": []},
        }
        r = app_client.get(
            "/api/maint/v2/analysis/distribution?metric=time_invested&bins=10",
            headers=admin_headers,
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.analysis_service.get_trends")
    def test_trends(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {
            "range": {}, "granularity": "day",
            "data": {"labels": [], "created": [], "resolved": [],
                     "canceled": [], "avg_resolution_minutes": []},
        }
        r = app_client.get(
            "/api/maint/v2/analysis/trends?granularity=day",
            headers=admin_headers,
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Reports endpoints (smoke)
# ─────────────────────────────────────────────────────────────────────

class TestReportsEndpoints:
    @patch("itcj2.apps.maint.services.reports_service.get_tickets_time_series")
    def test_tickets(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": []}
        r = app_client.get("/api/maint/v2/reports/tickets", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.reports_service.get_technician_report")
    def test_technicians(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": []}
        r = app_client.get("/api/maint/v2/reports/technicians", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.reports_service.get_category_report")
    def test_categories(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": []}
        r = app_client.get("/api/maint/v2/reports/categories", headers=admin_headers)
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.reports_service.get_sla_report")
    def test_sla(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"range": {}, "data": {}}
        r = app_client.get("/api/maint/v2/reports/sla", headers=admin_headers)
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Attachments endpoint validation
# ─────────────────────────────────────────────────────────────────────

class TestAttachmentValidation:
    def test_invalid_attachment_type(self, app_client, admin_headers):
        # Sin ticket real, igual debe rechazar tipo inválido antes de tocar DB
        r = app_client.post(
            "/api/maint/v2/tickets/1/attachments",
            headers=admin_headers,
            files={"file": ("test.jpg", b"fake", "image/jpeg")},
            data={"attachment_type": "bogus"},
        )
        assert r.status_code == 400

    def test_comment_type_requires_comment_id(self, app_client, admin_headers):
        r = app_client.post(
            "/api/maint/v2/tickets/1/attachments",
            headers=admin_headers,
            files={"file": ("test.jpg", b"fake", "image/jpeg")},
            data={"attachment_type": "comment"},
        )
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────
# Admin SLA trigger
# ─────────────────────────────────────────────────────────────────────

class TestAdminSlaCheck:
    @patch("itcj2.apps.maint.services.sla_service.run_overdue_check")
    def test_admin_sla_check(self, mock_svc, app_client, admin_headers):
        mock_svc.return_value = {"checked_at": "now", "found": 0, "notified_total": 0}
        r = app_client.post("/api/maint/v2/admin/sla/check", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        data = body.get("data", body)
        assert data["found"] == 0

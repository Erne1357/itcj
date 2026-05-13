"""
Tests para los endpoints de Dashboard Departamental (maint).

Endpoints cubiertos:
  GET /api/maint/v2/dashboard/me/departments
  GET /api/maint/v2/dashboard/summary
  GET /api/maint/v2/dashboard/full

Estrategia:
- app_client con dependency_override de get_db (MagicMock, sin BD real).
- JWT con exp 24 h para evitar refresh middleware que abre SessionLocal real.
- Servicios mockeados via unittest.mock.patch sobre la ruta del módulo service.
- Permisos mockeados via patch de authz_service.has_any_assignment /
  get_user_permissions_for_app cuando el usuario no es admin global.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401  ← resolución de mappers SQLAlchemy
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# ─────────────────────────────────────────────────────────────────────────────
# Helpers JWT
# ─────────────────────────────────────────────────────────────────────────────

def _jwt(user_id: int = 1, role: str | None = "admin") -> str:
    """Genera un JWT válido con exp a 24 h para evitar el refresh del middleware."""
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "cn": None,
            "name": "Test User",
            "iat": now,
            "exp": now + 24 * 3600,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client():
    """TestClient con get_db sobreescrito por MagicMock."""
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        client._mock_db = mock_db
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    """Headers con JWT de admin global (role='admin')."""
    return {"Cookie": f"itcj_token={_jwt(role='admin')}"}


@pytest.fixture
def summary_perm_headers():
    """Headers con JWT de usuario no-admin con permiso maint.dashboard.api.summary."""
    return {"Cookie": f"itcj_token={_jwt(user_id=42, role=None)}"}


@pytest.fixture
def full_perm_headers():
    """Headers con JWT de usuario no-admin con permiso maint.dashboard.api.full."""
    return {"Cookie": f"itcj_token={_jwt(user_id=43, role=None)}"}


@pytest.fixture
def no_perm_headers():
    """Headers con JWT de usuario no-admin sin ningún permiso maint."""
    return {"Cookie": f"itcj_token={_jwt(user_id=99, role=None)}"}


# Payload estándar de get_summary mockeado
_SUMMARY_PAYLOAD = {
    "kpis": {
        "open_total": 5,
        "unassigned": 2,
        "in_progress": 1,
        "overdue": 0,
        "resolved_this_week": 3,
    },
    "unassigned_tickets": [],
    "recent_open": [],
}

# Payload estándar de get_full mockeado
_FULL_PAYLOAD = {
    "kpis": {
        "open_total": 8,
        "unassigned": 3,
        "in_progress": 2,
        "overdue": 1,
        "resolved_this_week": 4,
        "avg_resolution_hours": 2.5,
        "rated_count": 3,
        "rated_pct": 37.5,
    },
    "by_status": {
        "PENDING": 3,
        "ASSIGNED": 3,
        "IN_PROGRESS": 2,
        "RESOLVED_SUCCESS": 4,
        "RESOLVED_FAILED": 0,
        "CLOSED": 0,
        "CANCELED": 0,
    },
    "by_category": [{"code": "GENERAL", "name": "General", "count": 5}],
    "by_technician": [],
    "sla_breakdown": {"on_time": 4, "overdue_open": 1, "overdue_resolved": 0},
    "recent_open": [],
    "overdue_tickets": [],
}

# Departamento de muestra
_DEPT = [{"id": 10, "code": "MAINT", "name": "Mantenimiento"}]

# Path del módulo service (para patches)
_SVC = "itcj2.apps.maint.services.department_dashboard_service"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de patch para simular permisos de usuario no-admin
# ─────────────────────────────────────────────────────────────────────────────

def _patch_has_assignment(value: bool):
    return patch(
        "itcj2.core.services.authz_service.has_any_assignment",
        return_value=value,
    )


def _patch_user_perms(perms: set):
    return patch(
        "itcj2.core.services.authz_service.get_user_permissions_for_app",
        return_value=perms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestAuthGates — 401 sin cookie en todos los endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthGates:
    @pytest.mark.parametrize("path", [
        "/api/maint/v2/dashboard/me/departments",
        "/api/maint/v2/dashboard/summary",
        "/api/maint/v2/dashboard/full",
    ])
    def test_no_auth_returns_401(self, app_client, path):
        r = app_client.get(path)
        assert r.status_code == 401, f"{path} retornó {r.status_code}, esperado 401"

    @pytest.mark.parametrize("path", [
        "/api/maint/v2/dashboard/me/departments",
        "/api/maint/v2/dashboard/summary",
        "/api/maint/v2/dashboard/full",
    ])
    def test_invalid_token_returns_401(self, app_client, path):
        r = app_client.get(path, headers={"Cookie": "itcj_token=token.invalido"})
        assert r.status_code == 401, f"{path} con token inválido retornó {r.status_code}"

    def test_no_auth_me_departments_returns_401(self, app_client):
        r = app_client.get("/api/maint/v2/dashboard/me/departments")
        assert r.status_code == 401

    def test_no_auth_summary_returns_401(self, app_client):
        r = app_client.get("/api/maint/v2/dashboard/summary")
        assert r.status_code == 401

    def test_no_auth_full_returns_401(self, app_client):
        r = app_client.get("/api/maint/v2/dashboard/full")
        assert r.status_code == 401

    def test_non_admin_without_any_perm_gets_403_on_me_departments(
        self, app_client, no_perm_headers
    ):
        """Usuario con JWT válido pero sin asignación ni permisos maint → 403."""
        with _patch_has_assignment(False):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=no_perm_headers,
            )
        assert r.status_code == 403

    def test_non_admin_without_perm_gets_403_on_summary(
        self, app_client, no_perm_headers
    ):
        with _patch_has_assignment(True), _patch_user_perms(set()):
            r = app_client.get(
                "/api/maint/v2/dashboard/summary",
                headers=no_perm_headers,
            )
        assert r.status_code == 403

    def test_non_admin_without_perm_gets_403_on_full(
        self, app_client, no_perm_headers
    ):
        with _patch_has_assignment(True), _patch_user_perms(set()):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=no_perm_headers,
            )
        assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# TestMyDepartments — GET /api/maint/v2/dashboard/me/departments
# ─────────────────────────────────────────────────────────────────────────────

class TestMyDepartments:
    def test_admin_global_returns_empty_data_with_flag(
        self, app_client, admin_headers
    ):
        """User con scope total (admin O dispatcher en maint) → is_admin_global=True."""
        with patch(
            "itcj2.apps.maint.api.department_dashboard._has_full_scope",
            return_value=True,
        ), patch(
            "itcj2.apps.maint.api.department_dashboard._is_maint_admin",
            return_value=True,
        ), patch(
            f"{_SVC}.get_user_departments", return_value=[]
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=admin_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"] == []
        assert body["is_admin_global"] is True

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    def test_non_admin_with_summary_perm_returns_departments(
        self, mock_get_depts, app_client, summary_perm_headers
    ):
        """Usuario con permiso summary ve sus departamentos activos."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=summary_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["is_admin_global"] is False
        assert len(body["data"]) == 1
        dept = body["data"][0]
        assert dept["id"] == 10
        assert dept["code"] == "MAINT"
        assert dept["name"] == "Mantenimiento"

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    def test_non_admin_with_full_perm_returns_departments(
        self, mock_get_depts, app_client, full_perm_headers
    ):
        """Usuario con permiso full también puede listar sus departamentos."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.full"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=full_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["is_admin_global"] is False
        assert body["data"][0]["id"] == 10

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    def test_non_admin_without_positions_returns_empty_list(
        self, mock_get_depts, app_client, summary_perm_headers
    ):
        """Usuario con permiso pero sin puestos activos → data: [], is_admin_global: false."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=summary_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["is_admin_global"] is False
        assert body["data"] == []

    @patch(f"{_SVC}.get_user_departments", side_effect=Exception("DB error"))
    def test_service_exception_returns_500(
        self, mock_get_depts, app_client, summary_perm_headers
    ):
        """Si el service lanza excepción inesperada → 500."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/me/departments",
                headers=summary_perm_headers,
            )
        assert r.status_code == 500


# ─────────────────────────────────────────────────────────────────────────────
# TestSummary — GET /api/maint/v2/dashboard/summary
# ─────────────────────────────────────────────────────────────────────────────

class TestSummary:
    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_summary", return_value=_SUMMARY_PAYLOAD)
    def test_admin_gets_summary_without_dept_filter(
        self, mock_summary, mock_depts, app_client, admin_headers
    ):
        """Admin global obtiene summary; departments = [] (acceso total)."""
        r = app_client.get(
            "/api/maint/v2/dashboard/summary",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "data" in body
        assert "departments" in body
        assert body["departments"] == []

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_summary", return_value=_SUMMARY_PAYLOAD)
    def test_admin_with_dept_filter_gets_200(
        self, mock_summary, mock_depts, app_client, admin_headers
    ):
        """Admin global puede filtrar por cualquier dept_id."""
        r = app_client.get(
            "/api/maint/v2/dashboard/summary?dept=10",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        # Verifica que get_summary fue llamado con dept_filter=10
        mock_summary.assert_called_once()
        call_kwargs = mock_summary.call_args.kwargs
        assert call_kwargs["dept_filter"] == 10

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(f"{_SVC}.get_summary", return_value=_SUMMARY_PAYLOAD)
    def test_non_admin_with_summary_perm_gets_200(
        self, mock_summary, mock_depts, app_client, summary_perm_headers
    ):
        """Usuario con permiso summary accede a su propio dept."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/summary",
                headers=summary_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        # Verifica shape de KPIs
        kpis = body["data"]["kpis"]
        assert "open_total" in kpis
        assert "unassigned" in kpis
        assert "in_progress" in kpis
        assert "overdue" in kpis
        assert "resolved_this_week" in kpis
        # Verifica listas
        assert "unassigned_tickets" in body["data"]
        assert "recent_open" in body["data"]
        # Verifica departments devueltos
        assert len(body["departments"]) == 1

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(f"{_SVC}.get_summary", return_value=_SUMMARY_PAYLOAD)
    def test_non_admin_with_full_perm_can_access_summary(
        self, mock_summary, mock_depts, app_client, full_perm_headers
    ):
        """Usuario con permiso full también puede acceder al endpoint summary."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.full"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/summary",
                headers=full_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(
        f"{_SVC}.get_summary",
        side_effect=ValueError("El departamento 999 no pertenece a tus puestos activos."),
    )
    def test_summary_dept_not_owned_by_user_returns_403(
        self, mock_summary, mock_depts, app_client, summary_perm_headers
    ):
        """Filtrar por un dept ajeno al usuario → 403 (ValueError en service).
        El handler global serializa HTTPException como {"error": ..., "status": 403}.
        """
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/summary?dept=999",
                headers=summary_perm_headers,
            )
        assert r.status_code == 403
        body = r.json()
        # El handler global puede usar "detail" o "error" según la excepción
        msg = body.get("detail") or body.get("error", "")
        assert "999" in msg

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(
        f"{_SVC}.get_summary",
        side_effect=Exception("conexión perdida"),
    )
    def test_summary_unexpected_error_returns_500(
        self, mock_summary, mock_depts, app_client, summary_perm_headers
    ):
        """Excepción inesperada en service → 500."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/summary",
                headers=summary_perm_headers,
            )
        assert r.status_code == 500

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_summary", return_value=_SUMMARY_PAYLOAD)
    def test_summary_kpi_values_match_mock(
        self, mock_summary, mock_depts, app_client, admin_headers
    ):
        """Verifica que los valores del mock se propagan correctamente al response."""
        r = app_client.get(
            "/api/maint/v2/dashboard/summary",
            headers=admin_headers,
        )
        assert r.status_code == 200
        kpis = r.json()["data"]["kpis"]
        assert kpis["open_total"] == 5
        assert kpis["unassigned"] == 2
        assert kpis["in_progress"] == 1
        assert kpis["overdue"] == 0
        assert kpis["resolved_this_week"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# TestFull — GET /api/maint/v2/dashboard/full
# ─────────────────────────────────────────────────────────────────────────────

class TestFull:
    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_admin_gets_full_dashboard(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Admin global obtiene el dashboard completo."""
        r = app_client.get(
            "/api/maint/v2/dashboard/full",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "data" in body
        assert "departments" in body
        assert body["departments"] == []

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_admin_with_dept_filter_passes_dept_to_service(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """El parámetro dept se pasa correctamente al service."""
        r = app_client.get(
            "/api/maint/v2/dashboard/full?dept=10",
            headers=admin_headers,
        )
        assert r.status_code == 200
        mock_full.assert_called_once()
        call_kwargs = mock_full.call_args.kwargs
        assert call_kwargs["dept_filter"] == 10

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_full_response_shape_contains_all_sections(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Admin maint ve TODAS las secciones (incluyendo by_technician)."""
        with patch(
            "itcj2.apps.maint.api.department_dashboard._is_maint_admin",
            return_value=True,
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=admin_headers,
            )
        assert r.status_code == 200
        data = r.json()["data"]
        # KPIs extendidos
        kpis = data["kpis"]
        assert "open_total" in kpis
        assert "unassigned" in kpis
        assert "in_progress" in kpis
        assert "overdue" in kpis
        assert "resolved_this_week" in kpis
        assert "avg_resolution_hours" in kpis
        assert "rated_count" in kpis
        assert "rated_pct" in kpis
        # Secciones extras del full
        assert "by_status" in data
        assert "by_category" in data
        assert "by_technician" in data  # solo si user es admin en maint
        assert "sla_breakdown" in data
        assert "recent_open" in data
        assert "overdue_tickets" in data

    @patch(f"{_SVC}.get_user_departments", return_value=[{"id": 24, "code": "x", "name": "X"}])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_dh_full_omits_by_technician(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Department_head (no admin en maint) NO ve by_technician."""
        with patch(
            "itcj2.apps.maint.api.department_dashboard._is_maint_admin",
            return_value=False,
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=admin_headers,
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "by_technician" not in data
        # El resto sí sigue
        assert "by_status" in data
        assert "by_category" in data
        assert "sla_breakdown" in data

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_full_kpi_values_match_mock(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Verifica que los valores del mock se propagan correctamente."""
        r = app_client.get(
            "/api/maint/v2/dashboard/full",
            headers=admin_headers,
        )
        kpis = r.json()["data"]["kpis"]
        assert kpis["open_total"] == 8
        assert kpis["avg_resolution_hours"] == 2.5
        assert kpis["rated_pct"] == 37.5

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_non_admin_with_full_perm_gets_200(
        self, mock_full, mock_depts, app_client, full_perm_headers
    ):
        """Usuario con permiso full puede ver el dashboard completo."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.full"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=full_perm_headers,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert len(body["departments"]) == 1

    def test_non_admin_with_only_summary_perm_gets_403_on_full(
        self, app_client, summary_perm_headers
    ):
        """Usuario que solo tiene permiso summary NO puede ver el dashboard full."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.summary"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=summary_perm_headers,
            )
        assert r.status_code == 403

    def test_non_admin_without_any_perm_gets_403_on_full(
        self, app_client, no_perm_headers
    ):
        """Usuario sin ningún permiso maint → 403 en /full."""
        with _patch_has_assignment(False):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=no_perm_headers,
            )
        assert r.status_code == 403

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(
        f"{_SVC}.get_full",
        side_effect=ValueError("El departamento 888 no pertenece a tus puestos activos."),
    )
    def test_full_dept_not_owned_by_user_returns_403(
        self, mock_full, mock_depts, app_client, full_perm_headers
    ):
        """Filtrar por dept ajeno → 403 (ValueError en service).
        El handler global serializa HTTPException como {"error": ..., "status": 403}.
        """
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.full"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full?dept=888",
                headers=full_perm_headers,
            )
        assert r.status_code == 403
        body = r.json()
        msg = body.get("detail") or body.get("error", "")
        assert "888" in msg

    @patch(f"{_SVC}.get_user_departments", return_value=_DEPT)
    @patch(
        f"{_SVC}.get_full",
        side_effect=Exception("timeout en BD"),
    )
    def test_full_unexpected_error_returns_500(
        self, mock_full, mock_depts, app_client, full_perm_headers
    ):
        """Excepción inesperada en service → 500."""
        with _patch_has_assignment(True), _patch_user_perms(
            {"maint.dashboard.api.full"}
        ):
            r = app_client.get(
                "/api/maint/v2/dashboard/full",
                headers=full_perm_headers,
            )
        assert r.status_code == 500

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_full_sla_breakdown_shape(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Verifica estructura del sla_breakdown en la respuesta."""
        r = app_client.get(
            "/api/maint/v2/dashboard/full",
            headers=admin_headers,
        )
        sla = r.json()["data"]["sla_breakdown"]
        assert "on_time" in sla
        assert "overdue_open" in sla
        assert "overdue_resolved" in sla
        assert sla["on_time"] == 4
        assert sla["overdue_open"] == 1

    @patch(f"{_SVC}.get_user_departments", return_value=[])
    @patch(f"{_SVC}.get_full", return_value=_FULL_PAYLOAD)
    def test_full_by_status_contains_all_statuses(
        self, mock_full, mock_depts, app_client, admin_headers
    ):
        """Verifica que by_status contiene los 7 estados posibles."""
        r = app_client.get(
            "/api/maint/v2/dashboard/full",
            headers=admin_headers,
        )
        by_status = r.json()["data"]["by_status"]
        expected_statuses = {
            "PENDING", "ASSIGNED", "IN_PROGRESS",
            "RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED",
        }
        assert set(by_status.keys()) == expected_statuses

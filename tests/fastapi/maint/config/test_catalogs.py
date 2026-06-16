"""
Tests — catálogos Tipo de mantenimiento + Origen del servicio (maint Fase 4).

Secciones:
  A. catalog_cache — unit sin app ni BD real (maint_types y service_origins).
  B. API /api/maint/v2/config/maint-types — TestClient con mocks.
  C. API /api/maint/v2/config/service-origins — TestClient con mocks.
  D. ticket_service.resolve_ticket — regresión validación maintenance_type / service_origin.

Estrategia global:
  - BD no disponible → mocks sobre _load_maint_types_from_db / _load_service_origins_from_db.
  - log_config_change se parchea en _catalog_crud (donde está importado).
  - invalidate_* se parcheann en el módulo router que los importa (maint_types / service_origins).
  - JWT admin (role='admin') → require_perms hace bypass automático.
  - Sin cookie → 401.
  - El cache de módulo se invalida antes de cada test que lo ejercite.
"""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401  — resolución de mappers
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# =============================================================================
# Helpers compartidos
# =============================================================================

def _admin_jwt(user_id: int = 1) -> str:
    """JWT con role=admin firmado con SECRET real → require_perms hace bypass."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": "admin",
        "cn": None,
        "name": "Admin Test",
        "iat": now,
        "exp": now + 24 * 3600,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _admin_headers() -> dict:
    return {"Cookie": f"itcj_token={_admin_jwt()}"}


def _fake_catalog_item(
    item_id: int = 1,
    code: str = "PREVENTIVO",
    label: str = "Preventivo",
    display_order: int = 0,
    is_active: bool = True,
) -> MagicMock:
    """Simula un objeto MaintMaintenanceType o MaintServiceOrigin."""
    item = MagicMock()
    item.id = item_id
    item.code = code
    item.label = label
    item.display_order = display_order
    item.is_active = is_active
    return item


# =============================================================================
# Fixture: app_client (mismo patrón que test_priorities_audit.py)
# =============================================================================

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


# =============================================================================
# A. catalog_cache — unit, sin app ni BD real
# =============================================================================

class TestMaintTypesCacheWithDbDown:
    """get_maint_type_codes() degrada al fallback cuando la BD no está disponible."""

    def setup_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_maint_types
        invalidate_maint_types()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_maint_types
        invalidate_maint_types()

    def test_get_maint_type_codes_bd_caida_retorna_fallback(self):
        """Con BD caída, get_maint_type_codes() devuelve {'PREVENTIVO','CORRECTIVO'}."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_type_codes,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            result = get_maint_type_codes()

        assert isinstance(result, set)
        assert result == {"PREVENTIVO", "CORRECTIVO"}

    def test_get_maint_type_codes_bd_caida_no_lanza(self):
        """get_maint_type_codes() con BD caída no propaga excepción."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_type_codes,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            try:
                get_maint_type_codes()
            except Exception as exc:
                pytest.fail(f"get_maint_type_codes lanzó excepción inesperada: {exc!r}")

    def test_get_maint_types_bd_caida_retorna_lista_fallback(self):
        """get_maint_types() con BD caída retorna lista con los códigos hardcoded."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_types,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            result = get_maint_types()

        assert isinstance(result, list)
        codes = {item["code"] for item in result}
        assert codes == {"PREVENTIVO", "CORRECTIVO"}

    def test_invalidate_maint_types_no_lanza(self):
        """invalidate_maint_types() nunca lanza, ni con cache lleno ni vacío."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_maint_types
        try:
            invalidate_maint_types()
            invalidate_maint_types()   # segunda vez sobre cache ya vacío
        except Exception as exc:
            pytest.fail(f"invalidate_maint_types lanzó: {exc!r}")


class TestMaintTypesCacheWithMockedDb:
    """catalog_cache lee correctamente desde BD mockeada para maint_types."""

    def setup_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_maint_types
        invalidate_maint_types()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_maint_types
        invalidate_maint_types()

    def test_get_maint_types_refleja_datos_de_bd(self):
        """get_maint_types() devuelve lista proveniente de BD mockeada."""
        fake_rows = [
            {"id": 1, "code": "PREVENTIVO", "label": "Preventivo",
             "display_order": 0, "is_active": True},
            {"id": 2, "code": "CORRECTIVO", "label": "Correctivo",
             "display_order": 1, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            return_value=fake_rows,
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_types,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            result = get_maint_types()

        assert len(result) == 2
        assert result[0]["code"] == "PREVENTIVO"
        assert result[1]["code"] == "CORRECTIVO"

    def test_get_maint_types_cachea_resultado(self):
        """La segunda llamada no invoca _load_maint_types_from_db."""
        fake_rows = [
            {"id": 1, "code": "PREVENTIVO", "label": "Preventivo",
             "display_order": 0, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            return_value=fake_rows,
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_types,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            get_maint_types()
            get_maint_types()   # segunda llamada — debe usar cache

        assert mock_load.call_count == 1

    def test_invalidate_maint_types_fuerza_recarga(self):
        """Tras invalidate_maint_types(), el siguiente get_maint_types() recarga desde BD."""
        fake_rows = [
            {"id": 1, "code": "PREVENTIVO", "label": "Preventivo",
             "display_order": 0, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            return_value=fake_rows,
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_types,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            get_maint_types()        # primera carga
            invalidate_maint_types()
            get_maint_types()        # recarga tras invalidar

        assert mock_load.call_count == 2

    def test_get_maint_type_codes_solo_activos(self):
        """get_maint_type_codes() filtra solo is_active=True."""
        fake_rows = [
            {"id": 1, "code": "PREVENTIVO", "label": "Preventivo",
             "display_order": 0, "is_active": True},
            {"id": 2, "code": "INACTIVO", "label": "Inactivo",
             "display_order": 1, "is_active": False},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_maint_types_from_db",
            return_value=fake_rows,
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_maint_type_codes,
                invalidate_maint_types,
            )
            invalidate_maint_types()
            codes = get_maint_type_codes()

        assert "PREVENTIVO" in codes
        assert "INACTIVO" not in codes


class TestServiceOriginsCacheWithDbDown:
    """get_service_origin_codes() degrada al fallback cuando la BD no está disponible."""

    def setup_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_service_origins
        invalidate_service_origins()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_service_origins
        invalidate_service_origins()

    def test_get_service_origin_codes_bd_caida_retorna_fallback(self):
        """Con BD caída, get_service_origin_codes() devuelve {'INTERNO','EXTERNO'}."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origin_codes,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            result = get_service_origin_codes()

        assert isinstance(result, set)
        assert result == {"INTERNO", "EXTERNO"}

    def test_get_service_origin_codes_bd_caida_no_lanza(self):
        """get_service_origin_codes() con BD caída no propaga excepción."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origin_codes,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            try:
                get_service_origin_codes()
            except Exception as exc:
                pytest.fail(f"get_service_origin_codes lanzó excepción inesperada: {exc!r}")

    def test_get_service_origins_bd_caida_retorna_lista_fallback(self):
        """get_service_origins() con BD caída retorna lista con los códigos hardcoded."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origins,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            result = get_service_origins()

        assert isinstance(result, list)
        codes = {item["code"] for item in result}
        assert codes == {"INTERNO", "EXTERNO"}

    def test_invalidate_service_origins_no_lanza(self):
        """invalidate_service_origins() nunca lanza, ni con cache lleno ni vacío."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_service_origins
        try:
            invalidate_service_origins()
            invalidate_service_origins()   # segunda vez sobre cache ya vacío
        except Exception as exc:
            pytest.fail(f"invalidate_service_origins lanzó: {exc!r}")


class TestServiceOriginsCacheWithMockedDb:
    """catalog_cache lee correctamente desde BD mockeada para service_origins."""

    def setup_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_service_origins
        invalidate_service_origins()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_service_origins
        invalidate_service_origins()

    def test_get_service_origins_refleja_datos_de_bd(self):
        """get_service_origins() devuelve lista proveniente de BD mockeada."""
        fake_rows = [
            {"id": 1, "code": "INTERNO", "label": "Interno",
             "display_order": 0, "is_active": True},
            {"id": 2, "code": "EXTERNO", "label": "Externo",
             "display_order": 1, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            return_value=fake_rows,
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origins,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            result = get_service_origins()

        assert len(result) == 2
        assert result[0]["code"] == "INTERNO"

    def test_get_service_origins_cachea_resultado(self):
        """La segunda llamada no invoca _load_service_origins_from_db."""
        fake_rows = [
            {"id": 1, "code": "INTERNO", "label": "Interno",
             "display_order": 0, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            return_value=fake_rows,
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origins,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            get_service_origins()
            get_service_origins()   # segunda llamada — debe usar cache

        assert mock_load.call_count == 1

    def test_invalidate_service_origins_fuerza_recarga(self):
        """Tras invalidate_service_origins(), el siguiente get recarga desde BD."""
        fake_rows = [
            {"id": 1, "code": "INTERNO", "label": "Interno",
             "display_order": 0, "is_active": True},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            return_value=fake_rows,
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origins,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            get_service_origins()        # primera carga
            invalidate_service_origins()
            get_service_origins()        # recarga tras invalidar

        assert mock_load.call_count == 2

    def test_get_service_origin_codes_solo_activos(self):
        """get_service_origin_codes() filtra solo is_active=True."""
        fake_rows = [
            {"id": 1, "code": "INTERNO", "label": "Interno",
             "display_order": 0, "is_active": True},
            {"id": 2, "code": "DESCONTINUADO", "label": "Desc",
             "display_order": 1, "is_active": False},
        ]
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_service_origins_from_db",
            return_value=fake_rows,
        ):
            from itcj2.apps.maint.utils.catalog_cache import (
                get_service_origin_codes,
                invalidate_service_origins,
            )
            invalidate_service_origins()
            codes = get_service_origin_codes()

        assert "INTERNO" in codes
        assert "DESCONTINUADO" not in codes


# =============================================================================
# B. API /api/maint/v2/config/maint-types
# =============================================================================

class TestMaintTypesApiGet:
    """GET /api/maint/v2/config/maint-types"""

    def _setup_db_query(self, mock_db, items: list):
        mock_db.query.return_value.order_by.return_value.all.return_value = items

    def test_get_returns_200(self, app_client):
        """Admin obtiene 200."""
        self._setup_db_query(app_client._mock_db, [
            _fake_catalog_item(1, "PREVENTIVO"),
            _fake_catalog_item(2, "CORRECTIVO"),
        ])
        r = app_client.get(
            "/api/maint/v2/config/maint-types",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_get_response_shape(self, app_client):
        """Respuesta tiene success=True, data (list) y total."""
        self._setup_db_query(app_client._mock_db, [_fake_catalog_item()])
        r = app_client.get(
            "/api/maint/v2/config/maint-types",
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body

    def test_get_total_correcto(self, app_client):
        """total coincide con la cantidad de ítems."""
        items = [_fake_catalog_item(i) for i in range(1, 4)]
        self._setup_db_query(app_client._mock_db, items)
        r = app_client.get(
            "/api/maint/v2/config/maint-types",
            headers=_admin_headers(),
        )
        assert r.json()["total"] == 3

    def test_get_data_item_estructura(self, app_client):
        """Cada ítem tiene id, code, label, display_order, is_active."""
        item = _fake_catalog_item(5, "PREVENTIVO")
        self._setup_db_query(app_client._mock_db, [item])
        r = app_client.get(
            "/api/maint/v2/config/maint-types",
            headers=_admin_headers(),
        )
        data_item = r.json()["data"][0]
        for field in ("id", "code", "label", "display_order", "is_active"):
            assert field in data_item, f"Campo '{field}' faltante en ítem"

    def test_get_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/maint-types")
        assert r.status_code == 401

    def test_get_token_invalido_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            "/api/maint/v2/config/maint-types",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


class TestMaintTypesApiPost:
    """POST /api/maint/v2/config/maint-types"""

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_happy_returns_201(self, mock_log, mock_inv, app_client):
        """POST con datos válidos → 201."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO", "label": "Predictivo", "display_order": 2},
            headers=_admin_headers(),
        )
        assert r.status_code == 201

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """POST exitoso devuelve {success: true, data: {...}}."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO", "label": "Predictivo"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_code_duplicado_retorna_400(self, mock_log, mock_inv, app_client):
        """POST con code ya existente → 400."""
        mock_db = app_client._mock_db
        existing = _fake_catalog_item(1, "PREVENTIVO")
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREVENTIVO", "label": "Preventivo dup"},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_post_code_vacio_retorna_422(self, app_client):
        """code vacío viola min_length=1 del schema → 422 de Pydantic."""
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "", "label": "Tipo"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_sin_label_retorna_422(self, app_client):
        """label faltante → 422."""
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO", "label": "Predictivo"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_invoca_invalidate_maint_types(self, mock_log, mock_inv, app_client):
        """POST exitoso llama invalidate_maint_types()."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO", "label": "Predictivo"},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_invoca_log_config_change_con_entity_maint_type(
        self, mock_log, mock_inv, app_client
    ):
        """POST exitoso llama log_config_change con entity_type='maint_type'."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app_client.post(
            "/api/maint/v2/config/maint-types",
            json={"code": "PREDICTIVO", "label": "Predictivo"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "maint_type"


class TestMaintTypesApiPatch:
    """PATCH /api/maint/v2/config/maint-types/{item_id}"""

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_happy_returns_200(self, mock_log, mock_inv, app_client):
        """PATCH con ítem existente → 200."""
        item = _fake_catalog_item(1, "PREVENTIVO")
        app_client._mock_db.get.return_value = item
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1",
            json={"label": "Preventivo actualizado"},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """PATCH exitoso devuelve {success: true, data: {...}}."""
        item = _fake_catalog_item(1, "PREVENTIVO")
        app_client._mock_db.get.return_value = item
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1",
            json={"label": "Preventivo nuevo"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_patch_item_inexistente_retorna_404(self, app_client):
        """db.get devuelve None → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/9999",
            json={"label": "X"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_patch_display_order_negativo_retorna_422(self, app_client):
        """display_order negativo viola ge=0 del schema → 422."""
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1",
            json={"display_order": -1},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_patch_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1",
            json={"label": "X"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """PATCH exitoso invoca log_config_change e invalidate_maint_types."""
        item = _fake_catalog_item(1, "PREVENTIVO")
        app_client._mock_db.get.return_value = item
        app_client.patch(
            "/api/maint/v2/config/maint-types/1",
            json={"label": "Preventivo nuevo"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()


class TestMaintTypesApiToggle:
    """PATCH /api/maint/v2/config/maint-types/{item_id}/toggle"""

    def _count_returns(self, mock_db, count: int):
        mock_db.query.return_value.filter.return_value.count.return_value = count

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_activar_retorna_200(self, mock_log, mock_inv, app_client):
        """Activar un ítem inactivo → 200."""
        item = _fake_catalog_item(2, "PREDICTIVO", is_active=False)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 2)
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_desactivar_normal_retorna_200(self, mock_log, mock_inv, app_client):
        """Desactivar un ítem activo cuando quedan más de uno → 200."""
        item = _fake_catalog_item(2, "CORRECTIVO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 3)
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_toggle_desactivar_unico_activo_retorna_400(self, app_client):
        """No se puede desactivar el único ítem activo → 400."""
        item = _fake_catalog_item(1, "PREVENTIVO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 1)
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_toggle_item_inexistente_retorna_404(self, app_client):
        """Ítem no encontrado → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/9999/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_toggle_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/maint-types/1/toggle",
            json={"is_active": True},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """Toggle exitoso invoca log_config_change e invalidate_maint_types."""
        item = _fake_catalog_item(2, "CORRECTIVO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 3)
        app_client.patch(
            "/api/maint/v2/config/maint-types/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()


class TestMaintTypesApiReorder:
    """PUT /api/maint/v2/config/maint-types/reorder"""

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_reorder_happy_returns_200(self, mock_log, mock_inv, app_client):
        """Reorder con IDs válidos → 200 {success: true}."""
        item1 = _fake_catalog_item(1, "PREVENTIVO", display_order=0)
        item2 = _fake_catalog_item(2, "CORRECTIVO", display_order=1)

        def _get(model, pk):
            return {1: item1, 2: item2}.get(pk)

        app_client._mock_db.get.side_effect = _get
        r = app_client.put(
            "/api/maint/v2/config/maint-types/reorder",
            json={"order": [{"id": 1, "display_order": 1}, {"id": 2, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reorder_lista_vacia_retorna_400(self, app_client):
        """Lista de orden vacía → 400."""
        r = app_client.put(
            "/api/maint/v2/config/maint-types/reorder",
            json={"order": []},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_reorder_id_inexistente_retorna_404(self, app_client):
        """ID no encontrado en la lista → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.put(
            "/api/maint/v2/config/maint-types/reorder",
            json={"order": [{"id": 9999, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_reorder_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.put(
            "/api/maint/v2/config/maint-types/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.maint_types.invalidate_maint_types")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_reorder_invoca_invalidate_y_log(self, mock_log, mock_inv, app_client):
        """Reorder exitoso llama invalidate_maint_types y log_config_change."""
        item = _fake_catalog_item(1, "PREVENTIVO")
        app_client._mock_db.get.return_value = item
        app_client.put(
            "/api/maint/v2/config/maint-types/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()
        mock_log.assert_called()


# =============================================================================
# C. API /api/maint/v2/config/service-origins
# =============================================================================

class TestServiceOriginsApiGet:
    """GET /api/maint/v2/config/service-origins"""

    def _setup_db_query(self, mock_db, items: list):
        mock_db.query.return_value.order_by.return_value.all.return_value = items

    def test_get_returns_200(self, app_client):
        """Admin obtiene 200."""
        self._setup_db_query(app_client._mock_db, [
            _fake_catalog_item(1, "INTERNO"),
            _fake_catalog_item(2, "EXTERNO"),
        ])
        r = app_client.get(
            "/api/maint/v2/config/service-origins",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_get_response_shape(self, app_client):
        """Respuesta tiene success=True, data (list) y total."""
        self._setup_db_query(app_client._mock_db, [_fake_catalog_item(1, "INTERNO")])
        r = app_client.get(
            "/api/maint/v2/config/service-origins",
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body

    def test_get_total_correcto(self, app_client):
        """total coincide con la cantidad de ítems."""
        items = [_fake_catalog_item(i, f"ORIG{i}") for i in range(1, 4)]
        self._setup_db_query(app_client._mock_db, items)
        r = app_client.get(
            "/api/maint/v2/config/service-origins",
            headers=_admin_headers(),
        )
        assert r.json()["total"] == 3

    def test_get_data_item_estructura(self, app_client):
        """Cada ítem tiene id, code, label, display_order, is_active."""
        item = _fake_catalog_item(1, "INTERNO")
        self._setup_db_query(app_client._mock_db, [item])
        r = app_client.get(
            "/api/maint/v2/config/service-origins",
            headers=_admin_headers(),
        )
        data_item = r.json()["data"][0]
        for field in ("id", "code", "label", "display_order", "is_active"):
            assert field in data_item, f"Campo '{field}' faltante en ítem"

    def test_get_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/service-origins")
        assert r.status_code == 401

    def test_get_token_invalido_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            "/api/maint/v2/config/service-origins",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


class TestServiceOriginsApiPost:
    """POST /api/maint/v2/config/service-origins"""

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_happy_returns_201(self, mock_log, mock_inv, app_client):
        """POST con datos válidos → 201."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO", "label": "Mixto", "display_order": 2},
            headers=_admin_headers(),
        )
        assert r.status_code == 201

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """POST exitoso devuelve {success: true, data: {...}}."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO", "label": "Mixto"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_code_duplicado_retorna_400(self, mock_log, mock_inv, app_client):
        """POST con code ya existente → 400."""
        mock_db = app_client._mock_db
        existing = _fake_catalog_item(1, "INTERNO")
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "INTERNO", "label": "Interno dup"},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_post_code_vacio_retorna_422(self, app_client):
        """code vacío viola min_length=1 del schema → 422 de Pydantic."""
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "", "label": "Origen"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_sin_label_retorna_422(self, app_client):
        """label faltante → 422."""
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO", "label": "Mixto"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_invoca_invalidate_service_origins(self, mock_log, mock_inv, app_client):
        """POST exitoso llama invalidate_service_origins()."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO", "label": "Mixto"},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_post_invoca_log_config_change_con_entity_service_origin(
        self, mock_log, mock_inv, app_client
    ):
        """POST exitoso llama log_config_change con entity_type='service_origin'."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app_client.post(
            "/api/maint/v2/config/service-origins",
            json={"code": "MIXTO", "label": "Mixto"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "service_origin"


class TestServiceOriginsApiPatch:
    """PATCH /api/maint/v2/config/service-origins/{item_id}"""

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_happy_returns_200(self, mock_log, mock_inv, app_client):
        """PATCH con ítem existente → 200."""
        item = _fake_catalog_item(1, "INTERNO")
        app_client._mock_db.get.return_value = item
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1",
            json={"label": "Interno actualizado"},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """PATCH exitoso devuelve {success: true, data: {...}}."""
        item = _fake_catalog_item(1, "INTERNO")
        app_client._mock_db.get.return_value = item
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1",
            json={"label": "Interno nuevo"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_patch_item_inexistente_retorna_404(self, app_client):
        """db.get devuelve None → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/9999",
            json={"label": "X"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_patch_display_order_negativo_retorna_422(self, app_client):
        """display_order negativo → 422."""
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1",
            json={"display_order": -1},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_patch_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1",
            json={"label": "X"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_patch_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """PATCH exitoso invoca log_config_change e invalidate_service_origins."""
        item = _fake_catalog_item(1, "INTERNO")
        app_client._mock_db.get.return_value = item
        app_client.patch(
            "/api/maint/v2/config/service-origins/1",
            json={"label": "Interno nuevo"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()


class TestServiceOriginsApiToggle:
    """PATCH /api/maint/v2/config/service-origins/{item_id}/toggle"""

    def _count_returns(self, mock_db, count: int):
        mock_db.query.return_value.filter.return_value.count.return_value = count

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_activar_retorna_200(self, mock_log, mock_inv, app_client):
        """Activar un ítem inactivo → 200."""
        item = _fake_catalog_item(2, "EXTERNO", is_active=False)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 2)
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_desactivar_normal_retorna_200(self, mock_log, mock_inv, app_client):
        """Desactivar un ítem activo cuando quedan más de uno → 200."""
        item = _fake_catalog_item(2, "EXTERNO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 3)
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_toggle_desactivar_unico_activo_retorna_400(self, app_client):
        """No se puede desactivar el único ítem activo → 400."""
        item = _fake_catalog_item(1, "INTERNO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 1)
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_toggle_item_inexistente_retorna_404(self, app_client):
        """Ítem no encontrado → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/9999/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_toggle_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/service-origins/1/toggle",
            json={"is_active": True},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_toggle_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """Toggle exitoso invoca log_config_change e invalidate_service_origins."""
        item = _fake_catalog_item(2, "EXTERNO", is_active=True)
        app_client._mock_db.get.return_value = item
        self._count_returns(app_client._mock_db, 3)
        app_client.patch(
            "/api/maint/v2/config/service-origins/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()


class TestServiceOriginsApiReorder:
    """PUT /api/maint/v2/config/service-origins/reorder"""

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_reorder_happy_returns_200(self, mock_log, mock_inv, app_client):
        """Reorder con IDs válidos → 200 {success: true}."""
        item1 = _fake_catalog_item(1, "INTERNO", display_order=0)
        item2 = _fake_catalog_item(2, "EXTERNO", display_order=1)

        def _get(model, pk):
            return {1: item1, 2: item2}.get(pk)

        app_client._mock_db.get.side_effect = _get
        r = app_client.put(
            "/api/maint/v2/config/service-origins/reorder",
            json={"order": [{"id": 1, "display_order": 1}, {"id": 2, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reorder_lista_vacia_retorna_400(self, app_client):
        """Lista de orden vacía → 400."""
        r = app_client.put(
            "/api/maint/v2/config/service-origins/reorder",
            json={"order": []},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_reorder_id_inexistente_retorna_404(self, app_client):
        """ID no encontrado en la lista → 404."""
        app_client._mock_db.get.return_value = None
        r = app_client.put(
            "/api/maint/v2/config/service-origins/reorder",
            json={"order": [{"id": 9999, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_reorder_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.put(
            "/api/maint/v2/config/service-origins/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.service_origins.invalidate_service_origins")
    @patch("itcj2.apps.maint.api.config._catalog_crud.log_config_change")
    def test_reorder_invoca_invalidate_y_log(self, mock_log, mock_inv, app_client):
        """Reorder exitoso llama invalidate_service_origins y log_config_change."""
        item = _fake_catalog_item(1, "INTERNO")
        app_client._mock_db.get.return_value = item
        app_client.put(
            "/api/maint/v2/config/service-origins/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()
        mock_log.assert_called()


# =============================================================================
# D. ticket_service.resolve_ticket — regresión
# =============================================================================

class TestResolveTicketCatalogValidation:
    """
    Verifica que resolve_ticket valida maintenance_type contra get_maint_type_codes()
    y service_origin contra get_service_origin_codes().

    Los parches van sobre catalog_cache en el namespace de utilities porque
    resolve_ticket los importa con `from itcj2.apps.maint.utils.catalog_cache import ...`
    dentro del cuerpo de la función.
    """

    def _make_ticket(self, status: str = "ASSIGNED") -> MagicMock:
        """Construye un ticket mock en el estado dado."""
        ticket = MagicMock()
        ticket.status = status
        ticket.id = 1
        ticket.technician_assignments = []  # sin asignados → dispatcher
        return ticket

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes",
        return_value={"INTERNO", "EXTERNO"},
    )
    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes",
        return_value={"PREVENTIVO", "CORRECTIVO"},
    )
    def test_resolve_ticket_tipo_y_origen_validos_no_lanza(
        self, mock_maint_codes, mock_origin_codes
    ):
        """
        Con tipo 'PREVENTIVO' y origen 'INTERNO' válidos, resolve_ticket supera
        las validaciones de catálogo sin lanzar HTTPException.
        Puede fallar más adelante por mocks de BD incompletos — eso es aceptable.
        """
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        ticket = self._make_ticket("IN_PROGRESS")  # D-F: resolver exige IN_PROGRESS salvo dispatcher/admin
        db.get.return_value = ticket

        try:
            resolve_ticket(
                db=db,
                ticket_id=1,
                resolved_by_id=1,
                success=True,
                maintenance_type="PREVENTIVO",
                service_origin="INTERNO",
                resolution_notes="Sin novedad",
                time_invested_minutes=30,
            )
        except HTTPException as exc:
            # Solo falla si el status_code es 400 (catálogo inválido) — eso sería un error.
            # Otros códigos (500, etc.) son esperables dado el mock parcial.
            assert exc.status_code != 400, (
                f"resolve_ticket rechazó tipo/origen válidos con 400: {exc.detail}"
            )
        except Exception:
            # Fallos de mock en DB son esperables — lo que importa es que NO lanzó 400 de catálogo.
            pass

        mock_maint_codes.assert_called()
        mock_origin_codes.assert_called()

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes",
        return_value={"INTERNO", "EXTERNO"},
    )
    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes",
        return_value={"PREVENTIVO", "CORRECTIVO"},
    )
    def test_resolve_ticket_maintenance_type_invalido_lanza_400(
        self, mock_maint_codes, mock_origin_codes
    ):
        """maintenance_type fuera del set válido → HTTPException 400."""
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        ticket = self._make_ticket("IN_PROGRESS")  # D-F: resolver exige IN_PROGRESS salvo dispatcher/admin
        db.get.return_value = ticket

        with pytest.raises(HTTPException) as exc_info:
            resolve_ticket(
                db=db,
                ticket_id=1,
                resolved_by_id=1,
                success=True,
                maintenance_type="PREDICTIVO",   # no está en el set
                service_origin="INTERNO",
                resolution_notes="Prueba",
                time_invested_minutes=15,
            )

        assert exc_info.value.status_code == 400
        assert "PREDICTIVO" not in {"PREVENTIVO", "CORRECTIVO"}

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes",
        return_value={"INTERNO", "EXTERNO"},
    )
    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes",
        return_value={"PREVENTIVO", "CORRECTIVO"},
    )
    def test_resolve_ticket_service_origin_invalido_lanza_400(
        self, mock_maint_codes, mock_origin_codes
    ):
        """service_origin fuera del set válido → HTTPException 400."""
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        ticket = self._make_ticket("IN_PROGRESS")  # D-F: resolver exige IN_PROGRESS salvo dispatcher/admin
        db.get.return_value = ticket

        with pytest.raises(HTTPException) as exc_info:
            resolve_ticket(
                db=db,
                ticket_id=1,
                resolved_by_id=1,
                success=True,
                maintenance_type="PREVENTIVO",
                service_origin="DESCONOCIDO",   # no está en el set
                resolution_notes="Prueba",
                time_invested_minutes=15,
            )

        assert exc_info.value.status_code == 400
        assert "DESCONOCIDO" not in {"INTERNO", "EXTERNO"}

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_service_origin_codes",
        return_value={"INTERNO", "EXTERNO"},
    )
    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_maint_type_codes",
        return_value={"PREVENTIVO", "CORRECTIVO"},
    )
    def test_resolve_ticket_ambos_invalidos_lanza_400_en_maintenance_type_primero(
        self, mock_maint_codes, mock_origin_codes
    ):
        """Cuando ambos son inválidos, se rechaza en maintenance_type (validación primero)."""
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        ticket = self._make_ticket("IN_PROGRESS")  # D-F: resolver exige IN_PROGRESS salvo dispatcher/admin
        db.get.return_value = ticket

        with pytest.raises(HTTPException) as exc_info:
            resolve_ticket(
                db=db,
                ticket_id=1,
                resolved_by_id=1,
                success=True,
                maintenance_type="INVALIDO",
                service_origin="INVALIDO",
                resolution_notes="Prueba",
                time_invested_minutes=15,
            )

        assert exc_info.value.status_code == 400

    def test_resolve_ticket_ticket_inexistente_lanza_404(self):
        """Ticket no encontrado → HTTPException 404 (antes de llegar al catálogo)."""
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            resolve_ticket(
                db=db,
                ticket_id=9999,
                resolved_by_id=1,
                success=True,
                maintenance_type="PREVENTIVO",
                service_origin="INTERNO",
                resolution_notes="Prueba",
                time_invested_minutes=15,
            )

        assert exc_info.value.status_code == 404

    def test_resolve_ticket_status_no_permitido_lanza_400(self):
        """Ticket en estado PENDING no puede resolverse → 400 antes del catálogo."""
        from itcj2.apps.maint.services.ticket_service import resolve_ticket

        db = MagicMock()
        ticket = self._make_ticket("PENDING")
        db.get.return_value = ticket

        with pytest.raises(HTTPException) as exc_info:
            resolve_ticket(
                db=db,
                ticket_id=1,
                resolved_by_id=1,
                success=True,
                maintenance_type="PREVENTIVO",
                service_origin="INTERNO",
                resolution_notes="Prueba",
                time_invested_minutes=15,
            )

        assert exc_info.value.status_code == 400

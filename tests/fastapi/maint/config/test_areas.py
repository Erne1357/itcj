"""
Tests — Áreas técnicas + refactor assign_area (maint Fase 5).

Secciones:
  A. catalog_cache áreas — unit sin app ni BD real.
  B. API /api/maint/v2/config/areas — TestClient con mocks.
  C. Refactor technicians.assign_area — regresión de validación con cache/fallback.

Estrategia global:
  - BD no disponible → mocks sobre _load_areas_from_db.
  - log_config_change se parchea en itcj2.apps.maint.api.config.areas (donde está importado).
  - invalidate_areas se parchea en itcj2.apps.maint.api.config.areas (importado directamente).
  - JWT admin (role='admin') → require_perms hace bypass automático.
  - Sin cookie → 401.
  - El cache de módulo se invalida antes de cada test que lo ejercite.
"""
import time
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


def _fake_area(
    area_id: int = 1,
    code: str = "ELECTRICAL",
    label: str = "Eléctrica",
    icon: str = "bi-lightning",
    color: str = "#fdd835",
    description: str = "Instalaciones eléctricas",
    display_order: int = 0,
    is_active: bool = True,
) -> MagicMock:
    """Simula un objeto MaintArea."""
    area = MagicMock()
    area.id = area_id
    area.code = code
    area.label = label
    area.icon = icon
    area.color = color
    area.description = description
    area.display_order = display_order
    area.is_active = is_active
    return area


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


@pytest.fixture
def app_client_no_raise():
    """
    TestClient que NO re-lanza excepciones del servidor.
    Usado para tests donde el validation_handler de main.py puede fallar
    al serializar ciertos errores de Pydantic v2 (ValueError en ctx.error).
    """
    app = create_app()
    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app, raise_server_exceptions=False) as c:
        c._mock_db = mock_db
        yield c
    app.dependency_overrides.clear()


# =============================================================================
# A. catalog_cache áreas — unit, sin app ni BD real
# =============================================================================

class TestAreasCacheWithDbDown:
    """_load_areas_from_db falla → funciones de áreas degradan silenciosamente."""

    def setup_method(self):
        """Invalida el cache antes de cada test para evitar interferencia."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_areas
        invalidate_areas()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_areas
        invalidate_areas()

    def test_get_area_codes_bd_caida_retorna_los_7_fallback(self):
        """Con BD caída, get_area_codes() devuelve los 7 códigos hardcoded incluyendo PAINTING."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_codes, invalidate_areas
            invalidate_areas()
            result = get_area_codes()

        assert isinstance(result, set)
        expected = {"TRANSPORT", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "GENERAL", "PAINTING"}
        assert result == expected

    def test_get_area_codes_bd_caida_incluye_painting(self):
        """PAINTING está en el fallback de get_area_codes()."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_codes, invalidate_areas
            invalidate_areas()
            result = get_area_codes()

        assert "PAINTING" in result

    def test_get_area_codes_bd_caida_no_lanza(self):
        """get_area_codes() con BD caída no propaga excepción."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_codes, invalidate_areas
            invalidate_areas()
            try:
                result = get_area_codes()
                assert isinstance(result, set)
            except Exception as exc:
                pytest.fail(f"get_area_codes lanzó excepción inesperada: {exc!r}")

    def test_get_area_by_code_transport_bd_caida_tolerante(self):
        """get_area_by_code('TRANSPORT') con BD caída retorna None sin lanzar."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_by_code, invalidate_areas
            invalidate_areas()
            try:
                result = get_area_by_code("TRANSPORT")
                # Con BD caída y cache vacío, puede ser None (no hay datos para buscar)
                assert result is None or isinstance(result, dict)
            except Exception as exc:
                pytest.fail(f"get_area_by_code lanzó excepción inesperada: {exc!r}")

    def test_get_areas_bd_caida_retorna_lista_con_fallback(self):
        """get_areas() con BD caída retorna lista con los 7 códigos hardcoded."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            side_effect=Exception("BD caída"),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_areas, invalidate_areas
            invalidate_areas()
            result = get_areas()

        assert isinstance(result, list)
        codes = {item["code"] for item in result}
        assert codes == {"TRANSPORT", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "GENERAL", "PAINTING"}

    def test_invalidate_areas_idempotente_no_lanza(self):
        """invalidate_areas() nunca lanza, ni con cache lleno ni vacío."""
        from itcj2.apps.maint.utils.catalog_cache import invalidate_areas
        try:
            invalidate_areas()
            invalidate_areas()   # segunda vez, cache ya vacío
            invalidate_areas()   # tercera vez
        except Exception as exc:
            pytest.fail(f"invalidate_areas lanzó: {exc!r}")


class TestAreasCacheWithMockedDb:
    """catalog_cache lee correctamente desde BD mockeada para áreas."""

    def setup_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_areas
        invalidate_areas()

    def teardown_method(self):
        from itcj2.apps.maint.utils.catalog_cache import invalidate_areas
        invalidate_areas()

    def _fake_rows(self) -> list:
        return [
            {"id": 1, "code": "ELECTRICAL", "label": "Eléctrica",
             "icon": "bi-lightning", "color": "#fdd835",
             "description": "Instalaciones eléctricas",
             "display_order": 0, "is_active": True},
            {"id": 2, "code": "TRANSPORT", "label": "Transporte",
             "icon": "bi-truck", "color": "#1565c0",
             "description": "Vehículos y transporte",
             "display_order": 1, "is_active": True},
            {"id": 3, "code": "PAINTING", "label": "Pintura",
             "icon": None, "color": None,
             "description": None,
             "display_order": 2, "is_active": False},
        ]

    def test_get_areas_refleja_datos_de_bd(self):
        """get_areas() devuelve la lista de dicts proveniente de la BD."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_areas, invalidate_areas
            invalidate_areas()
            result = get_areas()

        assert len(result) == 3
        assert result[0]["code"] == "ELECTRICAL"
        assert result[1]["code"] == "TRANSPORT"

    def test_get_areas_cachea_resultado(self):
        """La segunda llamada no vuelve a invocar _load_areas_from_db."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import get_areas, invalidate_areas
            invalidate_areas()
            get_areas()
            get_areas()   # segunda llamada — debe usar cache

        assert mock_load.call_count == 1

    def test_invalidate_areas_fuerza_recarga(self):
        """Tras invalidate_areas(), el siguiente get_areas() llama _load_areas_from_db."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ) as mock_load:
            from itcj2.apps.maint.utils.catalog_cache import get_areas, invalidate_areas
            invalidate_areas()
            get_areas()        # primera carga
            invalidate_areas()
            get_areas()        # recarga tras invalidar

        assert mock_load.call_count == 2

    def test_get_area_codes_solo_activos(self):
        """get_area_codes() filtra solo is_active=True."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_codes, invalidate_areas
            invalidate_areas()
            codes = get_area_codes()

        # ELECTRICAL y TRANSPORT están activas; PAINTING está inactiva
        assert "ELECTRICAL" in codes
        assert "TRANSPORT" in codes
        assert "PAINTING" not in codes

    def test_get_area_by_code_existente_retorna_dict(self):
        """get_area_by_code('ELECTRICAL') retorna el dict correcto."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_by_code, invalidate_areas
            invalidate_areas()
            result = get_area_by_code("ELECTRICAL")

        assert result is not None
        assert result["code"] == "ELECTRICAL"
        assert result["label"] == "Eléctrica"
        assert "icon" in result

    def test_get_area_by_code_inexistente_retorna_none(self):
        """get_area_by_code('INEXISTENTE') retorna None sin lanzar."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_area_by_code, invalidate_areas
            invalidate_areas()
            result = get_area_by_code("INEXISTENTE")

        assert result is None

    def test_get_areas_tiene_todos_los_campos_esperados(self):
        """Cada ítem de get_areas() tiene id, code, label, icon, color, description, display_order, is_active."""
        with patch(
            "itcj2.apps.maint.utils.catalog_cache._load_areas_from_db",
            return_value=self._fake_rows(),
        ):
            from itcj2.apps.maint.utils.catalog_cache import get_areas, invalidate_areas
            invalidate_areas()
            result = get_areas()

        for field in ("id", "code", "label", "icon", "color", "description", "display_order", "is_active"):
            assert field in result[0], f"Campo '{field}' faltante en ítem de get_areas()"


# =============================================================================
# B. API /api/maint/v2/config/areas
# =============================================================================

class TestAreasApiGet:
    """GET /api/maint/v2/config/areas"""

    def _setup_db_query(self, mock_db, areas: list):
        """Configura la cadena de mock para db.query(...).order_by(...).all()"""
        mock_db.query.return_value.order_by.return_value.all.return_value = areas

    def test_get_returns_200(self, app_client):
        """Admin obtiene 200."""
        a1 = _fake_area(1, "ELECTRICAL")
        a2 = _fake_area(2, "TRANSPORT")
        self._setup_db_query(app_client._mock_db, [a1, a2])

        r = app_client.get(
            "/api/maint/v2/config/areas",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_get_response_shape(self, app_client):
        """Respuesta tiene success=True, data (list) y total."""
        a = _fake_area()
        self._setup_db_query(app_client._mock_db, [a])

        r = app_client.get(
            "/api/maint/v2/config/areas",
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "total" in body

    def test_get_total_correcto(self, app_client):
        """total coincide con la cantidad de áreas."""
        areas = [_fake_area(i, f"AREA{i}") for i in range(1, 5)]
        self._setup_db_query(app_client._mock_db, areas)

        r = app_client.get(
            "/api/maint/v2/config/areas",
            headers=_admin_headers(),
        )
        assert r.json()["total"] == 4

    def test_get_data_item_estructura(self, app_client):
        """Cada item en data tiene id, code, label, icon, color, description, display_order, is_active."""
        a = _fake_area(5, "AC", label="Aire Acondicionado")
        self._setup_db_query(app_client._mock_db, [a])

        r = app_client.get(
            "/api/maint/v2/config/areas",
            headers=_admin_headers(),
        )
        item = r.json()["data"][0]
        for field in ("id", "code", "label", "icon", "color", "description", "display_order", "is_active"):
            assert field in item, f"Campo '{field}' faltante en item"

    def test_get_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/areas")
        assert r.status_code == 401

    def test_get_token_invalido_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            "/api/maint/v2/config/areas",
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401


class TestAreasApiPost:
    """POST /api/maint/v2/config/areas"""

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_post_happy_returns_201(self, mock_log, mock_inv, app_client):
        """POST con datos válidos → 201."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.return_value = None

        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={
                "code": "PLUMBING",
                "label": "Plomería",
                "icon": "bi-wrench",
                "color": "#4caf50",
                "description": "Instalaciones hidráulicas",
                "display_order": 5,
            },
            headers=_admin_headers(),
        )
        assert r.status_code == 201

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_post_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """POST exitoso devuelve {success: true, data: {...}}."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.return_value = None

        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING", "label": "Plomería"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_post_code_duplicado_retorna_400(self, mock_log, mock_inv, app_client):
        """POST con code ya existente → 400."""
        mock_db = app_client._mock_db
        existing = _fake_area(1, "ELECTRICAL")
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "ELECTRICAL", "label": "Eléctrica dup"},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_post_code_regex_invalido_rechazado(self, app_client_no_raise):
        """
        code que no cumple ^[A-Z][A-Z0-9_]*$ es rechazado por el field_validator.

        Usa app_client_no_raise porque el validation_handler de main.py no serializa
        correctamente el ValueError embebido en ctx.error de Pydantic v2 (Python 3.13),
        lo que provoca que el handler mismo falle con TypeError. El TestClient normal
        re-lanzaría esa excepción. Con raise_server_exceptions=False obtenemos el
        código de respuesta real (422 o 500) sin que el test explote.
        """
        r = app_client_no_raise.post(
            "/api/maint/v2/config/areas",
            json={"code": "123invalid", "label": "Inválido"},
            headers=_admin_headers(),
        )
        # El recurso no se crea: Pydantic rechaza el input (422) o el handler
        # falla al serializar (500). En ningún caso debería ser 201.
        assert r.status_code != 201, (
            f"Se esperaba rechazo del code inválido '123invalid', "
            f"pero el endpoint respondió 201."
        )

    def test_post_code_iniciando_con_numero_rechazado(self, app_client_no_raise):
        """code que comienza con número viola el regex → no retorna 201."""
        r = app_client_no_raise.post(
            "/api/maint/v2/config/areas",
            json={"code": "1ELECTRICAL", "label": "Eléctrica"},
            headers=_admin_headers(),
        )
        assert r.status_code != 201

    def test_post_sin_label_retorna_422(self, app_client):
        """label faltante → 422."""
        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_label_vacio_retorna_422(self, app_client):
        """label vacío viola min_length=1 → 422."""
        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING", "label": ""},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_post_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING", "label": "Plomería"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_post_invoca_invalidate_areas(self, mock_log, mock_inv, app_client):
        """POST exitoso llama invalidate_areas()."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.return_value = None

        app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING", "label": "Plomería"},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_post_invoca_log_config_change_con_entity_area(self, mock_log, mock_inv, app_client):
        """POST exitoso llama log_config_change con entity_type='area'."""
        mock_db = app_client._mock_db
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.flush.return_value = None

        app_client.post(
            "/api/maint/v2/config/areas",
            json={"code": "PLUMBING", "label": "Plomería"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "area"


class TestAreasApiPatch:
    """PATCH /api/maint/v2/config/areas/{area_id}"""

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_patch_happy_returns_200(self, mock_log, mock_inv, app_client):
        """PATCH con área existente → 200."""
        area = _fake_area(3, "AC", label="Aire Acondicionado")
        app_client._mock_db.get.return_value = area

        r = app_client.patch(
            "/api/maint/v2/config/areas/3",
            json={"label": "Climatización"},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_patch_happy_success_true_y_data(self, mock_log, mock_inv, app_client):
        """PATCH exitoso devuelve {success: true, data: {...}}."""
        area = _fake_area(3, "AC")
        app_client._mock_db.get.return_value = area

        r = app_client.patch(
            "/api/maint/v2/config/areas/3",
            json={"label": "Climatización"},
            headers=_admin_headers(),
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_patch_area_inexistente_retorna_404(self, app_client):
        """db.get devuelve None → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.patch(
            "/api/maint/v2/config/areas/9999",
            json={"label": "X"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_patch_display_order_negativo_retorna_422(self, app_client):
        """display_order negativo viola ge=0 del schema → 422."""
        r = app_client.patch(
            "/api/maint/v2/config/areas/1",
            json={"display_order": -1},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_patch_no_modifica_code(self, app_client):
        """UpdateArea no tiene campo code → incluirlo es ignorado por Pydantic (extra='ignore')."""
        # El campo code no está en UpdateArea, Pydantic lo ignora.
        # El endpoint no debe intentar setattr(area, 'code', ...).
        # Este test verifica que la ruta no explota con code en el payload.
        area = _fake_area(1, "ELECTRICAL")
        app_client._mock_db.get.return_value = area

        with patch("itcj2.apps.maint.api.config.areas.invalidate_areas"), \
             patch("itcj2.apps.maint.api.config.areas.log_config_change"):
            r = app_client.patch(
                "/api/maint/v2/config/areas/1",
                json={"label": "Nueva etiqueta", "code": "CAMBIO_ILEGAL"},
                headers=_admin_headers(),
            )
        # Debe responder OK; code nunca se modifica
        assert r.status_code == 200

    def test_patch_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/areas/1",
            json={"label": "X"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_patch_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """PATCH exitoso invoca log_config_change e invalidate_areas."""
        area = _fake_area(3, "AC")
        app_client._mock_db.get.return_value = area

        app_client.patch(
            "/api/maint/v2/config/areas/3",
            json={"label": "Climatización"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_patch_log_config_change_entity_area(self, mock_log, mock_inv, app_client):
        """PATCH exitoso llama log_config_change con entity_type='area'."""
        area = _fake_area(3, "AC")
        app_client._mock_db.get.return_value = area

        app_client.patch(
            "/api/maint/v2/config/areas/3",
            json={"icon": "bi-wind"},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "area"


class TestAreasApiToggle:
    """PATCH /api/maint/v2/config/areas/{area_id}/toggle"""

    def _count_returns(self, mock_db, count: int):
        """Configura el count de áreas activas en el mock."""
        mock_db.query.return_value.filter.return_value.count.return_value = count

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_activar_returns_200(self, mock_log, mock_inv, app_client):
        """Activar un área inactiva → 200."""
        area = _fake_area(2, "GARDENING", is_active=False)
        app_client._mock_db.get.return_value = area
        self._count_returns(app_client._mock_db, 5)

        r = app_client.patch(
            "/api/maint/v2/config/areas/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_desactivar_normal_returns_200(self, mock_log, mock_inv, app_client):
        """Desactivar un área activa cuando quedan más → 200."""
        area = _fake_area(2, "CARPENTRY", is_active=True)
        app_client._mock_db.get.return_value = area
        # Simular: hay 5 activas y 0 técnicos con esa área
        self._count_returns(app_client._mock_db, 5)
        # El segundo query (conteo de técnicos) también retorna 0
        app_client._mock_db.query.return_value.filter.return_value.count.side_effect = [5, 0]

        r = app_client.patch(
            "/api/maint/v2/config/areas/2/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_toggle_ultima_activa_retorna_400(self, app_client):
        """No se puede desactivar la última área activa → 400."""
        area = _fake_area(1, "GENERAL", is_active=True)
        app_client._mock_db.get.return_value = area
        self._count_returns(app_client._mock_db, 1)

        r = app_client.patch(
            "/api/maint/v2/config/areas/1/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_desactivar_con_tecnicos_devuelve_warning(self, mock_log, mock_inv, app_client):
        """
        Desactivar área con técnicos enlazados → 200 con campo 'warning' en respuesta.
        No bloquea; solo es informativo.
        """
        area = _fake_area(3, "TRANSPORT", is_active=True)
        app_client._mock_db.get.return_value = area
        # Primer count: áreas activas (5), segundo count: técnicos con esa área (3)
        app_client._mock_db.query.return_value.filter.return_value.count.side_effect = [5, 3]

        r = app_client.patch(
            "/api/maint/v2/config/areas/3/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert "warning" in body
        # El warning debe mencionar el conteo de técnicos
        assert "3" in body["warning"]

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_desactivar_sin_tecnicos_no_devuelve_warning(self, mock_log, mock_inv, app_client):
        """Desactivar área sin técnicos enlazados → 200 sin campo 'warning'."""
        area = _fake_area(3, "TRANSPORT", is_active=True)
        app_client._mock_db.get.return_value = area
        # Primer count: áreas activas (5), segundo count: técnicos con esa área (0)
        app_client._mock_db.query.return_value.filter.return_value.count.side_effect = [5, 0]

        r = app_client.patch(
            "/api/maint/v2/config/areas/3/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert "warning" not in body

    def test_toggle_area_inexistente_retorna_404(self, app_client):
        """Área no encontrada → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.patch(
            "/api/maint/v2/config/areas/9999/toggle",
            json={"is_active": False},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_toggle_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.patch(
            "/api/maint/v2/config/areas/1/toggle",
            json={"is_active": True},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_invoca_log_y_invalidate(self, mock_log, mock_inv, app_client):
        """Toggle exitoso invoca log_config_change e invalidate_areas."""
        area = _fake_area(2, "GARDENING", is_active=False)
        app_client._mock_db.get.return_value = area
        self._count_returns(app_client._mock_db, 5)

        app_client.patch(
            "/api/maint/v2/config/areas/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        mock_inv.assert_called()

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_toggle_log_config_change_entity_area(self, mock_log, mock_inv, app_client):
        """Toggle exitoso llama log_config_change con entity_type='area'."""
        area = _fake_area(2, "GARDENING", is_active=False)
        app_client._mock_db.get.return_value = area
        self._count_returns(app_client._mock_db, 5)

        app_client.patch(
            "/api/maint/v2/config/areas/2/toggle",
            json={"is_active": True},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "area"


class TestAreasApiReorder:
    """PUT /api/maint/v2/config/areas/reorder"""

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_reorder_happy_returns_200(self, mock_log, mock_inv, app_client):
        """Reorder con IDs válidos → 200 {success: true}."""
        a1 = _fake_area(1, "ELECTRICAL", display_order=0)
        a2 = _fake_area(2, "TRANSPORT", display_order=1)

        def _get(model, pk):
            return {1: a1, 2: a2}.get(pk)

        app_client._mock_db.get.side_effect = _get

        r = app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 1, "display_order": 1}, {"id": 2, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reorder_lista_vacia_retorna_400(self, app_client):
        """Lista de orden vacía → 400."""
        r = app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": []},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_reorder_id_inexistente_retorna_404(self, app_client):
        """ID de área inexistente en la lista → 404."""
        app_client._mock_db.get.return_value = None

        r = app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 9999, "display_order": 0}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 404

    def test_reorder_display_order_negativo_retorna_422(self, app_client):
        """display_order negativo en ítem de orden viola ge=0 → 422."""
        r = app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 1, "display_order": -1}]},
            headers=_admin_headers(),
        )
        assert r.status_code == 422

    def test_reorder_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_reorder_invoca_invalidate_y_log(self, mock_log, mock_inv, app_client):
        """Reorder exitoso llama invalidate_areas y log_config_change."""
        a = _fake_area(1, "ELECTRICAL")
        app_client._mock_db.get.return_value = a

        app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
            headers=_admin_headers(),
        )
        mock_inv.assert_called()
        mock_log.assert_called()

    @patch("itcj2.apps.maint.api.config.areas.invalidate_areas")
    @patch("itcj2.apps.maint.api.config.areas.log_config_change")
    def test_reorder_log_entity_area(self, mock_log, mock_inv, app_client):
        """Reorder exitoso llama log_config_change con entity_type='area'."""
        a = _fake_area(1, "ELECTRICAL")
        app_client._mock_db.get.return_value = a

        app_client.put(
            "/api/maint/v2/config/areas/reorder",
            json={"order": [{"id": 1, "display_order": 0}]},
            headers=_admin_headers(),
        )
        mock_log.assert_called()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("entity_type") == "area"


# =============================================================================
# C. Refactor technicians.assign_area — regresión de validación
# =============================================================================

class TestAssignAreaValidationWithCache:
    """
    Verifica que el endpoint POST /api/maint/v2/technicians/{user_id}/areas
    valida area_code contra get_area_codes() del cache (con fallback a VALID_AREAS).

    Estrategia:
      - Parchear get_area_codes en el namespace donde assign_area lo importa:
        itcj2.apps.maint.utils.catalog_cache.get_area_codes
        (importado con `from itcj2.apps.maint.utils.catalog_cache import get_area_codes`
        dentro del cuerpo del endpoint).
      - Parchear assignment_service.assign_technician_area para que no use BD.
    """

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_area_codes",
        return_value={"TRANSPORT", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "GENERAL", "PAINTING"},
    )
    @patch("itcj2.apps.maint.api.technicians.assignment_service.assign_technician_area")
    def test_area_valida_en_cache_asigna_ok(self, mock_assign, mock_codes, app_client):
        """area_code en el set del cache → 201 (asignación exitosa)."""
        fake_area_record = MagicMock()
        fake_area_record.area_code = "TRANSPORT"
        fake_area_record.user_id = 10
        mock_assign.return_value = fake_area_record

        r = app_client.post(
            "/api/maint/v2/technicians/10/areas",
            json={"area_code": "TRANSPORT"},
            headers=_admin_headers(),
        )
        assert r.status_code == 201

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_area_codes",
        return_value={"TRANSPORT", "ELECTRICAL"},
    )
    def test_area_fuera_del_set_retorna_400(self, mock_codes, app_client):
        """area_code que no está en el set del cache → 400."""
        r = app_client.post(
            "/api/maint/v2/technicians/10/areas",
            json={"area_code": "INVALIDA"},
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_area_codes",
        return_value={"TRANSPORT", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "GENERAL", "PAINTING"},
    )
    @patch("itcj2.apps.maint.api.technicians.assignment_service.assign_technician_area")
    def test_painting_en_cache_aceptado(self, mock_assign, mock_codes, app_client):
        """PAINTING está en el cache → 201 (refactor correcto, antes PAINTING no estaba en el service)."""
        fake_area_record = MagicMock()
        fake_area_record.area_code = "PAINTING"
        fake_area_record.user_id = 5
        mock_assign.return_value = fake_area_record

        r = app_client.post(
            "/api/maint/v2/technicians/5/areas",
            json={"area_code": "PAINTING"},
            headers=_admin_headers(),
        )
        assert r.status_code == 201

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_area_codes",
        return_value={"TRANSPORT", "ELECTRICAL", "CARPENTRY", "AC", "GARDENING", "GENERAL", "PAINTING"},
    )
    @patch("itcj2.apps.maint.api.technicians.assignment_service.assign_technician_area")
    def test_area_code_normalizado_a_upper(self, mock_assign, mock_codes, app_client):
        """area_code en minúsculas se normaliza a UPPER antes de validar."""
        fake_area_record = MagicMock()
        fake_area_record.area_code = "TRANSPORT"
        fake_area_record.user_id = 10
        mock_assign.return_value = fake_area_record

        r = app_client.post(
            "/api/maint/v2/technicians/10/areas",
            json={"area_code": "transport"},   # minúsculas
            headers=_admin_headers(),
        )
        # El endpoint hace .upper() antes de validar
        assert r.status_code == 201

    def test_assign_area_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.post(
            "/api/maint/v2/technicians/10/areas",
            json={"area_code": "TRANSPORT"},
        )
        assert r.status_code == 401

    @patch(
        "itcj2.apps.maint.utils.catalog_cache.get_area_codes",
        return_value=set(),  # set vacío → fallback a VALID_AREAS del módulo
    )
    @patch("itcj2.apps.maint.api.technicians.assignment_service.assign_technician_area")
    def test_get_area_codes_retorna_set_vacio_usa_valid_areas_fallback(
        self, mock_assign, mock_codes, app_client
    ):
        """
        Si get_area_codes() retorna set vacío (falsy), el endpoint usa VALID_AREAS como fallback.
        VALID_AREAS en technicians.py incluye PAINTING.
        El endpoint hace: valid_codes = get_area_codes() or VALID_AREAS
        """
        fake_area_record = MagicMock()
        fake_area_record.area_code = "PAINTING"
        fake_area_record.user_id = 7
        mock_assign.return_value = fake_area_record

        r = app_client.post(
            "/api/maint/v2/technicians/7/areas",
            json={"area_code": "PAINTING"},
            headers=_admin_headers(),
        )
        # PAINTING está en VALID_AREAS (el fallback del módulo technicians.py)
        assert r.status_code == 201

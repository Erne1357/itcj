"""
Tests para el Field Template Builder backend (maint — Fase 2).

Cubre:
  A. Unit del validador puro validate_field_template (sin app, sin BD).
  B. Endpoints GET /api/maint/v2/config/field-templates/{id}
             PUT /api/maint/v2/config/field-templates/{id}
     usando TestClient con get_db override y servicios mockeados.

Estrategia:
  - Validador: import directo, sin pytest-asyncio, sin TestClient.
  - API: fixture app_client (idéntica a test_api_smoke.py) + @patch sobre
    itcj2.apps.maint.services.category_service.get_category_by_id /
    update_field_template para evitar toda dependencia de BD.
  - JWT admin (role='admin') → require_perms hace bypass; sin cookie → 401.
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
from itcj2.apps.maint.services.field_template_validator import validate_field_template


# ─────────────────────────────────────────────────────────────────────────────
# Helpers JWT
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de app
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client():
    """TestClient con get_db override — patrón idéntico a test_api_smoke.py."""
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


def _fake_category(
    category_id: int = 7,
    code: str = "ELEC",
    name: str = "Electricidad",
    is_active: bool = True,
    field_template: list = None,
):
    """Objeto con atributos que simula un MaintCategory devuelto por el service."""
    obj = MagicMock()
    obj.id = category_id
    obj.code = code
    obj.name = name
    obj.is_active = is_active
    obj.field_template = field_template or []
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# A. Unit del validador puro
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateFieldTemplateNoneAndEmpty:
    def test_none_returns_empty_list(self):
        assert validate_field_template(None) == []

    def test_empty_list_returns_empty_list(self):
        assert validate_field_template([]) == []


class TestValidateFieldTemplateMinimoValido:
    def test_campo_minimo_conserva_key_y_label(self):
        result = validate_field_template([
            {"key": "nombre", "label": "Nombre", "type": "text"}
        ])
        assert len(result) == 1
        assert result[0]["key"] == "nombre"
        assert result[0]["label"] == "Nombre"
        assert result[0]["type"] == "text"

    def test_campo_minimo_defaults_required_a_false(self):
        result = validate_field_template([
            {"key": "obs", "label": "Observaciones", "type": "text"}
        ])
        assert result[0]["required"] is False

    def test_required_true_se_conserva(self):
        result = validate_field_template([
            {"key": "area", "label": "Área", "type": "text", "required": True}
        ])
        assert result[0]["required"] is True


class TestValidateFieldTemplateKeyInvalido:
    @pytest.mark.parametrize("bad_key", [
        "Bad",        # mayúscula
        "1x",         # empieza con dígito
        "a b",        # espacio
        "",           # vacío
        "A_UPPER",    # todo mayúsculas
        "kebab-case", # guion no permitido
    ])
    def test_key_invalido_lanza_422(self, bad_key):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": bad_key, "label": "Campo", "type": "text"}
            ])
        assert exc_info.value.status_code == 422

    def test_key_invalido_mensaje_incluye_posicion(self):
        """El detail del 422 menciona el índice o el key problemático."""
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "Bad", "label": "Campo", "type": "text"}
            ])
        detail = exc_info.value.detail
        # Debe mencionar índice 0 o el key 'Bad'
        assert "0" in detail or "Bad" in detail

    def test_key_duplicado_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "cosa", "label": "Cosa 1", "type": "text"},
                {"key": "cosa", "label": "Cosa 2", "type": "number"},
            ])
        assert exc_info.value.status_code == 422

    def test_key_duplicado_mensaje_incluye_key(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "dup", "label": "Dup 1", "type": "text"},
                {"key": "dup", "label": "Dup 2", "type": "text"},
            ])
        assert "dup" in exc_info.value.detail


class TestValidateFieldTemplateLabelInvalido:
    def test_label_vacio_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "", "type": "text"}
            ])
        assert exc_info.value.status_code == 422

    def test_label_solo_espacios_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "   ", "type": "text"}
            ])
        assert exc_info.value.status_code == 422

    def test_label_ausente_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "type": "text"}
            ])
        assert exc_info.value.status_code == 422


class TestValidateFieldTemplateTipoInvalido:
    @pytest.mark.parametrize("bad_type", [
        "textarea", "radio", "file", "checkbox", "foo", "TEXT", "Select",
    ])
    def test_type_no_soportado_lanza_422(self, bad_type):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "Campo", "type": bad_type}
            ])
        assert exc_info.value.status_code == 422

    @pytest.mark.parametrize("valid_type", [
        "text", "number", "date", "time", "select",
    ])
    def test_tipos_soportados_son_validos(self, valid_type):
        fields = [{"key": "campo", "label": "Campo", "type": valid_type}]
        if valid_type == "select":
            fields[0]["options"] = ["opcion1"]
        result = validate_field_template(fields)
        assert result[0]["type"] == valid_type


class TestValidateFieldTemplateSelect:
    def test_select_sin_options_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "piso", "label": "Piso", "type": "select"}
            ])
        assert exc_info.value.status_code == 422

    def test_select_options_lista_vacia_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "piso", "label": "Piso", "type": "select", "options": []}
            ])
        assert exc_info.value.status_code == 422

    def test_select_option_string_vacio_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "piso", "label": "Piso", "type": "select", "options": ["", "Primero"]}
            ])
        assert exc_info.value.status_code == 422

    def test_select_options_duplicadas_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "piso", "label": "Piso", "type": "select",
                 "options": ["Primero", "Segundo", "Primero"]}
            ])
        assert exc_info.value.status_code == 422

    def test_select_options_validas_se_conservan(self):
        result = validate_field_template([
            {"key": "piso", "label": "Piso", "type": "select",
             "options": ["Primero", "Segundo", "Tercero"]}
        ])
        assert result[0]["options"] == ["Primero", "Segundo", "Tercero"]

    def test_select_options_se_trimmean(self):
        """Opciones con espacios al inicio/fin se limpian."""
        result = validate_field_template([
            {"key": "zona", "label": "Zona", "type": "select",
             "options": ["  Norte  ", "  Sur  "]}
        ])
        assert result[0]["options"] == ["Norte", "Sur"]

    def test_select_options_unico_elemento_valido(self):
        result = validate_field_template([
            {"key": "turno", "label": "Turno", "type": "select", "options": ["Matutino"]}
        ])
        assert len(result[0]["options"]) == 1


class TestValidateFieldTemplateClavesExtra:
    def test_visible_when_descartado(self):
        result = validate_field_template([
            {"key": "obs", "label": "Obs", "type": "text",
             "visible_when": {"key": "otro", "value": "si"}}
        ])
        assert "visible_when" not in result[0]

    def test_order_descartado(self):
        result = validate_field_template([
            {"key": "obs", "label": "Obs", "type": "text", "order": 99}
        ])
        assert "order" not in result[0]

    def test_validation_descartado(self):
        result = validate_field_template([
            {"key": "obs", "label": "Obs", "type": "text",
             "validation": {"min": 1, "max": 100}}
        ])
        assert "validation" not in result[0]

    def test_solo_claves_conocidas_en_salida(self):
        """El resultado solo contiene key, label, type, required (y options si select)."""
        result = validate_field_template([
            {"key": "campo", "label": "Campo", "type": "text",
             "extra1": "x", "extra2": 42, "visible_when": True, "order": 1}
        ])
        allowed = {"key", "label", "type", "required"}
        assert set(result[0].keys()) == allowed


class TestValidateFieldTemplateRequiredNoBool:
    def test_required_string_lanza_422(self):
        """El validador exige required bool; string debe lanzar 422."""
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "Campo", "type": "text", "required": "yes"}
            ])
        assert exc_info.value.status_code == 422

    def test_required_int_lanza_422(self):
        """Entero 1 no es bool en Python (isinstance(1, bool) es False solo si no es True/False)."""
        # En Python isinstance(True, int) es True, pero isinstance(1, bool) es False
        # El validador hace isinstance(required_raw, bool), así que int 1 → 422
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "Campo", "type": "text", "required": 1}
            ])
        assert exc_info.value.status_code == 422

    def test_required_none_lanza_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "campo", "label": "Campo", "type": "text", "required": None}
            ])
        assert exc_info.value.status_code == 422


class TestValidateFieldTemplateMultiplesCampos:
    def test_dos_campos_validos_se_normalizan(self):
        result = validate_field_template([
            {"key": "nombre", "label": "Nombre", "type": "text", "required": True},
            {"key": "nivel", "label": "Nivel", "type": "select",
             "options": ["Bajo", "Medio", "Alto"], "required": False},
        ])
        assert len(result) == 2
        assert result[0]["key"] == "nombre"
        assert result[1]["key"] == "nivel"
        assert result[1]["options"] == ["Bajo", "Medio", "Alto"]

    def test_error_en_segundo_campo_incluye_indice_1(self):
        """El mensaje de error menciona posición 1 cuando el primer campo es válido."""
        with pytest.raises(HTTPException) as exc_info:
            validate_field_template([
                {"key": "ok", "label": "OK", "type": "text"},
                {"key": "Bad", "label": "Malo", "type": "text"},
            ])
        detail = exc_info.value.detail
        assert "1" in detail or "Bad" in detail


# ─────────────────────────────────────────────────────────────────────────────
# B. Tests de API — GET /api/maint/v2/config/field-templates/{category_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFieldTemplateAPI:
    @patch("itcj2.apps.maint.services.category_service.get_category_by_id")
    def test_get_happy_path_returns_200(self, mock_get, app_client, admin_headers):
        """Admin obtiene 200 con estructura correcta."""
        mock_get.return_value = _fake_category(
            category_id=7,
            code="ELEC",
            name="Electricidad",
            is_active=True,
            field_template=[
                {"key": "zona", "label": "Zona", "type": "text", "required": False}
            ],
        )
        r = app_client.get(
            "/api/maint/v2/config/field-templates/7",
            headers=admin_headers,
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.category_service.get_category_by_id")
    def test_get_response_shape_success_true(self, mock_get, app_client, admin_headers):
        """Respuesta tiene success=True y data con los campos esperados."""
        mock_get.return_value = _fake_category(
            category_id=7,
            field_template=[{"key": "zona", "label": "Zona", "type": "text", "required": False}],
        )
        r = app_client.get("/api/maint/v2/config/field-templates/7", headers=admin_headers)
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    @patch("itcj2.apps.maint.services.category_service.get_category_by_id")
    def test_get_data_contains_expected_keys(self, mock_get, app_client, admin_headers):
        """El objeto data incluye category_id, code, name, is_active, field_template."""
        mock_get.return_value = _fake_category(
            category_id=7,
            code="ELEC",
            name="Electricidad",
            is_active=True,
            field_template=[],
        )
        r = app_client.get("/api/maint/v2/config/field-templates/7", headers=admin_headers)
        data = r.json()["data"]
        assert data["category_id"] == 7
        assert data["code"] == "ELEC"
        assert data["name"] == "Electricidad"
        assert data["is_active"] is True
        assert isinstance(data["field_template"], list)

    @patch("itcj2.apps.maint.services.category_service.get_category_by_id")
    def test_get_field_template_propagado_desde_categoria(self, mock_get, app_client, admin_headers):
        """field_template del mock se refleja en la respuesta."""
        fields = [
            {"key": "piso", "label": "Piso", "type": "select",
             "options": ["1", "2", "3"], "required": False}
        ]
        mock_get.return_value = _fake_category(category_id=5, field_template=fields)
        r = app_client.get("/api/maint/v2/config/field-templates/5", headers=admin_headers)
        assert r.json()["data"]["field_template"] == fields

    @patch("itcj2.apps.maint.services.category_service.get_category_by_id")
    def test_get_404_cuando_categoria_no_existe(self, mock_get, app_client, admin_headers):
        """Service lanza HTTPException(404) → endpoint devuelve 404."""
        mock_get.side_effect = HTTPException(status_code=404, detail="Categoría no encontrada")
        r = app_client.get("/api/maint/v2/config/field-templates/9999", headers=admin_headers)
        assert r.status_code == 404

    def test_get_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get("/api/maint/v2/config/field-templates/7")
        assert r.status_code == 401

    def test_get_cookie_invalida_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            "/api/maint/v2/config/field-templates/7",
            headers={"Cookie": "itcj_token=not_a_real_token"},
        )
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# B. Tests de API — PUT /api/maint/v2/config/field-templates/{category_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestPutFieldTemplateAPI:
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_happy_path_returns_200(self, mock_upd, app_client, admin_headers):
        """PUT con body válido → 200."""
        mock_upd.return_value = _fake_category(
            category_id=7,
            field_template=[{"key": "obs", "label": "Observaciones", "type": "text", "required": False}],
        )
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [{"key": "obs", "label": "Observaciones", "type": "text"}]},
            headers=admin_headers,
        )
        assert r.status_code == 200

    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_happy_path_success_true(self, mock_upd, app_client, admin_headers):
        """Respuesta tiene success=True y data."""
        mock_upd.return_value = _fake_category(category_id=7, field_template=[])
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": []},
            headers=admin_headers,
        )
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_lista_vacia_elimina_template(self, mock_upd, app_client, admin_headers):
        """fields=[] es válido (elimina template); service devuelve campo vacío."""
        mock_upd.return_value = _fake_category(category_id=7, field_template=None)
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": []},
            headers=admin_headers,
        )
        assert r.status_code == 200
        # field_template None → serializado como [] por _category_to_dict
        assert r.json()["data"]["field_template"] == []

    def test_put_key_invalido_retorna_422(self, app_client, admin_headers):
        """Campo con key inválido ('Bad') → 422 por el validador antes de tocar BD."""
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [{"key": "Bad", "label": "Nombre", "type": "text"}]},
            headers=admin_headers,
        )
        assert r.status_code == 422

    def test_put_key_invalido_detail_no_vacio(self, app_client, admin_headers):
        """El detail del 422 contiene información sobre el campo culpable.

        El exception handler del proyecto serializa HTTPException(422) como
        {"status": 422, "error": "<mensaje>"} — usa la clave "error", no "detail".
        Pydantic ValidationError (body mal formado) sigue con "detail".
        Se verifica que alguna de las dos claves tenga contenido no vacío.
        """
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [{"key": "Bad", "label": "Nombre", "type": "text"}]},
            headers=admin_headers,
        )
        assert r.status_code == 422
        body = r.json()
        # El handler propio usa "error"; el handler Pydantic usa "detail"
        message = body.get("error") or body.get("detail") or ""
        if isinstance(message, list):
            assert len(message) > 0
        else:
            assert str(message).strip() != ""

    def test_put_type_invalido_retorna_422(self, app_client, admin_headers):
        """type='textarea' no soportado → 422."""
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [{"key": "obs", "label": "Obs", "type": "textarea"}]},
            headers=admin_headers,
        )
        assert r.status_code == 422

    def test_put_select_sin_options_retorna_422(self, app_client, admin_headers):
        """type='select' sin options → 422."""
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [{"key": "zona", "label": "Zona", "type": "select"}]},
            headers=admin_headers,
        )
        assert r.status_code == 422

    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_404_cuando_categoria_no_existe(self, mock_upd, app_client, admin_headers):
        """Service lanza HTTPException(404) → endpoint devuelve 404."""
        mock_upd.side_effect = HTTPException(status_code=404, detail="Categoría no encontrada")
        r = app_client.put(
            "/api/maint/v2/config/field-templates/9999",
            json={"fields": [{"key": "obs", "label": "Obs", "type": "text"}]},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_put_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": []},
        )
        assert r.status_code == 401

    def test_put_cookie_invalida_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": []},
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401

    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_data_response_contiene_category_id(self, mock_upd, app_client, admin_headers):
        """data en respuesta 200 incluye category_id del recurso actualizado."""
        mock_upd.return_value = _fake_category(category_id=3, code="MECA", name="Mecánica")
        r = app_client.put(
            "/api/maint/v2/config/field-templates/3",
            json={"fields": []},
            headers=admin_headers,
        )
        assert r.json()["data"]["category_id"] == 3

    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_put_multiple_campos_validos(self, mock_upd, app_client, admin_headers):
        """PUT con múltiples campos válidos → 200."""
        mock_upd.return_value = _fake_category(category_id=7, field_template=[
            {"key": "nombre", "label": "Nombre", "type": "text", "required": True},
            {"key": "nivel", "label": "Nivel", "type": "select",
             "options": ["Bajo", "Medio", "Alto"], "required": False},
        ])
        r = app_client.put(
            "/api/maint/v2/config/field-templates/7",
            json={"fields": [
                {"key": "nombre", "label": "Nombre", "type": "text", "required": True},
                {"key": "nivel", "label": "Nivel", "type": "select",
                 "options": ["Bajo", "Medio", "Alto"]},
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

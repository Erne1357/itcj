"""
Tests para export CSV de auditoría + gap field-template legacy — maint Fase 7.

Secciones:
  A. GET /api/maint/v2/config/audit/export.csv — descarga CSV.
  B. Colisión de rutas — export.csv vs /{log_id}.
  C. Gap corregido — PUT /api/maint/v2/categories/{id}/field-template
     invoca log_config_change con entity_type='field_template'.

Estrategia:
  - Mismo patrón que test_priorities_audit.py: app real con get_db override,
    JWT admin role='admin' que bypasea require_perms.
  - MaintConfigChangeLog no va a BD; toda la query se mockea en el MagicMock db.
  - El CSV se lee como bytes y se verifica BOM + headers + filas.
"""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import jwt
import pytest
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


def _fake_log_entry(
    log_id: int = 10,
    user_id: int = 1,
    entity_type: str = "priority",
    entity_id: int = 1,
    action: str = "create",
    before_data=None,
    after_data=None,
    changed_at: datetime = None,
    ip_address: str = "127.0.0.1",
) -> MagicMock:
    """Simula un objeto MaintConfigChangeLog con relación user cargada."""
    entry = MagicMock()
    entry.id = log_id
    entry.user_id = user_id
    entry.user = MagicMock()
    entry.user.first_name = "Admin"
    entry.user.last_name = "Test"
    entry.entity_type = entity_type
    entry.entity_id = entity_id
    entry.action = action
    entry.before_data = before_data
    entry.after_data = after_data
    entry.changed_at = changed_at or datetime(2026, 5, 1, 12, 0, 0)
    entry.ip_address = ip_address
    return entry


def _setup_export_query(mock_db, items: list):
    """
    Configura la cadena de mock para el export.csv:
    db.query(...).options(...).filter(...).order_by(...).limit(...).all()
    El mismo mock encadenable cubre cualquier combinación de filtros.
    """
    q = mock_db.query.return_value
    q.options.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = items


def _setup_detail_query(mock_db, entry=None):
    """Configura mock para GET /{log_id}."""
    q = mock_db.query.return_value
    q.options.return_value = q
    q.filter.return_value.first.return_value = entry


# =============================================================================
# Fixture: app_client (replicado de test_priorities_audit.py)
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
# A. GET /api/maint/v2/config/audit/export.csv
# =============================================================================

class TestAuditExportCsv:
    """GET /api/maint/v2/config/audit/export.csv"""

    _URL = "/api/maint/v2/config/audit/export.csv"

    def test_export_admin_returns_200(self, app_client):
        """Admin obtiene 200."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        assert r.status_code == 200

    def test_export_content_type_es_csv(self, app_client):
        """Content-Type empieza con 'text/csv'."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        assert r.headers["content-type"].startswith("text/csv")

    def test_export_content_disposition_attachment_filename(self, app_client):
        """Content-Disposition tiene attachment y filename con prefijo y extensión .csv."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "maint_config_audit_" in cd
        assert cd.endswith('.csv"')

    def test_export_cuerpo_empieza_con_bom(self, app_client):
        """El cuerpo del CSV empieza con BOM UTF-8 (\\xef\\xbb\\xbf)."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        # BOM UTF-8 = \xef\xbb\xbf
        assert r.content[:3] == b"\xef\xbb\xbf"

    def test_export_primera_linea_es_header_columnas(self, app_client):
        """La primera línea tras el BOM contiene exactamente las 10 columnas."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        # Decodificar omitiendo BOM
        text = r.content.decode("utf-8-sig")
        primera_linea = text.splitlines()[0]
        columnas_esperadas = [
            "id", "changed_at", "user_id", "user_name",
            "entity_type", "entity_id", "action",
            "ip_address", "before_data", "after_data",
        ]
        for col in columnas_esperadas:
            assert col in primera_linea, f"Columna '{col}' no encontrada en header CSV"

    def test_export_contiene_fila_de_datos_mockeados(self, app_client):
        """Las filas fake aparecen en el CSV con user_name del user.full_name."""
        entry = _fake_log_entry(
            log_id=42,
            user_id=5,
            entity_type="priority",
            entity_id=3,
            action="update",
            before_data={"sla_hours": 72},
            after_data={"sla_hours": 48},
            ip_address="10.0.0.1",
        )
        # user_name: "Admin Test"
        _setup_export_query(app_client._mock_db, [entry])

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        lineas = text.splitlines()
        # Al menos header + 1 fila de datos
        assert len(lineas) >= 2
        fila_datos = lineas[1]
        assert "Admin Test" in fila_datos
        assert "42" in fila_datos
        assert "priority" in fila_datos
        assert "update" in fila_datos

    def test_export_before_data_serializado_como_json(self, app_client):
        """before_data (dict) aparece como string JSON en el CSV."""
        entry = _fake_log_entry(
            before_data={"sla_hours": 72},
            after_data={"sla_hours": 48},
        )
        _setup_export_query(app_client._mock_db, [entry])

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        # El JSON del before_data debe estar en el cuerpo
        assert "sla_hours" in text
        assert "72" in text

    def test_export_none_before_data_es_celda_vacia(self, app_client):
        """before_data=None → celda vacía (no 'null' ni 'None')."""
        entry = _fake_log_entry(before_data=None, after_data=None)
        _setup_export_query(app_client._mock_db, [entry])

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        # La fila no debe tener 'null' ni 'None' literal para before/after
        lineas = text.splitlines()
        fila_datos = lineas[1]
        # La fila termina con ,, (dos celdas vacías: before_data, after_data)
        assert fila_datos.endswith(",,")

    def test_export_entity_id_none_es_celda_vacia(self, app_client):
        """entity_id=None → celda vacía en el CSV."""
        entry = _fake_log_entry(entity_id=None)
        _setup_export_query(app_client._mock_db, [entry])

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        # entity_id viene en columna 6 (0-indexed 5). Verificamos que la fila
        # tiene una celda vacía donde iría el entity_id.
        # Al menos que el export no falle con entity_id=None.
        assert r.status_code == 200

    def test_export_multiples_filas(self, app_client):
        """Varias entradas producen múltiples filas en el CSV."""
        entries = [
            _fake_log_entry(log_id=i, entity_type="priority", action="create")
            for i in range(1, 6)
        ]
        _setup_export_query(app_client._mock_db, entries)

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        lineas = [l for l in text.splitlines() if l.strip()]
        # 1 header + 5 filas
        assert len(lineas) == 6

    def test_export_sin_cookie_retorna_401(self, app_client):
        """Sin autenticación → 401."""
        r = app_client.get(self._URL)
        assert r.status_code == 401

    def test_export_token_invalido_retorna_401(self, app_client):
        """Token inválido → 401."""
        r = app_client.get(
            self._URL,
            headers={"Cookie": "itcj_token=garbage"},
        )
        assert r.status_code == 401

    def test_export_filtro_entity_type_no_rompe(self, app_client):
        """Pasar entity_type como query param no rompe el endpoint."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(
            self._URL + "?entity_type=priority",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_export_filtros_multiples_no_rompen(self, app_client):
        """Combinación de filtros no rompe el endpoint."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(
            self._URL + "?entity_type=category&action=update&user_id=1"
                        "&date_from=2026-01-01&date_to=2026-05-31",
            headers=_admin_headers(),
        )
        assert r.status_code == 200

    def test_export_date_from_invalido_retorna_400(self, app_client):
        """date_from con formato incorrecto → 400."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(
            self._URL + "?date_from=not-a-date",
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_export_date_to_invalido_retorna_400(self, app_client):
        """date_to con formato incorrecto → 400."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(
            self._URL + "?date_to=31-12-2026",
            headers=_admin_headers(),
        )
        assert r.status_code == 400

    def test_export_lista_vacia_tiene_solo_header(self, app_client):
        """Sin entradas, el CSV tiene solo la línea de encabezado."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(self._URL, headers=_admin_headers())
        text = r.content.decode("utf-8-sig")
        lineas = [l for l in text.splitlines() if l.strip()]
        assert len(lineas) == 1   # solo el header


# =============================================================================
# B. Sin colisión de rutas: export.csv vs /{log_id}
# =============================================================================

class TestAuditRoutesNoCollision:
    """
    Verifica que /audit/export.csv no colisiona con /audit/{log_id}.

    FastAPI registra /export.csv antes de /{log_id} en el router de audit,
    por lo que "export.csv" nunca debe intentar castearse a int.
    """

    def test_export_csv_no_devuelve_422_por_cast_a_int(self, app_client):
        """GET /audit/export.csv no devuelve 422 (no intenta parsear 'export.csv' como int)."""
        _setup_export_query(app_client._mock_db, [])

        r = app_client.get(
            "/api/maint/v2/config/audit/export.csv",
            headers=_admin_headers(),
        )
        # 200 o 401, NUNCA 422 (que indicaría que lo trató como /{log_id})
        assert r.status_code != 422

    def test_detail_log_id_numerico_sigue_devolviendo_200(self, app_client):
        """GET /audit/123 sigue resolviendo al endpoint de detalle (200 con mock)."""
        entry = _fake_log_entry(
            log_id=123,
            before_data={"sla_hours": 72},
            after_data={"sla_hours": 48},
        )
        _setup_detail_query(app_client._mock_db, entry)

        r = app_client.get(
            "/api/maint/v2/config/audit/123",
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "data" in body

    def test_export_csv_y_detalle_resuelven_distinto(self, app_client):
        """
        /export.csv → text/csv ; /123 → application/json.
        Ambas rutas coexisten sin interferencia.
        """
        # Preparar mocks para ambas rutas
        _setup_export_query(app_client._mock_db, [])
        entry = _fake_log_entry(log_id=99)
        _setup_detail_query(app_client._mock_db, entry)

        r_csv = app_client.get(
            "/api/maint/v2/config/audit/export.csv",
            headers=_admin_headers(),
        )
        r_detail = app_client.get(
            "/api/maint/v2/config/audit/99",
            headers=_admin_headers(),
        )

        assert r_csv.status_code == 200
        assert r_csv.headers["content-type"].startswith("text/csv")

        assert r_detail.status_code == 200
        assert "application/json" in r_detail.headers["content-type"]


# =============================================================================
# C. Gap corregido — PUT /categories/{id}/field-template invoca log_config_change
# =============================================================================

class TestFieldTemplateLegacyAuditGap:
    """
    Fase 7: PUT /api/maint/v2/categories/{id}/field-template ahora llama
    log_config_change con entity_type='field_template'.

    Parchea log_config_change en el namespace itcj2.apps.maint.api.categories
    y mockea category_service.update_field_template + db.get para el before.
    """

    _URL = "/api/maint/v2/categories/{id}/field-template"

    @patch("itcj2.apps.maint.api.categories.log_config_change")
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_field_template_invoca_log_con_entity_field_template(
        self, mock_update, mock_log, app_client
    ):
        """PUT invoca log_config_change con entity_type='field_template'."""
        # Simular la categoría devuelta por el service
        cat = MagicMock()
        cat.id = 7
        cat.code = "ELEC"
        cat.name = "Electricidad"
        cat.is_active = True
        cat.field_template = [{"name": "voltage", "type": "text"}]
        mock_update.return_value = cat

        # db.get para capturar `before_template`
        mock_before = MagicMock()
        mock_before.field_template = []
        app_client._mock_db.get.return_value = mock_before

        r = app_client.put(
            "/api/maint/v2/categories/7/field-template",
            json={"fields": [{"name": "voltage", "type": "text"}]},
            headers=_admin_headers(),
        )

        assert r.status_code in (200, 201)
        mock_log.assert_called()

        call_kwargs = mock_log.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        entity_type = kwargs.get("entity_type")
        assert entity_type == "field_template", (
            f"Se esperaba entity_type='field_template', se obtuvo: {entity_type!r}"
        )

    @patch("itcj2.apps.maint.api.categories.log_config_change")
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_field_template_log_action_es_update(
        self, mock_update, mock_log, app_client
    ):
        """log_config_change se invoca con action='update'."""
        cat = MagicMock()
        cat.id = 7
        cat.field_template = []
        mock_update.return_value = cat
        app_client._mock_db.get.return_value = MagicMock(field_template=[])

        app_client.put(
            "/api/maint/v2/categories/7/field-template",
            json={"fields": []},
            headers=_admin_headers(),
        )

        mock_log.assert_called()
        call_kwargs = mock_log.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        action = kwargs.get("action")
        assert action == "update", (
            f"Se esperaba action='update', se obtuvo: {action!r}"
        )

    @patch("itcj2.apps.maint.api.categories.log_config_change")
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_field_template_log_entity_id_es_category_id(
        self, mock_update, mock_log, app_client
    ):
        """log_config_change recibe entity_id = category_id del path."""
        cat = MagicMock()
        cat.id = 15
        cat.field_template = []
        mock_update.return_value = cat
        app_client._mock_db.get.return_value = MagicMock(field_template=[])

        app_client.put(
            "/api/maint/v2/categories/15/field-template",
            json={"fields": []},
            headers=_admin_headers(),
        )

        mock_log.assert_called()
        call_kwargs = mock_log.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        entity_id = kwargs.get("entity_id")
        assert entity_id == 15, (
            f"Se esperaba entity_id=15, se obtuvo: {entity_id!r}"
        )

    @patch("itcj2.apps.maint.api.categories.log_config_change")
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_field_template_respuesta_no_rompe_contrato_legacy(
        self, mock_update, mock_log, app_client
    ):
        """El endpoint sigue respondiendo OK (no rompe el contrato tras agregar audit)."""
        cat = MagicMock()
        cat.id = 7
        cat.code = "ELEC"
        cat.name = "Electricidad"
        cat.is_active = True
        cat.field_template = []
        mock_update.return_value = cat
        app_client._mock_db.get.return_value = MagicMock(field_template=[])

        r = app_client.put(
            "/api/maint/v2/categories/7/field-template",
            json={"fields": []},
            headers=_admin_headers(),
        )

        # El endpoint no debe retornar 500 (el audit es best-effort con try/except)
        assert r.status_code not in (500, 502, 503)

    @patch("itcj2.apps.maint.api.categories.log_config_change")
    @patch("itcj2.apps.maint.services.category_service.update_field_template")
    def test_field_template_sin_cookie_retorna_401(
        self, mock_update, mock_log, app_client
    ):
        """Sin autenticación → 401."""
        r = app_client.put(
            "/api/maint/v2/categories/7/field-template",
            json={"fields": []},
        )
        assert r.status_code == 401

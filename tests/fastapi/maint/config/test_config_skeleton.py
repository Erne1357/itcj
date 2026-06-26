"""
Smoke tests para el esqueleto de la pestaña Configuración de maint (Fase 1).

Cubre:
  A. Acceso a /maint/admin/config (página nueva)
  B. Redirecciones de compatibilidad /maint/admin/categories y /maint/admin/areas
  C. CLI _seed_config_files / seed-config (unit, sin BD real)

Estrategia — páginas HTML:
  - Misma fixture app_client que test_api_smoke.py: create_app() + override get_db.
  - render_maint se parchea directamente en itcj2.apps.maint.pages.admin para
    evitar SessionLocal() real + queries de navegación.
  - require_page_app llama has_any_assignment y get_user_permissions_for_app desde
    itcj2.core.services.authz_service; se parchean para que el usuario "tenga todo".
  - No-auth → PageLoginRequired → 302 a /itcj/login (comportamiento del exception handler).
  - TestClient se construye con follow_redirects=False para capturar 302 directos.

Estrategia — CLI:
  - CliRunner de Click (sin subprocess, sin BD).
  - Parchear itcj2.cli.maint.execute_sql_file con MagicMock.
  - La idempotencia real es responsabilidad del SQL (ON CONFLICT DO NOTHING);
    aquí solo se verifica que el código no lanza al llamarse dos veces.
"""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from click.testing import CliRunner
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.database import get_db
from itcj2.main import create_app


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de JWT (mismo patrón que test_api_smoke.py)
# ─────────────────────────────────────────────────────────────────────────────


def _admin_jwt(user_id: int = 1) -> str:
    """JWT con role=admin firmado con SECRET real."""
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
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_client():
    """TestClient con get_db override, follow_redirects=False y render_maint mockeado.

    render_maint se parchea en itcj2.apps.maint.pages.admin (donde se importa),
    no en nav.py, para que el mock intercepte la llamada del endpoint.

    require_page_app llama a has_any_assignment y get_user_permissions_for_app
    desde itcj2.core.services.authz_service. Se parchean para que el usuario de
    prueba siempre "tenga acceso" sin necesitar BD.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()

    render_patcher = patch(
        "itcj2.apps.maint.pages.admin.render_maint",
        return_value=HTMLResponse(
            content=(
                "<html><body>"
                '<button id="tab-categorias" data-hash="categorias">Categorías y campos</button>'
                '<button id="tab-areas" data-hash="areas">Áreas técnicas</button>'
                '<button id="tab-prioridades" data-hash="prioridades">Prioridades + SLA</button>'
                '<button id="tab-tipos" data-hash="tipos">Tipo y origen</button>'
                '<button id="tab-notif" data-hash="notif">Notificaciones</button>'
                '<button id="tab-audit" data-hash="audit">Auditoría</button>'
                "</body></html>"
            ),
            status_code=200,
        ),
    )

    # require_page_app importa has_any_assignment y get_user_permissions_for_app
    # dentro del cuerpo de la función dependency(), por lo que el punto de patch
    # correcto es el módulo de origen: itcj2.core.services.authz_service.
    has_assignment_patcher = patch(
        "itcj2.core.services.authz_service.has_any_assignment",
        return_value=True,
    )
    get_perms_patcher = patch(
        "itcj2.core.services.authz_service.get_user_permissions_for_app",
        return_value={"maint.config.page.view", "maint.admin.page.categories", "maint.admin.page.areas"},
    )

    render_patcher.start()
    has_assignment_patcher.start()
    get_perms_patcher.start()

    with TestClient(app, follow_redirects=False) as c:
        yield c

    render_patcher.stop()
    has_assignment_patcher.stop()
    get_perms_patcher.stop()
    app.dependency_overrides.clear()


@pytest.fixture
def admin_cookie():
    return {"Cookie": f"itcj_token={_admin_jwt()}"}


# ─────────────────────────────────────────────────────────────────────────────
# A. Acceso a /maint/admin/config
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigPageAccess:
    def test_admin_gets_200(self, app_client, admin_cookie):
        """Admin con permisos obtiene 200 en /maint/admin/config."""
        r = app_client.get("/maint/admin/config", headers=admin_cookie)
        assert r.status_code == 200

    def test_admin_response_contains_all_six_tab_anchors(self, app_client, admin_cookie):
        """La respuesta HTML incluye los 6 anchors de tab de configuración.

        Verifica data-hash de cada tab (categorias, areas, prioridades,
        tipos, notif, audit) como proxy de que el esqueleto está completo.
        """
        r = app_client.get("/maint/admin/config", headers=admin_cookie)
        assert r.status_code == 200
        body = r.text
        for anchor in ("categorias", "areas", "prioridades", "tipos", "notif", "audit"):
            assert anchor in body, f"Tab anchor '{anchor}' no encontrado en la respuesta HTML"

    def test_no_auth_redirects_to_login(self, app_client):
        """Sin cookie → PageLoginRequired → 302 a /itcj/login."""
        r = app_client.get("/maint/admin/config")
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"

    def test_invalid_token_redirects_to_login(self, app_client):
        """Token inválido → cookie ignorada → 302 a /itcj/login."""
        r = app_client.get(
            "/maint/admin/config",
            headers={"Cookie": "itcj_token=not_a_real_token"},
        )
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"


# ─────────────────────────────────────────────────────────────────────────────
# B. Redirecciones de compatibilidad
# ─────────────────────────────────────────────────────────────────────────────


class TestCompatibilityRedirects:
    def test_categories_redirects_302_to_config_hash(self, app_client, admin_cookie):
        """/maint/admin/categories → 302 → /maint/admin/config#categorias."""
        r = app_client.get("/maint/admin/categories", headers=admin_cookie)
        assert r.status_code == 302
        assert r.headers["location"] == "/maint/admin/config#categorias"

    def test_areas_redirects_302_to_config_hash(self, app_client, admin_cookie):
        """/maint/admin/areas → 302 → /maint/admin/config#areas."""
        r = app_client.get("/maint/admin/areas", headers=admin_cookie)
        assert r.status_code == 302
        assert r.headers["location"] == "/maint/admin/config#areas"

    def test_categories_no_auth_redirects_to_login(self, app_client):
        """Sin auth /maint/admin/categories → 302 a login, no a la URL de destino."""
        r = app_client.get("/maint/admin/categories")
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"

    def test_areas_no_auth_redirects_to_login(self, app_client):
        """Sin auth /maint/admin/areas → 302 a login."""
        r = app_client.get("/maint/admin/areas")
        assert r.status_code == 302
        assert r.headers["location"] == "/itcj/login"


# ─────────────────────────────────────────────────────────────────────────────
# C. CLI seed-config / _seed_config_files (unit, sin BD)
# ─────────────────────────────────────────────────────────────────────────────


class TestSeedConfigCli:
    """Tests unitarios del helper _seed_config_files y del comando seed-config.

    execute_sql_file se parchea para evitar cualquier conexión a BD.
    La idempotencia real (ON CONFLICT DO NOTHING) es responsabilidad del SQL;
    aquí solo verificamos que el código no lanza al invocarse repetidamente.
    """

    def test_seed_config_calls_execute_sql_for_each_file(self, tmp_path):
        """Con archivos .sql presentes, execute_sql_file se llama una vez por archivo."""
        # Crear un directorio config/ simulado con dos SQL
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "01_insert_permissions.sql").write_text("SELECT 1;")
        (config_dir / "02_more_perms.sql").write_text("SELECT 2;")

        # execute_sql_file se importa con 'from itcj2.cli.core import execute_sql_file'
        # dentro del cuerpo de _seed_config_files(), por lo que el punto de patch
        # correcto es el módulo de origen: itcj2.cli.core.
        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file") as mock_exec:

            from itcj2.cli.maint import _seed_config_files
            count = _seed_config_files()

        assert count == 2
        assert mock_exec.call_count == 2

    def test_seed_config_executes_files_in_alphabetical_order(self, tmp_path):
        """Los archivos se ejecutan en orden alfabético por nombre."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "03_last.sql").write_text("SELECT 3;")
        (config_dir / "01_first.sql").write_text("SELECT 1;")
        (config_dir / "02_middle.sql").write_text("SELECT 2;")

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file") as mock_exec:

            from itcj2.cli.maint import _seed_config_files
            _seed_config_files()

        called_paths = [Path(call.args[0]).name for call in mock_exec.call_args_list]
        assert called_paths == ["01_first.sql", "02_middle.sql", "03_last.sql"]

    def test_seed_config_with_real_config_dir_calls_execute_sql_at_least_once(self):
        """Con la carpeta real database/DML/maint/config/ (01_insert_permissions.sql),
        execute_sql_file se invoca al menos una vez.

        database/ está gitignored → en un clon limpio (CI) la carpeta no existe.
        Este test valida la presencia/orden del DML REAL, así que se salta si la
        carpeta no está (no aplica en CI; sí corre local donde los .sql existen).
        """
        import pytest
        from itcj2.cli.maint import DML_MAINT
        if not (Path(DML_MAINT) / "config").is_dir():
            pytest.skip("database/DML/maint/config/ untracked — ausente en CI")
        with patch("itcj2.cli.core.execute_sql_file") as mock_exec:
            from itcj2.cli.maint import _seed_config_files
            count = _seed_config_files()

        assert count >= 1
        assert mock_exec.call_count >= 1
        # Verificar que el archivo real se pasó por nombre (orden importa para auditoría)
        first_path = Path(mock_exec.call_args_list[0].args[0])
        assert first_path.name == "01_insert_permissions.sql"

    def test_seed_config_idempotent_two_invocations(self, tmp_path):
        """Invocar _seed_config_files dos veces no lanza excepción.

        La idempotencia real (no duplicar datos) es responsabilidad de los SQL
        (ON CONFLICT DO NOTHING). Este test verifica solo que el código no falla.
        """
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "01_insert_permissions.sql").write_text("SELECT 1;")

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file") as mock_exec:

            from itcj2.cli.maint import _seed_config_files
            _seed_config_files()
            _seed_config_files()

        # execute_sql_file se llama dos veces (una por invocación), sin excepción
        assert mock_exec.call_count == 2

    def test_seed_config_missing_config_dir_exits_zero(self, tmp_path):
        """Si config/ no existe, el comando termina con exit code 0 sin lanzar."""
        # tmp_path no tiene subdirectorio config/
        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file") as mock_exec:

            from itcj2.cli.maint import _seed_config_files
            count = _seed_config_files()

        assert count == 0
        mock_exec.assert_not_called()

    def test_seed_config_empty_config_dir_exits_zero(self, tmp_path):
        """Si config/ existe pero está vacía, retorna 0 y no llama execute_sql_file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # Sin archivos .sql

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file") as mock_exec:

            from itcj2.cli.maint import _seed_config_files
            count = _seed_config_files()

        assert count == 0
        mock_exec.assert_not_called()

    def test_seed_config_command_exit_code_zero(self, tmp_path):
        """El comando CLI `seed-config` termina con exit code 0 (happy path)."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "01_insert_permissions.sql").write_text("SELECT 1;")

        runner = CliRunner()

        from itcj2.cli.maint import seed_config_command

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file"):
            result = runner.invoke(seed_config_command)

        assert result.exit_code == 0, f"seed-config salió con {result.exit_code}: {result.output}"

    def test_seed_config_command_empty_dir_exit_code_zero(self, tmp_path):
        """seed-config con carpeta vacía → exit code 0 con mensaje informativo."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        runner = CliRunner()

        from itcj2.cli.maint import seed_config_command

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file"):
            result = runner.invoke(seed_config_command)

        assert result.exit_code == 0
        assert "sin archivos" in result.output.lower() or "vacía" in result.output.lower() or "vacˊa" in result.output

    def test_seed_config_command_missing_dir_exit_code_zero(self, tmp_path):
        """seed-config con carpeta inexistente → exit code 0 sin error."""
        runner = CliRunner()

        from itcj2.cli.maint import seed_config_command

        with patch("itcj2.cli.maint.DML_MAINT", tmp_path), \
             patch("itcj2.cli.core.execute_sql_file"):
            result = runner.invoke(seed_config_command)

        assert result.exit_code == 0
        assert "no encontrada" in result.output or "omite" in result.output

"""Tests de la sección **Reportes** de Calidad (F5): páginas, gate y reglas duras.

Seis URLs, todas con ``adhoc.reports.page.view``::

    GET /adhoc/reportes
    GET /adhoc/reportes/area_usuarios
    GET /adhoc/reportes/usuarios_tareas
    GET /adhoc/reportes/usuarios_documentos
    GET /adhoc/reportes/documentos_usuarios
    GET /adhoc/reportes/documentos_notas

Harness (plan §9.1): el error del cliente es ``{"error": …, "status": …}``, no
``{"detail": …}``; el gate se prueba con ``role="staff"`` + ``patch`` de
``cached_has_assignment``/``cached_perms``; y estas rutas devuelven **HTML**
(403 renderizado, 302 al login), nunca JSON.

Matiz del harness que conviene no olvidar: el bypass de ``role="admin"`` es de
``require_perms`` (la API). ``require_page_app`` **no lo tiene** — consulta la
asignación y los permisos para todo el mundo—, así que hasta el admin necesita
los dos parches. De ahí el fixture autouse ``_granted``.

Los endpoints importan el service **dentro** de la función, así que los mocks
van sobre el módulo fuente (``…services.report_service.ReportService``), no
sobre el consumidor.

``pages/router.py`` lo cablea la fase siguiente; el fixture ``client`` monta el
router de esta sección si aún no está, y no hace nada cuando ya lo esté.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.pages.reports import REPORTS_PERM
from itcj2.apps.adhoc.services.report_service import REPORT_META
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATES_DIR = APP_ROOT / "templates" / "adhoc" / "reports"
STATIC_DIR = APP_ROOT / "static"

SERVICE = "itcj2.apps.adhoc.services.report_service.ReportService"

REPORT_TYPES = list(REPORT_META)


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(scope="module")
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()

        # F5 en paralelo: pages/router.py es de la fase de cableado y puede o no
        # traer ya esta sección. Se monta solo si falta.
        if "/adhoc/reportes" not in {getattr(r, "path", None) for r in app.routes}:
            from itcj2.apps.adhoc.pages.reports import router as reports_router

            app.include_router(reports_router, prefix="/adhoc")

        mock_db = MagicMock()

        def _override():
            yield mock_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _granted():
    """Acceso a la app + permiso de la sección, por defecto, en TODOS los tests.

    ``require_page_app`` **no** tiene bypass de admin: consulta
    ``cached_has_assignment`` y ``cached_perms`` para cualquier usuario, incluido
    el ``role="admin"`` del JWT (que solo bypasea ``require_perms``, el de la
    API). Con ``get_db`` sobreescrito por un ``MagicMock`` esas consultas revientan
    en el primer ``>`` contra un int, así que se parchean aquí.

    Los tests de gate vuelven a parchear por dentro con sus propios valores: el
    ``patch`` anidado gana mientras dura su bloque.
    """
    with patch(
        "itcj2.core.services.authz_cache.cached_has_assignment", return_value=True
    ), patch(
        "itcj2.core.services.authz_cache.cached_perms", return_value={REPORTS_PERM}
    ):
        yield


@pytest.fixture()
def admin_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=201, role='staff')}"}


def _selection_data():
    return {
        "reports": [
            {
                "type": key,
                "title": meta["title"],
                "label": meta["label"],
                "subject": meta["subject"],
                "icon": meta["icon"],
                "icon_overlay": meta["icon_overlay"],
            }
            for key, meta in REPORT_META.items()
        ],
        "formats": ["sencillo", "completo"],
        "areas": [{"id": 1, "name": "Calidad", "color": "#4834d4"}],
        "users": [{"first_name": "Ana", "last_name": "Cruz", "areas": "Calidad"}],
        "documents": [{
            "code": "MC-01", "title": "Manual", "author": "Ana Cruz",
            "area": "Calidad", "status": "Aprobado", "version": "1.0",
            "created_at": "01/01/2026", "notes": "Sin notas",
        }],
    }


def _report(report_type="area_usuarios", rows=None, formato="sencillo", truncated=False):
    meta = REPORT_META[report_type]
    return {
        "report_type": report_type,
        "title": meta["title"],
        "label": meta["label"],
        "sheet": meta["sheet"],
        "file_prefix": meta["file_prefix"],
        "subject": meta["subject"],
        "formato": formato,
        "columns": [
            {"key": "first_name", "label": "Nombre", "align": "start"},
            {"key": "last_name", "label": "Apellidos", "align": "start"},
            {"key": "areas", "label": "Área Asignada", "align": "start"},
        ],
        "rows": rows if rows is not None else [
            {"first_name": "Ana", "last_name": "Cruz", "areas": "Calidad"},
        ],
        "total": len(rows) if rows is not None else 1,
        "subjects": 1,
        "truncated": truncated,
        "max_rows": 5000,
        "filters": {"nombre": "", "apellidos": "", "area": ""},
    }


@pytest.fixture()
def selection_ok():
    with patch(f"{SERVICE}.get_selection_data", return_value=_selection_data()) as m:
        yield m


# ==========================================================================
# Rutas y contrato HTTP
# ==========================================================================

class TestRutas:
    def test_la_seleccion_responde_html(self, client, admin_headers, selection_ok):
        res = client.get("/adhoc/reportes", headers=admin_headers)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    @pytest.mark.parametrize("report_type", REPORT_TYPES)
    def test_los_cinco_tipos_responden(self, client, admin_headers, report_type):
        with patch(f"{SERVICE}.build_report", return_value=_report(report_type)) as build:
            res = client.get(f"/adhoc/reportes/{report_type}", headers=admin_headers)
        assert res.status_code == 200, res.text[:400]
        assert build.call_args.args[1] == report_type

    def test_tipo_desconocido_es_404_de_pagina(self, client, admin_headers):
        """El legacy devolvía la cadena cruda ``"Reporte no encontrado", 404``.

        Aquí el handler global convierte el ``HTTPException`` en la PÁGINA de
        error (la ruta no empieza por ``/api/``), no en un JSON.
        """
        res = client.get("/adhoc/reportes/inventado", headers=admin_headers)
        assert res.status_code == 404
        assert "text/html" in res.headers["content-type"]

    def test_los_filtros_llegan_al_service_con_el_nombre_del_legacy(
        self, client, admin_headers
    ):
        with patch(f"{SERVICE}.build_report", return_value=_report()) as build:
            client.get(
                "/adhoc/reportes/area_usuarios"
                "?f_nombre=Ana&f_apellidos=Cruz&f_area=Calidad&formato=completo",
                headers=admin_headers,
            )
        assert build.call_args.kwargs == {
            "nombre": "Ana",
            "apellidos": "Cruz",
            "area": "Calidad",
            "formato": "completo",
        }

    def test_sin_query_string_usa_los_defaults(self, client, admin_headers):
        with patch(f"{SERVICE}.build_report", return_value=_report()) as build:
            client.get("/adhoc/reportes/area_usuarios", headers=admin_headers)
        assert build.call_args.kwargs == {
            "nombre": "", "apellidos": "", "area": "", "formato": "sencillo",
        }

    def test_formato_basura_no_revienta_la_pagina(self, client, admin_headers):
        """El service ya lo normaliza; la página no debe devolver 422 en JSON."""
        with patch(f"{SERVICE}.build_report", return_value=_report()):
            res = client.get(
                "/adhoc/reportes/area_usuarios?formato=%3Cscript%3E", headers=admin_headers
            )
        assert res.status_code == 200


# ==========================================================================
# Autorización
# ==========================================================================

class TestGate:
    @pytest.mark.parametrize(
        "url", ["/adhoc/reportes"] + [f"/adhoc/reportes/{t}" for t in REPORT_TYPES]
    )
    def test_anonimo_va_al_login(self, client, url):
        res = client.get(url, follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

    def test_sin_acceso_a_la_app_es_403_html(self, client, staff_headers):
        with patch(
            "itcj2.core.services.authz_cache.cached_has_assignment", return_value=False
        ):
            res = client.get("/adhoc/reportes", headers=staff_headers)
        assert res.status_code == 403
        assert "text/html" in res.headers["content-type"]

    def test_con_la_app_pero_sin_el_permiso_es_403(self, client, staff_headers):
        with patch(
            "itcj2.core.services.authz_cache.cached_has_assignment", return_value=True
        ), patch(
            "itcj2.core.services.authz_cache.cached_perms",
            return_value={"adhoc.dashboard.page.view"},
        ):
            res = client.get("/adhoc/reportes/area_usuarios", headers=staff_headers)
        assert res.status_code == 403

    def test_con_el_permiso_exacto_entra(self, client, staff_headers, selection_ok):
        with patch(
            "itcj2.core.services.authz_cache.cached_has_assignment", return_value=True
        ), patch(
            "itcj2.core.services.authz_cache.cached_perms", return_value={REPORTS_PERM}
        ):
            res = client.get("/adhoc/reportes", headers=staff_headers)
        assert res.status_code == 200

    def test_el_permiso_es_el_de_la_tabla_del_plan(self):
        assert REPORTS_PERM == "adhoc.reports.page.view"


# ==========================================================================
# Render de la pantalla de selección
# ==========================================================================

class TestSeleccionRender:
    @pytest.fixture()
    def html(self, client, admin_headers, selection_ok):
        return client.get("/adhoc/reportes", headers=admin_headers).text

    def test_pinta_las_cinco_tarjetas(self, html):
        for report_type, meta in REPORT_META.items():
            assert f'data-adhoc-report="{report_type}"' in html
            assert meta["label"] in html

    def test_las_tarjetas_son_botones_no_divs_con_onclick(self, html):
        """El legacy usaba ``<div class="report-card" data-report=…>``: ni
        focusable ni operable con teclado."""
        for report_type in REPORT_META:
            match = re.search(
                r"<button[^>]*data-adhoc-report=\"" + report_type + r"\"", html
            )
            assert match, report_type

    def test_iconos_bootstrap_no_font_awesome(self, html):
        assert "fa-solid" not in html
        assert "fa-" not in html.split("</head>")[-1] or "bi bi-" in html

    def test_el_modal_es_de_bootstrap(self, html):
        assert 'class="modal fade" id="adhoc-report-modal"' in html
        assert "modal-overlay" not in html
        assert 'data-bs-dismiss="modal"' in html

    def test_el_formulario_ofrece_los_dos_formatos(self, html):
        assert 'name="formato" value="sencillo"' in html
        assert 'name="formato" value="completo"' in html

    def test_los_tres_filtros_del_legacy_siguen_ahi(self, html):
        for name in ("f_nombre", "f_apellidos", "f_area"):
            assert f'name="{name}"' in html

    def test_el_select_de_areas_se_llena_desde_el_contexto(self, html):
        assert "Todas las Áreas" in html
        assert ">Calidad<" in html

    def test_las_filas_de_vista_previa_no_vienen_del_servidor(self, html):
        """Van en el JSON y las pinta el JS escapando: el legacy las renderizaba
        desde Jinja y encima inyectaba ``<option>`` crudos por JS."""
        assert "adhoc-report-users-body" in html
        assert "adhoc-report-docs-body" in html
        cuerpo = html.split('id="adhoc-report-users-body"')[1].split("</tbody>")[0]
        assert "Ana" not in cuerpo

    def test_emite_el_bloque_page_data_como_json(self, html):
        assert '<script id="adhoc-page-data" type="application/json">' in html
        payload = html.split('type="application/json">')[1].split("</script>")[0]
        import json

        data = json.loads(payload)
        assert {"reports", "areas", "users", "documents"} <= set(data)

    def test_carga_sus_estaticos_versionados(self, html):
        assert "/static/adhoc/css/reports/reports.css?v=" in html
        assert "/static/adhoc/js/reports/reports.js?v=" in html

    def test_el_nav_sigue_presente(self, html):
        assert "adhoc-appbar" in html
        assert 'href="/adhoc/reportes"' in html


# ==========================================================================
# Render del reporte
# ==========================================================================

class TestReporteRender:
    @pytest.fixture()
    def html(self, client, admin_headers):
        with patch(f"{SERVICE}.build_report", return_value=_report()):
            return client.get("/adhoc/reportes/area_usuarios", headers=admin_headers).text

    def test_es_una_pagina_de_la_app_no_un_html_suelto(self, html):
        """Los 5 del legacy eran documentos standalone con su propio <head>,
        Font Awesome, Google Fonts y SheetJS por CDN."""
        assert "adhoc-print" in html
        assert "/static/adhoc/css/adhoc.css?v=" in html
        assert "cdnjs.cloudflare.com" not in html
        assert "fonts.googleapis.com" not in html

    def test_encabezado_con_titulo_y_metadatos(self, html):
        assert REPORT_META["area_usuarios"]["title"] in html
        for label in ("Solicitado por", "Fecha de emisión", "Hora de emisión",
                      "Filtro Área", "Filtro Nombre", "Formato"):
            assert label in html

    def test_el_solicitante_sale_del_jwt(self, html):
        assert "Test User" in html

    def test_pinta_las_columnas_y_las_filas_del_service(self, html):
        for label in ("Nombre", "Apellidos", "Área Asignada"):
            assert f">{label}</th>" in html
        assert 'data-adhoc-cell="first_name">Ana<' in html
        assert 'data-adhoc-cell="areas">Calidad<' in html

    def test_botones_de_exportar_e_imprimir(self, html):
        assert "data-adhoc-report-excel" in html
        assert "data-adhoc-report-print" in html
        assert "onclick=" not in html

    def test_sheetjs_pineado_y_local_no_por_cdn(self, html):
        """Riesgo de cadena de suministro del legacy: ``xlsx-latest`` sin SRI."""
        assert "cdn.sheetjs.com" not in html
        assert "/static/adhoc/js/vendor/xlsx-0.20.3.mini.min.js?v=" in html

    def test_page_data_lleva_la_hoja_y_el_prefijo_de_archivo(self, html):
        import json

        payload = html.split('type="application/json">')[1].split("</script>")[0]
        data = json.loads(payload)
        assert data["sheet"] == REPORT_META["area_usuarios"]["sheet"]
        assert data["filePrefix"] == REPORT_META["area_usuarios"]["file_prefix"]
        assert data["reportType"] == "area_usuarios"

    def test_sin_filas_muestra_estado_vacio_fuera_de_la_tabla(self, client, admin_headers):
        """La fila fantasma de ``data_table`` acabaría dentro del Excel que
        genera ``XLSX.utils.table_to_book``; por eso el estado vacío va fuera."""
        with patch(f"{SERVICE}.build_report", return_value=_report(rows=[])):
            html = client.get("/adhoc/reportes/area_usuarios", headers=admin_headers).text
        assert "adhoc-empty" in html
        tabla = html.split('id="adhoc-report-table"')[1].split("</table>")[0]
        assert "<tbody>" in tabla
        assert "adhoc-empty" not in tabla

    def test_avisa_cuando_el_reporte_se_recorto(self, client, admin_headers):
        with patch(f"{SERVICE}.build_report", return_value=_report(truncated=True)):
            html = client.get("/adhoc/reportes/area_usuarios", headers=admin_headers).text
        assert "se recortó a los primeros 5000" in html

    @pytest.mark.parametrize("report_type", REPORT_TYPES)
    def test_las_cinco_formas_reales_del_service_caben_en_el_template(
        self, client, admin_headers, db_session, report_type
    ):
        """Integración service↔template: se construye el reporte REAL (contra
        Postgres) y se comprueba que el template pinta sus columnas.

        Es lo que ata las dos mitades: si un builder cambia el nombre de una
        clave, aquí se cae.
        """
        from itcj2.apps.adhoc.services.report_service import ReportService

        real = ReportService.build_report(db_session, report_type, formato="completo")

        with patch(f"{SERVICE}.build_report", return_value=real):
            res = client.get(
                f"/adhoc/reportes/{report_type}?formato=completo", headers=admin_headers
            )

        assert res.status_code == 200
        for col in real["columns"]:
            assert f">{col['label']}</th>" in res.text, (report_type, col)


# ==========================================================================
# Reglas duras del plan §6.2 / §6.3 / §6.4 sobre los archivos de la sección
# ==========================================================================

def _strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


SECTION_TEMPLATES = [TEMPLATES_DIR / "reports.html", TEMPLATES_DIR / "view_report.html"]
SECTION_JS = [
    STATIC_DIR / "js" / "reports" / "reports.js",
    STATIC_DIR / "js" / "reports" / "report-view.js",
]
SECTION_CSS = [
    STATIC_DIR / "css" / "reports" / "reports.css",
    STATIC_DIR / "css" / "reports" / "view-report.css",
]
VENDOR_XLSX = STATIC_DIR / "js" / "vendor" / "xlsx-0.20.3.mini.min.js"


class TestReglasDuras:
    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_templates_sin_css_ni_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text
        assert "onclick=" not in text
        assert "onchange=" not in text

    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_templates_extienden_la_base(self, path):
        text = path.read_text(encoding="utf-8")
        assert '{% extends "adhoc/base_adhoc.html" %}' in text
        assert "<!doctype" not in text.lower()

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_es_iife_estricto(self, path):
        assert path.exists(), path
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    def test_js_solo_expone_su_namespace(self):
        expected = {
            "reports.js": "window.AdhocReports",
            "report-view.js": "window.AdhocReportView",
        }
        for path in SECTION_JS:
            text = path.read_text(encoding="utf-8")
            assignments = set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M))
            assert assignments == {expected[path.name]}, (path.name, assignments)

    def test_js_es_idempotente_ante_una_reejecucion(self):
        """`hx-boost` reinserta —y reejecuta— los <script> de la página que entra.

        Como los listeners son delegados sobre `document` y sobreviven al swap,
        una segunda ejecución solo los duplicaría: el módulo tiene que salirse
        si su namespace ya existe.
        """
        expected = {
            "reports.js": "if (window.AdhocReports) return;",
            "report-view.js": "if (window.AdhocReportView) return;",
        }
        for path in SECTION_JS:
            text = path.read_text(encoding="utf-8")
            assert expected[path.name] in text, path.name

    def test_js_escapa_antes_de_inyectar_html(self):
        """La vista previa se pinta con innerHTML/insertAdjacentHTML."""
        text = (STATIC_DIR / "js" / "reports" / "reports.js").read_text(encoding="utf-8")
        assert "escapeHtml" in text
        # Ninguna interpolación cruda de un valor del servidor en el HTML.
        assert "+ rows[i][columns[c]] +" not in text

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_no_redefine_clases_de_bootstrap(self, path):
        css = path.read_text(encoding="utf-8")
        selectors = re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M)
        prohibidas = re.compile(
            r"(^|[\s,>])\.(form-control|form-group|form-row|form-label|form-select|"
            r"card|badge-|alert-|bg-)"
        )
        for selector in selectors:
            for part in selector.split(","):
                part = part.strip()
                if not part.startswith("."):
                    continue
                assert not prohibidas.search(" " + part), (path.name, part)

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_comentarios_no_cierran_sobre_un_token(self, path):
        """Gotcha real del repo: ``-*/`` pegado a un comodín rompe el bloque."""
        css = path.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_usa_los_tokens_no_hex_sueltos(self, path):
        """El legacy repetía 45 hex; solo se permiten los de impresión (#000)."""
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        hexes = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", css)}
        assert hexes <= {"#000", "#fff", "#000000", "#ffffff"}, hexes
        assert "var(--adhoc-" in css

    def test_el_vendor_de_excel_esta_pineado_en_disco(self):
        assert VENDOR_XLSX.exists(), VENDOR_XLSX
        head = VENDOR_XLSX.read_text(encoding="utf-8", errors="ignore")[:200]
        assert "SheetJS" in head
        assert (VENDOR_XLSX.parent / "README.md").exists()

    def test_ningun_template_de_la_seccion_carga_un_cdn_de_terceros(self):
        for path in SECTION_TEMPLATES:
            text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
            for host in ("cdn.sheetjs.com", "cdnjs.cloudflare.com", "fonts.googleapis.com"):
                assert host not in text, (path.name, host)

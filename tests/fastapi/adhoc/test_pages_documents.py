"""Tests de la sección **Documentos y flujos** de Calidad (fase F5/F6).

Cubre las seis páginas de ``itcj2/apps/adhoc/pages/documents.py``:

======================================  ============================
URL                                     Permiso de página
======================================  ============================
``/adhoc/documentos``                   ``adhoc.documents.page.list``
``/adhoc/documentos/panel``             ``adhoc.documents.page.manage``
``/adhoc/documentos/categorias``        ``adhoc.doc_catalogs.page.list``
``/adhoc/documentos/clasificaciones``   ``adhoc.doc_catalogs.page.list``
``/adhoc/documentos/flujos``            ``adhoc.flows.page.list``
``/adhoc/documentos/flujos/{id}/pasos`` ``adhoc.flows.page.list``
======================================  ============================

Harness (plan §9.1): estas rutas devuelven **HTML** (403 renderizado, 302 al
login), no JSON, y ``cached_has_assignment``/``cached_perms`` se parchean en el
**módulo fuente** porque las dependencias los importan dentro de la función.

Matiz importante del harness, distinto del de la API: ``require_page_app`` **no
tiene bypass para el admin global del JWT** —a diferencia de ``require_perms``,
comprueba asignación y permiso siempre—, así que aquí ni siquiera el JWT con
``role="admin"`` entra sin parchear la autorización. Lo que sí depende del rol
del JWT son las **capacidades de la UI**: ``_effective_perms`` devuelve ``None``
para el admin global (todo visible), que es justo lo que la API le permitirá.

Nota de montaje: el router de la sección se incluye **a mano** en el fixture.
``itcj2/apps/adhoc/pages/router.py`` lo cablea la fase siguiente y es un archivo
compartido que esta sección no toca; el prefijo con el que se monta aquí
(``/adhoc``) es exactamente el del router padre.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.pages.documents import router as documents_router
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATES_DIR = APP_ROOT / "templates" / "adhoc" / "documents"
CSS_DIR = APP_ROOT / "static" / "css" / "documents"
JS_DIR = APP_ROOT / "static" / "js" / "documents"

#: URL → permiso de página exigido (tabla del plan §4).
PAGES = {
    "/adhoc/documentos": "adhoc.documents.page.list",
    "/adhoc/documentos/panel": "adhoc.documents.page.manage",
    "/adhoc/documentos/categorias": "adhoc.doc_catalogs.page.list",
    "/adhoc/documentos/clasificaciones": "adhoc.doc_catalogs.page.list",
    "/adhoc/documentos/flujos": "adhoc.flows.page.list",
    "/adhoc/documentos/flujos/1/pasos": "adhoc.flows.page.list",
}

#: Nombre con markup: si sale sin escapar en el HTML, es un XSS.
EVIL = '<img src=x onerror="alert(1)">'

#: Todos los permisos de Calidad que tocan estas seis pantallas. Es lo que ve el
#: rol ``admin`` de la app. OJO: ``require_page_app`` **no** tiene bypass para el
#: admin global del JWT —comprueba asignación y permiso siempre—, así que estos
#: tests parchean ``cached_has_assignment``/``cached_perms`` incluso para él.
ALL_PERMS = {
    "adhoc.dashboard.page.view",
    "adhoc.documents.page.list",
    "adhoc.documents.page.manage",
    "adhoc.documents.api.read",
    "adhoc.documents.api.create",
    "adhoc.documents.api.update",
    "adhoc.documents.api.delete",
    "adhoc.documents.api.download",
    "adhoc.documents.api.start_flow",
    "adhoc.doc_catalogs.page.list",
    "adhoc.doc_catalogs.api.read",
    "adhoc.doc_catalogs.api.create",
    "adhoc.doc_catalogs.api.update",
    "adhoc.doc_catalogs.api.delete",
    "adhoc.flows.page.list",
    "adhoc.flows.api.read",
    "adhoc.flows.api.create",
    "adhoc.flows.api.update",
    "adhoc.flows.api.delete",
    "adhoc.flows.api.assign",
}


# ==========================================================================
# Doble de la sesión de BD
# ==========================================================================

class _FakeQuery:
    """Lo justo de la interfaz de ``Query`` que usan estas páginas."""

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **k):
        return self

    def filter_by(self, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def options(self, *a, **k):
        return self

    def distinct(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)


class FakeDB:
    """Sesión falsa: devuelve filas por nombre de modelo, sin tocar Postgres."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.rows = {
            "AdhocDocumentCategory": [SimpleNamespace(id=1, name="Manual de calidad")],
            "AdhocDocumentClassification": [SimpleNamespace(id=4, name="Procedimiento")],
            "AdhocArea": [SimpleNamespace(id=2, name="Servicios escolares", is_active=True)],
            "AdhocProcess": [SimpleNamespace(id=3, name="Gestión académica")],
            "AdhocApprovalFlow": [SimpleNamespace(id=7, name="Revisión de calidad",
                                                  description="Dos pasos")],
            "User": [SimpleNamespace(id=11, first_name="Ana", last_name="Ríos",
                                     middle_name=None, full_name="Ríos Ana",
                                     email="ana@itcj.edu.mx", username="arios",
                                     is_active=True)],
        }
        self.entities = {
            ("AdhocApprovalFlow", 1): SimpleNamespace(
                id=1, name="Revisión de calidad", description="Dos pasos"
            ),
        }

    def query(self, *entities):
        name = getattr(entities[0], "__name__", str(entities[0]))
        return _FakeQuery(self.rows.get(name, []))

    def get(self, model, pk):
        return self.entities.get((getattr(model, "__name__", str(model)), pk))


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(scope="module")
def fake_db():
    return FakeDB()


@pytest.fixture(scope="module")
def client(fake_db):
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()
        # El cableado real vive en pages/router.py (fase siguiente); aquí se monta
        # con el mismo prefijo para poder ejercitar las rutas por HTTP.
        app.include_router(documents_router, prefix="/adhoc")

        def _override():
            yield fake_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_db(fake_db):
    fake_db.reset()
    yield
    fake_db.reset()


@pytest.fixture(autouse=True)
def authz():
    """Acceso a la app concedido y permisos completos, salvo que el test los baje.

    Se parchea el **módulo fuente** (``authz_cache``, ``authz_service``) porque
    las dependencias de página y la propia ruta los importan dentro de la
    función. Devuelve el mock de ``cached_perms`` para que un test pueda
    estrechar el conjunto y comprobar el gate.
    """
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value=set(ALL_PERMS)) as perms_mock, \
         patch("itcj2.core.services.authz_service.users_with_assignment_select",
               return_value=[11]):
        yield perms_mock


@pytest.fixture()
def admin_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=201, role='staff')}"}


def get_as_staff(client, headers, url, perms, authz):
    """GET con un usuario NO admin que tiene exactamente *perms*."""
    authz.return_value = set(perms)
    try:
        return client.get(url, headers=headers)
    finally:
        authz.return_value = set(ALL_PERMS)


def page_data(html):
    """El bloque JSON que emite ``page_data_script()``, ya parseado."""
    match = re.search(
        r'<script id="adhoc-page-data" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert match, "la página no emitió el bloque adhoc-page-data"
    return json.loads(match.group(1))


# ==========================================================================
# Rutas y autorización
# ==========================================================================

class TestRutas:
    @pytest.mark.parametrize("url", list(PAGES))
    def test_admin_entra_a_las_seis(self, client, admin_headers, url):
        res = client.get(url, headers=admin_headers)
        assert res.status_code == 200, res.text[:400]
        assert "text/html" in res.headers["content-type"]

    @pytest.mark.parametrize("url", list(PAGES))
    def test_anonimo_va_al_login(self, client, url):
        res = client.get(url, follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

    @pytest.mark.parametrize("url,perm", list(PAGES.items()))
    def test_con_el_permiso_de_su_pagina_entra(self, client, staff_headers, authz, url, perm):
        res = get_as_staff(client, staff_headers, url, {perm}, authz)
        assert res.status_code == 200, res.text[:400]

    @pytest.mark.parametrize("url", list(PAGES))
    def test_sin_permiso_es_403(self, client, staff_headers, authz, url):
        """Bug #25: el legacy ponía @login_required ENCIMA de @route."""
        res = get_as_staff(client, staff_headers, url,
                           {"adhoc.dashboard.page.view"}, authz)
        assert res.status_code == 403, res.text[:400]

    def test_el_permiso_de_una_pagina_no_abre_la_otra(self, client, staff_headers, authz):
        """`documents.page.list` (consulta) NO da acceso al panel de gestión."""
        res = get_as_staff(client, staff_headers, "/adhoc/documentos/panel",
                           {"adhoc.documents.page.list"}, authz)
        assert res.status_code == 403

    def test_las_seis_rutas_estan_en_el_router_de_la_seccion(self):
        paths = {r.path for r in documents_router.routes}
        assert paths == {
            "/documentos",
            "/documentos/panel",
            "/documentos/categorias",
            "/documentos/clasificaciones",
            "/documentos/flujos",
            "/documentos/flujos/{flow_id}/pasos",
        }

    def test_el_router_no_trae_prefijo_propio(self):
        """El prefijo lo pone el padre en la fase de cableado."""
        assert documents_router.prefix == ""


# ==========================================================================
# /adhoc/documentos — la vista de consulta
# ==========================================================================

class TestConsulta:
    @pytest.fixture()
    def html(self, client, admin_headers):
        return client.get("/adhoc/documentos", headers=admin_headers).text

    def test_los_cuatro_selects_de_filtro_traen_opciones(self, html):
        """Bug #28: el legacy iteraba los cuatro catálogos y la ruta no los pasaba."""
        for name in ("category_id", "area_id", "process_id", "classification_id"):
            assert f'name="{name}"' in html
        assert "Manual de calidad" in html      # categoría
        assert "Servicios escolares" in html    # área
        assert "Gestión académica" in html      # proceso
        assert "Procedimiento" in html          # clasificación

    def test_ofrece_el_filtro_de_estatus_con_el_vocabulario_cerrado(self, html):
        for status in ("Borrador", "En Revisión", "Aprobado", "Rechazado"):
            assert f'<option value="{status}">' in html

    def test_los_nombres_de_catalogo_se_escapan(self, client, admin_headers, fake_db):
        fake_db.rows["AdhocDocumentCategory"] = [SimpleNamespace(id=9, name=EVIL)]
        html = client.get("/adhoc/documentos", headers=admin_headers).text
        assert "<img src=x" not in html
        assert "&lt;img" in html

    def test_no_pinta_filtros_por_columna(self, html):
        """El filtrado es de servidor: los inputs por columna serían mentira."""
        assert "data-adhoc-filter-input" not in html
        assert "data-adhoc-doc-filter" in html

    def test_declara_la_tabla_y_el_paginador(self, html):
        assert 'data-adhoc-table="adhoc-documents-table"' in html
        assert 'id="adhoc-documents-table-body"' in html
        assert "data-adhoc-pager" in html

    def test_page_data_lleva_la_capacidad_de_descarga(self, html):
        data = page_data(html)
        assert data["can_download"] is True
        assert data["per_page"] == 25

    def test_estaticos_versionados(self, html):
        assert "/static/adhoc/css/documents/documents.css?v=" in html
        assert "/static/adhoc/js/documents/document-list.js?v=" in html
        assert "/static/adhoc/js/documents/documents.js?v=" in html

    def test_sin_permiso_de_descarga_la_pagina_lo_dice(self, client, staff_headers, authz):
        res = get_as_staff(client, staff_headers, "/adhoc/documentos",
                           {"adhoc.documents.page.list"}, authz)
        assert page_data(res.text)["can_download"] is False


# ==========================================================================
# /adhoc/documentos/panel — administración
# ==========================================================================

class TestPanel:
    @pytest.fixture()
    def html(self, client, admin_headers):
        return client.get("/adhoc/documentos/panel", headers=admin_headers).text

    def test_los_catalogos_viajan_como_json(self, html):
        """El legacy inyectaba `categoriasHtml` como HTML crudo en un backtick."""
        data = page_data(html)
        assert data["categories"] == [{"id": 1, "name": "Manual de calidad"}]
        assert data["areas"] == [{"id": 2, "name": "Servicios escolares"}]
        assert data["processes"] == [{"id": 3, "name": "Gestión académica"}]
        assert data["classifications"] == [{"id": 4, "name": "Procedimiento"}]
        assert data["flows"] == [{"id": 7, "name": "Revisión de calidad"}]

    def test_page_data_no_contiene_markup_de_option(self, html):
        raw = re.search(
            r'<script id="adhoc-page-data" type="application/json">(.*?)</script>',
            html, re.S,
        ).group(1)
        assert "<option" not in raw
        assert "\\u003coption" not in raw

    def test_un_nombre_con_markup_no_escapa_del_json(self, client, admin_headers, fake_db):
        fake_db.rows["AdhocArea"] = [SimpleNamespace(id=5, name=EVIL, is_active=True)]
        html = client.get("/adhoc/documentos/panel", headers=admin_headers).text
        assert "<img src=x" not in html
        assert page_data(html)["areas"] == [{"id": 5, "name": EVIL}]

    def test_page_data_lleva_las_cuatro_capacidades(self, html):
        data = page_data(html)
        for key in ("can_create", "can_delete", "can_download", "can_start_flow"):
            assert data[key] is True

    def test_las_extensiones_permitidas_llegan_al_input_de_archivo(self, html):
        accept = page_data(html)["accept"]
        assert ".pdf" in accept
        assert all(ext.startswith(".") for ext in accept)

    def test_no_porta_los_mockups_del_legacy(self, html):
        """Plan §4: fuera "Historial de Versiones" y la celda `ISO 9001`."""
        assert "ISO 9001" not in html
        assert "Historial de Versiones" not in html
        assert "Sist. Gestión" not in html

    def test_los_modales_son_bootstrap(self, html):
        assert 'id="adhoc-doc-modal"' in html
        assert 'id="adhoc-doc-flow-modal"' in html
        assert "modal fade" in html
        assert "modal-overlay" not in html

    def test_el_alta_masiva_usa_los_nombres_de_campo_de_la_api(self, html):
        """El <form> real hace que `new FormData(form)` mande listas paralelas."""
        assert "data-adhoc-doc-form" in html
        assert "data-adhoc-doc-fields" in html

    def test_sin_permiso_de_alta_no_hay_boton_nuevo(self, client, staff_headers, authz):
        res = get_as_staff(client, staff_headers, "/adhoc/documentos/panel",
                           {"adhoc.documents.page.manage"}, authz)
        assert res.status_code == 200
        assert "data-adhoc-doc-new" not in res.text
        data = page_data(res.text)
        assert data["can_create"] is False
        assert data["can_delete"] is False
        assert data["can_start_flow"] is False


# ==========================================================================
# Catálogos de documento — macro compartida, cero JS propio
# ==========================================================================

class TestCatalogos:
    CASES = [
        ("/adhoc/documentos/categorias", "document-categories",
         "/api/adhoc/v2/document-categories"),
        ("/adhoc/documentos/clasificaciones", "document-classifications",
         "/api/adhoc/v2/document-classifications"),
    ]

    @pytest.mark.parametrize("url,resource,api", CASES)
    def test_usa_la_macro_y_el_modulo_compartido(self, client, admin_headers,
                                                 url, resource, api):
        html = client.get(url, headers=admin_headers).text
        assert "data-adhoc-catalog" in html
        assert f'data-adhoc-resource="{resource}"' in html
        assert f'data-adhoc-api="{api}"' in html
        assert f'data-adhoc-catalog-modal="{resource}"' in html
        assert "/static/adhoc/js/shared/catalog-crud.js?v=" in html

    @pytest.mark.parametrize("url,resource,api", CASES)
    def test_no_duplica_el_crud_con_js_propio(self, client, admin_headers,
                                              url, resource, api):
        """Plan §6.5: el legacy tenía cuatro copias del mismo archivo."""
        html = client.get(url, headers=admin_headers).text
        assert "/static/adhoc/js/documents/" not in html

    @pytest.mark.parametrize("url,resource,api", CASES)
    def test_vuelve_a_una_pagina_que_el_rol_consult_si_puede_ver(self, client,
                                                                 admin_headers,
                                                                 url, resource, api):
        html = client.get(url, headers=admin_headers).text
        assert 'href="/adhoc/documentos"' in html

    @pytest.mark.parametrize("url,resource,api", CASES)
    def test_solo_lectura_oculta_los_botones(self, client, staff_headers, authz,
                                             url, resource, api):
        res = get_as_staff(client, staff_headers, url,
                           {"adhoc.doc_catalogs.page.list",
                            "adhoc.doc_catalogs.api.read"}, authz)
        assert res.status_code == 200
        assert 'data-adhoc-can-create="0"' in res.text
        assert 'data-adhoc-can-update="0"' in res.text
        assert 'data-adhoc-can-delete="0"' in res.text
        assert "data-adhoc-catalog-new" not in res.text


# ==========================================================================
# /adhoc/documentos/flujos
# ==========================================================================

class TestFlujos:
    @pytest.fixture()
    def html(self, client, admin_headers):
        return client.get("/adhoc/documentos/flujos", headers=admin_headers).text

    def test_render_basico(self, html):
        assert "data-adhoc-flows" in html
        assert 'data-adhoc-table="adhoc-flows-table"' in html
        assert "/static/adhoc/js/documents/flows.js?v=" in html
        assert "/static/adhoc/css/documents/flows.css?v=" in html

    def test_el_modal_es_bootstrap(self, html):
        assert 'id="adhoc-flow-modal"' in html
        assert "modal fade" in html
        assert "modal-overlay" not in html

    def test_page_data_lleva_las_capacidades(self, html):
        data = page_data(html)
        assert data == {"can_create": True, "can_update": True, "can_delete": True}

    def test_filtra_por_clave_de_columna_no_por_indice(self, html):
        assert 'data-adhoc-filter-key="name"' in html
        assert 'data-adhoc-filter-input="name"' in html

    def test_solo_lectura_oculta_el_boton_nuevo(self, client, staff_headers, authz):
        res = get_as_staff(client, staff_headers, "/adhoc/documentos/flujos",
                           {"adhoc.flows.page.list", "adhoc.flows.api.read"}, authz)
        assert "data-adhoc-flow-new" not in res.text
        assert page_data(res.text) == {
            "can_create": False, "can_update": False, "can_delete": False,
        }


# ==========================================================================
# /adhoc/documentos/flujos/{id}/pasos
# ==========================================================================

class TestPasos:
    @pytest.fixture()
    def html(self, client, admin_headers):
        return client.get("/adhoc/documentos/flujos/1/pasos", headers=admin_headers).text

    def test_flujo_inexistente_es_404(self, client, admin_headers):
        res = client.get("/adhoc/documentos/flujos/999/pasos", headers=admin_headers)
        assert res.status_code == 404

    def test_render_basico(self, html):
        assert "data-adhoc-flow-steps" in html
        assert 'data-adhoc-table="adhoc-steps-table"' in html
        assert "Revisión de calidad" in html
        assert "/static/adhoc/js/documents/flow-steps.js?v=" in html

    def test_los_usuarios_van_en_page_data_no_como_option(self, html):
        """El legacy los pintaba desde Jinja y en la otra pantalla como HTML crudo."""
        data = page_data(html)
        assert data["flow_id"] == 1
        assert data["users"] == [{
            "id": 11, "full_name": "Ríos Ana",
            "email": "ana@itcj.edu.mx", "username": "arios",
        }]
        assert "arios" not in html.split('id="adhoc-page-data"')[0]

    def test_un_nombre_de_usuario_con_markup_no_llega_al_html(self, client,
                                                              admin_headers, fake_db):
        fake_db.rows["User"] = [SimpleNamespace(
            id=12, first_name="X", last_name="Y", middle_name=None,
            full_name=EVIL, email=None, username=None, is_active=True,
        )]
        html = client.get("/adhoc/documentos/flujos/1/pasos", headers=admin_headers).text
        assert "<img src=x" not in html
        assert page_data(html)["users"][0]["full_name"] == EVIL

    def test_monta_el_selector_compartido(self, html):
        assert "/static/adhoc/js/shared/user-picker.js?v=" in html
        assert "data-adhoc-user-picker" in html
        assert 'data-adhoc-users-key="users"' in html
        # los usuarios NUNCA se pintan desde Jinja
        assert "<option" not in html.split("data-adhoc-user-picker")[1]

    def test_el_selector_no_promete_un_orden_que_la_api_no_guarda(self, html):
        """`set_step_validators` guarda un CONJUNTO; numerar sería mentira."""
        assert 'data-adhoc-ordered="1"' not in html

    def test_sin_permiso_de_asignar_no_hay_capacidad(self, client, staff_headers, authz):
        res = get_as_staff(client, staff_headers, "/adhoc/documentos/flujos/1/pasos",
                           {"adhoc.flows.page.list"}, authz)
        data = page_data(res.text)
        assert data["can_update"] is False
        assert data["can_assign"] is False
        assert "data-adhoc-steps-add" not in res.text


# ==========================================================================
# Reglas duras del plan sobre los archivos de la sección
# ==========================================================================

def _strip_jinja_comments(text):
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


TEMPLATES = sorted(TEMPLATES_DIR.glob("*.html"))
CSS_FILES = sorted(CSS_DIR.glob("*.css"))
JS_FILES = sorted(JS_DIR.glob("*.js"))

JS_NAMESPACES = {
    "document-list.js": "window.AdhocDocumentList",
    "documents.js": "window.AdhocDocuments",
    "documents-panel.js": "window.AdhocDocumentsPanel",
    "flows.js": "window.AdhocFlows",
    "flow-steps.js": "window.AdhocFlowSteps",
}


class TestReglasDuras:
    def test_estan_los_archivos_esperados(self):
        assert {p.name for p in TEMPLATES} == {
            "documents.html", "documents_panel.html", "document_categories.html",
            "document_classifications.html", "flows.html", "flow_steps.html",
        }
        assert {p.name for p in JS_FILES} == set(JS_NAMESPACES)

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_templates_sin_css_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_templates_sin_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "onclick=" not in text
        assert "onchange=" not in text

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_el_unico_script_inline_es_el_bloque_json(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", text):
            assert 'type="application/json"' in match.group(0), match.group(0)

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_los_estaticos_van_versionados(self, path):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'(?:href|src)="(/static/[^"]+)"', text):
            assert "?v=" in match.group(1), match.group(1)

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_es_iife_estricto_y_documentado(self, path):
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        """Criterio de aceptación 5 del plan; el legacy tenía 14."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_solo_expone_su_namespace(self, path):
        assignments = set(re.findall(r"^\s*(window\.\w+)\s*=",
                                     path.read_text(encoding="utf-8"), re.M))
        assert assignments == {JS_NAMESPACES[path.name]}, (path.name, assignments)

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_no_mete_datos_del_servidor_en_innerhtml(self, path):
        """Solo se permite innerHTML con markup literal (iconos)."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"\.innerHTML\s*=\s*([^;]+);", text):
            expression = match.group(1)
            assert "escapeHtml" in expression or "'" in expression, expression
            assert "textContent" not in expression

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_no_redefine_clases_de_bootstrap(self, path):
        css = path.read_text(encoding="utf-8")
        prohibidas = re.compile(
            r"(^|[\s,>])\.(form-control|form-group|form-row|form-label|form-select|"
            r"card|badge-|alert-|bg-)"
        )
        for selector in re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M):
            for part in selector.split(","):
                part = part.strip()
                if not part.startswith("."):
                    continue
                assert not prohibidas.search(" " + part), (path.name, part)

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_comentarios_no_cierran_sobre_un_token(self, path):
        """Gotcha real del repo: un cierre de comentario pegado a un comodín."""
        css = path.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_usa_tokens_no_hex_sueltos(self, path):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", css)

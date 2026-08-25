"""Tests de la BASE UI de Calidad (fase F5/F6, sección "base").

Cubre lo que las seis secciones de página van a reutilizar y que, si se rompe,
las rompe todas a la vez:

* ``pages/nav.py`` — filtrado del menú por permisos reales de BD (fail-closed).
* ``partials/_macros.html`` — las macros compartidas, con foco en los contratos
  de los que dependen los módulos JS (``data-adhoc-filter-key`` por columna en
  vez de índices, ``|tojson`` en el bloque de constantes, cero ``style=`` y cero
  ``onclick=``).
* ``base_adhoc.html`` — que la página raíz de la app siga renderizando con el
  nav inyectado.
* Reglas duras del plan §6.2/§6.3 sobre los archivos de la base: sin CSS inline,
  sin manejadores inline, sin ``alert``/``confirm``/``prompt`` en el JS.

Harness (plan §9.1): el error del cliente es ``{"error": …, "status": …}``; un
JWT con ``role="admin"`` bypasea ``require_perms``; las páginas devuelven HTML.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.pages.nav import NAV_SECTIONS, nav_for_user, nav_items
from itcj2.apps.adhoc.pages.render import adhoc_templates
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

MACROS = "adhoc/partials/_macros.html"
APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATES_DIR = APP_ROOT / "templates"
STATIC_DIR = APP_ROOT / "static"

#: Permisos de página que el DML de F2 sembró de verdad. Si un permiso del nav
#: no está en esta lista, la sección queda invisible para todo el mundo.
DB_PAGE_PERMS = {
    "adhoc.areas.page.list",
    "adhoc.dashboard.page.view",
    "adhoc.doc_catalogs.page.list",
    "adhoc.documents.page.list",
    "adhoc.documents.page.manage",
    "adhoc.flows.page.list",
    "adhoc.incident_categories.page.list",
    "adhoc.incidents.page.list",
    "adhoc.indicators.page.list",
    "adhoc.indicators.page.manage",
    "adhoc.indicators.page.tracking",
    "adhoc.mail.page.view",
    "adhoc.panel.page.view",
    "adhoc.processes.page.list",
    "adhoc.program_categories.page.list",
    "adhoc.programs.page.list",
    "adhoc.reports.page.view",
    "adhoc.tasks.page.assign",
    "adhoc.tasks.page.list",
    "adhoc.users.page.list",
}


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(scope="module")
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()
        mock_db = MagicMock()

        def _override():
            yield mock_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def admin_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture(scope="module")
def macros():
    """Módulo Jinja con las macros ya evaluadas (acceso directo por atributo)."""
    return adhoc_templates.env.get_template(MACROS).module


def render(source: str, **ctx) -> str:
    """Renderiza un template al vuelo contra el entorno Jinja real de adhoc."""
    return adhoc_templates.env.from_string(source).render(**ctx)


# ==========================================================================
# nav.py — secciones y permisos
# ==========================================================================

class TestNavSections:
    def test_todos_los_permisos_del_nav_existen_en_bd(self):
        """Un permiso mal escrito deja la sección invisible sin fallar en test."""
        for label, _icon, _url, perms in NAV_SECTIONS:
            desconocidos = perms - DB_PAGE_PERMS
            assert not desconocidos, f"{label}: permisos inexistentes {desconocidos}"

    def test_urls_del_nav_son_literales_bajo_adhoc(self):
        for _label, _icon, url, _perms in NAV_SECTIONS:
            assert url.startswith("/adhoc/"), url

    def test_iconos_son_bootstrap_icons(self):
        """El legacy usaba Font Awesome; en adhoc todo es bi-*."""
        for _label, icon, _url, _perms in NAV_SECTIONS:
            assert icon.startswith("bi-"), icon

    def test_secciones_del_plan_estan_presentes(self):
        urls = {url.split("?")[0] for _l, _i, url, _p in NAV_SECTIONS}
        assert urls == {
            "/adhoc/dashboard",
            "/adhoc/documentos",
            "/adhoc/incidencias",
            "/adhoc/programas",
            "/adhoc/indicadores",
            "/adhoc/reportes",
            "/adhoc/panel",
        }

    def test_asignaciones_no_esta_en_el_nav(self):
        """Pantalla auxiliar: sin ?action/?task_id no tiene nada que mostrar."""
        urls = {url for _l, _i, url, _p in NAV_SECTIONS}
        assert "/adhoc/asignaciones" not in urls

    def test_admin_global_ve_todas_las_secciones(self):
        items = nav_items(MagicMock(), 1, is_admin=True)
        assert len(items) == len(NAV_SECTIONS)
        assert {i["label"] for i in items} == {s[0] for s in NAV_SECTIONS}

    def test_filtra_por_permisos(self):
        perms = {"adhoc.dashboard.page.view", "adhoc.incidents.page.list"}
        with patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=perms,
        ):
            items = nav_items(MagicMock(), 7)
        assert [i["label"] for i in items] == ["Tareas", "Incidencias"]

    def test_indicadores_basta_con_uno_de_los_dos_permisos(self):
        with patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value={"adhoc.indicators.page.tracking"},
        ):
            items = nav_items(MagicMock(), 7)
        assert [i["label"] for i in items] == ["Indicadores"]

    def test_sin_permisos_no_hay_menu(self):
        with patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=set(),
        ):
            assert nav_items(MagicMock(), 7) == []

    def test_error_al_calcular_permisos_es_fail_closed(self):
        """Devolver el menú completo sería un fallo ABIERTO: enlaces a 403."""
        with patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            side_effect=RuntimeError("sin BD"),
        ):
            assert nav_items(MagicMock(), 7) == []

    def test_nav_for_user_sin_usuario(self):
        assert nav_for_user(MagicMock(), None) == []

    def test_nav_for_user_con_jwt_admin(self):
        items = nav_for_user(MagicMock(), {"sub": "1", "role": "admin"})
        assert len(items) == len(NAV_SECTIONS)

    def test_nav_for_user_con_sub_invalido(self):
        assert nav_for_user(MagicMock(), {"sub": "no-es-un-int"}) == []


# ==========================================================================
# Macro data_table — el contrato con shared/table-filter.js
# ==========================================================================

COLS = [
    {"key": "code", "label": "Código", "filter": True},
    {"key": "title", "label": "Título", "filter": True, "placeholder": "Buscar título"},
    {"key": "actions", "label": "Acciones", "align": "end"},
]


class TestDataTable:
    def test_cada_columna_expone_su_clave(self, macros):
        html = macros.data_table("t1", COLS)
        for key in ("code", "title", "actions"):
            assert f'data-adhoc-filter-key="{key}"' in html

    def test_input_de_filtro_por_clave_no_por_indice(self, macros):
        """El bug del legacy: los filtros iban cableados al índice de columna."""
        html = macros.data_table("t1", COLS)
        assert 'data-adhoc-filter-input="code"' in html
        assert 'data-adhoc-filter-input="title"' in html
        # la columna de acciones no declara filter → no lleva input
        assert 'data-adhoc-filter-input="actions"' not in html

    def test_placeholder_personalizado_y_por_defecto(self, macros):
        html = macros.data_table("t1", COLS)
        assert 'placeholder="Buscar título"' in html
        assert 'placeholder="Código"' in html

    def test_sin_columnas_filtrables_no_hay_fila_de_filtros(self, macros):
        html = macros.data_table("t1", [{"key": "name", "label": "Nombre"}])
        assert "adhoc-filter-row" not in html

    def test_colspan_del_estado_vacio_cuadra_con_las_columnas(self, macros):
        html = macros.data_table("t1", COLS, "Nada por aquí.")
        assert 'colspan="3"' in html
        assert "Nada por aquí." in html
        assert "data-adhoc-empty" in html

    def test_ancho_minimo_por_clase_no_por_style(self, macros):
        html = macros.data_table("t1", COLS, width="xl")
        assert "adhoc-table-xl" in html
        assert "style=" not in html

    def test_scroll_horizontal_en_contenedor_propio(self, macros):
        html = macros.data_table("t1", COLS)
        assert "adhoc-table-wrap" in html
        assert "data-adhoc-table-wrap" in html

    def test_tbody_tiene_id_derivado_y_hook(self, macros):
        html = macros.data_table("tabla-docs", COLS)
        assert 'id="tabla-docs-body"' in html
        assert 'data-adhoc-table="tabla-docs"' in html
        assert "data-adhoc-table-body" in html

    def test_filas_del_caller_se_pintan_antes_del_estado_vacio(self):
        html = render(
            "{% from '" + MACROS + "' import data_table %}"
            "{% call data_table('t', COLS) %}<tr data-id='1'><td>x</td></tr>{% endcall %}",
            COLS=COLS,
        )
        assert html.index("data-id='1'") < html.index("data-adhoc-empty")

    def test_etiquetas_se_escapan(self, macros):
        html = macros.data_table("t1", [{"key": "k", "label": '<img src=x onerror="1">'}])
        assert "<img" not in html
        assert "&lt;img" in html


# ==========================================================================
# Macros de formulario
# ==========================================================================

class TestFormMacros:
    def test_form_field_texto(self, macros):
        html = macros.form_field("title", "Título", required=True, placeholder="Escribe...")
        assert 'name="title"' in html
        assert 'type="text"' in html
        assert "required" in html
        assert "adhoc-required" in html
        assert 'placeholder="Escribe..."' in html

    def test_form_field_textarea(self, macros):
        html = macros.form_field("notes", "Notas", "textarea", value="hola", rows=5)
        assert "<textarea" in html
        assert 'rows="5"' in html
        assert ">hola</textarea>" in html

    def test_form_field_checkbox(self, macros):
        html = macros.form_field("is_active", "Activo", "checkbox", value=True)
        assert 'type="checkbox"' in html
        assert "checked" in html
        assert "form-check" in html

    def test_form_field_escapa_el_valor(self, macros):
        html = macros.form_field("t", "T", value='"><script>alert(1)</script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&amp;lt;" in html

    def test_form_field_attrs_es_dict_y_se_escapa(self, macros):
        html = macros.form_field("t", "T", attrs={"data-adhoc-filter-input": "t"})
        assert 'data-adhoc-filter-input="t"' in html
        html2 = macros.form_field("t", "T", attrs={"data-x": '" onload="evil()'})
        assert '" onload="' not in html2      # la comilla no cierra el atributo
        assert "&#34;" in html2 or "&quot;" in html2

    def test_form_field_sin_estilos_ni_handlers_inline(self, macros):
        html = macros.form_field("t", "T", help="ayuda")
        assert "style=" not in html
        assert "onclick=" not in html
        assert "onchange=" not in html

    def test_select_field_placeholder_vacio(self, macros):
        html = macros.select_field("area_id", "Área", [{"value": 1, "label": "Calidad"}])
        assert '<option value="">Seleccionar...</option>' in html

    def test_select_field_sin_placeholder(self, macros):
        html = macros.select_field("s", "S", [(1, "Uno")], placeholder=None)
        assert '<option value="">' not in html

    def test_select_field_marca_seleccionado_comparando_por_cadena(self, macros):
        html = macros.select_field("s", "S", [{"value": 1, "label": "Uno"}], selected="1")
        assert '<option value="1" selected>Uno</option>' in html

    def test_select_field_admite_tuplas_y_escalares(self, macros):
        assert '<option value="1">Uno</option>' in macros.select_field("s", "S", [(1, "Uno")])
        assert '<option value="Alta">Alta</option>' in macros.select_field("s", "S", ["Alta"])

    def test_select_field_multiple_con_lista_de_seleccionados(self, macros):
        html = macros.select_field(
            "ids", "IDs", [(1, "Uno"), (2, "Dos"), (3, "Tres")],
            selected=[1, 3], multiple=True,
        )
        assert html.count("selected") == 2
        assert "multiple" in html

    def test_select_field_escapa_las_etiquetas(self, macros):
        html = macros.select_field("s", "S", [{"value": 1, "label": "<b>x</b>"}])
        assert "<b>" not in html

    def test_color_field(self, macros):
        html = macros.color_field("color", "Color", "#4834d4")
        assert 'type="color"' in html
        assert 'value="#4834d4"' in html
        assert "form-control-color" in html

    def test_color_field_valor_por_defecto(self, macros):
        assert 'value="#4834d4"' in macros.color_field("color", "Color", None)

    def test_helper_interno_resuelve_al_importar_una_sola_macro(self):
        """`form_field` llama a `_attrs`, que vive en el mismo módulo Jinja."""
        html = render(
            "{% from '" + MACROS + "' import form_field %}"
            "{{ form_field('t', 'T', attrs={'data-k': 'v'}) }}"
        )
        assert 'data-k="v"' in html


# ==========================================================================
# Badges, page_data, toolbar, filter_bar, user_picker
# ==========================================================================

class TestSmallMacros:
    @pytest.mark.parametrize("value,tone", [
        ("Baja", "muted"), ("Media", "info"), ("Alta", "warning"), ("Urgente", "danger"),
    ])
    def test_priority_badge_tono(self, macros, value, tone):
        html = macros.priority_badge(value)
        assert f"adhoc-badge-{tone}" in html
        assert value in html

    def test_priority_badge_valor_desconocido_no_revienta(self, macros):
        html = macros.priority_badge("Inventada")
        assert "adhoc-badge-neutral" in html

    def test_status_badge_sigue_funcionando(self, macros):
        """Firma existente: no se rompe (ya hay código que la usa)."""
        assert "adhoc-badge-success" in macros.status_badge("Aprobado", "document")

    def test_page_data_script_es_json_no_ejecutable(self, macros):
        html = macros.page_data_script({"users": [{"id": 1, "name": "Ana"}]})
        assert 'type="application/json"' in html
        assert 'id="adhoc-page-data"' in html
        assert '"id": 1' in html or '"id":1' in html

    def test_page_data_script_neutraliza_cierre_de_script(self, macros):
        """El vector que rompía los `htmlUsers` del legacy."""
        html = macros.page_data_script({"x": "</script><script>alert(1)</script>"})
        assert "</script><script>" not in html
        assert "\\u003c" in html or "&lt;" in html

    def test_page_data_script_id_personalizado(self, macros):
        assert 'id="otro"' in macros.page_data_script({}, "otro")

    def test_toolbar_alineacion(self, macros):
        assert "adhoc-toolbar-end" in macros.toolbar()
        assert "adhoc-toolbar-between" in macros.toolbar("between")

    def test_filter_bar_declara_su_tabla_destino(self, macros):
        html = macros.filter_bar(target="tabla-docs")
        assert 'data-adhoc-filter-scope="tabla-docs"' in html
        assert 'data-adhoc-filter-clear="tabla-docs"' in html

    def test_filter_bar_sin_boton_de_limpiar(self, macros):
        assert "data-adhoc-filter-clear" not in macros.filter_bar(clear=False)

    def test_user_picker_solo_declara_las_claves_de_page_data(self, macros):
        """Los usuarios NUNCA se pintan desde Jinja (7 XSS del legacy)."""
        html = macros.user_picker("picker-1", users_key="users",
                                  selected_key="assigned_ids", ordered=True)
        assert "data-adhoc-user-picker" in html
        assert 'data-adhoc-users-key="users"' in html
        assert 'data-adhoc-selected-key="assigned_ids"' in html
        assert 'data-adhoc-ordered="1"' in html
        assert "<option" not in html

    def test_back_button_y_page_header_intactos(self, macros):
        assert 'href="/adhoc/panel"' in macros.back_button("/adhoc/panel")
        assert "adhoc-page-title" in macros.page_header("Título")


# ==========================================================================
# Macro catalog_page / catalog_modal — el contrato con shared/catalog-crud.js
# ==========================================================================

class TestCatalogMacros:
    @pytest.fixture()
    def html(self, macros):
        return macros.catalog_page(
            "Categorías de documento", "document-categories",
            "/api/adhoc/v2/document-categories", "/adhoc/documentos/panel",
            singular="categoría", plural="categorías",
        )

    def test_expone_la_configuracion_que_lee_el_js(self, html):
        assert "data-adhoc-catalog" in html
        assert 'data-adhoc-resource="document-categories"' in html
        assert 'data-adhoc-api="/api/adhoc/v2/document-categories"' in html
        assert 'data-adhoc-singular="categoría"' in html

    def test_incluye_la_tabla_con_id_derivado_del_recurso(self, html):
        assert 'data-adhoc-table="adhoc-catalog-document-categories"' in html
        assert 'data-adhoc-filter-key="name"' in html
        assert 'data-adhoc-filter-input="name"' in html

    def test_boton_volver_y_boton_nuevo(self, html):
        assert 'href="/adhoc/documentos/panel"' in html
        assert "data-adhoc-catalog-new" in html

    def test_flags_de_permiso_ocultan_botones(self, macros):
        html = macros.catalog_page("T", "r", "/api/adhoc/v2/r", "/adhoc/panel",
                                   can_create=False, can_update=False, can_delete=False)
        assert "data-adhoc-catalog-new" not in html
        assert 'data-adhoc-can-create="0"' in html
        assert 'data-adhoc-can-update="0"' in html
        assert 'data-adhoc-can-delete="0"' in html

    def test_mensaje_vacio_usa_el_plural(self, html):
        assert "No hay categorías registradas." in html

    def test_modal_es_bootstrap_no_modal_overlay(self, macros):
        html = macros.catalog_modal("document-categories", singular="categoría")
        assert "modal fade" in html
        assert "modal-dialog" in html
        assert 'data-bs-dismiss="modal"' in html
        assert "modal-overlay" not in html
        assert "style=" not in html

    def test_modal_expone_sus_hooks(self, macros):
        html = macros.catalog_modal("document-categories", max_items=5)
        assert 'data-adhoc-catalog-modal="document-categories"' in html
        assert "data-adhoc-catalog-qty" in html
        assert "data-adhoc-catalog-fields" in html
        assert "data-adhoc-catalog-save" in html
        assert html.count("<option") == 5


# ==========================================================================
# Reglas duras del plan sobre los archivos de la base
# ==========================================================================

def _strip_jinja_comments(text: str) -> str:
    """Quita los bloques {# … #}: la regla es sobre el markup, no sobre la prosa."""
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    """Quita /* … */ y las líneas que son solo comentario."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _base_templates():
    """Templates de la base UI (los de sección los revisa su propio agente)."""
    return [
        TEMPLATES_DIR / "adhoc" / "base_adhoc.html",
        TEMPLATES_DIR / "adhoc" / "partials" / "_macros.html",
        TEMPLATES_DIR / "adhoc" / "partials" / "_nav.html",
    ]


def _base_js():
    return [
        STATIC_DIR / "js" / "adhoc-utils.js",
        STATIC_DIR / "js" / "shared" / "catalog-crud.js",
        STATIC_DIR / "js" / "shared" / "table-filter.js",
        STATIC_DIR / "js" / "shared" / "user-picker.js",
    ]


class TestReglasDuras:
    @pytest.mark.parametrize("path", _base_templates(), ids=lambda p: p.name)
    def test_templates_sin_css_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    @pytest.mark.parametrize("path", _base_templates(), ids=lambda p: p.name)
    def test_templates_sin_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "onclick=" not in text
        assert "onchange=" not in text

    @pytest.mark.parametrize("path", _base_js(), ids=lambda p: p.name)
    def test_js_existe_y_es_iife_estricto(self, path):
        assert path.exists(), path
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", _base_js(), ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        """Criterio de aceptación 5 del plan, acotado a los módulos base."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    def test_modulos_compartidos_solo_exponen_su_namespace(self):
        expected = {
            "catalog-crud.js": "window.AdhocCatalogCrud",
            "table-filter.js": "window.AdhocTableFilter",
            "user-picker.js": "window.AdhocUserPicker",
        }
        for path in _base_js():
            if path.name not in expected:
                continue
            text = path.read_text(encoding="utf-8")
            assignments = set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M))
            assert assignments == {expected[path.name]}, (path.name, assignments)

    def test_css_no_redefine_clases_de_bootstrap(self):
        """Plan §6.4: pisar .form-control o .card rompe media UI."""
        css = (STATIC_DIR / "css" / "adhoc.css").read_text(encoding="utf-8")
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
                assert not prohibidas.search(" " + part), part

    def test_css_comentarios_no_cierran_sobre_un_token(self):
        """Gotcha real del repo: un cierre de comentario pegado a un comodín."""
        css = (STATIC_DIR / "css" / "adhoc.css").read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    def test_css_define_los_tokens_de_estado(self):
        css = _strip_css_comments((STATIC_DIR / "css" / "adhoc.css").read_text(encoding="utf-8"))
        for token in ("state-white", "state-red", "state-yellow", "state-green"):
            assert f"--adhoc-{token}:" in css
        # y NO las clases .bg-blanco/.bg-rojo del legacy, que chocan con Bootstrap
        for legacy in (".bg-blanco", ".bg-rojo", ".bg-amarillo", ".bg-verde"):
            assert legacy not in css


# ==========================================================================
# Render de extremo a extremo por HTTP
# ==========================================================================

@pytest.fixture()
def dashboard_ready():
    """Deja ``/adhoc/dashboard`` renderizable sobre el ``client`` de este módulo.

    Desde la fase de cableado esa URL la sirve el dashboard REAL
    (`pages/dashboard.py`), no el placeholder de F0. Aquí el `client` es la app
    completa con un ``get_db`` que devuelve un ``MagicMock``, así que hay que
    parchear las dos cosas que tocan BD:

    * ``cached_has_assignment`` / ``cached_perms`` — el gate ``require_page_app``
      NO lo bypasea un JWT con ``role="admin"`` (eso solo vale para
      ``require_perms``), y sobre un mock revienta con TypeError.
    * ``get_dashboard_tasks`` — el tablero en sí. Con lista vacía el resto de la
      página (nav, appbar, estáticos), que es lo único que se comprueba aquí, se
      renderiza igual.
    """
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with patch(
        "itcj2.core.services.authz_cache.cached_has_assignment",
        side_effect=lambda *a, **k: True,
    ), patch(
        "itcj2.core.services.authz_cache.cached_perms",
        side_effect=lambda *a, **k: set(DB_PAGE_PERMS),
    ), patch.object(AdhocTaskService, "get_dashboard_tasks", return_value=[]):
        yield


class TestPaginaBase:
    def test_raiz_redirige_al_dashboard(self, client, admin_headers):
        res = client.get("/adhoc/", headers=admin_headers, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["location"] == "/adhoc/dashboard"

    def test_dashboard_renderiza_con_nav(self, client, admin_headers, dashboard_ready):
        res = client.get("/adhoc/dashboard", headers=admin_headers)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        html = res.text
        assert "adhoc-appbar" in html
        for _label, _icon, url, _perms in NAV_SECTIONS:
            assert f'href="{url}"' in html

    def test_dashboard_carga_los_estaticos_versionados(self, client, admin_headers, dashboard_ready):
        html = client.get("/adhoc/dashboard", headers=admin_headers).text
        assert "/static/adhoc/css/adhoc.css?v=" in html
        assert "/static/adhoc/js/adhoc-utils.js?v=" in html

    def test_anonimo_va_al_login(self, client):
        res = client.get("/adhoc/dashboard", follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

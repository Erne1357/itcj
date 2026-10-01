"""Tests de las páginas del **Panel de Control** de Calidad (fase F5/F6).

Cubre las seis rutas de la sección panel, su gate de permisos, el filtrado de
las tarjetas y las reglas duras del plan (§6.2/§6.3/§6.4) sobre los archivos
propios de esta sección.

Cableado: ``pages/router.py`` es de la fase siguiente y no puede tocarse desde
aquí, así que el fixture monta el router del panel sobre la app real. Si la fase
de cableado ya lo incluyó, el fixture lo detecta y no lo monta dos veces.

Harness (plan §9.1):

* el error del cliente es ``{"error": …, "status": …}``, no ``{"detail": …}``;
* un JWT con ``role="admin"`` **no** bypasea ``require_page_app`` (a diferencia
  de ``require_perms``): esa dependencia siempre consulta
  ``cached_has_assignment``/``cached_perms``, así que hay que parchearlas;
* las páginas devuelven **HTML** (403 renderizado, 302 al login), nunca JSON.
"""
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.sgi.sgc.pages.panel import (
    SGC_APP_ROLE_LABELS,
    ALL_PERMS,
    CONFIG_GROUPS,
    PANEL_TILES,
    _config_groups_for,
    _tiles_for,
    user_perms,
)
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "sgi" / "sgc"
TEMPLATES_DIR = APP_ROOT / "templates" / "sgc" / "panel"
CSS_DIR = APP_ROOT / "static" / "css" / "panel"
JS_DIR = APP_ROOT / "static" / "js" / "panel"

AUTHZ_CACHE = "itcj2.core.services.authz_cache"
AUTHZ_SERVICE = "itcj2.core.services.authz_service.get_user_permissions_for_app"

#: (url, permiso de página) — la tabla del plan §4 para la sección panel.
PAGES = [
    ("/sgi/sgc/panel", "sgi.sgc.panel.page.view"),
    ("/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list"),
    ("/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list"),
    ("/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list"),
    ("/sgi/sgc/panel/configuracion", "sgi.sgc.panel.page.view"),
    ("/sgi/sgc/panel/correo", "sgi.sgc.mail.page.view"),
]

PAGE_URLS = [url for url, _perm in PAGES]


# ==========================================================================
# Fixtures y utilidades
# ==========================================================================

@pytest.fixture(scope="module")
def client():
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()

        # El router del panel se monta aquí porque pages/router.py lo cablea la
        # fase siguiente. Guarda de idempotencia por si ya está cableado.
        existing = {getattr(route, "path", None) for route in app.routes}
        if "/sgi/sgc/panel" not in existing:
            from itcj2.apps.sgi.sgc.pages.panel import router as panel_router

            app.include_router(panel_router, prefix="/sgi/sgc", tags=["sgi-pages"])

        mock_db = MagicMock()

        def _override():
            yield mock_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


def _headers(role="staff", user_id=300):
    return {"Cookie": f"itcj_token={make_jwt(user_id=user_id, role=role)}"}


@contextmanager
def granted(*perms):
    """El usuario tiene acceso a la app y exactamente estos permisos.

    Parchea las dos funciones que consulta ``require_page_app`` **y** la que usa
    la página para decidir qué pintar, de modo que el gate y la UI vean lo mismo.
    """
    codes = set(perms)
    with patch(f"{AUTHZ_CACHE}.cached_has_assignment", return_value=True), \
         patch(f"{AUTHZ_CACHE}.cached_perms", return_value=codes), \
         patch(AUTHZ_SERVICE, return_value=codes):
        yield


@contextmanager
def no_app_access():
    with patch(f"{AUTHZ_CACHE}.cached_has_assignment", return_value=False):
        yield


def get_page(client, url, *perms, role="staff"):
    with granted(*perms):
        return client.get(url, headers=_headers(role=role))


# ==========================================================================
# Rutas, autenticación y autorización
# ==========================================================================

class TestGate:
    @pytest.mark.parametrize("url", PAGE_URLS)
    def test_ruta_registrada(self, client, url):
        """No 404/405: la ruta existe con método GET."""
        with granted():
            resp = client.get(url, headers=_headers())
        assert resp.status_code not in (404, 405)

    @pytest.mark.parametrize("url", PAGE_URLS)
    def test_anonimo_va_al_login(self, client, url):
        """Bug #25 del legacy: `@login_required` encima de `@route` no protegía."""
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/itcj/login" in resp.headers["location"]

    @pytest.mark.parametrize("url", PAGE_URLS)
    def test_sin_acceso_a_la_app_es_403_html(self, client, url):
        with no_app_access():
            resp = client.get(url, headers=_headers())
        assert resp.status_code == 403
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.parametrize("url,perm", PAGES)
    def test_permiso_exacto_abre_la_pagina(self, client, url, perm):
        """Los códigos son los de database/DML/sgi/init/02_insert_permissions.sql."""
        resp = get_page(client, url, perm)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.parametrize("url,perm", PAGES)
    def test_otro_permiso_de_la_app_no_abre_la_pagina(self, client, url, perm):
        """Tener la app no basta: el gate es por permiso de página."""
        resp = get_page(client, url, "sgi.sgc.dashboard.page.view")
        assert resp.status_code == 403

    @pytest.mark.parametrize("url,perm", PAGES)
    def test_admin_global_necesita_el_permiso_real(self, client, url, perm):
        """`require_page_app` NO tiene bypass de admin global (sí lo tiene
        `require_perms`). Con la app pero sin el permiso, 403 incluso para admin."""
        with patch(f"{AUTHZ_CACHE}.cached_has_assignment", return_value=True), \
             patch(f"{AUTHZ_CACHE}.cached_perms", return_value=set()):
            resp = client.get(url, headers=_headers(role="admin", user_id=200))
        assert resp.status_code == 403


# ==========================================================================
# /sgi/sgc/panel — rejilla de tarjetas
# ==========================================================================

class TestPanelHome:
    def test_pinta_las_tarjetas_permitidas(self, client):
        resp = get_page(
            client, "/sgi/sgc/panel",
            "sgi.sgc.panel.page.view", "sgi.sgc.areas.page.list", "sgi.sgc.processes.page.list",
        )
        html = resp.text
        assert 'href="/sgi/sgc/panel/areas"' in html
        assert 'href="/sgi/sgc/panel/procesos"' in html
        assert 'href="/sgi/sgc/panel/configuracion"' in html

    def test_oculta_las_tarjetas_sin_permiso(self, client):
        resp = get_page(client, "/sgi/sgc/panel", "sgi.sgc.panel.page.view")
        html = resp.text
        assert 'href="/sgi/sgc/panel/areas"' not in html
        assert 'href="/sgi/sgc/panel/usuarios"' not in html
        assert 'href="/sgi/sgc/documentos/panel"' not in html
        # La suya sí: `Configuración` cuelga del mismo permiso que el panel.
        assert 'href="/sgi/sgc/panel/configuracion"' in html

    def test_tarjetas_muertas_del_legacy_no_se_portan(self, client):
        """"7 Herramientas" y "Soporte" no tenían destino ni hacían nada."""
        resp = get_page(client, "/sgi/sgc/panel", "sgi.sgc.panel.page.view")
        assert "Herramientas" not in resp.text
        assert "Soporte" not in resp.text

    def test_las_tarjetas_son_enlaces_no_divs_con_data_link(self, client):
        """El legacy usaba div.card + data-link + un querySelectorAll('.card')
        global que enganchaba también las tarjetas del layout."""
        resp = get_page(client, "/sgi/sgc/panel", "sgi.sgc.panel.page.view")
        assert "data-link" not in resp.text
        assert '<a class="sgi-tile"' in resp.text

    def test_no_carga_javascript_de_seccion(self, client):
        resp = get_page(client, "/sgi/sgc/panel", "sgi.sgc.panel.page.view")
        assert "/static/sgi/sgc/js/panel/" not in resp.text

    def test_sin_tarjetas_muestra_estado_vacio(self, client):
        """`sgi.sgc.panel.page.view` habilita "Configuración", así que para ver el
        estado vacío hay que abrir la página con el permiso pero sin el conjunto
        de la UI: se fuerza el conjunto vacío en el cálculo de permisos."""
        with patch(f"{AUTHZ_CACHE}.cached_has_assignment", return_value=True), \
             patch(f"{AUTHZ_CACHE}.cached_perms", return_value={"sgi.sgc.panel.page.view"}), \
             patch(AUTHZ_SERVICE, return_value=set()):
            resp = client.get("/sgi/sgc/panel", headers=_headers())
        assert resp.status_code == 200
        assert "No tienes secciones habilitadas" in resp.text


# ==========================================================================
# /sgi/sgc/panel/areas y /sgi/sgc/panel/procesos — el template compartido
# ==========================================================================

class TestColorCatalogs:
    def test_areas_configura_su_recurso(self, client):
        html = get_page(client, "/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list").text
        assert "data-sgi-color-catalog" in html
        assert 'data-sgi-resource="areas"' in html
        assert 'data-sgi-api="/api/sgi/v2/sgc/areas"' in html
        assert 'data-sgi-has-active="1"' in html
        assert 'data-sgi-has-description="0"' in html

    def test_procesos_configura_su_recurso(self, client):
        html = get_page(client, "/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list").text
        assert 'data-sgi-resource="processes"' in html
        assert 'data-sgi-api="/api/sgi/v2/sgc/processes"' in html
        assert 'data-sgi-has-active="0"' in html
        assert 'data-sgi-has-description="1"' in html

    def test_las_dos_pantallas_comparten_template_y_modulo(self, client):
        """Plan §6.5: `areas_conf.js` era una copia literal de `processes.js`."""
        areas = get_page(client, "/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list").text
        procs = get_page(client, "/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list").text
        for html in (areas, procs):
            assert "/static/sgi/sgc/js/panel/color-catalog.js?v=" in html
            assert "/static/sgi/sgc/css/panel/color-catalog.css?v=" in html

    def test_areas_tiene_columna_de_estado_y_procesos_no(self, client):
        areas = get_page(client, "/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list").text
        procs = get_page(client, "/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list").text
        assert 'data-sgi-filter-key="is_active"' in areas
        assert 'data-sgi-filter-key="is_active"' not in procs

    def test_procesos_edita_la_descripcion_como_campo_propio(self, client):
        """Bug #15: el legacy guardaba el color DENTRO de `description`."""
        html = get_page(client, "/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list").text
        assert 'data-sgi-edit-field="description"' in html
        assert 'data-sgi-edit-field="color"' in html

    def test_color_por_defecto_del_recurso(self, client):
        areas = get_page(client, "/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list").text
        procs = get_page(client, "/sgi/sgc/panel/procesos", "sgi.sgc.processes.page.list").text
        assert 'data-sgi-default-color="#4834d4"' in areas
        assert 'data-sgi-default-color="#b2bec3"' in procs

    def test_los_modales_son_de_bootstrap(self, client):
        """Los 17 modales caseros del legacy (`.modal-overlay` +
        `style.display='flex'`) desaparecen."""
        html = get_page(client, "/sgi/sgc/panel/areas", "sgi.sgc.areas.page.list").text
        assert "modal-overlay" not in html
        assert 'class="modal fade"' in html
        assert 'data-bs-dismiss="modal"' in html

    def test_botones_de_escritura_dependen_del_permiso(self, client):
        solo_lectura = get_page(client, "/sgi/sgc/panel/areas",
                                "sgi.sgc.areas.page.list", "sgi.sgc.areas.api.read").text
        assert "data-sgi-catalog-new" not in solo_lectura
        assert "data-sgi-catalog-delete" not in solo_lectura

        completo = get_page(
            client, "/sgi/sgc/panel/areas",
            "sgi.sgc.areas.page.list", "sgi.sgc.areas.api.create",
            "sgi.sgc.areas.api.update", "sgi.sgc.areas.api.delete",
        ).text
        assert "data-sgi-catalog-new" in completo
        assert "data-sgi-catalog-delete" in completo
        assert 'data-sgi-can-update="1"' in completo


# ==========================================================================
# /sgi/sgc/panel/usuarios — el módulo recortado (D8)
# ==========================================================================

class TestUsersPage:
    def test_no_porta_el_alta_ni_el_cambio_de_contrasena(self, client):
        """El formulario del legacy era anónimo y creaba admins globales."""
        html = get_page(client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list").text
        assert 'type="password"' not in html
        assert "Contraseña" not in html
        assert "/api/usuarios/" not in html

    def test_enlaza_a_la_configuracion_del_core(self, client):
        html = get_page(client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list").text
        assert 'href="/itcj/config"' in html

    def test_no_pinta_datos_de_usuario_desde_jinja(self, client):
        """Las filas las trae GET /users; el legacy serializaba las áreas a un
        literal JS sin escapar."""
        html = get_page(client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list").text
        assert 'data-sgi-api="/api/sgi/v2/sgc/users"' in html
        assert 'data-sgi-areas-api="/api/sgi/v2/sgc/areas"' in html
        assert "<option" not in html.split("sgi-page-data")[0]

    def test_expone_los_roles_en_el_bloque_json(self, client):
        html = get_page(client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list").text
        assert 'id="sgi-page-data" type="application/json"' in html
        for role in SGC_APP_ROLE_LABELS:
            assert role in html

    def test_los_modales_dependen_del_permiso(self, client):
        solo_lectura = get_page(client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list").text
        assert 'data-sgi-users-modal="role"' not in solo_lectura
        assert 'data-sgi-users-modal="areas"' not in solo_lectura
        assert 'data-sgi-filter-key="actions"' not in solo_lectura

        completo = get_page(
            client, "/sgi/sgc/panel/usuarios", "sgi.sgc.users.page.list",
            "sgi.sgc.users.api.assign_role", "sgi.sgc.users.api.assign_areas",
        ).text
        assert 'data-sgi-users-modal="role"' in completo
        assert 'data-sgi-users-modal="areas"' in completo
        assert 'data-sgi-filter-key="actions"' in completo


# ==========================================================================
# /sgi/sgc/panel/configuracion y /sgi/sgc/panel/correo
# ==========================================================================

class TestConfigPage:
    def test_enlaza_los_catalogos_permitidos(self, client):
        html = get_page(
            client, "/sgi/sgc/panel/configuracion",
            "sgi.sgc.panel.page.view", "sgi.sgc.doc_catalogs.page.list",
            "sgi.sgc.flows.page.list", "sgi.sgc.mail.page.view",
        ).text
        assert 'href="/sgi/sgc/documentos/categorias"' in html
        assert 'href="/sgi/sgc/documentos/clasificaciones"' in html
        assert 'href="/sgi/sgc/documentos/flujos"' in html
        assert 'href="/sgi/sgc/panel/correo"' in html

    def test_oculta_grupos_completos_sin_permiso(self, client):
        html = get_page(client, "/sgi/sgc/panel/configuracion",
                        "sgi.sgc.panel.page.view", "sgi.sgc.mail.page.view").text
        assert 'href="/sgi/sgc/documentos/categorias"' not in html
        assert 'href="/sgi/sgc/incidencias/categorias"' not in html
        assert 'href="/sgi/sgc/panel/correo"' in html

    def test_sin_ningun_catalogo_muestra_estado_vacio(self, client):
        html = get_page(client, "/sgi/sgc/panel/configuracion", "sgi.sgc.panel.page.view").text
        assert "No tienes catálogos habilitados." in html


class TestMailPage:
    def test_interruptor_es_el_switch_del_legacy(self, client):
        """El interruptor es el `.switch`/`.slider` del legacy, prefijado y con
        su CSS en panel/mail.css — NO el `.form-switch` de Bootstrap (la app ya
        no carga Bootstrap). Lo que sigue sin portarse es el modal casero de
        éxito: el guardado avisa con un toast."""
        html = get_page(client, "/sgi/sgc/panel/correo", "sgi.sgc.mail.page.view",
                        "sgi.sgc.mail.api.update").text
        assert 'class="sgi-switch"' in html
        assert 'class="sgi-switch-slider"' in html
        assert "data-sgi-mail-toggle" in html
        assert "modal-success" not in html

    def test_apunta_a_la_api_v2(self, client):
        html = get_page(client, "/sgi/sgc/panel/correo", "sgi.sgc.mail.page.view").text
        assert 'data-sgi-api="/api/sgi/v2/sgc/mail-config"' in html
        assert "/api/mail/config" not in html

    def test_sin_permiso_de_escritura_queda_en_solo_lectura(self, client):
        html = get_page(client, "/sgi/sgc/panel/correo", "sgi.sgc.mail.page.view").text
        assert "data-sgi-mail-save" not in html
        assert "disabled" in html
        assert 'data-sgi-can-update="0"' in html

    def test_con_permiso_aparece_el_boton_de_guardar(self, client):
        html = get_page(client, "/sgi/sgc/panel/correo",
                        "sgi.sgc.mail.page.view", "sgi.sgc.mail.api.update").text
        assert "data-sgi-mail-save" in html
        assert 'data-sgi-can-update="1"' in html


# ==========================================================================
# Shell común: nav y estáticos versionados
# ==========================================================================

class TestShell:
    @pytest.mark.parametrize("url,perm", PAGES)
    def test_inyecta_el_nav_filtrado(self, client, url, perm):
        """Regla dura del encargo: toda página pasa nav=nav_for_user(db, user)."""
        with granted(perm, "sgi.sgc.dashboard.page.view"):
            html = client.get(url, headers=_headers()).text
        assert "sgi-appbar" in html
        assert 'href="/sgi/sgc/dashboard"' in html

    @pytest.mark.parametrize("url,perm", PAGES)
    def test_estaticos_versionados(self, client, url, perm):
        html = get_page(client, url, perm).text
        assert "/static/sgi/sgc/css/sgc.css?v=" in html
        for match in re.finditer(r'/static/sgi/sgc/(?:css|js)/panel/[\w.-]+', html):
            assert f"{match.group(0)}?v=" in html, match.group(0)

    @pytest.mark.parametrize("url,perm", PAGES)
    def test_sin_estilos_ni_handlers_inline_en_la_respuesta(self, client, url, perm):
        html = get_page(client, url, perm).text
        assert "<style" not in html
        assert 'style="' not in html
        assert "onclick=" not in html
        assert "onchange=" not in html


# ==========================================================================
# Unidades: filtrado de tarjetas y cálculo de permisos
# ==========================================================================

class TestTiles:
    def test_todos_los_permisos_referenciados_existen_en_el_dml(self):
        """Un permiso mal escrito deja la tarjeta invisible sin fallar en test."""
        sql = (
            Path(__file__).resolve().parents[3]
            / "database" / "DML" / "sgc" / "init" / "02_insert_permissions.sql"
        )
        if not sql.exists():                      # database/ está gitignored
            pytest.skip("el DML de sgc no está en este árbol")
        codes = set(re.findall(r"'(sgc\.[a-z_.]+)'", sql.read_text(encoding="utf-8")))
        for _title, _icon, _url, _text, needed in PANEL_TILES:
            assert needed <= codes, needed
        for group in CONFIG_GROUPS:
            for _label, _url, needed in group["links"]:
                assert needed <= codes, needed

    def test_las_urls_de_las_tarjetas_son_literales_bajo_sgc(self):
        for _title, _icon, url, _text, _perms in PANEL_TILES:
            assert url.startswith("/sgi/sgc/"), url
        for group in CONFIG_GROUPS:
            for _label, url, _perms in group["links"]:
                assert url.startswith("/sgi/sgc/"), url

    def test_iconos_son_font_awesome_con_la_clase_completa(self):
        """La app usa Font Awesome 6.4, igual que el legacy (decisión visual de
        la fase de porte: fuera Bootstrap Icons). El icono se guarda con la
        clase COMPLETA porque las plantillas lo escupen tal cual en `class=`."""
        for _title, icon, _url, _text, _perms in PANEL_TILES:
            assert icon.startswith(("fa-solid ", "fa-regular ")), icon
        for group in CONFIG_GROUPS:
            assert group["icon"].startswith(("fa-solid ", "fa-regular ")), group["icon"]

    def test_admin_global_ve_todas_las_tarjetas(self):
        assert len(_tiles_for(ALL_PERMS)) == len(PANEL_TILES)
        assert len(_config_groups_for(ALL_PERMS)) == len(CONFIG_GROUPS)

    def test_sin_permisos_no_hay_tarjetas(self):
        assert _tiles_for(frozenset()) == []
        assert _config_groups_for(frozenset()) == []

    def test_un_grupo_de_configuracion_sin_enlaces_no_se_pinta(self):
        groups = _config_groups_for({"sgi.sgc.mail.page.view"})
        assert [g["title"] for g in groups] == ["Funciones"]
        assert len(groups[0]["links"]) == 1

    def test_indicadores_basta_con_uno_de_los_dos_permisos(self):
        titles = [t["title"] for t in _tiles_for({"sgi.sgc.indicators.page.manage"})]
        assert titles == ["Indicadores"]


class TestUserPerms:
    def test_admin_global_lo_tiene_todo(self):
        perms = user_perms(MagicMock(), {"sub": "1", "role": "admin"})
        assert perms is ALL_PERMS
        assert "cualquier.cosa" in perms

    def test_usuario_normal_consulta_sus_permisos(self):
        with patch(AUTHZ_SERVICE, return_value={"sgi.sgc.areas.page.list"}) as spy:
            perms = user_perms(MagicMock(), {"sub": "7", "role": "staff"})
        assert perms == {"sgi.sgc.areas.page.list"}
        assert spy.call_args[0][2] == "sgi"

    def test_sin_usuario_no_hay_permisos(self):
        assert user_perms(MagicMock(), None) == frozenset()

    def test_error_al_calcular_es_fail_closed(self):
        """Pintar el panel completo sería un fallo ABIERTO: enlaces a un 403."""
        with patch(AUTHZ_SERVICE, side_effect=RuntimeError("sin BD")):
            assert user_perms(MagicMock(), {"sub": "7", "role": "staff"}) == frozenset()

    def test_sub_invalido_es_fail_closed(self):
        assert user_perms(MagicMock(), {"sub": "no-es-un-int"}) == frozenset()


# ==========================================================================
# Reglas duras del plan sobre los archivos de esta sección
# ==========================================================================

def _strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


PANEL_TEMPLATES = sorted(TEMPLATES_DIR.glob("*.html"))
PANEL_CSS = sorted(CSS_DIR.glob("*.css"))
PANEL_JS = sorted(JS_DIR.glob("*.js"))


class TestReglasDuras:
    def test_los_archivos_de_la_seccion_existen(self):
        assert {p.name for p in PANEL_TEMPLATES} == {
            "panel.html", "color_catalog.html", "users.html", "config.html", "mail.html",
        }
        assert {p.name for p in PANEL_CSS} == {
            "panel.css", "color-catalog.css", "users.css", "config.css", "mail.css",
        }
        assert {p.name for p in PANEL_JS} == {
            "color-catalog.js", "users.js", "mail.js",
        }

    @pytest.mark.parametrize("path", PANEL_TEMPLATES, ids=lambda p: p.name)
    def test_templates_sin_css_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    @pytest.mark.parametrize("path", PANEL_TEMPLATES, ids=lambda p: p.name)
    def test_templates_sin_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "onclick=" not in text
        assert "onchange=" not in text

    @pytest.mark.parametrize("path", PANEL_TEMPLATES, ids=lambda p: p.name)
    def test_templates_extienden_el_base(self, path):
        text = path.read_text(encoding="utf-8")
        assert '{% extends "sgc/base_sgc.html" %}' in text

    @pytest.mark.parametrize("path", PANEL_TEMPLATES, ids=lambda p: p.name)
    def test_el_unico_script_inline_es_el_bloque_json(self, path):
        """Plan §6.2: nada de constantes concatenadas ni <option> prerrenderizados."""
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for tag in re.findall(r"<script[^>]*>", text):
            assert "src=" in tag or 'type="application/json"' in tag, tag

    @pytest.mark.parametrize("path", PANEL_JS, ids=lambda p: p.name)
    def test_js_es_iife_estricto(self, path):
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", PANEL_JS, ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        """Criterio de aceptación 5 del plan. El legacy tenía 14."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    def test_cada_modulo_expone_un_solo_namespace(self):
        expected = {
            "color-catalog.js": "window.SgcColorCatalog",
            "users.js": "window.SgcPanelUsers",
            "mail.js": "window.SgcPanelMail",
        }
        for path in PANEL_JS:
            text = path.read_text(encoding="utf-8")
            assignments = set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M))
            assert assignments == {expected[path.name]}, (path.name, assignments)

    @pytest.mark.parametrize("path", PANEL_JS, ids=lambda p: p.name)
    def test_js_pega_a_la_api_v2(self, path):
        """Bug #20: 9 URLs del legacy tenían el prefijo `/app_prueba/api/…`.

        Se mira el CÓDIGO, no la prosa: los comentarios citan las URLs viejas a
        propósito para dejar constancia de qué se corrigió."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        assert "/app_prueba/" not in text
        for url in re.findall(r"'(/api/[\w/-]+)'", text):
            assert url.startswith("/api/sgi/v2/sgc/"), url

    @pytest.mark.parametrize("path", PANEL_CSS, ids=lambda p: p.name)
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
                assert not prohibidas.search(" " + part), part

    @pytest.mark.parametrize("path", PANEL_CSS, ids=lambda p: p.name)
    def test_css_comentarios_no_cierran_sobre_un_token(self, path):
        """Gotcha real del repo: `-*/` dentro de un comentario rompe el bloque
        siguiente y deja las variables sin definir."""
        css = path.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    @pytest.mark.parametrize("path", PANEL_CSS, ids=lambda p: p.name)
    def test_css_usa_los_tokens_y_no_hex_sueltos(self, path):
        """Plan §6.4: los 45 hex repetidos del legacy pasan a tokens --sgi-*."""
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r":\s*#[0-9a-fA-F]{3,8}\b", css), path.name

    @pytest.mark.parametrize("path", PANEL_CSS, ids=lambda p: p.name)
    def test_todas_las_clases_propias_van_prefijadas(self, path):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for selector in re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M):
            first = selector.split(",")[0].strip().split()[0]
            assert first.startswith(".sgi-"), selector

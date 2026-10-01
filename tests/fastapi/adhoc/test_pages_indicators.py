"""Tests de las páginas de **indicadores** de Calidad (fase F5/F6, sección
"indicadores").

Cubre las tres rutas del plan §4:

===================================================  ==============================
URL                                                  Permiso de página
===================================================  ==============================
``GET /adhoc/indicadores?mode=config|tracking``      ``adhoc.indicators.page.list``
``GET /adhoc/indicadores/{year_id}/tablero``         ``adhoc.indicators.page.manage``
``GET /adhoc/indicadores/{year_id}/seguimiento``     ``adhoc.indicators.page.tracking``
===================================================  ==============================

Regresiones obligatorias que quedan fijadas aquí (una por bug del legacy):

* **#26 — ``is_admin=True`` hardcodeado.** La vista de seguimiento del legacy
  pisaba la bandera real en el contexto, de modo que la plantilla habilitaba
  los inputs y pintaba el ``<select>`` de color para *cualquiera*. Ahora
  ``can_edit`` sale de ``adhoc.indicators.api.tracking``: sin ese permiso la
  rejilla es de solo lectura. Ver ``TestSeguridadDeSeguimiento``.
* **#16 — los 4 umbrales en un string ``"b-r-a-v"``.** Se comprueba que viajan
  como cuatro campos y que un umbral **con guion** sobrevive intacto.
* **``'Semanal'`` inalcanzable.** El ``<select>`` de frecuencia del legacy solo
  ofrecía Mensual y Anual aunque el render reconociera la semanal.
* **XSS por ``htmlProcesos``.** Los procesos ya no se inyectan como HTML crudo.

Harness (plan §9.1): las páginas devuelven HTML (403 renderizado, 302 al login),
nunca JSON. Ojo con una asimetría real de ``itcj2/dependencies.py``: a
diferencia de ``require_perms``, **``require_page_app`` NO tiene bypass de admin
global** — comprueba ``cached_has_assignment``/``cached_perms`` para todo el
mundo. Por eso el fixture ``authz`` los parchea siempre (si no, con la sesión
``MagicMock`` del harness la autorización acabaría en la BD real), y
``as_user(perms)`` los re-parchea dentro del test para probar el gate.
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.pages.indicators import (
    MODE_CONFIG,
    MODE_PAGE_PERM,
    MODE_PATH_SUFFIX,
    MODE_TRACKING,
    PERIODS_FALLBACK,
    _tracking_cards,
    router as indicators_router,
)
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATES_DIR = APP_ROOT / "templates" / "adhoc" / "indicators"
CSS_DIR = APP_ROOT / "static" / "css" / "indicators"
JS_DIR = APP_ROOT / "static" / "js" / "indicators"

SERVICE = "itcj2.apps.adhoc.services.indicator_service.IndicatorService"
CATALOG = "itcj2.apps.adhoc.services.catalog_service.AdhocCatalogService"
AUTHZ_CACHE = "itcj2.core.services.authz_cache"
AUTHZ_SERVICE = "itcj2.core.services.authz_service"

URL_YEARS = "/adhoc/indicadores"
URL_BOARD = "/adhoc/indicadores/7/tablero"
URL_TRACKING = "/adhoc/indicadores/7/seguimiento"

#: Los nueve permisos de indicadores que sembró el DML de F2.
ALL_PERMS = {
    "adhoc.indicators.page.list",
    "adhoc.indicators.page.manage",
    "adhoc.indicators.page.tracking",
    "adhoc.indicators.api.read",
    "adhoc.indicators.api.create",
    "adhoc.indicators.api.update",
    "adhoc.indicators.api.delete",
    "adhoc.indicators.api.download",
    "adhoc.indicators.api.tracking",
}

#: El paquete de **lectura** de indicadores: lo que el DML da a ``consult`` y,
#: desde B7, también a los tres supervisores. Ni ``page.manage`` (editar la
#: ficha del indicador sigue siendo de admin) ni ``api.tracking`` (capturar el
#: color de la celda). Es exactamente el perfil que destapó A27/A28.
READ_ONLY_PERMS = {
    "adhoc.indicators.page.list",
    "adhoc.indicators.page.tracking",
    "adhoc.indicators.api.read",
    "adhoc.indicators.api.download",
}


# ==========================================================================
# Dobles de prueba
# ==========================================================================

class FakeYear:
    def __init__(self, id=7, year=2026):
        self.id = id
        self.year = year


class FakeProcess:
    def __init__(self, id=1, name="Servicios escolares", color="#4834d4"):
        self.id = id
        self.name = name
        self.color = color


class FakeTracking:
    def __init__(self, period_index, real_value=None, color="blanco"):
        self.period_index = period_index
        self.real_value = real_value
        self.color = color


class FakeIndicator:
    """Doble del modelo, con los atributos que leen ``IndicatorOut`` y la vista."""

    def __init__(self, **kw):
        self.id = kw.get("id", 100)
        self.year_id = kw.get("year_id", 7)
        self.process_id = kw.get("process_id", 1)
        self.process = kw.get("process", FakeProcess())
        self.objective = kw.get("objective", "Reducir el tiempo de atención")
        self.prev_results = kw.get("prev_results", "85%")
        self.unit_calc = kw.get("unit_calc", "(Resueltos / Totales) * 100")
        self.responsible = kw.get("responsible", "Ana Ruiz")
        self.facilitator = kw.get("facilitator", "Sistemas")
        self.source = kw.get("source", "ERP")
        self.strategic_rel = kw.get("strategic_rel", "Eje 2")
        self.criteria = kw.get("criteria", "Medición mensual")
        self.plan_b = kw.get("plan_b", "Reforzar turno vespertino")
        self.frequency = kw.get("frequency", "Mensual")
        self.planned_white = kw.get("planned_white", "80%")
        self.planned_red = kw.get("planned_red", "< 70%")
        self.planned_yellow = kw.get("planned_yellow", "70% a 85%")
        self.planned_green = kw.get("planned_green", "> 85%")
        self.document_url = kw.get("document_url", None)
        self.trackings = kw.get("trackings", [])
        self.created_at = None
        self.updated_at = None


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(scope="module")
def client():
    """App real + el router de la sección montado bajo ``/adhoc``.

    El cableado de ``pages/router.py`` es de la fase siguiente y lo hace un
    único dueño (regla de concurrencia del plan §10), así que aquí se monta el
    router de la sección tal cual, con el mismo prefijo que le pondrá el padre.
    """
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()
        app.include_router(indicators_router, prefix="/adhoc")

        mock_db = MagicMock()

        def _override():
            yield mock_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


class _AuthzPatches:
    """Parchea los tres puntos de autorización que tocan estas páginas.

    Se parchea el **módulo fuente**, no el consumidor: ``require_page_app`` y
    ``_perm_checker`` importan de ``authz_cache`` dentro de la función, y
    ``pages/nav.py`` importa ``get_user_permissions_for_app`` de
    ``authz_service``.
    """

    def __init__(self, perms, has_app=True):
        self.perms = set(perms)
        self.has_app = has_app
        self._patches = []

    def __enter__(self):
        self._patches = [
            patch(f"{AUTHZ_CACHE}.cached_has_assignment", return_value=self.has_app),
            patch(f"{AUTHZ_CACHE}.cached_perms", return_value=self.perms),
            patch(f"{AUTHZ_SERVICE}.get_user_permissions_for_app", return_value=self.perms),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def as_user(perms, has_app=True):
    """Context manager: usuario con acceso a la app y exactamente esos permisos."""
    return _AuthzPatches(perms, has_app)


@pytest.fixture(autouse=True)
def authz():
    """Por defecto, un usuario con TODOS los permisos de indicadores.

    Sin esto, ``require_page_app`` llamaría a la autorización real con la sesión
    ``MagicMock`` del harness. Los tests que prueban el gate abren su propio
    ``as_user(...)`` encima (el patch anida y el interior gana)."""
    with as_user(ALL_PERMS):
        yield


@pytest.fixture()
def admin_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    return {"Cookie": f"itcj_token={make_jwt(user_id=201, role='staff')}"}


@pytest.fixture()
def year():
    return FakeYear()


@pytest.fixture()
def data_ok(year):
    """Service y catálogo parcheados con un año y un indicador mensual."""
    indicator = FakeIndicator(trackings=[FakeTracking(3, "78", "amarillo")])
    with patch(f"{SERVICE}.get_year", return_value=year), \
         patch(f"{SERVICE}.list_years", return_value=[(year, 4)]), \
         patch(f"{SERVICE}.list_indicators", return_value=[indicator]), \
         patch(f"{CATALOG}.list_items", return_value=[FakeProcess()]):
        yield indicator


def with_indicators(year, indicators, processes=None):
    """Atajo: parchea el service con esta lista concreta de fichas."""
    return _Patches([
        patch(f"{SERVICE}.get_year", return_value=year),
        patch(f"{SERVICE}.list_indicators", return_value=indicators),
        patch(f"{CATALOG}.list_items", return_value=processes or [FakeProcess()]),
    ])


class _Patches:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def page_data(html: str) -> dict:
    """Extrae el bloque ``<script id="adhoc-page-data" type="application/json">``."""
    match = re.search(
        r'<script id="adhoc-page-data" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert match, "la página no emitió el bloque adhoc-page-data"
    return json.loads(match.group(1))


# ==========================================================================
# Gate de las tres páginas
# ==========================================================================

@pytest.mark.parametrize("url", [URL_YEARS, URL_BOARD, URL_TRACKING])
class TestGate:
    def test_anonimo_va_al_login(self, client, url):
        res = client.get(url, follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

    def test_sin_acceso_a_la_app_es_403_html(self, client, staff_headers, url, data_ok):
        with as_user(ALL_PERMS, has_app=False):
            res = client.get(url, headers=staff_headers)
        assert res.status_code == 403
        assert "text/html" in res.headers["content-type"]

    def test_con_la_app_pero_sin_el_permiso_de_pagina_es_403(
        self, client, staff_headers, url, data_ok
    ):
        # Tiene todos los permisos de API, ninguno de página.
        with as_user({p for p in ALL_PERMS if ".page." not in p}):
            res = client.get(url, headers=staff_headers)
        assert res.status_code == 403
        assert "text/html" in res.headers["content-type"]

    def test_con_el_permiso_de_pagina_entra(self, client, admin_headers, url, data_ok):
        res = client.get(url, headers=admin_headers)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]


@pytest.mark.parametrize("url", [URL_YEARS, URL_BOARD, URL_TRACKING])
def test_cada_pagina_pinta_el_nav_y_los_estaticos_versionados(
    client, admin_headers, url, data_ok
):
    html = client.get(url, headers=admin_headers).text
    assert "adhoc-appbar" in html
    assert 'href="/adhoc/indicadores?mode=tracking"' in html      # item del nav
    assert "/static/adhoc/css/adhoc.css?v=" in html
    assert "/static/adhoc/js/adhoc-utils.js?v=" in html
    # y la hoja/módulo propios de la página, también versionados
    assert re.search(r"/static/adhoc/css/indicators/\w+\.css\?v=", html)
    assert re.search(r"/static/adhoc/js/indicators/\w+\.js\?v=", html)


# ==========================================================================
# GET /adhoc/indicadores
# ==========================================================================

class TestPaginaAnios:
    def test_modo_por_defecto_es_configuracion(self, client, admin_headers, data_ok):
        data = page_data(client.get(URL_YEARS, headers=admin_headers).text)
        assert data["mode"] == MODE_CONFIG
        assert data["target_suffix"] == "/tablero"
        assert data["target_base"] == "/adhoc/indicadores/"

    def test_modo_seguimiento(self, client, admin_headers, data_ok):
        data = page_data(
            client.get(URL_YEARS + "?mode=tracking", headers=admin_headers).text
        )
        assert data["mode"] == MODE_TRACKING
        assert data["target_suffix"] == "/seguimiento"

    def test_modo_desconocido_cae_en_configuracion(self, client, admin_headers, data_ok):
        """El legacy arrastraba el valor crudo del querystring sin validarlo."""
        data = page_data(
            client.get(URL_YEARS + "?mode=cualquier-cosa", headers=admin_headers).text
        )
        assert data["mode"] == MODE_CONFIG

    def test_los_anios_viajan_con_su_conteo(self, client, admin_headers, data_ok):
        """El conteo sale de la misma consulta; el legacy tocaba anio.indicators
        dentro del bucle de la plantilla (un N+1 por tarjeta)."""
        data = page_data(client.get(URL_YEARS, headers=admin_headers).text)
        assert data["years"] == [{"id": 7, "year": 2026, "indicators_count": 4}]

    def test_con_permisos_de_escritura_se_ven_los_botones(
        self, client, admin_headers, data_ok
    ):
        html = client.get(URL_YEARS, headers=admin_headers).text
        data = page_data(html)
        assert "data-adhoc-years-new" in html
        assert data["can_create"] is True
        assert data["can_delete"] is True

    def test_sin_permiso_de_alta_no_hay_boton(self, client, staff_headers, data_ok):
        with as_user({"adhoc.indicators.page.list", "adhoc.indicators.page.manage"}):
            html = client.get(URL_YEARS, headers=staff_headers).text
        assert "data-adhoc-years-new" not in html
        data = page_data(html)
        assert data["can_create"] is False
        assert data["can_delete"] is False

    def test_el_modo_conmuta_si_falta_el_permiso_del_destino(
        self, client, staff_headers, data_ok
    ):
        """Enseñar un enlace que responde 403 es peor que llevar a donde sí entra."""
        with as_user({"adhoc.indicators.page.list", "adhoc.indicators.page.tracking"}):
            data = page_data(
                client.get(URL_YEARS + "?mode=config", headers=staff_headers).text
            )
        assert data["mode"] == MODE_TRACKING
        assert data["target_suffix"] == "/seguimiento"

    def test_sin_ningun_destino_las_filas_no_son_enlaces(
        self, client, staff_headers, data_ok
    ):
        with as_user({"adhoc.indicators.page.list"}):
            data = page_data(client.get(URL_YEARS, headers=staff_headers).text)
        assert data["target_base"] == ""

    def test_la_tabla_declara_sus_claves_de_filtro(self, client, admin_headers, data_ok):
        html = client.get(URL_YEARS, headers=admin_headers).text
        assert 'data-adhoc-table="adhoc-indicator-years"' in html
        assert 'data-adhoc-filter-input="year"' in html

    def test_el_modal_es_de_bootstrap(self, client, admin_headers, data_ok):
        html = client.get(URL_YEARS, headers=admin_headers).text
        assert 'id="adhoc-years-modal"' in html
        assert "modal fade" in html
        assert "modal-overlay" not in html


# ==========================================================================
# GET /adhoc/indicadores/{year_id}/tablero
# ==========================================================================

class TestPaginaTablero:
    def test_anio_inexistente_es_404_html(self, client, admin_headers):
        """El legacy envolvía el get_or_404 en un except Exception que lo tragaba."""
        with patch(f"{SERVICE}.get_year", return_value=None):
            res = client.get(URL_BOARD, headers=admin_headers)
        assert res.status_code == 404
        assert "text/html" in res.headers["content-type"]

    def test_los_cuatro_umbrales_son_cuatro_campos(self, client, admin_headers, data_ok):
        data = page_data(client.get(URL_BOARD, headers=admin_headers).text)
        ficha = data["indicators"][0]
        for key in ("planned_white", "planned_red", "planned_yellow", "planned_green"):
            assert key in ficha
        assert "planned_value" not in ficha

    def test_un_umbral_con_guion_sobrevive_intacto(self, client, admin_headers, year):
        """Bug #16: el legacy los concatenaba en "b-r-a-v" y los partía con split('-')."""
        indicador = FakeIndicator(
            planned_white="1-2 días", planned_red="-5%",
            planned_yellow="5-10%", planned_green="> 10-20%",
        )
        with with_indicators(year, [indicador]):
            ficha = page_data(
                client.get(URL_BOARD, headers=admin_headers).text
            )["indicators"][0]
        assert ficha["planned_white"] == "1-2 días"
        assert ficha["planned_red"] == "-5%"
        assert ficha["planned_yellow"] == "5-10%"
        assert ficha["planned_green"] == "> 10-20%"

    def test_el_selector_de_frecuencia_ofrece_semanal(self, client, admin_headers, data_ok):
        """El render del legacy la reconocía, pero su formulario no la ofrecía."""
        data = page_data(client.get(URL_BOARD, headers=admin_headers).text)
        assert data["frequencies"] == ["Semanal", "Mensual", "Anual"]

    def test_los_procesos_viajan_como_json_no_como_options(
        self, client, admin_headers, data_ok
    ):
        """`htmlProcesos` del legacy era HTML crudo dentro de un template literal."""
        html = client.get(URL_BOARD, headers=admin_headers).text
        assert "htmlProcesos" not in html
        assert '<option value="1">Servicios escolares</option>' not in html
        assert page_data(html)["processes"] == [
            {"id": 1, "name": "Servicios escolares", "color": "#4834d4"}
        ]

    def test_el_nombre_de_proceso_hostil_no_escapa_del_json(
        self, client, admin_headers, year
    ):
        hostil = FakeProcess(name='</script><img src=x onerror="alert(1)">')
        with with_indicators(year, [], processes=[hostil]):
            html = client.get(URL_BOARD, headers=admin_headers).text
        assert "</script><img" not in html
        assert 'onerror="alert(1)"' not in html
        assert page_data(html)["processes"][0]["name"] == hostil.name

    def test_las_fichas_no_arrastran_el_seguimiento(self, client, admin_headers, data_ok):
        """El tablero no pinta celdas: cargar los trackings sería peso muerto."""
        ficha = page_data(
            client.get(URL_BOARD, headers=admin_headers).text
        )["indicators"][0]
        assert ficha["trackings"] == []

    def test_flags_de_permiso_para_el_modulo(self, client, staff_headers, data_ok):
        with as_user({"adhoc.indicators.page.manage", "adhoc.indicators.api.update"}):
            data = page_data(client.get(URL_BOARD, headers=staff_headers).text)
        assert data["can_update"] is True
        assert data["can_create"] is False
        assert data["can_delete"] is False
        assert data["can_download"] is False

    def test_enlace_al_seguimiento_solo_con_permiso(self, client, staff_headers, data_ok):
        with as_user({"adhoc.indicators.page.manage"}):
            html = client.get(URL_BOARD, headers=staff_headers).text
        assert 'href="/adhoc/indicadores/7/seguimiento"' not in html

        with as_user({"adhoc.indicators.page.manage", "adhoc.indicators.page.tracking"}):
            html = client.get(URL_BOARD, headers=staff_headers).text
        assert 'href="/adhoc/indicadores/7/seguimiento"' in html


# ==========================================================================
# A27/A28 — el callejón sin salida del módulo de indicadores
#
# Las tres pantallas se enlazan entre sí y hasta B7 dos de esos enlaces se
# pintaban sin mirar el permiso del destino: el tablero ofrecía "Seguimiento" a
# quien no puede entrar al seguimiento, y el seguimiento ofrecía "Tablero" a
# quien no puede entrar al tablero. Con `hx-boost` un 403 no intercambia nada,
# así que el botón simplemente no hacía nada al pulsarlo: el peor 403 posible,
# el que no se ve.
#
# El agujero era más ancho de lo que decía el informe. `page.manage` y
# `page.tracking` los tenía SOLO `admin`, así que el callejón no era cosa de
# `consult`: también se lo comían los tres supervisores. La decisión de producto
# (cerrada por el usuario) es que el seguimiento por colores es la vista de
# LECTURA del indicador —lo reciben `consult` y los tres supervisores— mientras
# que `manage` (editar la ficha) sigue siendo de admin. `TestElDmlRepartelaLectura`
# fija esa matriz contra el SQL, que es su única fuente.
# ==========================================================================

class TestCallejonDeIndicadores:
    def test_lectura_sin_manage_aterriza_en_el_seguimiento(
        self, client, staff_headers, data_ok
    ):
        """El perfil de `consult` y de los tres supervisores, tal cual."""
        with as_user(READ_ONLY_PERMS):
            data = page_data(client.get(URL_YEARS, headers=staff_headers).text)
        assert data["mode"] == MODE_TRACKING
        assert data["target_suffix"] == "/seguimiento"

    def test_y_sus_filas_son_clicables(self, client, staff_headers, data_ok):
        """`target_base` vacía = filas muertas: `years.js` no les ata el click.

        Es la mitad que conmutar el modo no arregla por sí sola. Elegir el
        destino correcto no sirve de nada si la fila no lleva a ninguna parte, y
        en esta pantalla la fila **es** el enlace: no hay ningún otro botón.
        """
        with as_user(READ_ONLY_PERMS):
            data = page_data(client.get(URL_YEARS, headers=staff_headers).text)
        assert data["target_base"] == "/adhoc/indicadores/"

    def test_y_ese_destino_abre_de_verdad(self, client, staff_headers, data_ok):
        """Lo que ofrece la fila responde 200. Es la comprobación que cierra el
        círculo: sin ella el test anterior solo diría que hay un enlace."""
        with as_user(READ_ONLY_PERMS):
            res = client.get(URL_TRACKING, headers=staff_headers)
        assert res.status_code == 200

    def test_el_tablero_le_sigue_estando_vedado(self, client, staff_headers, data_ok):
        """Leer el seguimiento no es editar la ficha: `manage` no se regala."""
        with as_user(READ_ONLY_PERMS):
            res = client.get(URL_BOARD, headers=staff_headers)
        assert res.status_code == 403

    def test_el_tablero_no_ofrece_el_seguimiento_sin_ese_permiso(
        self, client, staff_headers, data_ok
    ):
        with as_user({"adhoc.indicators.page.manage"}):
            html = client.get(URL_BOARD, headers=staff_headers).text
        data = page_data(html)
        # La URL se cae del JSON, no solo su `can_`: dejarla puesta invitaba a
        # que el módulo la usara por su cuenta el día que navegue solo.
        assert data["tracking_url"] == ""
        assert data["can_track"] is False
        assert 'href="/adhoc/indicadores/7/seguimiento"' not in html

    def test_el_tablero_lo_ofrece_a_quien_si_entra(self, client, staff_headers, data_ok):
        with as_user({"adhoc.indicators.page.manage", "adhoc.indicators.page.tracking"}):
            html = client.get(URL_BOARD, headers=staff_headers).text
        data = page_data(html)
        assert data["tracking_url"] == "/adhoc/indicadores/7/seguimiento"
        assert data["can_track"] is True
        assert 'href="/adhoc/indicadores/7/seguimiento"' in html

    def test_el_seguimiento_no_ofrece_el_tablero_sin_manage(
        self, client, staff_headers, data_ok
    ):
        """El otro lado del espejo, y el que más gente se comía: los cuatro roles
        no-admin llegan al seguimiento y ninguno de ellos tiene `manage`."""
        with as_user(READ_ONLY_PERMS):
            html = client.get(URL_TRACKING, headers=staff_headers).text
        assert 'href="/adhoc/indicadores/7/tablero"' not in html

    def test_el_seguimiento_lo_ofrece_a_quien_si_entra(
        self, client, staff_headers, data_ok
    ):
        with as_user({"adhoc.indicators.page.tracking", "adhoc.indicators.page.manage"}):
            html = client.get(URL_TRACKING, headers=staff_headers).text
        assert 'href="/adhoc/indicadores/7/tablero"' in html

    def test_la_lista_no_ofrece_conmutar_a_un_modo_vedado(
        self, client, staff_headers, data_ok
    ):
        """El TERCER enlace cruzado, el que se quedó fuera del arreglo de B7.

        La lista de años pinta un "Ir a configuración / Ir a seguimiento" en su
        línea de ayuda. La plantilla lo decidía mirando `mode` y nada más, así
        que a los cuatro roles no-admin se les ofrecía "Ir a configuración" y
        pulsarlo devolvía la MISMA pantalla: `indicator_years_page` reconmuta el
        modo al no encontrar `page.manage`, y el enlace volvía a salir igual.
        """
        with as_user(READ_ONLY_PERMS):
            html = client.get(URL_YEARS, headers=staff_headers).text
        assert "adhoc-years-mode-swap" not in html
        assert 'href="/adhoc/indicadores?mode=config"' not in html

    def test_y_tampoco_pulsando_el_modo_que_no_puede(
        self, client, staff_headers, data_ok
    ):
        """Ni llegando a la URL del modo vedado: la conmutación no lo resucita."""
        with as_user(READ_ONLY_PERMS):
            html = client.get(URL_YEARS + "?mode=config", headers=staff_headers).text
        assert "adhoc-years-mode-swap" not in html

    def test_la_lista_lo_ofrece_a_quien_si_entra(self, client, staff_headers, data_ok):
        """Con los dos permisos el conmutador sigue ahí, y lleva al otro modo."""
        with as_user({"adhoc.indicators.page.list", *MODE_PAGE_PERM.values()}):
            en_config = client.get(URL_YEARS, headers=staff_headers).text
            en_tracking = client.get(
                URL_YEARS + "?mode=tracking", headers=staff_headers
            ).text
        assert 'href="/adhoc/indicadores?mode=tracking"' in en_config
        assert 'href="/adhoc/indicadores?mode=config"' in en_tracking

    def test_sin_ningun_destino_no_hay_conmutador(self, client, staff_headers, data_ok):
        """Ni filas clicables ni conmutador: no queda nada a donde llevar."""
        with as_user({"adhoc.indicators.page.list"}):
            html = client.get(URL_YEARS, headers=staff_headers).text
        assert page_data(html)["target_base"] == ""
        assert "adhoc-years-mode-swap" not in html

    def test_los_dos_enlaces_salen_del_mismo_par_de_mapas(self):
        """`MODE_PAGE_PERM` × `MODE_PATH_SUFFIX`: una sola copia de la regla.

        Los tests de arriba prueban el comportamiento de los tres enlaces
        cruzados; este fija que el par sigue siendo el par, que es de donde salen las dos mitades del
        enlace —a dónde lleva y quién entra— y la razón de que no puedan
        desincronizarse otra vez.
        """
        assert MODE_PAGE_PERM == {
            MODE_CONFIG: "adhoc.indicators.page.manage",
            MODE_TRACKING: "adhoc.indicators.page.tracking",
        }
        assert MODE_PATH_SUFFIX == {
            MODE_CONFIG: "/tablero",
            MODE_TRACKING: "/seguimiento",
        }


#: Variable del DML → nombre del rol. El bloque de `admin` no se parsea: es un
#: `SELECT ... WHERE app_id = v_app_id` sin lista de códigos.
DML_ROLES = {
    "v_role_consult": "consult",
    "v_role_sup_doc": "supervisor_doc",
    "v_role_sup_inc": "supervisor_inc",
    "v_role_sup_prog": "supervisor_prog",
}

DML_ROLE_NAMES = sorted(DML_ROLES.values())


def _dml_matrix():
    """`{rol: {códigos de permiso}}` leídos de `03_insert_role_permission.sql`.

    Se lee el SQL y no la BD porque el SQL **es** la fuente —los permisos nunca
    van en una migración de Alembic— y porque la base de tests no lleva la fila
    de `adhoc` en `core_apps`. Se salta si `database/` no está en el árbol: está
    gitignored, así que en un clon limpio no existe.
    """
    sql = (
        Path(__file__).resolve().parents[3]
        / "database" / "DML" / "adhoc" / "init" / "03_insert_role_permission.sql"
    )
    if not sql.exists():
        pytest.skip("el DML de adhoc no está en este árbol")

    texto = sql.read_text(encoding="utf-8")
    matriz = {}
    for var, nombre in DML_ROLES.items():
        bloque = re.search(
            r"SELECT\s+" + var + r",.*?ON CONFLICT", texto, re.S,
        )
        assert bloque, "el DML no tiene bloque de permisos para " + nombre
        matriz[nombre] = set(re.findall(r"'(adhoc\.[a-z_.]+)'", bloque.group(0)))
    return matriz


class TestElDmlRepartelaLectura:
    """La otra mitad de A27/A28: el permiso tiene que existir en algún rol.

    Arreglar los enlaces no sirve de nada si `page.tracking` sigue siendo
    exclusivo de `admin`: la pantalla del seguimiento seguiría sin un solo
    usuario real, y el callejón se habría cerrado dejando dentro a todo el
    mundo. Medido antes de B7: `page.list` lo tenían admin y consult;
    `page.manage` y `page.tracking`, solo admin.
    """

    @pytest.mark.parametrize("rol", DML_ROLE_NAMES)
    def test_los_cuatro_roles_reciben_el_seguimiento(self, rol):
        assert "adhoc.indicators.page.tracking" in _dml_matrix()[rol]

    @pytest.mark.parametrize("rol", DML_ROLE_NAMES)
    def test_y_tambien_la_lista_de_anios(self, rol):
        """Sin `page.list` la tarjeta del nav se enciende y su URL da 403.

        `NAV_SECTIONS` muestra "Indicadores" con *any-of* `{page.list,
        page.tracking}` pero apunta a `/adhoc/indicadores?mode=tracking`, que
        exige `page.list`. Dar solo `tracking` habría cambiado un callejón por
        otro peor: el que ni siquiera deja llegar a la lista.
        """
        assert "adhoc.indicators.page.list" in _dml_matrix()[rol]

    @pytest.mark.parametrize("rol", DML_ROLE_NAMES)
    def test_ninguno_recibe_manage_ni_la_captura(self, rol):
        """Leer el seguimiento no es editar la ficha ni pintar la celda.

        `page.manage` abre el tablero (alta y edición del indicador) y
        `api.tracking` es lo que `TestSeguridadDeSeguimiento` exige para que la
        rejilla sea escribible. Los dos siguen siendo de admin.
        """
        perms = _dml_matrix()[rol]
        assert "adhoc.indicators.page.manage" not in perms
        assert "adhoc.indicators.api.tracking" not in perms


# ==========================================================================
# GET /adhoc/indicadores/{year_id}/seguimiento — el bug de seguridad #26
# ==========================================================================

class TestSeguridadDeSeguimiento:
    def test_con_permiso_de_captura_la_rejilla_es_editable(
        self, client, staff_headers, data_ok
    ):
        with as_user({"adhoc.indicators.page.tracking", "adhoc.indicators.api.tracking"}):
            html = client.get(URL_TRACKING, headers=staff_headers).text
        assert page_data(html)["can_edit"] is True
        assert "data-adhoc-tracking-color" in html
        assert "adhoc-tracking-readonly" not in html
        assert "disabled>" not in html

    def test_sin_permiso_de_captura_la_rejilla_es_de_solo_lectura(
        self, client, staff_headers, data_ok
    ):
        """Regresión del bug #26: el legacy pasaba ``is_admin=True`` hardcodeado
        en la ruta, así que cualquiera podía reescribir el seguimiento del SGC."""
        with as_user({"adhoc.indicators.page.tracking"}):
            html = client.get(URL_TRACKING, headers=staff_headers).text
        assert page_data(html)["can_edit"] is False
        assert "data-adhoc-tracking-color" not in html   # sin <select> de color
        assert "disabled>" in html                       # inputs bloqueados
        assert "adhoc-tracking-readonly" in html         # y el aviso visible

    def test_el_permiso_de_captura_es_el_mismo_que_exige_la_api(self):
        """La UI y el endpoint no pueden discrepar: si divergen, vuelve el bug."""
        from itcj2.apps.adhoc.api import indicators as api_indicators

        source = Path(api_indicators.__file__).read_text(encoding="utf-8")
        assert '"adhoc.indicators.api.tracking"' in source


class TestRejillaDeSeguimiento:
    def test_mensual_pinta_12_celdas_numeradas_desde_1(
        self, client, admin_headers, year
    ):
        with with_indicators(year, [FakeIndicator(frequency="Mensual")]):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert html.count("data-adhoc-tracking-input") == 12
        assert 'data-adhoc-period="1"' in html
        assert 'data-adhoc-period="12"' in html
        assert 'data-adhoc-period="13"' not in html
        assert "Mes 12" in html

    def test_semanal_pinta_52_celdas(self, client, admin_headers, year):
        with with_indicators(year, [FakeIndicator(frequency="Semanal")]):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert html.count("data-adhoc-tracking-input") == 52
        assert "Semana 52" in html

    def test_el_valor_guardado_y_su_color_se_pintan_en_su_periodo(
        self, client, admin_headers, year
    ):
        indicador = FakeIndicator(
            frequency="Mensual", trackings=[FakeTracking(3, "78", "amarillo")]
        )
        with with_indicators(year, [indicador]):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert 'value="78"' in html
        assert "adhoc-state-yellow" in html

    def test_los_colores_del_legacy_no_reaparecen(self, client, admin_headers, data_ok):
        """`.bg-blanco/.bg-rojo/…` colisionan con las utilidades de Bootstrap 5.3."""
        html = client.get(URL_TRACKING, headers=admin_headers).text
        for legacy in ("bg-blanco", "bg-rojo", "bg-amarillo", "bg-verde"):
            assert legacy not in html

    def test_los_cuatro_umbrales_se_leen_por_separado(self, client, admin_headers, year):
        indicador = FakeIndicator(frequency="Anual", planned_white="1-2 días",
                                  planned_red="-5%")
        with with_indicators(year, [indicador]):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert "1-2 días" in html
        assert "-5%" in html

    def test_enlace_de_descarga_de_la_evidencia(self, client, admin_headers, year):
        """Funcionalidad NUEVA: el legacy subía el documento y no lo devolvía."""
        with with_indicators(year, [FakeIndicator(document_url="100/estandar.pdf")]):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert 'href="/api/adhoc/v2/indicators/100/download"' in html

    def test_sin_permiso_de_descarga_no_hay_enlace(self, client, staff_headers, year):
        with with_indicators(year, [FakeIndicator(document_url="100/estandar.pdf")]), \
             as_user({"adhoc.indicators.page.tracking"}):
            html = client.get(URL_TRACKING, headers=staff_headers).text
        assert "/download" not in html

    def test_anio_sin_indicadores_muestra_estado_vacio(self, client, admin_headers, year):
        with with_indicators(year, []):
            html = client.get(URL_TRACKING, headers=admin_headers).text
        assert "No hay indicadores configurados para este año" in html

    def test_anio_inexistente_es_404_html(self, client, admin_headers):
        with patch(f"{SERVICE}.get_year", return_value=None):
            res = client.get(URL_TRACKING, headers=admin_headers)
        assert res.status_code == 404


# ==========================================================================
# _tracking_cards — el modelado que el legacy hacía dentro de la plantilla
# ==========================================================================

class TestTrackingCards:
    def test_numeracion_1_based_dentro_del_rango_que_acepta_el_service(self):
        """El service valida 0..N; la rejilla numera 1..N, como la ve el usuario."""
        card = _tracking_cards([FakeIndicator(frequency="Mensual")])[0]
        assert [c["index"] for c in card["cells"]] == list(range(1, 13))

    @pytest.mark.parametrize("frequency,periods,label", [
        ("Semanal", 52, "Semana"),
        ("Mensual", 12, "Mes"),
        ("Anual", 1, "Año"),
    ])
    def test_periodos_por_frecuencia(self, frequency, periods, label):
        """El número sale de ``TRACKING_PERIODS_BY_FREQUENCY``, el MISMO mapa con
        el que el service acota ``period_index``: pintar de más sería regalar 400."""
        from itcj2.apps.adhoc.utils.constants import TRACKING_PERIODS_BY_FREQUENCY

        assert TRACKING_PERIODS_BY_FREQUENCY[frequency] == periods
        card = _tracking_cards([FakeIndicator(frequency=frequency)])[0]
        assert card["periods"] == periods
        assert len(card["cells"]) == periods
        assert card["period_label"] == label

    def test_sin_frecuencia_hay_periodos_por_defecto(self):
        card = _tracking_cards([FakeIndicator(frequency=None)])[0]
        assert card["periods"] == PERIODS_FALLBACK
        assert card["period_label"] == "Periodo"

    def test_celda_sin_tracking_es_blanca_y_vacia(self):
        card = _tracking_cards([FakeIndicator(frequency="Mensual")])[0]
        assert card["cells"][0] == {
            "index": 1, "value": "", "color": "blanco",
            "color_class": "adhoc-state-white",
        }

    def test_celda_con_tracking_toma_valor_y_clase_de_color(self):
        card = _tracking_cards([
            FakeIndicator(frequency="Mensual", trackings=[FakeTracking(2, "91", "verde")])
        ])[0]
        assert card["cells"][1]["value"] == "91"
        assert card["cells"][1]["color_class"] == "adhoc-state-green"

    def test_un_tracking_fuera_de_rango_no_revienta_el_render(self):
        """Datos heredados con un ``period_index`` absurdo: se ignoran, no explotan."""
        card = _tracking_cards([
            FakeIndicator(frequency="Anual", trackings=[FakeTracking(40, "x", "rojo")])
        ])[0]
        assert len(card["cells"]) == 1
        assert card["cells"][0]["value"] == ""

    def test_indicador_sin_proceso_no_revienta(self):
        card = _tracking_cards([FakeIndicator(process=None)])[0]
        assert card["process_name"] == "Sin proceso"
        assert card["process_color"] == "#b2bec3"

    def test_los_umbrales_llegan_por_separado(self):
        card = _tracking_cards([FakeIndicator(planned_white="a-b", planned_red="c-d")])[0]
        assert card["planned_white"] == "a-b"
        assert card["planned_red"] == "c-d"
        assert "planned_value" not in card


# ==========================================================================
# Reglas duras del plan §6.2/§6.3/§6.4 sobre los archivos de la sección
# ==========================================================================

def _strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


TEMPLATES = [TEMPLATES_DIR / n for n in ("years.html", "board.html", "tracking.html")]
CSS_FILES = [CSS_DIR / n for n in ("years.css", "board.css", "tracking.css")]
JS_FILES = [JS_DIR / n for n in ("years.js", "board.js", "tracking.js")]


class TestReglasDuras:
    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_template_sin_css_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_template_sin_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "onclick=" not in text
        assert "onchange=" not in text

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_template_extiende_la_base_y_versiona_sus_estaticos(self, path):
        text = path.read_text(encoding="utf-8")
        assert '{% extends "adhoc/base_adhoc.html" %}' in text
        for attr in ("href", "src"):
            for match in re.finditer(attr + r'="(/static/adhoc/[^"]+)"', text):
                assert "?v={{ sv(" in match.group(1), match.group(1)

    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_template_usa_el_unico_script_inline_permitido(self, path):
        """Solo el bloque JSON de ``page_data``; ningún otro <script> con cuerpo."""
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        inline = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", text)
        assert inline == [], inline
        assert "page_data_script(page_data)" in text

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_existe_y_es_iife_estricto(self, path):
        assert path.exists(), path
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        """Criterio de aceptación 5 del plan, acotado a esta sección."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    @pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
    def test_js_sin_template_literals(self, path):
        """Los backticks del legacy eran su vector de XSS y se rompían con un
        apóstrofo o un ``${`` en el dato. Aquí se concatena y se escapa."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        assert "`" not in text
        assert "${" not in text

    def test_js_solo_expone_su_namespace(self):
        expected = {
            "years.js": "window.AdhocIndicatorYears",
            "board.js": "window.AdhocIndicatorBoard",
            "tracking.js": "window.AdhocIndicatorTracking",
        }
        for path in JS_FILES:
            text = path.read_text(encoding="utf-8")
            assignments = set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M))
            assert assignments == {expected[path.name]}, (path.name, assignments)

    def test_el_formulario_del_tablero_escapa_los_datos_del_servidor(self):
        """board.js construye 16 campos + los <option> de proceso desde JSON."""
        text = _strip_js_comments((JS_DIR / "board.js").read_text(encoding="utf-8"))
        assert "escapeHtml" in text
        # y ningún <option> pre-renderizado llega desde el servidor
        assert "htmlProcesos" not in text

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
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

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_comentarios_no_cierran_sobre_un_token(self, path):
        """Gotcha real del repo: un cierre de comentario pegado a un comodín."""
        css = path.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_usa_los_tokens_y_no_hex_sueltos_de_la_paleta(self, path):
        """El legacy repetía 45 hex; aquí la paleta vive en los tokens."""
        css = _strip_css_comments(path.read_text(encoding="utf-8"))
        for hexa in ("#4834d4", "#686de0", "#2d3436", "#636e72", "#dfe6e9",
                     "#e74c3c", "#f39c12", "#27ae60"):
            assert hexa not in css, (path.name, hexa)

    @pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
    def test_css_solo_declara_clases_prefijadas(self, path):
        css = _strip_css_comments(path.read_text(encoding="utf-8"))
        for name in set(re.findall(r"\.([A-Za-z][\w-]*)", css)):
            assert name.startswith("adhoc-"), (path.name, name)

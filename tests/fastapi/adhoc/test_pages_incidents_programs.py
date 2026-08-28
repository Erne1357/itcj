"""Tests de las 7 páginas de la sección **incidencias · programa · asignaciones**.

======================================  =====================================
URL                                     Permiso de página
======================================  =====================================
``/adhoc/incidencias``                  ``adhoc.incidents.page.list``
``/adhoc/incidencias/categorias``       ``adhoc.incident_categories.page.list``
``/adhoc/incidencias/{id}/tareas``      ``adhoc.tasks.page.list``
``/adhoc/programas``                    ``adhoc.programs.page.list``
``/adhoc/programas/categorias``         ``adhoc.program_categories.page.list``
``/adhoc/programas/{id}/tareas``        ``adhoc.tasks.page.list``
``/adhoc/asignaciones``                 ``adhoc.tasks.page.assign``
======================================  =====================================

Harness (plan §9.1), con una vuelta de tuerca propia de las páginas:

* ``require_page_app`` **NO** bypasea al admin global: comprueba
  ``cached_has_assignment`` y ``cached_perms`` siempre. Por eso aquí los dos
  se parchean en el **módulo fuente** (``itcj2.core.services.authz_cache``),
  que es de donde los importa la dependencia dentro de la función.
* Las páginas devuelven **HTML**: 302 a ``/itcj/login`` para el anónimo, 403
  renderizado sin permiso y 404 renderizado para un id inexistente — nunca
  ``{"detail": …}``.
* ``pages/router.py`` es propiedad de la fase de cableado, así que estos
  routers todavía no están montados. La fixture los monta **solo si faltan**:
  cuando el cableado los añada, la fixture lo detecta y no duplica rutas.

Desde B4 este archivo pide además una página que **no** es suya:
``/adhoc/documentos/{id}/tareas`` (``pages/documents.py``). Aparece en
``TestColumnaPaso`` porque lo que ahí se mide es lo que las TRES pantallas
comparten —el mismo ``adhoc/work/tasks.html``—, y la única forma de comprobar
que la columna nueva no se coló en estas dos es medirlas contra la que sí la
lleva. Por la misma razón ``TestAsignaciones`` estrena un padre de tipo
documento: ``/adhoc/asignaciones`` vive aquí, pero sirve a los tres.
"""
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import make_jwt

APP_ROOT = Path(__file__).resolve().parents[3] / "itcj2" / "apps" / "adhoc"
TEMPLATES_DIR = APP_ROOT / "templates" / "adhoc"
STATIC_DIR = APP_ROOT / "static"

#: Todos los permisos que tocan estas siete páginas.
ALL_PERMS = {
    "adhoc.incidents.page.list",
    "adhoc.incident_categories.page.list",
    "adhoc.programs.page.list",
    "adhoc.program_categories.page.list",
    "adhoc.tasks.page.list",
    "adhoc.tasks.page.assign",
    "adhoc.incidents.api.create",
    "adhoc.incidents.api.update",
    "adhoc.incidents.api.delete",
    "adhoc.incidents.api.files.create",
    "adhoc.incidents.api.files.delete",
    "adhoc.incidents.api.files.download",
    "adhoc.incident_categories.api.create",
    "adhoc.incident_categories.api.update",
    "adhoc.incident_categories.api.delete",
    "adhoc.programs.api.create",
    "adhoc.programs.api.update",
    "adhoc.programs.api.delete",
    "adhoc.programs.api.duplicate",
    "adhoc.programs.api.files.create",
    "adhoc.programs.api.files.delete",
    "adhoc.programs.api.files.download",
    "adhoc.program_categories.api.create",
    "adhoc.program_categories.api.update",
    "adhoc.program_categories.api.delete",
    "adhoc.tasks.api.create",
    "adhoc.tasks.api.update",
    "adhoc.tasks.api.delete",
    "adhoc.tasks.api.assign",
}


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture()
def pages_client(app_client, db_session):
    """TestClient real con los routers de la sección montados si aún faltan."""
    from itcj2.apps.adhoc.pages.incidents import router as incidents_router
    from itcj2.apps.adhoc.pages.programs import router as programs_router
    from itcj2.database import get_db

    app = app_client.app
    existentes = {getattr(r, "path", None) for r in app.routes}
    if "/adhoc/incidencias" not in existentes:
        app.include_router(incidents_router, prefix="/adhoc")
    if "/adhoc/programas" not in existentes:
        app.include_router(programs_router, prefix="/adhoc")

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield app_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def headers():
    """Cookie de un usuario staff: sin bypass, su acceso depende del parche."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=4101, role='staff')}"}


@pytest.fixture()
def grant():
    """Finge la asignación a la app y el conjunto de permisos efectivos."""
    from contextlib import contextmanager

    @contextmanager
    def _grant(*, assigned=True, perms=ALL_PERMS):
        with patch(
            "itcj2.core.services.authz_cache.cached_has_assignment",
            return_value=assigned,
        ), patch(
            "itcj2.core.services.authz_cache.cached_perms", return_value=set(perms)
        ):
            yield

    return _grant


@pytest.fixture()
def catalogs(db_session):
    """Área, proceso y las dos categorías, para poblar los `<select>`."""
    from itcj2.apps.adhoc.models.incidents import AdhocIncidentCategory
    from itcj2.apps.adhoc.models.programs import AdhocProgramCategory
    from itcj2.apps.adhoc.models.structure import AdhocArea, AdhocProcess

    area = AdhocArea(name="e2e_area_ip", color="#4834d4", is_active=True)
    inactiva = AdhocArea(name="e2e_area_baja", color="#000000", is_active=False)
    proceso = AdhocProcess(name="e2e_proc_ip", color="#686de0")
    cat_inc = AdhocIncidentCategory(name="e2e_cat_inc")
    cat_prog = AdhocProgramCategory(name="e2e_cat_prog")
    db_session.add_all([area, inactiva, proceso, cat_inc, cat_prog])
    db_session.flush()
    return {
        "area": area, "area_inactiva": inactiva, "process": proceso,
        "incident_category": cat_inc, "program_category": cat_prog,
    }


@pytest.fixture()
def incident(db_session, catalogs):
    from itcj2.apps.adhoc.models.incidents import AdhocIncident

    row = AdhocIncident(
        folio="e2e_INC-1", title="e2e incidencia de prueba",
        priority="Alta", status="Iniciada",
        category_id=catalogs["incident_category"].id,
        area_id=catalogs["area"].id,
        process_id=catalogs["process"].id,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def event(db_session, catalogs):
    from itcj2.apps.adhoc.models.programs import AdhocProgramEvent

    row = AdhocProgramEvent(
        folio="e2e_PRG-1", title="e2e evento de prueba",
        priority="Media", status="Planeado", location="Aula magna",
        category_id=catalogs["program_category"].id,
        area_id=catalogs["area"].id,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def incident_task(db_session, incident):
    from itcj2.apps.adhoc.models.tasks import AdhocTask

    row = AdhocTask(description="e2e tarea de incidencia", incident_id=incident.id)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def document_task(db_session):
    """Tarea de aprobación de un documento: el TERCER padre de ``_task_target``.

    Es la que se atasca cuando sus validadores dejan de tener acceso a la app, y
    la que hasta B4 volvía al tablero después de reasignarla porque su expediente
    no tenía pantalla.
    """
    from itcj2.apps.adhoc.models.documents import AdhocDocument
    from itcj2.apps.adhoc.models.tasks import AdhocTask

    doc = AdhocDocument(code="e2e_DOC-asig", title="e2e documento de asignaciones",
                        version="1.0", status="En Revisión")
    db_session.add(doc)
    db_session.flush()
    row = AdhocTask(description="Aprobar Documento: e2e", document_id=doc.id,
                    status="En Revisión", priority="Alta")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def usuario_sin_acceso(db_session):
    """Responsable que sigue asignado y ya NO puede entrar a Calidad.

    Es el caso vivo del documento 202: la tarea 683 tiene un solo responsable y
    ese responsable está dado de baja, así que ``assignable_users`` —que filtra
    por ``is_active`` + ``users_with_assignment_select``— no lo devuelve. Se
    crea inactivo porque es la vía más corta de caer fuera de ese conjunto sin
    tocar roles ni puestos: al picker le da igual **por qué** quedó fuera.
    """
    from itcj2.core.models.user import User

    row = User(first_name="Zzz", last_name="Sin Acceso",
               username="e2e_sin_acceso_picker", email="sinacceso@itcj.edu.mx",
               is_active=False)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def flow_step(db_session):
    """Paso de un flujo de aprobación: el otro destino de /adhoc/asignaciones."""
    from itcj2.apps.adhoc.models.documents import (
        AdhocApprovalFlow,
        AdhocApprovalFlowStep,
    )

    flow = AdhocApprovalFlow(name="e2e_flujo_ip")
    db_session.add(flow)
    db_session.flush()
    step = AdhocApprovalFlowStep(flow_id=flow.id, name="e2e_paso_1", step_order=1)
    db_session.add(step)
    db_session.flush()
    return step


def page_data(html: str) -> dict:
    """Extrae el bloque JSON que los templates emiten con ``|tojson``."""
    match = re.search(
        r'<script id="adhoc-page-data" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert match, "la página no emitió el bloque adhoc-page-data"
    return json.loads(match.group(1))


# ==========================================================================
# Rutas: existen, autentican y autorizan
# ==========================================================================

URLS = [
    "/adhoc/incidencias",
    "/adhoc/incidencias/categorias",
    "/adhoc/programas",
    "/adhoc/programas/categorias",
]


class TestRutasYGates:
    @pytest.mark.parametrize("url", URLS)
    def test_responden_200_con_permiso(self, pages_client, headers, grant, url, catalogs):
        with grant():
            res = pages_client.get(url, headers=headers)
        assert res.status_code == 200, res.text[:300]
        assert "text/html" in res.headers["content-type"]

    def test_paginas_de_tareas_responden_200(self, pages_client, headers, grant,
                                             incident, event):
        with grant():
            uno = pages_client.get(f"/adhoc/incidencias/{incident.id}/tareas", headers=headers)
            dos = pages_client.get(f"/adhoc/programas/{event.id}/tareas", headers=headers)
        assert uno.status_code == 200, uno.text[:300]
        assert dos.status_code == 200, dos.text[:300]

    def test_asignaciones_responde_200(self, pages_client, headers, grant, incident_task):
        with grant():
            res = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers,
            )
        assert res.status_code == 200, res.text[:300]

    @pytest.mark.parametrize("url", URLS)
    def test_anonimo_va_al_login(self, pages_client, url):
        res = pages_client.get(url, follow_redirects=False)
        assert res.status_code in (302, 307)
        assert "/itcj/login" in res.headers["location"]

    @pytest.mark.parametrize("url", URLS)
    def test_sin_acceso_a_la_app_es_403(self, pages_client, headers, grant, url):
        with grant(assigned=False):
            res = pages_client.get(url, headers=headers, follow_redirects=False)
        assert res.status_code == 403

    def test_sin_el_permiso_de_la_pagina_es_403(self, pages_client, headers, grant):
        """Tiene la app y otros permisos, pero no el de ESTA página."""
        otros = ALL_PERMS - {"adhoc.incidents.page.list"}
        with grant(perms=otros):
            res = pages_client.get("/adhoc/incidencias", headers=headers,
                                   follow_redirects=False)
        assert res.status_code == 403

    def test_cada_pagina_exige_su_propio_permiso(self, pages_client, headers, grant, catalogs):
        """Un permiso de página no abre las demás páginas de la sección."""
        casos = {
            "/adhoc/incidencias": "adhoc.incidents.page.list",
            "/adhoc/incidencias/categorias": "adhoc.incident_categories.page.list",
            "/adhoc/programas": "adhoc.programs.page.list",
            "/adhoc/programas/categorias": "adhoc.program_categories.page.list",
        }
        for url, needed in casos.items():
            with grant(perms={needed}):
                ok = pages_client.get(url, headers=headers, follow_redirects=False)
            assert ok.status_code == 200, (url, ok.status_code)
            for otra, _ in casos.items():
                if otra == url:
                    continue
                with grant(perms={needed}):
                    res = pages_client.get(otra, headers=headers, follow_redirects=False)
                assert res.status_code == 403, (needed, otra)

    def test_padre_inexistente_es_404_html(self, pages_client, headers, grant):
        with grant():
            res = pages_client.get("/adhoc/incidencias/99999999/tareas", headers=headers)
        assert res.status_code == 404
        assert "text/html" in res.headers["content-type"]

    def test_evento_inexistente_es_404(self, pages_client, headers, grant):
        with grant():
            res = pages_client.get("/adhoc/programas/99999999/tareas", headers=headers)
        assert res.status_code == 404


# ==========================================================================
# /adhoc/incidencias
# ==========================================================================

class TestPaginaIncidencias:
    @pytest.fixture()
    def html(self, pages_client, headers, grant, catalogs):
        with grant():
            res = pages_client.get("/adhoc/incidencias", headers=headers)
        assert res.status_code == 200, res.text[:400]
        return res.text

    def test_apunta_a_la_api_v2_correcta(self, html):
        data = page_data(html)
        assert data["api"] == "/api/adhoc/v2/incidents"
        assert data["kind"] == "incident"

    def test_la_url_de_tareas_sale_del_json_no_del_js(self, html):
        """El legacy tenía `/app_prueba/extintor/tareas/${id}` cableado en el JS."""
        assert page_data(html)["tasks_url"] == "/adhoc/incidencias/{id}/tareas"

    def test_vocabulario_de_estatus_es_el_de_la_ui(self, html):
        data = page_data(html)
        assert data["statuses"] == ["No Iniciada", "Iniciada", "Cerrada"]
        assert data["priorities"] == ["Baja", "Media", "Alta", "Urgente"]

    def test_los_filtros_traducen_al_parametro_real_de_la_api(self, html):
        """`?q=` en incidencias, `?search=` en programas: el mapa lo resuelve."""
        assert page_data(html)["query_map"]["search"] == "q"

    def test_catalogos_viajan_como_datos_no_como_option(self, html, catalogs):
        data = page_data(html)
        nombres = {c["name"] for c in data["categories"]}
        assert "e2e_cat_inc" in nombres
        assert {a["name"] for a in data["areas"]} >= {"e2e_area_ip"}
        assert {p["name"] for p in data["processes"]} >= {"e2e_proc_ip"}
        # …y NUNCA como <option> pre-renderizados (los 7 XSS del legacy).
        assert 'value="{}"'.format(catalogs["incident_category"].id) not in html

    def test_las_areas_dadas_de_baja_no_se_ofrecen(self, html):
        """El legacy mandaba Area.query.all() a la plantilla, bajas incluidas."""
        assert "e2e_area_baja" not in {a["name"] for a in page_data(html)["areas"]}

    def test_las_columnas_declaran_su_clave(self, html):
        for key in ("folio", "title", "category", "area", "process", "responsible",
                    "commitment_date", "priority", "status", "tasks", "actions"):
            assert f'data-adhoc-filter-key="{key}"' in html

    def test_incluye_el_nav_y_los_estaticos_versionados(self, html):
        assert "adhoc-appbar" in html
        assert "/static/adhoc/css/adhoc.css?v=" in html
        assert "/static/adhoc/css/work/work-items.css?v=" in html
        assert "/static/adhoc/js/work/work-items.js?v=" in html
        assert "/static/adhoc/js/incidents/incidents.js?v=" in html

    def test_pinta_el_nav_filtrado_por_permisos(self, pages_client, headers, grant, catalogs):
        """Regla 6 de templates: toda página pasa `nav=nav_for_user(db, user)`.

        `nav_items` no usa `cached_perms` sino `get_user_permissions_for_app`, así
        que hay que parchear ESE nombre en su módulo fuente.
        """
        # Desde el porte visual el nav son las CUATRO tarjetas del legacy
        # (Tareas, Documentos, Indicadores, Panel Control): incidencias y
        # programa se alcanzan desde el panel, no desde la barra superior.
        visibles = {"adhoc.incidents.page.list", "adhoc.dashboard.page.view"}
        with grant(), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=visibles,
        ):
            html = pages_client.get("/adhoc/incidencias", headers=headers).text
        nav = html.split('<nav class="adhoc-nav"')[1].split("</nav>")[0]
        assert 'href="/adhoc/dashboard"' in nav
        # Sin el permiso, la tarjeta no aparece: el menú es fail-closed.
        assert 'href="/adhoc/panel"' not in nav
        assert 'href="/adhoc/documentos"' not in nav

    def test_el_boton_nuevo_depende_del_permiso_de_alta(self, pages_client, headers,
                                                        grant, catalogs):
        sin_alta = ALL_PERMS - {"adhoc.incidents.api.create"}
        with grant(perms=sin_alta):
            html = pages_client.get("/adhoc/incidencias", headers=headers).text
        assert "data-adhoc-work-new" not in html
        assert page_data(html)["can"]["create"] is False

    def test_trae_el_modal_de_archivos(self, html):
        """La incidencia se construyó sin adjuntos; ya no es el caso (351 del
        SGC legacy). El modal es el mismo markup que el de programas."""
        assert "data-adhoc-files-modal" in html
        assert "data-adhoc-files-list" in html

    def test_permisos_de_archivos_llegan_al_json(self, html):
        can = page_data(html)["can"]
        assert can["files"] is True
        assert can["files_create"] is True
        assert can["files_delete"] is True
        # "Duplicar" nunca aplica a una incidencia.
        assert can["duplicate"] is False

    def test_sin_permiso_de_subida_no_hay_formulario_de_subida(
        self, pages_client, headers, grant, catalogs
    ):
        with grant(perms=ALL_PERMS - {"adhoc.incidents.api.files.create"}):
            html = pages_client.get("/adhoc/incidencias", headers=headers).text
        assert "data-adhoc-files-upload" not in html


# ==========================================================================
# /adhoc/programas
# ==========================================================================

class TestPaginaProgramas:
    @pytest.fixture()
    def html(self, pages_client, headers, grant, catalogs):
        with grant():
            res = pages_client.get("/adhoc/programas", headers=headers)
        assert res.status_code == 200, res.text[:400]
        return res.text

    def test_apunta_a_la_api_de_eventos(self, html):
        data = page_data(html)
        assert data["api"] == "/api/adhoc/v2/program-events"
        assert data["kind"] == "program"
        assert data["tasks_url"] == "/adhoc/programas/{id}/tareas"

    def test_su_estatus_es_el_de_eventos_no_el_de_incidencias(self, html):
        assert page_data(html)["statuses"] == ["Planeado", "En Proceso", "Completado"]

    def test_el_filtro_de_busqueda_se_llama_search(self, html):
        assert page_data(html)["query_map"]["search"] == "search"

    def test_tiene_las_columnas_propias_de_evento(self, html):
        assert 'data-adhoc-filter-key="location"' in html
        assert 'data-adhoc-filter-key="files"' in html

    def test_trae_el_modal_de_archivos(self, html):
        assert "data-adhoc-files-modal" in html
        assert "data-adhoc-files-list" in html

    def test_carga_su_propio_modulo(self, html):
        assert "/static/adhoc/js/programs/programs.js?v=" in html
        assert "/static/adhoc/js/work/work-items.js?v=" in html

    def test_permisos_de_duplicar_y_archivos_llegan_al_json(self, html):
        can = page_data(html)["can"]
        assert can["duplicate"] is True
        assert can["files"] is True
        assert can["files_create"] is True

    def test_sin_permiso_de_subida_no_hay_formulario_de_subida(
        self, pages_client, headers, grant, catalogs
    ):
        with grant(perms=ALL_PERMS - {"adhoc.programs.api.files.create"}):
            html = pages_client.get("/adhoc/programas", headers=headers).text
        assert "data-adhoc-files-upload" not in html


# ==========================================================================
# Catálogos de categorías
# ==========================================================================

class TestCategorias:
    def test_incidencias_usa_la_macro_y_su_api(self, pages_client, headers, grant):
        with grant():
            html = pages_client.get("/adhoc/incidencias/categorias", headers=headers).text
        assert 'data-adhoc-resource="incident-categories"' in html
        assert 'data-adhoc-api="/api/adhoc/v2/incident-categories"' in html
        assert 'data-adhoc-catalog-modal="incident-categories"' in html
        assert 'href="/adhoc/incidencias"' in html
        assert "/static/adhoc/js/shared/catalog-crud.js?v=" in html

    def test_programas_usa_la_macro_y_su_api(self, pages_client, headers, grant):
        with grant():
            html = pages_client.get("/adhoc/programas/categorias", headers=headers).text
        assert 'data-adhoc-resource="program-categories"' in html
        assert 'data-adhoc-api="/api/adhoc/v2/program-categories"' in html
        assert 'href="/adhoc/programas"' in html

    def test_los_flags_de_permiso_ocultan_los_botones(self, pages_client, headers, grant):
        solo_lectura = {"adhoc.incident_categories.page.list"}
        with grant(perms=solo_lectura):
            html = pages_client.get("/adhoc/incidencias/categorias", headers=headers).text
        assert "data-adhoc-catalog-new" not in html
        assert 'data-adhoc-can-update="0"' in html
        assert 'data-adhoc-can-delete="0"' in html


# ==========================================================================
# Páginas de tareas — UN template, dos padres
# ==========================================================================

class TestPaginasDeTareas:
    def test_incidencia_pasa_su_parent_type(self, pages_client, headers, grant, incident):
        with grant():
            html = pages_client.get(
                f"/adhoc/incidencias/{incident.id}/tareas", headers=headers).text
        data = page_data(html)
        assert data["parent_type"] == "incident"
        assert data["parent_id"] == incident.id
        assert data["api"] == "/api/adhoc/v2/tasks"
        assert data["back_url"] == "/adhoc/incidencias"
        assert "e2e incidencia de prueba" in html

    def test_evento_pasa_su_parent_type(self, pages_client, headers, grant, event):
        with grant():
            html = pages_client.get(
                f"/adhoc/programas/{event.id}/tareas", headers=headers).text
        data = page_data(html)
        assert data["parent_type"] == "program"
        assert data["parent_id"] == event.id
        assert data["back_url"] == "/adhoc/programas"

    def test_las_dos_comparten_template_y_modulo(self, pages_client, headers, grant,
                                                 incident, event):
        with grant():
            uno = pages_client.get(f"/adhoc/incidencias/{incident.id}/tareas",
                                   headers=headers).text
            dos = pages_client.get(f"/adhoc/programas/{event.id}/tareas",
                                   headers=headers).text
        for html in (uno, dos):
            assert "/static/adhoc/js/work/tasks.js?v=" in html
            assert "/static/adhoc/css/work/tasks.css?v=" in html
            assert "data-adhoc-tasks" in html

    def test_ofrece_los_seis_estatus_de_tarea(self, pages_client, headers, grant, incident):
        """El <select> del legacy solo ofrecía tres: editar degradaba la tarea."""
        with grant():
            html = pages_client.get(
                f"/adhoc/incidencias/{incident.id}/tareas", headers=headers).text
        assert page_data(html)["statuses"] == [
            "Pendiente", "En Proceso", "En Revisión", "En Espera",
            "Completada", "Rechazada",
        ]

    def test_la_url_de_asignacion_sale_del_json(self, pages_client, headers, grant, incident):
        with grant():
            html = pages_client.get(
                f"/adhoc/incidencias/{incident.id}/tareas", headers=headers).text
        assert page_data(html)["assign_url"] == "/adhoc/asignaciones"


# ==========================================================================
# La columna "Paso" — TRES pantallas, un solo template  (B4)
#
# `adhoc/work/tasks.html` lo comparten ahora las dos pantallas de esta sección y
# la que B4 añadió en `pages/documents.py` (`/adhoc/documentos/{id}/tareas`). La
# tercera se ejercita desde aquí, aunque su ruta viva en otro módulo, porque lo
# que se prueba es justamente lo que las TRES comparten: si la columna nueva se
# hubiera colado en las otras dos, esta sección se quedaría con una columna de
# guiones —las tareas de incidencia y de evento no cuelgan de ningún paso—.
#
# El descuadre que este bloque vigila es el clásico de una tabla escrita a mano:
# alguien añade un `<th>` a la cabecera y se olvida de la fila de filtros o del
# `colspan` del "sin resultados", y la tabla se desalinea solo cuando está
# vacía. Aquí no puede pasar por construcción —la macro `data_table()` deriva
# las tres cosas de la MISMA lista de columnas— y esto es el test que lo
# certifica sobre el HTML de verdad, no sobre el código que lo genera.
# ==========================================================================

#: Rótulos de la tabla de tareas en incidencias y programa.
COLUMNAS_BASE = ["Tarea", "Responsable(s)", "Estatus", "Prioridad", "Inicio",
                 "Compromiso", "Real", "Notas", "Acciones"]

#: En documentos, "Paso" se inserta justo detrás de "Tarea": el paso describe la
#: tarea ("Aprobar Documento: X (Paso: Y)"), no es un atributo más de su
#: seguimiento. El orden es contrato con `work/tasks.js::buildRow`, que mete su
#: `<td>` en esta misma posición.
COLUMNAS_DOCUMENTO = ["Tarea", "Paso"] + COLUMNAS_BASE[1:]


def tabla_de_tareas(html: str) -> dict:
    """Mide la cabecera REAL de la tabla de tareas de la página renderizada.

    Se renderiza y se cuenta el markup en vez de mirar la lista de columnas del
    template con un ``grep``: lo que puede descuadrarse es el HTML, y un grep
    sobre la plantilla daría por buena una tabla cuya fila de filtros tuviera
    una celda de menos.
    """
    tabla = re.search(
        r'<table[^>]*data-adhoc-table="adhoc-table-tasks"[^>]*>(.*?)</table>',
        html, re.S,
    )
    assert tabla, "la página no pintó la tabla de tareas"
    cuerpo = tabla.group(1)

    thead = re.search(r"<thead>(.*?)</thead>", cuerpo, re.S)
    assert thead, "la tabla no tiene cabecera"
    filas = re.findall(r"<tr[^>]*>(.*?)</tr>", thead.group(1), re.S)
    assert len(filas) == 2, "el thead son dos filas: rótulos y filtros"

    rotulos = [
        re.sub(r"<[^>]+>", "", celda).strip()
        for celda in re.findall(r"<th[^>]*>(.*?)</th>", filas[0], re.S)
    ]
    filtros = re.findall(r"<th[^>]*>(.*?)</th>", filas[1], re.S)
    vacia = re.search(r'<td colspan="(\d+)"', cuerpo)
    assert vacia, "la tabla no declara la fila de 'sin resultados'"

    return {
        "rotulos": rotulos,
        "filtros": len(filtros),
        "con_input": sum(1 for celda in filtros if "adhoc-filter-input" in celda),
        "colspan": int(vacia.group(1)),
    }


class TestColumnaPaso:
    @pytest.fixture()
    def documento(self, db_session):
        from itcj2.apps.adhoc.models.documents import AdhocDocument

        row = AdhocDocument(code="e2e_DOC-1", title="e2e documento de prueba",
                            version="1.0", status="En Revisión")
        db_session.add(row)
        db_session.flush()
        return row

    @pytest.fixture()
    def pantallas(self, pages_client, headers, grant, incident, event, documento):
        """El HTML de las tres, pedido por HTTP contra el cableado real."""
        with grant():
            res = {
                "incident": pages_client.get(
                    f"/adhoc/incidencias/{incident.id}/tareas", headers=headers),
                "program": pages_client.get(
                    f"/adhoc/programas/{event.id}/tareas", headers=headers),
                "document": pages_client.get(
                    f"/adhoc/documentos/{documento.id}/tareas", headers=headers),
            }
        for tipo, r in res.items():
            assert r.status_code == 200, (tipo, r.text[:300])
        return {tipo: r.text for tipo, r in res.items()}

    def test_las_tres_cuadran_cabecera_filtros_y_colspan(self, pantallas):
        """9 · 9 · 10, y en cada una las tres cuentas coinciden entre sí."""
        medidas = {tipo: tabla_de_tareas(html) for tipo, html in pantallas.items()}

        assert medidas["incident"]["rotulos"] == COLUMNAS_BASE
        assert medidas["program"]["rotulos"] == COLUMNAS_BASE
        assert medidas["document"]["rotulos"] == COLUMNAS_DOCUMENTO

        for tipo, m in medidas.items():
            assert m["filtros"] == len(m["rotulos"]), (tipo, m)
            assert m["colspan"] == len(m["rotulos"]), (tipo, m)

        # La columna nueva es filtrable: son 3 filtros en las hermanas y 4 aquí.
        assert medidas["incident"]["con_input"] == 3
        assert medidas["program"]["con_input"] == 3
        assert medidas["document"]["con_input"] == 4

    def test_solo_la_de_documento_enciende_la_bandera(self, pantallas):
        """La bandera del servidor es UNA y la leen la plantilla y el JS.

        Si la pantalla la emitiera y la plantilla decidiera por su cuenta con un
        ``parent_type == 'document'`` suelto, habría dos frases sobre lo mismo y
        podrían discrepar: cabecera con columna y filas sin celda, o al revés.
        """
        assert page_data(pantallas["incident"])["show_step_column"] is False
        assert page_data(pantallas["program"])["show_step_column"] is False
        assert page_data(pantallas["document"])["show_step_column"] is True

    def test_el_paso_vacio_se_lee(self):
        """"Fuera del flujo" es INFORMACION, y la informacion tiene que leerse.

        La celda se pintaba con `.adhoc-muted-cell`, que en esta hoja es
        `--adhoc-disabled` (#b2bec3): 1.90:1 sobre la tarjeta blanca, el texto
        menos legible de la pantalla — y justo el que el docstring de
        `stepCell` defiende como dato y no como hueco ("un guion se lee como no
        hay dato"). Esa clase es el placeholder de "Sin asignar"; esta celda
        necesitaba la suya.

        Se mide el contraste de verdad y no se compara el nombre del token:
        cambiar el valor de `--adhoc-muted` sin mirar volvería a bajar de AA sin
        que ningún test se enterara. Las pantallas de tareas no están en el
        barrido de `tests/e2e/adhoc/contrast-sweep.spec.js` porque su URL pide
        un id de entidad.
        """
        js = _strip_js_comments(
            (STATIC_DIR / "js" / "work" / "tasks.js").read_text(encoding="utf-8"))
        hoja = (STATIC_DIR / "css" / "work" / "tasks.css").read_text(encoding="utf-8")
        base = (STATIC_DIR / "css" / "adhoc.css").read_text(encoding="utf-8")

        assert "'flow_step', 'Fuera del flujo', 'adhoc-step-empty'" in js, (
            "la celda vacía del paso tiene que llevar su propia clase, no el "
            "placeholder `.adhoc-muted-cell`"
        )

        regla = re.search(r"\.adhoc-step-empty\s*\{([^}]*)\}", hoja)
        assert regla, "`.adhoc-step-empty` no tiene regla en work/tasks.css"
        token = re.search(r"color:\s*var\((--adhoc-[\w-]+)\)", regla.group(1))
        assert token, "el color de la celda tiene que salir de un token"

        def _hex(nombre):
            m = re.search(re.escape(nombre) + r":\s*(#[0-9a-fA-F]{6})", base)
            assert m, nombre
            return m.group(1)

        def _luminancia(color):
            canales = []
            for i in (1, 3, 5):
                c = int(color[i:i + 2], 16) / 255
                canales.append(c / 12.92 if c <= 0.03928
                               else ((c + 0.055) / 1.055) ** 2.4)
            return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]

        tinta = _luminancia(_hex(token.group(1)))
        fondo = _luminancia(_hex("--adhoc-surface"))       # la tarjeta, blanca
        claro, oscuro = max(tinta, fondo), min(tinta, fondo)
        ratio = (claro + 0.05) / (oscuro + 0.05)

        assert ratio >= 4.5, f"{token.group(1)} da {ratio:.2f}:1 sobre la tarjeta (AA pide 4.5)"

    def test_las_hermanas_no_pintan_la_columna_ni_su_filtro(self, pantallas):
        """No basta con que la bandera esté apagada: el markup no puede tenerla."""
        for tipo in ("incident", "program"):
            assert 'data-adhoc-filter-key="flow_step"' not in pantallas[tipo], tipo
            assert ">Paso<" not in pantallas[tipo], tipo
        assert 'data-adhoc-filter-key="flow_step"' in pantallas["document"]


# ==========================================================================
# El hilo de la tarea en estas dos pantallas (B3)
#
# El modal de workflow era el ÚNICO visor del hilo de comentarios de una tarea
# y solo se abría desde el tablero, que lista únicamente las tareas ABIERTAS
# del usuario: los 930 comentarios que cuelgan de tareas ya completadas —el
# 85 % del histórico del SGC— no se podían leer desde ninguna URL. Aquí el
# contador de la columna "Notas", que antes era un número muerto, lo abre.
#
# En SOLO LECTURA: el markup compartido se incluye sin el `{% with %}` de las
# capacidades, así que `wf_can_comment` y `wf_can_workflow` llegan `Undefined`
# —falso— y ni la caja de comentario ni las tres acciones de flujo se emiten,
# también cuando la tarea sigue abierta. Actuar sigue siendo cosa del tablero.
# ==========================================================================

class TestHiloDeLaTarea:
    @pytest.fixture()
    def htmls(self, pages_client, headers, grant, incident, event):
        """El HTML de las dos pantallas: comparten template, comparten modal."""
        with grant():
            return {
                "incident": pages_client.get(
                    f"/adhoc/incidencias/{incident.id}/tareas", headers=headers).text,
                "program": pages_client.get(
                    f"/adhoc/programas/{event.id}/tareas", headers=headers).text,
            }

    def test_las_dos_pantallas_traen_el_modal_y_su_hoja(self, htmls):
        for parent_type, html in htmls.items():
            assert 'id="adhoc-wf-modal"' in html, parent_type
            assert 'id="adhoc-wf-comments"' in html, parent_type
            assert "/static/adhoc/css/work/workflow-modal.css?v=" in html, parent_type
            assert "/static/adhoc/js/work/workflow-modal.js?v=" in html, parent_type

    def test_el_modal_es_de_solo_lectura(self, htmls):
        """Sin caja de comentario y sin las tres acciones irreversibles.

        No es una decisión de CSS: el markup **no se emite**. Esconder los
        botones con una clase deja el control en el DOM y a un clic de
        distancia de `POST /workflow-action`.
        """
        for parent_type, html in htmls.items():
            for marcador in ("data-adhoc-wf-comment-new", "data-adhoc-wf-comment-save",
                             'id="adhoc-wf-comment-form"', "data-adhoc-wf-actions",
                             'data-adhoc-wf-action="aprobar"',
                             'data-adhoc-wf-action="rechazar"',
                             'data-adhoc-wf-action="terminar"'):
                assert marcador not in html, (parent_type, marcador)

    def test_el_modal_de_solo_lectura_no_pinta_pie(self, htmls):
        """Sin controles no hay pie, y sin pie no hay hueco muerto.

        El `<div class="modal-footer">` se emitia siempre y su unico hijo
        incondicional es el aviso, que nace `d-none` y solo lo enciende
        `showNotice()` —al que en modo lectura no llega nadie: sus tres
        llamadas pasan antes por `isFull()`—. `adhoc.css` le da al pie
        `margin-top: 25px`, `padding-top: 20px` y un `border-top`, asi que
        cada uno de los 453 hilos con comentarios terminaba en un separador
        que no separa nada y ~46 px de vacio.
        """
        for parent_type, html in htmls.items():
            assert "adhoc-wf-footer" not in html, parent_type
            assert 'id="adhoc-wf-notice"' not in html, parent_type

    #: Los rótulos inertes de la fila de tareas: `<span>` con `cursor: help`, sin
    #: `data-adhoc-task-action`. Cada vez que se añade uno hay que meterlo en el
    #: guard de `bind()`, y esta lista es la que obliga a acordarse.
    ROTULOS_INERTES = [".adhoc-count-off", ".adhoc-task-stuck"]

    def test_los_rotulos_inertes_no_caen_en_el_atajo_de_edicion(self):
        """Las pastillas apagadas tienen que ser inertes, no solo parecerlo.

        Se emiten como `<span>` sin `data-adhoc-task-action` —a proposito: un
        `<button disabled>` no despacharia el clic, pero los navegadores
        tampoco muestran el `title` de un control deshabilitado, y ese texto es
        todo lo que tienen que decir—. Sin el guard, el clic seguia burbujeando
        hasta el atajo de fila y abria el modal de EDICION: el usuario pulsaba
        un control con cursor de ayuda que le decia "solo puedes abrir el
        historial de las tareas en las que participas" —o "bloqueada: nadie
        puede atenderla"— y le salia el formulario de la tarea.

        Son DOS porque B4 añadió el aviso de atasco con el mismo markup y el
        mismo defecto, doce lineas mas abajo del guard que ya lo arreglaba para
        el contador. El guard va ANTES del atajo, o no sirve de nada.
        """
        text = _strip_js_comments(
            (STATIC_DIR / "js" / "work" / "tasks.js").read_text(encoding="utf-8"))
        atajo = text.index("if (self.can.update) self.openEdit(task);")
        for clase in self.ROTULOS_INERTES:
            assert clase in text, clase
            guard = re.search(
                r"closest\('([^']*" + re.escape(clase) + r"[^']*)'\)", text)
            assert guard, f"{clase} no está en ningún guard de `closest`"
            assert guard.start() < atajo, clase

    def test_el_aviso_de_atasco_se_pinta_pero_no_se_pulsa(self):
        """Es un rótulo, no un control: `role="img"` + `title`, cero listener.

        Si algún día tuviera que hacer algo al pulsarlo, lo que hay que darle es
        un `data-adhoc-task-action` propio —no quitarle el guard—: el guard es
        lo único que separa "pastilla que explica" de "pastilla que abre el
        formulario de la tarea por accidente".
        """
        text = _strip_js_comments(
            (STATIC_DIR / "js" / "work" / "tasks.js").read_text(encoding="utf-8"))
        aviso = text.index("adhoc-task-stuck")
        cierre = text.index("Tasks.prototype.buildActions", aviso)
        bloque = text[aviso:cierre]
        assert "data-adhoc-task-action" not in bloque
        assert "'role', 'img'" in bloque

    def test_el_modulo_del_modal_se_carga_antes_que_el_de_la_pantalla(self, htmls):
        """`tasks.js` consume `window.AdhocWorkflowModal` al pulsar el contador.

        Y con ESE id: idiomorph empareja los `<script>` por `id`, así que al ir
        del tablero a esta lista el nodo se conserva y el módulo no se
        re-ejecuta. Con otro id habría dos copias con dos estados distintos.
        """
        for parent_type, html in htmls.items():
            modal = html.index('id="adhoc-mod-work-workflow-modal"')
            pantalla = html.index('id="adhoc-mod-work-tasks"')
            assert modal < pantalla, parent_type

    def test_los_ids_del_modal_no_chocan_con_los_del_modal_de_edicion(self, htmls):
        """Dos diálogos en la misma página: `adhoc-wf-…` y `adhoc-tasks-…`.

        Un id repetido rompe `getElementById` en silencio y el modal empieza a
        pintar en el nodo equivocado.
        """
        for parent_type, html in htmls.items():
            ids = re.findall(r'\bid="([^"]+)"', html)
            repetidos = {i for i in ids if ids.count(i) > 1}
            assert not repetidos, (parent_type, repetidos)
            assert any(i.startswith("adhoc-wf-") for i in ids), parent_type
            assert any(i.startswith("adhoc-tasks-") for i in ids), parent_type

    def test_el_modal_va_en_el_bloque_de_modales_del_template(self):
        """Fuera de cualquier contenedor con `transform`, que rompe el overlay."""
        text = _strip_jinja_comments(
            (TEMPLATES_DIR / "work" / "tasks.html").read_text(encoding="utf-8"))
        bloque = text.index("{% block modals %}")
        fin = text.index("{% endblock %}", bloque)
        assert bloque < text.index("_workflow_modal.html") < fin

    def test_el_template_incluye_el_partial_sin_declarar_capacidades(self):
        """El `{% with %}` de las capacidades es lo que separa leer de actuar.

        Si alguien lo copiara del tablero, esta pantalla emitiría los botones
        de flujo sin haberlo decidido. El defecto es no poder actuar.
        """
        text = _strip_jinja_comments(
            (TEMPLATES_DIR / "work" / "tasks.html").read_text(encoding="utf-8"))
        assert "wf_can_comment" not in text
        assert "wf_can_workflow" not in text

    def test_el_contador_de_notas_lo_pinta_el_js_con_el_flag_del_servidor(self):
        """`thread_readable` decide botón o pastilla apagada, no el navegador.

        Es la lección de B1 y B2 aplicada al pie de la letra: la regla que la
        UI usa para pintar el control y la que el servidor usa para permitirlo
        son la misma función (`puede_leer_hilo`), o divergen.
        """
        text = _strip_js_comments(
            (STATIC_DIR / "js" / "work" / "tasks.js").read_text(encoding="utf-8"))
        assert "thread_readable" in text
        assert "AdhocWorkflowModal" in text
        assert "adhoc-count-off" in text


# ==========================================================================
# /adhoc/asignaciones — la consolidación de las dos rutas del legacy
# ==========================================================================

class TestAsignaciones:
    def test_assign_apunta_al_endpoint_de_responsables(self, pages_client, headers,
                                                       grant, incident_task):
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text
        data = page_data(html)
        assert data["endpoint"] == f"/api/adhoc/v2/tasks/{incident_task.id}/assignees"
        assert data["method"] == "PUT"
        assert data["target"] == "task"

    def test_notify_apunta_al_endpoint_de_vencimiento(self, pages_client, headers,
                                                      grant, incident_task):
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=notify&task_id={incident_task.id}",
                headers=headers).text
        assert page_data(html)["endpoint"] == (
            f"/api/adhoc/v2/tasks/{incident_task.id}/overdue-notifications"
        )

    def test_vuelve_a_las_tareas_del_padre_correcto(self, pages_client, headers,
                                                    grant, incident_task, incident):
        """El legacy usaba history.back(), que no existe si entras por URL."""
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text
        assert page_data(html)["return_to"] == f"/adhoc/incidencias/{incident.id}/tareas"

    def test_una_tarea_de_documento_vuelve_a_su_expediente(self, pages_client, headers,
                                                           grant, document_task):
        """B4: el tercer padre estaba sin mapear y el ``else`` se lo tragaba.

        ``_task_target`` resolvía ``incident_id`` y ``program_id``, y para todo
        lo demás caía a ``/adhoc/dashboard``. O sea: reasignar la tarea de
        aprobación de un documento —justo lo que hay que hacer cuando un paso
        se atasca porque sus validadores ya no entran a la app— te dejaba en el
        tablero, desde donde no hay forma de volver al expediente. Y como el
        botón "Volver" de esta pantalla usa el mismo valor, el destino
        equivocado se veía dos veces.
        """
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={document_task.id}",
                headers=headers).text
        data = page_data(html)
        assert data["return_to"] == (
            f"/adhoc/documentos/{document_task.document_id}/tareas"
        )
        assert data["return_to"] != "/adhoc/dashboard"

    def test_los_tres_padres_de_una_tarea_tienen_destino_propio(
            self, pages_client, headers, grant, incident_task, incident,
            document_task, db_session):
        """El mapa completo, en un solo sitio: ninguno cae al tablero.

        Escrito como tabla y no como tres tests sueltos porque lo que se prueba
        es que la lista está **completa**: el fallo de B4 no fue un destino
        equivocado sino uno que faltaba, y eso solo se ve mirando los tres
        juntos.
        """
        from itcj2.apps.adhoc.models.programs import AdhocProgramEvent
        from itcj2.apps.adhoc.models.tasks import AdhocTask

        evento = AdhocProgramEvent(folio="e2e_PRG-asig", title="e2e evento asignaciones",
                                   priority="Media", status="Planeado")
        db_session.add(evento)
        db_session.flush()
        tarea_evento = AdhocTask(description="e2e tarea de evento", program_id=evento.id)
        db_session.add(tarea_evento)
        db_session.flush()

        esperado = {
            incident_task.id: f"/adhoc/incidencias/{incident.id}/tareas",
            tarea_evento.id: f"/adhoc/programas/{evento.id}/tareas",
            document_task.id: f"/adhoc/documentos/{document_task.document_id}/tareas",
        }
        for task_id, destino in esperado.items():
            with grant():
                html = pages_client.get(
                    f"/adhoc/asignaciones?action=assign&task_id={task_id}",
                    headers=headers).text
            assert page_data(html)["return_to"] == destino, task_id

    def test_return_to_externo_se_descarta(self, pages_client, headers, grant,
                                           incident_task, incident):
        """Sin esto la pantalla sería un redirector abierto."""
        for malicioso in ("https://evil.example/x", "//evil.example",
                          "/itcj/config", "/\\evil.example"):
            with grant():
                html = pages_client.get(
                    "/adhoc/asignaciones",
                    params={"action": "assign", "task_id": incident_task.id,
                            "return_to": malicioso},
                    headers=headers).text
            assert page_data(html)["return_to"] == (
                f"/adhoc/incidencias/{incident.id}/tareas"
            )

    def test_return_to_interno_se_respeta(self, pages_client, headers, grant, incident_task):
        with grant():
            html = pages_client.get(
                "/adhoc/asignaciones",
                params={"action": "assign", "task_id": incident_task.id,
                        "return_to": "/adhoc/programas"},
                headers=headers).text
        assert page_data(html)["return_to"] == "/adhoc/programas"

    def test_sin_id_es_400_y_no_un_formulario_inutil(self, pages_client, headers, grant):
        """El legacy dejaba elegir usuarios y fallaba AL GUARDAR."""
        with grant():
            res = pages_client.get("/adhoc/asignaciones?action=assign", headers=headers)
        assert res.status_code == 400

    def test_step_sin_step_id_es_400(self, pages_client, headers, grant):
        with grant():
            res = pages_client.get("/adhoc/asignaciones?action=step_assign", headers=headers)
        assert res.status_code == 400

    def test_accion_invalida_es_400(self, pages_client, headers, grant, incident_task):
        with grant():
            res = pages_client.get(
                f"/adhoc/asignaciones?action=inventada&task_id={incident_task.id}",
                headers=headers)
        assert res.status_code == 400

    def test_step_assign_apunta_al_endpoint_de_validadores(self, pages_client, headers,
                                                           grant, flow_step):
        """La cuarta esquina de la consolidación: el destino es un PASO de flujo."""
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=step_assign&step_id={flow_step.id}",
                headers=headers).text
        data = page_data(html)
        assert data["target"] == "step"
        assert data["endpoint"] == (
            f"/api/adhoc/v2/approval-flows/steps/{flow_step.id}/validators"
        )
        assert data["return_to"] == f"/adhoc/documentos/flujos/{flow_step.flow_id}/pasos"

    def test_notify_step_apunta_a_su_endpoint(self, pages_client, headers, grant, flow_step):
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=notify_step&step_id={flow_step.id}",
                headers=headers).text
        assert page_data(html)["endpoint"] == (
            f"/api/adhoc/v2/approval-flows/steps/{flow_step.id}/overdue-notifications"
        )

    def test_paso_inexistente_es_404(self, pages_client, headers, grant):
        with grant():
            res = pages_client.get(
                "/adhoc/asignaciones?action=step_assign&step_id=99999999", headers=headers)
        assert res.status_code == 404

    def test_step_assign_precarga_los_validadores_actuales(self, pages_client, headers,
                                                           grant, db_session, flow_step):
        from itcj2.core.models.user import User

        usuario = db_session.query(User).filter(User.is_active.is_(True)).first()
        if usuario is None:
            pytest.skip("la BD de desarrollo no tiene usuarios activos")

        flow_step.assignees.append(usuario)
        db_session.flush()

        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=step_assign&step_id={flow_step.id}",
                headers=headers).text
        assert page_data(html)["selected_ids"] == [usuario.id]

    def test_notify_step_no_hereda_a_los_validadores(self, pages_client, headers,
                                                     grant, db_session, flow_step):
        """`notify_on_overdue` es un flag de la asociación, no "ser validador"."""
        from itcj2.core.models.user import User

        usuario = db_session.query(User).filter(User.is_active.is_(True)).first()
        if usuario is None:
            pytest.skip("la BD de desarrollo no tiene usuarios activos")

        flow_step.assignees.append(usuario)
        db_session.flush()

        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=notify_step&step_id={flow_step.id}",
                headers=headers).text
        assert page_data(html)["selected_ids"] == []

    def test_tarea_inexistente_es_404(self, pages_client, headers, grant):
        with grant():
            res = pages_client.get(
                "/adhoc/asignaciones?action=assign&task_id=99999999", headers=headers)
        assert res.status_code == 404

    def test_selecciona_a_los_responsables_actuales(self, pages_client, headers, grant,
                                                    db_session, incident_task):
        from itcj2.core.models.user import User

        usuario = db_session.query(User).filter(User.is_active.is_(True)).first()
        if usuario is None:
            pytest.skip("la BD de desarrollo no tiene usuarios activos")

        incident_task.assignees.append(usuario)
        db_session.flush()

        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text
        assert page_data(html)["selected_ids"] == [usuario.id]

    def test_notify_no_hereda_la_seleccion_de_responsables(self, pages_client, headers,
                                                           grant, db_session, incident_task):
        """En el legacy la ruta de incidencias devolvía los asignados, no los avisados."""
        from itcj2.core.models.user import User

        usuario = db_session.query(User).filter(User.is_active.is_(True)).first()
        if usuario is None:
            pytest.skip("la BD de desarrollo no tiene usuarios activos")

        incident_task.assignees.append(usuario)
        db_session.flush()

        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=notify&task_id={incident_task.id}",
                headers=headers).text
        assert page_data(html)["selected_ids"] == []

    # ---- el responsable que ya no puede entrar (B4, revisión adversarial) ----
    #
    # El aviso de "tarea bloqueada" de `/adhoc/documentos/{id}/tareas` manda a
    # esta pantalla a arreglarlo. Y esta pantalla no podía: la lista de a quién
    # se puede marcar (`assignable_users`) y la de quién ya está marcado
    # (`selected_ids`) salen del MISMO criterio de acceso, así que al
    # responsable que lo perdió lo excluye la primera exactamente por el motivo
    # por el que aparece en la segunda. El picker no lo encontraba en `users` y
    # caía a su respaldo `'#' + id`: el supervisor leía un nombre en la fila
    # "Bloqueada" y aquí veía la ficha `#24055`, sin nombre ni departamento. Y
    # como `getSelection()` no distingue una ficha de otra, marcar un sustituto
    # y guardar mandaba `user_ids: [24055, nuevo]` — la tarea volvía marcada.

    def test_un_responsable_sin_acceso_llega_con_nombre_y_marcado(
            self, pages_client, headers, grant, incident_task, usuario_sin_acceso,
            db_session):
        """Los dos conjuntos los conoce el servidor; los concilia el servidor."""
        incident_task.assignees.append(usuario_sin_acceso)
        db_session.flush()

        with grant():
            data = page_data(pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text)

        ficha = next((u for u in data["users"] if u["id"] == usuario_sin_acceso.id), None)
        assert ficha is not None, "el seleccionado no llegó en `users`: el picker lo pintaría como '#id'"
        assert ficha["without_access"] is True
        # Con su NOMBRE: es lo único que permite reconocer la ficha que sobra.
        assert ficha["full_name"] == "Zzz Sin Acceso"
        assert ficha["full_name"] != f"#{usuario_sin_acceso.id}"

    def test_todo_seleccionado_esta_en_la_lista_de_usuarios(
            self, pages_client, headers, grant, incident_task, usuario_sin_acceso,
            db_session):
        """La invariante de la pantalla, y la que estaba rota.

        `selected_ids` ⊆ `users`. Si un id seleccionado no está en la lista, el
        picker no puede ponerle cara: ni en la ficha, ni en la casilla de la
        lista con la que se desmarca.
        """
        from itcj2.core.models.user import User

        otro = db_session.query(User).filter(User.is_active.is_(True)).first()
        incident_task.assignees.append(usuario_sin_acceso)
        if otro is not None:
            incident_task.assignees.append(otro)
        db_session.flush()

        with grant():
            data = page_data(pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text)

        conocidos = {u["id"] for u in data["users"]}
        assert set(data["selected_ids"]) <= conocidos, (
            set(data["selected_ids"]) - conocidos
        )

    def test_quien_si_puede_entrar_no_lleva_la_marca(
            self, pages_client, headers, grant, incident_task):
        """La marca es la excepción, no una columna más.

        Si `without_access` viajara en todas las fichas, el JS tendría que
        distinguir `false` de ausente y la pantalla se llenaría de rótulos que
        no dicen nada.
        """
        with grant():
            data = page_data(pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text)

        assert data["users"], "la BD de desarrollo no tiene usuarios con acceso a adhoc"
        assert not [u for u in data["users"] if u.get("without_access")]

    def test_tambien_en_los_validadores_de_un_paso(
            self, pages_client, headers, grant, flow_step, usuario_sin_acceso,
            db_session):
        """El otro destino de la pantalla tiene el mismo problema.

        Los validadores de un paso salen de `get_step_details`, que tampoco
        filtra por acceso: un validador dado de baja se preselecciona igual. La
        conciliación va en el `page_data`, que es donde se juntan los dos
        conjuntos, así que cubre las cuatro acciones sin repetirse.
        """
        flow_step.assignees.append(usuario_sin_acceso)
        db_session.flush()

        with grant():
            data = page_data(pages_client.get(
                f"/adhoc/asignaciones?action=step_assign&step_id={flow_step.id}",
                headers=headers).text)

        assert usuario_sin_acceso.id in data["selected_ids"]
        ficha = next((u for u in data["users"] if u["id"] == usuario_sin_acceso.id), None)
        assert ficha is not None and ficha["without_access"] is True

    def test_el_picker_pinta_la_marca_y_avisa_antes_de_guardar(self):
        """La regla la escribe el servidor una vez; el JS solo la obedece.

        Tres piezas y ninguna vuelve a decidir quién tiene acceso: el picker
        marca la ficha y la fila de la lista, `selectionWithoutAccess()` delata
        lo que sigue seleccionado, y `assignments.js` lo pregunta antes de
        mandar el PUT. Sin lo último, quien seguía la instrucción del aviso
        —marcar a alguien y Guardar— dejaba al bloqueado dentro.
        """
        picker = _strip_js_comments(
            (STATIC_DIR / "js" / "shared" / "user-picker.js").read_text(encoding="utf-8"))
        assign = _strip_js_comments(
            (STATIC_DIR / "js" / "work" / "assignments.js").read_text(encoding="utf-8"))

        assert "without_access" in picker
        assert "adhoc-chip-off" in picker and "adhoc-user-option-flag" in picker
        assert "selectionWithoutAccess" in picker
        # El aviso va ANTES del envío, o no sirve de nada.
        aviso = assign.index("selectionWithoutAccess")
        envio = assign.index("Assignments.prototype.send")
        assert aviso < envio
        assert "confirmDialog" in assign

    def test_usa_el_user_picker_compartido_sin_option_de_jinja(self, pages_client, headers,
                                                               grant, incident_task):
        with grant():
            html = pages_client.get(
                f"/adhoc/asignaciones?action=assign&task_id={incident_task.id}",
                headers=headers).text
        assert "data-adhoc-user-picker" in html
        assert 'data-adhoc-ordered="1"' in html
        assert "/static/adhoc/js/shared/user-picker.js?v=" in html
        # El bloque de datos es el ÚNICO sitio donde viajan los usuarios.
        cuerpo = html.split('<script id="adhoc-page-data"')[0]
        assert "<option" not in cuerpo


# ==========================================================================
# safe_return_to — unitario, sin HTTP
# ==========================================================================

class TestSafeReturnTo:
    @pytest.mark.parametrize("valor", [
        None, "", "   ", "https://evil.example", "//evil.example", "/\\evil.example",
        "http://localhost/adhoc/x", "/itcj/config", "/adhocolate", "javascript:alert(1)",
    ])
    def test_rechaza_lo_que_no_es_ruta_interna(self, valor):
        from itcj2.apps.adhoc.pages._work_context import safe_return_to

        assert safe_return_to(valor, "/adhoc/dashboard") == "/adhoc/dashboard"

    @pytest.mark.parametrize("valor", [
        "/adhoc", "/adhoc/", "/adhoc/programas", "/adhoc/incidencias/3/tareas?x=1",
    ])
    def test_acepta_rutas_de_la_app(self, valor):
        from itcj2.apps.adhoc.pages._work_context import safe_return_to

        assert safe_return_to(valor, "/adhoc/dashboard") == valor


# ==========================================================================
# picker_users — la conciliación de los dos conjuntos, sin HTTP
# ==========================================================================

class TestPickerUsers:
    def test_sin_seleccion_es_exactamente_assignable_users(self, db_session):
        from itcj2.apps.adhoc.pages._work_context import assignable_users, picker_users

        assert picker_users(db_session, []) == assignable_users(db_session)
        assert picker_users(db_session, None) == assignable_users(db_session)

    def test_un_seleccionado_que_si_puede_entrar_no_se_duplica(self, db_session):
        """El caso normal: la conciliación no puede inflar la lista.

        Si un asignable apareciera dos veces, el picker pintaría dos casillas
        para la misma persona y desmarcar una dejaría la otra puesta.
        """
        from itcj2.apps.adhoc.pages._work_context import assignable_users, picker_users

        asignables = assignable_users(db_session)
        if not asignables:
            pytest.skip("la BD de desarrollo no tiene usuarios con acceso a adhoc")

        salida = picker_users(db_session, [asignables[0]["id"]])
        ids = [u["id"] for u in salida]
        assert len(ids) == len(set(ids))
        assert salida == asignables

    def test_el_que_no_puede_entrar_va_primero_y_marcado(self, db_session,
                                                         usuario_sin_acceso):
        """Primero porque es lo único de la lista que exige una decisión.

        La lista está ordenada por apellido y se recorre buscando a quien
        añadir; al que ya no puede entrar no se le busca —se le retira—.
        """
        from itcj2.apps.adhoc.pages._work_context import picker_users

        salida = picker_users(db_session, [usuario_sin_acceso.id])

        assert salida[0]["id"] == usuario_sin_acceso.id
        assert salida[0]["without_access"] is True
        assert salida[0]["full_name"] == "Zzz Sin Acceso"
        assert not [u for u in salida[1:] if u.get("without_access")]

    def test_un_id_sin_fila_conserva_su_numero(self, db_session):
        """Defensivo: la asociación es FK, así que no debería pasar.

        Pero si pasara, la ficha con el número sigue siendo mejor que perder el
        id de la selección en silencio al guardar.
        """
        from itcj2.apps.adhoc.pages._work_context import picker_users

        salida = picker_users(db_session, [99999999])

        assert salida[0]["id"] == 99999999
        assert salida[0]["full_name"] == "#99999999"
        assert salida[0]["without_access"] is True


# ==========================================================================
# Reglas duras del plan §6.2/§6.3 sobre los archivos de ESTA sección
# ==========================================================================

SECTION_TEMPLATES = [
    TEMPLATES_DIR / "incidents" / "incidents.html",
    TEMPLATES_DIR / "incidents" / "categories.html",
    TEMPLATES_DIR / "programs" / "programs.html",
    TEMPLATES_DIR / "programs" / "categories.html",
    TEMPLATES_DIR / "work" / "_work_item_page.html",
    TEMPLATES_DIR / "work" / "tasks.html",
    TEMPLATES_DIR / "work" / "assignments.html",
]

SECTION_JS = [
    STATIC_DIR / "js" / "work" / "work-items.js",
    STATIC_DIR / "js" / "work" / "tasks.js",
    STATIC_DIR / "js" / "work" / "assignments.js",
    STATIC_DIR / "js" / "incidents" / "incidents.js",
    STATIC_DIR / "js" / "programs" / "programs.js",
]

SECTION_CSS = [
    STATIC_DIR / "css" / "work" / "work-items.css",
    STATIC_DIR / "css" / "work" / "tasks.css",
    STATIC_DIR / "css" / "work" / "assignments.css",
]

JS_NAMESPACE = {
    "work-items.js": "window.AdhocWorkItems",
    "tasks.js": "window.AdhocTasks",
    "assignments.js": "window.AdhocAssignments",
    "incidents.js": "window.AdhocIncidents",
    "programs.js": "window.AdhocPrograms",
}


def _strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


class TestReglasDuras:
    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_template_existe_y_sin_css_inline(self, path):
        assert path.exists(), path
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        assert "<style" not in text
        assert 'style="' not in text

    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_template_sin_handlers_inline(self, path):
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for needle in ("onclick=", "onchange=", "onsubmit=", "oninput="):
            assert needle not in text, f"{path.name} usa {needle}"

    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_template_versiona_todos_sus_estaticos(self, path):
        text = path.read_text(encoding="utf-8")
        for href in re.findall(r'(?:href|src)="(/static/[^"]+)"', text):
            assert "?v=" in href, f"{path.name}: {href} sin versionar"

    @pytest.mark.parametrize("path", SECTION_TEMPLATES, ids=lambda p: p.name)
    def test_template_no_emite_option_con_datos_del_servidor(self, path):
        """Los 7 vectores de XSS del legacy nacían justo aquí."""
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for bloque in re.findall(r"<option[^>]*>.*?</option>", text, re.S):
            assert "{{" not in bloque or "{{ n }}" in bloque, f"{path.name}: {bloque}"

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_es_iife_estricto(self, path):
        assert path.exists(), path
        text = path.read_text(encoding="utf-8")
        assert "'use strict'" in text
        assert text.lstrip().startswith("/**")

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_sin_dialogos_nativos(self, path):
        """Criterio de aceptación 5 del plan, acotado a esta sección."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for needle in ("alert(", "confirm(", "prompt("):
            hits = [
                m.start() for m in re.finditer(re.escape(needle), text)
                if not re.search(r"[\w.]$", text[:m.start()])
            ]
            assert not hits, f"{path.name} usa {needle}"

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_solo_expone_su_namespace(self, path):
        text = path.read_text(encoding="utf-8")
        asignaciones = set(re.findall(r"^\s*(window\.\w+)\s*=", text, re.M))
        assert asignaciones == {JS_NAMESPACE[path.name]}, (path.name, asignaciones)

    @pytest.mark.parametrize("path", SECTION_JS, ids=lambda p: p.name)
    def test_js_no_apunta_a_urls_del_legacy(self, path):
        """Las 9 URLs con el prefijo inexistente `/app_prueba/api/...` (404
        silencioso) no se portan. Se ignoran los comentarios: ahí SÍ se citan,
        para documentar de dónde viene cada endpoint nuevo."""
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        assert "/app_prueba/" not in text

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_existe_y_no_pisa_bootstrap(self, path):
        assert path.exists(), path
        css = path.read_text(encoding="utf-8")
        selectores = re.findall(r"^\s*([.#][^{\n]+?)\s*\{", css, re.M)
        prohibidas = re.compile(
            r"(^|[\s,>])\.(form-control|form-group|form-row|form-label|form-select|"
            r"card|badge-|alert-|bg-)"
        )
        for selector in selectores:
            for parte in selector.split(","):
                parte = parte.strip()
                if not parte.startswith("."):
                    continue
                assert not prohibidas.search(" " + parte), (path.name, parte)

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_comentarios_no_cierran_sobre_un_token(self, path):
        """Gotcha real del repo: un cierre de comentario pegado a un comodín."""
        css = path.read_text(encoding="utf-8")
        assert "-*/" not in css
        assert css.count("/*") == css.count("*/")

    @pytest.mark.parametrize("path", SECTION_CSS, ids=lambda p: p.name)
    def test_css_usa_tokens_y_no_hex_sueltos(self, path):
        """El legacy repetía 45 hex a mano; aquí el color sale de las variables."""
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r":\s*#[0-9a-fA-F]{3,8}\s*;", css)

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
        visibles = {"adhoc.incidents.page.list", "adhoc.dashboard.page.view"}
        with grant(), patch(
            "itcj2.core.services.authz_service.get_user_permissions_for_app",
            return_value=visibles,
        ):
            html = pages_client.get("/adhoc/incidencias", headers=headers).text
        assert 'href="/adhoc/incidencias"' in html
        assert 'href="/adhoc/dashboard"' in html
        # Sin el permiso, la sección no aparece: el menú es fail-closed.
        assert 'href="/adhoc/programas"' not in html

    def test_el_boton_nuevo_depende_del_permiso_de_alta(self, pages_client, headers,
                                                        grant, catalogs):
        sin_alta = ALL_PERMS - {"adhoc.incidents.api.create"}
        with grant(perms=sin_alta):
            html = pages_client.get("/adhoc/incidencias", headers=headers).text
        assert "data-adhoc-work-new" not in html
        assert page_data(html)["can"]["create"] is False


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

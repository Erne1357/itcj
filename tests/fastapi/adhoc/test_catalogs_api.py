"""Tests HTTP de ``api/catalogs.py`` — los seis catálogos simples.

El router agregado de catálogos ya está cableado en
``itcj2/apps/adhoc/router.py`` (sin prefijo: trae dentro sus seis segmentos),
así que el fixture :func:`client` NO lo monta y pega contra las rutas reales de
``create_app()``. Montarlo otra vez duplicaría el árbol y estos tests pasarían
aunque el cableado estuviera mal.

La BD se sustituye por un ``MagicMock`` vía ``dependency_overrides[get_db]`` y
el service se parchea en su **módulo fuente** — los endpoints lo importan
localmente, así que parchear el consumidor no serviría (gotcha del plan §9.1).

Cobertura:

* envelope de cada verbo (``success`` / ``data`` / ``total`` / ``message``);
* ``201`` y reporte de omitidos en el alta masiva;
* mapa de errores del service → HTTP: 404 / 409 / 400, con ``detail`` **string**
  (el cliente ve ``{"error": "...", "status": N}``, no ``{"detail": ...}``);
* 401 sin cookie y 403 sin permiso;
* **los 24 códigos de permiso**, uno por endpoint, comprobados contra el string
  literal de ``database/DML/adhoc/init/02_insert_permissions.sql``;
* 422 de validación: lista vacía, color no-hex, nombre ausente.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.services.catalog_service import (
    BulkCreateResult,
    CatalogDuplicate,
    CatalogInUse,
    CatalogNotFound,
    CatalogValidationError,
)
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

SERVICE = "itcj2.apps.adhoc.services.catalog_service.AdhocCatalogService"
AUTHZ = "itcj2.core.services.authz_cache"

_NOW = datetime(2026, 8, 25, 12, 0, 0)


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(scope="module")
def client():
    """App real: los catálogos vienen del cableado de ``adhoc_router``.

    Alcance de módulo: ``create_app()`` tarda ~0.4 s y aquí hay >90 tests.
    """
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
    """JWT con ``role="admin"`` — bypasea ``require_perms`` (gotcha §9.1)."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    """JWT sin bypass: obliga a pasar por ``cached_has_assignment``/``cached_perms``."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=300, role='staff')}"}


def _area(id_=1, name="Calidad", color="#4834d4", is_active=True):
    return SimpleNamespace(
        id=id_, name=name, color=color, is_active=is_active,
        created_at=_NOW, updated_at=_NOW,
    )


def _process(id_=1, name="Compras", color="#b2bec3", description=None):
    return SimpleNamespace(
        id=id_, name=name, color=color, description=description,
        created_at=_NOW, updated_at=_NOW,
    )


def _named(id_=1, name="Manual"):
    return SimpleNamespace(id=id_, name=name, created_at=_NOW, updated_at=_NOW)


def _any_row(id_=1, name="X"):
    """Fila con TODOS los campos: sirve para cualquiera de los seis ``*Out``."""
    return SimpleNamespace(
        id=id_, name=name, color="#4834d4", is_active=True, description=None,
        created_at=_NOW, updated_at=_NOW,
    )


#: ``(url, permiso_read, permiso_create, permiso_update, permiso_delete)``.
#: Copiados LITERALES de ``database/DML/adhoc/init/02_insert_permissions.sql``.
RESOURCES = [
    ("/api/adhoc/v2/areas",
     "adhoc.areas.api.read", "adhoc.areas.api.create",
     "adhoc.areas.api.update", "adhoc.areas.api.delete"),
    ("/api/adhoc/v2/processes",
     "adhoc.processes.api.read", "adhoc.processes.api.create",
     "adhoc.processes.api.update", "adhoc.processes.api.delete"),
    ("/api/adhoc/v2/document-categories",
     "adhoc.doc_catalogs.api.read", "adhoc.doc_catalogs.api.create",
     "adhoc.doc_catalogs.api.update", "adhoc.doc_catalogs.api.delete"),
    ("/api/adhoc/v2/document-classifications",
     "adhoc.doc_catalogs.api.read", "adhoc.doc_catalogs.api.create",
     "adhoc.doc_catalogs.api.update", "adhoc.doc_catalogs.api.delete"),
    ("/api/adhoc/v2/incident-categories",
     "adhoc.incident_categories.api.read", "adhoc.incident_categories.api.create",
     "adhoc.incident_categories.api.update", "adhoc.incident_categories.api.delete"),
    ("/api/adhoc/v2/program-categories",
     "adhoc.program_categories.api.read", "adhoc.program_categories.api.create",
     "adhoc.program_categories.api.update", "adhoc.program_categories.api.delete"),
]

URLS = [r[0] for r in RESOURCES]


# ==========================================================================
# GET — listado
# ==========================================================================

class TestList:
    def test_areas_envelope(self, client, admin_headers):
        with patch(f"{SERVICE}.list_items", return_value=[_area(), _area(2, "Sistemas")]):
            resp = client.get("/api/adhoc/v2/areas", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["total"] == 2
        assert body["data"][0] == {
            "id": 1, "name": "Calidad", "color": "#4834d4", "is_active": True,
            "created_at": "2026-08-25T12:00:00", "updated_at": "2026-08-25T12:00:00",
        }

    def test_processes_exponen_color_y_description(self, client, admin_headers):
        """Regresión: el legacy guardaba el color dentro de ``description``."""
        with patch(f"{SERVICE}.list_items",
                   return_value=[_process(color="#0f0f0f", description="Texto")]):
            resp = client.get("/api/adhoc/v2/processes", headers=admin_headers)

        item = resp.json()["data"][0]
        assert item["color"] == "#0f0f0f"
        assert item["description"] == "Texto"

    def test_areas_pasa_is_active_al_service(self, client, admin_headers):
        with patch(f"{SERVICE}.list_items", return_value=[]) as spy:
            resp = client.get("/api/adhoc/v2/areas?is_active=false", headers=admin_headers)

        assert resp.status_code == 200
        assert spy.call_args.kwargs["is_active"] is False

    def test_areas_sin_filtro_no_fuerza_is_active(self, client, admin_headers):
        """El legacy tenía el filtro cableado y las filas NULL desaparecían."""
        with patch(f"{SERVICE}.list_items", return_value=[]) as spy:
            client.get("/api/adhoc/v2/areas", headers=admin_headers)

        assert spy.call_args.kwargs["is_active"] is None

    def test_catalogos_de_nombre_no_exponen_is_active(self, client, admin_headers):
        with patch(f"{SERVICE}.list_items", return_value=[]) as spy:
            client.get("/api/adhoc/v2/incident-categories?is_active=true",
                       headers=admin_headers)

        assert "is_active" not in spy.call_args.kwargs

    def test_search_llega_al_service(self, client, admin_headers):
        with patch(f"{SERVICE}.list_items", return_value=[]) as spy:
            client.get("/api/adhoc/v2/program-categories?search=audit", headers=admin_headers)

        assert spy.call_args.kwargs["search"] == "audit"

    @pytest.mark.parametrize("url", URLS)
    def test_todas_las_rutas_responden(self, client, admin_headers, url):
        with patch(f"{SERVICE}.list_items", return_value=[]):
            resp = client.get(url, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "data": [], "total": 0}


# ==========================================================================
# POST — alta masiva
# ==========================================================================

class TestBulkCreate:
    def test_crea_y_reporta_omitidos(self, client, admin_headers):
        """LA regresión: un duplicado ya no revierte el lote, se reporta."""
        result = BulkCreateResult(created=[_named(1, "Nuevo")], skipped=["Repetida"])
        with patch(f"{SERVICE}.bulk_create", return_value=result):
            resp = client.post(
                "/api/adhoc/v2/incident-categories",
                json={"items": [{"name": "Nuevo"}, {"name": "Repetida"}]},
                headers=admin_headers,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["total"] == 1
        assert body["data"][0]["name"] == "Nuevo"
        assert body["skipped"] == ["Repetida"]
        assert body["skipped_count"] == 1
        assert "omitido" in body["message"]

    def test_area_aplica_defaults(self, client, admin_headers):
        with patch(f"{SERVICE}.bulk_create",
                   return_value=BulkCreateResult(created=[_area()], skipped=[])) as spy:
            resp = client.post(
                "/api/adhoc/v2/areas",
                json={"items": [{"name": "Calidad"}]},
                headers=admin_headers,
            )

        assert resp.status_code == 201
        assert spy.call_args.args[2] == [
            {"name": "Calidad", "color": "#4834d4", "is_active": True}
        ]

    def test_area_color_vacio_cae_al_default(self, client, admin_headers):
        """El ``<input>`` vacío manda ``""``; plan §2.8 regla 2."""
        with patch(f"{SERVICE}.bulk_create",
                   return_value=BulkCreateResult(created=[_area()], skipped=[])) as spy:
            client.post(
                "/api/adhoc/v2/areas",
                json={"items": [{"name": "Calidad", "color": ""}]},
                headers=admin_headers,
            )

        assert spy.call_args.args[2][0]["color"] == "#4834d4"

    def test_process_separa_color_de_description(self, client, admin_headers):
        with patch(f"{SERVICE}.bulk_create",
                   return_value=BulkCreateResult(created=[_process()], skipped=[])) as spy:
            client.post(
                "/api/adhoc/v2/processes",
                json={"items": [{"name": "Compras", "color": "#0f0f0f",
                                 "description": "Proceso de compras"}]},
                headers=admin_headers,
            )

        assert spy.call_args.args[2][0] == {
            "name": "Compras", "color": "#0f0f0f", "description": "Proceso de compras",
        }

    @pytest.mark.parametrize("url", URLS)
    def test_lista_vacia_es_422(self, client, admin_headers, url):
        resp = client.post(url, json={"items": []}, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.parametrize("url", URLS)
    def test_nombre_ausente_es_422(self, client, admin_headers, url):
        resp = client.post(url, json={"items": [{}]}, headers=admin_headers)
        assert resp.status_code == 422

    @pytest.mark.parametrize("url", URLS)
    def test_nombre_en_blanco_es_422(self, client, admin_headers, url):
        resp = client.post(url, json={"items": [{"name": "   "}]}, headers=admin_headers)
        assert resp.status_code == 422

    def test_color_no_hex_es_422(self, client, admin_headers):
        resp = client.post(
            "/api/adhoc/v2/areas",
            json={"items": [{"name": "X", "color": "rojo"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_color_de_3_digitos_es_422(self, client, admin_headers):
        resp = client.post(
            "/api/adhoc/v2/processes",
            json={"items": [{"name": "X", "color": "#fff"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_tope_de_lote(self, client, admin_headers):
        resp = client.post(
            "/api/adhoc/v2/program-categories",
            json={"items": [{"name": f"c{i}"} for i in range(201)]},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_error_de_validacion_del_service_es_400(self, client, admin_headers):
        with patch(f"{SERVICE}.bulk_create",
                   side_effect=CatalogValidationError("Campo no permitido")):
            resp = client.post(
                "/api/adhoc/v2/areas",
                json={"items": [{"name": "X"}]},
                headers=admin_headers,
            )
        assert resp.status_code == 400
        assert resp.json()["error"] == "Campo no permitido"

    def test_carrera_de_duplicado_es_409(self, client, admin_headers):
        with patch(f"{SERVICE}.bulk_create",
                   side_effect=CatalogDuplicate("Ya existe un área con ese nombre")):
            resp = client.post(
                "/api/adhoc/v2/areas",
                json={"items": [{"name": "X"}]},
                headers=admin_headers,
            )
        assert resp.status_code == 409
        assert resp.json()["error"] == "Ya existe un área con ese nombre"


# ==========================================================================
# PATCH
# ==========================================================================

class TestUpdate:
    def test_actualiza(self, client, admin_headers):
        with patch(f"{SERVICE}.update", return_value=_named(7, "Renombrada")) as spy:
            resp = client.patch(
                "/api/adhoc/v2/document-categories/7",
                json={"name": "Renombrada"},
                headers=admin_headers,
            )

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "data": {
            "id": 7, "name": "Renombrada",
            "created_at": "2026-08-25T12:00:00", "updated_at": "2026-08-25T12:00:00",
        }}
        assert spy.call_args.args[2] == 7
        assert spy.call_args.args[3] == {"name": "Renombrada"}

    def test_solo_envia_los_campos_presentes(self, client, admin_headers):
        with patch(f"{SERVICE}.update", return_value=_area()) as spy:
            client.patch("/api/adhoc/v2/areas/1", json={"is_active": False},
                         headers=admin_headers)

        assert spy.call_args.args[3] == {"is_active": False}

    def test_id_inexistente_es_404_con_error_string(self, client, admin_headers):
        """Regresión: el legacy tragaba el ``get_or_404`` y redirigía "exitoso"."""
        with patch(f"{SERVICE}.update",
                   side_effect=CatalogNotFound("No se encontró el área con id 99")):
            resp = client.patch("/api/adhoc/v2/areas/99", json={"name": "X"},
                                headers=admin_headers)

        assert resp.status_code == 404
        body = resp.json()
        assert isinstance(body["error"], str)
        assert body["error"] == "No se encontró el área con id 99"
        assert body["status"] == 404
        assert "detail" not in body

    def test_nombre_duplicado_es_409(self, client, admin_headers):
        with patch(f"{SERVICE}.update",
                   side_effect=CatalogDuplicate("Ya existe un proceso con el nombre «X»")):
            resp = client.patch("/api/adhoc/v2/processes/1", json={"name": "X"},
                                headers=admin_headers)

        assert resp.status_code == 409
        assert resp.json()["error"] == "Ya existe un proceso con el nombre «X»"

    def test_body_vacio_es_400(self, client, admin_headers):
        with patch(f"{SERVICE}.update",
                   side_effect=CatalogValidationError("No se recibió ningún campo para actualizar")):
            resp = client.patch("/api/adhoc/v2/areas/1", json={}, headers=admin_headers)

        assert resp.status_code == 400
        assert resp.json()["error"] == "No se recibió ningún campo para actualizar"

    def test_nombre_vacio_llega_como_none_al_service(self, client, admin_headers):
        """``""`` → ``None`` (plan §2.8) y el service lo rechaza con 400."""
        with patch(f"{SERVICE}.update",
                   side_effect=CatalogValidationError("El campo «name» no puede quedar vacío")) as spy:
            resp = client.patch("/api/adhoc/v2/areas/1", json={"name": ""},
                                headers=admin_headers)

        assert spy.call_args.args[3] == {"name": None}
        assert resp.status_code == 400

    def test_color_no_hex_es_422(self, client, admin_headers):
        resp = client.patch("/api/adhoc/v2/areas/1", json={"color": "azul"},
                            headers=admin_headers)
        assert resp.status_code == 422


# ==========================================================================
# DELETE
# ==========================================================================

class TestDelete:
    def test_borra(self, client, admin_headers):
        with patch(f"{SERVICE}.delete") as spy:
            resp = client.delete("/api/adhoc/v2/areas/3", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Área eliminada"}
        assert spy.call_args.args[2] == 3

    def test_en_uso_es_409_con_desglose(self, client, admin_headers):
        """Regresión: el legacy tragaba el ``IntegrityError`` y decía "listo"."""
        msg = "No se puede eliminar el área «Calidad»: está en uso por 3 documentos y 1 incidencia."
        with patch(f"{SERVICE}.delete", side_effect=CatalogInUse(msg)):
            resp = client.delete("/api/adhoc/v2/areas/3", headers=admin_headers)

        assert resp.status_code == 409
        assert resp.json()["error"] == msg

    def test_id_inexistente_es_404(self, client, admin_headers):
        with patch(f"{SERVICE}.delete",
                   side_effect=CatalogNotFound("No se encontró el proceso con id 99")):
            resp = client.delete("/api/adhoc/v2/processes/99", headers=admin_headers)

        assert resp.status_code == 404

    @pytest.mark.parametrize("url,mensaje", [
        ("/api/adhoc/v2/areas", "Área eliminada"),
        ("/api/adhoc/v2/processes", "Proceso eliminado"),
        ("/api/adhoc/v2/document-categories", "Categoría de documento eliminada"),
        ("/api/adhoc/v2/document-classifications", "Clasificación de documento eliminada"),
        ("/api/adhoc/v2/incident-categories", "Categoría de incidencia eliminada"),
        ("/api/adhoc/v2/program-categories", "Categoría de programa eliminada"),
    ])
    def test_mensaje_por_recurso(self, client, admin_headers, url, mensaje):
        with patch(f"{SERVICE}.delete"):
            resp = client.delete(f"{url}/1", headers=admin_headers)
        assert resp.json()["message"] == mensaje


# ==========================================================================
# Autorización
# ==========================================================================

class TestAuth:
    @pytest.mark.parametrize("url", URLS)
    def test_get_sin_cookie_es_401(self, client, url):
        assert client.get(url).status_code == 401

    @pytest.mark.parametrize("url", URLS)
    def test_post_sin_cookie_es_401(self, client, url):
        assert client.post(url, json={"items": [{"name": "X"}]}).status_code == 401

    @pytest.mark.parametrize("url", URLS)
    def test_patch_sin_cookie_es_401(self, client, url):
        assert client.patch(f"{url}/1", json={"name": "X"}).status_code == 401

    @pytest.mark.parametrize("url", URLS)
    def test_delete_sin_cookie_es_401(self, client, url):
        assert client.delete(f"{url}/1").status_code == 401

    @pytest.mark.parametrize("url", URLS)
    def test_sin_acceso_a_la_app_es_403(self, client, staff_headers, url):
        with patch(f"{AUTHZ}.cached_has_assignment", return_value=False):
            resp = client.get(url, headers=staff_headers)
        assert resp.status_code == 403
        assert "adhoc" in resp.json()["error"]

    @pytest.mark.parametrize(
        "url,perm_read,perm_create,perm_update,perm_delete", RESOURCES,
    )
    def test_cada_endpoint_exige_su_permiso(
        self, client, staff_headers, url, perm_read, perm_create, perm_update, perm_delete,
    ):
        """Los códigos son los de ``02_insert_permissions.sql``, literales.

        Con el permiso correcto pasa; con un permiso ajeno responde 403. Es lo
        que impide que un typo en el string quede invisible.
        """
        casos = [
            (perm_read, lambda: client.get(url, headers=staff_headers), f"{SERVICE}.list_items", []),
            (perm_create,
             lambda: client.post(url, json={"items": [{"name": "X"}]}, headers=staff_headers),
             f"{SERVICE}.bulk_create", BulkCreateResult(created=[], skipped=[])),
            (perm_update,
             lambda: client.patch(f"{url}/1", json={"name": "X"}, headers=staff_headers),
             f"{SERVICE}.update", _any_row()),
            (perm_delete,
             lambda: client.delete(f"{url}/1", headers=staff_headers),
             f"{SERVICE}.delete", None),
        ]

        for perm, call, target, retval in casos:
            with patch(f"{AUTHZ}.cached_has_assignment", return_value=True), \
                 patch(f"{AUTHZ}.cached_perms", return_value={perm}), \
                 patch(target, return_value=retval):
                assert call().status_code in (200, 201), f"{perm} debería permitir {url}"

            with patch(f"{AUTHZ}.cached_has_assignment", return_value=True), \
                 patch(f"{AUTHZ}.cached_perms", return_value={"adhoc.otro.api.read"}), \
                 patch(target, return_value=retval):
                resp = call()
            assert resp.status_code == 403, f"{perm} no debería concederse por otro permiso"
            assert perm in resp.json()["error"]

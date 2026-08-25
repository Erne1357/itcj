"""Tests HTTP de ``/api/adhoc/v2/incidents``.

El router de incidencias ya está cableado en ``itcj2/apps/adhoc/router.py``,
así que la fixture :func:`incidents_client` usa la app REAL de ``create_app()``
tal cual, sin montar nada. Con eso el test pasa por el ``JWTMiddleware`` y por
el manejador global de ``HTTPException`` de verdad — que es justo lo que se
quiere verificar: el cliente ve ``{"error": "...", "status": N}``, **no**
``{"detail": ...}``.

Gotchas del harness aplicados (plan §9.1):

* Un JWT con ``role="admin"`` **bypasea** ``require_perms``. Para probar que
  los permisos están bien puestos hace falta ``role="staff"`` + parche de
  ``cached_has_assignment`` / ``cached_perms``.
* Los parches van sobre el **módulo fuente**
  (``itcj2.core.services.authz_cache``), porque ``require_perms`` importa esos
  nombres dentro de la función.
* ``get_db`` se sobreescribe con la sesión transaccional del test para que lo
  que escriba el endpoint sea visible al assert y se revierta al final.
"""
from unittest.mock import patch

import pytest

from tests.conftest import make_jwt


PERMS = {
    "adhoc.incidents.api.read",
    "adhoc.incidents.api.create",
    "adhoc.incidents.api.update",
    "adhoc.incidents.api.delete",
}

BASE = "/api/adhoc/v2/incidents"


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture()
def incidents_client(app_client, db_session):
    """TestClient real (router ya cableado) con ``get_db`` fijado al test."""
    from itcj2.database import get_db

    app = app_client.app

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield app_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def admin_headers():
    """Admin global: bypasea ``require_perms`` por diseño."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=200, role='admin')}"}


@pytest.fixture()
def staff_headers():
    """Usuario sin bypass: su autorización depende de los permisos reales."""
    return {"Cookie": f"itcj_token={make_jwt(user_id=201, role='staff')}"}


@pytest.fixture()
def grant(staff_headers):
    """Context manager que finge la asignación y los permisos del staff."""
    from contextlib import contextmanager

    @contextmanager
    def _grant(*, assigned=True, perms=PERMS):
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
    from itcj2.apps.adhoc.models.incidents import AdhocIncidentCategory
    from itcj2.apps.adhoc.models.structure import AdhocArea

    area = AdhocArea(name="e2e_api_area")
    category = AdhocIncidentCategory(name="e2e_api_cat")
    db_session.add_all([area, category])
    db_session.flush()
    return {"area": area, "category": category}


def _crear(client, headers, **campos):
    payload = {"title": "Incidencia API"}
    payload.update(campos)
    resp = client.post(BASE, json={"items": [payload]}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"][0]


# ==========================================================================
# Autenticación y autorización
# ==========================================================================

@pytest.mark.parametrize(
    "metodo,url",
    [("get", BASE), ("post", BASE), ("patch", f"{BASE}/1"), ("delete", f"{BASE}/1")],
)
def test_sin_cookie_es_401(incidents_client, metodo, url):
    """Ninguno de los 4 endpoints responde 200 sin sesión (bug #1 del legacy)."""
    resp = incidents_client.request(metodo.upper(), url, json={})
    assert resp.status_code == 401
    assert resp.json()["error"]


def test_sin_acceso_a_la_app_es_403(incidents_client, staff_headers, grant):
    with grant(assigned=False):
        resp = incidents_client.get(BASE, headers=staff_headers)
    assert resp.status_code == 403
    assert "adhoc" in resp.json()["error"]


def test_sin_el_permiso_concreto_es_403(incidents_client, staff_headers, grant):
    """Tener la app no basta: cada verbo pide su propio permiso."""
    with grant(perms={"adhoc.incidents.api.read"}):
        lectura = incidents_client.get(BASE, headers=staff_headers)
        escritura = incidents_client.post(
            BASE, json={"items": [{"title": "x"}]}, headers=staff_headers
        )
    assert lectura.status_code == 200
    assert escritura.status_code == 403
    assert "adhoc.incidents.api.create" in escritura.json()["error"]


def test_con_los_permisos_reales_funciona_sin_ser_admin(
    incidents_client, staff_headers, grant
):
    with grant():
        resp = incidents_client.post(
            BASE, json={"items": [{"title": "e2e_staff"}]}, headers=staff_headers
        )
    assert resp.status_code == 201


# ==========================================================================
# Contrato de error
# ==========================================================================

def test_el_error_es_error_y_status_no_detail(incidents_client, admin_headers):
    """El handler global publica ``{"error": str, "status": N}``."""
    resp = incidents_client.delete(f"{BASE}/987654321", headers=admin_headers)
    cuerpo = resp.json()
    assert resp.status_code == 404
    assert set(cuerpo) == {"error", "status"}
    assert isinstance(cuerpo["error"], str)  # detail STRING, nunca dict anidado
    assert cuerpo["status"] == 404


# ==========================================================================
# GET ""
# ==========================================================================

def test_listado_devuelve_el_sobre_paginado(incidents_client, admin_headers):
    _crear(incidents_client, admin_headers, title="e2e_api_list", folio="e2e_api_list")

    resp = incidents_client.get(
        BASE, params={"q": "e2e_api_list"}, headers=admin_headers
    )
    cuerpo = resp.json()

    assert resp.status_code == 200
    assert cuerpo["success"] is True
    assert {"data", "total", "page", "per_page", "total_pages"} <= set(cuerpo)
    assert cuerpo["total"] == 1
    assert cuerpo["data"][0]["title"] == "e2e_api_list"


def test_listado_pagina(incidents_client, admin_headers):
    for n in range(3):
        _crear(incidents_client, admin_headers, title=f"e2e_api_pg_{n}",
               folio=f"e2e_api_pg_{n}")

    resp = incidents_client.get(
        BASE, params={"q": "e2e_api_pg_", "page": 1, "per_page": 2},
        headers=admin_headers,
    )
    cuerpo = resp.json()
    assert len(cuerpo["data"]) == 2
    assert (cuerpo["total"], cuerpo["total_pages"], cuerpo["page"]) == (3, 2, 1)


def test_listado_trae_catalogos_y_task_count(incidents_client, admin_headers,
                                             catalogs, db_session):
    from itcj2.apps.adhoc.models.tasks import AdhocTask

    creada = _crear(
        incidents_client, admin_headers, title="e2e_api_rel", folio="e2e_api_rel",
        area_id=catalogs["area"].id, category_id=catalogs["category"].id,
    )
    db_session.add(AdhocTask(description="t", incident_id=creada["id"]))
    db_session.flush()

    fila = incidents_client.get(
        BASE, params={"q": "e2e_api_rel"}, headers=admin_headers
    ).json()["data"][0]

    assert fila["area"]["name"] == "e2e_api_area"
    assert fila["category"]["name"] == "e2e_api_cat"
    assert fila["task_count"] == 1


def test_listado_tolera_filtros_en_blanco(incidents_client, admin_headers):
    """Los ``<select>`` de esta app mandan ``value=""``: no puede ser un 422."""
    resp = incidents_client.get(
        BASE,
        params={"area_id": "", "category_id": "", "status": "", "priority": "",
                "start_from": "", "q": ""},
        headers=admin_headers,
    )
    assert resp.status_code == 200


def test_listado_con_status_invalido_es_400(incidents_client, admin_headers):
    resp = incidents_client.get(
        BASE, params={"status": "Completado"}, headers=admin_headers
    )
    assert resp.status_code == 400
    assert "Completado" in resp.json()["error"]


def test_listado_con_filtro_no_numerico_es_400(incidents_client, admin_headers):
    resp = incidents_client.get(BASE, params={"area_id": "abc"}, headers=admin_headers)
    assert resp.status_code == 400


def test_listado_con_orden_no_permitido_es_400(incidents_client, admin_headers):
    resp = incidents_client.get(
        BASE, params={"order_by": "(select 1)"}, headers=admin_headers
    )
    assert resp.status_code == 400


# ==========================================================================
# POST "" (alta masiva)
# ==========================================================================

def test_alta_masiva_crea_varias(incidents_client, admin_headers):
    resp = incidents_client.post(
        BASE,
        json={"items": [{"title": "e2e_api_b1"}, {"title": "e2e_api_b2",
                                                  "priority": "Urgente"}]},
        headers=admin_headers,
    )
    cuerpo = resp.json()

    assert resp.status_code == 201
    assert cuerpo["success"] is True and cuerpo["total"] == 2
    assert cuerpo["data"][0]["priority"] == "Media"      # default NOT NULL
    assert cuerpo["data"][0]["status"] == "No Iniciada"
    assert cuerpo["data"][1]["priority"] == "Urgente"


def test_alta_masiva_acepta_listas_paralelas_del_legacy(incidents_client, admin_headers):
    resp = incidents_client.post(
        BASE,
        json={"titles[]": ["e2e_api_p1", "e2e_api_p2"], "priorities[]": ["Alta", ""],
              "area_ids[]": ["", ""]},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    assert [i["priority"] for i in resp.json()["data"]] == ["Alta", "Media"]


def test_alta_masiva_con_listas_descuadradas_es_422(incidents_client, admin_headers):
    """Antes eso era un campo vacío en el registro equivocado, en silencio."""
    resp = incidents_client.post(
        BASE, json={"titles": ["a", "b", "c"], "priorities": ["Alta"]},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_alta_masiva_sin_titulo_es_422(incidents_client, admin_headers):
    resp = incidents_client.post(
        BASE, json={"items": [{"folio": "sin-titulo"}]}, headers=admin_headers
    )
    assert resp.status_code == 422


def test_alta_masiva_con_status_fuera_del_vocabulario_es_422(incidents_client,
                                                             admin_headers):
    resp = incidents_client.post(
        BASE, json={"items": [{"title": "x", "status": "Completado"}]},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_alta_masiva_vacia_es_422(incidents_client, admin_headers):
    resp = incidents_client.post(BASE, json={"items": []}, headers=admin_headers)
    assert resp.status_code == 422


def test_alta_masiva_con_fk_inexistente_es_400_y_no_inserta_nada(
    incidents_client, admin_headers
):
    resp = incidents_client.post(
        BASE,
        json={"items": [{"title": "e2e_api_fk_ok"},
                        {"title": "e2e_api_fk_mala", "area_id": 987654321}]},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "987654321" in resp.json()["error"]

    quedan = incidents_client.get(
        BASE, params={"q": "e2e_api_fk_"}, headers=admin_headers
    ).json()
    assert quedan["total"] == 0


# ==========================================================================
# PATCH /{id}
# ==========================================================================

def test_patch_actualiza_solo_lo_enviado(incidents_client, admin_headers):
    creada = _crear(incidents_client, admin_headers, title="Antes", folio="e2e_api_up",
                    priority="Alta")

    resp = incidents_client.patch(
        f"{BASE}/{creada['id']}", json={"title": "Después"}, headers=admin_headers
    )
    cuerpo = resp.json()

    assert resp.status_code == 200
    assert cuerpo["success"] is True
    assert cuerpo["data"]["title"] == "Después"
    assert cuerpo["data"]["folio"] == "e2e_api_up"
    assert cuerpo["data"]["priority"] == "Alta"


def test_patch_con_priority_en_blanco_no_rompe_el_not_null(incidents_client,
                                                           admin_headers):
    """Regresión de ``edit_incident``: ``priorities[1]`` ausente -> ``None``."""
    creada = _crear(incidents_client, admin_headers, title="x", priority="Alta")
    resp = incidents_client.patch(
        f"{BASE}/{creada['id']}", json={"priority": ""}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["priority"] == "Media"


def test_patch_guarda_las_fechas_como_date(incidents_client, admin_headers):
    creada = _crear(incidents_client, admin_headers, title="x")
    resp = incidents_client.patch(
        f"{BASE}/{creada['id']}", json={"real_date": "2026-07-08"},
        headers=admin_headers,
    )
    assert resp.json()["data"]["real_date"] == "2026-07-08"


def test_patch_de_inexistente_es_404(incidents_client, admin_headers):
    """El legacy respondía un redirect 'exitoso'."""
    resp = incidents_client.patch(
        f"{BASE}/987654321", json={"title": "x"}, headers=admin_headers
    )
    assert resp.status_code == 404


def test_patch_con_status_invalido_es_422(incidents_client, admin_headers):
    creada = _crear(incidents_client, admin_headers, title="x")
    resp = incidents_client.patch(
        f"{BASE}/{creada['id']}", json={"status": "Completado"}, headers=admin_headers
    )
    assert resp.status_code == 422


def test_patch_con_fk_inexistente_es_400(incidents_client, admin_headers):
    creada = _crear(incidents_client, admin_headers, title="x")
    resp = incidents_client.patch(
        f"{BASE}/{creada['id']}", json={"process_id": 987654321}, headers=admin_headers
    )
    assert resp.status_code == 400


# ==========================================================================
# DELETE /{id}
# ==========================================================================

def test_delete_borra_y_responde_mensaje(incidents_client, admin_headers):
    creada = _crear(incidents_client, admin_headers, title="e2e_api_del",
                    folio="e2e_api_del")

    resp = incidents_client.delete(f"{BASE}/{creada['id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "message": "Incidencia eliminada"}

    quedan = incidents_client.get(
        BASE, params={"q": "e2e_api_del"}, headers=admin_headers
    ).json()
    assert quedan["total"] == 0


def test_delete_arrastra_las_tareas_hijas(incidents_client, admin_headers, db_session):
    from itcj2.apps.adhoc.models.tasks import AdhocTask

    creada = _crear(incidents_client, admin_headers, title="e2e_api_del_casc")
    tarea = AdhocTask(description="t", incident_id=creada["id"])
    db_session.add(tarea)
    db_session.flush()
    tarea_id = tarea.id

    assert incidents_client.delete(
        f"{BASE}/{creada['id']}", headers=admin_headers
    ).status_code == 200

    db_session.expire_all()
    assert db_session.get(AdhocTask, tarea_id) is None


def test_delete_de_inexistente_es_404(incidents_client, admin_headers):
    resp = incidents_client.delete(f"{BASE}/987654321", headers=admin_headers)
    assert resp.status_code == 404

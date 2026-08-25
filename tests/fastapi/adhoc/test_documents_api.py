"""Tests de la API v2 de documentos y flujos de aprobación (Adhoc / Calidad).

Cubren el contrato del plan §3: sobre ``{"success": True, ...}``, errores
``{"error": "<texto>", "status": N}`` (**nunca** ``{"detail": ...}``), 401 sin
cookie y 403 sin permiso.

Dos particularidades del harness que conviene tener presentes:

1. Los sub-routers ya están cableados en ``itcj2/apps/adhoc/router.py``, así
   que el fixture NO los monta: usa las rutas reales de ``create_app()``. (El
   guard anterior miraba ``app.routes``, que en esta versión de FastAPI ya no
   expone las rutas anidadas, así que siempre duplicaba el montaje.)
2. Un JWT con ``role="admin"`` **bypasea ``require_perms``** (``dependencies.py``
   corta antes de tocar la BD). Sirve para el camino feliz; para probar que los
   permisos están bien puestos hay que usar ``role="staff"`` y parchear
   ``cached_has_assignment`` / ``cached_perms`` **en su módulo fuente**
   (``itcj2.core.services.authz_cache``), porque el endpoint los importa dentro
   de la función.
"""
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from itcj2.apps.adhoc.models import (
    AdhocApprovalFlow,
    AdhocApprovalFlowStep,
    AdhocDocument,
)
from itcj2.apps.adhoc.services import upload_service
from itcj2.core.models.user import User
from itcj2.database import get_db
from tests.conftest import TEST_SECRET, make_jwt

API = "/api/adhoc/v2"
DOCS = f"{API}/documents"
FLOWS = f"{API}/approval-flows"


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------

@pytest.fixture()
def client(db_session):
    """App real (routers ya cableados), atada a la sesión del test."""
    with patch("itcj2.middleware._JWT_SECRET", TEST_SECRET):
        from itcj2.main import create_app

        app = create_app()

        def _override():
            yield db_session

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def admin_cookies():
    return {"itcj_token": make_jwt(user_id=1, role="admin")}


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    class _S:
        ADHOC_UPLOAD_PATH = str(tmp_path)
        ADHOC_MAX_FILE_SIZE = 1024 * 1024
        ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"

    monkeypatch.setattr(upload_service, "_settings", lambda: _S())
    return tmp_path


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------

def make_user(db, label="val"):
    tag = uuid.uuid4().hex[:10]
    u = User(
        first_name=label.upper(), last_name="ADHOC",
        username=f"e2e_adhoc_{label}_{tag}",
        email=f"e2e_adhoc_{label}_{tag}@test.local",
    )
    db.add(u)
    db.flush()
    return u


def make_flow(db, steps=(("Revisión", 3), ("Autorización", 5))):
    flow = AdhocApprovalFlow(name=f"e2e_flow_{uuid.uuid4().hex[:8]}")
    db.add(flow)
    db.flush()
    for i, (name, days) in enumerate(steps, start=1):
        db.add(AdhocApprovalFlowStep(
            flow_id=flow.id, name=name, days_limit=days, step_order=i,
        ))
    db.flush()
    db.refresh(flow)
    return flow


def make_document(db, **kw):
    kw.setdefault("title", f"e2e_doc_{uuid.uuid4().hex[:8]}")
    kw.setdefault("status", "Borrador")
    doc = AdhocDocument(**kw)
    db.add(doc)
    db.flush()
    return doc


# ==========================================================================
# Autenticación y autorización
# ==========================================================================

@pytest.mark.parametrize("method,path", [
    ("get", DOCS),
    ("post", DOCS),
    ("get", f"{DOCS}/1"),
    ("patch", f"{DOCS}/1"),
    ("delete", f"{DOCS}/1"),
    ("get", f"{DOCS}/1/download"),
    ("post", f"{DOCS}/1/start-flow"),
    ("get", FLOWS),
    ("post", FLOWS),
    ("patch", f"{FLOWS}/1"),
    ("delete", f"{FLOWS}/1"),
    ("get", f"{FLOWS}/1/steps"),
    ("put", f"{FLOWS}/1/steps"),
    ("get", f"{FLOWS}/steps/1"),
    ("put", f"{FLOWS}/steps/1/validators"),
    ("put", f"{FLOWS}/steps/1/overdue-notifications"),
])
def test_sin_cookie_es_401(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.json()["error"]


def test_sin_permiso_es_403(client):
    """``role="staff"`` no bypasea: se comprueban permisos de verdad."""
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value=set()):
        resp = client.get(DOCS, cookies=cookies)
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_con_el_permiso_exacto_pasa(client):
    cookies = {"itcj_token": make_jwt(user_id=1, role="staff")}
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.documents.api.read"}):
        resp = client.get(DOCS, cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ==========================================================================
# Documentos
# ==========================================================================

def test_listado_devuelve_sobre_paginado(client, admin_cookies, db_session):
    make_document(db_session, title="e2e_listado")
    resp = client.get(DOCS, params={"page": 1, "per_page": 5}, cookies=admin_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert {"total", "page", "per_page", "total_pages"} <= set(body)


def test_listado_con_status_invalido_es_400_no_500(client, admin_cookies):
    resp = client.get(DOCS, params={"status": "Inventado"}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_alta_masiva_multipart(client, admin_cookies, uploads_root, db_session):
    resp = client.post(
        DOCS,
        data={
            "titles": ["e2e Manual", "e2e Procedimiento"],
            "codes": ["E2E-1", "E2E-2"],
            "versions": ["", "2.0"],
        },
        files=[("files", ("evidencia.pdf", BytesIO(b"pdf"), "application/pdf"))],
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    creados = {d["title"]: d for d in body["data"]}
    assert creados["e2e Manual"]["version"] == "1.0"
    assert creados["e2e Procedimiento"]["version"] == "2.0"
    assert creados["e2e Manual"]["has_file"] is True
    assert creados["e2e Procedimiento"]["has_file"] is False


def test_alta_masiva_sin_filas_utiles_es_400(client, admin_cookies):
    resp = client.post(DOCS, data={"titles": ["   "]}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_alta_masiva_con_fk_inexistente_es_400(client, admin_cookies):
    resp = client.post(
        DOCS,
        data={"titles": ["e2e FK"], "area_ids": ["99999999"]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


def test_detalle_de_documento_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{DOCS}/99999999", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Documento no encontrado", "status": 404}


def test_patch_actualiza_solo_lo_enviado(client, admin_cookies, db_session):
    doc = make_document(db_session, code="E2E-P", title="Antes")
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"title": "Después"}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["title"] == "Después"
    assert resp.json()["data"]["code"] == "E2E-P"


def test_patch_sin_cambios_es_400(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.patch(f"{DOCS}/{doc.id}", data={}, cookies=admin_cookies)
    assert resp.status_code == 400


def test_patch_con_status_invalido_es_422(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.patch(
        f"{DOCS}/{doc.id}", data={"status": "Inventado"}, cookies=admin_cookies,
    )
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_delete_documento(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.delete(f"{DOCS}/{doc.id}", cookies=admin_cookies)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert db_session.get(AdhocDocument, doc.id) is None


def test_descarga_sin_adjunto_es_404_json(client, admin_cookies, db_session):
    """El legacy devolvía texto plano ``"El documento no tiene archivo adjunto."``."""
    doc = make_document(db_session)
    resp = client.get(f"{DOCS}/{doc.id}/download", cookies=admin_cookies)
    assert resp.status_code == 404
    assert resp.json()["status"] == 404


def test_descarga_devuelve_el_archivo(client, admin_cookies, uploads_root, db_session):
    doc = make_document(db_session)
    destino = Path(uploads_root) / "documents" / str(doc.id)
    destino.mkdir(parents=True)
    (destino / "informe.pdf").write_bytes(b"%PDF-1.4 e2e")
    doc.file_url = f"{doc.id}/informe.pdf"
    db_session.flush()

    resp = client.get(f"{DOCS}/{doc.id}/download", cookies=admin_cookies)
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 e2e"


# ==========================================================================
# start-flow
# ==========================================================================

def test_start_flow_sin_flow_id_es_400(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.post(f"{DOCS}/{doc.id}/start-flow", json={}, cookies=admin_cookies)
    assert resp.status_code == 400
    assert resp.json()["error"] == "Debe enviar flow_id."


def test_start_flow_con_flujo_inexistente_es_404(client, admin_cookies, db_session):
    doc = make_document(db_session)
    resp = client.post(
        f"{DOCS}/{doc.id}/start-flow", json={"flow_id": 99999999}, cookies=admin_cookies,
    )
    assert resp.status_code == 404


def test_start_flow_camino_feliz(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    doc = make_document(db_session)
    resp = client.post(
        f"{DOCS}/{doc.id}/start-flow", json={"flow_id": flow.id}, cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "En Revisión"
    assert data["current_step_id"] == flow.steps[0].id
    assert "message" in data


# ==========================================================================
# Flujos
# ==========================================================================

def test_crud_de_flujos(client, admin_cookies):
    creado = client.post(FLOWS, json={"name": "e2e Flujo API"}, cookies=admin_cookies)
    assert creado.status_code == 200, creado.text
    flow_id = creado.json()["data"]["id"]
    assert creado.json()["data"]["step_count"] == 0

    listado = client.get(FLOWS, cookies=admin_cookies)
    assert listado.status_code == 200
    assert any(f["id"] == flow_id for f in listado.json()["data"])

    editado = client.patch(
        f"{FLOWS}/{flow_id}", json={"description": "d"}, cookies=admin_cookies,
    )
    assert editado.json()["data"]["description"] == "d"

    borrado = client.delete(f"{FLOWS}/{flow_id}", cookies=admin_cookies)
    assert borrado.status_code == 200
    assert borrado.json()["success"] is True


def test_crear_flujo_sin_nombre_es_422(client, admin_cookies):
    resp = client.post(FLOWS, json={"name": ""}, cookies=admin_cookies)
    assert resp.status_code == 422


def test_upsert_de_pasos_conserva_ids(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    antes = {s.step_order: s.id for s in flow.steps}
    resp = client.put(
        f"{FLOWS}/{flow.id}/steps",
        json={"steps": [
            {"name": "Revisión editada", "days_limit": 7, "step_order": 1},
            {"name": "Autorización", "days_limit": 5, "step_order": 2},
        ]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200, resp.text
    despues = {s["step_order"]: s["id"] for s in resp.json()["data"]}
    assert despues == antes


def test_upsert_de_pasos_con_documento_en_revision_es_409(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    resp = client.put(
        f"{FLOWS}/{flow.id}/steps",
        json={"steps": [{"name": "Solo uno", "step_order": 1}]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409
    assert "error" in resp.json()


def test_delete_flujo_en_uso_es_409(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    make_document(db_session, flow_id=flow.id, current_step_id=flow.steps[0].id,
                  status="En Revisión")
    resp = client.delete(f"{FLOWS}/{flow.id}", cookies=admin_cookies)
    assert resp.status_code == 409


def test_listado_de_pasos_de_flujo_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{FLOWS}/99999999/steps", cookies=admin_cookies)
    assert resp.status_code == 404


# ==========================================================================
# Validadores del paso
# ==========================================================================

def test_validadores_y_notificaciones_de_atraso(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    step_id = flow.steps[0].id
    u1, u2 = make_user(db_session, "a"), make_user(db_session, "b")

    asignar = client.put(
        f"{FLOWS}/steps/{step_id}/validators",
        json={"user_ids": [u1.id, u2.id]},
        cookies=admin_cookies,
    )
    assert asignar.status_code == 200, asignar.text

    marcar = client.put(
        f"{FLOWS}/steps/{step_id}/overdue-notifications",
        json={"user_ids": [u1.id]},
        cookies=admin_cookies,
    )
    assert marcar.status_code == 200

    detalle = client.get(f"{FLOWS}/steps/{step_id}", cookies=admin_cookies)
    data = detalle.json()["data"]
    assert {u["id"] for u in data["assigned"]} == {u1.id, u2.id}
    assert [u["id"] for u in data["notify"]] == [u1.id]

    # Reasignar NO debe borrar el flag (bug del legacy).
    client.put(
        f"{FLOWS}/steps/{step_id}/validators",
        json={"user_ids": [u1.id, u2.id]},
        cookies=admin_cookies,
    )
    detalle2 = client.get(f"{FLOWS}/steps/{step_id}", cookies=admin_cookies)
    assert [u["id"] for u in detalle2.json()["data"]["notify"]] == [u1.id]


def test_validadores_con_usuario_inexistente_es_400(client, admin_cookies, db_session):
    flow = make_flow(db_session)
    resp = client.put(
        f"{FLOWS}/steps/{flow.steps[0].id}/validators",
        json={"user_ids": [99999999]},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


def test_detalle_de_paso_inexistente_es_404(client, admin_cookies):
    resp = client.get(f"{FLOWS}/steps/99999999", cookies=admin_cookies)
    assert resp.status_code == 404

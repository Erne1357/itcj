"""Tests de la API v2 de eventos de programa (``/api/adhoc/v2/program-events``).

El router de adhoc ya está cableado, así que la fixture ``client`` NO monta
nada: pega contra las rutas reales de ``create_app()``. Volver a montarlo
duplicaría el árbol y haría que estos tests pasaran aunque el prefijo del
cableado fuera otro.

Gotchas del harness que se aplican (plan §9.1):

- El cuerpo de error es ``{"error": ..., "status": ...}``, **no** ``{"detail": ...}``.
- Un JWT con ``role="admin"`` **bypasea** ``require_perms``: el 403 se prueba con
  ``role="staff"`` + patch de ``cached_has_assignment`` / ``cached_perms`` en su
  **módulo fuente** (``itcj2.core.services.authz_cache``), porque el dependency
  los importa dentro de la función.
- ``get_db`` se ata a la sesión transaccional del test para que el endpoint vea
  lo que crean las fixtures (y no persista nada).
"""
import json
import uuid
from io import BytesIO

import pytest

from itcj2.apps.adhoc.models import AdhocArea, AdhocProgramEvent, AdhocProgramEventFile
from itcj2.apps.adhoc.services import upload_service
from itcj2.core.models.user import User
from itcj2.database import get_db

from tests.conftest import make_jwt

BASE = "/api/adhoc/v2/program-events"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, root):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024 * 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "_settings", lambda: _FakeSettings(tmp_path))
    return tmp_path


@pytest.fixture()
def actor(db_session):
    """Usuario real en ``core_users``: ``uploaded_by_id`` es FK, no puede inventarse."""
    user = User(first_name="QA", last_name="ADHOC", email="qa.adhoc@example.test")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def client(app_client, db_session):
    """TestClient real (router ya cableado) con ``get_db`` atado al test."""

    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def headers(actor):
    """Cookie de admin global (bypasea ``require_perms``: camino feliz)."""
    return {"Cookie": "itcj_token=" + make_jwt(user_id=actor.id, role="admin")}


def _make_event(db, **kwargs):
    from itcj2.apps.adhoc.schemas.programs import ProgramEventCreate
    from itcj2.apps.adhoc.services import program_event_service as svc

    payload = {"title": "Evento API"}
    payload.update(kwargs)
    return svc.bulk_create(db, [ProgramEventCreate(**payload)])[0]


# --------------------------------------------------------------------------
# Autenticación y autorización
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("get", BASE),
    ("post", BASE),
    ("get", BASE + "/1"),
    ("patch", BASE + "/1"),
    ("delete", BASE + "/1"),
    ("post", BASE + "/1/duplicate"),
    ("get", BASE + "/1/files"),
    ("post", BASE + "/1/files"),
    ("delete", BASE + "/files/1"),
    ("get", BASE + "/files/1/download"),
])
def test_sin_cookie_responde_401(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.json()["error"] == "No autenticado"


def test_sin_permiso_responde_403(client, actor, monkeypatch):
    """Un usuario con acceso a la app pero sin el permiso concreto: 403."""
    from itcj2.core.services import authz_cache

    monkeypatch.setattr(authz_cache, "cached_has_assignment", lambda db, uid, app: True)
    monkeypatch.setattr(authz_cache, "cached_perms", lambda db, uid, app: {"adhoc.dashboard.page.view"})

    staff = {"Cookie": "itcj_token=" + make_jwt(user_id=actor.id, role="staff")}
    resp = client.get(BASE, headers=staff)

    assert resp.status_code == 403
    assert "error" in resp.json()


def test_con_el_permiso_correcto_responde_200(client, actor, monkeypatch):
    from itcj2.core.services import authz_cache

    monkeypatch.setattr(authz_cache, "cached_has_assignment", lambda db, uid, app: True)
    monkeypatch.setattr(authz_cache, "cached_perms", lambda db, uid, app: {"adhoc.programs.api.read"})

    staff = {"Cookie": "itcj_token=" + make_jwt(user_id=actor.id, role="staff")}
    resp = client.get(BASE, headers=staff)

    assert resp.status_code == 200
    assert resp.json()["success"] is True


# --------------------------------------------------------------------------
# GET  (listado)
# --------------------------------------------------------------------------

def test_listado_devuelve_sobre_paginado(client, headers, db_session):
    _make_event(db_session, title="Listado A")
    _make_event(db_session, title="Listado B")

    body = client.get(BASE + "?per_page=1", headers=headers).json()

    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["page"] == 1
    assert body["per_page"] == 1
    assert body["total"] >= 2
    assert body["total_pages"] >= 2


def test_listado_filtra_por_area_y_texto(client, headers, db_session):
    area = AdhocArea(name="e2e_api_area_" + uuid.uuid4().hex[:8])
    db_session.add(area)
    db_session.flush()
    _make_event(db_session, title="Simulacro de incendio", area_id=area.id)
    _make_event(db_session, title="Capacitacion ISO", area_id=area.id)

    body = client.get(BASE, headers=headers, params={"area_id": area.id, "search": "simulacro"}).json()

    assert body["total"] == 1
    assert body["data"][0]["title"] == "Simulacro de incendio"
    assert body["data"][0]["area_name"] == area.name


def test_listado_rechaza_un_status_fuera_del_vocabulario(client, headers):
    resp = client.get(BASE, headers=headers, params={"status": "Inventado"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# POST  (alta masiva multipart)
# --------------------------------------------------------------------------

def test_alta_masiva_crea_eventos_y_adjuntos(client, headers, db_session, uploads_root):
    payload = json.dumps({"events": [
        {"title": "Auditoria interna", "priority": "Alta", "start_date": "2026-05-01"},
        {"title": "Revision por la direccion"},
    ]})

    resp = client.post(
        BASE,
        headers=headers,
        data={"payload": payload, "file_indexes": ["0"]},
        files=[("files", ("evidencia.pdf", BytesIO(b"contenido"), "application/pdf"))],
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["total"] == 2
    assert body["data"][0]["priority"] == "Alta"
    assert body["data"][0]["status"] == "Planeado"
    assert body["data"][0]["start_date"] == "2026-05-01"
    assert body["data"][0]["files_count"] == 1
    assert body["data"][0]["files"][0]["original_name"] == "evidencia.pdf"
    # El segundo evento cae en los defaults del vocabulario cerrado.
    assert body["data"][1]["priority"] == "Media"
    assert body["data"][1]["files_count"] == 0


def test_alta_masiva_sin_archivos_funciona(client, headers, uploads_root):
    resp = client.post(
        BASE, headers=headers,
        data={"payload": json.dumps([{"title": "Solo datos", "area_id": ""}])},
    )
    assert resp.status_code == 201
    assert resp.json()["data"][0]["area_id"] is None


def test_alta_masiva_con_json_invalido_responde_400(client, headers):
    resp = client.post(BASE, headers=headers, data={"payload": "{no es json"})
    assert resp.status_code == 400
    assert "JSON" in resp.json()["error"]


def test_alta_masiva_con_titulo_vacio_responde_422(client, headers):
    resp = client.post(BASE, headers=headers, data={"payload": json.dumps([{"title": "   "}])})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_alta_masiva_exige_file_indexes_con_varios_eventos(client, headers, uploads_root):
    payload = json.dumps([{"title": "Uno"}, {"title": "Dos"}])
    resp = client.post(
        BASE, headers=headers, data={"payload": payload},
        files=[("files", ("a.pdf", BytesIO(b"x"), "application/pdf"))],
    )
    assert resp.status_code == 400
    assert "file_indexes" in resp.json()["error"]


def test_alta_masiva_rechaza_extension_no_permitida(client, headers, uploads_root, db_session):
    antes = db_session.query(AdhocProgramEvent).count()
    resp = client.post(
        BASE, headers=headers,
        data={"payload": json.dumps([{"title": "Malicioso"}])},
        files=[("files", ("shell.php", BytesIO(b"<?php"), "application/x-php"))],
    )
    assert resp.status_code == 400
    assert "php" in resp.json()["error"].lower()
    assert db_session.query(AdhocProgramEvent).count() == antes


# --------------------------------------------------------------------------
# GET / PATCH / DELETE de un evento
# --------------------------------------------------------------------------

def test_detalle_de_evento_inexistente_responde_404(client, headers):
    resp = client.get(BASE + "/99999999", headers=headers)
    assert resp.status_code == 404
    assert isinstance(resp.json()["error"], str), "detail debe ser STRING, no dict"


def test_detalle_incluye_los_adjuntos(client, headers, db_session, uploads_root):
    from itcj2.apps.adhoc.services import program_event_service as svc

    event = _make_event(db_session, title="Con adjuntos")
    svc.add_files(db_session, event.id, [_upload("plan.pdf")], uploaded_by_id=None)

    body = client.get(BASE + "/" + str(event.id), headers=headers).json()

    assert body["data"]["files_count"] == 1
    assert body["data"]["files"][0]["original_name"] == "plan.pdf"


def test_patch_actualiza_solo_lo_enviado(client, headers, db_session):
    event = _make_event(db_session, title="Original", location="Aula Magna")

    body = client.patch(
        BASE + "/" + str(event.id), headers=headers, json={"title": "Renombrado"}
    ).json()

    assert body["data"]["title"] == "Renombrado"
    assert body["data"]["location"] == "Aula Magna"


def test_patch_rechaza_status_fuera_del_vocabulario(client, headers, db_session):
    event = _make_event(db_session)
    resp = client.patch(BASE + "/" + str(event.id), headers=headers, json={"status": "Inventado"})
    assert resp.status_code == 422


def test_patch_de_evento_inexistente_responde_404(client, headers):
    resp = client.patch(BASE + "/99999999", headers=headers, json={"title": "X"})
    assert resp.status_code == 404


def test_delete_borra_el_evento(client, headers, db_session):
    event = _make_event(db_session)
    event_id = event.id

    resp = client.delete(BASE + "/" + str(event_id), headers=headers)

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert db_session.get(AdhocProgramEvent, event_id) is None


def test_delete_de_evento_inexistente_responde_404(client, headers):
    """El legacy devolvía un redirect 'exitoso' al borrar algo que no existe."""
    resp = client.delete(BASE + "/99999999", headers=headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# duplicate
# --------------------------------------------------------------------------

def test_duplicate_genera_folios_distintos(client, headers, db_session):
    event = _make_event(db_session, title="Auditoria", folio="API-001", location="Sala 1")

    copia1 = client.post(BASE + "/" + str(event.id) + "/duplicate", headers=headers)
    copia2 = client.post(BASE + "/" + str(event.id) + "/duplicate", headers=headers)

    assert copia1.status_code == 201
    assert copia1.json()["data"]["folio"] == "API-001-COPY"
    assert copia2.json()["data"]["folio"] != copia1.json()["data"]["folio"]
    assert copia1.json()["data"]["location"] == "Sala 1"
    assert copia1.json()["data"]["status"] == "Planeado"


def test_duplicate_de_evento_inexistente_responde_404(client, headers):
    resp = client.post(BASE + "/99999999/duplicate", headers=headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# Adjuntos
# --------------------------------------------------------------------------

def _upload(filename, content=b"contenido", content_type="application/pdf"):
    class _U:
        def __init__(self):
            self.filename = filename
            self.content_type = content_type
            self.file = BytesIO(content)
    return _U()


def test_subir_y_listar_adjuntos(client, headers, db_session, uploads_root):
    event = _make_event(db_session)

    subida = client.post(
        BASE + "/" + str(event.id) + "/files", headers=headers,
        files=[
            ("files", ("plan.pdf", BytesIO(b"uno"), "application/pdf")),
            ("files", ("acta.txt", BytesIO(b"dos"), "text/plain")),
        ],
    )
    assert subida.status_code == 201
    assert subida.json()["total"] == 2

    listado = client.get(BASE + "/" + str(event.id) + "/files", headers=headers).json()
    assert listado["total"] == 2
    assert {f["original_name"] for f in listado["data"]} == {"plan.pdf", "acta.txt"}


def test_listar_adjuntos_de_evento_inexistente_responde_404(client, headers):
    resp = client.get(BASE + "/99999999/files", headers=headers)
    assert resp.status_code == 404


def test_subir_adjunto_a_evento_inexistente_responde_404(client, headers, uploads_root):
    resp = client.post(
        BASE + "/99999999/files", headers=headers,
        files=[("files", ("plan.pdf", BytesIO(b"x"), "application/pdf"))],
    )
    assert resp.status_code == 404


def test_descargar_adjunto_por_id_devuelve_el_binario(client, headers, db_session, uploads_root):
    from itcj2.apps.adhoc.services import program_event_service as svc

    event = _make_event(db_session)
    # Nombre con espacio y acento: el legacy lo rompía al armar la URL cruda.
    row = svc.add_files(db_session, event.id, [_upload("acta de revisión.pdf", b"binario")],
                        uploaded_by_id=None)[0]

    resp = client.get(BASE + "/files/" + str(row.id) + "/download", headers=headers)

    assert resp.status_code == 200
    assert resp.content == b"binario"
    assert "attachment" in resp.headers["content-disposition"]


def test_descargar_adjunto_inexistente_responde_404(client, headers):
    resp = client.get(BASE + "/files/99999999/download", headers=headers)
    assert resp.status_code == 404


def test_borrar_adjunto_por_id(client, headers, db_session, uploads_root):
    from itcj2.apps.adhoc.services import program_event_service as svc

    event = _make_event(db_session)
    row = svc.add_files(db_session, event.id, [_upload("plan.pdf")], uploaded_by_id=None)[0]
    file_id = row.id

    resp = client.delete(BASE + "/files/" + str(file_id), headers=headers)

    assert resp.status_code == 200
    assert db_session.get(AdhocProgramEventFile, file_id) is None


def test_borrar_adjunto_inexistente_responde_404(client, headers):
    resp = client.delete(BASE + "/files/99999999", headers=headers)
    assert resp.status_code == 404

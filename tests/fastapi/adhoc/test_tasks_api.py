"""Tests HTTP de ``/api/adhoc/v2/tasks`` (``itcj2.apps.adhoc.api.tasks``).

Dos cosas que conviene tener claras antes de tocar este archivo:

* **El router viene del cableado real.** ``itcj2/apps/adhoc/router.py`` ya monta
  ``tasks`` en ``/api/adhoc/v2/tasks``, así que la fixture ``tasks_client`` usa
  la app de ``create_app()`` tal cual (con su ``JWTMiddleware`` y su handler
  global de ``HTTPException``) y no vuelve a montar nada: si el prefijo del
  cableado cambiara, estos tests deben romperse.
* **El error del cliente es ``{"error": ..., "status": ...}``**, no
  ``{"detail": ...}``: lo envuelve el handler global de ``itcj2/main.py``.

Sobre los 403: un JWT con ``role="admin"`` **bypasea ``require_perms``**, así
que el camino feliz con un admin no prueba nada sobre los permisos. Para eso
está ``staff_headers`` + el parche de ``cached_has_assignment`` / ``cached_perms``
(hay que parchear ``itcj2.dependencies``, que es donde se importan).
"""
import shutil
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from itcj2.database import get_db
from tests.conftest import make_jwt
from tests.fastapi.adhoc._tasks_helpers import (
    add_comment,
    add_comment_file,
    assignee_flag,
    make_document,
    make_flow,
    make_incident,
    make_program_event,
    make_task,
    make_user,
)

PREFIX = "/api/adhoc/v2/tasks"


@pytest.fixture()
def tasks_client(app_client, db_session):
    """App real (router ya cableado) + ``get_db`` atado a la sesión del test."""

    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


def headers_for(user, role: str = "admin") -> dict:
    return {"Cookie": f"itcj_token={make_jwt(user_id=user.id, role=role)}"}


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile``, para escribir un binario real en
    disco sin pasar por el endpoint multipart (que solo sube UN archivo por
    comentario, columna vieja)."""

    def __init__(self, filename, content=b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


# ==========================================================================
# Autenticación y autorización
# ==========================================================================

@pytest.mark.parametrize("method,path", [
    ("get", f"{PREFIX}/mine"),
    ("get", f"{PREFIX}?parent_type=incident&parent_id=1"),
    ("post", PREFIX),
    ("patch", f"{PREFIX}/1"),
    ("delete", f"{PREFIX}/1"),
    ("put", f"{PREFIX}/1/assignees"),
    ("put", f"{PREFIX}/1/overdue-notifications"),
    ("get", f"{PREFIX}/1/workflow"),
    ("post", f"{PREFIX}/1/workflow-action"),
    ("post", f"{PREFIX}/1/comments"),
    ("get", f"{PREFIX}/comments/1/download"),
    ("get", f"{PREFIX}/comments/files/1/download"),
])
def test_sin_cookie_es_401(tasks_client, method, path):
    resp = getattr(tasks_client, method)(path)

    assert resp.status_code == 401
    assert resp.json()["error"]


def test_sin_permiso_es_403(tasks_client, db_session):
    """``role='staff'`` no bypasea: hace falta el permiso real en la app."""
    u = make_user(db_session)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms", return_value={"adhoc.otro.permiso"}):
        resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u, role="staff"))

    assert resp.status_code == 403
    assert "adhoc.tasks.api.read.own" in resp.json()["error"]


def test_con_permiso_exacto_pasa(tasks_client, db_session):
    u = make_user(db_session)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u, role="staff"))

    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_sin_acceso_a_la_app_es_403(tasks_client, db_session):
    u = make_user(db_session)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=False):
        resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u, role="staff"))

    assert resp.status_code == 403


# ==========================================================================
# Lectura
# ==========================================================================

def test_get_mine_devuelve_el_tablero(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u], description="Mía")
    otro = make_user(db_session, "OTRO")
    make_task(db_session, incident=inc, assignees=[otro], description="Ajena")

    resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u))

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["total"] == 1
    fila = body["data"][0]
    assert fila["id"] == t.id
    assert fila["parent"]["type"] == "incident"
    assert fila["assignees"][0]["id"] == u.id


def test_get_por_padre(tasks_client, db_session):
    u = make_user(db_session)
    ev = make_program_event(db_session)
    t = make_task(db_session, program=ev)

    resp = tasks_client.get(
        f"{PREFIX}?parent_type=program&parent_id={ev.id}", headers=headers_for(u)
    )

    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()["data"]] == [t.id]


def test_get_por_padre_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.get(
        f"{PREFIX}?parent_type=incident&parent_id=987654321", headers=headers_for(u)
    )

    assert resp.status_code == 404
    assert isinstance(resp.json()["error"], str)


def test_get_por_padre_con_tipo_invalido_es_400(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.get(
        f"{PREFIX}?parent_type=marciano&parent_id=1", headers=headers_for(u)
    )

    assert resp.status_code == 400


def test_get_workflow(tasks_client, db_session):
    val = make_user(db_session, "VAL")
    autor = make_user(db_session, "AUTOR")
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[val])
    add_comment(db_session, t, val, "ok")

    resp = tasks_client.get(f"{PREFIX}/{t.id}/workflow", headers=headers_for(val))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task"]["id"] == t.id
    assert data["parent"]["step_name"] == steps[0].name
    assert len(data["comments"]) == 1
    assert data["approvals"] == []


def test_get_workflow_con_read_own_y_asignado_pasa(tasks_client, db_session):
    """``consult`` (solo ``read.own``) sí puede ver el detalle de SU tarea."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        resp = tasks_client.get(f"{PREFIX}/{t.id}/workflow", headers=headers_for(u, role="staff"))

    assert resp.status_code == 200


def test_get_workflow_sin_read_all_ni_relacion_es_403(tasks_client, db_session):
    """D4: con solo ``read.own``, un ajeno a la tarea (ni asignado ni
    responsable del padre) no puede leer su detalle."""
    ajeno = make_user(db_session, "AJENO")
    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        resp = tasks_client.get(f"{PREFIX}/{t.id}/workflow",
                                headers=headers_for(ajeno, role="staff"))

    assert resp.status_code == 403


# ==========================================================================
# Alta, parche y borrado
# ==========================================================================

def test_post_bulk_crea_las_tareas(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)

    resp = tasks_client.post(PREFIX, headers=headers_for(u), json={
        "parent_type": "incident",
        "parent_id": inc.id,
        "tasks": [
            {"description": "Una", "due_date": "2026-10-01", "responsible_ids": [u.id]},
            {"description": "Otra"},
        ],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["data"][0]["incident_id"] == inc.id
    assert body["data"][0]["assignees"][0]["id"] == u.id
    assert body["data"][0]["created_by_id"] == u.id


def test_post_bulk_con_select_vacio_usa_los_defaults(tasks_client, db_session):
    """El ``value=""`` del placeholder no debe llegar a un CheckConstraint."""
    u = make_user(db_session)
    inc = make_incident(db_session)

    resp = tasks_client.post(PREFIX, headers=headers_for(u), json={
        "parent_type": "incident",
        "parent_id": inc.id,
        "tasks": [{"description": "Con vacíos", "priority": "", "status": "",
                   "start_date": "", "due_date": "", "responsible_ids": ["", None]}],
    })

    assert resp.status_code == 200
    fila = resp.json()["data"][0]
    assert fila["priority"] == "Media"
    assert fila["status"] == "Pendiente"
    assert fila["start_date"] is None
    assert fila["assignees"] == []


def test_post_bulk_padre_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.post(PREFIX, headers=headers_for(u), json={
        "parent_type": "incident", "parent_id": 987654321,
        "tasks": [{"description": "x"}],
    })

    assert resp.status_code == 404


def test_post_bulk_sin_tareas_es_422(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)

    resp = tasks_client.post(PREFIX, headers=headers_for(u), json={
        "parent_type": "incident", "parent_id": inc.id, "tasks": [],
    })

    assert resp.status_code == 422


def test_patch_actualiza(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    resp = tasks_client.patch(f"{PREFIX}/{t.id}", headers=headers_for(u),
                              json={"status": "Completada"})

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "Completada"
    assert resp.json()["data"]["completed_at"] is not None


def test_patch_sin_campos_es_400(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    resp = tasks_client.patch(f"{PREFIX}/{t.id}", headers=headers_for(u), json={})

    assert resp.status_code == 400


def test_patch_con_estatus_fuera_del_vocabulario_es_422(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    resp = tasks_client.patch(f"{PREFIX}/{t.id}", headers=headers_for(u),
                              json={"status": "Inventado"})

    assert resp.status_code == 422


def test_patch_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.patch(f"{PREFIX}/987654321", headers=headers_for(u),
                              json={"status": "En Proceso"})

    assert resp.status_code == 404


def test_delete(tasks_client, db_session):
    from itcj2.apps.adhoc.models import AdhocTask

    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    tid = t.id

    resp = tasks_client.delete(f"{PREFIX}/{tid}", headers=headers_for(u))

    assert resp.status_code == 200
    assert resp.json()["message"]
    assert db_session.get(AdhocTask, tid) is None


def test_delete_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.delete(f"{PREFIX}/987654321", headers=headers_for(u))

    assert resp.status_code == 404


# ==========================================================================
# Asignación
# ==========================================================================

def test_put_assignees(tasks_client, db_session):
    actor = make_user(db_session, "ACTOR")
    a, b = make_user(db_session, "A"), make_user(db_session, "B")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[a])

    resp = tasks_client.put(f"{PREFIX}/{t.id}/assignees", headers=headers_for(actor),
                            json={"user_ids": [b.id]})

    assert resp.status_code == 200
    assert [x["id"] for x in resp.json()["data"]["assignees"]] == [b.id]


def test_put_overdue_notifications_escala_a_urgente(tasks_client, db_session):
    """Efecto de negocio conservado del legacy (``api_tasks.py:219``)."""
    actor = make_user(db_session, "ACTOR")
    a = make_user(db_session, "A")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[a], priority="Baja")

    resp = tasks_client.put(f"{PREFIX}/{t.id}/overdue-notifications",
                            headers=headers_for(actor), json={"user_ids": [a.id]})

    assert resp.status_code == 200
    assert resp.json()["data"]["priority"] == "Urgente"
    assert assignee_flag(db_session, t.id, a.id) is True


# ==========================================================================
# Workflow
# ==========================================================================

def test_workflow_action_actor_no_asignado_es_403(tasks_client, db_session):
    """Ni siquiera un admin global puede aprobar una tarea que no es suya."""
    asignado = make_user(db_session, "ASIGNADO")
    intruso = make_user(db_session, "INTRUSO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])
    add_comment(db_session, t, asignado)

    resp = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                             headers=headers_for(intruso), json={"accion": "aprobar"})

    assert resp.status_code == 403


def test_workflow_action_sin_comentario_es_400(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    resp = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                             headers=headers_for(u), json={"accion": "aprobar"})

    assert resp.status_code == 400
    assert "comentario" in resp.json()["error"].lower()


def test_workflow_action_invalida_es_400(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    resp = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                             headers=headers_for(u), json={"accion": "explotar"})

    assert resp.status_code == 400


def test_workflow_action_aprueba_y_cierra_la_incidencia(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    resp = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                             headers=headers_for(u), json={"accion": "aprobar"})

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    db_session.refresh(inc)
    assert inc.status == "Cerrada"


def test_workflow_action_multivalidador_espera_al_segundo(tasks_client, db_session):
    v1, v2 = make_user(db_session, "V1"), make_user(db_session, "V2")
    autor = make_user(db_session, "AUTOR")
    flow, steps = make_flow(db_session, steps=("Único",))
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[v1, v2])
    add_comment(db_session, t, v1)

    r1 = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                           headers=headers_for(v1), json={"accion": "aprobar"})
    assert r1.status_code == 200
    assert "Esperando" in r1.json()["message"]
    db_session.refresh(doc)
    assert doc.status == "En Revisión"

    r2 = tasks_client.post(f"{PREFIX}/{t.id}/workflow-action",
                           headers=headers_for(v2), json={"accion": "aprobar"})
    assert r2.status_code == 200
    db_session.refresh(doc)
    assert doc.status == "Aprobado"


# ==========================================================================
# Comentarios y descargas
# ==========================================================================

def test_post_comment(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    resp = tasks_client.post(f"{PREFIX}/{t.id}/comments", headers=headers_for(u),
                             data={"comment": "Avance registrado"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["comment"] == "Avance registrado"
    assert data["user"]["id"] == u.id
    assert data["file_path"] is None


def test_post_comment_vacio_es_400(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    resp = tasks_client.post(f"{PREFIX}/{t.id}/comments", headers=headers_for(u),
                             data={"comment": "   "})

    assert resp.status_code == 400


def test_post_comment_en_tarea_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.post(f"{PREFIX}/987654321/comments", headers=headers_for(u),
                             data={"comment": "hola"})

    assert resp.status_code == 404


def test_post_comment_con_extension_prohibida_es_400(tasks_client, db_session):
    """Whitelist de extensiones: el legacy aceptaba ``.php`` sin parpadear."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    resp = tasks_client.post(
        f"{PREFIX}/{t.id}/comments", headers=headers_for(u),
        data={"comment": "adjunto"},
        files={"file": ("shell.php", b"<?php ?>", "application/x-php")},
    )

    assert resp.status_code == 400


def test_comment_con_adjunto_se_sube_y_se_descarga(tasks_client, db_session):
    from itcj2.apps.adhoc.services.upload_service import resolve_dir

    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    directorio: Path | None = None

    try:
        subida = tasks_client.post(
            f"{PREFIX}/{t.id}/comments", headers=headers_for(u),
            data={"comment": "con evidencia"},
            files={"file": ("evidencia.txt", b"contenido de prueba", "text/plain")},
        )
        assert subida.status_code == 200
        comment_id = subida.json()["data"]["id"]
        assert subida.json()["data"]["file_path"].startswith(f"{t.id}/")
        directorio = resolve_dir("task_comments", t.id)

        descarga = tasks_client.get(f"{PREFIX}/comments/{comment_id}/download",
                                    headers=headers_for(u))
        assert descarga.status_code == 200
        assert descarga.content == b"contenido de prueba"
    finally:
        if directorio is not None and directorio.exists():
            shutil.rmtree(directorio, ignore_errors=True)


def test_download_sin_adjunto_es_404(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)

    resp = tasks_client.get(f"{PREFIX}/comments/{c.id}/download", headers=headers_for(u))

    assert resp.status_code == 404


def test_download_con_ruta_envenenada_es_404(tasks_client, db_session):
    """Path traversal desde una fila de BD: ``safe_join`` lo corta."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u, file_path="../../../../etc/passwd")

    resp = tasks_client.get(f"{PREFIX}/comments/{c.id}/download", headers=headers_for(u))

    assert resp.status_code == 404


# ==========================================================================
# Adjuntos de comentario (`adhoc_task_comment_files`) — el bug de los 533
# adjuntos invisibles: el ETL dejó `file_path` en NULL en 1098 filas y puso
# los archivos aquí porque 85 comentarios del legacy tienen más de uno.
# ==========================================================================

def test_comentario_con_varios_adjuntos_se_listan_en_el_workflow(tasks_client, db_session):
    """``GET /tasks/{id}/workflow`` expone ``files`` (0..N) además del
    ``file_path`` heredado — un mismo comentario puede traer ambas cosas."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    c = add_comment(db_session, t, u, file_path="legado/unico.pdf")
    f1 = add_comment_file(db_session, c, original_name="anexo1.pdf", file_path="1/anexo1.pdf")
    f2 = add_comment_file(db_session, c, original_name="anexo2.pdf", file_path=None)

    resp = tasks_client.get(f"{PREFIX}/{t.id}/workflow", headers=headers_for(u))

    assert resp.status_code == 200
    comentario = resp.json()["data"]["comments"][0]
    assert comentario["file_path"] == "legado/unico.pdf"
    assert len(comentario["files"]) == 2
    disponibilidad = {f["id"]: f["is_available"] for f in comentario["files"]}
    assert disponibilidad[f1.id] is True
    assert disponibilidad[f2.id] is False


def test_comentario_con_adjunto_nuevo_se_descarga_por_id_de_archivo(tasks_client, db_session):
    from itcj2.apps.adhoc.services.upload_service import resolve_dir, save_upload

    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    directorio: Path | None = None

    try:
        meta = save_upload(
            "task_comments", t.id,
            _FakeUpload("anexo.txt", content=b"hola mundo", content_type="text/plain"),
        )
        f = add_comment_file(db_session, c, original_name="anexo.txt", file_path=meta["file_path"],
                             mime_type="text/plain")
        directorio = resolve_dir("task_comments", t.id)

        descarga = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download",
                                    headers=headers_for(u))
        assert descarga.status_code == 200
        assert descarga.content == b"hola mundo"
    finally:
        if directorio is not None and directorio.exists():
            shutil.rmtree(directorio, ignore_errors=True)


def test_descarga_de_adjunto_sin_binario_es_404_legible(tasks_client, db_session):
    """Adjunto migrado cuyo binario ya no está en el servidor del proveedor."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    f = add_comment_file(db_session, c, file_path=None)

    resp = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download", headers=headers_for(u))

    assert resp.status_code == 404
    assert resp.json()["error"]


def test_descarga_de_adjunto_inexistente_es_404(tasks_client, db_session):
    u = make_user(db_session)

    resp = tasks_client.get(f"{PREFIX}/comments/files/99999999/download", headers=headers_for(u))

    assert resp.status_code == 404


def test_descarga_de_adjunto_con_ruta_envenenada_es_404(tasks_client, db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    f = add_comment_file(db_session, c, file_path="../../../../etc/passwd")

    resp = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download", headers=headers_for(u))

    assert resp.status_code == 404

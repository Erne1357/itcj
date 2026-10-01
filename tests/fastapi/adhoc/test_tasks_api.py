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


# ==========================================================================
# `thread_readable` — el flag por fila que B3 añadió al listado
#
# La lista de tareas de un expediente pinta el contador de la columna "Notas"
# como botón que abre el hilo, o apagado si el actor no lo alcanza. Quien
# decide es el servidor, con la MISMA función que levanta el 403 de
# `GET /tasks/{id}/workflow` (`puede_leer_hilo`); si las dos frases
# divergieran, la fila ofrecería un botón que el detalle contesta con un error.
# ==========================================================================

def test_get_tasks_emite_thread_readable_en_cada_fila(tasks_client, db_session):
    """Ninguna fila puede llegar sin el flag: sin él el contador se apaga."""
    admin = make_user(db_session, "ADMIN")
    otro = make_user(db_session, "OTRO")
    inc = make_incident(db_session)
    mia = make_task(db_session, incident=inc, description="Mía", assignees=[admin])
    ajena = make_task(db_session, incident=inc, description="Ajena", assignees=[otro])
    sin_nadie = make_task(db_session, incident=inc, description="Sin asignar")

    resp = tasks_client.get(
        f"{PREFIX}?parent_type=incident&parent_id={inc.id}", headers=headers_for(admin)
    )

    assert resp.status_code == 200
    filas = {row["id"]: row for row in resp.json()["data"]}
    assert set(filas) == {mia.id, ajena.id, sin_nadie.id}
    for tid, fila in filas.items():
        assert "thread_readable" in fila, tid
    # El admin global tiene `read.all` por bypass: alcanza los tres hilos.
    assert all(f["thread_readable"] is True for f in filas.values())


def test_el_listado_por_padre_admite_los_dos_alcances(tasks_client, db_session):
    """El listado acepta ``read.own``, y es lo que hace util al flag.

    Mientras solo admitio ``read.all``, la pastilla apagada no la podia ver
    ningun actor real: todo el que lograba cargar la lista tenia alcance
    completo y ``thread_readable`` salia siempre en ``True``. Y el destinatario
    del estado apagado —``consult``, 10 usuarios, con ``adhoc.tasks.page.list``
    y ``read.own``— abria la pagina y recibia 403 en la tabla, o sea que A6
    quedaba cerrado solo para quien ya tenia alcance completo.

    Con los dos alcances (``require_perms`` es OR) la lista se carga entera y la
    que decide fila por fila es ``puede_leer_hilo``: la pastilla queda clicable
    donde el actor participa y apagada en el resto, que es la decision 3 de B3.
    """
    u = make_user(db_session, "CONSULT")
    otro = make_user(db_session, "OTRO")
    inc = make_incident(db_session)
    mia = make_task(db_session, incident=inc, description="Mia", assignees=[u])
    ajena = make_task(db_session, incident=inc, description="Ajena", assignees=[otro])

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True),          patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        resp = tasks_client.get(
            f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
            headers=headers_for(u, role="staff"),
        )

    assert resp.status_code == 200
    filas = {row["id"]: row for row in resp.json()["data"]}
    # Ve el expediente completo: la fila no es contenido del hilo.
    assert set(filas) == {mia.id, ajena.id}
    # Pero el hilo, solo el suyo.
    assert filas[mia.id]["thread_readable"] is True
    assert filas[ajena.id]["thread_readable"] is False


def test_el_listado_por_padre_sigue_exigiendo_uno_de_los_dos(tasks_client, db_session):
    """Abrirlo a ``read.own`` no es abrirlo: sin ninguno de los dos, 403."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    make_task(db_session, incident=inc)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True),          patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.comment"}):
        resp = tasks_client.get(
            f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
            headers=headers_for(u, role="staff"),
        )

    assert resp.status_code == 403
    assert "adhoc.tasks.api.read" in resp.json()["error"]


def test_get_mine_emite_thread_readable_y_el_tablero_nunca_trae_un_hilo_cerrado(
        tasks_client, db_session):
    """Invariante del tablero: toda tarjeta que lista puede abrir su modal.

    ``get_dashboard_tasks`` selecciona por "asignado" o "responsable del
    padre", que son los mismos predicados de :func:`puede_leer_hilo`. Si
    alguien añadiera una quinta rama al tablero sin tocar el predicado, este
    test lo cazaría: el usuario vería una tarjeta que al pulsarla da 403.
    """
    u = make_user(db_session, "YO")
    ejecutor = make_user(db_session, "EJECUTOR")
    inc = make_incident(db_session, "Inc propia", responsible=u)
    ev = make_program_event(db_session, "Evt propio", responsible=u)
    autor = make_user(db_session, "AUTOR")
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])

    # Una tarjeta por cada uno de los 4 predicados del tablero.
    mia = make_task(db_session, incident=inc, status="Pendiente", assignees=[u])
    revisar_inc = make_task(db_session, incident=inc, status="En Revisión",
                            assignees=[ejecutor])
    revisar_ev = make_task(db_session, program=ev, status="En Revisión",
                           assignees=[ejecutor])
    validar = make_task(db_session, document=doc, flow_step=steps[0],
                        status="En Revisión", assignees=[u])

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u, role="staff"))

    assert resp.status_code == 200
    filas = resp.json()["data"]
    assert {f["id"] for f in filas} == {mia.id, revisar_inc.id, revisar_ev.id, validar.id}
    assert all(f["thread_readable"] is True for f in filas), filas


def test_el_flag_y_el_403_del_detalle_coinciden_sobre_http(tasks_client, db_session):
    """La coherencia de B3, extremo a extremo y por los dos caminos.

    Misma tarea ajena, dos actores con distinto alcance, y las dos mitades
    —listado y detalle— viajando por HTTP de verdad:

    * con ``read.all`` (aqui por el bypass de admin global) el listado la trae
      con ``thread_readable=True`` **y** el detalle responde 200;
    * con solo ``read.own`` el listado la trae con ``thread_readable=False``
      **y** el detalle responde 403.

    Es la invariante que ninguna de las dos mitades puede romper sola: si
    divergieran, la fila ofreceria un boton que el servidor contesta con un
    error, o apagaria un hilo que si se puede leer. El segundo camino solo se
    puede recorrer entero desde que el listado admite ``read.own``; antes habia
    que llamar al serializador a mano porque ``GET /tasks`` contestaba 403.
    """
    admin = make_user(db_session, "ADMIN")
    ajeno = make_user(db_session, "AJENO")
    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session)
    ajena = make_task(db_session, incident=inc, assignees=[asignado])

    # --- camino "si": read.all -> flag True y detalle 200 -------------------
    listado = tasks_client.get(
        f"{PREFIX}?parent_type=incident&parent_id={inc.id}", headers=headers_for(admin)
    )
    fila = next(f for f in listado.json()["data"] if f["id"] == ajena.id)
    detalle = tasks_client.get(f"{PREFIX}/{ajena.id}/workflow", headers=headers_for(admin))

    assert fila["thread_readable"] is True
    assert detalle.status_code == 200

    # --- camino "no": solo read.own -> flag False y detalle 403 -------------
    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True),          patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        listado_ajeno = tasks_client.get(
            f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
            headers=headers_for(ajeno, role="staff"),
        )
        cerrado = tasks_client.get(f"{PREFIX}/{ajena.id}/workflow",
                                   headers=headers_for(ajeno, role="staff"))

    fila_ajena = next(f for f in listado_ajeno.json()["data"] if f["id"] == ajena.id)
    assert fila_ajena["thread_readable"] is False
    assert cerrado.status_code == 403


def test_actor_context_solo_da_read_all_a_quien_lo_tiene(tasks_client, db_session):
    """El contexto del actor es UN camino: si diverge, divergen flag y 403.

    Tres orígenes posibles del alcance completo y solo dos lo conceden: el
    permiso explícito y el bypass del admin global.
    """
    from itcj2.apps.adhoc.api.tasks import _actor_context

    u = make_user(db_session)

    with patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.all"}):
        assert _actor_context(db_session, {"sub": str(u.id), "role": "staff"}) == (u.id, True)

    with patch("itcj2.core.services.authz_cache.cached_perms",
               return_value={"adhoc.tasks.api.read.own"}):
        assert _actor_context(db_session, {"sub": str(u.id), "role": "staff"}) == (u.id, False)
        # El admin global no paga siquiera la consulta de permisos.
        assert _actor_context(db_session, {"sub": str(u.id), "role": "admin"}) == (u.id, True)


# ==========================================================================
# Las CUATRO puertas del hilo
#
# El hilo de una tarea se alcanza por cuatro rutas: el detalle, los dos
# adjuntos y el alta de comentario. Hasta la auditoria de B3 solo la primera
# preguntaba por la pertenencia; las otras tres se conformaban con
# `adhoc.tasks.api.comment`, que el rol `consult` tiene. El mismo actor recibia
# 403 en el hilo y 200 en su contenido, y con 533 adjuntos de ids correlativos
# desde 1 enumerar bajaba el expediente entero del SGC.
#
# Ahora las cuatro pasan por `_exigir_acceso_al_hilo` -> `puede_leer_hilo`.
# ==========================================================================

def _consult():
    """Los permisos reales del rol `consult`: comenta y lee, pero sin `read.all`."""
    return patch(
        "itcj2.core.services.authz_cache.cached_perms",
        return_value={"adhoc.tasks.api.read.own", "adhoc.tasks.api.comment",
                      "adhoc.tasks.api.workflow"},
    )


def test_el_adjunto_heredado_exige_pertenencia_al_hilo(tasks_client, db_session):
    """`GET /tasks/comments/{id}/download` sobre una tarea ajena: 403.

    El permiso dice "puedes ver adjuntos de comentarios"; la pertenencia dice
    "puedes ver los de ESTE". Sin lo segundo, tener `adhoc.tasks.api.comment`
    bastaba para bajarse el adjunto de cualquier comentario del sistema.
    """
    autor = make_user(db_session, "AUTOR")
    ajeno = make_user(db_session, "AJENO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[autor])
    c = add_comment(db_session, t, autor, file_path=f"{t.id}/evidencia.txt")

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         _consult():
        resp = tasks_client.get(f"{PREFIX}/comments/{c.id}/download",
                                headers=headers_for(ajeno, role="staff"))

    assert resp.status_code == 403


def test_el_adjunto_por_file_id_exige_pertenencia_al_hilo(tasks_client, db_session):
    """Igual sobre `adhoc_task_comment_files`, que es la tabla enumerable.

    533 filas, ids correlativos desde 1 y una ruta que solo pedia un permiso
    que tienen los 10 usuarios del rol `consult`.
    """
    autor = make_user(db_session, "AUTOR")
    ajeno = make_user(db_session, "AJENO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[autor])
    c = add_comment(db_session, t, autor)
    f = add_comment_file(db_session, c, file_path=f"{t.id}/anexo.pdf")

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         _consult():
        resp = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download",
                                headers=headers_for(ajeno, role="staff"))

    assert resp.status_code == 403


def test_el_403_del_adjunto_va_antes_que_el_404_de_no_hay_binario(tasks_client, db_session):
    """El orden importa: primero autorizar, luego mirar si hay archivo.

    Al reves, el 404 de "este comentario no tiene adjunto" le contaria a un
    extranno que comentarios del expediente llevan archivo y cuales no.
    """
    autor = make_user(db_session, "AUTOR")
    ajeno = make_user(db_session, "AJENO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[autor])
    sin_binario = add_comment(db_session, t, autor)          # file_path NULL
    f = add_comment_file(db_session, sin_binario, file_path=None)

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         _consult():
        heredado = tasks_client.get(f"{PREFIX}/comments/{sin_binario.id}/download",
                                    headers=headers_for(ajeno, role="staff"))
        por_id = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download",
                                  headers=headers_for(ajeno, role="staff"))

    assert heredado.status_code == 403
    assert por_id.status_code == 403


def test_comentar_una_tarea_ajena_es_403_y_no_escribe_nada(tasks_client, db_session):
    """Escribir en el hilo no puede ser mas facil que leerlo.

    `consult` tiene `adhoc.tasks.api.comment`, asi que sin gate de pertenencia
    podia inyectar comentarios en el expediente de cualquier no conformidad del
    SGC —y disparar la notificacion a sus asignados—.
    """
    from itcj2.apps.adhoc.models import AdhocTaskComment

    autor = make_user(db_session, "AUTOR")
    ajeno = make_user(db_session, "AJENO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[autor])

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         _consult():
        resp = tasks_client.post(f"{PREFIX}/{t.id}/comments",
                                 headers=headers_for(ajeno, role="staff"),
                                 data={"comment": "sonda"})

    assert resp.status_code == 403
    assert db_session.query(AdhocTaskComment).filter_by(task_id=t.id).count() == 0


def test_el_responsable_del_padre_alcanza_las_cuatro_puertas(tasks_client, db_session):
    """El otro lado del gate: quien SI participa entra por las cuatro.

    Y participa sin estar asignado — es el responsable de la incidencia, la
    tercera rama de `puede_leer_hilo`. Si el gate se hubiera escrito a mano en
    cada ruta en vez de reusar el predicado, este es el caso que se habria
    caido en alguna de ellas.
    """
    ejecutor = make_user(db_session, "EJECUTOR")
    jefe = make_user(db_session, "JEFE")
    inc = make_incident(db_session, "Inc con jefe", responsible=jefe)
    t = make_task(db_session, incident=inc, assignees=[ejecutor])
    c = add_comment(db_session, t, ejecutor, file_path="ruta/inexistente.pdf")
    f = add_comment_file(db_session, c, file_path="ruta/inexistente.pdf")

    with patch("itcj2.core.services.authz_cache.cached_has_assignment", return_value=True), \
         _consult():
        h = headers_for(jefe, role="staff")
        detalle = tasks_client.get(f"{PREFIX}/{t.id}/workflow", headers=h)
        heredado = tasks_client.get(f"{PREFIX}/comments/{c.id}/download", headers=h)
        por_id = tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download", headers=h)
        nuevo = tasks_client.post(f"{PREFIX}/{t.id}/comments", headers=h,
                                  data={"comment": "revisado"})

    assert detalle.status_code == 200
    assert nuevo.status_code == 200
    # Los dos adjuntos pasan el gate y mueren despues, en `safe_join`: lo que
    # se prueba aqui es que NINGUNO contesta 403.
    assert heredado.status_code == 404
    assert por_id.status_code == 404


def test_las_cuatro_puertas_del_hilo_dan_el_mismo_veredicto(tasks_client, db_session):
    """La invariante, escrita como tal: mismo actor, misma tarea, mismo si/no.

    Es la leccion de B1 y B2 llevada a su forma final. Una regla escrita cuatro
    veces diverge; escrita una y consultada cuatro, no puede. Este test es el
    que se rompe si alguien anade una quinta puerta al hilo y se olvida del
    gate.
    """
    autor = make_user(db_session, "AUTOR")
    ajeno = make_user(db_session, "AJENO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[autor])
    c = add_comment(db_session, t, autor, file_path="ruta/inexistente.pdf")
    f = add_comment_file(db_session, c, file_path="ruta/inexistente.pdf")

    def veredictos(usuario):
        with patch("itcj2.core.services.authz_cache.cached_has_assignment",
                   return_value=True), _consult():
            h = headers_for(usuario, role="staff")
            return {
                "workflow": tasks_client.get(f"{PREFIX}/{t.id}/workflow",
                                             headers=h).status_code == 403,
                "heredado": tasks_client.get(f"{PREFIX}/comments/{c.id}/download",
                                             headers=h).status_code == 403,
                "por_id": tasks_client.get(f"{PREFIX}/comments/files/{f.id}/download",
                                           headers=h).status_code == 403,
                "comentar": tasks_client.post(f"{PREFIX}/{t.id}/comments", headers=h,
                                              data={"comment": "x"}).status_code == 403,
            }

    del_ajeno = veredictos(ajeno)
    del_autor = veredictos(autor)

    assert set(del_ajeno.values()) == {True}, del_ajeno
    assert set(del_autor.values()) == {False}, del_autor


# ==========================================================================
# `flow_step` y `assignees_without_access` — lo que B4 añadió al listado
#
# El flujo documental se rompía por la mitad: `parent_type='document'` lo
# soportaban la API y el service, pero la pantalla que lo pinta no existía, así
# que las tareas de aprobación de un documento solo asomaban en el tablero
# personal de cada validador. Nadie —ni un supervisor documental ni un admin—
# veía el avance por pasos ni podía destrabar un paso cuyos asignados ya no
# entran a Calidad.
#
# Las dos claves que hacen posible esa pantalla salen de aquí:
#
# * `flow_step` — el paso del que nació la tarea, con su `step_order`. Es lo que
#   convierte la lista en un avance por pasos: sin el orden, "Autorización" no
#   dice si va antes o después de "Revisión y liberación", y esos nombres los
#   escribe a mano quien define el flujo.
# * `assignees_without_access` — los asignados que NO pueden entrar a la app.
#   El conjunto lo calcula el SERVIDOR una vez por petición (`_app_user_ids` →
#   `users_with_assignment_select`, el mismo criterio que llena el desplegable
#   de `/adhoc/asignaciones`) y viaja en el payload; el JS no vuelve a decidir
#   quién tiene acceso. Si el aviso y el desplegable divergieran, la pantalla
#   marcaría a alguien que el picker sí ofrece —o se callaría sobre alguien a
#   quien no ofrece— y el supervisor no tendría con qué arreglar lo que se le
#   está señalando.
# ==========================================================================

def _con_acceso(*users):
    """Parchea el conjunto de usuarios que pueden ENTRAR a Calidad.

    Se parchea el **módulo fuente** (``authz_service``) porque ``_app_user_ids``
    importa la función dentro del cuerpo. Devolver una lista de ids en vez del
    ``SELECT`` real basta: el endpoint la mete en un ``User.id.in_(...)``.
    """
    return patch(
        "itcj2.core.services.authz_service.users_with_assignment_select",
        return_value=[u.id for u in users],
    )


def _documento_con_dos_pasos(db):
    """Documento con flujo de dos pasos, la forma que deja ``start_flow``."""
    autor = make_user(db, "AUTOR")
    flow, steps = make_flow(db)
    doc = make_document(db, author=autor, flow=flow, current_step=steps[0])
    return doc, steps


def test_flow_step_sale_poblado_en_una_tarea_de_documento(tasks_client, db_session):
    """El paso viaja entero —id, nombre y orden—, no solo su id.

    ``flow_step_id`` ya estaba, pero un número no se puede pintar en una
    columna: obligaría al JS a pedir el flujo aparte para traducirlo, o a la
    pantalla a enseñar "9" donde el usuario espera "Revisión y liberación".
    """
    doc, steps = _documento_con_dos_pasos(db_session)
    val = make_user(db_session, "VALIDADOR")
    primera = make_task(db_session, document=doc, flow_step=steps[0],
                        status="En Revisión", assignees=[val])
    segunda = make_task(db_session, document=doc, flow_step=steps[1],
                        status="En Espera", assignees=[val])

    with _con_acceso(val):
        resp = tasks_client.get(
            f"{PREFIX}?parent_type=document&parent_id={doc.id}",
            headers=headers_for(val),
        )

    assert resp.status_code == 200
    filas = {row["id"]: row for row in resp.json()["data"]}
    assert filas[primera.id]["flow_step"] == {
        "id": steps[0].id, "name": steps[0].name, "step_order": 1,
    }
    assert filas[segunda.id]["flow_step"] == {
        "id": steps[1].id, "name": steps[1].name, "step_order": 2,
    }
    # La clave nueva no sustituye a la vieja: el id sigue viajando.
    assert filas[primera.id]["flow_step_id"] == steps[0].id


def test_flow_step_es_none_en_las_otras_dos_formas_de_padre(tasks_client, db_session):
    """Se emite SIEMPRE, también como ``None`` — las tres formas de padre.

    Una clave que a veces está y a veces no obligaría al JS a comprobar dos
    cosas (que exista y que valga algo) para pintar una celda que, sin flujo
    detrás, simplemente va vacía. Solo las tareas de documento cuelgan de un
    paso: las de incidencia y las de evento de programa no nacen de un flujo.
    """
    u = make_user(db_session)
    inc = make_incident(db_session)
    ev = make_program_event(db_session)
    de_incidencia = make_task(db_session, incident=inc)
    de_programa = make_task(db_session, program=ev)

    with _con_acceso(u):
        una = tasks_client.get(f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
                               headers=headers_for(u))
        otra = tasks_client.get(f"{PREFIX}?parent_type=program&parent_id={ev.id}",
                                headers=headers_for(u))

    for resp, tid in ((una, de_incidencia.id), (otra, de_programa.id)):
        fila = next(f for f in resp.json()["data"] if f["id"] == tid)
        assert "flow_step" in fila, fila
        assert fila["flow_step"] is None
        assert fila["flow_step_id"] is None


def test_sin_asignados_sin_acceso_la_lista_va_vacia(tasks_client, db_session):
    """Todos los asignados pueden entrar: la lista sale vacía, no ausente.

    Vacía es una afirmación —"lo comprobé y no falta nadie"— que aquí sí se
    sostiene, porque el conjunto se calculó. La UI no pinta nada.
    """
    u = make_user(db_session, "CON")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    with _con_acceso(u):
        resp = tasks_client.get(f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
                                headers=headers_for(u))

    fila = next(f for f in resp.json()["data"] if f["id"] == t.id)
    assert fila["assignees_without_access"] == []


def test_la_tarea_atascada_marca_a_todos_sus_asignados(tasks_client, db_session):
    """El caso vivo: la tarea 683 del documento 202 en la base real.

    Un único responsable, y ese responsable no puede entrar a Calidad. La tarea
    sigue "En Revisión" y nadie de los suyos puede atenderla: el paso está
    atascado y hasta B4 no había ninguna pantalla donde se viera.
    """
    sin = make_user(db_session, "SIN")
    otro = make_user(db_session, "OTRO")   # tiene acceso, pero no está asignado
    doc, steps = _documento_con_dos_pasos(db_session)
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[sin])

    with _con_acceso(otro):
        resp = tasks_client.get(f"{PREFIX}?parent_type=document&parent_id={doc.id}",
                                headers=headers_for(otro))

    fila = next(f for f in resp.json()["data"] if f["id"] == t.id)
    assert fila["assignees_without_access"] == [sin.id]
    # "Bloqueada" es *todos*; el JS lo decide comparando con `assignees`.
    assert [a["id"] for a in fila["assignees"]] == [sin.id]


def test_el_caso_mixto_distingue_bloqueada_de_degradada(tasks_client, db_session):
    """Uno sí y otro no: la tarea NO está atascada, pero cojea.

    Es el caso que separa los dos estados del aviso. Si el payload solo dijera
    "hay alguien sin acceso" (un booleano), la pantalla no podría distinguir
    "nadie puede atenderla" de "queda quien la atienda", que son dos urgencias
    distintas para el supervisor. Por eso viajan los **ids**, no un flag.
    """
    dentro = make_user(db_session, "DENTRO")
    fuera = make_user(db_session, "FUERA")
    doc, steps = _documento_con_dos_pasos(db_session)
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[dentro, fuera])

    with _con_acceso(dentro):
        resp = tasks_client.get(f"{PREFIX}?parent_type=document&parent_id={doc.id}",
                                headers=headers_for(dentro))

    fila = next(f for f in resp.json()["data"] if f["id"] == t.id)
    assert fila["assignees_without_access"] == [fuera.id]
    assert len(fila["assignees"]) == 2


def test_un_asignado_dado_de_baja_cuenta_como_sin_acceso(tasks_client, db_session):
    """Conservar el rol no es poder entrar: el ``is_active`` decide.

    En la base real hay 14 usuarios que mantienen un rol de la app pero están
    dados de baja, y entre ellos suman 82 asignaciones de tarea. Sin el filtro
    las 82 se declararían "con acceso" mientras el desplegable de asignación no
    ofrece a ninguno de ellos — o sea, el aviso callaría justo donde el
    supervisor no tiene a quién reasignar.
    """
    activo = make_user(db_session, "ACTIVO")
    baja = make_user(db_session, "BAJA")
    baja.is_active = False
    db_session.flush()
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[activo, baja])

    with _con_acceso(activo, baja):
        resp = tasks_client.get(f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
                                headers=headers_for(activo))

    fila = next(f for f in resp.json()["data"] if f["id"] == t.id)
    assert fila["assignees_without_access"] == [baja.id]


def test_el_aviso_y_el_desplegable_miran_el_mismo_conjunto(db_session):
    """La invariante de B4, escrita como tal: una regla, dos consumidores.

    ``_app_user_ids`` marca a quién avisar y ``assignable_users`` llena el
    desplegable que desatasca la tarea. Son las dos mitades de la misma
    pregunta —"¿quién puede entrar a Calidad?"— y por eso las dos llaman a
    ``users_with_assignment_select`` con el mismo filtro de ``is_active``. Si
    divergieran, la pantalla señalaría un problema que su propio botón no puede
    resolver.
    """
    from itcj2.apps.adhoc.api.tasks import _app_user_ids
    from itcj2.apps.adhoc.pages._work_context import assignable_users

    dentro = make_user(db_session, "DENTRO")
    baja = make_user(db_session, "BAJA")
    baja.is_active = False
    db_session.flush()

    with _con_acceso(dentro, baja):
        con_acceso = _app_user_ids(db_session)
        ofrecidos = {u["id"] for u in assignable_users(db_session)}

    assert dentro.id in con_acceso
    assert baja.id not in con_acceso
    assert con_acceso == ofrecidos


def test_sin_el_conjunto_la_clave_no_afirma_que_nadie_tiene_acceso(db_session):
    """El default honesto, mismo criterio que ``thread_readable`` en B3.

    Una lista vacía afirmaría "comprobé y todos los asignados tienen acceso", y
    sin conjunto eso no se ha comprobado. Ausente, el JS lee
    ``(fila.assignees_without_access || []).length`` y da 0: la UI se calla
    igual, pero el JSON no ha afirmado nada que no supiera.

    ``flow_step`` va al revés y por eso se comprueba aquí al lado: esa sí se
    emite siempre, porque el paso es un dato de la tarea y no depende de ningún
    contexto que el llamante pueda no haber calculado.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    data = serialize_task(t)

    assert "assignees_without_access" not in data
    assert "thread_readable" not in data
    assert "flow_step" in data and data["flow_step"] is None


def test_si_el_conjunto_no_se_puede_calcular_la_lista_no_se_cae(tasks_client, db_session):
    """Sin fila de ``core_apps`` no hay aviso, pero sí hay lista.

    ``users_with_assignment_select`` resuelve la fila de la app y lanza 404 si
    falta. Solo un admin global puede llegar ahí (a cualquier otro
    ``cached_has_assignment`` ya le habría dado 403), y una lista de tareas no
    se cae por no poder calcular un aviso: se omite la clave.
    """
    from fastapi import HTTPException

    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    with patch("itcj2.core.services.authz_service.users_with_assignment_select",
               side_effect=HTTPException(status_code=404, detail="App inexistente")):
        resp = tasks_client.get(f"{PREFIX}?parent_type=incident&parent_id={inc.id}",
                                headers=headers_for(u))

    assert resp.status_code == 200
    fila = next(f for f in resp.json()["data"] if f["id"] == t.id)
    assert "assignees_without_access" not in fila
    assert "flow_step" in fila


def test_el_tablero_personal_no_paga_el_aviso(tasks_client, db_session):
    """``/tasks/mine`` no emite la clave, y es deliberado.

    El aviso es para quien SUPERVISA a los asignados; el tablero lo mira el
    asignado, que por definición sí pudo entrar. Calcular ahí el conjunto sería
    pagar dos queries por carga de la landing para no pintar nada.
    """
    u = make_user(db_session, "YO")
    inc = make_incident(db_session)
    make_task(db_session, incident=inc, status="Pendiente", assignees=[u])

    with _con_acceso(u):
        resp = tasks_client.get(f"{PREFIX}/mine", headers=headers_for(u))

    assert resp.status_code == 200
    fila = resp.json()["data"][0]
    assert "assignees_without_access" not in fila
    # `flow_step` sí, porque no depende del contexto de la petición.
    assert "flow_step" in fila

"""Tests de ``itcj2.apps.adhoc.services.task_service``.

Cubre el CRUD, la asignación, los comentarios y —sobre todo— el tablero del
dashboard (``get_dashboard_tasks``), que es la fuente de ``GET /tasks/mine`` y
la puerta de entrada al workflow (plan §3.b: cuatro predicados en UNA query).
"""
from datetime import date, datetime
from io import BytesIO

import pytest
from fastapi import HTTPException

from itcj2.apps.adhoc.services import upload_service
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


class _FakeUploadSettings:
    def __init__(self, root):
        self.ADHOC_UPLOAD_PATH = str(root)
        self.ADHOC_MAX_FILE_SIZE = 1024 * 1024
        self.ADHOC_ALLOWED_EXTENSIONS = "pdf,png,txt"


class _FakeUpload:
    """Duck-type de ``fastapi.UploadFile`` (espejo del de ``test_incidents_service.py``)."""

    def __init__(self, filename, content=b"contenido", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self.file = BytesIO(content)


@pytest.fixture()
def uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service, "_settings", lambda: _FakeUploadSettings(tmp_path))
    return tmp_path


# ==========================================================================
# Listado por padre
# ==========================================================================

def test_list_by_parent_devuelve_solo_las_del_padre(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session, "Inc A")
    otra = make_incident(db_session, "Inc B")
    t1 = make_task(db_session, incident=inc, description="uno")
    make_task(db_session, incident=otra, description="dos")

    tasks = AdhocTaskService.list_by_parent(db_session, "incident", inc.id)

    assert [t.id for t in tasks] == [t1.id]


def test_list_by_parent_padre_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.list_by_parent(db_session, "incident", 987654321)

    assert exc.value.status_code == 404
    assert isinstance(exc.value.detail, str)


# ==========================================================================
# Alta masiva
# ==========================================================================

def test_bulk_create_liga_al_padre_y_asigna(db_session):
    from itcj2.apps.adhoc.schemas.tasks import TaskBulkCreate
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u1 = make_user(db_session, "ANA")
    u2 = make_user(db_session, "LUIS")

    payload = TaskBulkCreate.model_validate({
        "parent_type": "incident",
        "parent_id": inc.id,
        "tasks": [
            {"description": "Revisar extintores", "start_date": "2026-09-01",
             "due_date": "2026-09-10", "responsible_ids": [u1.id, u2.id]},
            {"description": "Actualizar bitácora"},
        ],
    })

    created = AdhocTaskService.bulk_create(db_session, payload, created_by_id=u1.id)

    assert len(created) == 2
    assert all(t.incident_id == inc.id for t in created)
    assert created[0].start_date == date(2026, 9, 1)
    assert {u.id for u in created[0].assignees} == {u1.id, u2.id}
    assert created[1].assignees == []
    assert created[0].status == "Pendiente"
    assert created[0].created_by_id == u1.id


def test_bulk_create_padre_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.schemas.tasks import TaskBulkCreate
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    payload = TaskBulkCreate.model_validate({
        "parent_type": "program", "parent_id": 987654321,
        "tasks": [{"description": "x"}],
    })

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.bulk_create(db_session, payload, created_by_id=None)

    assert exc.value.status_code == 404


def test_bulk_create_ignora_asignados_inexistentes(db_session):
    """Un id de usuario basura no debe abortar el lote (el legacy sí lo hacía)."""
    from itcj2.apps.adhoc.schemas.tasks import TaskBulkCreate
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    ev = make_program_event(db_session)
    u1 = make_user(db_session)

    payload = TaskBulkCreate.model_validate({
        "parent_type": "program", "parent_id": ev.id,
        "tasks": [{"description": "x", "responsible_ids": [u1.id, 987654321]}],
    })

    created = AdhocTaskService.bulk_create(db_session, payload, created_by_id=None)

    assert {u.id for u in created[0].assignees} == {u1.id}


# ==========================================================================
# Actualización
# ==========================================================================

def test_update_completada_pone_completed_at(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    updated = AdhocTaskService.update(db_session, t.id, {"status": "Completada"}, actor_id=None)

    assert updated.status == "Completada"
    assert isinstance(updated.completed_at, datetime)


def test_update_saliendo_de_completada_limpia_completed_at(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, status="Completada")
    t.completed_at = datetime(2026, 1, 1, 10, 0)
    db_session.flush()

    updated = AdhocTaskService.update(db_session, t.id, {"status": "En Proceso"}, actor_id=None)

    assert updated.completed_at is None


def test_update_es_parche_no_reemplazo(db_session):
    """Mandar solo ``status`` no debe borrar la descripción."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, description="No me borres")

    updated = AdhocTaskService.update(db_session, t.id, {"status": "En Proceso"}, actor_id=None)

    assert updated.description == "No me borres"


def test_update_descripcion_nula_es_400(db_session):
    """``adhoc_tasks.description`` es NOT NULL; el legacy metía None y daba 500."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.update(db_session, t.id, {"description": None}, actor_id=None)

    assert exc.value.status_code == 400


def test_update_tarea_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.update(db_session, 987654321, {"status": "En Proceso"}, actor_id=None)

    assert exc.value.status_code == 404


def test_delete_borra_la_tarea(db_session):
    from itcj2.apps.adhoc.models import AdhocTask
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)
    tid = t.id

    AdhocTaskService.delete(db_session, tid)

    assert db_session.get(AdhocTask, tid) is None


def test_delete_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.delete(db_session, 987654321)

    assert exc.value.status_code == 404


# ==========================================================================
# Asignación
# ==========================================================================

def test_set_assignees_reemplaza_la_lista(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u1, u2, u3 = make_user(db_session, "A"), make_user(db_session, "B"), make_user(db_session, "C")
    t = make_task(db_session, incident=inc, assignees=[u1, u2])

    updated = AdhocTaskService.set_assignees(db_session, t.id, [u2.id, u3.id], actor_id=None)

    assert {u.id for u in updated.assignees} == {u2.id, u3.id}


def test_set_assignees_preserva_notified_overdue_de_quien_sigue(db_session):
    """El legacy vaciaba y recreaba, perdiendo la bandera de aviso."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u1, u2 = make_user(db_session, "A"), make_user(db_session, "B")
    t = make_task(db_session, incident=inc, assignees=[u1])
    AdhocTaskService.set_overdue_notifications(db_session, t.id, [u1.id], actor_id=None)
    assert assignee_flag(db_session, t.id, u1.id) is True

    AdhocTaskService.set_assignees(db_session, t.id, [u1.id, u2.id], actor_id=None)

    assert assignee_flag(db_session, t.id, u1.id) is True
    assert assignee_flag(db_session, t.id, u2.id) is False


def test_set_overdue_notifications_marca_y_desmarca_y_pone_urgente(db_session):
    """Efecto de negocio conservado del legacy: la tarea pasa a 'Urgente'."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u1, u2 = make_user(db_session, "A"), make_user(db_session, "B")
    t = make_task(db_session, incident=inc, assignees=[u1, u2], priority="Baja")

    AdhocTaskService.set_overdue_notifications(db_session, t.id, [u1.id], actor_id=None)
    assert assignee_flag(db_session, t.id, u1.id) is True
    assert assignee_flag(db_session, t.id, u2.id) is False
    assert t.priority == "Urgente"

    AdhocTaskService.set_overdue_notifications(db_session, t.id, [u2.id], actor_id=None)
    assert assignee_flag(db_session, t.id, u1.id) is False
    assert assignee_flag(db_session, t.id, u2.id) is True


def test_set_overdue_notifications_agrega_al_no_asignado(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u1, u2 = make_user(db_session, "A"), make_user(db_session, "B")
    t = make_task(db_session, incident=inc, assignees=[u1])

    updated = AdhocTaskService.set_overdue_notifications(db_session, t.id, [u2.id], actor_id=None)

    assert {u.id for u in updated.assignees} == {u1.id, u2.id}
    assert assignee_flag(db_session, t.id, u2.id) is True


# ==========================================================================
# Comentarios
# ==========================================================================

def test_add_comment_persiste(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    c = AdhocTaskService.add_comment(db_session, t.id, u.id, "Listo", upload=None,
                                     has_read_all=False)

    assert c.id is not None
    assert c.comment == "Listo"
    assert c.file_path is None


@pytest.mark.parametrize("texto", [None, "", "   "])
def test_add_comment_vacio_es_400(db_session, texto):
    """``comment`` es NOT NULL: el legacy no validaba y daba IntegrityError → 500."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.add_comment(db_session, t.id, u.id, texto, upload=None,
                                     has_read_all=True)

    assert exc.value.status_code == 400


def test_add_comment_sin_usuario_es_400(db_session):
    """``user_id`` es NOT NULL: el legacy aceptaba anónimo y daba 500."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.add_comment(db_session, t.id, None, "Hola", upload=None,
                                     has_read_all=True)

    assert exc.value.status_code == 400


def test_comment_download_sin_adjunto_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_download(db_session, c.id, actor_id=u.id,
                                             has_read_all=True)

    assert exc.value.status_code == 404


def test_comment_download_con_traversal_es_404(db_session):
    """Fila envenenada: ``open_stored`` la rechaza, no lee fuera de la raíz."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u, file_path="../../../etc/passwd")

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_download(db_session, c.id, actor_id=u.id,
                                             has_read_all=True)

    assert exc.value.status_code == 404


# ==========================================================================
# Adjuntos de comentario (`adhoc_task_comment_files`)
# ==========================================================================

def test_comment_file_download_ok(db_session, uploads_root):
    """El adjunto nuevo se descarga por id de archivo, no por id de comentario."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    meta = upload_service.save_upload("task_comments", t.id, _FakeUpload("evidencia.pdf"))
    f = add_comment_file(db_session, c, original_name="evidencia.pdf", file_path=meta["file_path"])

    row, path = AdhocTaskService.get_comment_file_download(
        db_session, f.id, actor_id=u.id, has_read_all=True)

    assert row.id == f.id
    assert path.is_file()
    assert path.name.endswith(".pdf")


def test_comment_file_download_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_file_download(db_session, 99_999_999,
                                                  actor_id=1, has_read_all=True)

    assert exc.value.status_code == 404


def test_comment_file_download_sin_binario_es_404(db_session):
    """``file_path`` NULL: adjunto migrado cuyo binario ya no está en el proveedor."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    f = add_comment_file(db_session, c, file_path=None)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_file_download(db_session, f.id, actor_id=u.id,
                                                  has_read_all=True)

    assert exc.value.status_code == 404


def test_comment_file_download_con_traversal_es_404(db_session):
    """Fila envenenada: ``open_stored`` la rechaza, no lee fuera de la raíz."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)
    f = add_comment_file(db_session, c, file_path="../../../etc/passwd")

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_file_download(db_session, f.id, actor_id=u.id,
                                                  has_read_all=True)

    assert exc.value.status_code == 404


def test_workflow_details_expone_varios_adjuntos_por_comentario(db_session):
    """``serialize_comment`` trae ``files`` (0..N) además del ``file_path`` heredado.

    Cubre exactamente el caso que dejó 213 comentarios sin adjunto visible: el
    ETL puso más de un archivo en ``adhoc_task_comment_files`` porque
    ``file_path`` solo admite uno.
    """
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u, file_path="legado/unico.pdf")
    f1 = add_comment_file(db_session, c, original_name="anexo1.pdf", file_path="1/anexo1.pdf")
    f2 = add_comment_file(db_session, c, original_name="anexo2.pdf", file_path=None)

    detail = AdhocTaskService.get_workflow_details(
        db_session, t.id, actor_id=u.id, has_read_all=True
    )

    comentario = detail["comments"][0]
    assert comentario["file_path"] == "legado/unico.pdf"
    assert [f["id"] for f in comentario["files"]] == [f1.id, f2.id]
    disponibilidad = {f["id"]: f["is_available"] for f in comentario["files"]}
    assert disponibilidad[f1.id] is True
    assert disponibilidad[f2.id] is False


# ==========================================================================
# Detalle de workflow
# ==========================================================================

def test_get_workflow_details_de_tarea_documental(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    autor = make_user(db_session, "AUTOR")
    val = make_user(db_session, "VALIDADOR")
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[val])
    add_comment(db_session, t, val, "primer comentario")

    detail = AdhocTaskService.get_workflow_details(
        db_session, t.id, actor_id=val.id, has_read_all=False
    )

    assert detail["task"]["id"] == t.id
    assert detail["parent"]["type"] == "document"
    assert detail["parent"]["step_name"] == steps[0].name
    assert detail["parent"]["author"]["id"] == autor.id
    assert len(detail["comments"]) == 1
    assert detail["approvals"] == []


def test_get_workflow_details_de_tarea_de_incidencia(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    resp = make_user(db_session, "RESP")
    inc = make_incident(db_session, "Inc con responsable", responsible=resp)
    t = make_task(db_session, incident=inc)

    # Sin `read.all`: `resp` no está asignado a la tarea, pero es el
    # responsable del padre, y eso basta (D4).
    detail = AdhocTaskService.get_workflow_details(
        db_session, t.id, actor_id=resp.id, has_read_all=False
    )

    assert detail["parent"]["type"] == "incident"
    assert detail["parent"]["responsible"]["id"] == resp.id


def test_get_workflow_details_sin_read_all_ni_relacion_es_403(db_session):
    """D4: ni asignado ni responsable del padre, y sin `read.all` -> 403."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    ajeno = make_user(db_session, "AJENO")
    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_workflow_details(
            db_session, t.id, actor_id=ajeno.id, has_read_all=False
        )

    assert exc.value.status_code == 403


def test_get_workflow_details_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_workflow_details(
            db_session, 987654321, actor_id=1, has_read_all=True
        )

    assert exc.value.status_code == 404


# ==========================================================================
# Tablero del dashboard — los 4 predicados del plan §3.b
# ==========================================================================

def test_dashboard_incluye_tareas_abiertas_del_ejecutor(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    u = make_user(db_session)
    inc = make_incident(db_session)
    pendiente = make_task(db_session, incident=inc, status="Pendiente", assignees=[u])
    rechazada = make_task(db_session, incident=inc, status="Rechazada", assignees=[u])
    en_proceso = make_task(db_session, incident=inc, status="En Proceso", assignees=[u])
    completada = make_task(db_session, incident=inc, status="Completada", assignees=[u])

    ids = {t.id for t in AdhocTaskService.get_dashboard_tasks(db_session, u.id)}

    assert {pendiente.id, rechazada.id, en_proceso.id} <= ids
    assert completada.id not in ids


def test_dashboard_incluye_revision_del_responsable_de_incidencia(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    revisor = make_user(db_session, "REVISOR")
    ejecutor = make_user(db_session, "EJECUTOR")
    inc = make_incident(db_session, responsible=revisor)
    en_revision = make_task(db_session, incident=inc, status="En Revisión", assignees=[ejecutor])
    pendiente = make_task(db_session, incident=inc, status="Pendiente", assignees=[ejecutor])

    ids = {t.id for t in AdhocTaskService.get_dashboard_tasks(db_session, revisor.id)}

    assert en_revision.id in ids
    assert pendiente.id not in ids


def test_dashboard_incluye_revision_del_responsable_de_evento(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    revisor = make_user(db_session, "REVISOR")
    ejecutor = make_user(db_session, "EJECUTOR")
    ev = make_program_event(db_session, responsible=revisor)
    en_revision = make_task(db_session, program=ev, status="En Revisión", assignees=[ejecutor])

    ids = {t.id for t in AdhocTaskService.get_dashboard_tasks(db_session, revisor.id)}

    assert en_revision.id in ids


def test_dashboard_incluye_tareas_documentales_asignadas(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    val = make_user(db_session, "VALIDADOR")
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=val, flow=flow, current_step=steps[0])
    revision = make_task(db_session, document=doc, flow_step=steps[0],
                         status="En Revisión", assignees=[val])
    espera = make_task(db_session, document=doc, flow_step=steps[1],
                       status="En Espera", assignees=[val])

    ids = {t.id for t in AdhocTaskService.get_dashboard_tasks(db_session, val.id)}

    assert {revision.id, espera.id} <= ids


def test_dashboard_no_duplica_la_tarea_que_cae_en_dos_ramas(db_session):
    """Tarea documental asignada al propio usuario: ramas 1 y 4 la capturan."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    u = make_user(db_session)
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=u, flow=flow, current_step=steps[0])
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[u])
    # Y además una de incidencia donde es responsable Y ejecutor.
    inc = make_incident(db_session, responsible=u)
    t2 = make_task(db_session, incident=inc, status="En Revisión", assignees=[u])

    tasks = AdhocTaskService.get_dashboard_tasks(db_session, u.id)
    ids = [t.id for t in tasks]

    assert len(ids) == len(set(ids))
    assert {t.id, t2.id} <= set(ids)


def test_dashboard_excluye_lo_ajeno(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    yo = make_user(db_session, "YO")
    otro = make_user(db_session, "OTRO")
    inc = make_incident(db_session, responsible=otro)
    ajena = make_task(db_session, incident=inc, status="Pendiente", assignees=[otro])

    ids = {t.id for t in AdhocTaskService.get_dashboard_tasks(db_session, yo.id)}

    assert ajena.id not in ids


# ==========================================================================
# `puede_leer_hilo` — la fuente única de B3
#
# El predicado vive en ``schemas/tasks.py`` (ver su docstring: es la dirección
# de los imports la que lo puso ahí), pero lo que decide es de este dominio:
# quién alcanza el hilo de comentarios de una tarea. Se prueba junto al service
# porque las dos mitades obligadas a decir lo mismo son ``get_workflow_details``
# —que levanta el 403— y ``serialize_task`` —que emite ``thread_readable``, el
# flag con el que la lista de tareas pinta el contador clicable o apagado.
#
# El criterio: con ``adhoc.tasks.api.read.all`` se lee cualquier hilo; sin él
# hay que estar asignado a la tarea o ser el responsable de la incidencia o del
# evento padre.
# ==========================================================================

def test_puede_leer_hilo_con_read_all_alcanza_cualquier_hilo(db_session):
    """``has_read_all`` corta antes que todo lo demás: ni asignado ni responsable."""
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    ajeno = make_user(db_session, "AJENO")
    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    assert puede_leer_hilo(t, actor_id=ajeno.id, has_read_all=True) is True


def test_puede_leer_hilo_del_asignado_sin_read_all(db_session):
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    assert puede_leer_hilo(t, actor_id=asignado.id, has_read_all=False) is True


def test_puede_leer_hilo_del_responsable_de_la_incidencia(db_session):
    """El responsable del expediente no suele estar asignado a sus propias tareas."""
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    resp = make_user(db_session, "RESP")
    ejecutor = make_user(db_session, "EJECUTOR")
    inc = make_incident(db_session, "Inc con responsable", responsible=resp)
    t = make_task(db_session, incident=inc, assignees=[ejecutor])

    assert puede_leer_hilo(t, actor_id=resp.id, has_read_all=False) is True


def test_puede_leer_hilo_del_responsable_del_evento_de_programa(db_session):
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    resp = make_user(db_session, "RESP")
    ejecutor = make_user(db_session, "EJECUTOR")
    ev = make_program_event(db_session, "Evento con responsable", responsible=resp)
    t = make_task(db_session, program=ev, assignees=[ejecutor])

    assert puede_leer_hilo(t, actor_id=resp.id, has_read_all=False) is True


def test_puede_leer_hilo_del_ajeno_es_false(db_session):
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    ajeno = make_user(db_session, "AJENO")
    asignado = make_user(db_session, "ASIGNADO")
    resp = make_user(db_session, "RESP")
    inc = make_incident(db_session, responsible=resp)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    assert puede_leer_hilo(t, actor_id=ajeno.id, has_read_all=False) is False


def test_puede_leer_hilo_en_tarea_documental_solo_alcanza_a_sus_asignados(db_session):
    """Un documento no tiene ``responsible_id``: la única vía es estar asignado.

    Es además el caso que deja ``task.incident`` y ``task.program`` en ``None``
    **a la vez**; el predicado tiene que resolverlo sin reventar. Las tareas de
    documento no tienen todavía pantalla propia (la trae B4), y cuando la tengan
    heredarán este mismo criterio sin trabajo extra.
    """
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    autor = make_user(db_session, "AUTOR")
    validador = make_user(db_session, "VALIDADOR")
    ajeno = make_user(db_session, "AJENO")
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])
    t = make_task(db_session, document=doc, flow_step=steps[0],
                  status="En Revisión", assignees=[validador])

    assert t.incident is None and t.program is None
    assert puede_leer_hilo(t, actor_id=validador.id, has_read_all=False) is True
    assert puede_leer_hilo(t, actor_id=ajeno.id, has_read_all=False) is False
    # Ni siquiera el autor del documento: no está asignado al paso.
    assert puede_leer_hilo(t, actor_id=autor.id, has_read_all=False) is False


def test_puede_leer_hilo_sin_actor_es_false(db_session):
    """Nunca ``True`` por omisión: sin actor no hay nada que afirmar."""
    from itcj2.apps.adhoc.schemas.tasks import puede_leer_hilo

    asignado = make_user(db_session, "ASIGNADO")
    inc = make_incident(db_session, responsible=asignado)
    t = make_task(db_session, incident=inc, assignees=[asignado])

    assert puede_leer_hilo(t, actor_id=None, has_read_all=False) is False


def test_serialize_task_sin_contexto_no_emite_el_flag(db_session):
    """Sin ``actor_id`` la clave **no sale**, en vez de salir en ``False``.

    Un ``False`` por omisión sería una afirmación que el serializador no tiene
    con qué sostener, y sería falsa justo donde más aparecería: dentro de
    ``serialize_workflow_details``, o sea en el payload que el actor está
    leyendo en ese preciso momento. Ausente, el JS lo lee como ``undefined``,
    que es falsy: misma prudencia en la UI, sin mentir en el JSON.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task

    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    assert "thread_readable" not in serialize_task(t)
    assert serialize_task(t, actor_id=u.id)["thread_readable"] is True


def test_el_flag_y_el_403_nunca_se_contradicen(db_session):
    """**El test que impide el botón roto.**

    Matriz de las tres formas que tiene una tarea de tener padre, cruzada con
    las cinco relaciones que un actor puede guardar con ella y con los dos
    valores de ``has_read_all``. En cada celda se preguntan las dos mitades:
    qué ``thread_readable`` emite ``serialize_task`` —lo que la lista usa para
    decidir si el contador de comentarios es un botón— y qué contesta
    ``get_workflow_details``, que es quien levanta el 403. Tienen que coincidir
    SIEMPRE y en los dos sentidos: si el flag dice que sí, el detalle no puede
    negarse; si dice que no, no puede abrirse.

    Con una sola función el resultado es una tautología —y por eso el test es
    barato de mantener—; deja de serlo en cuanto alguien reimplemente el
    criterio en la mitad que le toque, que es exactamente lo que pasó en B1 con
    ``DOCUMENT_STATUSES_STARTABLE``.
    """
    from itcj2.apps.adhoc.schemas.tasks import serialize_task
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    asignado = make_user(db_session, "ASIGNADO")
    resp_inc = make_user(db_session, "RESPINC")
    resp_prog = make_user(db_session, "RESPPRG")
    validador = make_user(db_session, "VALIDADOR")
    ajeno = make_user(db_session, "AJENO")

    inc = make_incident(db_session, "Inc matriz", responsible=resp_inc)
    ev = make_program_event(db_session, "Evt matriz", responsible=resp_prog)
    flow, steps = make_flow(db_session)
    doc = make_document(db_session, author=ajeno, flow=flow, current_step=steps[0])

    tareas = {
        "incidencia": make_task(db_session, incident=inc, assignees=[asignado]),
        "evento": make_task(db_session, program=ev, assignees=[asignado]),
        "documento": make_task(db_session, document=doc, flow_step=steps[0],
                               status="En Revisión", assignees=[validador]),
    }
    actores = {"asignado": asignado, "resp_inc": resp_inc, "resp_prog": resp_prog,
               "validador": validador, "ajeno": ajeno}

    vistos = set()
    for nombre_tarea, tarea in tareas.items():
        for nombre_actor, actor in actores.items():
            for has_read_all in (False, True):
                caso = (nombre_tarea, nombre_actor, has_read_all)

                flag = serialize_task(
                    tarea, actor_id=actor.id, has_read_all=has_read_all
                )["thread_readable"]

                try:
                    AdhocTaskService.get_workflow_details(
                        db_session, tarea.id, actor_id=actor.id,
                        has_read_all=has_read_all,
                    )
                    alcanzable = True
                except HTTPException as exc:
                    assert exc.status_code == 403, caso
                    alcanzable = False

                assert flag is alcanzable, caso
                vistos.add(alcanzable)

    # Los dos caminos recorridos: una matriz que solo viera 200 no probaría nada.
    assert vistos == {True, False}

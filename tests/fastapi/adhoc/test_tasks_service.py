"""Tests de ``itcj2.apps.adhoc.services.task_service``.

Cubre el CRUD, la asignación, los comentarios y —sobre todo— el tablero del
dashboard (``get_dashboard_tasks``), que es la fuente de ``GET /tasks/mine`` y
la puerta de entrada al workflow (plan §3.b: cuatro predicados en UNA query).
"""
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from tests.fastapi.adhoc._tasks_helpers import (
    add_comment,
    assignee_flag,
    make_document,
    make_flow,
    make_incident,
    make_program_event,
    make_task,
    make_user,
)


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

    c = AdhocTaskService.add_comment(db_session, t.id, u.id, "Listo", upload=None)

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
        AdhocTaskService.add_comment(db_session, t.id, u.id, texto, upload=None)

    assert exc.value.status_code == 400


def test_add_comment_sin_usuario_es_400(db_session):
    """``user_id`` es NOT NULL: el legacy aceptaba anónimo y daba 500."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.add_comment(db_session, t.id, None, "Hola", upload=None)

    assert exc.value.status_code == 400


def test_comment_download_sin_adjunto_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u)

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_download(db_session, c.id)

    assert exc.value.status_code == 404


def test_comment_download_con_traversal_es_404(db_session):
    """Fila envenenada: ``open_stored`` la rechaza, no lee fuera de la raíz."""
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    inc = make_incident(db_session)
    u = make_user(db_session)
    t = make_task(db_session, incident=inc)
    c = add_comment(db_session, t, u, file_path="../../../etc/passwd")

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_comment_download(db_session, c.id)

    assert exc.value.status_code == 404


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

    detail = AdhocTaskService.get_workflow_details(db_session, t.id)

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

    detail = AdhocTaskService.get_workflow_details(db_session, t.id)

    assert detail["parent"]["type"] == "incident"
    assert detail["parent"]["responsible"]["id"] == resp.id


def test_get_workflow_details_inexistente_es_404(db_session):
    from itcj2.apps.adhoc.services.task_service import AdhocTaskService

    with pytest.raises(HTTPException) as exc:
        AdhocTaskService.get_workflow_details(db_session, 987654321)

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

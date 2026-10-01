"""Tests del motor de workflow (``task_workflow_service``) — plan §10.b.

Un test por rama de la máquina de estados y uno por cada uno de los ocho
arreglos 🔧 respecto del legacy:

1. actor no asignado → 403 (el legacy dejaba que cualquiera aprobara).
2. sin comentario → 400 (el legacy devolvía ``success:false`` con HTTP **200**).
3. acción desconocida → 400.
4. la aprobación se registra en ``adhoc_task_approvals``, **sin** vaciar la
   lista de asignados.
5. ``paso_actual`` ``None`` → 409 (el legacy: ``AttributeError`` → 500).
6. incidencia terminada → ``'Cerrada'``; evento de programa → ``'Completado'``.
7. ``parent.real_date`` es ``date``, no ``datetime``.
8. la tarea de corrección lleva ``created_by_id``.
"""
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from tests.fastapi.adhoc._tasks_helpers import (
    add_comment,
    make_document,
    make_flow,
    make_incident,
    make_program_event,
    make_task,
    make_user,
)


def _action(db, task_id, accion, actor_id):
    from itcj2.apps.adhoc.services.task_workflow_service import AdhocTaskWorkflowService

    return AdhocTaskWorkflowService.workflow_action(db, task_id, accion, actor_id)


# ==========================================================================
# Precondiciones comunes
# ==========================================================================

def test_tarea_inexistente_es_404(db_session):
    with pytest.raises(HTTPException) as exc:
        _action(db_session, 987654321, "aprobar", 1)
    assert exc.value.status_code == 404


def test_actor_no_asignado_es_403(db_session):
    """🔧 Bug #1 del legacy: cualquiera aprobaba o rechazaba cualquier documento."""
    asignado = make_user(db_session, "ASIGNADO")
    intruso = make_user(db_session, "INTRUSO")
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[asignado])
    add_comment(db_session, t, asignado)

    with pytest.raises(HTTPException) as exc:
        _action(db_session, t.id, "aprobar", intruso.id)

    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, str)
    db_session.refresh(t)
    assert t.status == "Pendiente"


def test_sin_comentario_es_400(db_session):
    """🔧 El legacy respondía ``success:false`` con HTTP 200."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])

    with pytest.raises(HTTPException) as exc:
        _action(db_session, t.id, "aprobar", u.id)

    assert exc.value.status_code == 400


def test_accion_invalida_es_400(db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    with pytest.raises(HTTPException) as exc:
        _action(db_session, t.id, "borrar-todo", u.id)

    assert exc.value.status_code == 400


def test_accion_vacia_es_400(db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    with pytest.raises(HTTPException) as exc:
        _action(db_session, t.id, None, u.id)

    assert exc.value.status_code == 400


# ==========================================================================
# Rama A — tarea SIN documento
# ==========================================================================

def test_rama_a_terminar(db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    _action(db_session, t.id, "terminar", u.id)

    db_session.refresh(t)
    assert t.status == "En Revisión"
    assert isinstance(t.completed_at, datetime)


def test_rama_a_rechazar(db_session):
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, status="En Revisión", assignees=[u])
    t.completed_at = datetime(2026, 1, 1, 9, 0)
    db_session.flush()
    add_comment(db_session, t, u)

    _action(db_session, t.id, "rechazar", u.id)

    db_session.refresh(t)
    assert t.status == "Rechazada"
    assert t.completed_at is None


def test_rama_a_aprobar_cierra_la_incidencia(db_session):
    """🔧 El legacy escribía 'Completado', valor que la UI de incidencias ignora."""
    u = make_user(db_session)
    inc = make_incident(db_session)
    t = make_task(db_session, incident=inc, assignees=[u])
    add_comment(db_session, t, u)

    _action(db_session, t.id, "aprobar", u.id)

    db_session.refresh(t)
    db_session.refresh(inc)
    assert t.status == "Completada"
    assert inc.status == "Cerrada"
    assert inc.real_date == date.today()
    assert isinstance(inc.real_date, date) and not isinstance(inc.real_date, datetime)


def test_rama_a_aprobar_completa_el_evento_de_programa(db_session):
    u = make_user(db_session)
    ev = make_program_event(db_session)
    t = make_task(db_session, program=ev, assignees=[u])
    add_comment(db_session, t, u)

    _action(db_session, t.id, "aprobar", u.id)

    db_session.refresh(ev)
    assert ev.status == "Completado"
    assert ev.real_date == date.today()


# ==========================================================================
# Rama B — documento rechazado
# ==========================================================================

def _documento_en_flujo(db_session, validadores, *, pasos=("Revisión", "Autorización")):
    """Documento en revisión con una tarea por paso, como lo deja ``start_flow``."""
    autor = make_user(db_session, "AUTOR")
    flow, steps = make_flow(db_session, steps=pasos)
    doc = make_document(db_session, author=autor, flow=flow, current_step=steps[0])
    tareas = []
    for i, step in enumerate(steps):
        tareas.append(make_task(
            db_session, document=doc, flow_step=step,
            description=f"Aprobar Documento: {doc.title} (Paso: {step.name})",
            status="En Revisión" if i == 0 else "En Espera",
            priority="Alta", assignees=validadores, created_by=autor,
        ))
    return autor, doc, steps, tareas


def test_rama_b_rechazo_marca_documento_y_registra_la_decision(db_session):
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    val = make_user(db_session, "VALIDADOR")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [val])
    add_comment(db_session, tareas[0], val, "Falta la portada")

    _action(db_session, tareas[0].id, "rechazar", val.id)

    db_session.refresh(doc)
    db_session.refresh(tareas[0])
    assert doc.status == "Rechazado"
    assert tareas[0].status == "Rechazada"

    # 🔧 la decisión queda registrada y los asignados NO se pierden
    aprobaciones = db_session.query(AdhocTaskApproval).filter_by(task_id=tareas[0].id).all()
    assert len(aprobaciones) == 1
    assert aprobaciones[0].decision == "rechazado"
    assert aprobaciones[0].user_id == val.id
    assert [u.id for u in tareas[0].assignees] == [val.id]


def test_rama_b_rechazo_borra_las_tareas_en_espera(db_session):
    from itcj2.apps.adhoc.models import AdhocTask

    val = make_user(db_session, "VALIDADOR")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [val])
    id_en_espera = tareas[1].id
    add_comment(db_session, tareas[0], val)

    _action(db_session, tareas[0].id, "rechazar", val.id)

    assert db_session.get(AdhocTask, id_en_espera) is None


def test_rama_b_crea_tarea_de_correccion_con_creador(db_session):
    """🔧 El legacy dejaba la tarea de corrección sin ``created_by_id``."""
    from itcj2.apps.adhoc.models import AdhocTask

    val = make_user(db_session, "VALIDADOR")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [val])
    add_comment(db_session, tareas[0], val)

    _action(db_session, tareas[0].id, "rechazar", val.id)

    correccion = (
        db_session.query(AdhocTask)
        .filter(AdhocTask.document_id == doc.id, AdhocTask.id != tareas[0].id)
        .one()
    )
    assert correccion.description == f"Corregir Documento Rechazado: {doc.title}"
    assert correccion.status == "Rechazada"
    assert correccion.priority == "Urgente"
    assert correccion.created_by_id == val.id
    assert [u.id for u in correccion.assignees] == [autor.id]


def test_rama_b_terminar_sobre_documento_es_400(db_session):
    """'terminar' no aplica a una tarea documental (igual que el legacy)."""
    val = make_user(db_session, "VALIDADOR")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [val])
    add_comment(db_session, tareas[0], val)

    with pytest.raises(HTTPException) as exc:
        _action(db_session, tareas[0].id, "terminar", val.id)

    assert exc.value.status_code == 400


# ==========================================================================
# Rama C — aprobación multi-validador
# ==========================================================================

def test_rama_c_primer_validador_no_completa_la_tarea(db_session):
    """🔧 El legacy iba REMOVIENDO al usuario de ``assigned_users``."""
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    v1 = make_user(db_session, "VAL1")
    v2 = make_user(db_session, "VAL2")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v1, v2])
    add_comment(db_session, tareas[0], v1)

    result = _action(db_session, tareas[0].id, "aprobar", v1.id)

    db_session.refresh(tareas[0])
    assert tareas[0].status == "En Revisión"
    assert {u.id for u in tareas[0].assignees} == {v1.id, v2.id}  # intactos
    assert db_session.query(AdhocTaskApproval).filter_by(task_id=tareas[0].id).count() == 1
    assert "Esperando" in result["message"]


def test_rama_c_aprobar_dos_veces_es_idempotente(db_session):
    """El unique ``(task_id, user_id)`` no debe explotar en un doble clic."""
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    v1 = make_user(db_session, "VAL1")
    v2 = make_user(db_session, "VAL2")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v1, v2])
    add_comment(db_session, tareas[0], v1)

    _action(db_session, tareas[0].id, "aprobar", v1.id)
    _action(db_session, tareas[0].id, "aprobar", v1.id)

    assert db_session.query(AdhocTaskApproval).filter_by(task_id=tareas[0].id).count() == 1
    db_session.refresh(tareas[0])
    assert tareas[0].status == "En Revisión"


def test_rama_c_reasignar_no_cuenta_aprobaciones_de_quien_ya_no_esta(db_session):
    """🔧 D3: ``_approved_count`` filtraba solo por ``task_id`` + ``decision``.

    Si alguien reasigna la tarea después de que parte del paso ya aprobó, las
    aprobaciones de gente que ya no está asignada no deben seguir contando
    para el paso avanzar.
    """
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    v1 = make_user(db_session, "VAL1")
    v2 = make_user(db_session, "VAL2")
    v3 = make_user(db_session, "VAL3")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v1, v2])
    add_comment(db_session, tareas[0], v1)

    result1 = _action(db_session, tareas[0].id, "aprobar", v1.id)
    assert "Esperando" in result1["message"]

    # Reasignación: v1 sale, entra v3. La tarea queda en manos de v2 y v3, y la
    # aprobación histórica de v1 sigue en `adhoc_task_approvals`.
    tareas[0].assignees = [v2, v3]
    db_session.flush()
    assert db_session.query(AdhocTaskApproval).filter_by(
        task_id=tareas[0].id, decision="aprobado"
    ).count() == 1  # la de v1, todavía ahí

    add_comment(db_session, tareas[0], v2)
    result2 = _action(db_session, tareas[0].id, "aprobar", v2.id)

    db_session.refresh(tareas[0])
    # Sin el fix, la aprobación vieja de v1 (ya no asignado) sumaba junto con
    # la de v2 y el paso avanzaba sin que v3 aprobara nada.
    assert "Esperando" in result2["message"]
    assert tareas[0].status == "En Revisión"

    add_comment(db_session, tareas[0], v3)
    result3 = _action(db_session, tareas[0].id, "aprobar", v3.id)

    db_session.refresh(tareas[0])
    assert tareas[0].status == "Completada"
    assert "Acción procesada" in result3["message"]


def test_rama_c_ultimo_validador_avanza_al_siguiente_paso(db_session):
    v1 = make_user(db_session, "VAL1")
    v2 = make_user(db_session, "VAL2")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v1, v2])
    add_comment(db_session, tareas[0], v1)

    _action(db_session, tareas[0].id, "aprobar", v1.id)
    _action(db_session, tareas[0].id, "aprobar", v2.id)

    db_session.refresh(doc)
    db_session.refresh(tareas[0])
    db_session.refresh(tareas[1])
    assert tareas[0].status == "Completada"
    assert isinstance(tareas[0].completed_at, datetime)
    assert doc.current_step_id == steps[1].id
    assert doc.status == "En Revisión"
    assert tareas[1].status == "En Revisión"


def test_rama_c_ultimo_paso_aprueba_el_documento(db_session):
    v = make_user(db_session, "VAL")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v], pasos=("Único",))
    add_comment(db_session, tareas[0], v)

    _action(db_session, tareas[0].id, "aprobar", v.id)

    db_session.refresh(doc)
    assert doc.status == "Aprobado"
    assert isinstance(doc.approval_date, datetime)


def test_rama_c_documento_sin_paso_actual_es_409(db_session):
    """🔧 El legacy reventaba con ``AttributeError`` → 500."""
    v = make_user(db_session, "VAL")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v], pasos=("Único",))
    doc.current_step_id = None
    db_session.flush()
    add_comment(db_session, tareas[0], v)

    with pytest.raises(HTTPException) as exc:
        _action(db_session, tareas[0].id, "aprobar", v.id)

    assert exc.value.status_code == 409
    assert isinstance(exc.value.detail, str)


def test_rama_c_la_aprobacion_apunta_al_comentario_del_actor(db_session):
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    v = make_user(db_session, "VAL")
    otro = make_user(db_session, "OTRO")
    autor, doc, steps, tareas = _documento_en_flujo(db_session, [v], pasos=("Único",))
    add_comment(db_session, tareas[0], otro, "comentario ajeno")
    mio = add_comment(db_session, tareas[0], v, "visto bueno")

    _action(db_session, tareas[0].id, "aprobar", v.id)

    ap = db_session.query(AdhocTaskApproval).filter_by(task_id=tareas[0].id).one()
    assert ap.comment_id == mio.id

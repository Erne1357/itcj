"""Motor de workflow de tareas — la pieza más delicada del SGC.

Implementa `POST /tasks/{id}/workflow-action` según la spec del plan §10.b,
extraída de ``api_tasks.py::process_task_workflow`` del legacy. Tres ramas:

* **A — tarea sin documento** (incidencia o evento de programa):
  ``terminar`` / ``rechazar`` / ``aprobar`` sobre la tarea; al aprobar se cierra
  también el padre.
* **B — tarea de documento, ``rechazar``**: documento a ``Rechazado``, se
  borran las tareas del documento que seguían ``En Espera`` y se crea la tarea
  de corrección para el autor.
* **C — tarea de documento, ``aprobar``**: aprobación **multi-validador**. La
  tarea solo se completa cuando *todos* los asignados aprobaron; entonces el
  documento avanza al siguiente paso del flujo o, si no hay siguiente, queda
  ``Aprobado``.

Los ocho arreglos respecto del legacy (marcados 🔧 en el plan) están todos aquí:

1. **El actor debe estar entre los asignados** → 403. El legacy no lo
   comprobaba: cualquier usuario podía aprobar o rechazar cualquier documento
   del sistema.
2. Comentario obligatorio → **400** (el legacy: ``success:false`` con HTTP 200).
3. Acción desconocida → **400**.
4. La aprobación se registra en ``adhoc_task_approvals``; **no** se remueve al
   usuario de los asignados. El legacy modelaba "ya aprobé" haciendo
   ``assigned_users.remove(user)``, y así perdía para siempre tanto quién
   estaba asignado como quién aprobó.
5. ``doc.current_step`` ``None`` → **409** (el legacy: ``AttributeError`` → 500).
6. Al aprobar una tarea genérica el padre incidencia pasa a ``'Cerrada'`` y el
   padre evento de programa a ``'Completado'``. El legacy escribía
   ``'Completado'`` en ambos, valor que su propia UI de incidencias no
   reconocía.
7. ``parent.real_date`` recibe un ``date`` (la columna es ``Date``; el legacy le
   metía un ``datetime``).
8. La tarea de corrección lleva ``created_by_id``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

logger = logging.getLogger(__name__)

__all__ = ["AdhocTaskWorkflowService"]


# ==========================================================================
# Internos
# ==========================================================================

def _load(db: Session, task_id: int):
    from itcj2.apps.adhoc.models import AdhocTask

    task = (
        db.query(AdhocTask)
        .options(
            selectinload(AdhocTask.assignees),
            selectinload(AdhocTask.comments),
            selectinload(AdhocTask.approvals),
            selectinload(AdhocTask.document),
            selectinload(AdhocTask.incident),
            selectinload(AdhocTask.program),
        )
        .filter(AdhocTask.id == task_id)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


def _check_preconditions(db: Session, task, accion: Optional[str], actor_id: Optional[int]) -> str:
    """Las tres precondiciones comunes del plan §10.b, en ese orden.

    Orden deliberado: la pertenencia se comprueba **antes** que la validez de la
    acción, para no filtrarle a un intruso si la tarea tiene comentarios o si su
    acción era válida.
    """
    from itcj2.apps.adhoc.models import AdhocTaskComment
    from itcj2.apps.adhoc.utils.constants import WORKFLOW_ACTIONS

    # 1. 🔧 El actor tiene que estar asignado.
    asignados = {u.id for u in task.assignees}
    if not actor_id or int(actor_id) not in asignados:
        raise HTTPException(
            status_code=403,
            detail="No estás asignado a esta tarea; no puedes ejecutar acciones de flujo",
        )

    # 2. 🔧 Comentario obligatorio (400, no success:false con 200).
    hay_comentario = (
        db.query(AdhocTaskComment.id).filter(AdhocTaskComment.task_id == task.id).first()
        is not None
    )
    if not hay_comentario:
        raise HTTPException(
            status_code=400,
            detail="Es obligatorio agregar un comentario antes de ejecutar la acción",
        )

    # 3. 🔧 Acción del vocabulario cerrado.
    if accion not in WORKFLOW_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Acción no válida: {accion!r}. Use terminar, rechazar o aprobar",
        )

    return accion


def _last_comment_id(db: Session, task_id: int, user_id: int) -> Optional[int]:
    """Último comentario del actor en la tarea — el que justifica su decisión."""
    from itcj2.apps.adhoc.models import AdhocTaskComment

    row = (
        db.query(AdhocTaskComment.id)
        .filter(AdhocTaskComment.task_id == task_id, AdhocTaskComment.user_id == user_id)
        .order_by(AdhocTaskComment.id.desc())
        .first()
    )
    return row[0] if row else None


def _record_decision(db: Session, task, actor_id: int, decision: str):
    """Upsert en ``adhoc_task_approvals``. Idempotente por el unique (task, user).

    Sin esta tabla no hay forma de saber quién validó: era exactamente el bug #4
    del legacy, que "recordaba" la aprobación borrando la asignación.
    """
    from itcj2.apps.adhoc.models import AdhocTaskApproval

    existente = (
        db.query(AdhocTaskApproval)
        .filter(AdhocTaskApproval.task_id == task.id, AdhocTaskApproval.user_id == actor_id)
        .first()
    )
    comment_id = _last_comment_id(db, task.id, actor_id)

    if existente is not None:
        existente.decision = decision
        existente.comment_id = comment_id
        return existente

    aprobacion = AdhocTaskApproval(
        task_id=task.id,
        user_id=actor_id,
        decision=decision,
        comment_id=comment_id,
    )
    db.add(aprobacion)
    return aprobacion


def _approved_count(db: Session, task_id: int) -> int:
    from itcj2.apps.adhoc.models import AdhocTaskApproval
    from itcj2.apps.adhoc.utils.constants import APPROVAL_DECISION_APPROVED

    return (
        db.query(AdhocTaskApproval)
        .filter(
            AdhocTaskApproval.task_id == task_id,
            AdhocTaskApproval.decision == APPROVAL_DECISION_APPROVED,
        )
        .count()
    )


# ==========================================================================
# Service
# ==========================================================================

class AdhocTaskWorkflowService:
    """Las tres acciones de flujo sobre una tarea."""

    @staticmethod
    def workflow_action(db: Session, task_id: int, accion: Optional[str],
                        actor_id: Optional[int]) -> dict:
        """Ejecuta ``terminar`` | ``rechazar`` | ``aprobar`` sobre una tarea.

        Devuelve ``{"message": str, "task_id": int, "document_id": int | None,
        "status": str}``. Los errores salen como ``HTTPException`` con ``detail``
        **string**, que el handler global envuelve en
        ``{"error": "...", "status": N}``.
        """
        task = _load(db, task_id)
        accion = _check_preconditions(db, task, accion, actor_id)
        actor_id = int(actor_id)

        if not task.document_id:
            return AdhocTaskWorkflowService._generic_task(db, task, accion, actor_id)

        if accion == "rechazar":
            return AdhocTaskWorkflowService._reject_document(db, task, actor_id)
        if accion == "aprobar":
            return AdhocTaskWorkflowService._approve_document(db, task, actor_id)

        # 'terminar' no aplica a una tarea documental (igual que el legacy, que
        # caía al `return ... 400` del final).
        raise HTTPException(
            status_code=400,
            detail="Acción no válida para una tarea de documento: use aprobar o rechazar",
        )

    # ------------------------------------------------------------- rama A

    @staticmethod
    def _generic_task(db: Session, task, accion: str, actor_id: int) -> dict:
        """Rama A: tarea de incidencia o de evento de programa."""
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper
        from itcj2.apps.adhoc.utils.constants import (
            INCIDENT_STATUS_CLOSED,
            PROGRAM_EVENT_STATUS_COMPLETED,
            TASK_STATUS_COMPLETED,
            TASK_STATUS_IN_REVIEW,
            TASK_STATUS_REJECTED,
        )

        if accion == "terminar":
            task.status = TASK_STATUS_IN_REVIEW
            task.completed_at = datetime.now()

        elif accion == "rechazar":
            task.status = TASK_STATUS_REJECTED
            task.completed_at = None

        else:  # aprobar
            task.status = TASK_STATUS_COMPLETED
            task.completed_at = datetime.now()
            # 🔧 Vocabulario correcto por tipo de padre + `date`, no `datetime`.
            if task.incident is not None:
                task.incident.status = INCIDENT_STATUS_CLOSED
                task.incident.real_date = date.today()
            elif task.program is not None:
                task.program.status = PROGRAM_EVENT_STATUS_COMPLETED
                task.program.real_date = date.today()

        db.commit()
        db.refresh(task)

        destinatarios = [u for u in task.assignees if u.id != actor_id]
        if destinatarios:
            _fire(db, notify.notify_task_workflow_action, task, accion, destinatarios,
                  actor_id=actor_id)
            _fire_email(AdhocEmailHelper.send_task_updated, db, task, destinatarios,
                        action_label=f"Acción en tarea: {accion}")

        return {
            "message": "Acción procesada exitosamente.",
            "task_id": task.id,
            "document_id": None,
            "status": task.status,
        }

    # ------------------------------------------------------------- rama B

    @staticmethod
    def _reject_document(db: Session, task, actor_id: int) -> dict:
        """Rama B: rechazo de un documento en revisión."""
        from itcj2.apps.adhoc.models import AdhocTask
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper
        from itcj2.apps.adhoc.utils.constants import (
            APPROVAL_DECISION_REJECTED,
            DOCUMENT_STATUS_REJECTED,
            PRIORITY_URGENT,
            TASK_STATUS_REJECTED,
            TASK_STATUS_WAITING,
        )

        doc = task.document

        task.status = TASK_STATUS_REJECTED
        task.completed_at = datetime.now()
        doc.status = DOCUMENT_STATUS_REJECTED

        # 🔧 Queda registro de quién rechazó, sin tocar la asignación.
        _record_decision(db, task, actor_id, APPROVAL_DECISION_REJECTED)

        # Los pasos posteriores dejan de tener sentido: el documento vuelve al autor.
        pendientes = (
            db.query(AdhocTask)
            .filter(
                AdhocTask.document_id == doc.id,
                AdhocTask.status == TASK_STATUS_WAITING,
                AdhocTask.id != task.id,
            )
            .all()
        )
        for futura in pendientes:
            db.delete(futura)

        correccion = AdhocTask(
            description=f"Corregir Documento Rechazado: {doc.title}",
            status=TASK_STATUS_REJECTED,
            priority=PRIORITY_URGENT,
            document_id=doc.id,
            created_by_id=actor_id,  # 🔧 el legacy la dejaba sin creador
        )
        if doc.author is not None:
            correccion.assignees.append(doc.author)
        db.add(correccion)

        db.commit()
        db.refresh(task)
        db.refresh(correccion)

        motivo = "Revisar comentarios en la tarea"
        if doc.author_id:
            _fire(db, notify.notify_document_rejected, doc, doc.author_id, reason=motivo)
            _fire(db, notify.notify_correction_task_created, correccion, doc.author_id)
            _fire_email(AdhocEmailHelper.send_document_rejected, db, doc, doc.author,
                        reason=motivo)
            _fire_email(AdhocEmailHelper.send_task_assigned, db, correccion, [doc.author])

        return {
            "message": "Documento rechazado correctamente.",
            "task_id": task.id,
            "document_id": doc.id,
            "status": task.status,
        }

    # ------------------------------------------------------------- rama C

    @staticmethod
    def _approve_document(db: Session, task, actor_id: int) -> dict:
        """Rama C: aprobación multi-validador de una tarea documental."""
        from itcj2.apps.adhoc.models import AdhocApprovalFlowStep, AdhocTask
        from itcj2.apps.adhoc.services import notify
        from itcj2.apps.adhoc.services.email_helper import AdhocEmailHelper
        from itcj2.apps.adhoc.utils.constants import (
            APPROVAL_DECISION_APPROVED,
            DOCUMENT_STATUS_APPROVED,
            TASK_STATUS_COMPLETED,
            TASK_STATUS_IN_REVIEW,
        )

        doc = task.document

        _record_decision(db, task, actor_id, APPROVAL_DECISION_APPROVED)
        db.flush()

        aprobaciones = _approved_count(db, task.id)
        requeridas = len({u.id for u in task.assignees})

        # Faltan validadores: la tarea sigue viva y los asignados intactos.
        if aprobaciones < requeridas:
            db.commit()
            return {
                "message": ("Aprobaste el documento. Esperando la validación de los "
                            "demás compañeros del paso."),
                "task_id": task.id,
                "document_id": doc.id,
                "status": task.status,
            }

        # 🔧 Sin paso actual no hay a dónde avanzar: 409, no AttributeError → 500.
        # La aprobación SÍ se persiste (es un hecho del validador); lo que falla
        # es el avance del flujo, y al reintentar tras arreglar el documento
        # `_record_decision` es idempotente y el conteo sigue cuadrando.
        paso_actual = doc.current_step
        if paso_actual is None:
            db.commit()
            raise HTTPException(
                status_code=409,
                detail=("El documento no tiene un paso actual asignado; "
                        "no se puede avanzar el flujo"),
            )

        task.status = TASK_STATUS_COMPLETED
        task.completed_at = datetime.now()

        siguiente = (
            db.query(AdhocApprovalFlowStep)
            .filter(
                AdhocApprovalFlowStep.flow_id == doc.flow_id,
                AdhocApprovalFlowStep.step_order > paso_actual.step_order,
            )
            .order_by(AdhocApprovalFlowStep.step_order.asc())
            .first()
        )

        tarea_siguiente = None
        if siguiente is not None:
            doc.current_step_id = siguiente.id
            tarea_siguiente = (
                db.query(AdhocTask)
                .options(selectinload(AdhocTask.assignees))
                .filter(AdhocTask.document_id == doc.id, AdhocTask.flow_step_id == siguiente.id)
                .first()
            )
            if tarea_siguiente is not None:
                tarea_siguiente.status = TASK_STATUS_IN_REVIEW
        else:
            doc.status = DOCUMENT_STATUS_APPROVED
            doc.approval_date = datetime.now()

        db.commit()
        db.refresh(task)

        if tarea_siguiente is not None:
            destinatarios = list(tarea_siguiente.assignees)
            if destinatarios:
                _fire(db, notify.notify_step_advanced, doc, siguiente, destinatarios)
                _fire_email(AdhocEmailHelper.send_task_assigned, db, tarea_siguiente,
                            destinatarios)
        elif siguiente is None and doc.author_id:
            _fire(db, notify.notify_document_approved, doc, doc.author_id)
            _fire_email(AdhocEmailHelper.send_document_approved, db, doc, doc.author)

        return {
            "message": "Acción procesada exitosamente.",
            "task_id": task.id,
            "document_id": doc.id,
            "status": task.status,
        }


# ==========================================================================
# Disparo fail-soft de avisos (mismo contrato que en task_service)
# ==========================================================================

def _fire(db: Session, fn, *args, **kwargs) -> None:
    """Notificación in-app + commit. Nunca lanza: el flujo ya se persistió."""
    try:
        fn(db, *args, **kwargs)
        db.commit()
    except Exception:
        logger.exception("[adhoc] Fallo notificando (%s); se continúa",
                         getattr(fn, "__name__", fn))
        try:
            db.rollback()
        except Exception:
            pass


def _fire_email(fn, *args, **kwargs) -> None:
    """Correo transaccional. Nunca lanza."""
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("[adhoc] Fallo enviando correo (%s); se continúa",
                         getattr(fn, "__name__", fn))

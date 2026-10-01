"""Notificaciones in-app de Adhoc (Calidad).

Una función por **evento de negocio** — los 10 puntos de disparo del plan §7 —
para que ningún service tenga que acordarse del formato del payload. Todas son
*best-effort*: loguean y siguen. Una notificación que falla jamás debe tumbar la
aprobación de un documento (propiedad del legacy que sí valía la pena conservar).

Tres precisiones sobre ``NotificationService`` del core, verificadas en
``itcj2/core/services/notification_service.py``:

1. ``create()`` hace ``db.add()`` + ``db.flush()`` y **no commitea**. El service
   llamador es dueño de la transacción y tiene que commitear él.
2. ``create(**kwargs)`` filtra los kwargs extra contra una whitelist
   (``ticket_id``, ``source_request_id``, ``source_appointment_id``,
   ``program_id``) y **descarta el resto en silencio** → todo lo de adhoc va
   dentro de ``data`` (JSONB). Ojo con ``program_id``: en el core es FK a
   ``core_programs`` (carrera académica), **no** el evento de programa de
   Calidad; por eso el id del evento viaja como ``data['program_event_id']``.
3. ``/notify`` es el *namespace* Socket.IO (``itcj2/sockets/notifications.py``,
   room ``user:{uid}:notify``), no un endpoint HTTP. El broadcast lo hace
   ``create()`` solo; aquí no se toca.

Convención: ``app_name='adhoc'`` · ``data['url']`` apunta a la página donde el
usuario puede actuar sobre lo que se le notifica.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("itcj2.apps.adhoc.notify")

APP_NAME = "adhoc"

# Tipos de notificación (String(100) libre en core_notifications.type).
TYPE_FLOW_STARTED = "ADHOC_FLOW_STARTED"
TYPE_TASK_CREATED = "ADHOC_TASK_CREATED"
TYPE_TASK_UPDATED = "ADHOC_TASK_UPDATED"
TYPE_TASK_ASSIGNED = "ADHOC_TASK_ASSIGNED"
TYPE_TASK_COMMENTED = "ADHOC_TASK_COMMENTED"
TYPE_TASK_WORKFLOW = "ADHOC_TASK_WORKFLOW"
TYPE_DOCUMENT_REJECTED = "ADHOC_DOCUMENT_REJECTED"
TYPE_DOCUMENT_CORRECTION = "ADHOC_DOCUMENT_CORRECTION"
TYPE_STEP_ADVANCED = "ADHOC_STEP_ADVANCED"
TYPE_DOCUMENT_APPROVED = "ADHOC_DOCUMENT_APPROVED"

URL_DASHBOARD = "/adhoc/dashboard"
URL_DOCUMENTS = "/adhoc/documentos"

_TITLE_MAX = 200  # core_notifications.title es String(200)


# ==========================================================================
# Internos
# ==========================================================================

def _user_ids(recipients: Optional[Iterable[Any]], exclude: Optional[int] = None) -> list[int]:
    """Normaliza una lista de usuarios (objetos o ids) a ids únicos y válidos."""
    out: list[int] = []
    seen: set[int] = set()
    for r in recipients or []:
        if r is None:
            continue
        uid = getattr(r, "id", r)
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen or (exclude is not None and uid == exclude):
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _task_url(task: Any) -> str:
    """Página donde el usuario puede actuar sobre la tarea.

    Las tareas documentales se atienden desde el modal de workflow del tablero;
    las de incidencia y programa tienen su propia página de tareas.
    """
    if getattr(task, "document_id", None):
        return URL_DASHBOARD
    if getattr(task, "incident_id", None):
        return f"/adhoc/incidencias/{task.incident_id}/tareas"
    if getattr(task, "program_id", None):
        return f"/adhoc/programas/{task.program_id}/tareas"
    return URL_DASHBOARD


def _task_data(task: Any) -> dict:
    return {
        "task_id": getattr(task, "id", None),
        "document_id": getattr(task, "document_id", None),
        "incident_id": getattr(task, "incident_id", None),
        "program_event_id": getattr(task, "program_id", None),
        "status": getattr(task, "status", None),
        "priority": getattr(task, "priority", None),
    }


def _push(
    db: Session,
    user_ids: Iterable[int],
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    url: str = URL_DASHBOARD,
    data: Optional[dict] = None,
) -> int:
    """Crea una notificación por destinatario. Devuelve cuántas se crearon.

    Nunca lanza: un fallo se loguea y el flujo de negocio continúa. **No hace
    commit** — el service llamador es dueño de la transacción.
    """
    created = 0
    payload = {"url": url, **(data or {})}
    for uid in user_ids:
        try:
            from itcj2.core.services.notification_service import NotificationService

            NotificationService.create(
                db,
                user_id=uid,
                app_name=APP_NAME,
                type=type,
                title=title[:_TITLE_MAX],
                body=body,
                data=payload,
            )
            created += 1
        except Exception as exc:  # pragma: no cover - best-effort por diseño
            logger.warning(
                "[adhoc] No se pudo notificar (%s) al usuario %s: %s", type, uid, exc
            )
    return created


# ==========================================================================
# Los 10 eventos de negocio (plan §7)
# ==========================================================================

def notify_flow_started(db: Session, document: Any, step: Any, recipients: Iterable[Any]) -> int:
    """1. ``POST /documents/{id}/start-flow`` → validadores del primer paso."""
    return _push(
        db,
        _user_ids(recipients),
        type=TYPE_FLOW_STARTED,
        title="Documento para revisión",
        body=f"{document.title} — paso: {getattr(step, 'name', '—')}",
        url=URL_DASHBOARD,
        data={
            "document_id": getattr(document, "id", None),
            "flow_step_id": getattr(step, "id", None),
        },
    )


def notify_task_created(db: Session, task: Any, recipients: Iterable[Any]) -> int:
    """2. ``POST /tasks`` (alta masiva) → asignados."""
    return _push(
        db,
        _user_ids(recipients),
        type=TYPE_TASK_CREATED,
        title="Nueva tarea asignada",
        body=getattr(task, "description", None),
        url=_task_url(task),
        data=_task_data(task),
    )


def notify_task_updated(
    db: Session,
    task: Any,
    recipients: Iterable[Any],
    *,
    action_label: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> int:
    """3. ``PATCH /tasks/{id}`` (cambia descripción o estatus) → asignados.

    ``actor_id`` se excluye: quien hizo el cambio no necesita el aviso.
    """
    return _push(
        db,
        _user_ids(recipients, exclude=actor_id),
        type=TYPE_TASK_UPDATED,
        title=action_label or "Actualización de tarea",
        body=getattr(task, "description", None),
        url=_task_url(task),
        data=_task_data(task),
    )


def notify_task_assignees_changed(db: Session, task: Any, recipients: Iterable[Any]) -> int:
    """4. ``PUT /tasks/{id}/assignees`` → **solo los nuevos** asignados.

    El service debe pasar la diferencia (nuevos − previos), no la lista entera:
    reasignar a alguien que ya estaba no es un evento.
    """
    return _push(
        db,
        _user_ids(recipients),
        type=TYPE_TASK_ASSIGNED,
        title="Se te asignó una tarea",
        body=getattr(task, "description", None),
        url=_task_url(task),
        data=_task_data(task),
    )


def notify_task_commented(
    db: Session,
    task: Any,
    comment: Any,
    recipients: Iterable[Any],
    *,
    actor_id: Optional[int] = None,
) -> int:
    """5. ``POST /tasks/{id}/comments`` → asignados (menos el autor)."""
    texto = (getattr(comment, "comment", "") or "").strip()
    return _push(
        db,
        _user_ids(recipients, exclude=actor_id),
        type=TYPE_TASK_COMMENTED,
        title="Nuevo comentario en una tarea",
        body=(texto[:280] + "…") if len(texto) > 280 else (texto or None),
        url=_task_url(task),
        data={**_task_data(task), "comment_id": getattr(comment, "id", None)},
    )


def notify_task_workflow_action(
    db: Session,
    task: Any,
    action: str,
    recipients: Iterable[Any],
    *,
    actor_id: Optional[int] = None,
) -> int:
    """6. ``POST /tasks/{id}/workflow-action`` (tarea NO documental) → asignados."""
    return _push(
        db,
        _user_ids(recipients, exclude=actor_id),
        type=TYPE_TASK_WORKFLOW,
        title=f"Acción en tarea: {action}",
        body=getattr(task, "description", None),
        url=_task_url(task),
        data={**_task_data(task), "action": action},
    )


def notify_document_rejected(
    db: Session,
    document: Any,
    author_id: Optional[int],
    *,
    reason: Optional[str] = None,
) -> int:
    """7. Rechazo de documento → autor."""
    return _push(
        db,
        _user_ids([author_id]),
        type=TYPE_DOCUMENT_REJECTED,
        title="Tu documento fue rechazado",
        body=f"{document.title}" + (f" — {reason}" if reason else ""),
        url=URL_DOCUMENTS,
        data={"document_id": getattr(document, "id", None), "reason": reason},
    )


def notify_correction_task_created(db: Session, task: Any, author_id: Optional[int]) -> int:
    """8. Tarea de corrección creada tras un rechazo → autor del documento."""
    return _push(
        db,
        _user_ids([author_id]),
        type=TYPE_DOCUMENT_CORRECTION,
        title="Tienes un documento por corregir",
        body=getattr(task, "description", None),
        url=URL_DASHBOARD,
        data=_task_data(task),
    )


def notify_step_advanced(
    db: Session,
    document: Any,
    step: Any,
    recipients: Iterable[Any],
) -> int:
    """9. Avance de paso → validadores del paso siguiente."""
    return _push(
        db,
        _user_ids(recipients),
        type=TYPE_STEP_ADVANCED,
        title="Documento pendiente de tu validación",
        body=f"{document.title} — paso: {getattr(step, 'name', '—')}",
        url=URL_DASHBOARD,
        data={
            "document_id": getattr(document, "id", None),
            "flow_step_id": getattr(step, "id", None),
        },
    )


def notify_document_approved(db: Session, document: Any, author_id: Optional[int]) -> int:
    """10. Documento aprobado (ya no hay paso siguiente) → autor."""
    return _push(
        db,
        _user_ids([author_id]),
        type=TYPE_DOCUMENT_APPROVED,
        title="Tu documento fue aprobado",
        body=getattr(document, "title", None),
        url=URL_DOCUMENTS,
        data={"document_id": getattr(document, "id", None)},
    )

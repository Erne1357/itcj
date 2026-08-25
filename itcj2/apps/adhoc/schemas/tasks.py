"""Schemas Pydantic v2 y serializadores del dominio de **tareas**.

Dos mitades:

* **Entrada** — ``TaskBulkCreate`` / ``TaskUpdate`` / ``TaskAssigneesUpdate`` /
  ``TaskOverdueNotificationsUpdate`` / ``TaskWorkflowActionRequest``. Todas
  heredan de :class:`~itcj2.apps.adhoc.schemas.common.AdhocSchema`, así que el
  ``""`` de los ``<select>`` y de los ``<input type="date">`` vacíos se coacciona
  a ``None`` antes de la validación de tipo (plan §2.8).
* **Salida** — las funciones ``serialize_*``. Son puras (no tocan la sesión) y
  asumen que el service ya hizo el *eager loading*; el legacy serializaba dentro
  del endpoint con relaciones lazy y disparaba un N+1 por tarea y por comentario.

Nota sobre ``accion`` de ``POST /tasks/{id}/workflow-action``: **no** se declara
como ``Literal``. El vocabulario es cerrado, pero no tiene ``CheckConstraint``
detrás (no se persiste), y el plan §10.b exige **400** para una acción
desconocida — un ``Literal`` daría 422 de Pydantic. La validación vive en
``task_workflow_service``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import AliasChoices, Field, field_validator

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    OptStr,
    PriorityField,
    blank_to_default,
)
from itcj2.apps.adhoc.utils.constants import (
    PRIORITY_DEFAULT,
    TASK_STATUS_DEFAULT,
    Priority,
    TaskParentType,
    TaskStatus,
)

__all__ = [
    "TaskStatusField",
    "TaskCreateItem",
    "TaskBulkCreate",
    "TaskUpdate",
    "TaskAssigneesUpdate",
    "TaskOverdueNotificationsUpdate",
    "TaskWorkflowActionRequest",
    "TaskCommentCreate",
    "serialize_user",
    "parent_type_of",
    "serialize_task",
    "serialize_comment",
    "serialize_approval",
    "serialize_parent",
    "serialize_workflow_details",
]


#: ``adhoc_tasks.status`` es NOT NULL con CheckConstraint: un ``None`` entrante
#: (el legacy hacía ``request.form.get('status')`` a pelo) se resuelve al default.
TaskStatusField = Annotated[TaskStatus, blank_to_default(TASK_STATUS_DEFAULT)]


def _clean_ids(value: Any) -> list[int]:
    """Normaliza una lista heterogénea de ids a enteros positivos únicos.

    Los formularios del legacy mandan ``["", "3", "3", None]``; sin esto el
    ``""`` reventaría la coerción a ``int`` y el ``3`` duplicado provocaría un
    ``IntegrityError`` en la tabla de asociación.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    out: list[int] = []
    seen: set[int] = set()
    for raw in value:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


# ==========================================================================
# Entrada
# ==========================================================================

class TaskCreateItem(AdhocSchema):
    """Una fila del alta masiva (``POST /tasks``).

    ``assignee_ids`` acepta también el nombre ``responsible_ids`` del legacy,
    que mandaba **un** responsable por fila; aquí la relación es M2M de verdad.
    """

    description: str = Field(min_length=1, max_length=255)
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    priority: PriorityField = PRIORITY_DEFAULT  # type: ignore[assignment]
    status: TaskStatusField = TASK_STATUS_DEFAULT  # type: ignore[assignment]
    assignee_ids: list[int] = Field(
        default_factory=list,
        validation_alias=AliasChoices("assignee_ids", "responsible_ids", "user_ids"),
    )

    @field_validator("assignee_ids", mode="before")
    @classmethod
    def _normalize_assignees(cls, value: Any) -> list[int]:
        return _clean_ids(value)


class TaskBulkCreate(AdhocSchema):
    """Cuerpo de ``POST /tasks``: el padre + las filas.

    El legacy no validaba que ``parent_type`` y ``parent_id`` fueran un par
    coherente (si ``parent_id`` no era dígito creaba la tarea **huérfana**, hoy
    imposible por ``ck_adhoc_tasks_single_parent``). El service verifica además
    que el padre exista.
    """

    parent_type: TaskParentType
    parent_id: int = Field(gt=0)
    tasks: list[TaskCreateItem] = Field(min_length=1)


class TaskUpdate(AdhocSchema):
    """Cuerpo de ``PATCH /tasks/{id}``. Semántica de parche: solo lo enviado.

    ``changes()`` devuelve exactamente los campos presentes en el JSON, de modo
    que mandar ``{"status": "Completada"}`` no borra la descripción — el legacy
    asignaba ``description`` y ``status`` siempre, así que un formulario
    incompleto los ponía en ``None``.
    """

    description: OptStr = Field(default=None, max_length=255)
    status: Optional[TaskStatus] = None
    priority: Optional[Priority] = None
    start_date: Optional[date] = None
    due_date: Optional[date] = None

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class _UserIdsPayload(AdhocSchema):
    user_ids: list[int] = Field(default_factory=list)

    @field_validator("user_ids", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> list[int]:
        return _clean_ids(value)


class TaskAssigneesUpdate(_UserIdsPayload):
    """Cuerpo de ``PUT /tasks/{id}/assignees``: la lista COMPLETA de asignados."""


class TaskOverdueNotificationsUpdate(_UserIdsPayload):
    """Cuerpo de ``PUT /tasks/{id}/overdue-notifications``.

    La lista completa de quién queda marcado para el aviso de vencimiento; los
    ausentes se desmarcan.
    """


class TaskWorkflowActionRequest(AdhocSchema):
    """Cuerpo de ``POST /tasks/{id}/workflow-action``.

    ``accion`` es ``str`` a propósito (ver el docstring del módulo): el service
    valida contra ``WORKFLOW_ACTIONS`` y responde **400**, no 422.
    """

    accion: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("accion", "action"),
    )


class TaskCommentCreate(AdhocSchema):
    """Comentario de tarea. Solo se usa para validar el campo de texto.

    El endpoint es ``multipart/form-data`` (lleva adjunto), así que el ``comment``
    llega por ``Form(...)`` y este schema se aplica a mano en el service.
    ``adhoc_task_comments.comment`` es NOT NULL: el legacy no lo validaba y un
    comentario vacío terminaba en ``IntegrityError`` → 500.
    """

    comment: str = Field(min_length=1)


# ==========================================================================
# Salida
# ==========================================================================

def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def serialize_user(user: Any) -> Optional[dict]:
    """``{"id", "name"}`` — la forma mínima que consume el frontend."""
    if user is None:
        return None
    return {
        "id": getattr(user, "id", None),
        "name": getattr(user, "full_name", None) or "Sistema",
    }


def parent_type_of(task: Any) -> Optional[str]:
    """Discriminador polimórfico de la tarea.

    Las tres FK son mutuamente excluyentes por ``ck_adhoc_tasks_single_parent``,
    así que el orden de comprobación no puede producir ambigüedad (el legacy
    asumía la prioridad ``program > incident > document`` sin garantía ninguna).
    """
    if getattr(task, "incident_id", None):
        return "incident"
    if getattr(task, "program_id", None):
        return "program"
    if getattr(task, "document_id", None):
        return "document"
    return None


def _parent_of(task: Any) -> Any:
    kind = parent_type_of(task)
    if kind == "incident":
        return task.incident
    if kind == "program":
        return task.program
    if kind == "document":
        return task.document
    return None


def serialize_task(task: Any, *, with_parent: bool = False) -> dict:
    """Forma canónica de una tarea en la API.

    Asume ``selectinload`` de ``assignees`` y ``comments``; ``comments_count``
    saldría en un N+1 si el service no cargó la colección.
    """
    data = {
        "id": task.id,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "start_date": _iso(task.start_date),
        "due_date": _iso(task.due_date),
        "completed_at": _iso(task.completed_at),
        "created_by_id": task.created_by_id,
        "incident_id": task.incident_id,
        "program_id": task.program_id,
        "document_id": task.document_id,
        "flow_step_id": task.flow_step_id,
        "parent_type": parent_type_of(task),
        "assignees": [serialize_user(u) for u in (task.assignees or [])],
        "comments_count": len(task.comments or []),
        "created_at": _iso(task.created_at),
    }
    if with_parent:
        data["parent"] = serialize_parent(task)
    return data


def serialize_comment(comment: Any) -> dict:
    """Comentario con su autor y su adjunto (si lo tiene)."""
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "user_id": comment.user_id,
        "user": serialize_user(getattr(comment, "user", None)),
        "comment": comment.comment,
        "file_path": comment.file_path,
        "file_name": (comment.file_path or "").split("/")[-1] or None,
        "created_at": _iso(comment.created_at),
    }


def serialize_approval(approval: Any) -> dict:
    """Registro de ``adhoc_task_approvals`` — la tabla que el legacy no tenía."""
    return {
        "id": approval.id,
        "task_id": approval.task_id,
        "user_id": approval.user_id,
        "user": serialize_user(getattr(approval, "user", None)),
        "decision": approval.decision,
        "comment_id": approval.comment_id,
        "created_at": _iso(approval.created_at),
    }


def serialize_parent(task: Any) -> dict:
    """Datos del padre para el modal de workflow.

    Tres formas distintas según el tipo. El legacy accedía a ``parent.code`` /
    ``parent.version`` sin guarda cuando el padre era ``None``.
    """
    kind = parent_type_of(task)
    parent = _parent_of(task)

    if parent is None:
        return {"type": kind, "id": None, "title": None}

    if kind == "document":
        step = getattr(task, "flow_step", None) or getattr(parent, "current_step", None)
        return {
            "type": "document",
            "id": parent.id,
            "title": parent.title,
            "code": parent.code,
            "version": parent.version,
            "status": parent.status,
            "step_name": getattr(step, "name", None),
            "step_days": getattr(step, "days_limit", None),
            "author": serialize_user(getattr(parent, "author", None)),
            "has_file": bool(parent.file_url),
        }

    return {
        "type": kind,
        "id": parent.id,
        "title": parent.title,
        "folio": parent.folio,
        "status": parent.status,
        "area": getattr(getattr(parent, "area", None), "name", None),
        "process": getattr(getattr(parent, "process", None), "name", None),
        "responsible": serialize_user(getattr(parent, "responsible", None)),
        "commitment_date": _iso(getattr(parent, "commitment_date", None)),
        "real_date": _iso(getattr(parent, "real_date", None)),
    }


def serialize_workflow_details(task: Any) -> dict:
    """Payload de ``GET /tasks/{id}/workflow``: tarea + padre + comentarios + aprobaciones."""
    return {
        "task": serialize_task(task),
        "parent": serialize_parent(task),
        "comments": [serialize_comment(c) for c in (task.comments or [])],
        "approvals": [serialize_approval(a) for a in (task.approvals or [])],
    }

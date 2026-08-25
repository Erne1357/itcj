"""Schemas Pydantic v2 de documentos y flujos de aprobación (Adhoc / Calidad).

Dos bloques:

* **Entrada** — lo que valida la API antes de tocar el ORM. Todo campo con
  ``CheckConstraint`` detrás se declara con el ``Literal`` de
  ``utils/constants.py`` (regla 1 del plan §2.8), y los ``""`` del ``<select>``
  placeholder se coaccionan a ``None`` heredando de :class:`AdhocSchema`
  (regla 2). Los campos ``NOT NULL`` con default (``version``, ``days_limit``)
  usan ``blank_to_default`` porque un ``""`` entrante los dejaría en ``None`` y
  ``None`` no satisface el tipo (regla 4).
* **Salida** — funciones puras ``*_out`` que convierten una fila del ORM en el
  dict que viaja dentro de ``{"success": True, "data": ...}``. Viven aquí, y no
  en el service, para que ``api/documents.py`` y ``api/flows.py`` compartan
  exactamente el mismo contrato sin importarse entre sí.

Nota sobre ``StartFlowIn.flow_id``: es **opcional a propósito**. El plan §10.b
paso 1 exige responder **400** ("Debe enviar flow_id.") cuando falta, no el 422
que produciría un campo requerido de Pydantic; la validación de presencia la
hace ``document_flow_service.start_flow``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import Field

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    OptInt,
    OptStr,
    blank_to_default,
)
from itcj2.apps.adhoc.utils.constants import DocumentStatus

__all__ = [
    # Entrada — documentos
    "DocumentCreate",
    "DocumentUpdate",
    "DocumentFilters",
    "StartFlowIn",
    # Entrada — flujos y pasos
    "FlowCreate",
    "FlowUpdate",
    "FlowStepIn",
    "FlowStepsUpsert",
    "StepUsersIn",
    # Salida
    "document_out",
    "flow_out",
    "step_out",
    "step_details_out",
    "user_brief",
]


# ==========================================================================
# Entrada — documentos
# ==========================================================================

class DocumentCreate(AdhocSchema):
    """Una fila del alta masiva de ``POST /documents`` (multipart).

    El legacy (``api_docs.save_documents``) exigía ``code`` **y** ``title`` y
    descartaba la fila en silencio si faltaba alguno. Aquí ``title`` es
    obligatorio de verdad (422 si falta) y ``code`` es opcional, como declara la
    columna (``nullable=True``).
    """

    code: Annotated[Optional[str], Field(max_length=50)] = None
    title: str = Field(min_length=1, max_length=200)
    version: Annotated[str, blank_to_default("1.0"), Field(max_length=10)] = "1.0"
    notes: OptStr = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None


class DocumentUpdate(AdhocSchema):
    """``PATCH /documents/{id}``. Se aplica con ``model_dump(exclude_unset=True)``.

    Un ``""`` entrante se vuelve ``None`` (limpia la columna); por eso ``title``
    es ``Optional`` aquí y su vacío lo rechaza el service con un 400 legible en
    vez de dejar un documento sin título.
    """

    code: Annotated[Optional[str], Field(max_length=50)] = None
    title: Annotated[Optional[str], Field(max_length=200)] = None
    version: Annotated[Optional[str], Field(max_length=10)] = None
    status: Optional[DocumentStatus] = None
    notes: OptStr = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None


class DocumentFilters(AdhocSchema):
    """Filtros de ``GET /documents``. Se construye desde los query params.

    El endpoint los recibe como strings crudos y arma este modelo dentro de un
    ``try``: un ``status`` inventado tiene que ser un 400 legible, no un 500 por
    ``ValidationError`` suelta.
    """

    q: OptStr = None
    status: Optional[DocumentStatus] = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    classification_id: OptInt = None
    flow_id: OptInt = None
    author_id: OptInt = None


class StartFlowIn(AdhocSchema):
    """``POST /documents/{id}/start-flow``. Ver nota del docstring del módulo."""

    flow_id: OptInt = None


# ==========================================================================
# Entrada — flujos de aprobación y pasos
# ==========================================================================

class FlowCreate(AdhocSchema):
    name: str = Field(min_length=1, max_length=100)
    description: Annotated[Optional[str], Field(max_length=255)] = None


class FlowUpdate(AdhocSchema):
    name: Annotated[Optional[str], Field(max_length=100)] = None
    description: Annotated[Optional[str], Field(max_length=255)] = None


class FlowStepIn(AdhocSchema):
    """Un paso del ``PUT /approval-flows/{id}/steps``.

    ``step_order`` es la **clave del upsert**: si se omite, el service asigna
    ``índice + 1``. Mandarlo explícitamente permite reordenar el payload sin
    que los pasos existentes se borren y se recreen con ids nuevos (el bug #3
    del legacy, que dejaba ``adhoc_tasks.flow_step_id`` y
    ``adhoc_documents.current_step_id`` apuntando a filas muertas).
    """

    name: str = Field(min_length=1, max_length=100)
    days_limit: Annotated[int, blank_to_default(3), Field(ge=1, le=365)] = 3
    step_order: OptInt = None


class FlowStepsUpsert(AdhocSchema):
    steps: list[FlowStepIn] = Field(default_factory=list)


class StepUsersIn(AdhocSchema):
    """Body de ``PUT /steps/{id}/validators`` y ``/steps/{id}/overdue-notifications``."""

    user_ids: list[int] = Field(default_factory=list)


# ==========================================================================
# Salida
# ==========================================================================

def _iso(value: Any) -> Optional[str]:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return None


def user_brief(user: Any) -> Optional[dict]:
    """``{"id", "name", "email"}`` de un ``core_users`` (o ``None``)."""
    if user is None:
        return None
    name = getattr(user, "full_name", None) or getattr(user, "username", None)
    return {
        "id": getattr(user, "id", None),
        "name": name or "Sin nombre",
        "email": getattr(user, "email", None),
    }


def _named(obj: Any, *extra: str) -> Optional[dict]:
    if obj is None:
        return None
    out = {"id": getattr(obj, "id", None), "name": getattr(obj, "name", None)}
    for field in extra:
        out[field] = getattr(obj, field, None)
    return out


def document_out(doc: Any, *, detail: bool = False) -> dict:
    """Fila de documento para la API.

    ``detail=True`` añade el flujo y el paso actual resueltos; el listado los
    omite para no forzar dos joins más en cada página.
    """
    data = {
        "id": doc.id,
        "code": doc.code,
        "title": doc.title,
        "version": doc.version,
        "status": doc.status,
        "notes": doc.notes,
        "approval_date": _iso(doc.approval_date),
        "file_url": doc.file_url,
        "has_file": bool(doc.file_url),
        "category": _named(doc.category),
        "area": _named(doc.area, "color"),
        "process": _named(doc.process, "color"),
        "classification": _named(doc.classification),
        "author": user_brief(doc.author),
        "flow_id": doc.flow_id,
        "current_step_id": doc.current_step_id,
        "created_at": _iso(doc.created_at),
        "updated_at": _iso(doc.updated_at),
    }
    if detail:
        data["flow"] = _named(doc.flow, "description")
        data["current_step"] = step_out(doc.current_step) if doc.current_step else None
    return data


def step_out(step: Any, *, assignee_count: Optional[int] = None) -> dict:
    out = {
        "id": step.id,
        "flow_id": step.flow_id,
        "name": step.name,
        "days_limit": step.days_limit,
        "step_order": step.step_order,
    }
    if assignee_count is not None:
        out["assignee_count"] = assignee_count
    return out


def flow_out(flow: Any, *, step_count: Optional[int] = None) -> dict:
    out = {
        "id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "created_at": _iso(flow.created_at),
        "updated_at": _iso(flow.updated_at),
    }
    if step_count is not None:
        out["step_count"] = step_count
    return out


def step_details_out(step: Any, assigned: list, notify_ids: set) -> dict:
    """``GET /approval-flows/steps/{id}`` — validadores y quién recibe la alerta.

    Espeja la forma del legacy (``assigned`` / ``notify``) porque la UI del
    modal de asignación la consume tal cual; lo que cambia es el sobre
    (``{"success": True, "data": {...}}``) y que ahora exige permiso.
    """
    return {
        "step": step_out(step),
        "assigned": [user_brief(u) for u in assigned],
        "notify": [user_brief(u) for u in assigned if getattr(u, "id", None) in notify_ids],
    }

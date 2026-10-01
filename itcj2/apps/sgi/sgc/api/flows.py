"""API v2 de flujos de aprobación y sus pasos (Sgc / Calidad).

Monta en ``/api/sgi/v2/sgc/approval-flows`` — el prefijo lo pone el router padre.
Los endpoints de **paso** cuelgan de este mismo router (plan §3, "Nota de
prefijos"), así que se declaran como ``/steps/{step_id}`` y la URL final queda
``/api/sgi/v2/sgc/approval-flows/steps/{step_id}``.

Superficie:

===============================================  ===============================
Endpoint                                         Permiso
===============================================  ===============================
``GET    ""``                                    ``sgi.sgc.flows.api.read``
``POST   ""``                                    ``sgi.sgc.flows.api.create``
``PATCH  /{flow_id}``                            ``sgi.sgc.flows.api.update``
``DELETE /{flow_id}``                            ``sgi.sgc.flows.api.delete``
``GET    /{flow_id}/steps``                      ``sgi.sgc.flows.api.read``
``PUT    /{flow_id}/steps``                      ``sgi.sgc.flows.api.update``
``GET    /steps/{step_id}``                      ``sgi.sgc.flows.api.read``
``PUT    /steps/{step_id}/validators``           ``sgi.sgc.flows.api.assign``
``PUT    /steps/{step_id}/overdue-notifications``  ``sgi.sgc.flows.api.assign``
===============================================  ===============================

El ``PUT /{flow_id}/steps`` es un **upsert por ``step_order``** (nunca un
delete-all) y devuelve **409** si hay documentos en revisión con ese flujo o si
el paso que habría que borrar está referenciado por tareas o documentos. Lo
mismo el ``DELETE /{flow_id}``: los pasos caen en cascada, pero
``sgc_tasks.flow_step_id`` y ``sgc_documents.current_step_id`` son RESTRICT.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from itcj2.apps.sgi.sgc.schemas.documents import (
    FlowCreate,
    FlowStepsUpsert,
    FlowUpdate,
    StepUsersIn,
)
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["sgi-flows"])
logger = logging.getLogger(__name__)


@contextmanager
def _domain_errors():
    """``LookupError`` → 404 · ``SgcConflict`` → 409 · ``ValueError`` → 400."""
    from itcj2.apps.sgi.sgc.services.document_service import SgcConflict

    try:
        yield
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "No encontrado") from exc
    except SgcConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ==========================================================================
# Pasos — se declaran ANTES que las rutas /{flow_id}/... por claridad de lectura
# (no hay ambigüedad real: `flow_id` es `int` y "steps" nunca casa).
# ==========================================================================

@router.get("/steps/{step_id}")
def get_step_details(
    request: Request,
    step_id: int,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.read"]),
    db: DbSession = None,
):
    """Validadores del paso y cuáles reciben la alerta de atraso."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_item
    from itcj2.apps.sgi.sgc.schemas.documents import step_details_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        step, assigned, notify_ids = SgcDocumentFlowService.get_step_details(db, step_id)
    return ok_item(step_details_out(step, assigned, notify_ids))


@router.put("/steps/{step_id}/validators")
def set_step_validators(
    request: Request,
    step_id: int,
    payload: StepUsersIn,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.assign"]),
    db: DbSession = None,
):
    """Reemplaza los validadores del paso **preservando ``notify_on_overdue``**.

    El legacy reasignaba la colección entera y borraba el flag de todos sin
    avisar; aquí solo se tocan las filas que entran o salen.
    """
    from itcj2.apps.sgi.sgc.schemas.common import ok_message
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        SgcDocumentFlowService.set_step_validators(db, step_id, payload.user_ids)
    return ok_message("Validadores asignados correctamente al paso.")


@router.put("/steps/{step_id}/overdue-notifications")
def set_step_overdue_notifications(
    request: Request,
    step_id: int,
    payload: StepUsersIn,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.assign"]),
    db: DbSession = None,
):
    """Marca quién recibe la alerta de atraso del paso.

    Efecto heredado del legacy que se conserva a propósito: marcar a alguien que
    todavía no era validador **lo asigna** al paso.
    """
    from itcj2.apps.sgi.sgc.schemas.common import ok_message
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        SgcDocumentFlowService.set_step_overdue_notifications(
            db, step_id, payload.user_ids,
        )
    return ok_message("Notificaciones de atraso configuradas.")


# ==========================================================================
# Flujos
# ==========================================================================

@router.get("")
def list_flows(
    request: Request,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.read"]),
    db: DbSession = None,
):
    """Todos los flujos con su número de pasos (sin N+1)."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_list
    from itcj2.apps.sgi.sgc.schemas.documents import flow_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    flows = SgcDocumentFlowService.list_flows(db)
    return ok_list([flow_out(f, step_count=len(f.steps)) for f in flows])


@router.post("")
def create_flow(
    request: Request,
    payload: FlowCreate,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.create"]),
    db: DbSession = None,
):
    """Crea un flujo de aprobación (sin pasos; se cargan con el ``PUT``)."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_item
    from itcj2.apps.sgi.sgc.schemas.documents import flow_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        flow = SgcDocumentFlowService.create_flow(db, payload)
    return ok_item(flow_out(flow, step_count=0))


@router.patch("/{flow_id}")
def update_flow(
    request: Request,
    flow_id: int,
    payload: FlowUpdate,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.update"]),
    db: DbSession = None,
):
    """Renombra el flujo o cambia su descripción."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_item
    from itcj2.apps.sgi.sgc.schemas.documents import flow_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        flow = SgcDocumentFlowService.update_flow(db, flow_id, payload)
    return ok_item(flow_out(flow, step_count=len(flow.steps)))


@router.delete("/{flow_id}")
def delete_flow(
    request: Request,
    flow_id: int,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.delete"]),
    db: DbSession = None,
):
    """Elimina el flujo y sus pasos. **409** si algún documento o tarea los usa."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_message
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        SgcDocumentFlowService.delete_flow(db, flow_id)
    return ok_message("Flujo eliminado correctamente")


@router.get("/{flow_id}/steps")
def list_flow_steps(
    request: Request,
    flow_id: int,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.read"]),
    db: DbSession = None,
):
    """Pasos del flujo ordenados por ``step_order``, con cuántos validadores tienen."""
    from itcj2.apps.sgi.sgc.schemas.common import ok_list
    from itcj2.apps.sgi.sgc.schemas.documents import step_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        steps = SgcDocumentFlowService.list_steps(db, flow_id)
    return ok_list([step_out(s, assignee_count=len(s.assignees)) for s in steps])


@router.put("/{flow_id}/steps")
def upsert_flow_steps(
    request: Request,
    flow_id: int,
    payload: FlowStepsUpsert,
    user: dict = require_perms("sgi", ["sgi.sgc.flows.api.update"]),
    db: DbSession = None,
):
    """Sincroniza los pasos del flujo por ``step_order`` (upsert, **no** delete-all).

    Bug #3 del legacy: borraba todos los pasos y los recreaba con ids nuevos,
    dejando ``sgc_tasks.flow_step_id`` y ``sgc_documents.current_step_id``
    apuntando a filas muertas. Devuelve **409** si hay documentos en revisión con
    este flujo, o si un paso a eliminar está referenciado.
    """
    from itcj2.apps.sgi.sgc.schemas.common import ok_list
    from itcj2.apps.sgi.sgc.schemas.documents import step_out
    from itcj2.apps.sgi.sgc.services.document_flow_service import SgcDocumentFlowService

    with _domain_errors():
        steps = SgcDocumentFlowService.upsert_flow_steps(db, flow_id, payload.steps)
    return ok_list([step_out(s) for s in steps])

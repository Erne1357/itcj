"""Páginas de **incidencias** de Calidad (+ tareas y asignación de usuarios).

Cuatro rutas (plan §4). El router no lleva prefijo propio: se lo pone
``pages/router.py`` en la fase de cableado (``prefix="/adhoc"``).

======================================  =====================================
URL final                               Permiso de página
======================================  =====================================
``/adhoc/incidencias``                  ``adhoc.incidents.page.list``
``/adhoc/incidencias/categorias``       ``adhoc.incident_categories.page.list``
``/adhoc/incidencias/{id}/tareas``      ``adhoc.tasks.page.list``
``/adhoc/asignaciones``                 ``adhoc.tasks.page.assign``
======================================  =====================================

Qué cambia respecto del legacy (``routes/pages/incidents.py``):

* **Autorización real.** El legacy no tenía *ninguna*: `@login_required` estaba
  puesto encima de `@route`, donde no protege nada (bug #25).
* **La página ya no trae los datos.** El legacy mandaba `Incident.query.all()`
  a la plantilla y filtraba en el DOM. Aquí la tabla la puebla
  ``GET /api/adhoc/v2/incidents`` con filtros y paginación de servidor; la
  página solo aporta catálogos, usuarios y URLs dentro del bloque
  ``page_data_script()`` (``|tojson``), nunca como markup.
* **`/asignaciones` consolida dos rutas** (`/extintor/usuarios` y
  `/calendario/usuarios`) que renderizaban el mismo template con contextos
  distintos —una pasaba `areas` que la plantilla no usaba, la otra no resolvía
  los ya notificados—. Aquí es una sola vista parametrizada por querystring.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

router = APIRouter()

__all__ = ["router"]

#: Permisos de escritura que solo sirven para ocultar botones (el gate real está
#: en ``require_perms`` de cada endpoint de la API).
#: Los tres de archivos son un delta posterior al alta de la app —ver
#: ``cli/adhoc.py::grant_incident_files_command``—: la incidencia se construyó
#: asumiendo que no llevaba adjuntos y el SGC legacy migró 351 con ella.
_WRITE_PERMS = (
    "adhoc.incidents.api.create",
    "adhoc.incidents.api.update",
    "adhoc.incidents.api.delete",
    "adhoc.incidents.api.files.create",
    "adhoc.incidents.api.files.delete",
    "adhoc.incidents.api.files.download",
)

_CAT_PERMS = (
    "adhoc.incident_categories.api.create",
    "adhoc.incident_categories.api.update",
    "adhoc.incident_categories.api.delete",
)

#: Columnas de la tabla, en el mismo orden que las pinta ``js/work/work-items.js``.
#: La ``key`` es el contrato con el JS (``data-adhoc-cell``) y con
#: ``shared/table-filter.js``: nunca un índice, que es lo que desalineaba los
#: filtros del legacy en cuanto se añadía un ``<td>``.
_COLUMNS = [
    {"key": "folio", "label": "Folio"},
    {"key": "title", "label": "Incidencia"},
    {"key": "category", "label": "Categoría"},
    {"key": "area", "label": "Área"},
    {"key": "process", "label": "Proceso"},
    {"key": "responsible", "label": "Responsable"},
    {"key": "start_date", "label": "Alta"},
    {"key": "commitment_date", "label": "Compromiso"},
    {"key": "real_date", "label": "Real"},
    {"key": "priority", "label": "Prioridad"},
    {"key": "status", "label": "Estatus"},
    {"key": "tasks", "label": "Tareas", "align": "center"},
    {"key": "actions", "label": "Acciones", "align": "end"},
]

#: Nombre lógico del filtro (el ``data-adhoc-param`` del template) → parámetro
#: real de ``GET /api/adhoc/v2/incidents``. Los que no aparecen se mandan tal cual.
_QUERY_MAP = {
    "search": "q",
    "date_from": "commitment_from",
    "date_to": "commitment_to",
}


# ==========================================================================
# /adhoc/incidencias
# ==========================================================================

@router.get("/incidencias")
def incidents_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.incidents.page.list"])),
    db: Session = Depends(get_db),
):
    """Listado de incidencias con alta masiva, edición y filtros de servidor."""
    from itcj2.apps.adhoc.pages._work_context import (
        assignable_users,
        catalog_options,
        granted,
        page_context,
    )
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.utils.constants import INCIDENT_STATUSES, PRIORITIES

    catalogos = catalog_options(db, category_model="AdhocIncidentCategory")
    permisos = granted(db, user, _WRITE_PERMS)
    ctx = page_context(db, user)

    page_data = {
        "kind": "incident",
        "api": "/api/adhoc/v2/incidents",
        "table_id": "adhoc-table-incidents",
        "tasks_url": "/adhoc/incidencias/{id}/tareas",
        "statuses": list(INCIDENT_STATUSES),
        "priorities": list(PRIORITIES),
        "users": assignable_users(db),
        "today": ctx["today"],
        "per_page": 25,
        "query_map": _QUERY_MAP,
        "can": {
            "create": permisos["adhoc.incidents.api.create"],
            "update": permisos["adhoc.incidents.api.update"],
            "delete": permisos["adhoc.incidents.api.delete"],
            # "Duplicar" sigue sin existir para incidencias (solo tiene sentido
            # para un evento repetible del programa de trabajo).
            "duplicate": False,
            "files": permisos["adhoc.incidents.api.files.download"],
            "files_create": permisos["adhoc.incidents.api.files.create"],
            "files_delete": permisos["adhoc.incidents.api.files.delete"],
        },
        "labels": {
            "singular": "incidencia",
            "plural": "incidencias",
            "title_field": "Título de la incidencia",
            "date_start": "Fecha de alta",
            "date_commitment": "Fecha compromiso",
            "date_real": "Fecha real de cierre",
            "description": "Descripción detallada",
        },
        **catalogos,
    }

    return render_adhoc(
        request,
        "adhoc/incidents/incidents.html",
        {
            **ctx,
            "page_data": page_data,
            "columns": _COLUMNS,
            # Textos e iconos del legacy (`incidents/incidents.html`): título
            # "Gestión de Incidencias" con el extintor, sin subtítulo.
            "page_title": "Gestión de Incidencias",
            "page_subtitle": None,
            "page_icon": "fa-solid fa-fire-extinguisher",
            "back_url": "/adhoc/panel",
            "back_label": "Volver al Panel",
            "new_label": "Añadir Nuevas Incidencias",
            "empty_message": "No hay incidencias que coincidan con el filtro.",
            "empty_icon": "fa-solid fa-fire-extinguisher",
            "can_create": page_data["can"]["create"],
            "categories_url": "/adhoc/incidencias/categorias",
            "can_manage_categories": True,
        },
    )


# ==========================================================================
# /adhoc/incidencias/categorias
# ==========================================================================

@router.get("/incidencias/categorias")
def incident_categories_page(
    request: Request,
    user: dict = Depends(
        require_page_app("adhoc", perms=["adhoc.incident_categories.page.list"])
    ),
    db: Session = Depends(get_db),
):
    """Catálogo de categorías de incidencia (macro ``catalog_page`` + catalog-crud.js)."""
    from itcj2.apps.adhoc.pages._work_context import granted, page_context
    from itcj2.apps.adhoc.pages.render import render_adhoc

    permisos = granted(db, user, _CAT_PERMS)

    return render_adhoc(
        request,
        "adhoc/incidents/categories.html",
        {
            **page_context(db, user),
            "can_create": permisos["adhoc.incident_categories.api.create"],
            "can_update": permisos["adhoc.incident_categories.api.update"],
            "can_delete": permisos["adhoc.incident_categories.api.delete"],
        },
    )


# ==========================================================================
# /adhoc/incidencias/{id}/tareas
# ==========================================================================

@router.get("/incidencias/{incident_id}/tareas")
def incident_tasks_page(
    request: Request,
    incident_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.tasks.page.list"])),
    db: Session = Depends(get_db),
):
    """Tareas de una incidencia. Mismo template que las de un evento de programa."""
    from itcj2.apps.adhoc.pages._work_context import tasks_page_context
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.services.incident_service import IncidentService

    incidencia = IncidentService.get(db, incident_id)
    if incidencia is None:
        # 404 real. El legacy usaba get_or_404 dentro de un try/except Exception
        # que lo convertía en cualquier otra cosa.
        raise HTTPException(status_code=404, detail=f"No existe la incidencia {incident_id}")

    return render_adhoc(
        request,
        "adhoc/work/tasks.html",
        tasks_page_context(
            db,
            user,
            parent=incidencia,
            parent_type="incident",
            back_url="/adhoc/incidencias",
            parent_label="incidencia",
        ),
    )


# ==========================================================================
# /adhoc/asignaciones
# ==========================================================================

#: Las cuatro acciones que consolida la pantalla, con el endpoint que ataca cada
#: una y de dónde sale la selección inicial. ``assign``/``notify`` operan sobre
#: una TAREA; ``step_assign``/``notify_step`` sobre un PASO de flujo de
#: aprobación (el legacy llegaba aquí desde la configuración de flujos).
_ASSIGN_ACTIONS = {
    "assign": {
        "target": "task",
        "title": "Asignar Usuarios",
        "icon": "fa-solid fa-users-gear",
        "back_label": "Volver a Tareas",
        "subtitle": "Marca a quién le toca esta tarea. El orden de selección es el orden de atención.",
        "endpoint": "/api/adhoc/v2/tasks/{id}/assignees",
        "method": "PUT",
    },
    "notify": {
        "target": "task",
        "title": "Notificar Atraso",
        "icon": "fa-solid fa-bell",
        "back_label": "Volver a Tareas",
        "subtitle": (
            "Marca a quién avisar del vencimiento. Ojo: guardar escala la tarea a "
            "prioridad Urgente, y quien no fuera responsable queda asignado."
        ),
        "endpoint": "/api/adhoc/v2/tasks/{id}/overdue-notifications",
        "method": "PUT",
    },
    "step_assign": {
        "target": "step",
        "title": "Asignar Validadores al Paso",
        "icon": "fa-solid fa-users-viewfinder",
        "back_label": "Volver a Config. de Flujo",
        "subtitle": "El orden en que selecciones a los validadores es el orden secuencial de aprobación.",
        "endpoint": "/api/adhoc/v2/approval-flows/steps/{id}/validators",
        "method": "PUT",
    },
    "notify_step": {
        "target": "step",
        "title": "Notificar Validadores Atrasados",
        "icon": "fa-solid fa-user-clock",
        "back_label": "Volver a Config. de Flujo",
        "subtitle": "Marca a los validadores que recibirán la alerta de atraso de este paso.",
        "endpoint": "/api/adhoc/v2/approval-flows/steps/{id}/overdue-notifications",
        "method": "PUT",
    },
}


@router.get("/asignaciones")
def assignments_page(
    request: Request,
    action: str = Query("assign", description="assign | notify | step_assign | notify_step"),
    task_id: int | None = Query(None, gt=0),
    step_id: int | None = Query(None, gt=0),
    return_to: str | None = Query(None),
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.tasks.page.assign"])),
    db: Session = Depends(get_db),
):
    """Selector de usuarios para una tarea o para un paso de flujo.

    Consolida ``/extintor/usuarios`` y ``/calendario/usuarios`` del legacy, que
    eran **el mismo template con dos rutas** y dos contextos incompatibles.

    El destino sale de ``?action=``; el id, de ``?task_id=`` o ``?step_id=``. Si
    falta el id la página responde **400** en vez de renderizar un formulario
    que al guardar habría dicho "Error: No se detectó el origen" (lo que hacía
    el JS del legacy, ya con el usuario habiendo elegido a diez personas).
    """
    from itcj2.apps.adhoc.pages._work_context import (
        assignable_users,
        page_context,
        safe_return_to,
    )
    from itcj2.apps.adhoc.pages.render import render_adhoc

    config = _ASSIGN_ACTIONS.get(action)
    if config is None:
        raise HTTPException(
            status_code=400,
            detail=f"Acción de asignación inválida: {action!r}. "
                   f"Válidas: {', '.join(sorted(_ASSIGN_ACTIONS))}",
        )

    if config["target"] == "task":
        target_id, selected, fallback_back = _task_target(db, action, task_id)
    else:
        target_id, selected, fallback_back = _step_target(db, action, step_id)

    page_data = {
        "action": action,
        "target": config["target"],
        "target_id": target_id,
        "endpoint": config["endpoint"].format(id=target_id),
        "method": config["method"],
        "users": assignable_users(db),
        "selected_ids": selected,
        "return_to": safe_return_to(return_to, fallback_back),
        "labels": {"title": config["title"]},
    }

    return render_adhoc(
        request,
        "adhoc/work/assignments.html",
        {
            **page_context(db, user),
            "page_data": page_data,
            "page_title": config["title"],
            "page_subtitle": config["subtitle"],
            "page_icon": config["icon"],
            "back_url": page_data["return_to"],
            "back_label": config["back_label"],
        },
    )


def _task_target(db: Session, action: str, task_id: int | None) -> tuple[int, list[int], str]:
    """Resuelve la tarea destino y su selección actual."""
    from itcj2.apps.adhoc.models import AdhocTask
    from itcj2.apps.adhoc.pages._work_context import (
        task_assignee_ids,
        task_notified_ids,
    )

    if not task_id:
        raise HTTPException(
            status_code=400,
            detail=f"La acción '{action}' necesita ?task_id= en la URL",
        )

    task = db.get(AdhocTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"No existe la tarea {task_id}")

    selected = (
        task_notified_ids(db, task.id) if action == "notify"
        else task_assignee_ids(db, task.id)
    )

    if task.incident_id:
        volver = f"/adhoc/incidencias/{task.incident_id}/tareas"
    elif task.program_id:
        volver = f"/adhoc/programas/{task.program_id}/tareas"
    else:
        volver = "/adhoc/dashboard"

    return task.id, selected, volver


def _step_target(db: Session, action: str, step_id: int | None) -> tuple[int, list[int], str]:
    """Resuelve el paso de flujo destino y su selección actual."""
    from itcj2.apps.adhoc.services.document_flow_service import AdhocDocumentFlowService

    if not step_id:
        raise HTTPException(
            status_code=400,
            detail=f"La acción '{action}' necesita ?step_id= en la URL",
        )

    try:
        step, validadores, notify_ids = AdhocDocumentFlowService.get_step_details(db, step_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if action == "notify_step":
        selected = [u.id for u in validadores if u.id in notify_ids]
    else:
        selected = [u.id for u in validadores]

    return step.id, selected, f"/adhoc/documentos/flujos/{step.flow_id}/pasos"

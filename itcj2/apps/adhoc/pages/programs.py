"""Páginas de **eventos del programa de trabajo** de Calidad (+ sus tareas).

**Vocabulario (plan §2.6):** "programa" aquí es un evento del programa de
trabajo del SGC, **no** una carrera académica (``core_programs``).

Tres rutas (plan §4). El router no lleva prefijo propio: se lo pone
``pages/router.py`` en la fase de cableado (``prefix="/adhoc"``).

=====================================  =====================================
URL final                              Permiso de página
=====================================  =====================================
``/adhoc/programas``                   ``adhoc.programs.page.list``
``/adhoc/programas/categorias``        ``adhoc.program_categories.page.list``
``/adhoc/programas/{id}/tareas``       ``adhoc.tasks.page.list``
=====================================  =====================================

Esta pantalla y la de incidencias son **el mismo formulario al 90 %** (en el
legacy, ``programs.js`` era una copia de ``incidents.js`` con los textos
cambiados y una regresión propia: su filtrado usaba ``cells[index]`` en vez de
``cells[index + 1]``). Aquí las dos comparten el template
``adhoc/work/_work_item_page.html`` y el módulo ``js/work/work-items.js``; lo
único propio de programas es lo que incidencias no tiene: **ubicación**,
**adjuntos** y **duplicar**.

La página de tareas es literalmente la misma que la de incidencias
(``adhoc/work/tasks.html``, parametrizada por ``parent_type``), como en el
legacy — pero con un solo contexto en vez de dos divergentes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_app

logger = logging.getLogger(__name__)

router = APIRouter()

__all__ = ["router"]

_WRITE_PERMS = (
    "adhoc.programs.api.create",
    "adhoc.programs.api.update",
    "adhoc.programs.api.delete",
    "adhoc.programs.api.duplicate",
    "adhoc.programs.api.files.create",
    "adhoc.programs.api.files.delete",
    "adhoc.programs.api.files.download",
)

_CAT_PERMS = (
    "adhoc.program_categories.api.create",
    "adhoc.program_categories.api.update",
    "adhoc.program_categories.api.delete",
)

#: Columnas de la tabla. Respecto de incidencias añade ``location`` y
#: ``files``; el resto es el mismo contrato de ``key`` → ``data-adhoc-cell``.
#:
#: ``responsible`` va en el mismo hueco que en incidencias (detrás de
#: ``process``) y no es cosmético: la fila de filtros de
#: ``work/_work_item_page.html`` pinta cada control **en su columna**, así que
#: sin la columna no había dónde pintar el ``<select>`` de responsable y el
#: filtro no existía en la pantalla —aunque ``ProgramEventFilters`` y
#: ``list_events`` lo soportan desde el primer día—. Era el único filtro de la
#: API de eventos que no se podía usar, y justo el que contesta la pregunta con
#: la que se abre esta pantalla: "¿qué me toca a mí?".
_COLUMNS = [
    {"key": "folio", "label": "Folio"},
    {"key": "title", "label": "Evento"},
    {"key": "category", "label": "Categoría"},
    {"key": "area", "label": "Área"},
    {"key": "process", "label": "Proceso"},
    {"key": "responsible", "label": "Responsable"},
    {"key": "location", "label": "Ubicación"},
    {"key": "start_date", "label": "Inicio"},
    {"key": "commitment_date", "label": "Cierre"},
    {"key": "real_date", "label": "Real"},
    {"key": "priority", "label": "Prioridad"},
    {"key": "status", "label": "Estatus"},
    {"key": "files", "label": "Archivos", "align": "center"},
    {"key": "tasks", "label": "Tareas", "align": "center"},
    {"key": "actions", "label": "Acciones", "align": "end"},
]

#: ``GET /api/adhoc/v2/program-events`` llama ``search`` a lo que incidencias
#: llama ``q``, y sus fechas son ``date_from``/``date_to`` (que filtran por
#: ``start_date``). El template usa nombres lógicos y este mapa los traduce.
_QUERY_MAP = {"search": "search"}

#: Columna bajo la que se pinta el rango de fechas, y cómo se llama esa fecha.
#:
#: **No es ``commitment_date``** —el default del template, que es lo correcto en
#: incidencias porque allí ``_QUERY_MAP`` traduce el rango a
#: ``commitment_from``/``commitment_to``—. Aquí ``date_from``/``date_to`` viajan
#: tal cual y ``program_event_service.list_events`` los aplica sobre
#: ``AdhocProgramEvent.start_date``, así que el rango pertenece a la columna
#: "Inicio". Estaba bajo "Cierre" y rotulado "Compromiso desde/hasta": quien
#: filtraba por fecha de cierre obtenía un filtro por fecha de inicio.
#:
#: Se mueve el control en vez de cambiar el parámetro porque el servicio
#: **solo sabe filtrar por una** de las tres fechas (no existe un
#: ``commitment_from`` en ``ProgramEventFilters`` que se pudiera mandar): con
#: un solo rango disponible, lo honesto es ponerlo donde de verdad opera.
#: Ofrecer además el rango por fecha de cierre es trabajo de
#: ``services/program_event_service.py``, no de esta pantalla.
_DATE_FILTER_KEY = "start_date"
_DATE_FILTER_LABEL = "Inicio"


# ==========================================================================
# /adhoc/programas
# ==========================================================================

@router.get("/programas")
def programs_page(
    request: Request,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.programs.page.list"])),
    db: Session = Depends(get_db),
):
    """Listado de eventos de programa, con adjuntos y duplicado."""
    from itcj2.apps.adhoc.pages._work_context import (
        TASKS_PAGE_PERM,
        assignable_users,
        catalog_options,
        columns_without_tasks,
        granted,
        page_context,
    )
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.utils.constants import PRIORITIES, PROGRAM_EVENT_STATUSES

    catalogos = catalog_options(db, category_model="AdhocProgramCategory")
    permisos = granted(db, user, _WRITE_PERMS + (TASKS_PAGE_PERM,))
    ctx = page_context(db, user)

    # Mismo gate que en incidencias y que en el panel de documentos: el botón
    # "Tareas" lleva a una página que exige `adhoc.tasks.page.list`, así que sin
    # el permiso no se ofrece en vez de ser un callejón a la pantalla de
    # prohibido.
    ver_tareas = permisos[TASKS_PAGE_PERM]

    page_data = {
        "kind": "program",
        "api": "/api/adhoc/v2/program-events",
        "table_id": "adhoc-table-programs",
        "tasks_url": "/adhoc/programas/{id}/tareas" if ver_tareas else None,
        "statuses": list(PROGRAM_EVENT_STATUSES),
        "priorities": list(PRIORITIES),
        "users": assignable_users(db),
        "today": ctx["today"],
        "per_page": 25,
        "query_map": _QUERY_MAP,
        "can": {
            "create": permisos["adhoc.programs.api.create"],
            "update": permisos["adhoc.programs.api.update"],
            "delete": permisos["adhoc.programs.api.delete"],
            "duplicate": permisos["adhoc.programs.api.duplicate"],
            "files": permisos["adhoc.programs.api.files.download"],
            "files_create": permisos["adhoc.programs.api.files.create"],
            "files_delete": permisos["adhoc.programs.api.files.delete"],
        },
        "labels": {
            "singular": "evento",
            "plural": "eventos",
            "title_field": "Título del evento",
            "date_start": "Fecha de inicio",
            "date_commitment": "Fecha de cierre",
            "date_real": "Fecha real de cierre",
            "description": "Resumen ejecutivo",
        },
        **catalogos,
    }

    return render_adhoc(
        request,
        "adhoc/programs/programs.html",
        {
            **ctx,
            "page_data": page_data,
            # La celda "Tareas" la rellena `work-items.js` siempre: sin permiso
            # se retira la columna entera, no solo su URL.
            "columns": columns_without_tasks(_COLUMNS, can_open=ver_tareas),
            # El rango de fechas se pinta bajo "Inicio", que es la columna que
            # `list_events` filtra de verdad con `date_from`/`date_to`.
            "date_filter_key": _DATE_FILTER_KEY,
            "date_filter_label": _DATE_FILTER_LABEL,
            # Textos e iconos del legacy (`programs/programs.html`): título
            # "Gestión de Programas" con el calendario, sin subtítulo.
            "page_title": "Gestión de Programas",
            "page_subtitle": None,
            "page_icon": "fa-regular fa-calendar-days",
            "back_url": "/adhoc/panel",
            "back_label": "Volver al Panel",
            "new_label": "Añadir Nuevos Programas",
            "empty_message": "No hay eventos que coincidan con el filtro.",
            "empty_icon": "fa-regular fa-calendar-days",
            "can_create": page_data["can"]["create"],
            "categories_url": "/adhoc/programas/categorias",
            "can_manage_categories": True,
        },
    )


# ==========================================================================
# /adhoc/programas/categorias
# ==========================================================================

@router.get("/programas/categorias")
def program_categories_page(
    request: Request,
    user: dict = Depends(
        require_page_app("adhoc", perms=["adhoc.program_categories.page.list"])
    ),
    db: Session = Depends(get_db),
):
    """Catálogo de categorías de evento (macro ``catalog_page`` + catalog-crud.js).

    En el legacy esta pantalla era el cuarto clon del mismo CRUD, con su propio
    JS, su propio CSS y **un endpoint de alta duplicado en dos blueprints**
    (``pages/programs.py:78`` y ``api_programs.py:157``). Aquí es la macro
    compartida contra ``/api/adhoc/v2/program-categories``.
    """
    from itcj2.apps.adhoc.pages._work_context import granted, page_context
    from itcj2.apps.adhoc.pages.render import render_adhoc

    permisos = granted(db, user, _CAT_PERMS)

    return render_adhoc(
        request,
        "adhoc/programs/categories.html",
        {
            **page_context(db, user),
            "can_create": permisos["adhoc.program_categories.api.create"],
            "can_update": permisos["adhoc.program_categories.api.update"],
            "can_delete": permisos["adhoc.program_categories.api.delete"],
        },
    )


# ==========================================================================
# /adhoc/programas/{id}/tareas
# ==========================================================================

@router.get("/programas/{program_id}/tareas")
def program_tasks_page(
    request: Request,
    program_id: int,
    user: dict = Depends(require_page_app("adhoc", perms=["adhoc.tasks.page.list"])),
    db: Session = Depends(get_db),
):
    """Tareas de un evento de programa. Mismo template que las de una incidencia."""
    from itcj2.apps.adhoc.pages._work_context import tasks_page_context
    from itcj2.apps.adhoc.pages.render import render_adhoc
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        evento = svc.get_event(db, program_id)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return render_adhoc(
        request,
        "adhoc/work/tasks.html",
        tasks_page_context(
            db,
            user,
            parent=evento,
            parent_type="program",
            back_url="/adhoc/programas",
            parent_label="evento",
        ),
    )

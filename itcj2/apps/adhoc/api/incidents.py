"""API v2 de incidencias del SGC — ``/api/adhoc/v2/incidents``.

Reemplaza las tres vistas de ``routes/api/api_incidents.py`` del legacy
(``save_incidents`` / ``edit_incident`` / ``delete_incident``), que no tenían
autorización de ningún tipo, leían ``request.form`` a mano y respondían
**siempre** con un ``redirect`` — el mismo 302 para un alta correcta, para una
FK inexistente y para un id que no existe.

Contrato de este módulo:

* Autorización obligatoria en los cuatro endpoints, con los códigos exactos de
  ``database/DML/adhoc/init/02_insert_permissions.sql``
  (``adhoc.incidents.api.{read,create,update,delete}``).
* Sobres de respuesta de ``schemas/common.py``: ``ok_page`` / ``ok_list`` /
  ``ok_item`` / ``ok_message``.
* Errores como ``HTTPException(status_code=..., detail="texto")`` con
  ``detail`` **string**: el handler global de ``itcj2/main.py`` lo publica como
  ``{"error": "<texto>", "status": N}``. ``ValueError`` del service (entrada
  inválida, p.ej. una FK que no existe) -> 400; ausencia del recurso -> 404.

**Los filtros de query se declaran como ``str``, no como ``int``/``date``.** Es
deliberado: los ``<select>`` de esta app mandan el ``value=""`` del placeholder
y los inputs de fecha vacíos mandan ``""``. Con un ``Optional[int]`` FastAPI
devolvería 422 ante ``?area_id=`` (los ``BeforeValidator`` de Pydantic **no**
se aplican a query params, verificado en FastAPI 0.141), lo que rompería el
listado en cuanto el usuario dejara un filtro en blanco. Aquí el ``""`` se
coacciona a ``None`` y solo un valor realmente mal formado da 400.

El prefijo lo pone el padre en la fase de cableado::

    adhoc_router.include_router(incidents_router, prefix="/incidents")
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from itcj2.apps.adhoc.schemas.common import PaginationParams
from itcj2.apps.adhoc.schemas.incidents import IncidentBulkCreate, IncidentUpdate
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["adhoc-incidents"])
logger = logging.getLogger(__name__)


# ==========================================================================
# Coerción de filtros (ver nota del docstring del módulo)
# ==========================================================================

def _as_int(value: Optional[str], field: str) -> Optional[int]:
    from itcj2.apps.adhoc.schemas.common import empty_to_none

    limpio = empty_to_none(value)
    if limpio is None:
        return None
    try:
        return int(limpio)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail=f"El filtro '{field}' debe ser un número entero"
        )


def _as_date(value: Optional[str], field: str) -> Optional[date]:
    from itcj2.apps.adhoc.schemas.common import empty_to_none

    limpio = empty_to_none(value)
    if limpio is None:
        return None
    try:
        return date.fromisoformat(limpio)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"El filtro '{field}' debe ser una fecha con formato YYYY-MM-DD",
        )


def _as_choice(
    value: Optional[str], choices: Sequence[str], field: str
) -> Optional[str]:
    from itcj2.apps.adhoc.schemas.common import empty_to_none

    limpio = empty_to_none(value)
    if limpio is None:
        return None
    if limpio not in choices:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' inválido: {limpio}. Válidos: {', '.join(choices)}",
        )
    return limpio


# ==========================================================================
# Endpoints
# ==========================================================================

@router.get("")
def list_incidents(
    request: Request,
    q: Optional[str] = Query(None, description="Busca en folio, título y descripción"),
    status: Optional[str] = Query(None, description="No Iniciada | Iniciada | Cerrada"),
    priority: Optional[str] = Query(None, description="Baja | Media | Alta | Urgente"),
    category_id: Optional[str] = Query(None),
    area_id: Optional[str] = Query(None),
    process_id: Optional[str] = Query(None),
    responsible_id: Optional[str] = Query(None),
    start_from: Optional[str] = Query(None, description="start_date >= YYYY-MM-DD"),
    start_to: Optional[str] = Query(None, description="start_date <= YYYY-MM-DD"),
    commitment_from: Optional[str] = Query(None),
    commitment_to: Optional[str] = Query(None),
    order_by: str = Query("id"),
    order_dir: str = Query("asc", pattern="^(asc|desc)$"),
    pagination: PaginationParams = Depends(),
    user: dict = require_perms("adhoc", ["adhoc.incidents.api.read"]),
    db: DbSession = None,
):
    """Listado paginado de incidencias con sus catálogos y su responsable.

    Incluye ``task_count`` por fila (columna "Tareas" de la tabla), resuelto en
    una sola query agrupada: el legacy renderizaba ``incidencia.tasks`` en el
    template y disparaba un SELECT por incidencia.
    """
    from itcj2.apps.adhoc.schemas.common import empty_to_none, ok_page
    from itcj2.apps.adhoc.schemas.incidents import serialize_incident
    from itcj2.apps.adhoc.services.incident_service import IncidentService
    from itcj2.apps.adhoc.utils.constants import INCIDENT_STATUSES, PRIORITIES

    try:
        pagina = IncidentService.list(
            db,
            page=pagination.page,
            per_page=pagination.per_page,
            q=empty_to_none(q),
            status=_as_choice(status, INCIDENT_STATUSES, "status"),
            priority=_as_choice(priority, PRIORITIES, "priority"),
            category_id=_as_int(category_id, "category_id"),
            area_id=_as_int(area_id, "area_id"),
            process_id=_as_int(process_id, "process_id"),
            responsible_id=_as_int(responsible_id, "responsible_id"),
            start_from=_as_date(start_from, "start_from"),
            start_to=_as_date(start_to, "start_to"),
            commitment_from=_as_date(commitment_from, "commitment_from"),
            commitment_to=_as_date(commitment_to, "commitment_to"),
            order_by=order_by,
            order_dir=order_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    conteos = IncidentService.task_counts(db, [i.id for i in pagina.items])
    datos = [
        serialize_incident(i, task_count=conteos.get(i.id, 0)) for i in pagina.items
    ]
    return ok_page(datos, pagina, pagination.page, pagination.per_page)


@router.post("", status_code=201)
def create_incidents(
    request: Request,
    payload: IncidentBulkCreate = ...,
    user: dict = require_perms("adhoc", ["adhoc.incidents.api.create"]),
    db: DbSession = None,
):
    """Alta masiva. Cuerpo: ``{"items": [{...}, {...}]}``.

    El legacy leía **10 listas paralelas** y las recorría por índice, con un
    índice 1-based solo para ``priorities``: una lista más corta que las demás
    no era un error, era un campo vacío en el registro equivocado. Aquí cada
    incidencia es un objeto y el schema acepta el formato de listas paralelas
    solo si todas miden lo mismo (si no, 422 diciendo cuál descuadra).

    O entran todas o no entra ninguna: las FKs se validan antes de insertar.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.incidents import serialize_incident
    from itcj2.apps.adhoc.services.incident_service import IncidentService

    try:
        creadas = IncidentService.bulk_create(db, payload.items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "[adhoc] Usuario %s creó %d incidencia(s)", user.get("sub"), len(creadas)
    )
    return ok_list([serialize_incident(i) for i in creadas])


@router.patch("/{incident_id}")
def update_incident(
    request: Request,
    incident_id: int,
    payload: IncidentUpdate = ...,
    user: dict = require_perms("adhoc", ["adhoc.incidents.api.update"]),
    db: DbSession = None,
):
    """Edición parcial: solo se aplica lo que venga en el cuerpo.

    Un id inexistente responde **404** — el legacy lo convertía en un redirect
    "exitoso" porque su ``except Exception`` se tragaba el ``get_or_404``.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.incidents import serialize_incident
    from itcj2.apps.adhoc.services.incident_service import IncidentService

    try:
        incidencia = IncidentService.update(db, incident_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if incidencia is None:
        raise HTTPException(
            status_code=404, detail=f"No existe la incidencia {incident_id}"
        )

    conteos = IncidentService.task_counts(db, [incidencia.id])
    return ok_item(
        serialize_incident(incidencia, task_count=conteos.get(incidencia.id, 0))
    )


@router.delete("/{incident_id}")
def delete_incident(
    request: Request,
    incident_id: int,
    user: dict = require_perms("adhoc", ["adhoc.incidents.api.delete"]),
    db: DbSession = None,
):
    """Borra la incidencia y, por ``ON DELETE CASCADE``, sus tareas hijas
    (con sus asignados, comentarios y aprobaciones)."""
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.incident_service import IncidentService

    if not IncidentService.delete(db, incident_id):
        raise HTTPException(
            status_code=404, detail=f"No existe la incidencia {incident_id}"
        )

    logger.info("[adhoc] Usuario %s eliminó la incidencia %s", user.get("sub"), incident_id)
    return ok_message("Incidencia eliminada")

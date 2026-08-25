"""API v2 de indicadores del SGC: años, fichas y tablero de seguimiento.

Este módulo expone **tres** routers, uno por recurso, todos sin prefijo propio
(lo pone el padre en la fase de cableado)::

    adhoc_router.include_router(years_router,     prefix="/indicator-years")
    adhoc_router.include_router(router,           prefix="/indicators")
    adhoc_router.include_router(trackings_router, prefix="/indicator-trackings")

Qué cambia respecto del legacy (``api_indicators.py``):

===========================================  =================================
Legacy                                       Aquí
===========================================  =================================
Las 6 rutas **anónimas**                     ``require_perms("adhoc", [...])``
``redirect(request.referrer)``, éxito o no   JSON ``{"success": true, ...}``
``except Exception`` que traga el 404        404 real, ``detail`` STRING
15 listas paralelas indexadas sin guarda     Un JSON validado por fila
4 umbrales en un string ``"b-r-a-v"``        4 campos independientes
``frequency = ''`` contra el CheckConstraint ``None`` (coacción del schema)
Sin forma de bajar la evidencia subida       ``GET /{id}/download``
Upsert de tracking con carrera               ``ON CONFLICT`` sobre el UNIQUE
Ruta con doble prefijo ``/api/api/...``      ``DELETE /indicator-years/{id}``
===========================================  =================================
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from itcj2.apps.adhoc.schemas.indicators import (
    IndicatorTrackingUpsert,
    IndicatorYearBulkCreate,
)
from itcj2.dependencies import DbSession, require_perms

years_router = APIRouter(tags=["adhoc-indicators"])
router = APIRouter(tags=["adhoc-indicators"])
trackings_router = APIRouter(tags=["adhoc-indicators"])

logger = logging.getLogger(__name__)

__all__ = ["years_router", "router", "trackings_router"]


# ==========================================================================
# Helpers locales
# ==========================================================================

@contextmanager
def _domain_errors():
    """Traduce el contrato de excepciones del service a códigos HTTP.

    ``LookupError`` → 404 · ``ValueError`` → 400. El ``detail`` es siempre un
    STRING: el handler global lo envuelve como ``{"error": detail, "status": N}``
    y tanto el JS como los tests asumen texto plano (plan §3).
    """
    try:
        yield
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _readable_validation_error(exc) -> str:
    """``ValidationError`` → una frase legible, no el dump de Pydantic."""
    partes = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        partes.append((loc + ": " if loc else "") + err.get("msg", "valor inválido"))
    return "Datos inválidos — " + "; ".join(partes)


def _parse_bulk_payload(payload: str):
    """``payload`` (JSON del multipart) → lista de ``IndicatorCreate``.

    Acepta ``{"indicators": [...]}`` y también una lista pelada ``[...]``.
    """
    from pydantic import ValidationError

    from itcj2.apps.adhoc.schemas.indicators import IndicatorCreate

    try:
        raw = json.loads(payload)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El campo 'payload' no es JSON válido")

    if isinstance(raw, dict):
        raw = raw.get("indicators")
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=400,
            detail="El campo 'payload' debe ser un objeto {\"indicators\": [...]} "
                   "o una lista de indicadores",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="No se recibió ningún indicador")

    try:
        return [IndicatorCreate.model_validate(row) for row in raw]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_readable_validation_error(exc))


def _align_uploads(files, file_indexes, total_rows: int) -> list:
    """``files`` + ``file_indexes`` → lista alineada por índice con las filas.

    Un indicador tiene **una** evidencia (``document_url`` es una columna), así
    que dos archivos para la misma fila es un error del cliente, no un "gana el
    último". Con un solo indicador en el lote, ``file_indexes`` puede omitirse.
    """
    usable = [f for f in (files or []) if getattr(f, "filename", None)]
    slots: list = [None] * total_rows
    if not usable:
        return slots

    indexes = list(file_indexes or [])
    if not indexes:
        if total_rows != 1:
            raise HTTPException(
                status_code=400,
                detail="Falta 'file_indexes': con más de un indicador hay que decir "
                       "a cuál pertenece cada archivo",
            )
        indexes = [0] * len(usable)

    if len(indexes) != len(usable):
        raise HTTPException(
            status_code=400,
            detail="'file_indexes' debe traer exactamente un índice por archivo enviado",
        )

    for upload, index in zip(usable, indexes):
        if index < 0 or index >= total_rows:
            raise HTTPException(
                status_code=400,
                detail="Índice de archivo fuera de rango: " + str(index),
            )
        if slots[index] is not None:
            raise HTTPException(
                status_code=400,
                detail="Un indicador solo admite un archivo de evidencia "
                       f"(índice {index} repetido)",
            )
        slots[index] = upload
    return slots


# ==========================================================================
# Años  —  prefijo /indicator-years
# ==========================================================================

@years_router.get("")
def list_indicator_years(
    request: Request,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.read"]),
    db: DbSession = None,
):
    """Años del tablero, del más nuevo al más viejo, con su número de fichas."""
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.indicators import IndicatorYearOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    rows = IndicatorService.list_years(db)
    return ok_list([
        IndicatorYearOut.from_model(year, count).model_dump() for year, count in rows
    ])


@years_router.post("", status_code=201)
def create_indicator_years(
    request: Request,
    payload: IndicatorYearBulkCreate = ...,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.create"]),
    db: DbSession = None,
):
    """Alta de uno o varios años.

    Los años que ya existían se devuelven en ``skipped``, no como error: el
    ``year`` es ``UNIQUE`` y repetirlo es una operación idempotente, no un fallo.
    El legacy, cuando no le llegaba ``years[]``, iteraba **todos los valores del
    formulario** y hacía ``int()`` sobre ellos.
    """
    from itcj2.apps.adhoc.schemas.indicators import IndicatorYearOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        result = IndicatorService.create_years(db, payload.years)

    created = [IndicatorYearOut.from_model(y).model_dump() for y in result["created"]]
    return {
        "success": True,
        "data": created,
        "total": len(created),
        "skipped": result["skipped"],
        "message": f"{len(created)} año(s) creado(s), {len(result['skipped'])} ya existía(n)",
    }


@years_router.delete("/{year_id}")
def delete_indicator_year(
    year_id: int,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.delete"]),
    db: DbSession = None,
):
    """Elimina el año con todos sus indicadores, seguimientos y evidencias."""
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        IndicatorService.delete_year(db, year_id)
    return ok_message("Año eliminado correctamente")


# ==========================================================================
# Indicadores  —  prefijo /indicators
# ==========================================================================

@router.get("")
def list_indicators(
    request: Request,
    year_id: int = Query(..., description="Año del tablero"),
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.read"]),
    db: DbSession = None,
):
    """Fichas de un año, con su proceso y su seguimiento ya cargados."""
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.indicators import IndicatorOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        rows = IndicatorService.list_indicators(db, year_id)
    return ok_list([IndicatorOut.from_model(row).model_dump() for row in rows])


@router.post("", status_code=201)
def create_indicators(
    year_id: int = Form(..., description="Año al que pertenece el lote"),
    payload: str = Form(..., description='JSON: {"indicators": [ {...}, {...} ]}'),
    files: list[UploadFile] = File(None),
    file_indexes: list[int] = Form(None),
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.create"]),
    db: DbSession = None,
):
    """Alta masiva del tablero de un año (``multipart/form-data``).

    Contrato del formulario:

    ``year_id``
        El año es común a todo el lote (el tablero siempre se captura dentro
        de un año).
    ``payload``
        JSON con ``{"indicators": [ ... ]}`` (o una lista pelada). Cada
        elemento se valida como ``IndicatorCreate``: los cuatro umbrales son
        campos independientes y ``frequency`` vacía se coacciona a ``None``.
    ``files`` / ``file_indexes``
        Campos repetibles y paralelos: ``file_indexes[k]`` es el índice
        (0-based) de la fila a la que pertenece ``files[k]``. Con un solo
        indicador en el lote, ``file_indexes`` puede omitirse.

    El lote es atómico: si un adjunto no pasa la validación no se crea ningún
    indicador ni queda ningún fichero en disco. El legacy dejaba las filas
    creadas y respondía con un redirect de éxito.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.indicators import IndicatorOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    rows = _parse_bulk_payload(payload)
    uploads = _align_uploads(files, file_indexes, len(rows))

    with _domain_errors():
        created = IndicatorService.bulk_create(
            db, year_id, [row.model_dump() for row in rows], uploads=uploads,
        )
    return ok_list([IndicatorOut.from_model(row).model_dump() for row in created])


@router.patch("/{indicator_id}")
def update_indicator(
    indicator_id: int,
    payload: Optional[str] = Form(
        None, description='JSON con SOLO los campos a modificar, p.ej. {"objective": "..."}',
    ),
    file: Optional[UploadFile] = File(None),
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.update"]),
    db: DbSession = None,
):
    """Edición parcial de una ficha (``multipart/form-data``, por el adjunto).

    **Solo se escriben las claves presentes en ``payload``.** Una clave ausente
    deja la columna intacta; una clave con ``null`` o ``""`` la limpia. El
    legacy hacía ``request.form.getlist('x[]')[0]`` trece veces seguidas: un
    solo campo faltante mataba el request entero con un ``IndexError`` tragado.

    Los campos viajan como **JSON dentro del multipart** y no como campos de
    formulario sueltos por una limitación de FastAPI: para un ``Form(None)``
    opcional, un valor vacío es indistinguible de un campo ausente (ambos caen
    al default), y aquí esa diferencia es justo la que separa "no toques este
    campo" de "bórralo".

    ``file`` reemplaza la evidencia y borra la anterior del disco.
    """
    from pydantic import ValidationError

    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.indicators import IndicatorOut, IndicatorUpdate
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    data: dict = {}
    if payload is not None and payload.strip():
        try:
            raw = json.loads(payload)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="El campo 'payload' no es JSON válido")
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=400,
                detail="El campo 'payload' debe ser un objeto con los campos a modificar",
            )
        try:
            data = IndicatorUpdate.model_validate(raw).model_dump(exclude_unset=True)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=_readable_validation_error(exc))

    if not data and not (file and getattr(file, "filename", None)):
        raise HTTPException(status_code=400, detail="No se recibió ningún cambio")

    with _domain_errors():
        IndicatorService.update_indicator(db, indicator_id, data, upload=file)
        indicator = IndicatorService.get_indicator(db, indicator_id)

    return ok_item(IndicatorOut.from_model(indicator).model_dump())


@router.delete("/{indicator_id}")
def delete_indicator(
    indicator_id: int,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.delete"]),
    db: DbSession = None,
):
    """Elimina la ficha, su seguimiento (cascade) y su evidencia del disco."""
    from itcj2.apps.adhoc.schemas.common import ok_message
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        IndicatorService.delete_indicator(db, indicator_id)
    return ok_message("Indicador eliminado correctamente")


@router.get("/{indicator_id}/download")
def download_indicator_document(
    indicator_id: int,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.download"]),
    db: DbSession = None,
):
    """Descarga la evidencia del indicador.

    Endpoint **nuevo**: el legacy subía el archivo (a una ruta relativa al CWD,
    sin subdirectorio por indicador) y no ofrecía ninguna forma de recuperarlo.
    Exige permiso, como todas las descargas del SGC.
    """
    from fastapi.responses import FileResponse

    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        path = IndicatorService.document_path(db, indicator_id)

    return FileResponse(
        str(path),
        media_type="application/octet-stream",
        filename=path.name,
    )


# ==========================================================================
# Seguimiento  —  prefijo /indicator-trackings
# ==========================================================================

@trackings_router.put("")
def upsert_indicator_tracking(
    request: Request,
    payload: IndicatorTrackingUpsert = ...,
    user: dict = require_perms("adhoc", ["adhoc.indicators.api.tracking"]),
    db: DbSession = None,
):
    """Guarda una celda del renglón REAL del tablero de seguimiento.

    Es un **upsert** por ``(indicator_id, period_index)`` resuelto con un solo
    ``INSERT ... ON CONFLICT DO UPDATE`` sobre el UNIQUE nuevo. El legacy hacía
    ``filter_by(...).first()`` y luego ``add()``: dos guardados simultáneos del
    mismo periodo —lo normal, porque el tablero guarda con un *debounce* de 1 s
    por tecleo— dejaban dos filas y la vista pintaba una al azar.

    ``color`` es ``NOT NULL``: si llega vacío o nulo se resuelve a ``'blanco'``.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.indicators import IndicatorTrackingOut
    from itcj2.apps.adhoc.services.indicator_service import IndicatorService

    with _domain_errors():
        tracking = IndicatorService.upsert_tracking(
            db,
            payload.indicator_id,
            payload.period_index,
            real_value=payload.real_value,
            color=payload.color,
        )

    return ok_item(
        IndicatorTrackingOut.model_validate(tracking, from_attributes=True).model_dump()
    )

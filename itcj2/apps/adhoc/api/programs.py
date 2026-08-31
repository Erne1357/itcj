"""API v2 de eventos del programa de trabajo de Calidad (calendario del SGC).

**Nota de vocabulario (plan §2.6):** "programa" aquí es un *evento del programa
de trabajo*, **no** una carrera académica (``core_programs``).

El router se declara **sin prefijo**: lo pone el padre en la fase de cableado
(``adhoc_router.include_router(programs_router, prefix="/program-events")``),
así que las URLs finales son ``/api/adhoc/v2/program-events/...``.

Qué cambia respecto del legacy (``api_programs.py``):

===========================================  =================================
Legacy                                       Aquí
===========================================  =================================
Todas las rutas **anónimas**                 ``require_perms("adhoc", [...])``
                                             en las 10, incluida la descarga
                                             (el legacy dejaba enumerar ids y
                                             bajarse el SGC entero).
Redirect 302 a la página, éxito o no         JSON ``{"success": true, ...}``
``except Exception`` que se traga el 404     404 real; ``detail`` es un STRING
Listas paralelas ``titles[]``/``folios[]``   Un JSON validado por fila
``support_files_{i+1}[]`` (1-based)          ``files`` + ``file_indexes``
Archivos listados con ``os.listdir``         ``adhoc_program_event_files``
Descarga por **nombre** de archivo           Descarga por **id** de archivo
===========================================  =================================

La descarga por id es deliberada: el legacy armaba la URL concatenando el
nombre crudo sin ``encodeURIComponent`` (``programs.js:252``), así que cualquier
adjunto con espacio o acento daba 404.
"""
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from itcj2.apps.adhoc.schemas.common import PaginationParams
from itcj2.apps.adhoc.schemas.programs import ProgramEventFilters, ProgramEventUpdate
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["adhoc-programs"])
logger = logging.getLogger(__name__)


# ==========================================================================
# Helpers locales
# ==========================================================================

def _parse_bulk_payload(payload: str):
    """``payload`` (JSON del multipart) → lista de ``ProgramEventCreate``.

    Acepta ``{"events": [...]}`` y también una lista pelada ``[...]``.

    Raises:
        HTTPException: 400 si no es JSON válido, 422 si algún evento no pasa
            la validación (mensaje legible, no el dump de Pydantic).
    """
    from pydantic import ValidationError

    from itcj2.apps.adhoc.schemas.programs import ProgramEventBulkCreate

    try:
        raw = json.loads(payload)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El campo 'payload' no es JSON válido")

    if isinstance(raw, list):
        raw = {"events": raw}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail="El campo 'payload' debe ser un objeto {\"events\": [...]} o una lista de eventos",
        )

    try:
        return ProgramEventBulkCreate.model_validate(raw).events
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_readable_validation_error(exc))


def _readable_validation_error(exc) -> str:
    """Convierte un ``ValidationError`` en una frase, no en un dump JSON.

    ``detail`` tiene que ser un STRING: el handler global lo envuelve como
    ``{"error": detail, "status": N}`` y el cliente asume texto (plan §3).
    """
    partes = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        partes.append((loc + ": " if loc else "") + err.get("msg", "valor inválido"))
    return "Datos inválidos — " + "; ".join(partes)


def _map_files(files, file_indexes, total_events: int) -> dict:
    """``files`` + ``file_indexes`` → ``{indice_de_evento: [UploadFile, ...]}``.

    ``file_indexes`` es paralelo a ``files`` (mismo orden y longitud) y dice a
    qué evento del lote pertenece cada archivo. Si se omite y el lote trae un
    solo evento, todos los archivos van a ese evento.
    """
    usable = [f for f in (files or []) if getattr(f, "filename", None)]
    if not usable:
        return {}

    indexes = list(file_indexes or [])
    if not indexes:
        if total_events != 1:
            raise HTTPException(
                status_code=400,
                detail="Falta 'file_indexes': con más de un evento hay que decir a cuál pertenece cada archivo",
            )
        indexes = [0] * len(usable)

    if len(indexes) != len(usable):
        raise HTTPException(
            status_code=400,
            detail="'file_indexes' debe traer exactamente un índice por archivo enviado",
        )

    mapping: dict = {}
    for upload, index in zip(usable, indexes):
        if index < 0 or index >= total_events:
            raise HTTPException(
                status_code=400,
                detail="Índice de archivo fuera de rango: " + str(index),
            )
        mapping.setdefault(index, []).append(upload)
    return mapping


# ==========================================================================
# Adjuntos por id  — declarados ANTES que las rutas /{event_id} a propósito:
# el convertidor por defecto de FastAPI es `str`, así que "/files/3" podría
# entrar por "/{event_id}/..." si el orden fuera el inverso.
# ==========================================================================

@router.get("/files/{file_id}/download")
def download_event_file(
    file_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.files.download"]),
    db: DbSession = None,
):
    """Descarga un adjunto por **id** (no por nombre de archivo).

    En el legacy esta ruta era anónima: enumerando ids se bajaba cualquier
    adjunto del SGC (``src_api.md`` §bug 6 — IDOR).
    """
    from fastapi.responses import FileResponse

    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        row = svc.get_file(db, file_id)
        path = svc.open_file(row)
    except svc.EventFileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    from itcj2.apps.adhoc.services import upload_service

    return FileResponse(
        str(path),
        media_type=row.mime_type or "application/octet-stream",
        # `original_name` no siempre trae extensión — ver `download_name`.
        filename=upload_service.download_name(path, row.original_name),
    )


@router.delete("/files/{file_id}")
def delete_event_file(
    file_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.files.delete"]),
    db: DbSession = None,
):
    """Elimina un adjunto: la fila y el fichero del disco."""
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        svc.delete_file(db, file_id)
    except svc.EventFileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"success": True, "message": "Archivo eliminado"}


# ==========================================================================
# Eventos
# ==========================================================================

@router.get("")
def list_program_events(
    request: Request,
    filters: ProgramEventFilters = Depends(),
    pagination: PaginationParams = Depends(),
    user: dict = require_perms("adhoc", ["adhoc.programs.api.read"]),
    db: DbSession = None,
):
    """Listado paginado de eventos, con filtros en servidor.

    Query params: ``search``, ``status``, ``priority``, ``category_id``,
    ``area_id``, ``process_id``, ``responsible_id``, ``date_from``, ``date_to``,
    ``page``, ``per_page``.

    Incluye ``task_count`` por fila —la pastilla del botón "Ver Tareas" de la
    tabla—, resuelto en una sola query agrupada sobre el lote de la página,
    igual que en ``GET /incidents``. Contarlo dentro de ``event_to_dict`` con
    un ``len(event.tasks)`` daría el mismo JSON y un SELECT por evento.
    """
    from itcj2.apps.adhoc.schemas.common import ok_page
    from itcj2.apps.adhoc.schemas.programs import event_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    page = svc.list_events(db, filters, page=pagination.page, per_page=pagination.per_page)
    conteos = svc.task_counts(db, [e.id for e in page.items])
    return ok_page(
        [event_to_dict(e, task_count=conteos.get(e.id, 0)) for e in page.items],
        page,
        pagination.page,
        pagination.per_page,
    )


@router.post("", status_code=201)
def create_program_events(
    payload: str = Form(..., description='JSON: {"events": [ {...}, {...} ]}'),
    files: list[UploadFile] = File(None),
    file_indexes: list[int] = Form(None),
    user: dict = require_perms("adhoc", ["adhoc.programs.api.create"]),
    db: DbSession = None,
):
    """Alta masiva de eventos con sus adjuntos (``multipart/form-data``).

    Contrato del formulario:

    ``payload``
        JSON con ``{"events": [ ... ]}`` (o una lista pelada). Cada elemento se
        valida como ``ProgramEventCreate``: los ``""`` de los ``<select>``
        placeholder se coaccionan a ``None`` y ``priority``/``status`` caen a
        su default si vienen vacíos.
    ``files`` / ``file_indexes``
        Campos repetibles y **paralelos**: ``file_indexes[k]`` es el índice
        (0-based) del evento al que pertenece ``files[k]``. Con un solo evento
        en el lote, ``file_indexes`` puede omitirse. Sustituye al
        ``support_files_{i+1}[]`` 1-based del legacy, que desalineaba archivo y
        fila en cuanto una fila venía vacía.

    El lote es atómico: si un adjunto no pasa la validación no se crea ningún
    evento ni queda ningún fichero en disco.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.programs import event_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    events = _parse_bulk_payload(payload)
    files_by_index = _map_files(files, file_indexes, len(events))

    try:
        created = svc.bulk_create(
            db, events,
            files_by_index=files_by_index,
            uploaded_by_id=int(user["sub"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok_list([event_to_dict(e, include_files=True) for e in created])


@router.get("/{event_id}")
def get_program_event(
    event_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.read"]),
    db: DbSession = None,
):
    """Detalle de un evento, con sus adjuntos.

    ⚠️ **Sin consumidor en el front, y se conserva.** El modal de edición de
    ``programs/programs.js`` no lo llama: rellena el formulario con el ítem que
    ya trajo ``GET /program-events`` (la lista precarga ``files`` y expone
    ``files_count``), y tras cada escritura recarga la lista entera. Deuda
    simple, no código muerto — razones para no borrarlo:

    * Es la lectura de UNO del recurso, y su ausencia es lo que ya duele en
      incidencias: ``/incidents`` **no** tiene detalle, y por eso cualquier
      refresco de una sola ficha allí obliga a repaginar la lista. Quitarlo aquí
      propagaría esa asimetría en vez de corregirla.
    * Está probado (``tests/fastapi/adhoc/test_programs_api.py``: el 404 del
      evento inexistente y que el detalle incluye los adjuntos) y lo cubre el
      permiso ``adhoc.programs.api.read``, el mismo de la lista: no amplía
      superficie de ataque.

    Si un día el modal deja de recargar la lista completa tras guardar, este es
    el endpoint que ya está esperando.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.programs import event_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        event = svc.get_event(db, event_id)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ok_item(event_to_dict(event, include_files=True))


@router.patch("/{event_id}")
def update_program_event(
    event_id: int,
    data: ProgramEventUpdate,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.update"]),
    db: DbSession = None,
):
    """Edición parcial. Solo se tocan los campos presentes en el cuerpo.

    El legacy sí leía ``descriptions[]`` en el alta pero **no** en la edición,
    y nunca escribía ``location``, ``real_date`` ni ``status`` desde el
    formulario; aquí los cuatro son editables.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.programs import event_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        event = svc.update_event(db, event_id, data)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok_item(event_to_dict(event, include_files=True))


@router.delete("/{event_id}")
def delete_program_event(
    event_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.delete"]),
    db: DbSession = None,
):
    """Elimina el evento, sus adjuntos (BD **y** disco) y sus tareas hijas."""
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        svc.delete_event(db, event_id)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"success": True, "message": "Evento eliminado"}


@router.post("/{event_id}/duplicate", status_code=201)
def duplicate_program_event(
    event_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.duplicate"]),
    db: DbSession = None,
):
    """Duplica un evento como nuevo evento *Planeado*.

    Se copia: título (prefijado "Copia de "), descripción, prioridad,
    **ubicación** (que el legacy perdía), fecha de inicio, fecha compromiso,
    categoría, área, proceso y responsable.

    NO se copia: ``real_date`` ni ``status`` (el avance real es del evento
    original), los adjuntos ni las tareas hijas.

    El folio de la copia es el primer ``-COPY`` libre (``-COPY``, ``-COPY-2``,
    …): el legacy generaba siempre el mismo y duplicar dos veces producía dos
    eventos con folio idéntico.
    """
    from itcj2.apps.adhoc.schemas.common import ok_item
    from itcj2.apps.adhoc.schemas.programs import event_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        copy = svc.duplicate_event(db, event_id)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok_item(event_to_dict(copy, include_files=True))


# ==========================================================================
# Adjuntos de un evento
# ==========================================================================

@router.get("/{event_id}/files")
def list_program_event_files(
    event_id: int,
    user: dict = require_perms("adhoc", ["adhoc.programs.api.read"]),
    db: DbSession = None,
):
    """Adjuntos del evento, leídos de la BD (no de ``os.listdir``)."""
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.programs import file_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        rows = svc.list_files(db, event_id)
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ok_list([file_to_dict(f) for f in rows])


@router.post("/{event_id}/files", status_code=201)
def upload_program_event_files(
    event_id: int,
    files: list[UploadFile] = File(...),
    user: dict = require_perms("adhoc", ["adhoc.programs.api.files.create"]),
    db: DbSession = None,
):
    """Adjunta archivos a un evento ya existente (``multipart/form-data``).

    Campo repetible ``files``. Extensión, tamaño y nombre los valida
    ``upload_service``; si uno falla no se guarda ninguno.
    """
    from itcj2.apps.adhoc.schemas.common import ok_list
    from itcj2.apps.adhoc.schemas.programs import file_to_dict
    from itcj2.apps.adhoc.services import program_event_service as svc

    try:
        rows = svc.add_files(db, event_id, files, uploaded_by_id=int(user["sub"]))
    except svc.EventNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ok_list([file_to_dict(f) for f in rows])

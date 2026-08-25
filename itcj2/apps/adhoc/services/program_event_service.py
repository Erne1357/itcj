"""Eventos del programa de trabajo de Calidad (el calendario del SGC).

**Nota de vocabulario (plan §2.6):** "programa" aquí es un *evento del programa
de trabajo*, **no** una carrera académica (``core_programs``).

Reemplaza a ``template/itcj/apps/app_prueba/routes/api/api_programs.py``.
Los cinco arreglos que justifican este módulo:

1. **Los adjuntos se registran en BD** (``adhoc_program_event_files``). El
   legacy los escribía en disco y los "descubría" con ``os.listdir``: si el
   ``commit()` posterior fallaba quedaban archivos apuntando a un id
   inexistente, y ``delete_program`` no borraba nada del disco (bug #18).
   Aquí ``delete_event`` limpia filas **y** ficheros **y** el directorio.
2. **El alta masiva es atómica.** El legacy hacía ``flush()`` por fila, escribía
   los archivos y luego commiteaba dentro de un ``except Exception`` que se
   tragaba el error: un lote roto dejaba basura en disco y redirigía como si
   hubiera funcionado. Aquí, si algo falla, se hace ``rollback()`` y se borran
   los ficheros ya escritos antes de propagar el error.
3. **``duplicate`` no colisiona de folio.** El legacy generaba siempre
   ``f"{folio}-COPY"``: duplicar dos veces producía dos eventos con el mismo
   folio. Aquí se busca el primer sufijo libre (``-COPY``, ``-COPY-2``, …),
   respetando el largo máximo de la columna (50).
4. **``duplicate`` conserva ``location``**, que el legacy perdía.
5. **Listado con filtros y paginación en servidor.** El legacy mandaba la tabla
   entera a la plantilla y filtraba en el DOM.

Convención de errores: el service lanza :class:`EventNotFound` /
:class:`EventFileNotFound` (subclases de ``LookupError``) para el 404 y
``ValueError`` para el 400. El endpoint traduce; el service no sabe de HTTP.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from itcj2.apps.adhoc.utils.constants import PROGRAM_EVENT_STATUS_DEFAULT

logger = logging.getLogger(__name__)

__all__ = [
    "EventNotFound",
    "EventFileNotFound",
    "UPLOAD_KIND",
    "get_event",
    "list_events",
    "bulk_create",
    "update_event",
    "delete_event",
    "duplicate_event",
    "list_files",
    "add_files",
    "get_file",
    "open_file",
    "delete_file",
    "AdhocProgramEventService",
]


class EventNotFound(LookupError):
    """El evento de programa no existe. El endpoint lo traduce a 404."""


class EventFileNotFound(LookupError):
    """El adjunto no existe. El endpoint lo traduce a 404."""


#: Almacén de ``upload_service`` para los adjuntos de eventos.
UPLOAD_KIND = "program_events"

#: Largo de ``adhoc_program_events.folio``.
_FOLIO_MAX = 50

#: Sufijo base que el legacy usaba (se conserva por continuidad de UX).
_COPY_SUFFIX = "-COPY"

#: Tope de intentos al desambiguar el folio de una copia.
_MAX_COPY_ATTEMPTS = 500

#: Columnas NOT NULL con CheckConstraint: un ``null`` explícito en el PATCH se
#: ignora en vez de reventar el UPDATE (plan §2.8, regla 4).
_NOT_NULL_FIELDS = ("priority", "status")

#: Campos que ``duplicate_event`` copia del original. Fuera quedan a propósito
#: ``real_date`` y ``status`` (el avance real del evento original no es el de la
#: copia) y los adjuntos (documentar es más honesto que clonar ficheros).
_DUPLICATED_FIELDS = (
    "description",
    "priority",
    "location",
    "start_date",
    "commitment_date",
    "category_id",
    "area_id",
    "process_id",
    "responsible_id",
)


def _eager(query):
    """Carga las relaciones que la serialización necesita — mata el N+1.

    El listado del legacy tocaba ``evento.area``, ``.process``, ``.category`` y
    ``.responsible`` por fila desde la plantilla: 4 queries extra por evento.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent

    return query.options(
        selectinload(AdhocProgramEvent.category),
        selectinload(AdhocProgramEvent.area),
        selectinload(AdhocProgramEvent.process),
        selectinload(AdhocProgramEvent.responsible),
        selectinload(AdhocProgramEvent.files),
    )


# ==========================================================================
# Lectura
# ==========================================================================

def get_event(db: Session, event_id: int, *, eager: bool = True):
    """Devuelve un evento por PK o lanza :class:`EventNotFound`.

    El legacy usaba ``get_or_404`` dentro de un ``except Exception`` que se
    tragaba el ``NotFound`` de werkzeug y devolvía un redirect "exitoso"
    (``src_api.md`` §bug 4).
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent

    if eager:
        event = _eager(db.query(AdhocProgramEvent)).filter(
            AdhocProgramEvent.id == event_id
        ).one_or_none()
    else:
        event = db.get(AdhocProgramEvent, event_id)

    if event is None:
        raise EventNotFound("El evento de programa " + str(event_id) + " no existe")
    return event


def list_events(db: Session, filters: Any = None, *, page: int = 1, per_page: int = 20):
    """Listado paginado y filtrado, ordenado por id descendente.

    ``filters`` es un ``ProgramEventFilters`` (o cualquier objeto con esos
    atributos); ``None`` significa "sin filtros".

    Returns:
        El ``Pagination`` de ``itcj2.models.base`` (``.items``, ``.total``,
        ``.pages``).
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent
    from itcj2.models.base import paginate

    query = _eager(db.query(AdhocProgramEvent))

    def _f(name):
        return getattr(filters, name, None) if filters is not None else None

    search = _f("search")
    if search:
        like = "%" + str(search).strip() + "%"
        query = query.filter(or_(
            AdhocProgramEvent.title.ilike(like),
            AdhocProgramEvent.folio.ilike(like),
            AdhocProgramEvent.description.ilike(like),
            AdhocProgramEvent.location.ilike(like),
        ))

    for attr in ("status", "priority", "category_id", "area_id", "process_id", "responsible_id"):
        value = _f(attr)
        if value is not None:
            query = query.filter(getattr(AdhocProgramEvent, attr) == value)

    date_from = _f("date_from")
    if date_from is not None:
        query = query.filter(AdhocProgramEvent.start_date >= date_from)
    date_to = _f("date_to")
    if date_to is not None:
        query = query.filter(AdhocProgramEvent.start_date <= date_to)

    query = query.order_by(AdhocProgramEvent.id.desc())
    return paginate(query, page, per_page)


# ==========================================================================
# Alta masiva (con adjuntos)
# ==========================================================================

def bulk_create(
    db: Session,
    events: Sequence[Any],
    *,
    files_by_index: Optional[Mapping[int, Iterable[Any]]] = None,
    uploaded_by_id: Optional[int] = None,
):
    """Crea N eventos y adjunta los archivos de cada uno. Todo o nada.

    Args:
        events: lista de ``ProgramEventCreate`` ya validados.
        files_by_index: ``{indice_en_events: [UploadFile, ...]}``. El índice es
            0-based (el legacy usaba ``support_files_{i+1}[]``, 1-based, lo que
            desalineaba el archivo con su fila si una fila venía vacía).
        uploaded_by_id: autor del alta, para ``adhoc_program_event_files``.

    Returns:
        Los eventos creados, en el mismo orden que ``events``.

    Raises:
        ValueError: lista vacía o adjunto inválido (extensión, tamaño, nombre).
            En ese caso no queda ni un evento ni un fichero: se hace rollback y
            se borran del disco los archivos ya escritos.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent, AdhocProgramEventFile
    from itcj2.apps.adhoc.services import upload_service

    if not events:
        raise ValueError("No se recibió ningún evento para registrar")

    files_by_index = files_by_index or {}
    created: list = []
    written: list[str] = []   # rutas relativas ya escritas, para limpiar si algo falla

    try:
        for index, payload in enumerate(events):
            data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
            event = AdhocProgramEvent(**data)
            db.add(event)
            db.flush()          # necesitamos el id para el directorio del evento
            created.append(event)

            for upload in files_by_index.get(index) or []:
                if not getattr(upload, "filename", None):
                    continue    # input file vacío del navegador
                meta = upload_service.save_upload(UPLOAD_KIND, event.id, upload)
                written.append(meta["file_path"])
                db.add(AdhocProgramEventFile(
                    event_id=event.id,
                    file_path=meta["file_path"],
                    original_name=meta["original_name"],
                    mime_type=meta["mime_type"],
                    size_bytes=meta["size_bytes"],
                    uploaded_by_id=uploaded_by_id,
                ))

        db.commit()
    except Exception:
        db.rollback()
        for relative in written:
            upload_service.delete_file(UPLOAD_KIND, relative)
        raise

    for event in created:
        db.refresh(event)
    logger.info("[adhoc] %s eventos de programa creados", len(created))
    return created


# ==========================================================================
# Actualización y borrado
# ==========================================================================

def update_event(db: Session, event_id: int, data: Any):
    """Actualiza parcialmente un evento (PATCH).

    Solo se tocan los campos presentes en el payload (``exclude_unset``); un
    ``null``/``""`` limpia las columnas nullable, y se ignora en ``priority`` y
    ``status``, que son NOT NULL con CheckConstraint.
    """
    event = get_event(db, event_id, eager=False)

    changes = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
    for field, value in changes.items():
        if value is None and field in _NOT_NULL_FIELDS:
            continue
        setattr(event, field, value)

    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event_id: int) -> None:
    """Elimina el evento, sus filas de adjuntos y sus ficheros del disco.

    Bug #18 del legacy: ``delete_program`` borraba la fila y dejaba el
    directorio de archivos huérfano para siempre. Las tareas hijas las borra la
    BD (``adhoc_tasks.program_id`` es ``ON DELETE CASCADE``).
    """
    from itcj2.apps.adhoc.services import upload_service

    event = get_event(db, event_id, eager=True)
    stored_paths = [f.file_path for f in (event.files or [])]

    try:
        directory: Optional[Path] = upload_service.resolve_dir(UPLOAD_KIND, event_id)
    except ValueError:
        directory = None

    db.delete(event)
    db.commit()

    # Solo después de que la BD confirmó el borrado se toca el disco: si el
    # commit falla, los ficheros siguen ahí y la fila también (consistente).
    for relative in stored_paths:
        upload_service.delete_file(UPLOAD_KIND, relative)
    if directory is not None and directory.is_dir():
        try:
            next(directory.iterdir())
        except StopIteration:
            try:
                directory.rmdir()
            except OSError:
                logger.warning("[adhoc] No se pudo borrar el directorio %s", directory)
        except OSError:
            pass

    logger.info("[adhoc] Evento de programa %s eliminado (%s adjuntos)", event_id, len(stored_paths))


# ==========================================================================
# Duplicado
# ==========================================================================

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _copy_folio_candidates(folio: str):
    """Genera ``FOLIO-COPY``, ``FOLIO-COPY-2``, … truncados a 50 caracteres."""
    yield folio[: _FOLIO_MAX - len(_COPY_SUFFIX)] + _COPY_SUFFIX
    for n in range(2, _MAX_COPY_ATTEMPTS):
        suffix = _COPY_SUFFIX + "-" + str(n)
        yield folio[: _FOLIO_MAX - len(suffix)] + suffix


def next_copy_folio(db: Session, folio: Optional[str]) -> Optional[str]:
    """Primer folio de copia libre, o ``None`` si el original no tenía folio.

    El legacy devolvía siempre ``f"{folio}-COPY"`` (y ``"COPY"`` a secas si no
    había folio), así que duplicar dos veces el mismo evento producía dos
    eventos indistinguibles en la tabla.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent

    if not folio or not str(folio).strip():
        return None

    folio = str(folio).strip()
    # Prefijo común a todos los candidatos, para traer solo lo que puede chocar.
    prefix = folio[: max(1, _FOLIO_MAX - len(_COPY_SUFFIX) - 4)]
    taken = {
        row[0] for row in db.query(AdhocProgramEvent.folio)
        .filter(AdhocProgramEvent.folio.like(_escape_like(prefix) + "%", escape="\\"))
        .all()
        if row[0]
    }

    for candidate in _copy_folio_candidates(folio):
        if candidate not in taken:
            return candidate
    raise ValueError("No se pudo generar un folio libre para la copia; renombra el folio original")


def duplicate_event(db: Session, event_id: int):
    """Clona un evento como nuevo evento *Planeado*.

    **Qué se copia:** título (prefijado con "Copia de "), descripción,
    prioridad, ubicación, fecha de inicio, fecha compromiso, categoría, área,
    proceso y responsable. La ubicación es justo lo que el legacy perdía.

    **Qué NO se copia, a propósito:** ``real_date`` y ``status`` (el avance real
    pertenece al evento original; la copia nace en ``'Planeado'``), los
    **adjuntos** (una copia no debe duplicar ficheros en disco: si se necesitan,
    se suben a la copia) y las **tareas** hijas.

    El folio de la copia es el primer ``-COPY`` libre (ver
    :func:`next_copy_folio`); si el original no tenía folio, la copia tampoco.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEvent

    original = get_event(db, event_id, eager=False)

    copy = AdhocProgramEvent(
        folio=next_copy_folio(db, original.folio),
        title=("Copia de " + (original.title or ""))[:200],
        status=PROGRAM_EVENT_STATUS_DEFAULT,
        real_date=None,
    )
    for field in _DUPLICATED_FIELDS:
        setattr(copy, field, getattr(original, field))

    db.add(copy)
    db.commit()
    db.refresh(copy)
    logger.info("[adhoc] Evento de programa %s duplicado como %s", event_id, copy.id)
    return copy


# ==========================================================================
# Adjuntos
# ==========================================================================

def list_files(db: Session, event_id: int):
    """Adjuntos de un evento, del más reciente al más antiguo.

    Sale de ``adhoc_program_event_files``, no de ``os.listdir``: el legacy
    listaba el directorio, así que un fichero borrado a mano desaparecía sin
    rastro y uno subido a mano aparecía como si fuera del SGC.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEventFile

    get_event(db, event_id, eager=False)
    return (
        db.query(AdhocProgramEventFile)
        .filter(AdhocProgramEventFile.event_id == event_id)
        .order_by(AdhocProgramEventFile.id.desc())
        .all()
    )


def add_files(db: Session, event_id: int, uploads: Sequence[Any], *, uploaded_by_id: Optional[int] = None):
    """Adjunta uno o más archivos a un evento existente.

    Raises:
        EventNotFound: el evento no existe.
        ValueError: no venía ningún archivo, o alguno es inválido (extensión
            fuera de whitelist, tamaño, nombre con traversal). En ese caso no
            queda ninguno: se borra del disco lo ya escrito y se hace rollback.
    """
    from itcj2.apps.adhoc.models import AdhocProgramEventFile
    from itcj2.apps.adhoc.services import upload_service

    get_event(db, event_id, eager=False)

    usable = [u for u in (uploads or []) if getattr(u, "filename", None)]
    if not usable:
        raise ValueError("No se recibió ningún archivo")

    rows: list = []
    written: list[str] = []
    try:
        for upload in usable:
            meta = upload_service.save_upload(UPLOAD_KIND, event_id, upload)
            written.append(meta["file_path"])
            row = AdhocProgramEventFile(
                event_id=event_id,
                file_path=meta["file_path"],
                original_name=meta["original_name"],
                mime_type=meta["mime_type"],
                size_bytes=meta["size_bytes"],
                uploaded_by_id=uploaded_by_id,
            )
            db.add(row)
            rows.append(row)
        db.commit()
    except Exception:
        db.rollback()
        for relative in written:
            upload_service.delete_file(UPLOAD_KIND, relative)
        raise

    for row in rows:
        db.refresh(row)
    return rows


def get_file(db: Session, file_id: int):
    """Adjunto por PK o :class:`EventFileNotFound`."""
    from itcj2.apps.adhoc.models import AdhocProgramEventFile

    row = db.get(AdhocProgramEventFile, file_id)
    if row is None:
        raise EventFileNotFound("El archivo " + str(file_id) + " no existe")
    return row


def open_file(file_row: Any) -> Path:
    """Ruta absoluta y verificada del adjunto, lista para ``FileResponse``.

    Pasa por ``safe_join``: el valor de ``file_path`` viene de la BD y se trata
    como dato no confiable.

    Raises:
        EventFileNotFound: el registro apunta a un fichero que ya no está o a
            una ruta que se sale de la raíz de uploads.
    """
    from itcj2.apps.adhoc.services import upload_service

    try:
        return upload_service.open_stored(UPLOAD_KIND, file_row.file_path)
    except ValueError as exc:
        raise EventFileNotFound(str(exc)) from exc


def delete_file(db: Session, file_id: int) -> None:
    """Borra el adjunto: primero la fila, después el fichero del disco."""
    from itcj2.apps.adhoc.services import upload_service

    row = get_file(db, file_id)
    relative = row.file_path
    db.delete(row)
    db.commit()
    upload_service.delete_file(UPLOAD_KIND, relative)
    logger.info("[adhoc] Adjunto de evento %s eliminado", file_id)


class AdhocProgramEventService:
    """Fachada de clase (convención del repo). Delega en las funciones del módulo."""

    get_event = staticmethod(get_event)
    list_events = staticmethod(list_events)
    bulk_create = staticmethod(bulk_create)
    update_event = staticmethod(update_event)
    delete_event = staticmethod(delete_event)
    duplicate_event = staticmethod(duplicate_event)
    next_copy_folio = staticmethod(next_copy_folio)
    list_files = staticmethod(list_files)
    add_files = staticmethod(add_files)
    get_file = staticmethod(get_file)
    open_file = staticmethod(open_file)
    delete_file = staticmethod(delete_file)

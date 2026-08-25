"""Almacenamiento de adjuntos de Adhoc — un solo helper para los cuatro kinds.

Reemplaza los **cuatro** helpers duplicados del legacy
(``api_docs.py:233``, ``api_programs.py:10``, ``api_tasks.py:236`` y ``:345``,
``api_indicators.py:9``) y arregla lo que cada uno hacía mal
(``docs/adhoc/analysis/src_api.md`` §3):

===========================  =====================================================
Problema del legacy          Qué hace este módulo
===========================  =====================================================
Sin whitelist de extensión   ``ADHOC_ALLOWED_EXTENSIONS`` (se puede subir ``.php``,
                             ``.svg``, ``.html`` — no ya).
Sin límite de tamaño         ``ADHOC_MAX_FILE_SIZE``, medido antes de escribir.
Colisión = sobrescritura     Sufijo numérico ``nombre_1.pdf``; el archivo previo
silenciosa                   nunca se pisa.
Indicadores en un directorio ``indicators/{indicator_id}/`` como los demás; dos
plano relativo al CWD        indicadores con ``evidencia.pdf`` ya no se pisan, y la
                             raíz es absoluta (``ADHOC_UPLOAD_PATH``), no relativa
                             al directorio desde el que arrancó gunicorn.
``os.path.join`` con tramos  ``safe_join`` en **toda** ruta cuyo último tramo venga
de origen HTTP               de HTTP o de una columna de BD.
===========================  =====================================================

``safe_join`` no es opcional: ``os.path.join(raiz, parte)`` descarta ``raiz`` en
silencio si ``parte`` es absoluta, y este repo ya tiene un incidente por eso
(``instance/apps/``, agosto 2026 — ver ``itcj2/core/utils/safe_paths.py``).

**Contrato de la ruta guardada en BD:** ``save_upload`` devuelve ``file_path``
**relativo al kind**, con la forma ``"{entity_id}/{filename}"`` — exactamente el
formato que declaran ``AdhocDocument.file_url``, ``AdhocProgramEventFile.file_path``,
``AdhocTaskComment.file_path`` y ``AdhocIndicator.document_url``. Para volver del
valor de BD al fichero, ``open_stored(kind, valor)``.

**Errores:** todo fallo previsible es un ``ValueError`` con mensaje en español,
listo para que el endpoint haga
``raise HTTPException(status_code=400, detail=str(exc))``.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from werkzeug.utils import secure_filename

from itcj2.apps.adhoc.utils.constants import UPLOAD_KINDS, UploadKind
from itcj2.core.utils.safe_paths import UnsafePath, safe_join

logger = logging.getLogger(__name__)

__all__ = [
    "resolve_dir",
    "save_upload",
    "open_download",
    "open_stored",
    "delete_file",
    "AdhocUploadService",
]

#: Tope de intentos al desambiguar un nombre colisionado antes de rendirse.
_MAX_NAME_ATTEMPTS = 500

#: Trozo de lectura al copiar el stream al disco.
_CHUNK = 64 * 1024


def _settings():
    """Indirección deliberada: los tests parchean **esta** función.

    Se importa dentro para evitar circulares y para que ``get_settings()``
    (que está ``lru_cache``-ado) no quede congelado en tiempo de import.
    """
    from itcj2.config import get_settings
    return get_settings()


def _allowed_extensions() -> set[str]:
    raw = getattr(_settings(), "ADHOC_ALLOWED_EXTENSIONS", "") or ""
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def _max_size() -> int:
    return int(getattr(_settings(), "ADHOC_MAX_FILE_SIZE", 10 * 1024 * 1024))


def _root() -> str:
    return str(getattr(_settings(), "ADHOC_UPLOAD_PATH"))


# ==========================================================================
# Validación de tramos
# ==========================================================================

def _check_kind(kind: str) -> str:
    if kind not in UPLOAD_KINDS:
        raise ValueError(
            f"Tipo de adjunto desconocido: {kind!r}. "
            f"Válidos: {', '.join(UPLOAD_KINDS)}"
        )
    return kind


def _check_entity_id(entity_id: Any) -> int:
    """El id tiene que ser un entero positivo — es un tramo de ruta.

    Un ``entity_id`` que llega como ``"../.."`` desde un query param es el
    vector más obvio de traversal, y es el único tramo del path que no pasa por
    ``secure_filename``.
    """
    if isinstance(entity_id, bool) or not isinstance(entity_id, int):
        try:
            entity_id = int(str(entity_id).strip())
        except (TypeError, ValueError):
            raise ValueError(f"Identificador de entidad inválido: {entity_id!r}")
    if entity_id <= 0:
        raise ValueError(f"Identificador de entidad inválido: {entity_id!r}")
    return entity_id


def _check_upload_filename(raw: Optional[str]) -> tuple[str, str]:
    """Sanea el nombre que manda el navegador. Devuelve ``(nombre, ext)``.

    Rechaza —en vez de aplanar— cualquier nombre con separador de ruta, ``..``
    o byte nulo: un cliente legítimo nunca manda eso, y un rechazo explícito
    deja rastro en el log en lugar de "arreglar" silenciosamente un ataque.
    """
    if not raw or not str(raw).strip():
        raise ValueError("Archivo sin nombre")

    raw = str(raw)
    if "\x00" in raw:
        raise ValueError("Nombre de archivo inválido (byte nulo)")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(f"Nombre de archivo inválido: {raw!r}")
    if os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise ValueError(f"Nombre de archivo inválido: {raw!r}")

    name = secure_filename(raw)
    if not name or "." not in name:
        # secure_filename se come acentos y espacios; si no queda nada usable
        # (p. ej. un nombre íntegramente en cirílico) es un rechazo, no un
        # nombre inventado.
        raise ValueError(f"Nombre de archivo inválido: {raw!r}")

    ext = name.rsplit(".", 1)[1].lower()
    if not ext:
        raise ValueError(f"Archivo sin extensión: {raw!r}")

    allowed = _allowed_extensions()
    if allowed and ext not in allowed:
        raise ValueError(
            f"Extensión no permitida: .{ext}. "
            f"Solo se aceptan: {', '.join(sorted(allowed))}"
        )
    return name, ext


def _measure(stream) -> int:
    """Tamaño del stream en bytes, dejándolo rebobinado al inicio."""
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        return int(size)
    except (AttributeError, OSError):
        # Stream no buscable: se cuenta leyendo, con tope, y se sirve luego
        # desde el buffer que devolvemos rebobinado si se puede.
        total = 0
        limit = _max_size()
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                break
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            raise ValueError("No se pudo leer el archivo enviado")
        return total


def _unique_target(directory: Path, filename: str) -> Path:
    """``directory/filename`` o, si ya existe, ``nombre_1.ext``, ``nombre_2.ext``…

    El legacy sobrescribía sin avisar: dos usuarios subiendo ``evidencia.pdf``
    al mismo documento dejaban un solo archivo, y en indicadores —directorio
    plano compartido— el ``document_url`` del primer indicador acababa
    apuntando al archivo del segundo.
    """
    target = directory / filename
    if not target.exists():
        return target

    stem, dot, ext = filename.rpartition(".")
    stem = stem or filename
    for i in range(1, _MAX_NAME_ATTEMPTS):
        candidate = directory / (f"{stem}_{i}{dot}{ext}" if dot else f"{stem}_{i}")
        if not candidate.exists():
            return candidate
    raise ValueError("Demasiados archivos con el mismo nombre; renombra el archivo")


# ==========================================================================
# API pública
# ==========================================================================

def resolve_dir(kind: UploadKind, entity_id: Any, *, create: bool = False) -> Path:
    """Directorio absoluto de los adjuntos de una entidad.

    ``{ADHOC_UPLOAD_PATH}/{kind}/{entity_id}``, verificado con ``safe_join``.

    Args:
        kind: uno de ``documents`` | ``program_events`` | ``task_comments`` | ``indicators``.
        entity_id: PK de la entidad dueña (entero positivo).
        create: crea el árbol si no existe (solo en escritura).

    Raises:
        ValueError: kind desconocido, id inválido o ruta que escapa de la raíz.
    """
    kind = _check_kind(kind)
    entity_id = _check_entity_id(entity_id)
    try:
        target = safe_join(_root(), kind, str(entity_id))
    except UnsafePath as exc:
        raise ValueError(f"Ruta de adjunto inválida: {exc}") from exc

    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def save_upload(
    kind: UploadKind,
    entity_id: Any,
    upload: Any,
    *,
    max_size: Optional[int] = None,
) -> dict:
    """Guarda un archivo subido y devuelve sus metadatos para la BD.

    Args:
        kind: almacén destino (ver :data:`UPLOAD_KINDS`).
        entity_id: PK de la entidad dueña; el archivo va a su subdirectorio.
        upload: ``fastapi.UploadFile`` o cualquier objeto con ``.filename``,
            ``.file`` y (opcionalmente) ``.content_type``.
        max_size: override del límite en bytes; por defecto ``ADHOC_MAX_FILE_SIZE``.

    Returns:
        ``{"file_path": "{entity_id}/{nombre}", "original_name": str,
        "mime_type": str | None, "size_bytes": int}``.
        **``file_path`` es RELATIVO al kind** — es el valor que va a la columna.

    Raises:
        ValueError: nombre inválido o con traversal, extensión fuera de la
            whitelist, archivo vacío o por encima del límite de tamaño.
            Ninguna de estas rutas deja basura en disco.
    """
    filename, _ext = _check_upload_filename(getattr(upload, "filename", None))

    stream = getattr(upload, "file", None) or upload
    limit = int(max_size) if max_size else _max_size()
    size = _measure(stream)
    if size <= 0:
        raise ValueError("El archivo está vacío")
    if size > limit:
        raise ValueError(
            f"El archivo excede el tamaño máximo permitido "
            f"({limit // (1024 * 1024)}MB)"
        )

    directory = resolve_dir(kind, entity_id, create=True)
    target = _unique_target(directory, filename)

    try:
        with open(target, "wb") as fh:
            shutil.copyfileobj(stream, fh, _CHUNK)
    except OSError as exc:
        logger.exception("[adhoc] Error escribiendo adjunto en %s", target)
        # No dejar un archivo a medias.
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError("No se pudo guardar el archivo") from exc

    original_name = str(getattr(upload, "filename", filename))[:255]
    mime_type = getattr(upload, "content_type", None) or mimetypes.guess_type(target.name)[0]

    relative = f"{_check_entity_id(entity_id)}/{target.name}"
    logger.info("[adhoc] Adjunto guardado: %s/%s (%s bytes)", kind, relative, size)
    return {
        "file_path": relative,
        "original_name": original_name,
        "mime_type": mime_type,
        "size_bytes": size,
    }


def open_download(kind: UploadKind, entity_id: Any, filename: str) -> Path:
    """Ruta absoluta y verificada de un adjunto existente.

    Pensado para el endpoint de descarga: ``filename`` viene de la URL o de una
    columna, así que pasa por ``safe_join`` obligatoriamente.

    Raises:
        ValueError: ruta fuera de la raíz de uploads, o archivo inexistente.
    """
    directory = resolve_dir(kind, entity_id)
    if not filename or "\x00" in str(filename):
        raise ValueError("Nombre de archivo inválido")
    try:
        target = safe_join(directory, str(filename))
    except UnsafePath as exc:
        logger.warning("[adhoc] Descarga rechazada por ruta insegura: %s", exc)
        raise ValueError("Ruta de archivo inválida") from exc

    if not target.is_file():
        raise ValueError("El archivo no existe")
    return target


def open_stored(kind: UploadKind, stored_path: str) -> Path:
    """Igual que :func:`open_download`, pero desde el valor tal cual está en BD.

    ``stored_path`` es ``"{entity_id}/{filename}"`` (``AdhocDocument.file_url``,
    ``AdhocTaskComment.file_path``, ``AdhocProgramEventFile.file_path``,
    ``AdhocIndicator.document_url``). Se trata como **dato no confiable**: una
    fila envenenada por un bug previo no debe poder leer ``/etc/passwd``.
    """
    if not stored_path or not str(stored_path).strip():
        raise ValueError("El registro no tiene archivo asociado")

    parts = [p for p in str(stored_path).replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) != 2:
        raise ValueError(f"Ruta almacenada inválida: {stored_path!r}")
    entity_id, filename = parts
    return open_download(kind, entity_id, filename)


def delete_file(kind: UploadKind, stored_path: str) -> bool:
    """Borra el archivo apuntado por un valor de BD. Best-effort, nunca lanza.

    Devuelve ``True`` solo si se borró algo. El legacy no borraba nunca los
    archivos de eventos de programa (bug #18): quedaban huérfanos en disco al
    eliminar el evento.
    """
    try:
        target = open_stored(kind, stored_path)
    except ValueError:
        return False
    try:
        target.unlink()
        logger.info("[adhoc] Adjunto borrado: %s/%s", kind, stored_path)
        return True
    except OSError:
        logger.warning("[adhoc] No se pudo borrar el adjunto %s/%s", kind, stored_path)
        return False


class AdhocUploadService:
    """Fachada de clase (convención del repo). Delega en las funciones del módulo."""

    resolve_dir = staticmethod(resolve_dir)
    save_upload = staticmethod(save_upload)
    open_download = staticmethod(open_download)
    open_stored = staticmethod(open_stored)
    delete_file = staticmethod(delete_file)

"""Archivos de la revisión de sinodales (fase 5): validación y disco.

Solo PDF o Word (.docx, .doc). La firma del contenido manda sobre la extensión
(un .docx renombrado a .pdf se rechaza). Un .docx se reconoce abriéndolo como
ZIP en memoria y buscando alguna entrada ``word/…``; nunca se extrae nada.

Disco: ``{UPLOAD}/{period}/{control}/revision/``, hermana de ``documents/``
(``utils/storage.py``, cuyas utilidades reutiliza: raíz, ``safe_join`` y
escritura atómica). Módulo puro: sin BD.
"""
from __future__ import annotations

import io
import os
import re
import unicodedata
import zipfile
from pathlib import Path

from itcj2.apps.titulatec.utils import storage
from itcj2.config import get_settings

REVIEW_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
}

_MB = 1024 * 1024
_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
_PDF_MAGIC = b"%PDF-"
_CONTROL_RE = re.compile(r"[A-Za-z0-9]+")
_FILENAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")

_MSG_EMPTY = "El archivo está vacío."
_MSG_EXT = "Solo se aceptan archivos PDF o Word (.docx, .doc)."
_MSG_SIGNATURE = "El archivo no es un PDF o Word válido."


class ReviewFileError(ValueError):
    """Archivo de revisión no válido; el mensaje es para el usuario."""


def max_bytes() -> int:
    """Tope por archivo en bytes (lee la config en cada llamada)."""
    return get_settings().TITULATEC_REVIEW_MAX_FILE_MB * _MB


def review_days() -> int:
    """Días hábiles que dura la revisión de los sinodales (config, cada llamada)."""
    return int(get_settings().TITULATEC_REVIEW_DAYS)


def _ext_of(name: str) -> str:
    return os.path.splitext(name or "")[1].lstrip(".").lower()


def _is_docx(raw: bytes) -> bool:
    if not raw.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return any(n.startswith("word/") for n in z.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return False


def validate(raw: bytes, original_name: str) -> tuple[str, str]:
    """Valida el archivo y devuelve ``(extensión, mime)``; ``ReviewFileError`` si no pasa."""
    if not raw:
        raise ReviewFileError(_MSG_EMPTY)
    ext = _ext_of(original_name)
    if ext not in REVIEW_TYPES:
        raise ReviewFileError(_MSG_EXT)
    limit = max_bytes()
    if len(raw) > limit:
        raise ReviewFileError(f"El archivo supera {max(1, limit // _MB)} MB.")
    if ext == "pdf":
        ok = raw.startswith(_PDF_MAGIC)
    elif ext == "doc":
        ok = raw.startswith(_OLE_MAGIC)
    else:
        ok = _is_docx(raw)
    if not ok:
        raise ReviewFileError(_MSG_SIGNATURE)
    return ext, REVIEW_TYPES[ext]


def _check_ext(ext: str) -> str:
    if ext not in REVIEW_TYPES:
        raise ReviewFileError(_MSG_EXT)
    return ext


def _check_control(control: str) -> str:
    c = str(control or "")
    if not _CONTROL_RE.fullmatch(c):
        raise ReviewFileError("El número de control tiene caracteres no válidos.")
    return c


def version_filename(number: int, control: str, ext: str) -> str:
    """``v{number}_{control}.{ext}``: la versión N del documento del alumno."""
    return f"v{int(number)}_{_check_control(control)}.{_check_ext(ext)}"


def attachment_filename(message_id: int, control: str, ext: str) -> str:
    """``m{message_id}_{control}.{ext}``: adjunto de un mensaje del chat."""
    return f"m{int(message_id)}_{_check_control(control)}.{_check_ext(ext)}"


def write(raw: bytes, *, period_code: str, control_number: str, filename: str) -> str:
    """Escribe ``raw`` en ``{period}/{control}/revision/{filename}``; devuelve la ruta relativa.

    Anclada con ``safe_join`` (``../`` no escapa) y escritura atómica.
    """
    from itcj2.core.utils.safe_paths import UnsafePath, safe_join

    if not _FILENAME_RE.fullmatch(str(filename or "")) or ".." in filename:
        raise ReviewFileError("Nombre de archivo no válido.")
    if not str(period_code or "").strip() or not str(control_number or "").strip():
        raise ReviewFileError("Faltan el periodo o el número de control.")
    base = storage._base()
    try:
        folder = safe_join(base, str(period_code), str(control_number), "revision")
        target = safe_join(folder, filename)
    except UnsafePath as exc:
        raise ReviewFileError("No pudimos guardar el archivo.") from exc
    folder.mkdir(parents=True, exist_ok=True)
    storage._write_atomic(target, raw)
    return target.relative_to(Path(os.path.realpath(str(base)))).as_posix()


def disposition(ext: str) -> str:
    """``inline`` solo para PDF; Word siempre se descarga."""
    return "inline" if ext == "pdf" else "attachment"


def download_name(original_name: str, ext: str) -> str:
    """Nombre ASCII saneado para ``Content-Disposition``, con la extensión real."""
    base = re.split(r"[\\/]", str(original_name or ""))[-1]
    stem = os.path.splitext(base)[0]
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return f"{stem or 'revision'}.{_check_ext(ext)}"

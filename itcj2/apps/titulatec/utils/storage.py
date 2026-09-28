"""Almacenamiento de archivos de TitulaTec.

Estructura: instance/apps/titulatec/{period_code}/{control_number}/documents/{control_number}_{TIPO}.{ext}
- TIPO: ``ACTA``, ``CERTIFICADO``, ``CURP`` o el código del tipo en mayúsculas
  (``document_label``). Es el nombre con el que Servicios Escolares archiva el
  expediente; el nombre original que subió el alumno se queda en la BD
  (``Document.original_name``) pero ya no nombra nada.
- Solo se conserva la última versión (nombre fijo por tipo → sobreescribe).
- Imágenes: se comprimen con Pillow.
- PDFs (2026-09-28): hasta ``TITULATEC_MAX_PDF_SIZE`` (2 MB) se guardan intactos;
  entre ese tope y ``TITULATEC_MAX_PDF_UPLOAD_SIZE`` (20 MB) se comprimen
  (``utils/pdf_compress.py``) y solo se aceptan si bajan del tope.
"""
from __future__ import annotations

import io
import os
import re
from pathlib import Path, PurePosixPath

from itcj2.config import get_settings

_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
_PDF_EXTS = {"pdf"}
_MAX_IMAGE_DIM = 1920
_JPEG_QUALITY = 85
_MB = 1024 * 1024

# Etiqueta del archivo en disco y en la descarga. Los tres iniciales llevan el
# nombre corto con el que los conoce la ventanilla; el resto, su código en
# mayúsculas (EGEL_PROOF, INE, ANEXO_III, RESIDENCY_PROOF, FINAL_PROJECT...).
_DOCUMENT_LABELS = {
    "birth_certificate": "ACTA",
    "high_school_cert": "CERTIFICADO",
    "curp": "CURP",
}

# El número de control viene de `core_users.control_number`, que el importador
# de CSV escribe SIN validar (ver `process_documents_dir`). Para NOMBRAR un
# archivo solo se acepta alfanumérico ASCII: ni separadores, ni espacios, ni
# acentos. Si no casa, es error; no se inventa un nombre.
_CONTROL_RE = re.compile(r"[A-Za-z0-9]+")


def _base() -> Path:
    return Path(get_settings().TITULATEC_UPLOAD_PATH)


def process_documents_dir(period_code: str, control_number: str) -> Path:
    """Carpeta de documentos del alumno en una convocatoria (la crea si no existe).

    `control_number` viene de core_users.control_number, que el importador de CSV
    de TitulaTec escribe SIN validar (import_service.import_rows solo comprueba que
    no esté vacío), a diferencia de core/api/users_admin.py que sí aplica
    CONTROL_NUMBER_RE. Un valor con "../" convertiría este mkdir(parents=True) en
    creación y escritura de archivos fuera de instance/apps/titulatec/ — el mismo
    patrón que produjo el incidente de instance/apps/. safe_join lo ancla.
    """
    from itcj2.core.utils.safe_paths import safe_join

    d = safe_join(_base(), str(period_code), str(control_number), "documents")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext_of(filename: str) -> str:
    return (os.path.splitext(filename or "")[1].lstrip(".") or "").lower()


def _compress_image(raw: bytes, ext: str) -> tuple[bytes, str]:
    """Comprime una imagen: limita dimensión y recodifica. Devuelve (bytes, ext_final)."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)  # respeta orientación EXIF
    img.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM))

    out = io.BytesIO()
    if ext == "png":
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "png"
    if ext == "webp":
        img.save(out, format="WEBP", quality=_JPEG_QUALITY, method=6)
        return out.getvalue(), "webp"
    # jpg/jpeg → JPEG (aplana transparencia)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue(), "jpg"


class StorageError(Exception):
    pass


# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------
def document_label(type_code: str) -> str:
    """Etiqueta del tipo en el nombre de archivo: ACTA / CERTIFICADO / CURP / CÓDIGO."""
    return _DOCUMENT_LABELS.get(type_code, str(type_code).upper())


def _check_control(control_number: str) -> str:
    control = str(control_number or "")
    if not _CONTROL_RE.fullmatch(control):
        raise StorageError(
            "El número de control del alumno tiene caracteres no válidos; "
            "pide a Servicios Escolares que lo corrija antes de subir documentos."
        )
    return control


def document_filename(control_number: str, type_code: str, ext: str) -> str:
    """``{control}_{ETIQUETA}.{ext}``. ``StorageError`` si el control no es alfanumérico."""
    control = _check_control(control_number)
    return f"{control}_{document_label(type_code)}.{ext}"


def download_filename(control_number: str, type_code: str, file_path: str) -> str:
    """Nombre para el ``Content-Disposition`` de una descarga. Nunca falla.

    Mismo nombre que en disco (``document_filename``), calculado desde el
    control y el tipo — no desde el nombre real del archivo — para que un
    documento que todavía no pasó por ``rename-documents`` se descargue ya con
    el nombre nuevo. Con un control inválido (fila vieja que el importador
    dejó pasar) cae a la etiqueta sola: una descarga no se rompe por el nombre.
    """
    ext = _ext_of(file_path) or "pdf"
    try:
        return document_filename(control_number, type_code, ext)
    except StorageError:
        return f"{document_label(type_code)}.{ext}"


# ---------------------------------------------------------------------------
# Topes de PDF (siempre derivados de la config: nada de números literales)
# ---------------------------------------------------------------------------
def pdf_limits_mb() -> tuple[int, int]:
    """(tope guardado, máximo aceptado para comprimir), en MB enteros."""
    s = get_settings()
    return s.TITULATEC_MAX_PDF_SIZE // _MB, s.TITULATEC_MAX_PDF_UPLOAD_SIZE // _MB


def pdf_upload_hint() -> str:
    """Ayuda de la casilla de subida de un PDF."""
    max_mb, upload_mb = pdf_limits_mb()
    return (f"PDF de hasta {max_mb} MB. Si pesa más (hasta {upload_mb} MB), "
            "lo comprimimos automáticamente.")


def _mb1(size: int) -> str:
    return f"{size / _MB:.1f}"


def check_pdf_upload_size(size: int | None) -> None:
    """``StorageError`` si un PDF de ``size`` bytes excede lo que se acepta recibir.

    La ruta de subida la llama con ``UploadFile.size`` ANTES de leer el cuerpo;
    ``save_document`` la vuelve a aplicar sobre los bytes reales. ``None``
    (tamaño desconocido) no opina.
    """
    if size is None:
        return
    limit = get_settings().TITULATEC_MAX_PDF_UPLOAD_SIZE
    if size > limit:
        raise StorageError(
            f"Tu PDF pesa {_mb1(size)} MB; el máximo que aceptamos es {limit // _MB} MB."
        )


def _fit_pdf(raw: bytes) -> bytes:
    """Los bytes del PDF que se van a guardar, ya dentro del tope, o ``StorageError``.

    Supone ya aplicado ``check_pdf_upload_size`` (lo hace ``save_document``).
    """
    from itcj2.apps.titulatec.utils import pdf_compress

    target = get_settings().TITULATEC_MAX_PDF_SIZE
    if len(raw) <= target:
        return raw
    try:
        out = pdf_compress.compress_pdf(raw, target_bytes=target)
    except pdf_compress.PdfUnreadable as exc:
        raise StorageError(
            "No pudimos leer tu PDF; vuelve a generarlo o escanéalo de nuevo."
        ) from exc
    if out is None:
        raise StorageError(
            f"Tu PDF pesa {_mb1(len(raw))} MB y aun comprimido supera {target // _MB} MB; "
            "escanéalo en menor resolución o en blanco y negro."
        )
    return out


# ---------------------------------------------------------------------------
# Guardar / borrar
# ---------------------------------------------------------------------------
def _previous_versions(folder: Path, stems: set[str], target: Path) -> list[Path]:
    """Archivos de ``folder`` que son ``{stem}.*`` para algún stem, salvo ``target``.

    Equivale a ``folder.glob(f"{stem}.*")`` por cada stem, sin interpretar
    comodines en el nombre.
    """
    out = []
    for p in folder.iterdir():
        head, sep, _ = p.name.partition(".")
        if sep and head in stems and p != target and p.is_file():
            out.append(p)
    return out


def save_document(
    *,
    raw: bytes,
    original_name: str,
    content_type: str | None,
    period_code: str,
    control_number: str,
    type_code: str,
    file_kind: str,
) -> dict:
    """Guarda (sobreescribe) un documento. Devuelve metadata para el modelo Document.

    file_kind: 'pdf' | 'image'. Valida extensión y tamaño; comprime imágenes y
    los PDFs que pasan de ``TITULATEC_MAX_PDF_SIZE``.
    El nombre en disco es fijo: ``{control}_{ETIQUETA}.{ext}`` (solo última versión).
    Todo lo que puede fallar se valida ANTES de crear la carpeta: un error no
    deja nada en disco.
    Retorna: {file_path (relativo a TITULATEC_UPLOAD_PATH), original_name, mime_type,
    size_bytes (del archivo GUARDADO)}.
    """
    settings = get_settings()
    ext = _ext_of(original_name)

    if file_kind == "pdf":
        if ext not in _PDF_EXTS:
            raise StorageError("Solo se permiten archivos PDF para este documento.")
        check_pdf_upload_size(len(raw))
        _check_control(control_number)          # antes de gastar CPU comprimiendo
        data, final_ext, mime = _fit_pdf(raw), "pdf", "application/pdf"
    elif file_kind == "image":
        if ext not in _IMAGE_EXTS:
            raise StorageError("Formato de imagen no permitido (jpg, png, webp).")
        if len(raw) > settings.TITULATEC_MAX_IMAGE_SIZE:
            mb = settings.TITULATEC_MAX_IMAGE_SIZE // _MB
            raise StorageError(f"La imagen excede el tamaño máximo ({mb} MB).")
        _check_control(control_number)
        data, final_ext = _compress_image(raw, ext)
        mime = f"image/{'jpeg' if final_ext == 'jpg' else final_ext}"
    else:
        raise StorageError(f"file_kind inválido: {file_kind}")

    filename = document_filename(control_number, type_code, final_ext)
    target = process_documents_dir(period_code, control_number) / filename
    # Borra cualquier versión previa del MISMO tipo: la de antes de 2026-09-28
    # (`{type_code}.*`) y la del nombre nuevo con otra extensión.
    stems = {str(type_code), filename.rsplit(".", 1)[0]}
    for prev in _previous_versions(target.parent, stems, target):
        prev.unlink(missing_ok=True)
    target.write_bytes(data)

    rel = target.relative_to(_base()).as_posix()
    return {
        "file_path": rel,
        "original_name": original_name,
        "mime_type": mime,
        "size_bytes": len(data),
    }


def delete_document_file(file_path: str) -> None:
    """Borra el archivo físico dado su path relativo a TITULATEC_UPLOAD_PATH."""
    if not file_path:
        return
    p = _base() / file_path
    p.unlink(missing_ok=True)


def abs_path(file_path: str) -> Path:
    """Ruta absoluta de un archivo relativo a TITULATEC_UPLOAD_PATH."""
    return _base() / file_path


def safe_abs_path(file_path: str) -> Path:
    """Como ``abs_path`` pero anclada con ``safe_join`` (``UnsafePath`` si escapa)."""
    from itcj2.core.utils.safe_paths import safe_join

    return safe_join(_base(), *PurePosixPath(file_path).parts)

"""Almacenamiento de archivos de TitulaTec.

Estructura: instance/apps/titulatec/{period_code}/{control_number}/documents/{type_code}.{ext}
- Solo se conserva la última versión (nombre fijo por tipo → sobreescribe).
- Imágenes: se comprimen con Pillow. PDFs: se valida tamaño (no se recomprime).
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from itcj2.config import get_settings

_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
_PDF_EXTS = {"pdf"}
_MAX_IMAGE_DIM = 1920
_JPEG_QUALITY = 85


def _base() -> Path:
    return Path(get_settings().TITULATEC_UPLOAD_PATH)


def process_documents_dir(period_code: str, control_number: str) -> Path:
    """Carpeta de documentos del alumno en una convocatoria (la crea si no existe)."""
    d = _base() / str(period_code) / str(control_number) / "documents"
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

    file_kind: 'pdf' | 'image'. Valida extensión y tamaño; comprime imágenes.
    El nombre en disco es fijo: ``{type_code}.{ext}`` (solo última versión).
    Retorna: {file_path (relativo a TITULATEC_UPLOAD_PATH), original_name, mime_type, size_bytes}.
    """
    settings = get_settings()
    ext = _ext_of(original_name)

    if file_kind == "pdf":
        if ext not in _PDF_EXTS:
            raise StorageError("Solo se permiten archivos PDF para este documento.")
        if len(raw) > settings.TITULATEC_MAX_PDF_SIZE:
            mb = settings.TITULATEC_MAX_PDF_SIZE // (1024 * 1024)
            raise StorageError(f"El PDF excede el tamaño máximo ({mb} MB).")
        data, final_ext, mime = raw, "pdf", "application/pdf"
    elif file_kind == "image":
        if ext not in _IMAGE_EXTS:
            raise StorageError("Formato de imagen no permitido (jpg, png, webp).")
        if len(raw) > settings.TITULATEC_MAX_IMAGE_SIZE:
            mb = settings.TITULATEC_MAX_IMAGE_SIZE // (1024 * 1024)
            raise StorageError(f"La imagen excede el tamaño máximo ({mb} MB).")
        data, final_ext = _compress_image(raw, ext)
        mime = f"image/{'jpeg' if final_ext == 'jpg' else final_ext}"
    else:
        raise StorageError(f"file_kind inválido: {file_kind}")

    target = process_documents_dir(period_code, control_number) / f"{type_code}.{final_ext}"
    # Borra cualquier versión previa con otra extensión (p.ej. cambió de png a jpg)
    for prev in target.parent.glob(f"{type_code}.*"):
        if prev != target:
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

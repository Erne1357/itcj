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

Dos pasos (revisión 2026-09-28, m1): ``prepare_document`` valida y comprime
(CPU, segundos; sin disco ni BD) y ``write_document`` escribe. Así la ruta de
subida comprime SIN una transacción abierta y solo después persiste.
``save_document`` hace los dos seguidos, para quien no necesite separarlos.
La escritura es atómica (temporal + ``os.replace``) y las versiones viejas se
borran solo DESPUÉS de escribir la nueva (m5).
"""
from __future__ import annotations

import io
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from itcj2.config import get_settings

_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}
_PDF_EXTS = {"pdf"}
_MAX_IMAGE_DIM = 1920
_JPEG_QUALITY = 85
_MB = 1024 * 1024

# Etiqueta del archivo en disco y en la descarga. Los documentos iniciales --
# los 3 de licenciatura y los 4 extras de posgrado (spec 2026-09-30-titulatec-
# posgrado-design.md §4.4) -- llevan el nombre corto con el que los conoce la
# ventanilla; el resto, su código en mayúsculas (EGEL_PROOF, INE, ANEXO_III,
# RESIDENCY_PROOF, FINAL_PROJECT...).
_DOCUMENT_LABELS = {
    "birth_certificate": "ACTA",
    "high_school_cert": "CERTIFICADO",
    "curp": "CURP",
    "professional_license": "CEDULA",
    "degree_title": "TITULO",
    "postgrad_authorization": "OFICIOS",
    "efirma_sat": "EFIRMA",
}

# El número de control viene de `core_users.control_number`, que el importador
# de CSV escribe SIN validar (ver `process_documents_dir`). Para NOMBRAR un
# archivo solo se acepta alfanumérico ASCII: ni separadores, ni espacios, ni
# acentos. Si no casa, es error; no se inventa un nombre.
_CONTROL_RE = re.compile(r"[A-Za-z0-9]+")

# El tipo sale del catálogo (DML): minúsculas, dígitos y guion bajo. Un código
# fuera de ese patrón no nombra ningún archivo (m7).
_TYPE_CODE_RE = re.compile(r"[a-z0-9_]+")
_EXT_RE = re.compile(r"[a-z0-9]+")


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
    """Etiqueta del tipo en el nombre de archivo: ACTA / CERTIFICADO / CURP / CÓDIGO.

    ``StorageError`` si el código no casa ``^[a-z0-9_]+$``.
    """
    code = str(type_code or "")
    if not _TYPE_CODE_RE.fullmatch(code):
        raise StorageError("Tipo de documento no válido.")
    return _DOCUMENT_LABELS.get(code, code.upper())


def _check_control(control_number: str) -> str:
    control = str(control_number or "")
    if not _CONTROL_RE.fullmatch(control):
        raise StorageError(
            "El número de control del alumno tiene caracteres no válidos; "
            "pide a Servicios Escolares que lo corrija antes de subir documentos."
        )
    return control


def document_filename(control_number: str, type_code: str, ext: str) -> str:
    """``{control}_{ETIQUETA}.{ext}``.

    ``StorageError`` si el control no es alfanumérico, el tipo no casa
    ``^[a-z0-9_]+$`` o la extensión no es alfanumérica.
    """
    control = _check_control(control_number)
    label = document_label(type_code)
    if not _EXT_RE.fullmatch(str(ext or "")):
        raise StorageError("Extensión de archivo no válida.")
    return f"{control}_{label}.{ext}"


def download_filename(control_number: str, type_code: str, file_path: str) -> str:
    """Nombre para el ``Content-Disposition`` de una descarga. Nunca falla.

    Mismo nombre que en disco (``document_filename``), calculado desde el
    control y el tipo — no desde el nombre real del archivo — para que un
    documento que todavía no pasó por ``rename-documents`` se descargue ya con
    el nombre nuevo. Con un control inválido (fila vieja que el importador
    dejó pasar) cae a la etiqueta sola, y con un tipo inválido a
    ``documento``: una descarga no se rompe por el nombre.
    """
    ext = _ext_of(file_path)
    if not _EXT_RE.fullmatch(ext):
        ext = "pdf"
    try:
        return document_filename(control_number, type_code, ext)
    except StorageError:
        pass
    try:
        return f"{document_label(type_code)}.{ext}"
    except StorageError:
        return f"documento.{ext}"


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
    """MB con un decimal, redondeado HACIA ARRIBA (m8).

    Con redondeo normal, 20 MB + 1 byte decía «pesa 20.0 MB; el máximo es
    20 MB». Hacia arriba, lo que pasa del tope siempre se ve mayor que el tope.
    Aritmética entera: sin errores de coma flotante en el décimo.
    """
    tenths = -(-int(size) * 10 // _MB)
    return f"{tenths // 10}.{tenths % 10}"


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


@dataclass(frozen=True)
class PreparedDocument:
    """Bytes ya validados (y comprimidos si hacía falta), listos para escribir."""

    data: bytes
    ext: str
    mime_type: str
    original_name: str
    file_kind: str


def prepare_document(
    *,
    raw: bytes,
    original_name: str,
    control_number: str,
    file_kind: str,
) -> PreparedDocument:
    """Valida y comprime un documento. Solo CPU: no toca el disco ni la BD.

    file_kind: 'pdf' | 'image'. Valida extensión, tamaño y número de control
    (antes de gastar CPU comprimiendo); comprime imágenes y los PDFs que pasan
    de ``TITULATEC_MAX_PDF_SIZE``. ``StorageError`` con el mensaje para el
    alumno si algo no pasa.
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

    return PreparedDocument(data=data, ext=final_ext, mime_type=mime,
                            original_name=original_name, file_kind=file_kind)


def _write_atomic(target: Path, data: bytes) -> None:
    """Escribe ``data`` en ``target`` sin dejarlo nunca a medias (m5).

    Va a un temporal en la MISMA carpeta (``.{nombre}.{azar}.tmp``, creado en
    exclusiva y con los permisos normales del proceso) y se renombra con
    ``os.replace``, que es atómico: quien lea ``target`` ve el archivo anterior
    completo o el nuevo completo. Si algo falla, el temporal se borra y
    ``target`` queda como estaba.
    """
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(6)}.tmp")
    try:
        with open(tmp, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_document(
    prepared: PreparedDocument,
    *,
    period_code: str,
    control_number: str,
    type_code: str,
) -> dict:
    """Escribe un documento ya preparado. Devuelve metadata para el modelo Document.

    El nombre en disco es fijo: ``{control}_{ETIQUETA}.{ext}`` (solo última
    versión), anclado con ``safe_join`` en la carpeta del alumno. El nombre se
    valida ANTES de crear la carpeta. La escritura es atómica y las versiones
    previas del MISMO tipo — la de antes de 2026-09-28 (``{type_code}.*``) y la
    del nombre nuevo con otra extensión — se borran solo DESPUÉS de escribir la
    nueva: si la escritura falla, lo anterior sigue en su lugar.
    Retorna: {file_path (relativo a TITULATEC_UPLOAD_PATH), original_name,
    mime_type, size_bytes (del archivo GUARDADO)}.
    """
    from itcj2.core.utils.safe_paths import UnsafePath, safe_join

    filename = document_filename(control_number, type_code, prepared.ext)
    folder = process_documents_dir(period_code, control_number)
    try:
        target = safe_join(folder, filename)
    except UnsafePath as exc:
        raise StorageError(
            "No pudimos guardar el documento; avisa a Servicios Escolares."
        ) from exc

    _write_atomic(target, prepared.data)

    stems = {str(type_code), target.name.rsplit(".", 1)[0]}
    for prev in _previous_versions(folder, stems, target):
        prev.unlink(missing_ok=True)

    rel = target.relative_to(_base()).as_posix()
    return {
        "file_path": rel,
        "original_name": prepared.original_name,
        "mime_type": prepared.mime_type,
        "size_bytes": len(prepared.data),
    }


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
    """Guarda (sobreescribe) un documento: ``prepare_document`` + ``write_document``.

    Todo lo que puede fallar se valida ANTES de crear la carpeta: un error de
    validación no deja nada en disco. Retorna lo mismo que ``write_document``.
    """
    prepared = prepare_document(raw=raw, original_name=original_name,
                                control_number=control_number, file_kind=file_kind)
    return write_document(prepared, period_code=period_code,
                          control_number=control_number, type_code=type_code)


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

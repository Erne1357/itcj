"""Compresión de PDFs escaneados para TitulaTec (tope de 2 MB por documento).

Una sola responsabilidad: recibir los bytes de un PDF y devolver unos bytes que
quepan en ``target_bytes``, o decir que no se puede. No sabe de rutas, de BD ni
de mensajes al alumno (eso es de ``utils/storage.py``). Todo ocurre en memoria:
nunca escribe en disco.

Por qué así (brief 2026-09-28, documentos a 2 MB): lo que pesa en un PDF de
acta/certificado/CURP es la imagen del escaneo, no el texto. Casi siempre viene
a 300-600 dpi, cuando para leerlo en pantalla o imprimirlo basta con 150. Así
que la compresión es de imágenes: cada una se lleva a la resolución de la
pasada, medida contra el tamaño de la PÁGINA (lo que el alumno ve), y se
recodifica en JPEG. Las pasadas van de la más suave a la más fuerte y gana la
primera que cabe, para no degradar más de lo necesario.

pypdf se importa PEREZOSAMENTE dentro de las funciones: este módulo lo importa
``storage.py``, que está en la ruta de cualquier subida, y pypdf solo hace falta
cuando un PDF pasa del tope.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# (dpi, calidad JPEG), de la más suave a la más fuerte. Se devuelve la PRIMERA
# cuyo resultado quepa en el objetivo.
PASSES: tuple[tuple[int, int], ...] = ((150, 75), (110, 60), (96, 50))

_POINTS_PER_INCH = 72


class PdfUnreadable(Exception):
    """El PDF no se puede abrir: bytes que no son PDF, truncado o cifrado."""


def compress_pdf(raw: bytes, *, target_bytes: int) -> bytes | None:
    """Devuelve ``raw`` comprimido a ``<= target_bytes``, o ``None`` si no se puede.

    - ``len(raw) <= target_bytes`` → devuelve ``raw`` tal cual (el mismo objeto;
      ni siquiera se lee).
    - Si no, prueba ``PASSES`` en orden y devuelve la primera que quepa.
    - Si ninguna cabe → ``None``.
    - PDF ilegible, cifrado o que pypdf no puede abrir → ``PdfUnreadable``.
    """
    if target_bytes <= 0:
        raise ValueError("target_bytes debe ser positivo")
    if len(raw) <= target_bytes:
        return raw

    for dpi, quality in PASSES:
        out = _one_pass(raw, dpi=dpi, quality=quality)
        logger.debug("compress_pdf: %s dpi q%s -> %s bytes (objetivo %s)",
                     dpi, quality, len(out), target_bytes)
        if len(out) <= target_bytes:
            return out
    return None


def _one_pass(raw: bytes, *, dpi: int, quality: int) -> bytes:
    """Una pasada completa sobre una copia fresca del original.

    Cada pasada parte de ``raw`` y no de la anterior: recomprimir un JPEG ya
    recomprimido acumula pérdida sin necesidad.
    """
    from pypdf import PdfReader, PdfWriter

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfUnreadable("PDF cifrado")
        writer = PdfWriter(clone_from=reader)
        pages = list(writer.pages)
    except PdfUnreadable:
        raise
    except Exception as exc:   # pypdf levanta de todo ante bytes rotos
        raise PdfUnreadable(str(exc)) from exc

    for page in pages:
        limit = _pixel_limit(page, dpi)
        if limit:
            _shrink_page_images(page, limit=limit, quality=quality)
        try:
            page.compress_content_streams()
        except Exception as exc:
            logger.debug("compress_pdf: no se comprimió un content stream: %s", exc)

    try:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except Exception as exc:
        logger.debug("compress_pdf: no se compactaron objetos: %s", exc)

    try:
        buf = io.BytesIO()
        writer.write(buf)
    except Exception as exc:
        raise PdfUnreadable(str(exc)) from exc
    return buf.getvalue()


def _pixel_limit(page, dpi: int) -> int | None:
    """Tamaño máximo, en píxeles, del lado mayor de una imagen de esta página.

    Es el lado MAYOR de la página (mediabox / 72 = pulgadas) por los dpi de la
    pasada, y se aplica a ambos lados de la imagen: así una imagen apaisada
    colocada girada en una página vertical no se reduce de más (con un límite
    por eje, su lado largo se toparía contra el ancho de la página).
    """
    try:
        box = page.mediabox
        side_pt = max(abs(float(box.width)), abs(float(box.height)))
    except Exception:
        return None
    if side_pt <= 0:
        return None
    return max(1, round(side_pt / _POINTS_PER_INCH * dpi))


def _shrink_page_images(page, *, limit: int, quality: int) -> None:
    """Reduce y recodifica las imágenes de la página que pasan de ``limit``.

    Cualquier imagen que pypdf o Pillow no puedan decodificar (CCITT raros,
    JBIG2, máscaras exóticas, datos corruptos) o reemplazar (imágenes inline)
    se deja COMO ESTÁ: una imagen difícil no debe tumbar la compresión del
    resto del documento.
    """
    try:
        images = page.images
        count = len(images)
    except Exception as exc:
        logger.debug("compress_pdf: no se listaron las imágenes de la página: %s", exc)
        return

    for i in range(count):
        try:
            item = images[i]
            pil = item.image
            if pil is None or max(pil.size) <= limit:
                continue
            prepared = _for_jpeg(pil)
            if prepared is None:
                continue
            prepared.thumbnail((limit, limit))
            item.replace(prepared, quality=quality)
        except Exception as exc:
            logger.debug("compress_pdf: imagen %s se deja como está: %s", i, exc)


def _for_jpeg(img):
    """Imagen lista para JPEG, o ``None`` si conviene dejarla como está.

    - RGBA / LA / P / PA → RGB aplanada sobre blanco (JPEG no tiene alfa).
    - L (escala de grises) → se queda en L: un escaneo en grises pesa un tercio.
    - 1 (bitonal) → ``None``: ya viene en CCITT/Flate, que a un bit por píxel
      pesa menos que cualquier JPEG; convertirlo lo haría crecer.
    - RGB se queda; cualquier otro modo (CMYK, 16 bits…) → RGB.

    Siempre devuelve una COPIA: ``thumbnail`` trabaja en sitio.
    """
    from PIL import Image

    mode = img.mode
    if mode == "1":
        return None
    if mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    if mode in ("L", "RGB"):
        return img.copy()
    return img.convert("RGB")

"""Compresión de PDFs escaneados para TitulaTec (tope de 2 MB por documento).

Una sola responsabilidad: recibir los bytes de un PDF y devolver unos bytes que
quepan en ``target_bytes``, o decir que no se puede. No sabe de rutas, de BD ni
de mensajes al alumno (eso es de ``utils/storage.py``). Todo ocurre en memoria:
nunca escribe en disco.

Por qué así (brief 2026-09-28, documentos a 2 MB): lo que pesa en un PDF de
acta/certificado/CURP es la imagen del escaneo, no el texto. Casi siempre viene
a 300-600 dpi, cuando para leerlo en pantalla o imprimirlo basta con 150. Así
que la compresión es de imágenes, en pasadas de la más suave a la más fuerte
(gana la primera que cabe, para no degradar más de lo necesario). En cada
pasada, cada imagen:

- se reduce si su lado largo pasa del MENOR de dos límites: el relativo a la
  página (lado mayor de la página en pulgadas × dpi de la pasada) y un tope
  ABSOLUTO en px (≈ lado largo de un A4 a esos dpi). El tope absoluto existe
  por los «foto → PDF» (iPhone «Crear PDF», Vista Previa, img2pdf, apps de
  escaneo): hacen la página del tamaño de la foto a 72 dpi (~42×56″), así que
  el límite de la página nunca la tocaba (revisión 2026-09-28, R1);
- se recodifica en JPEG a la calidad de la pasada AUNQUE ya quepa, salvo que ya
  sea un JPEG a esa calidad o menor: un escaneo guardado sin pérdida (Flate) o
  en JPEG q95 no baja de otra forma (R1). Si el JPEG nuevo no pesa menos que el
  stream original, la imagen se deja como está (una gráfica plana en Flate
  pesa menos que en JPEG);
- lo bitonal (1 bit, máscaras) nunca se toca: en JPEG crecería;
- lo de paleta (``/Indexed``) nunca se toca: pypdf puede leerlo mal (NEGRO,
  con ``/ASCIIHexDecode``) y el JPEG negro pesa menos, así que se aceptaba
  en silencio (revisión 2026-09-28, ronda 2);
- guarda de sanidad para cualquier otra mala lectura: si la imagen
  decodificada es de un solo color y el stream original pesa más de
  ``UNIFORM_SUSPECT_BYTES``, se deja la original (ronda 2).

Memoria (m2): un JPEG se decodifica ya reducido con ``Image.draft`` (la
biblioteca escala al decodificar por 1/2, 1/4 u 1/8), y una imagen que declara
más de ``MAX_IMAGE_PIXELS`` píxeles (/Width × /Height) ni se decodifica: se deja
como está. Ese tope es propio y no depende de ``PIL.Image.MAX_IMAGE_PIXELS``.

La imagen nueva se escribe EN SITIO sobre el stream del XObject (mismo objeto
indirecto, así que cada página o Form que la usa ve la nueva): datos JPEG,
``/DCTDecode``, medidas y espacio de color; se quitan ``/SMask``, ``/Decode``
y compañía, que ya no aplican a los píxeles aplanados.

pypdf y Pillow se importan PEREZOSAMENTE dentro de las funciones: este módulo
lo importa ``storage.py``, que está en la ruta de cualquier subida, y solo hacen
falta cuando un PDF pasa del tope.
"""
from __future__ import annotations

import io
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class _Pass(NamedTuple):
    dpi: int        # límite relativo a la página: lado mayor (pulgadas) × dpi
    quality: int    # calidad JPEG de la recodificación
    max_px: int     # tope ABSOLUTO del lado largo de una imagen (≈ A4 a esos dpi)


# De la más suave a la más fuerte. Se devuelve la PRIMERA que quepa.
# max_px = round(841.89 pt / 72 × dpi): el lado largo de un A4 a esos dpi.
PASSES: tuple[_Pass, ...] = (
    _Pass(dpi=150, quality=75, max_px=1754),
    _Pass(dpi=110, quality=60, max_px=1286),
    _Pass(dpi=96, quality=50, max_px=1123),
)

# Una imagen que declara más píxeles que esto se deja como está, sin
# decodificarla: ~150 MB en RGB. Cubre de sobra un escaneo a 600 dpi de una
# hoja oficio (5100 × 8400 = 43 MP).
MAX_IMAGE_PIXELS = 50_000_000

# Una imagen que se decodifica de UN SOLO color no reemplaza a la original si
# el stream original (más su SMask) pesa más que esto: una imagen de verdad
# lisa se comprime a casi nada, así que un stream grande con resultado liso es
# una mala decodificación (ronda 2). Dejarla nunca la corrompe; si por eso el
# PDF no cabe, se rechaza con el mensaje de siempre.
UNIFORM_SUSPECT_BYTES = 4 * 1024

_POINTS_PER_INCH = 72

# Tabla de cuantización de luminancia del estándar JPEG (ITU T.81, anexo K),
# la que libjpeg escala según la calidad. Sirve para estimar con qué calidad se
# guardó un JPEG sin decodificarlo.
_STD_LUMA_QTABLE = (
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
)

# Claves del XObject que describen los píxeles VIEJOS y no aplican al JPEG nuevo.
_STALE_IMAGE_KEYS = ("/DecodeParms", "/Decode", "/SMask", "/Mask", "/SMaskInData",
                     "/ImageMask", "/Filter")


class PdfUnreadable(Exception):
    """El PDF no se puede abrir: bytes que no son PDF, truncado o cifrado."""


def compress_pdf(raw: bytes, *, target_bytes: int) -> bytes | None:
    """Devuelve ``raw`` comprimido a ``<= target_bytes``, o ``None`` si no se puede.

    - ``len(raw) <= target_bytes`` → devuelve ``raw`` tal cual (el mismo objeto;
      ni siquiera se lee).
    - Si no, prueba ``PASSES`` en orden y devuelve la primera que quepa.
    - Si ninguna cabe → ``None``.
    - PDF ilegible, cifrado o que pypdf no puede abrir → ``PdfUnreadable``.
    - Nunca devuelve un PDF con otro número de páginas: si el resultado que
      cabe no conserva las páginas del original, ``PdfUnreadable``.
    """
    if target_bytes <= 0:
        raise ValueError("target_bytes debe ser positivo")
    if len(raw) <= target_bytes:
        return raw

    pages = _page_count(raw)
    for p in PASSES:
        out = _one_pass(raw, p)
        logger.debug("compress_pdf: %s dpi q%s tope %s px -> %s bytes (objetivo %s)",
                     p.dpi, p.quality, p.max_px, len(out), target_bytes)
        if len(out) <= target_bytes:
            if _page_count(out) != pages:
                raise PdfUnreadable("el resultado no conserva las páginas del original")
            return out
    return None


def _open_reader(raw: bytes):
    """``PdfReader`` sobre ``raw``, o ``PdfUnreadable`` (basura, truncado, cifrado)."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise PdfUnreadable("PDF cifrado")
        return reader
    except PdfUnreadable:
        raise
    except Exception as exc:   # pypdf levanta de todo ante bytes rotos
        raise PdfUnreadable(str(exc)) from exc


def _page_count(raw: bytes) -> int:
    reader = _open_reader(raw)
    try:
        return len(reader.pages)
    except Exception as exc:
        raise PdfUnreadable(str(exc)) from exc


def _one_pass(raw: bytes, p: _Pass) -> bytes:
    """Una pasada completa sobre una copia fresca del original.

    Cada pasada parte de ``raw`` y no de la anterior: recomprimir un JPEG ya
    recomprimido acumula pérdida sin necesidad.
    """
    from pypdf import PdfWriter

    reader = _open_reader(raw)
    try:
        writer = PdfWriter(clone_from=reader)
        pages = list(writer.pages)
    except Exception as exc:
        raise PdfUnreadable(str(exc)) from exc

    done: set[int] = set()        # XObjects ya tratados (una imagen puede repetirse)
    for page in pages:
        limit = _pixel_limit(page, p)
        for path, obj in _page_images(page):
            key = id(obj)
            if key in done:
                continue
            done.add(key)
            try:
                _recode_image(page, path, obj, limit=limit, quality=p.quality)
            except Exception as exc:
                logger.debug("compress_pdf: imagen %s se deja como está: %s", path, exc)
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


def _pixel_limit(page, p: _Pass) -> int:
    """Tamaño máximo, en píxeles, del lado mayor de una imagen de esta página.

    El MENOR entre el tope absoluto de la pasada y el lado MAYOR de la página
    (mediabox / 72 = pulgadas) por los dpi de la pasada. Se aplica a ambos lados
    de la imagen: así una imagen apaisada colocada girada en una página vertical
    no se reduce de más (con un límite por eje, su lado largo se toparía contra
    el ancho de la página). Sin mediabox legible, manda el tope absoluto.
    """
    try:
        box = page.mediabox
        side_pt = max(abs(float(box.width)), abs(float(box.height)))
    except Exception:
        return p.max_px
    if side_pt <= 0:
        return p.max_px
    return max(1, min(p.max_px, round(side_pt / _POINTS_PER_INCH * p.dpi)))


def _resolved(value):
    return value.get_object() if value is not None and hasattr(value, "get_object") else value


def _page_images(page) -> list[tuple[list[str], object]]:
    """(ruta, stream) de cada XObject de imagen de la página, también dentro de Forms.

    La ruta es la lista de nombres desde los recursos de la página (``["/Im0"]``
    o ``["/Fm0", "/Im0"]``): es la clave que acepta ``page.images[...]``. Las
    imágenes inline no aparecen: no se pueden reemplazar.
    """
    from pypdf.generic import StreamObject

    out: list[tuple[list[str], object]] = []
    seen_forms: set[int] = set()

    def walk(holder, path: list[str]) -> None:
        try:
            resources = _resolved(holder.get("/Resources"))
            xobjs = _resolved(resources.get("/XObject")) if resources else None
            names = list(xobjs.keys()) if isinstance(xobjs, dict) else []
        except Exception:
            return
        for name in names:
            try:
                obj = _resolved(xobjs.raw_get(name))
            except Exception:
                continue
            if not isinstance(obj, StreamObject):
                continue
            subtype = obj.get("/Subtype")
            if subtype == "/Image":
                out.append(([*path, str(name)], obj))
            elif subtype == "/Form" and id(obj) not in seen_forms:
                seen_forms.add(id(obj))
                walk(obj, [*path, str(name)])

    walk(page, [])
    return out


def _filters(obj) -> list[str]:
    f = _resolved(obj.get("/Filter"))
    if f is None:
        return []
    if isinstance(f, (list, tuple)):
        return [str(_resolved(x)) for x in f]
    return [str(f)]


def _is_bilevel(obj) -> bool:
    """1 bit por pixel o máscara de estencil: CCITT/JBIG2/Flate ganan a JPEG."""
    if bool(_resolved(obj.get("/ImageMask", False))):
        return True
    if _resolved(obj.get("/BitsPerComponent")) == 1:
        return True
    return any(f in ("/CCITTFaxDecode", "/JBIG2Decode") for f in _filters(obj))


def _is_indexed(obj) -> bool:
    """Espacio de color de paleta: ``/Indexed`` como nombre o como arreglo que
    empieza con ``/Indexed``, aunque venga por referencia indirecta.

    pypdf 6.19 decodifica NEGRA una ``/Indexed`` con ``/ASCIIHexDecode`` (así
    la escribe Pillow en modo P: índices y paleta en cero), y ese JPEG negro
    pesa menos que el original. Lo que se lee de una paleta no es confiable:
    se deja como está (ronda 2).
    """
    cs = _resolved(obj.get("/ColorSpace"))
    if isinstance(cs, (list, tuple)):
        cs = _resolved(cs[0]) if cs else None
    return str(cs) == "/Indexed"


def _is_uniform(img) -> bool:
    """La imagen es de un solo color: ningún canal varía (``getextrema``)."""
    extrema = img.getextrema()
    if not isinstance(extrema[0], tuple):       # un solo canal: (min, max)
        extrema = (extrema,)
    return all(lo == hi for lo, hi in extrema)


def _encoded_len(obj) -> int:
    """Bytes que ocupa hoy la imagen en el archivo (con su SMask, que se pierde)."""
    size = len(getattr(obj, "_data", b"") or b"")
    smask = _resolved(obj.get("/SMask"))
    if smask is not None:
        size += len(getattr(smask, "_data", b"") or b"")
    return size


def _recode_image(page, path: list[str], obj, *, limit: int, quality: int) -> None:
    """Reduce y/o recodifica en JPEG una imagen, en sitio, si con eso pesa menos.

    Cualquier imagen que no se pueda decodificar (CCITT raros, JBIG2, datos
    corruptos) lanza y el llamador la deja COMO ESTÁ: una imagen difícil no debe
    tumbar la compresión del resto del documento.
    """
    if _is_bilevel(obj) or _is_indexed(obj):
        return
    width = int(_resolved(obj.get("/Width")) or 0)
    height = int(_resolved(obj.get("/Height")) or 0)
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        return
    needs_resize = max(width, height) > limit

    pil = None
    if _filters(obj) == ["/DCTDecode"]:
        from PIL import Image

        jpeg = Image.open(io.BytesIO(obj.get_data()))       # solo lee cabeceras
        if jpeg.size[0] * jpeg.size[1] > MAX_IMAGE_PIXELS:
            return
        if not needs_resize:
            q = _jpeg_quality(jpeg)
            if q is not None and q <= quality:
                return          # ya es un JPEG a esta calidad o menor y cabe
        pil = _decode_jpeg_reduced(jpeg, obj, limit)
    if pil is None:
        pil = _decode_with_pypdf(page, path)
    if pil is None:
        return

    prepared = _for_jpeg(pil)
    if prepared is None:
        return
    if _is_uniform(prepared) and _encoded_len(obj) > UNIFORM_SUSPECT_BYTES:
        # Un solo color salido de un stream que no es trivial: casi seguro una
        # mala decodificación (ronda 2). El JPEG pesaría casi nada y la guarda
        # de abajo lo aceptaría: el documento quedaría en negro sin avisar.
        logger.debug("compress_pdf: imagen %s decodificada de un solo color; "
                     "se deja como está", path)
        return
    if max(prepared.size) > limit:
        prepared.thumbnail((limit, limit))
    buf = io.BytesIO()
    # optimize: tablas Huffman a la medida (unos % menos, misma calidad).
    prepared.save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    if len(data) >= _encoded_len(obj):
        return                  # el JPEG no gana nada: se queda la original
    _put_jpeg(obj, data, prepared)


def _decode_with_pypdf(page, path: list[str]):
    """Decodifica con pypdf lo que no es un JPEG «simple» (Flate, JPX, CMYK, con
    SMask, con /Decode...): pypdf sabe aplicar espacios de color y máscaras."""
    return page.images[path if len(path) > 1 else path[0]].image


def _decode_jpeg_reduced(jpeg, obj, limit: int):
    """Decodifica un JPEG «simple» ya reducido (``draft``), o ``None`` si no lo es.

    Simple = gris o RGB, sin ``/SMask``/``/Mask``/``/Decode`` y en un espacio de
    color directo: ahí los píxeles del JPEG son los que se ven. Lo demás (CMYK
    de Adobe invertido, índices, máscaras) va por pypdf.
    """
    if jpeg.mode not in ("L", "RGB"):
        return None
    if any(k in obj for k in ("/SMask", "/Mask", "/Decode")):
        return None
    cs = _resolved(obj.get("/ColorSpace"))
    if isinstance(cs, (list, tuple)):
        cs = _resolved(cs[0]) if cs else None
    if str(cs) not in ("/DeviceGray", "/DeviceRGB", "/ICCBased", "/CalGray", "/CalRGB"):
        return None
    w, h = jpeg.size
    if max(w, h) > limit:
        scale = limit / max(w, h)
        jpeg.draft(jpeg.mode, (max(1, round(w * scale)), max(1, round(h * scale))))
    jpeg.load()
    return jpeg


def _jpeg_quality(img) -> int | None:
    """Calidad (1-100) con la que se guardó un JPEG, estimada de su tabla de luma.

    Compara la suma de la tabla 0 con la de la tabla estándar escalada como lo
    hace libjpeg; en un empate gana la calidad MAYOR (así, ante la duda, se
    recodifica). ``None`` si no hay tabla legible.
    """
    tables = getattr(img, "quantization", None) or {}
    luma = tables.get(0)
    if not luma or len(luma) != 64:
        return None
    total = sum(luma)
    return min(range(100, 0, -1), key=lambda q: abs(_luma_sum(q) - total))


def _luma_sum(quality: int) -> int:
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return sum(min(max((v * scale + 50) // 100, 1), 255) for v in _STD_LUMA_QTABLE)


def _for_jpeg(img):
    """Imagen lista para JPEG, o ``None`` si conviene dejarla como está.

    - RGBA / LA / P / PA → RGB aplanada sobre blanco (JPEG no tiene alfa).
    - L (escala de grises) → se queda en L: un escaneo en grises pesa un tercio.
    - 1 (bitonal) → ``None``: ya viene en CCITT/Flate, que a un bit por píxel
      pesa menos que cualquier JPEG; convertirlo lo haría crecer.
    - RGB se queda; cualquier otro modo (CMYK, 16 bits…) → RGB.

    L y RGB se devuelven SIN copiar (m2: una copia duplicaba la memoria): la
    imagen es nuestra, recién decodificada, y ``thumbnail`` puede ir en sitio.
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
        return img
    return img.convert("RGB")


def _put_jpeg(obj, data: bytes, img) -> None:
    """Escribe ``data`` (JPEG de ``img``) en sitio sobre el stream del XObject."""
    from pypdf.generic import NameObject, NumberObject

    for key in _STALE_IMAGE_KEYS:
        obj.pop(key, None)
    obj[NameObject("/Filter")] = NameObject("/DCTDecode")
    obj[NameObject("/Width")] = NumberObject(img.width)
    obj[NameObject("/Height")] = NumberObject(img.height)
    obj[NameObject("/BitsPerComponent")] = NumberObject(8)
    obj[NameObject("/ColorSpace")] = NameObject(
        "/DeviceGray" if img.mode == "L" else "/DeviceRGB")
    obj._data = data                    # el writer recalcula /Length al escribir
    if hasattr(obj, "decoded_self"):    # caché de pypdf con los píxeles viejos
        obj.decoded_self = None

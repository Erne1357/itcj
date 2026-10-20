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

Decodificar (rendimiento 2026-10-06 y 2026-10-14): ``page.images[...]`` de
pypdf re-CODIFICA cada imagen (a PNG, a JPEG2000 si era JPEG2000 o JPEG con
máscara) y la vuelve a abrir antes de devolverla: ~2 s por hoja A4 a 300 dpi
con máscara suave, ~3.4 s con JPEG2000 (un PDF de prod de 7.4 MB tardó 10.6 s).
Por eso lo «simple» se decodifica directo (``_decode_direct``): JPEG y JPEG2000
ya reducidos, Flate sin pérdida, y cualquiera de los tres con máscara suave,
aplanada sobre blanco. pypdf queda para lo raro (CMYK, ``/Decode``, máscaras de
bits...). ``stats`` cuenta por qué ruta pasó cada imagen y cuánto costó lo que
fue por pypdf: con eso la próxima subida lenta dice en Tempo qué la hizo lenta.

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
import time
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

# Claves que cambian qué píxeles se ven y que la decodificación directa no
# reproduce: con alguna de ellas, la imagen va por pypdf. La máscara SUAVE
# (`/SMask`) sí se reproduce: la aplana `_flatten_smask`.
_PYPDF_ONLY_KEYS = ("/Mask", "/Decode")

# Reducción máxima al decodificar un JPEG2000: 1/8 por lado (2**3), de sobra
# para un escaneo a 600 dpi.
_JPX_MAX_REDUCE = 3


class PdfUnreadable(Exception):
    """El PDF no se puede abrir: bytes que no son PDF, truncado o cifrado."""


def compress_pdf(raw: bytes, *, target_bytes: int, stats: dict | None = None) -> bytes | None:
    """Devuelve ``raw`` comprimido a ``<= target_bytes``, o ``None`` si no se puede.

    - ``len(raw) <= target_bytes`` → devuelve ``raw`` tal cual (el mismo objeto;
      ni siquiera se lee).
    - Si no, prueba ``PASSES`` en orden y devuelve la primera que quepa.
    - Si ninguna cabe → ``None``.
    - PDF ilegible, cifrado o que pypdf no puede abrir → ``PdfUnreadable``.
    - Nunca devuelve un PDF con otro número de páginas: si el resultado que
      cabe no conserva las páginas del original, ``PdfUnreadable``.

    ``stats`` (opcional) recibe ``passes``: cuántas pasadas corrieron (0 si ya
    cabía); ``images``: ``{ruta: n}`` de la última pasada, por dónde se
    decodificó cada imagen (``jpeg``, ``jpx``, ``flat``, ``smask``,
    ``pypdf``) o ``error`` si no se pudo y se dejó como estaba; y
    ``pypdf_ms``: el tiempo de las imágenes que fueron por pypdf, sumado en
    todas las pasadas. Son para el span y el log de la subida, no cambian el
    resultado.
    """
    if target_bytes <= 0:
        raise ValueError("target_bytes debe ser positivo")
    if stats is not None:
        stats["passes"] = 0
        stats["images"] = {}
        stats["pypdf_ms"] = 0.0
    if len(raw) <= target_bytes:
        return raw

    pages = _page_count(raw)
    for p in PASSES:
        if stats is not None:
            stats["passes"] += 1
        out = _one_pass(raw, p, stats)
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


def _one_pass(raw: bytes, p: _Pass, stats: dict | None = None) -> bytes:
    """Una pasada completa sobre una copia fresca del original.

    Cada pasada parte de ``raw`` y no de la anterior: recomprimir un JPEG ya
    recomprimido acumula pérdida sin necesidad. Con ``stats``, deja ahí las
    rutas de ESTA pasada y suma el tiempo de pypdf (ver ``compress_pdf``).
    """
    from pypdf import PdfWriter

    reader = _open_reader(raw)
    try:
        writer = PdfWriter(clone_from=reader)
        pages = list(writer.pages)
    except Exception as exc:
        raise PdfUnreadable(str(exc)) from exc

    rutas: dict[str, int] = {}
    done: set[int] = set()        # XObjects ya tratados (una imagen puede repetirse)
    for page in pages:
        limit = _pixel_limit(page, p)
        for path, obj in _page_images(page):
            key = id(obj)
            if key in done:
                continue
            done.add(key)
            inicio = time.perf_counter()
            try:
                ruta = _recode_image(page, path, obj, limit=limit, quality=p.quality)
            except Exception as exc:
                ruta = "error"
                logger.debug("compress_pdf: imagen %s se deja como está: %s", path, exc)
            if ruta == "pypdf" and stats is not None:
                stats["pypdf_ms"] += (time.perf_counter() - inicio) * 1000
            if ruta is not None:
                rutas[ruta] = rutas.get(ruta, 0) + 1
        try:
            page.compress_content_streams()
        except Exception as exc:
            logger.debug("compress_pdf: no se comprimió un content stream: %s", exc)

    try:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except Exception as exc:
        logger.debug("compress_pdf: no se compactaron objetos: %s", exc)

    if stats is not None:
        stats["images"] = rutas
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


def _recode_image(page, path: list[str], obj, *, limit: int, quality: int) -> str | None:
    """Reduce y/o recodifica en JPEG una imagen, en sitio, si con eso pesa menos.

    Devuelve la ruta por la que se decodificó (ver ``_decode_direct``, o
    ``"pypdf"``), o ``None`` si se dejó sin decodificar (bitonal, paleta,
    enorme o un JPEG que ya está a esta calidad).

    Cualquier imagen que no se pueda decodificar (CCITT raros, JBIG2, datos
    corruptos) lanza y el llamador la deja COMO ESTÁ: una imagen difícil no debe
    tumbar la compresión del resto del documento.
    """
    if _is_bilevel(obj) or _is_indexed(obj):
        return None
    width = int(_resolved(obj.get("/Width")) or 0)
    height = int(_resolved(obj.get("/Height")) or 0)
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        return None
    needs_resize = max(width, height) > limit

    jpeg = None
    if _filters(obj) == ["/DCTDecode"]:
        from PIL import Image

        jpeg = Image.open(io.BytesIO(obj.get_data()))       # solo lee cabeceras
        if jpeg.size[0] * jpeg.size[1] > MAX_IMAGE_PIXELS:
            return None
        if not needs_resize:
            q = _jpeg_quality(jpeg)
            if q is not None and q <= quality:
                return None     # ya es un JPEG a esta calidad o menor y cabe
    pil, ruta = _decode_direct(obj, limit, jpeg)
    if pil is None:
        pil, ruta = _decode_with_pypdf(page, path), "pypdf"
    if pil is None:
        return ruta

    prepared = _for_jpeg(pil)
    if prepared is None:
        return ruta
    if _is_uniform(prepared) and _encoded_len(obj) > UNIFORM_SUSPECT_BYTES:
        # Un solo color salido de un stream que no es trivial: casi seguro una
        # mala decodificación (ronda 2). El JPEG pesaría casi nada y la guarda
        # de abajo lo aceptaría: el documento quedaría en negro sin avisar.
        logger.debug("compress_pdf: imagen %s decodificada de un solo color; "
                     "se deja como está", path)
        return ruta
    if max(prepared.size) > limit:
        prepared.thumbnail((limit, limit))
    buf = io.BytesIO()
    # optimize: tablas Huffman a la medida (unos % menos, misma calidad).
    prepared.save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    if len(data) >= _encoded_len(obj):
        return ruta             # el JPEG no gana nada: se queda la original
    _put_jpeg(obj, data, prepared)
    return ruta


def _decode_direct(obj, limit: int, jpeg=None):
    """``(imagen, ruta)`` decodificada SIN pypdf, o ``(None, None)`` si no es «simple».

    Rutas: ``"jpeg"`` (``jpeg`` = el JPEG del stream con solo sus cabeceras
    leídas; se abre aquí si no viene), ``"jpx"`` (JPEG2000), ``"flat"`` (Flate
    sin pérdida) y ``"smask"`` (cualquiera de los tres con máscara suave,
    aplanada sobre blanco por ``_flatten_smask``). JPEG y JPEG2000 se
    decodifican ya reducidos a la menor medida que no baje de ``limit``.
    Lo demás va por ``_decode_with_pypdf``, la ruta cara.
    """
    filtros = _filters(obj)
    if filtros == ["/DCTDecode"]:
        if jpeg is None:
            from PIL import Image

            jpeg = Image.open(io.BytesIO(obj.get_data()))
        base, ruta = _decode_jpeg_reduced(jpeg, obj, limit), "jpeg"
    elif filtros == ["/JPXDecode"]:
        base, ruta = _decode_jpx(obj, limit), "jpx"
    elif filtros == ["/FlateDecode"]:
        base, ruta = _decode_flat(obj), "flat"
    else:
        return None, None
    if base is None:
        return None, None
    if "/SMask" not in obj:
        return base, ruta
    plana = _flatten_smask(obj, base)
    return (plana, "smask") if plana is not None else (None, None)


def _decode_with_pypdf(page, path: list[str]):
    """Decodifica con pypdf lo que ``_decode_direct`` no sabe (CMYK, ``/Decode``,
    máscaras de bits, máscaras suaves raras...): pypdf sabe aplicar espacios de
    color y máscaras. CARO: `page.images` re-codifica la imagen (a PNG, TIFF o
    JPEG2000) y la vuelve a abrir (≈2-3.4 s por hoja A4 a 300 dpi), por eso va
    al final."""
    return page.images[path if len(path) > 1 else path[0]].image


# Espacio de color -> modo de Pillow para el Flate «simple». ICCBased/Cal* se
# leen por su número de componentes, como lo hace pypdf (sin aplicar el perfil).
_FLAT_MODES = {"/DeviceGray": "L", "/CalGray": "L", "/DeviceRGB": "RGB", "/CalRGB": "RGB"}


def _decode_flat(obj):
    """Decodifica directo un Flate «simple», o ``None`` si no lo es.

    Simple = ``/FlateDecode`` solo (con o sin predictor PNG, que resuelve
    ``get_data``), 8 bits por componente, gris o RGB (directo, Cal* o ICCBased
    de 1 o 3 componentes) y sin ``/Mask``/``/Decode``. Es el escaneo sin
    pérdida típico. Da los MISMOS píxeles que pypdf sin su vuelta por PNG
    (rendimiento 2026-10-06: 2.4 s → 25 ms por hoja). Lo demás va por
    ``_decode_with_pypdf``. Son los píxeles del stream: una ``/SMask`` la
    aplana después ``_decode_direct``.
    """
    from PIL import Image

    if _filters(obj) != ["/FlateDecode"]:
        return None
    if _resolved(obj.get("/BitsPerComponent")) != 8:
        return None
    if any(k in obj for k in _PYPDF_ONLY_KEYS):
        return None
    cs = _resolved(obj.get("/ColorSpace"))
    if isinstance(cs, (list, tuple)) and cs:
        family = str(_resolved(cs[0]))
        if family == "/ICCBased" and len(cs) > 1:
            n = _resolved(_resolved(cs[1]).get("/N"))
            mode = {1: "L", 3: "RGB"}.get(n)
        else:
            mode = _FLAT_MODES.get(family)
    else:
        mode = _FLAT_MODES.get(str(cs))
    if mode is None:
        return None
    width = int(_resolved(obj.get("/Width")))
    height = int(_resolved(obj.get("/Height")))
    expected = width * height * (1 if mode == "L" else 3)
    data = obj.get_data()
    if len(data) < expected:
        return None             # datos cortos: que pypdf decida qué hacer
    return Image.frombytes(mode, (width, height), data[:expected])


def _decode_jpeg_reduced(jpeg, obj, limit: int):
    """Decodifica un JPEG «simple» ya reducido (``draft``), o ``None`` si no lo es.

    Simple = gris o RGB, sin ``/Mask``/``/Decode`` y en un espacio de color
    directo: ahí los píxeles del JPEG son los que se ven. Lo demás (CMYK de
    Adobe invertido, índices, máscaras de bits) va por pypdf. Una ``/SMask`` la
    aplana después ``_decode_direct``.
    """
    if jpeg.mode not in ("L", "RGB"):
        return None
    if any(k in obj for k in _PYPDF_ONLY_KEYS):
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


# `/ColorSpace` directo -> modo de Pillow de un JPEG2000 «simple».
_JPX_MODES = {"/DeviceGray": "L", "/CalGray": "L", "/DeviceRGB": "RGB", "/CalRGB": "RGB"}


def _decode_jpx(obj, limit: int):
    """Decodifica directo un JPEG2000 «simple», ya reducido, o ``None`` si no lo es.

    Simple = sin ``/SMaskInData`` (alfa dentro del códec) ni ``/Mask``/``/Decode``,
    gris o RGB en el códec, y el ``/ColorSpace`` del PDF ausente (manda el
    códec, como permite la norma) o del mismo número de canales (directo, Cal*
    o ICCBased). Da los MISMOS píxeles que pypdf, que abre el mismo códec con
    Pillow, sin su vuelta: pypdf lo re-CODIFICA a JPEG2000 y lo abre otra vez
    (rendimiento 2026-10-14: ~3.4 s por hoja A4 a 300 dpi; un PDF de prod de
    7.4 MB tardó 10.6 s). Además se decodifica ya reducido: ``reduce`` descarta
    niveles de resolución del códec (1/2, 1/4, 1/8 por lado, como ``draft`` en
    JPEG) hasta la menor medida que no baje de ``limit``.
    """
    from PIL import Image

    if any(k in obj for k in _PYPDF_ONLY_KEYS) or _resolved(obj.get("/SMaskInData")):
        return None
    esperado = _jpx_mode(obj)
    if esperado is False:
        return None
    data = obj.get_data()
    img = Image.open(io.BytesIO(data), formats=("JPEG2000",))
    if img.mode not in ("L", "RGB") or esperado not in (None, img.mode):
        return None
    if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
        return None
    niveles = _jpx_reduce(img.size, limit)
    if niveles:
        try:
            img.reduce = niveles
            img.load()
            return img
        except Exception as exc:     # el códec trae menos niveles que los pedidos
            logger.debug("compress_pdf: JPEG2000 sin %s niveles de reducción: %s",
                         niveles, exc)
            img = Image.open(io.BytesIO(data), formats=("JPEG2000",))
    img.load()
    return img


def _jpx_mode(obj):
    """El modo que pide el ``/ColorSpace`` de un JPEG2000: ``None`` si no lo
    trae (manda el códec), ``"L"`` o ``"RGB"``, o ``False`` si no es simple
    (CMYK, Lab, paleta, separaciones...)."""
    cs = _resolved(obj.get("/ColorSpace"))
    if cs is None:
        return None
    if isinstance(cs, (list, tuple)):
        if not cs:
            return False
        family = str(_resolved(cs[0]))
        if family == "/ICCBased" and len(cs) > 1:
            return {1: "L", 3: "RGB"}.get(_resolved(_resolved(cs[1]).get("/N")), False)
        return _JPX_MODES.get(family, False)
    return _JPX_MODES.get(str(cs), False)


def _jpx_reduce(size: tuple[int, int], limit: int) -> int:
    """Niveles a descartar: la mayor reducción (hasta ``_JPX_MAX_REDUCE``) cuyo
    lado mayor no baje de ``limit``; ``thumbnail`` deja después la medida exacta."""
    lado = max(size)
    niveles = 0
    while niveles < _JPX_MAX_REDUCE and lado >> (niveles + 1) >= limit:
        niveles += 1
    return niveles


def _flatten_smask(obj, base):
    """``base`` aplanada sobre blanco con la máscara suave del XObject, o
    ``None`` si la máscara no es «simple» (que la resuelva pypdf).

    Es lo mismo que pypdf + ``_for_jpeg``: pypdf pone la máscara como canal
    alfa y ``_for_jpeg`` pega la imagen sobre blanco con ese alfa. Como pypdf,
    una máscara de otra medida que la imagen se ignora (queda opaca). Dos
    diferencias a propósito: si ``base`` se decodificó ya reducida, la máscara
    se escala a su medida (a la vista, igual), y lo gris se queda gris (pypdf +
    ``_for_jpeg`` lo daban en RGB: el triple de JPEG con los mismos píxeles).
    ``/Matte`` (alfa premultiplicado) no es simple.
    """
    from PIL import Image
    from pypdf.generic import StreamObject

    mascara = _resolved(obj.get("/SMask"))
    if not isinstance(mascara, StreamObject) or "/Matte" in mascara:
        return None
    alfa = _decode_mask(mascara)
    if alfa is None:
        return None
    width = int(_resolved(obj.get("/Width")) or 0)
    height = int(_resolved(obj.get("/Height")) or 0)
    if alfa.size != (width, height):
        return base
    if alfa.size != base.size:
        alfa = alfa.resize(base.size, Image.Resampling.BILINEAR)
    plana = Image.new(base.mode, base.size, "white")
    plana.paste(base, mask=alfa)
    return plana


def _decode_mask(mascara):
    """La máscara suave como imagen ``L`` (8 bits, gris), decodificada directo,
    o ``None`` si no es simple (bits sueltos, otro espacio de color, enorme...)."""
    from PIL import Image

    if any(k in mascara for k in ("/SMask", *_PYPDF_ONLY_KEYS)):
        return None
    width = int(_resolved(mascara.get("/Width")) or 0)
    height = int(_resolved(mascara.get("/Height")) or 0)
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        return None
    filtros = _filters(mascara)
    if filtros == ["/FlateDecode"]:
        alfa = _decode_flat(mascara)
    elif filtros == ["/DCTDecode"]:
        alfa = Image.open(io.BytesIO(mascara.get_data()))
        alfa.load()
    elif filtros == ["/JPXDecode"]:
        alfa = _decode_jpx(mascara, max(width, height) + 1)    # completa, sin reducir
    else:
        return None
    return alfa if alfa is not None and alfa.mode == "L" else None


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

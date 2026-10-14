"""PDFs sinteticos EN MEMORIA para las pruebas de compresion y de subida.

Nada de archivos binarios en el repo ni de documentos reales: todo sale de
Pillow (`Image.save(buf, "PDF", ...)`), y `flate_pdf` ademas cambia el stream
con pypdf. Cada generador esta en `lru_cache` porque armar una pagina A4 a
300 dpi cuesta ~1 s y varios tests reusan la misma; los `bytes` son
inmutables, compartirlos es seguro.

Tamanos medidos en el contenedor (Pillow 12.3, pypdf 6.19):

* `photo_pdf()`   A4 a 300 dpi, degradado + ruido, JPEG q90  -> ~4.1 MB.
                  La pasada de 150 dpi lo deja en ~0.25 MB, la de 110 dpi en
                  ~0.06 MB y la de 96 dpi en ~0.03 MB.
* `photo_pdf(width=3000, height=4000, resolution=72)` -> ~5.7 MB. Es el
                  "foto -> PDF" del iPhone / Vista Previa / img2pdf: la
                  pagina mide lo mismo que la foto (41.7 x 55.6 pulgadas), asi
                  que el limite relativo a la pagina no la toca; solo el tope
                  ABSOLUTO de px de cada pasada la baja.
* `flate_pdf()`   foto de 1200x1600 a 150 dpi guardada SIN perdida
                  (FlateDecode) -> ~5 MB. La imagen ya cabe en el tope de px:
                  solo baja si se recodifica en JPEG aunque quepa.
* `bilevel_noise_pdf()` ruido bitonal (1 bit, CCITT G4) de 3200 px a 300 dpi
                  -> ~2.6 MB. Lo bitonal nunca se recodifica (en JPEG
                  creceria), asi que ninguna pasada lo baja: es el PDF que
                  "aun comprimido" sigue arriba de 2 MB.
* `indexed_pdf()` foto cuantizada a 64 colores (modo P de Pillow) de
                  1200x1600 a 150 dpi -> ~3.7 MB. Pillow la escribe como
                  `/Indexed` con `/ASCIIHexDecode`, y pypdf 6.19 la decodifica
                  NEGRA (indices y paleta en cero): es la muestra de la
                  corrupcion silenciosa de la ronda 2.
* `jpx_pdf()`     la misma foto en JPEG2000 (`/JPXDecode`, tasa 20:1). Es la
                  muestra del PDF de prod que tardo 10.6 s (2026-10-13).
* `masked_pdf()`  foto de 600x800 con mascara suave (`/SMask`) en Flate,
                  JPEG o JPEG2000: lo que deja un PNG con transparencia.
"""
from __future__ import annotations

import io
import zlib
from functools import lru_cache

from PIL import Image, ImageChops

MB = 1024 * 1024


def _photo_image(width: int, height: int, sigma: int = 40, mode: str = "RGB") -> Image.Image:
    """Contenido "fotografico": degradados cruzados + ruido gaussiano suave."""
    grad = Image.linear_gradient("L").resize((width, height))
    grad_x = grad.rotate(90, expand=True).resize((width, height))
    r = ImageChops.add(grad, Image.effect_noise((width, height), sigma), scale=2.0)
    if mode == "L":
        return r
    g = ImageChops.add(grad_x, Image.effect_noise((width, height), sigma), scale=2.0)
    b = ImageChops.add(ImageChops.invert(grad), Image.effect_noise((width, height), sigma),
                       scale=2.0)
    return Image.merge("RGB", (r, g, b))


def _to_pdf(images: list[Image.Image], *, resolution: float, quality: int) -> bytes:
    buf = io.BytesIO()
    images[0].save(buf, "PDF", resolution=resolution, quality=quality,
                   save_all=True, append_images=images[1:])
    return buf.getvalue()


@lru_cache(maxsize=None)
def photo_pdf(*, width: int = 2480, height: int = 3508, resolution: float = 300,
              quality: int = 90, pages: int = 1, mode: str = "RGB") -> bytes:
    """Pagina(s) con foto sintetica. Por omision, A4 a 300 dpi (~4.1 MB)."""
    imgs = [_photo_image(width, height, mode=mode) for _ in range(pages)]
    return _to_pdf(imgs, resolution=resolution, quality=quality)


@lru_cache(maxsize=None)
def flate_pdf(*, width: int = 1200, height: int = 1600, resolution: float = 150) -> bytes:
    """Foto sintetica en FlateDecode (sin perdida), como la dejan algunos
    escaneres y los convertidores PNG -> PDF. Pillow solo escribe RGB en JPEG,
    asi que se arma su PDF y se cambia el stream por los pixeles en zlib."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    img = _photo_image(width, height)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(
        _to_pdf([img], resolution=resolution, quality=75))))
    xobjs = writer.pages[0]["/Resources"]["/XObject"]
    stream = xobjs.raw_get(next(iter(xobjs))).get_object()
    stream._data = zlib.compress(img.tobytes(), 6)
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@lru_cache(maxsize=None)
def bilevel_noise_pdf(*, px: int = 3200) -> bytes:
    """Ruido bitonal a 300 dpi: incomprimible con las pasadas de `compress_pdf`."""
    noise = Image.effect_noise((px, px), 128).point(lambda v: 255 if v > 127 else 0)
    img = noise.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=300)
    return buf.getvalue()


@lru_cache(maxsize=None)
def indexed_pdf(*, width: int = 1200, height: int = 1600, resolution: float = 150,
                colorspace_ref: str = "directo") -> bytes:
    """Imagen de paleta (`/Indexed`) tal como la escribe Pillow en modo P.

    `colorspace_ref` cambia COMO llega el espacio de color, no los pixeles:
    ``"directo"`` (lo que escribe Pillow), ``"arreglo"`` (todo el arreglo
    `/ColorSpace` por referencia indirecta) o ``"nombre"`` (solo el `/Indexed`
    del arreglo por referencia indirecta).
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject

    buf = io.BytesIO()
    _photo_image(width, height).quantize(64).save(buf, "PDF", resolution=resolution)
    if colorspace_ref == "directo":
        return buf.getvalue()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    xobjs = writer.pages[0]["/Resources"]["/XObject"]
    stream = xobjs.raw_get(next(iter(xobjs))).get_object()
    cs = stream["/ColorSpace"]
    if colorspace_ref == "arreglo":
        stream[NameObject("/ColorSpace")] = writer._add_object(ArrayObject(cs))
    elif colorspace_ref == "nombre":
        stream[NameObject("/ColorSpace")] = ArrayObject(
            [writer._add_object(NameObject("/Indexed")), *cs[1:]])
    else:
        raise ValueError(colorspace_ref)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _swap_image_stream(pdf: bytes, edit) -> bytes:
    """Clona ``pdf`` y llama ``edit(writer, stream, page_index)`` sobre el
    stream de la imagen de cada pagina (una por pagina en estas muestras)."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    for i, page in enumerate(writer.pages):
        xobjs = page["/Resources"]["/XObject"]
        edit(writer, xobjs.raw_get(next(iter(xobjs))).get_object(), i)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _jpx_bytes(img: Image.Image) -> bytes:
    """JPEG2000 con perdida (tasa 20:1), como lo escriben los escaneres que lo usan."""
    buf = io.BytesIO()
    img.save(buf, "JPEG2000", irreversible=True, quality_mode="rates", quality_layers=[20])
    return buf.getvalue()


@lru_cache(maxsize=None)
def jpx_pdf(*, width: int = 1200, height: int = 1600, resolution: float = 150,
            mode: str = "RGB", colorspace: str = "directo", pages: int = 1) -> bytes:
    """Foto sintetica en JPEG2000 (`/JPXDecode`), la del PDF de 7.4 MB que tardo
    10.6 s en comprimirse en prod (2026-10-13). Pillow solo escribe JPEG dentro
    de un PDF, asi que se arma ese PDF y se cambia cada stream por JPEG2000.

    `colorspace`: ``"directo"`` (`/DeviceRGB` o `/DeviceGray` segun `mode`),
    ``"sin"`` (sin `/ColorSpace`: lo dice el codestream, como permite la norma)
    o ``"icc"`` (`[/ICCBased <</N 3>>]`).
    """
    from pypdf.generic import ArrayObject, NameObject, NumberObject, StreamObject

    imgs = [_photo_image(width, height, mode=mode) for _ in range(pages)]

    def edit(writer, stream, i):
        stream._data = _jpx_bytes(imgs[i])
        stream[NameObject("/Filter")] = NameObject("/JPXDecode")
        stream.pop("/DecodeParms", None)
        if colorspace == "sin":
            stream.pop("/ColorSpace", None)
        elif colorspace == "icc":
            perfil = StreamObject()
            perfil[NameObject("/N")] = NumberObject(3)
            stream[NameObject("/ColorSpace")] = ArrayObject(
                [NameObject("/ICCBased"), writer._add_object(perfil)])
        else:
            stream[NameObject("/ColorSpace")] = NameObject(
                "/DeviceGray" if mode == "L" else "/DeviceRGB")

    return _swap_image_stream(_to_pdf(imgs, resolution=resolution, quality=75), edit)


@lru_cache(maxsize=None)
def masked_pdf(*, base: str = "flate", mode: str = "RGB", width: int = 600, height: int = 800,
               resolution: float = 72, mask_size: tuple[int, int] | None = None,
               matte: bool = False) -> bytes:
    """Una pagina con UNA imagen con mascara suave (`/SMask`, degradado de
    alfa), como la dejan los PNG con transparencia al pasar a PDF. pypdf las
    re-codifica a PNG (Flate) o a JPEG2000 (JPEG/JPEG2000) antes de devolverlas.

    `base`: ``"flate"``, ``"jpeg"`` o ``"jpx"`` (filtro de la imagen).
    `mask_size`: otra medida para la mascara (pypdf la ignora si no coincide).
    `matte`: agrega `/Matte` (alfa premultiplicado) a la mascara.
    """
    from pypdf.generic import ArrayObject, FloatObject, NameObject, NumberObject, StreamObject

    img = _photo_image(width, height, mode=mode)
    mw, mh = mask_size or (width, height)
    alfa = Image.linear_gradient("L").rotate(90).resize((mw, mh))

    def edit(writer, stream, _i):
        if base == "flate":
            stream._data = zlib.compress(img.tobytes(), 6)
            stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        elif base == "jpx":
            stream._data = _jpx_bytes(img)
            stream[NameObject("/Filter")] = NameObject("/JPXDecode")
        # "jpeg": el stream que escribio Pillow ya es el JPEG de `img`
        stream[NameObject("/ColorSpace")] = NameObject(
            "/DeviceGray" if mode == "L" else "/DeviceRGB")
        mascara = StreamObject()
        mascara._data = zlib.compress(alfa.tobytes(), 6)
        mascara.update({NameObject("/Type"): NameObject("/XObject"),
                        NameObject("/Subtype"): NameObject("/Image"),
                        NameObject("/Width"): NumberObject(mw),
                        NameObject("/Height"): NumberObject(mh),
                        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                        NameObject("/BitsPerComponent"): NumberObject(8),
                        NameObject("/Filter"): NameObject("/FlateDecode")})
        if matte:
            mascara[NameObject("/Matte")] = ArrayObject(
                [FloatObject(1)] * (1 if mode == "L" else 3))
        stream[NameObject("/SMask")] = writer._add_object(mascara)

    return _swap_image_stream(_to_pdf([img], resolution=resolution, quality=90), edit)


def merge_pdfs(*pdfs: bytes) -> bytes:
    """Une varios PDFs (una pagina tras otra) con pypdf."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(PdfReader(io.BytesIO(pdf)))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@lru_cache(maxsize=None)
def small_pdf() -> bytes:
    """PDF valido y chico (decenas de KB): se guarda tal cual."""
    return photo_pdf(width=400, height=566, resolution=48, quality=75)

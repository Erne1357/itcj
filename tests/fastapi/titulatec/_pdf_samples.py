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

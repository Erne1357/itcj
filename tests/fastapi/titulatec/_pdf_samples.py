"""PDFs sinteticos EN MEMORIA para las pruebas de compresion y de subida.

Nada de archivos binarios en el repo ni de documentos reales: todo sale de
Pillow (`Image.save(buf, "PDF", ...)`). Cada generador esta en `lru_cache`
porque armar una pagina A4 a 300 dpi cuesta ~1 s y varios tests reusan la
misma; los `bytes` son inmutables, compartirlos es seguro.

Tamanos medidos en el contenedor (Pillow 12.3, pypdf 6.19):

* `photo_pdf()`   A4 a 300 dpi, degradado + ruido, JPEG q90  -> ~4.1 MB.
                  La pasada de 150 dpi lo deja en ~0.25 MB, la de 110 dpi en
                  ~0.06 MB y la de 96 dpi en ~0.03 MB.
* `noise_pdf()`   ruido de color a 72 dpi, JPEG q95          -> ~2.5 MB.
                  La pagina mide lo que la imagen (px/72 pulgadas), asi que
                  ninguna pasada la reduce: es el PDF que "aun comprimido"
                  sigue arriba de 2 MB.
"""
from __future__ import annotations

import io
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
def noise_pdf(*, px: int = 1500, quality: int = 95) -> bytes:
    """Ruido de color a 72 dpi: incomprimible con las pasadas de `compress_pdf`."""
    img = Image.merge("RGB", tuple(Image.effect_noise((px, px), 80) for _ in range(3)))
    return _to_pdf([img], resolution=72, quality=quality)


@lru_cache(maxsize=None)
def small_pdf() -> bytes:
    """PDF valido y chico (decenas de KB): se guarda tal cual."""
    return photo_pdf(width=400, height=566, resolution=48, quality=75)

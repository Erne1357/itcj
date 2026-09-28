"""`utils/pdf_compress.compress_pdf`: bajar un PDF escaneado al tope de 2 MB.

Contrato (brief 2026-09-28, documentos a 2 MB):

* `len(raw) <= target_bytes` -> devuelve `raw` SIN TOCAR (el mismo objeto).
* si no, prueba tres pasadas cada vez mas fuertes -(150 dpi, q75), (110, q60),
  (96, q50)- y devuelve la PRIMERA que quepa; si ninguna cabe, `None`.
* PDF ilegible, cifrado o que pypdf no abre -> `PdfUnreadable`.
* por pagina, cada imagen mas grande que `lado_de_la_pagina_en_pulgadas x dpi`
  se reduce (conservando proporcion) y se recodifica JPEG; una imagen que no se
  puede decodificar se deja como esta, sin abortar.

Los PDFs salen de `_pdf_samples` (Pillow, en memoria).
"""
from __future__ import annotations

import io
import os

import pytest
from pypdf import PdfReader, PdfWriter

from itcj2.apps.titulatec.utils.pdf_compress import PdfUnreadable, compress_pdf
from tests.fastapi.titulatec._pdf_samples import MB, noise_pdf, photo_pdf, small_pdf

TARGET = 2 * MB

# Lado largo de un A4 (841.89 pt) a los dpi de cada pasada, en pixeles.
A4_LONG_150 = round(841.89 / 72 * 150)   # 1754
A4_LONG_110 = round(841.89 / 72 * 110)   # 1286


def _images(pdf: bytes) -> list:
    reader = PdfReader(io.BytesIO(pdf))
    return [img.image for page in reader.pages for img in page.images]


class TestSinTocar:
    def test_un_pdf_que_ya_cabe_regresa_los_mismos_bytes(self):
        raw = small_pdf()

        assert compress_pdf(raw, target_bytes=len(raw)) is raw
        assert compress_pdf(raw, target_bytes=TARGET) is raw

    def test_ni_siquiera_se_lee_si_ya_cabe(self):
        """Hasta 2 MB se guarda como hoy: aunque no sea un PDF valido."""
        basura = b"%PDF-1.4 esto no es un pdf de verdad"

        assert compress_pdf(basura, target_bytes=TARGET) is basura


class TestComprime:
    def test_un_escaneo_fotografico_de_4mb_baja_de_2mb(self):
        raw = photo_pdf()
        assert len(raw) > TARGET, "la muestra debe pesar mas que el objetivo"

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None
        assert len(out) <= TARGET
        assert len(out) < len(raw)

    def test_devuelve_la_primera_pasada_que_cabe(self):
        """Con 2 MB cabe ya la de 150 dpi: no se degrada de mas."""
        out = compress_pdf(photo_pdf(), target_bytes=TARGET)

        (img,) = _images(out)
        assert max(img.size) == A4_LONG_150
        assert img.size[0] < img.size[1], "conserva la proporcion (vertical)"

    def test_si_la_primera_no_cabe_prueba_la_siguiente(self):
        """150 dpi deja ~250 KB y 110 dpi ~60 KB: con 150 KB gana la segunda."""
        out = compress_pdf(photo_pdf(), target_bytes=150_000)

        assert out is not None and len(out) <= 150_000
        (img,) = _images(out)
        assert max(img.size) == A4_LONG_110, "la de 110 dpi, no la de 96"

    def test_el_resultado_es_un_pdf_legible_con_las_mismas_paginas(self):
        raw = photo_pdf(width=1700, height=2200, resolution=200, pages=3)
        assert len(raw) > TARGET

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        reader = PdfReader(io.BytesIO(out))
        assert len(reader.pages) == 3
        assert all(img.image.size[0] > 0 for page in reader.pages for img in page.images)

    def test_la_escala_de_grises_se_queda_en_grises(self):
        raw = photo_pdf(mode="L", quality=95)
        assert len(raw) > 1 * MB

        out = compress_pdf(raw, target_bytes=len(raw) - 1)

        (img,) = _images(out)
        assert max(img.size) == A4_LONG_150, "la imagen si se reemplazo"
        assert img.mode == "L"


class TestNoAlcanza:
    def test_ni_la_pasada_mas_fuerte_llega_devuelve_none(self):
        """96 dpi deja ~30 KB: un objetivo de 10 KB no se alcanza."""
        assert compress_pdf(photo_pdf(), target_bytes=10_000) is None

    def test_imagenes_que_no_se_pueden_reducir_devuelven_none(self):
        """Pagina del tamano de la imagen (72 dpi): ninguna pasada la toca."""
        raw = noise_pdf()
        assert len(raw) > TARGET

        assert compress_pdf(raw, target_bytes=TARGET) is None


class TestIlegible:
    def test_bytes_basura(self):
        with pytest.raises(PdfUnreadable):
            compress_pdf(b"esto no es un pdf" * 1000, target_bytes=100)

    def test_pdf_truncado(self):
        raw = photo_pdf()

        with pytest.raises(PdfUnreadable):
            compress_pdf(raw[: len(raw) // 2], target_bytes=1024)

    def test_pdf_cifrado(self):
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(photo_pdf())))
        writer.encrypt(user_password="", owner_password="dueno")
        buf = io.BytesIO()
        writer.write(buf)

        with pytest.raises(PdfUnreadable):
            compress_pdf(buf.getvalue(), target_bytes=TARGET)


class TestImagenQueNoSeDecodifica:
    def test_se_deja_como_esta_y_se_comprime_el_resto(self):
        """Pagina 1 con un JPEG corrupto; pagina 2 con una foto sana."""
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(
            photo_pdf(width=1700, height=2200, resolution=200, pages=2))))
        xobjs = writer.pages[0]["/Resources"]["/XObject"]
        stream = xobjs[list(xobjs)[0]].get_object()
        corrupto = os.urandom(200_000)
        stream._data = corrupto            # sigue declarando /DCTDecode
        buf = io.BytesIO()
        writer.write(buf)
        raw = buf.getvalue()

        out = compress_pdf(raw, target_bytes=len(raw) - 1)

        assert out is not None and len(out) < len(raw)
        reader = PdfReader(io.BytesIO(out))
        assert len(reader.pages) == 2
        xo = reader.pages[0]["/Resources"]["/XObject"]
        assert xo[list(xo)[0]].get_object()._data == corrupto
        assert max(reader.pages[1].images[0].image.size) < 2200

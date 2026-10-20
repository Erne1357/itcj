"""`utils/pdf_compress.compress_pdf`: bajar un PDF escaneado al tope de 2 MB.

Contrato (brief 2026-09-28, documentos a 2 MB):

* `len(raw) <= target_bytes` -> devuelve `raw` SIN TOCAR (el mismo objeto).
* si no, prueba tres pasadas cada vez mas fuertes -(150 dpi, q75), (110, q60),
  (96, q50)- y devuelve la PRIMERA que quepa; si ninguna cabe, `None`.
* PDF ilegible, cifrado o que pypdf no abre -> `PdfUnreadable`.
* por pagina, cada imagen mas grande que `lado_de_la_pagina_en_pulgadas x dpi`
  se reduce (conservando proporcion) y se recodifica JPEG; una imagen que no se
  puede decodificar se deja como esta, sin abortar.
* ronda 1 (R1): ademas un tope ABSOLUTO por pasada (lado largo 1754 / 1286 /
  1123 px, un A4 a 150 / 110 / 96 dpi) para los "foto -> PDF" cuya pagina mide
  lo que la foto, y toda imagen no bitonal que no sea ya JPEG a la calidad de
  la pasada o menor se recodifica aunque quepa (Flate sin perdida, JPEG q95).
* ronda 1 (m2): un JPEG grande se decodifica ya reducido (`Image.draft`) y una
  imagen con mas pixeles declarados que `MAX_IMAGE_PIXELS` ni se decodifica.
* ronda 1 (m6): nunca se devuelve un PDF con otro numero de paginas.
* ronda 2: una imagen `/Indexed` (paleta) nunca se recodifica (pypdf la leia
  negra y se aceptaba), y una imagen que se decodifica de un solo color con un
  stream original de mas de unos KB tampoco reemplaza a la original.
* rendimiento 2026-10-14: JPEG2000 y mascaras suaves (`/SMask`) se decodifican
  sin pypdf (que las re-codificaba a JPEG2000/PNG: 10.6 s en un PDF de prod), y
  `stats` cuenta por que ruta paso cada imagen.

Los PDFs salen de `_pdf_samples` (Pillow, en memoria).
"""
from __future__ import annotations

import io
import os

import pytest
from pypdf import PdfReader, PdfWriter

from itcj2.apps.titulatec.utils import pdf_compress
from itcj2.apps.titulatec.utils.pdf_compress import PdfUnreadable, compress_pdf
from tests.fastapi.titulatec._pdf_samples import (
    MB, bilevel_noise_pdf, flate_pdf, indexed_pdf, jpx_pdf, masked_pdf, merge_pdfs, photo_pdf,
    small_pdf,
)

TARGET = 2 * MB

# Lado largo de un A4 (841.89 pt) a los dpi de cada pasada, en pixeles.
A4_LONG_150 = round(841.89 / 72 * 150)   # 1754
A4_LONG_110 = round(841.89 / 72 * 110)   # 1286
A4_LONG_96 = round(841.89 / 72 * 96)     # 1123


def _images(pdf: bytes) -> list:
    reader = PdfReader(io.BytesIO(pdf))
    return [img.image for page in reader.pages for img in page.images]


def _xobjects(pdf: bytes) -> list:
    """El stream de imagen de cada pagina (una por pagina en las muestras)."""
    reader = PdfReader(io.BytesIO(pdf))
    out = []
    for page in reader.pages:
        xo = page["/Resources"]["/XObject"]
        out.append(xo[list(xo)[0]].get_object())
    return out


class TestTopes:
    def test_el_tope_absoluto_de_cada_pasada_es_un_a4_a_esos_dpi(self):
        assert [(p.dpi, p.quality, p.max_px) for p in pdf_compress.PASSES] == [
            (150, 75, A4_LONG_150), (110, 60, A4_LONG_110), (96, 50, A4_LONG_96)]
        assert (A4_LONG_150, A4_LONG_110, A4_LONG_96) == (1754, 1286, 1123)


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

    def test_lo_bitonal_no_se_recodifica_y_devuelve_none(self):
        """1 bit por pixel: en JPEG creceria, asi que se deja como esta."""
        raw = bilevel_noise_pdf()
        assert len(raw) > TARGET

        assert compress_pdf(raw, target_bytes=TARGET) is None


class TestFotoAPdf:
    """R1: el iPhone «Crear PDF», Vista Previa o img2pdf hacen la pagina del
    tamano de la foto a 72 dpi; el limite relativo a la pagina no la toca."""

    def test_foto_de_celular_a_72dpi_baja_de_2mb(self):
        raw = photo_pdf(width=3000, height=4000, resolution=72)
        assert len(raw) > TARGET
        page = PdfReader(io.BytesIO(raw)).pages[0]
        assert float(page.mediabox.height) / 72 > 50, "pagina de ~55 pulgadas"

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        reader = PdfReader(io.BytesIO(out))
        assert len(reader.pages) == 1
        (img,) = _images(out)
        assert max(img.size) == A4_LONG_150, "el tope absoluto, no el de la pagina"
        assert img.size[0] < img.size[1], "conserva la proporcion"

    def test_flate_sin_perdida_que_ya_cabe_se_recodifica(self):
        raw = flate_pdf()
        assert len(raw) > TARGET

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        (xo,) = _xobjects(out)
        assert xo["/Filter"] == "/DCTDecode"
        assert (xo["/Width"], xo["/Height"]) == (1200, 1600), "cabia: no se reduce"
        (img,) = _images(out)
        assert img.size == (1200, 1600)

    def test_jpeg_que_cabe_a_calidad_alta_se_recodifica(self):
        from PIL import Image

        raw = photo_pdf(width=1200, height=1600, resolution=150, quality=95)

        out = compress_pdf(raw, target_bytes=len(raw) - 1)

        assert out is not None and len(out) < len(raw) // 2
        (xo,) = _xobjects(out)
        assert (xo["/Width"], xo["/Height"]) == (1200, 1600)
        assert pdf_compress._jpeg_quality(Image.open(io.BytesIO(xo.get_data()))) == 75

    def test_jpeg_que_cabe_a_calidad_igual_o_menor_no_se_toca(self):
        cabe = photo_pdf(width=1200, height=1600, resolution=150, quality=70)
        raw = merge_pdfs(cabe, photo_pdf())
        antes = _xobjects(raw)[0].get_data()
        assert len(raw) > TARGET

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        primera, segunda = _xobjects(out)
        assert primera.get_data() == antes, "q70 <= q75 y cabe: mismos bytes"
        assert max(segunda["/Width"], segunda["/Height"]) == A4_LONG_150


class TestMemoria:
    """m2: nada de decodificar una imagen enorme completa."""

    def test_un_jpeg_grande_se_decodifica_ya_reducido(self, monkeypatch):
        from PIL import JpegImagePlugin

        tamanos = []
        real_load = JpegImagePlugin.JpegImageFile.load

        def _load(self):
            tamanos.append(self.size)
            return real_load(self)

        monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", _load)

        out = compress_pdf(photo_pdf(), target_bytes=TARGET)

        assert out is not None
        assert tamanos, "se decodifico algun JPEG"
        assert max(max(s) for s in tamanos) <= A4_LONG_150, tamanos

    def test_mas_pixeles_que_el_tope_no_se_decodifica(self, monkeypatch):
        from PIL import Image

        monkeypatch.setattr(pdf_compress, "MAX_IMAGE_PIXELS", 1_000_000)
        abiertas = []
        real_open = Image.open

        def _open(*a, **k):
            abiertas.append(1)
            return real_open(*a, **k)

        monkeypatch.setattr(Image, "open", _open)
        raw = photo_pdf()        # 2480 x 3508 = 8.7 MP declarados

        assert compress_pdf(raw, target_bytes=TARGET) is None
        assert abiertas == [], "ni siquiera se abrio la imagen"


def _uniforme(img) -> bool:
    """Un solo color: sin variacion en ningun canal."""
    extremos = img.getextrema()
    if not isinstance(extremos[0], tuple):      # un solo canal: (min, max)
        extremos = (extremos,)
    return all(lo == hi for lo, hi in extremos)


def _indexed_a_mano(xo):
    """Decodifica A MANO una imagen `/Indexed` de 8 bits: indices del stream +
    paleta del arreglo `/ColorSpace`. pypdf 6.19 la da negra, asi que no sirve
    para comprobar que la imagen conserva su contenido."""
    from PIL import Image

    cs = xo["/ColorSpace"]
    paleta = cs[3].get_object() if hasattr(cs[3], "get_object") else cs[3]
    img = Image.frombytes("P", (int(xo["/Width"]), int(xo["/Height"])), xo.get_data())
    img.putpalette(bytes(paleta))
    return img.convert("RGB")


class TestIndexed:
    """Ronda 2: pypdf 6.19 decodifica NEGRA una imagen `/Indexed` con
    `/ASCIIHexDecode` (asi la escribe Pillow en modo P) y el JPEG negro pesa
    menos, asi que la guarda de «solo si pesa menos» lo aceptaba (medido
    16.81 -> 0.01 MB, media [0,0,0]). Una imagen de paleta nunca se recodifica."""

    @pytest.mark.parametrize("ref", ["directo", "arreglo", "nombre"])
    def test_sola_no_se_recodifica_y_el_pdf_se_rechaza(self, ref):
        raw = indexed_pdf(colorspace_ref=ref)
        assert len(raw) > TARGET
        assert not _uniforme(_indexed_a_mano(_xobjects(raw)[0])), "la muestra tiene variacion"

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is None, "sin recodificar la paleta no cabe: nunca un documento negro"

    def test_se_deja_igual_y_se_comprime_el_resto(self):
        raw = merge_pdfs(indexed_pdf(width=600, height=800), photo_pdf())
        antes = _xobjects(raw)[0].get_data()
        assert len(raw) > TARGET

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        primera, segunda = _xobjects(out)
        assert primera["/ColorSpace"][0] == "/Indexed"
        assert primera.get_data() == antes, "la paleta se deja como estaba"
        assert not _uniforme(_indexed_a_mano(primera)), "conserva la variacion: no salio negra"
        assert max(segunda["/Width"], segunda["/Height"]) == A4_LONG_150


class TestDecodificacionUniforme:
    """Ronda 2, guarda general: si lo decodificado sale de UN SOLO color y el
    stream original pesa mas de unos KB, la decodificacion es sospechosa (el
    caso `/Indexed`, u otro que pypdf lea mal): se deja la original. Se simula
    la mala lectura sobre un Flate sano de 600x800 (~1.2 MB)."""

    @pytest.mark.parametrize("color", [("RGB", (0, 0, 0)), ("L", 255)], ids=["negra", "blanca"])
    def test_un_solo_color_no_reemplaza_a_la_original(self, monkeypatch, color):
        from PIL import Image

        mode, relleno = color
        # La muestra es un Flate simple: desde 2026-10-06 se decodifica en
        # `_decode_flat` (sin pypdf). La mala lectura se simula en los DOS
        # decodificadores para que la guarda se pruebe sea cual sea el camino.
        monkeypatch.setattr(pdf_compress, "_decode_flat",
                            lambda obj: Image.new(mode, (600, 800), relleno))
        monkeypatch.setattr(pdf_compress, "_decode_with_pypdf",
                            lambda page, path: Image.new(mode, (600, 800), relleno))
        raw = merge_pdfs(flate_pdf(width=600, height=800), photo_pdf())
        antes = _xobjects(raw)[0].get_data()
        assert len(raw) > TARGET

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        primera, segunda = _xobjects(out)
        assert primera["/Filter"] == "/FlateDecode"
        assert primera.get_data() == antes, "la original, no el JPEG de un solo color"
        assert max(segunda["/Width"], segunda["/Height"]) == A4_LONG_150

    def test_lo_que_si_varia_se_sigue_recodificando(self):
        """La guarda no frena el caso normal: el mismo Flate, bien leido, pasa a JPEG."""
        raw = merge_pdfs(flate_pdf(width=600, height=800), photo_pdf())

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None
        assert _xobjects(out)[0]["/Filter"] == "/DCTDecode"


class TestPaginas:
    def test_una_salida_con_otro_numero_de_paginas_nunca_se_devuelve(self, monkeypatch):
        raw = photo_pdf(width=1700, height=2200, resolution=200, pages=3)
        monkeypatch.setattr(pdf_compress, "_one_pass", lambda raw, p, stats=None: small_pdf())

        with pytest.raises(PdfUnreadable):
            compress_pdf(raw, target_bytes=TARGET)


@pytest.mark.parametrize("q", [50, 60, 70, 75, 90])
def test_estima_la_calidad_de_un_jpeg(q):
    from PIL import Image
    from tests.fastapi.titulatec._pdf_samples import _photo_image

    buf = io.BytesIO()
    _photo_image(300, 400).save(buf, "JPEG", quality=q)

    assert pdf_compress._jpeg_quality(Image.open(io.BytesIO(buf.getvalue()))) == q


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


# ---------------------------------------------------------------------------
# Rendimiento (2026-10-06): decodificación directa de un Flate simple
# ---------------------------------------------------------------------------
def _variante_flate(kind: str, *, width: int = 300, height: int = 400) -> bytes:
    """Una página con UNA imagen Flate sin pérdida en la variante pedida:
    `rgb`, `gray`, `icc` (ICCBased /N 3), `up` (predictor PNG «Up»),
    `smask` (con máscara suave), `decode` (con `/Decode`) o `mask` (con
    `/Mask` de color clave): las dos últimas no son «simples», van por pypdf."""
    import zlib

    from pypdf.generic import (
        ArrayObject, DictionaryObject, NameObject, NumberObject, StreamObject,
    )
    from tests.fastapi.titulatec._pdf_samples import _photo_image

    img = _photo_image(width, height, mode="L" if kind == "gray" else "RGB")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(flate_pdf(width=width, height=height))))
    xobjs = writer.pages[0]["/Resources"]["/XObject"]
    stream = xobjs.raw_get(next(iter(xobjs))).get_object()
    raw = img.tobytes()
    if kind == "up":
        stride = width * 3
        prev, filas = bytes(stride), []
        for y in range(height):
            fila = raw[y * stride:(y + 1) * stride]
            filas.append(b"\x02" + bytes((a - b) & 0xFF for a, b in zip(fila, prev)))
            prev = fila
        stream._data = zlib.compress(b"".join(filas), 6)
        stream[NameObject("/DecodeParms")] = DictionaryObject({
            NameObject("/Predictor"): NumberObject(12), NameObject("/Colors"): NumberObject(3),
            NameObject("/Columns"): NumberObject(width),
            NameObject("/BitsPerComponent"): NumberObject(8)})
    else:
        stream._data = zlib.compress(raw, 6)
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    if kind == "gray":
        stream[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
    if kind == "icc":
        perfil = StreamObject()
        perfil[NameObject("/N")] = NumberObject(3)
        stream[NameObject("/ColorSpace")] = ArrayObject(
            [NameObject("/ICCBased"), writer._add_object(perfil)])
    if kind == "smask":
        mascara = StreamObject()
        mascara._data = zlib.compress(bytes([200]) * (width * height), 6)
        mascara.update({NameObject("/Type"): NameObject("/XObject"),
                        NameObject("/Subtype"): NameObject("/Image"),
                        NameObject("/Width"): NumberObject(width),
                        NameObject("/Height"): NumberObject(height),
                        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                        NameObject("/BitsPerComponent"): NumberObject(8),
                        NameObject("/Filter"): NameObject("/FlateDecode")})
        stream[NameObject("/SMask")] = writer._add_object(mascara)
    if kind == "decode":
        stream[NameObject("/Decode")] = ArrayObject([NumberObject(v) for v in (0, 1) * 3])
    if kind == "mask":
        stream[NameObject("/Mask")] = ArrayObject([NumberObject(v) for v in (0, 10) * 3])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _pagina_e_imagen(pdf: bytes):
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    xo = page["/Resources"]["/XObject"]
    nombre = list(xo)[0]
    return page, nombre, xo[nombre].get_object()


class TestDecodificacionDirecta:
    """pypdf (`page.images[...]`) re-codifica cada imagen a PNG y la vuelve a
    abrir: en una hoja escaneada A4 a 300 dpi eran ~2.4 s de los 2.5 s de la
    subida (medido 2026-10-06 sobre las subidas lentas de prod). Un Flate
    «simple» (8 bits, gris/RGB, sin máscaras ni /Decode) se lee directo de
    `get_data()`, con los MISMOS píxeles."""

    @pytest.mark.parametrize("kind", ["rgb", "gray", "icc", "up"])
    def test_da_los_mismos_pixeles_que_pypdf(self, kind):
        page, nombre, obj = _pagina_e_imagen(_variante_flate(kind))

        directa = pdf_compress._decode_flat(obj)
        de_pypdf = page.images[nombre].image

        assert directa is not None, f"{kind} es un Flate simple"
        assert (directa.mode, directa.size) == (de_pypdf.mode, de_pypdf.size)
        assert directa.tobytes() == de_pypdf.tobytes()

    @pytest.mark.parametrize("kind", ["decode", "mask"])
    def test_lo_que_no_es_simple_no_se_decodifica_directo(self, kind):
        _page, _nombre, obj = _pagina_e_imagen(_variante_flate(kind))
        assert pdf_compress._decode_direct(obj, 10**6) == (None, None)

    def test_un_jpeg_no_es_flate_simple(self):
        _page, _nombre, obj = _pagina_e_imagen(photo_pdf(width=600, height=800, resolution=72))
        assert pdf_compress._decode_flat(obj) is None

    def test_comprimir_un_flate_simple_no_pasa_por_pypdf(self, monkeypatch):
        def _prohibido(page, path):
            raise AssertionError("un Flate simple no debe re-codificarse a PNG en pypdf")

        monkeypatch.setattr(pdf_compress, "_decode_with_pypdf", _prohibido)
        raw = merge_pdfs(flate_pdf(width=600, height=800), photo_pdf())

        out = compress_pdf(raw, target_bytes=TARGET)

        assert out is not None and len(out) <= TARGET
        assert _xobjects(out)[0]["/Filter"] == "/DCTDecode"

    def test_las_pasadas_quedan_en_stats(self):
        stats = {}
        out = compress_pdf(merge_pdfs(flate_pdf(width=600, height=800), photo_pdf()),
                           target_bytes=TARGET, stats=stats)
        assert out is not None and stats["passes"] >= 1

    def test_stats_dice_cero_pasadas_si_ya_cabe(self):
        stats = {}
        compress_pdf(small_pdf(), target_bytes=TARGET, stats=stats)
        assert stats["passes"] == 0


# ---------------------------------------------------------------------------
# Rendimiento (2026-10-14): JPEG2000 y máscaras suaves sin pasar por pypdf
# ---------------------------------------------------------------------------
def _sin_pypdf(monkeypatch):
    def _prohibido(page, path):
        raise AssertionError("esta imagen no debe re-codificarse en pypdf")

    monkeypatch.setattr(pdf_compress, "_decode_with_pypdf", _prohibido)


def _jpeg_de(obj):
    """El JPEG del stream con solo sus cabeceras leídas (como `_recode_image`)."""
    from PIL import Image

    return Image.open(io.BytesIO(obj.get_data()))


def _parecidas(a, b, *, size=(60, 80)) -> float:
    """Diferencia media (0-255) entre dos imágenes vistas en chico: «a la vista»."""
    from PIL import Image, ImageChops, ImageStat

    chica = [im.convert("RGB").resize(size, Image.Resampling.BOX) for im in (a, b)]
    return max(ImageStat.Stat(ImageChops.difference(*chica)).mean)


class TestJpx:
    """Traza de prod `0ed8aba9…` (2026-10-13): un PDF de 7.4 MB pasó 10.6 s en
    `titulatec.prepare_document`. Con JPEG2000, `page.images[...]` de pypdf
    decodifica la imagen, la vuelve a CODIFICAR a JPEG2000 y la decodifica otra
    vez al abrirla (~3.4 s por hoja A4 a 300 dpi: 0.9 + 1.5 + 0.9). Un JPEG2000
    «simple» se decodifica directo con Pillow y ya reducido (`reduce`, el
    equivalente de `draft` en JPEG)."""

    @pytest.mark.parametrize("variante", [
        {"mode": "RGB", "colorspace": "directo"},
        {"mode": "L", "colorspace": "directo"},
        {"mode": "RGB", "colorspace": "sin"},
        {"mode": "RGB", "colorspace": "icc"},
    ], ids=["rgb", "gris", "sin_colorspace", "icc"])
    def test_da_los_mismos_pixeles_que_pypdf(self, variante):
        page, nombre, obj = _pagina_e_imagen(jpx_pdf(width=300, height=400, **variante))

        directa = pdf_compress._decode_jpx(obj, 10**6)
        de_pypdf = page.images[nombre].image

        assert directa is not None
        assert (directa.mode, directa.size) == (de_pypdf.mode, de_pypdf.size)
        assert directa.tobytes() == de_pypdf.tobytes()

    def test_se_decodifica_ya_reducido(self):
        _page, _nombre, obj = _pagina_e_imagen(jpx_pdf(width=1200, height=1600))

        img = pdf_compress._decode_jpx(obj, 400)

        assert img.size == (300, 400), "1/4 por lado: la mayor reducción que no baja del límite"

    def test_sin_reducir_si_ya_cabe(self):
        _page, _nombre, obj = _pagina_e_imagen(jpx_pdf(width=300, height=400))
        assert pdf_compress._decode_jpx(obj, A4_LONG_150).size == (300, 400)

    @pytest.mark.parametrize("cambio", ["smask_in_data", "cmyk"])
    def test_lo_que_no_es_simple_no_se_decodifica_directo(self, cambio):
        from pypdf.generic import NameObject, NumberObject

        _page, _nombre, obj = _pagina_e_imagen(jpx_pdf(width=300, height=400))
        if cambio == "smask_in_data":           # alfa dentro del propio JPEG2000
            obj[NameObject("/SMaskInData")] = NumberObject(1)
        else:                                   # el PDF dice CMYK y el códec RGB
            obj[NameObject("/ColorSpace")] = NameObject("/DeviceCMYK")

        assert pdf_compress._decode_jpx(obj, 10**6) is None

    def test_comprimir_un_jpx_no_pasa_por_pypdf_ni_lo_decodifica_completo(self, monkeypatch):
        from PIL import Jpeg2KImagePlugin

        _sin_pypdf(monkeypatch)
        tamanos = []
        real_load = Jpeg2KImagePlugin.Jpeg2KImageFile.load

        def _load(self):
            salida = real_load(self)
            tamanos.append(self.size)       # Pillow aplica `reduce` DENTRO de load
            return salida

        monkeypatch.setattr(Jpeg2KImagePlugin.Jpeg2KImageFile, "load", _load)
        raw = jpx_pdf(width=2480, height=3508, resolution=300)

        out = compress_pdf(raw, target_bytes=len(raw) - 1)

        assert out is not None and len(out) < len(raw)
        (xo,) = _xobjects(out)
        assert xo["/Filter"] == "/DCTDecode"
        assert max(xo["/Width"], xo["/Height"]) == A4_LONG_150
        assert tamanos and max(max(s) for s in tamanos) <= A4_LONG_150, tamanos


class TestMascaraSuave:
    """Una imagen con `/SMask` (un PNG con transparencia pasado a PDF) iba por
    pypdf, que le pega el alfa y la re-codifica a PNG -o a JPEG2000 si era
    JPEG- antes de devolverla (~2 s por hoja A4 a 300 dpi). Ahora imagen y
    máscara se decodifican directo y se aplana sobre blanco: lo MISMO que salía
    de pypdf + `_for_jpeg`."""

    @pytest.mark.parametrize("base,mode", [
        ("flate", "RGB"), ("flate", "L"), ("jpeg", "RGB"), ("jpx", "RGB"),
    ])
    def test_da_lo_mismo_que_pypdf_aplanado(self, base, mode):
        page, nombre, obj = _pagina_e_imagen(masked_pdf(base=base, mode=mode))
        jpeg = _jpeg_de(obj) if base == "jpeg" else None

        directa, ruta = pdf_compress._decode_direct(obj, 10**6, jpeg)
        esperada = pdf_compress._for_jpeg(page.images[nombre].image)

        assert ruta == "smask"
        assert directa.size == esperada.size
        assert directa.convert("RGB").tobytes() == esperada.convert("RGB").tobytes()

    def test_la_escala_de_grises_se_queda_en_grises(self):
        _page, _nombre, obj = _pagina_e_imagen(masked_pdf(mode="L"))
        directa, _ruta = pdf_compress._decode_direct(obj, 10**6)
        assert directa.mode == "L", "un tercio del JPEG que saldría en RGB"

    def test_una_mascara_de_otra_medida_se_ignora_como_en_pypdf(self):
        page, nombre, obj = _pagina_e_imagen(masked_pdf(mask_size=(300, 400)))

        directa, _ruta = pdf_compress._decode_direct(obj, 10**6)
        esperada = pdf_compress._for_jpeg(page.images[nombre].image)

        assert directa.convert("RGB").tobytes() == esperada.convert("RGB").tobytes()

    @pytest.mark.parametrize("base", ["jpeg", "jpx"])
    def test_ya_reducida_la_mascara_se_escala_y_se_ve_igual(self, base):
        """Con la imagen decodificada en chico (`draft`/`reduce`) la máscara se
        escala a su medida: no es idéntica píxel a píxel, pero sí a la vista."""
        page, nombre, obj = _pagina_e_imagen(
            masked_pdf(base=base, width=1200, height=1600))
        jpeg = _jpeg_de(obj) if base == "jpeg" else None

        directa, _ruta = pdf_compress._decode_direct(obj, 400, jpeg)
        esperada = pdf_compress._for_jpeg(page.images[nombre].image)

        assert max(directa.size) < 1600, "se decodificó reducida"
        assert _parecidas(directa, esperada) < 3

    def test_una_mascara_con_matte_va_por_pypdf(self):
        _page, _nombre, obj = _pagina_e_imagen(masked_pdf(matte=True))
        assert pdf_compress._decode_direct(obj, 10**6) == (None, None)

    def test_comprimir_con_mascara_no_pasa_por_pypdf(self, monkeypatch):
        _sin_pypdf(monkeypatch)
        raw = masked_pdf(width=1200, height=1600, resolution=150)

        out = compress_pdf(raw, target_bytes=len(raw) - 1)

        assert out is not None and len(out) < len(raw)
        (xo,) = _xobjects(out)
        assert xo["/Filter"] == "/DCTDecode"
        assert "/SMask" not in xo, "el alfa ya va aplanado sobre blanco"


class TestRutasEnStats:
    """`stats["images"]` cuenta por qué ruta se decodificó cada imagen en la
    última pasada y `stats["pypdf_ms"]` cuánto costó lo que aún va por pypdf:
    van al span `titulatec.prepare_document`, así la próxima subida lenta dice
    en Tempo QUÉ la hizo lenta (la de 10.6 s solo decía «comprimir»)."""

    def test_cuenta_cada_imagen_por_su_ruta(self):
        raw = merge_pdfs(
            photo_pdf(width=1200, height=1600, resolution=150, quality=95),   # JPEG q95
            flate_pdf(width=600, height=800),
            jpx_pdf(width=600, height=800, resolution=72),
            masked_pdf(),
        )
        stats = {}

        out = compress_pdf(raw, target_bytes=len(raw) - 1, stats=stats)

        assert out is not None
        assert stats["images"] == {"jpeg": 1, "flat": 1, "jpx": 1, "smask": 1}
        assert stats["pypdf_ms"] == 0

    def test_lo_que_va_por_pypdf_se_cuenta_y_se_cronometra(self):
        raw = merge_pdfs(_variante_flate("decode"),
                         photo_pdf(width=1200, height=1600, resolution=150, quality=95))
        stats = {}

        compress_pdf(raw, target_bytes=len(raw) - 1, stats=stats)

        assert stats["images"] == {"pypdf": 1, "jpeg": 1}
        assert stats["pypdf_ms"] > 0

    def test_una_imagen_que_no_se_decodifica_cuenta_como_error(self):
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(
            photo_pdf(width=1700, height=2200, resolution=200, pages=2))))
        xobjs = writer.pages[0]["/Resources"]["/XObject"]
        xobjs[list(xobjs)[0]].get_object()._data = os.urandom(200_000)
        buf = io.BytesIO()
        writer.write(buf)
        stats = {}

        compress_pdf(buf.getvalue(), target_bytes=len(buf.getvalue()) - 1, stats=stats)

        assert stats["images"] == {"error": 1, "jpeg": 1}

    def test_si_ya_cabe_no_hay_rutas(self):
        stats = {}
        compress_pdf(small_pdf(), target_bytes=TARGET, stats=stats)
        assert (stats["images"], stats["pypdf_ms"]) == ({}, 0)

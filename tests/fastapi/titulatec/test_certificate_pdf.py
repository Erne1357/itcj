"""`utils/certificate_pdf.render_certificates_pdf`: el PDF de un lote de
constancias (Tarea 3, spec `2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 y §7: "constancias ... PDF con WeasyPrint: 3 por página y texto
extraíble con pypdf"; Tarea 1 de
`2026-10-02-titulatec-constancias-y-pendientes-design.md` §2 E4/E8 y §3.1:
`per_page` 2 o 3 elegido al abrir el PDF, plantilla en dos piezas).

Puro: no toca Postgres (`Certificate(...)` se construye en memoria, sin
`db_session.add`/`flush` -- el renderizador solo LEE atributos del objeto,
nunca consulta la base), así que estos tests no necesitan la fixture
`db_session`. Mismo patrón que `test_pdf_compress.py` (PDFs sintéticos, nada
de archivos en disco).
"""
from __future__ import annotations

import io
from datetime import datetime

import pytest
from pypdf import PdfReader

from itcj2.apps.titulatec.models import Certificate
from itcj2.apps.titulatec.utils.certificate_pdf import (
    ALLOWED_PER_PAGE, DEFAULT_PER_PAGE, render_certificates_pdf,
)


def _cert(kind="library_clearance", number="BIB-2026-0001", voided_at=None,
         period_label="Agosto-Diciembre 2026", program_name="Ingeniería en Sistemas Computacionales",
         control_number="20261234", student_name="ALUMNO DE PRUEBA UNO"):
    return Certificate(
        kind=kind,
        number=number,
        process_id=1,
        source_ref=f"{kind}:1",
        control_number=control_number,
        student_name=student_name,
        program_name=program_name,
        period_label=period_label,
        issued_at=datetime(2026, 9, 28, 10, 0, 0),
        issued_by_id=1,
        voided_at=voided_at,
    )


def _texto(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(p.extract_text() for p in reader.pages)


def test_allowed_per_page_y_default():
    assert ALLOWED_PER_PAGE == (2, 3)
    assert DEFAULT_PER_PAGE == 3


def test_per_page_invalido_da_valueerror():
    with pytest.raises(ValueError):
        render_certificates_pdf([_cert()], per_page=4)


def test_cuatro_constancias_dan_dos_paginas_con_texto_extraible():
    certs = [_cert(number=f"BIB-2026-000{i}") for i in range(1, 5)]

    pdf = render_certificates_pdf(certs)

    assert pdf[:4] == b"%PDF"
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2

    texto = "\n".join(p.extract_text() for p in reader.pages)
    assert "BIB-2026-0001" in texto          # número de folio
    assert "20261234" in texto               # número de control
    assert "ALUMNO DE PRUEBA UNO" in texto   # nombre
    assert "Ingeniería en Sistemas Computacionales" in texto  # carrera
    assert "Agosto-Diciembre 2026" in texto  # semestre


@pytest.mark.parametrize("n,per_page,paginas", [
    # per_page=3 (el de siempre, D7/omisión)
    (1, 3, 1), (2, 3, 1), (3, 3, 1), (4, 3, 2), (6, 3, 2), (7, 3, 3),
    # per_page=2 (spec §3.1/E4)
    (1, 2, 1), (2, 2, 1), (3, 2, 2), (4, 2, 2), (5, 2, 3), (6, 2, 3),
])
def test_paginacion_segun_per_page(n, per_page, paginas):
    certs = [_cert(number=f"BIB-2026-{i:04d}") for i in range(1, n + 1)]

    reader = PdfReader(io.BytesIO(render_certificates_pdf(certs, per_page=per_page)))

    assert len(reader.pages) == paginas


def test_cinco_constancias_en_2_por_hoja_dan_3_paginas_repartidas_2_2_1():
    """Pruebas mínimas §5 de
    `2026-10-02-titulatec-constancias-y-pendientes-design.md`: no basta con
    contar páginas -- confirma que el reparto real es 2/2/1 (no 1/2/2 ni
    cualquier otra combinación que también sumara 3 páginas)."""
    certs = [_cert(number=f"BIB-2026-{i:04d}") for i in range(1, 6)]

    reader = PdfReader(io.BytesIO(render_certificates_pdf(certs, per_page=2)))

    assert len(reader.pages) == 3
    textos = [p.extract_text() for p in reader.pages]
    assert "BIB-2026-0001" in textos[0] and "BIB-2026-0002" in textos[0]
    assert "BIB-2026-0003" not in textos[0]
    assert "BIB-2026-0003" in textos[1] and "BIB-2026-0004" in textos[1]
    assert "BIB-2026-0005" not in textos[1]
    assert "BIB-2026-0005" in textos[2]
    assert "BIB-2026-0001" not in textos[2] and "BIB-2026-0003" not in textos[2]


def test_cinco_constancias_en_3_por_hoja_dan_2_paginas_repartidas_3_2():
    """Mismas 5 constancias que la prueba hermana de arriba, con el OTRO
    acomodo: 3 + 2, nunca 2 + 3 (`certs` se agrupa en el orden recibido)."""
    certs = [_cert(number=f"BIB-2026-{i:04d}") for i in range(1, 6)]

    reader = PdfReader(io.BytesIO(render_certificates_pdf(certs, per_page=3)))

    assert len(reader.pages) == 2
    textos = [p.extract_text() for p in reader.pages]
    assert all(f"BIB-2026-000{i}" in textos[0] for i in (1, 2, 3))
    assert "BIB-2026-0004" not in textos[0] and "BIB-2026-0005" not in textos[0]
    assert "BIB-2026-0004" in textos[1] and "BIB-2026-0005" in textos[1]


def test_una_sola_ranura_en_la_hoja_no_lleva_linea_de_corte():
    """La línea de corte (`.cut`, con la tijera) va ENTRE ranuras de la misma
    hoja, nunca tras la última -- con una sola constancia en el grupo no debe
    haber ninguna. Revisa el HTML crudo (mismo patrón que
    `test_mail_compose.py`: `titulatec_templates.get_template(...).render`)
    en vez del PDF: más rápido y no depende de que el extractor de texto del
    PDF reconozca el glifo de la tijera (U+2702)."""
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    from itcj2.apps.titulatec.utils.certificate_pdf import _cert_ctx

    grupos = [[_cert_ctx(_cert())]]
    html = titulatec_templates.get_template(
        "titulatec/certificates/sheet.html").render(groups=grupos, per_page=2)

    assert 'class="cut"' not in html


def test_tres_ranuras_en_la_hoja_llevan_dos_lineas_de_corte():
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    from itcj2.apps.titulatec.utils.certificate_pdf import _cert_ctx

    grupos = [[_cert_ctx(_cert(number=f"BIB-2026-000{i}")) for i in range(1, 4)]]
    html = titulatec_templates.get_template(
        "titulatec/certificates/sheet.html").render(groups=grupos, per_page=3)

    assert html.count('class="cut"') == 2


def test_slot_foot_se_ancla_al_fondo_con_posicion_absoluta():
    """Ruling R1 (fix round 1): WeasyPrint 70 tiene soporte PARCIAL de flex
    -- el truco `margin-top: auto` (para empujar un hijo al fondo de un
    contenedor `flex-direction: column`) no tenía efecto ahí: el pie
    («Fecha de emisión» / «Nombre, firma y sello») quedaba pegado justo
    debajo de la tabla de datos, con el resto de la ranura en blanco por
    debajo (hasta ~55% vacío en 2 por hoja) y SIN espacio arriba de la línea
    para firmar y sellar -- confirmado visualmente corriendo
    `.superpowers/sdd/2026-10-02-titulatec-constancias-y-pendientes/
    render_sample.py` y leyendo `sample_2xhoja.pdf`/`sample_3xhoja.pdf` con
    el visor de PDF (ver el report del fix para el detalle).

    No se fija con las coordenadas que entrega pypdf: se probó y no son una
    base confiable para ESTA plantilla (WeasyPrint aísla cada `.slot` --
    `overflow: hidden` + posicionamiento absoluto -- en su propio espacio de
    transformación; los valores de `PageObject.extract_text(visitor_text=
    ...)` caen FUERA del `mediabox` de la página, ~980pt en una página de
    792pt de alto). Se fija en cambio el MECANISMO -el CSS mismo, leído del
    `<style>` de `sheet.html` vía el loader de Jinja, sin pasar por
    WeasyPrint-: `.slot` sigue siendo `position: relative` (ya lo era) y
    `.slot-foot` depende de `position: absolute` anclada con `bottom`,
    nunca de `margin-top: auto`."""
    import re

    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    source, _, _ = titulatec_templates.env.loader.get_source(
        titulatec_templates.env, "titulatec/certificates/sheet.html")
    style = source.split("<style>", 1)[1].split("</style>", 1)[0]
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL)   # sin comentarios CSS

    # selector EXACTO -> cuerpo de la regla; distingue `.slot-foot` de
    # `.sheet--2 .slot-foot` (que solo ajusta el tamaño de letra).
    rules = {sel.strip(): body for sel, body in
             re.findall(r"([^{}]+)\{([^{}]*)\}", style)}

    slot = rules[".slot"]
    assert "position" in slot and "relative" in slot, slot

    pie = rules.get(".slot-foot")
    assert pie is not None, "no se encontró la regla .slot-foot en sheet.html"
    assert "position" in pie and "absolute" in pie, pie
    assert "bottom" in pie, pie
    assert "margin-top" not in pie, pie


@pytest.mark.parametrize("per_page", [2, 3])
def test_constancia_anulada_lleva_el_sello_en_los_dos_acomodos(per_page):
    certs = [_cert(voided_at=datetime(2026, 9, 29, 9, 0, 0))]

    texto = _texto(render_certificates_pdf(certs, per_page=per_page))

    assert "ANULADA" in texto


def test_constancia_vigente_no_lleva_el_sello_anulada():
    certs = [_cert(voided_at=None)]

    texto = _texto(render_certificates_pdf(certs))

    assert "ANULADA" not in texto


def test_cada_tipo_usa_su_titulo_y_departamento():
    from itcj2.apps.titulatec.services.certificate_service import CERT_KINDS

    certs = [_cert(kind="library_clearance", number="BIB-2026-0001"),
             _cert(kind="survey_release", number="GTV-2026-0001")]

    texto = _texto(render_certificates_pdf(certs))

    assert CERT_KINDS["library_clearance"]["title"] in texto
    assert CERT_KINDS["survey_release"]["title"] in texto
    assert CERT_KINDS["library_clearance"]["department"] in texto
    assert CERT_KINDS["survey_release"]["department"] in texto


def test_fecha_de_emision_en_espanol():
    certs = [_cert()]
    certs[0].issued_at = datetime(2026, 9, 28, 10, 0, 0)

    texto = _texto(render_certificates_pdf(certs))

    assert "28 de septiembre de 2026" in texto

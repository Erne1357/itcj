"""`utils/certificate_pdf.render_certificates_pdf`: el PDF de un lote de
constancias (Tarea 3, spec `2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5 y §7: "constancias ... PDF con WeasyPrint: 3 por página y texto
extraíble con pypdf").

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
from itcj2.apps.titulatec.utils.certificate_pdf import PER_PAGE, render_certificates_pdf


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


def test_per_page_es_3():
    assert PER_PAGE == 3


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


@pytest.mark.parametrize("n,paginas", [(1, 1), (2, 1), (3, 1), (4, 2), (6, 2), (7, 3)])
def test_paginacion_de_a_3(n, paginas):
    certs = [_cert(number=f"BIB-2026-{i:04d}") for i in range(1, n + 1)]

    reader = PdfReader(io.BytesIO(render_certificates_pdf(certs)))

    assert len(reader.pages) == paginas


def test_constancia_anulada_lleva_el_sello_anulada():
    certs = [_cert(voided_at=datetime(2026, 9, 29, 9, 0, 0))]

    texto = _texto(render_certificates_pdf(certs))

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

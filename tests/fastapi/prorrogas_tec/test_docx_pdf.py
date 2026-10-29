from io import BytesIO

import pytest
from docx import Document

from itcj2.core.utils import docx_pdf
from itcj2.core.utils.docx_pdf import PdfConversionError


def test_sin_libreoffice_lanza_pdf_conversion_error(monkeypatch):
    monkeypatch.setattr(docx_pdf, "find_libreoffice", lambda: None)
    with pytest.raises(PdfConversionError, match="LibreOffice no está instalado"):
        docx_pdf.docx_to_pdf(b"x", kind="prorrogas_documento")


def test_helpdesk_delega_en_core(monkeypatch):
    from itcj2.apps.helpdesk.services import document_service
    monkeypatch.setattr(document_service, "docx_to_pdf", lambda data, *, kind: b"%PDF-" + kind.encode())
    assert document_service._convert_docx_to_pdf(BytesIO(b"docx"), "solicitud").read() == b"%PDF-solicitud"


@pytest.mark.skipif(docx_pdf.find_libreoffice() is None, reason="sin LibreOffice")
def test_convierte_un_docx_real():
    d = Document()
    d.add_paragraph("hola")
    buf = BytesIO()
    d.save(buf)
    assert docx_pdf.docx_to_pdf(buf.getvalue(), kind="prorrogas_documento").startswith(b"%PDF")

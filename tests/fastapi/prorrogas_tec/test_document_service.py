from datetime import date, datetime

import pytest

from itcj2.apps.prorrogas_tec.documents.catalog import sample_signature_png
from itcj2.apps.prorrogas_tec.documents.values import SignatureInfo
from itcj2.apps.prorrogas_tec.models.signature import ProrrogaSignature
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.core.utils import docx_pdf

HOY = date(2091, 2, 1)


def _firma(req):
    return SignatureInfo(png=sample_signature_png(), signer_id=req.student_id,
                         signed_at=datetime(2091, 2, 1, 10, 42), ip="10.0.0.1", user_agent="pytest")


def test_formato_de_solicitud_firmado(db_session, solicitud, pdf_falso):
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=solicitud.student_id,
                                   today=HOY, signature=_firma(solicitud))
    assert doc.version == 1 and doc.signed_at == datetime(2091, 2, 1, 10, 42)
    assert doc.context["folio"] == f"PR-{solicitud.id:05d}" and doc.context["semestre"] == "enero – junio 2091"
    assert doc.context["firma_estudiante_leyenda"].startswith("Firmado electrónicamente por")
    assert pdf_falso.calls[-1] == {"placeholders": set(), "kind": "prorrogas_documento"}
    assert DocumentService.read_pdf(doc) == b"%PDF-1.4 fake"
    sig = db_session.query(ProrrogaSignature).filter_by(document_id=doc.id).one()
    assert sig.pdf_sha256 == doc.sha256 and sig.ip == "10.0.0.1"


def test_sin_firma_la_leyenda_queda_vacia(db_session, solicitud, pdf_falso):
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=None, today=HOY)
    assert doc.context["firma_estudiante_leyenda"] == "" and doc.signed_at is None


def test_una_nueva_version_sustituye_a_la_anterior(db_session, solicitud, pdf_falso):
    v1 = DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    v2 = DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    assert (v1.version, v2.version) == (1, 2) and v1.superseded_at is not None
    assert [d.id for d in DocumentService.current(db_session, solicitud)] == [v2.id]


def test_el_texto_libre_se_limpia(db_session, solicitud, pdf_falso):
    solicitud.reason = "Línea 1\nLínea 2\x07   fin"
    doc = DocumentService.generate(db_session, solicitud, "formato_solicitud", actor_id=None, today=HOY)
    assert doc.context["motivo"] == "Línea 1 Línea 2 fin"


def test_sin_pdf_lanza_pdf_no_disponible(db_session, solicitud, monkeypatch):
    import subprocess
    from itcj2.apps.prorrogas_tec.services.errors import ServiceError

    def boom(data, *, kind):
        raise subprocess.TimeoutExpired(["soffice"], 60)

    monkeypatch.setattr(docx_pdf, "docx_to_pdf", boom)
    with pytest.raises(ServiceError) as e:
        DocumentService.generate(db_session, solicitud, "carta_aceptacion", actor_id=None, today=HOY)
    assert e.value.code == "pdf_no_disponible" and e.value.status == 503


@pytest.mark.skipif(docx_pdf.find_libreoffice() is None, reason="sin LibreOffice")
def test_pdf_real_de_la_carta_de_rechazo(db_session, solicitud):
    doc = DocumentService.generate(db_session, solicitud, "carta_rechazo", actor_id=None, today=HOY,
                                   extra={"motivo_rechazo": "Falta el comprobante de ingresos."})
    assert DocumentService.read_pdf(doc).startswith(b"%PDF")

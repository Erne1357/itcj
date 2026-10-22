"""Archivos de revisión de la fase 5: validación (PDF/Word) y disco. Módulo puro, sin BD."""
import io
import zipfile

import pytest

from itcj2.apps.titulatec.utils import review_files as rf
from itcj2.apps.titulatec.utils import storage

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64


def _zip(names: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in names.items():
            z.writestr(n, c)
    return buf.getvalue()


DOCX = _zip({"[Content_Types].xml": "<x/>", "word/document.xml": "<w/>"})


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_base", lambda: tmp_path)
    return tmp_path


def test_tipos_y_constantes():
    assert rf.REVIEW_TYPES["pdf"] == "application/pdf"
    assert rf.REVIEW_TYPES["doc"] == "application/msword"
    assert rf.REVIEW_TYPES["docx"].endswith("wordprocessingml.document")
    assert issubclass(rf.ReviewFileError, ValueError)


def test_pdf_valido():
    assert rf.validate(PDF, "Tesis.PDF") == ("pdf", "application/pdf")


def test_docx_valido():
    assert rf.validate(DOCX, "t.docx") == ("docx", rf.REVIEW_TYPES["docx"])


def test_doc_valido_firma_ole():
    assert rf.validate(OLE, "t.doc") == ("doc", "application/msword")


def test_docx_renombrado_pdf_falla():
    with pytest.raises(rf.ReviewFileError, match="no es un PDF o Word válido"):
        rf.validate(DOCX, "t.pdf")


def test_pdf_renombrado_docx_falla():
    with pytest.raises(rf.ReviewFileError, match="no es un PDF o Word válido"):
        rf.validate(PDF, "t.docx")


def test_zip_sin_word_falla():
    raw = _zip({"xl/workbook.xml": "<x/>"})
    with pytest.raises(rf.ReviewFileError, match="no es un PDF o Word válido"):
        rf.validate(raw, "t.docx")


def test_zip_corrupto_falla():
    with pytest.raises(rf.ReviewFileError, match="no es un PDF o Word válido"):
        rf.validate(b"PK\x03\x04basura", "t.docx")


def test_vacio():
    with pytest.raises(rf.ReviewFileError, match="El archivo está vacío."):
        rf.validate(b"", "t.pdf")


def test_extension_no_permitida():
    with pytest.raises(rf.ReviewFileError,
                       match=r"Solo se aceptan archivos PDF o Word \(\.docx, \.doc\)\."):
        rf.validate(PDF, "t.exe")
    with pytest.raises(rf.ReviewFileError, match="Solo se aceptan"):
        rf.validate(PDF, "sinextension")


def test_supera_limite(monkeypatch):
    monkeypatch.setattr(rf, "max_bytes", lambda: 1024 * 1024)
    raw = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # 1 MB + 1 byte
    assert len(raw) == 1024 * 1024 + 1
    with pytest.raises(rf.ReviewFileError) as ei:
        rf.validate(raw, "t.pdf")
    assert str(ei.value) == "El archivo supera 1 MB."


def test_docx_con_basura_al_inicio_falla():
    with pytest.raises(rf.ReviewFileError) as ei:
        rf.validate(b"junk" + DOCX, "t.docx")
    assert str(ei.value) == "El archivo no es un PDF o Word válido."


def test_write_rechaza_periodo_o_control_vacio(base):
    for period, control in (("", "1"), ("  ", "1"), ("p", ""), ("p", "  ")):
        with pytest.raises(rf.ReviewFileError):
            rf.write(PDF, period_code=period, control_number=control,
                     filename="v1_1.pdf")
    assert not list(base.iterdir())


def test_max_bytes_lee_settings_en_cada_llamada(monkeypatch):
    from itcj2.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "TITULATEC_REVIEW_MAX_FILE_MB", 3, raising=False)
    assert rf.max_bytes() == 3 * 1024 * 1024
    monkeypatch.setattr(s, "TITULATEC_REVIEW_MAX_FILE_MB", 4, raising=False)
    assert rf.max_bytes() == 4 * 1024 * 1024


def test_review_days_default():
    assert isinstance(rf.review_days(), int) and rf.review_days() >= 1


def test_nombres():
    assert rf.version_filename(2, "20110001", "pdf") == "v2_20110001.pdf"
    assert rf.attachment_filename(15, "20110001", "docx") == "m15_20110001.docx"
    with pytest.raises(rf.ReviewFileError):
        rf.version_filename(1, "../x", "pdf")
    with pytest.raises(rf.ReviewFileError):
        rf.attachment_filename(1, "20110001", "../pdf")


def test_write_en_carpeta_revision(base):
    rel = rf.write(PDF, period_code="2026-1", control_number="20110001",
                   filename="v1_20110001.pdf")
    assert rel == "2026-1/20110001/revision/v1_20110001.pdf"
    assert (base / rel).read_bytes() == PDF
    # sin temporales sobrantes
    assert [p.name for p in (base / "2026-1/20110001/revision").iterdir()] == ["v1_20110001.pdf"]


def test_write_reemplaza_atomico(base):
    rf.write(PDF, period_code="p", control_number="1", filename="v1_1.pdf")
    rel = rf.write(PDF + b"x", period_code="p", control_number="1", filename="v1_1.pdf")
    assert (base / rel).read_bytes() == PDF + b"x"


def test_write_no_escapa(base):
    with pytest.raises(rf.ReviewFileError):
        rf.write(PDF, period_code="p", control_number="1", filename="../../evil.pdf")
    with pytest.raises(rf.ReviewFileError):
        rf.write(PDF, period_code="..", control_number="../..", filename="v1_1.pdf")
    assert not list(base.parent.glob("evil*"))


def test_disposition():
    assert rf.disposition("pdf") == "inline"
    assert rf.disposition("docx") == "attachment"
    assert rf.disposition("doc") == "attachment"


def test_download_name():
    assert rf.download_name("Tésis final (v2).pdf", "pdf") == "Tesis_final_v2.pdf"
    assert rf.download_name("../../etc/passwd", "docx") == "passwd.docx"
    assert rf.download_name("", "doc") == "revision.doc"
    assert rf.download_name("informe.pdf", "docx") == "informe.docx"

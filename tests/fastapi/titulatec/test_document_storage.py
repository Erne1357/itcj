"""`utils/storage.py` y `DocumentService.save`: tope de 2 MB con compresion
automatica y nombres `{control}_{TIPO}.{ext}` en disco (brief 2026-09-28).

* PDF <= `TITULATEC_MAX_PDF_SIZE` (2 MB)        -> se guarda INTACTO.
* PDF >  2 MB y <= `..._UPLOAD_SIZE` (20 MB)    -> se comprime; si no baja de
  2 MB, `StorageError` y no queda NADA (ni disco ni BD).
* PDF >  20 MB                                  -> `StorageError` sin intentar.
* Nombre en disco `{control}_{ETIQUETA}.pdf`: ACTA / CERTIFICADO / CURP, y
  `type_code.upper()` para el resto. Resubir borra el nombre viejo
  `{type_code}.*`. Un control con caracteres raros es error, no un nombre
  inventado.

`TITULATEC_UPLOAD_PATH` se redirige a `tmp_path` parcheando `storage._base`,
igual que `test_scope_guard.py` y `test_student_phase_guard.py`.
"""
from __future__ import annotations

import pytest

from itcj2.apps.titulatec.utils import pdf_compress, storage
from itcj2.apps.titulatec.utils.storage import StorageError
from itcj2.config import get_settings
from tests.fastapi.titulatec._pdf_samples import MB, noise_pdf, photo_pdf, small_pdf

CONTROL = "99000401"
PERIOD = "2029A"

MSG_ILEGIBLE = "No pudimos leer tu PDF; vuelve a generarlo o escanéalo de nuevo."


def _msg_incomprimible(raw: bytes, limit_mb: int = 2) -> str:
    return (f"Tu PDF pesa {len(raw) / MB:.1f} MB y aun comprimido supera {limit_mb} MB; "
            "escanéalo en menor resolución o en blanco y negro.")


def _msg_demasiado_grande(size: int, max_mb: int = 20) -> str:
    return f"Tu PDF pesa {size / MB:.1f} MB; el máximo que aceptamos es {max_mb} MB."


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    return tmp_path


def _save(raw, *, type_code="curp", control=CONTROL, name="escaneo.pdf"):
    return storage.save_document(
        raw=raw, original_name=name, content_type="application/pdf",
        period_code=PERIOD, control_number=control, type_code=type_code,
        file_kind="pdf",
    )


def _files(root) -> list:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
def test_los_topes_de_la_config():
    s = get_settings()
    assert s.TITULATEC_MAX_PDF_SIZE == 2 * MB
    assert s.TITULATEC_MAX_PDF_UPLOAD_SIZE == 20 * MB


def test_la_ayuda_sale_de_la_config(monkeypatch):
    assert storage.pdf_upload_hint() == (
        "PDF de hasta 2 MB. Si pesa más (hasta 20 MB), lo comprimimos automáticamente.")
    monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_SIZE", 3 * MB)
    monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_UPLOAD_SIZE", 25 * MB)
    assert storage.pdf_upload_hint() == (
        "PDF de hasta 3 MB. Si pesa más (hasta 25 MB), lo comprimimos automáticamente.")


# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("type_code,label", [
    ("birth_certificate", "ACTA"),
    ("high_school_cert", "CERTIFICADO"),
    ("curp", "CURP"),
    ("ine", "INE"),
    ("egel_proof", "EGEL_PROOF"),
    ("anexo_iii", "ANEXO_III"),
    ("residency_proof", "RESIDENCY_PROOF"),
])
def test_etiqueta_y_nombre_de_archivo(type_code, label):
    assert storage.document_label(type_code) == label
    assert storage.document_filename(CONTROL, type_code, "pdf") == f"{CONTROL}_{label}.pdf"


def test_el_control_con_letra_de_traslado_se_respeta():
    assert storage.document_filename("B12345678", "curp", "pdf") == "B12345678_CURP.pdf"


@pytest.mark.parametrize("control", ["../x", "99-0001", "99 0001", "", "99000401\n",
                                     "99/0001", "ñ9000401"])
def test_un_control_con_caracteres_raros_es_error(control):
    with pytest.raises(StorageError):
        storage.document_filename(control, "curp", "pdf")


def test_nombre_de_descarga_con_control_invalido_no_revienta():
    """La descarga no puede fallar por el nombre: cae a la etiqueta sola."""
    assert storage.download_filename(CONTROL, "curp", "x/y/curp.pdf") == f"{CONTROL}_CURP.pdf"
    assert storage.download_filename("99-01", "curp", "x/y/curp.pdf") == "CURP.pdf"
    assert storage.download_filename(CONTROL, "birth_certificate", "a/acta.PDF") == \
        f"{CONTROL}_ACTA.pdf"


# ---------------------------------------------------------------------------
# save_document
# ---------------------------------------------------------------------------
class TestHasta2MB:
    def test_se_guarda_identico_con_el_nombre_nuevo(self, base):
        raw = small_pdf()

        meta = _save(raw, type_code="birth_certificate")

        dest = base / meta["file_path"]
        assert dest.name == f"{CONTROL}_ACTA.pdf"
        assert meta["file_path"] == f"{PERIOD}/{CONTROL}/documents/{CONTROL}_ACTA.pdf"
        assert dest.read_bytes() == raw
        assert meta["size_bytes"] == len(raw)
        assert meta["original_name"] == "escaneo.pdf"

    def test_no_se_llama_al_compresor(self, base, monkeypatch):
        def _no(*a, **k):
            raise AssertionError("no debe comprimir un PDF de <= 2 MB")
        monkeypatch.setattr(pdf_compress, "compress_pdf", _no)

        _save(small_pdf())


class TestMasDe2MB:
    def test_comprimible_se_guarda_comprimido_con_su_tamano_real(self, base):
        raw = photo_pdf()
        assert len(raw) > 2 * MB

        meta = _save(raw, type_code="high_school_cert")

        dest = base / meta["file_path"]
        stored = dest.read_bytes()
        assert dest.name == f"{CONTROL}_CERTIFICADO.pdf"
        assert stored != raw and stored.startswith(b"%PDF")
        assert len(stored) <= 2 * MB
        assert meta["size_bytes"] == len(stored)
        assert meta["mime_type"] == "application/pdf"

    def test_incomprimible_es_error_y_no_deja_nada(self, base):
        raw = noise_pdf()
        assert 2 * MB < len(raw) < 20 * MB

        with pytest.raises(StorageError) as exc:
            _save(raw)

        assert str(exc.value) == _msg_incomprimible(raw)
        assert _files(base) == [] and list(base.iterdir()) == []

    def test_ilegible_es_error_y_no_deja_nada(self, base):
        raw = b"%PDF-1.4\n" + b"basura " * (400 * 1024)
        assert len(raw) > 2 * MB

        with pytest.raises(StorageError) as exc:
            _save(raw)

        assert str(exc.value) == MSG_ILEGIBLE
        assert list(base.iterdir()) == []

    def test_mas_de_20mb_se_rechaza_antes_de_comprimir(self, base, monkeypatch):
        def _no(*a, **k):
            raise AssertionError("no debe intentar comprimir > 20 MB")
        monkeypatch.setattr(pdf_compress, "compress_pdf", _no)
        raw = b"%PDF-1.4\n" + b"0" * (20 * MB)

        with pytest.raises(StorageError) as exc:
            _save(raw)

        assert str(exc.value) == _msg_demasiado_grande(len(raw))
        assert list(base.iterdir()) == []

    def test_los_numeros_del_mensaje_salen_de_la_config(self, base, monkeypatch):
        monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_SIZE", 1 * MB)
        monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_UPLOAD_SIZE", 2 * MB)
        raw = noise_pdf()

        with pytest.raises(StorageError) as exc:
            _save(raw)

        assert str(exc.value) == _msg_demasiado_grande(len(raw), max_mb=2)


class TestExtension:
    def test_solo_pdf(self, base):
        with pytest.raises(StorageError):
            _save(small_pdf(), name="acta.docx")


class TestResubir:
    def test_borra_el_nombre_viejo_y_otras_extensiones_del_mismo_tipo(self, base):
        carpeta = base / PERIOD / CONTROL / "documents"
        carpeta.mkdir(parents=True)
        (carpeta / "curp.pdf").write_bytes(b"viejo")                  # nombre viejo
        (carpeta / f"{CONTROL}_CURP.jpg").write_bytes(b"otra ext")    # nuevo, otra ext
        (carpeta / "birth_certificate.pdf").write_bytes(b"acta vieja")  # OTRO tipo
        (carpeta / f"{CONTROL}_ACTA.pdf").write_bytes(b"acta nueva")    # OTRO tipo

        meta = _save(small_pdf(), type_code="curp")

        assert sorted(p.name for p in carpeta.iterdir()) == sorted([
            f"{CONTROL}_CURP.pdf", "birth_certificate.pdf", f"{CONTROL}_ACTA.pdf",
        ])
        assert (base / meta["file_path"]).read_bytes() == small_pdf()

    def test_resubir_el_mismo_tipo_sobrescribe(self, base):
        _save(photo_pdf(), type_code="curp")
        meta = _save(small_pdf(), type_code="curp")

        carpeta = (base / meta["file_path"]).parent
        assert [p.name for p in carpeta.iterdir()] == [f"{CONTROL}_CURP.pdf"]
        assert (base / meta["file_path"]).read_bytes() == small_pdf()


class TestControlInvalido:
    @pytest.mark.parametrize("control", ["99-0001", "../fuera", "99 0001"])
    def test_error_claro_y_nada_en_disco(self, base, control):
        with pytest.raises(StorageError) as exc:
            _save(small_pdf(), control=control)

        assert "número de control" in str(exc.value)
        assert list(base.iterdir()) == []


# ---------------------------------------------------------------------------
# DocumentService.save (BD real, sesion del test)
# ---------------------------------------------------------------------------
@pytest.fixture()
def proceso(base, db_session, seed_phase_defs, seed_document_types, make_cohort,
            make_student, make_process):
    def _build(control=None):
        seed_phase_defs()
        seed_document_types()
        student = make_student(control_number=control)
        proc = make_process(student, cohort=make_cohort(), current_phase=1)
        return proc, student
    return _build


def _doc_row(db, process_id, type_code="curp"):
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=type_code).first()


class TestDocumentServiceSave:
    def test_comprimible_guarda_fila_con_tamano_real_y_nombre_nuevo(self, proceso, base,
                                                                    db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()

        doc = DocumentService.save(db_session, proc, "curp", raw=photo_pdf(),
                                   original_name="mi curp.pdf",
                                   content_type="application/pdf",
                                   uploaded_by_id=student.id)

        stored = (base / doc.file_path).read_bytes()
        assert doc.file_path.endswith(f"/documents/{student.control_number}_CURP.pdf")
        assert doc.size_bytes == len(stored) <= 2 * MB
        assert doc.original_name == "mi curp.pdf"      # se sigue guardando

    def test_hasta_2mb_guarda_identico(self, proceso, base, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()

        doc = DocumentService.save(db_session, proc, "birth_certificate", raw=small_pdf(),
                                   original_name="acta.pdf", content_type="application/pdf",
                                   uploaded_by_id=student.id)

        assert (base / doc.file_path).read_bytes() == small_pdf()
        assert doc.size_bytes == len(small_pdf())

    def test_incomprimible_no_deja_fila_ni_archivo(self, proceso, base, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        raw = noise_pdf()

        with pytest.raises(StorageError) as exc:
            DocumentService.save(db_session, proc, "curp", raw=raw, original_name="c.pdf",
                                 content_type="application/pdf", uploaded_by_id=student.id)

        assert str(exc.value) == _msg_incomprimible(raw)
        assert _doc_row(db_session, proc.id) is None
        assert _files(base) == []

    def test_control_invalido_no_deja_fila_ni_archivo(self, proceso, base, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso(control="99-000402")

        with pytest.raises(StorageError):
            DocumentService.save(db_session, proc, "curp", raw=small_pdf(),
                                 original_name="c.pdf", content_type="application/pdf",
                                 uploaded_by_id=student.id)

        assert _doc_row(db_session, proc.id) is None
        assert _files(base) == []

    def test_resubir_actualiza_la_fila_y_borra_el_archivo_con_nombre_viejo(
            self, proceso, base, db_session, make_document):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        control = student.control_number
        viejo = f"{proc.cohort.period_code}/{control}/documents/curp.pdf"
        make_document(proc, type_code="curp", file_path=viejo)
        (base / viejo).parent.mkdir(parents=True)
        (base / viejo).write_bytes(b"%PDF-1.4 version anterior")

        doc = DocumentService.save(db_session, proc, "curp", raw=small_pdf(),
                                   original_name="curp2.pdf",
                                   content_type="application/pdf",
                                   uploaded_by_id=student.id)

        assert doc.version == 2
        assert doc.file_path == f"{proc.cohort.period_code}/{control}/documents/{control}_CURP.pdf"
        assert not (base / viejo).exists()
        assert (base / doc.file_path).read_bytes() == small_pdf()

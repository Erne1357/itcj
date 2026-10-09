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

Ronda 1 (revision 2026-09-28):

* m1: `prepare_document` (validar + comprimir, sin disco ni BD) y
  `write_document` (escribir) por separado, para que la ruta comprima fuera de
  la transaccion; `DocumentService.save(..., prepared=...)` ya no comprime.
* m5: se escribe a un temporal y se renombra; las versiones viejas se borran
  SOLO despues de escribir la nueva.
* m7: `type_code` fuera de `^[a-z0-9_]+$` es error y el nombre final pasa por
  `safe_join`.
* m8: el peso del mensaje se redondea HACIA ARRIBA (20 MB + 1 byte = 20.1).
"""
from __future__ import annotations

import math
import os

import pytest

from itcj2.apps.titulatec.utils import pdf_compress, storage
from itcj2.apps.titulatec.utils.storage import StorageError
from itcj2.config import get_settings
from tests.fastapi.titulatec._pdf_samples import MB, bilevel_noise_pdf, photo_pdf, small_pdf

CONTROL = "99000401"
PERIOD = "2029A"

MSG_ILEGIBLE = "No pudimos leer tu PDF; vuelve a generarlo o escanéalo de nuevo."


def _mb_arriba(size: int) -> str:
    """Un decimal, redondeado hacia arriba (nunca iguala al maximo)."""
    return f"{math.ceil(size * 10 / MB) / 10:.1f}"


def _msg_incomprimible(raw: bytes, limit_mb: int = 2) -> str:
    return (f"Tu PDF pesa {_mb_arriba(len(raw))} MB y aun comprimido supera {limit_mb} MB; "
            "escanéalo en menor resolución o en blanco y negro.")


def _msg_demasiado_grande(size: int, max_mb: int = 20) -> str:
    return f"Tu PDF pesa {_mb_arriba(size)} MB; el máximo que aceptamos es {max_mb} MB."


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


@pytest.mark.parametrize("type_code", ["../x", "Curp", "cu rp", "", "curp\n", "a/b",
                                       "ñandu", "curp.pdf"])
def test_un_type_code_fuera_del_patron_es_error(type_code):
    """m7: solo `^[a-z0-9_]+$`; el catalogo real (DML) ya cumple."""
    with pytest.raises(StorageError):
        storage.document_label(type_code)
    with pytest.raises(StorageError):
        storage.document_filename(CONTROL, type_code, "pdf")


def test_descarga_con_type_code_invalido_cae_a_un_nombre_generico():
    assert storage.download_filename(CONTROL, "../x", "a/b.pdf") == "documento.pdf"


# ---------------------------------------------------------------------------
# Redondeo del peso en los mensajes (m8)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size,texto", [
    (20 * MB + 1, "20.1"), (2 * MB + 1, "2.1"), (2 * MB, "2.0"),
    (int(2.4 * MB), "2.4"), (5 * MB - 1, "5.0"),
])
def test_el_peso_se_redondea_hacia_arriba(size, texto):
    assert storage._mb1(size) == texto


def test_20mb_y_un_byte_no_dice_que_pesa_lo_mismo_que_el_maximo():
    with pytest.raises(StorageError) as exc:
        storage.check_pdf_upload_size(20 * MB + 1)

    assert str(exc.value) == "Tu PDF pesa 20.1 MB; el máximo que aceptamos es 20 MB."


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

    def test_otro_tipo_se_guarda_con_su_codigo_en_mayusculas(self, base):
        """m6: `_INE` en disco, probado por storage (no solo por el CLI)."""
        meta = _save(small_pdf(), type_code="ine")

        assert meta["file_path"] == f"{PERIOD}/{CONTROL}/documents/{CONTROL}_INE.pdf"
        assert (base / meta["file_path"]).read_bytes() == small_pdf()


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
        raw = bilevel_noise_pdf()
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
        raw = bilevel_noise_pdf()

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


class TestTypeCodeYRutaFinal:
    """m7."""

    def test_type_code_invalido_no_deja_nada(self, base):
        with pytest.raises(StorageError):
            _save(small_pdf(), type_code="../../fuera")

        assert _files(base) == []

    def test_el_nombre_final_pasa_por_safe_join(self, base, monkeypatch):
        """Aunque un nombre raro burlara las validaciones, no sale de la carpeta."""
        monkeypatch.setattr(storage, "document_filename", lambda *a, **k: "../fuera.pdf")

        with pytest.raises(StorageError):
            _save(small_pdf())

        assert _files(base) == []


# ---------------------------------------------------------------------------
# Escritura atomica (m5)
# ---------------------------------------------------------------------------
class TestEscrituraAtomica:
    def _carpeta(self, base):
        carpeta = base / PERIOD / CONTROL / "documents"
        carpeta.mkdir(parents=True)
        return carpeta

    @staticmethod
    def _falla_al_renombrar(monkeypatch):
        def _boom(*a, **k):
            raise OSError("disco lleno")
        monkeypatch.setattr(storage.os, "replace", _boom)

    def test_si_falla_la_escritura_el_nombre_viejo_sigue_y_no_quedan_temporales(
            self, base, monkeypatch):
        carpeta = self._carpeta(base)
        (carpeta / "curp.pdf").write_bytes(b"viejo")
        self._falla_al_renombrar(monkeypatch)

        with pytest.raises(OSError):
            _save(small_pdf())

        assert [p.name for p in carpeta.iterdir()] == ["curp.pdf"]
        assert (carpeta / "curp.pdf").read_bytes() == b"viejo"

    def test_si_falla_la_escritura_el_mismo_nombre_conserva_lo_anterior(
            self, base, monkeypatch):
        carpeta = self._carpeta(base)
        destino = carpeta / f"{CONTROL}_CURP.pdf"
        destino.write_bytes(b"anterior")
        self._falla_al_renombrar(monkeypatch)

        with pytest.raises(OSError):
            _save(small_pdf())

        assert [p.name for p in carpeta.iterdir()] == [destino.name]
        assert destino.read_bytes() == b"anterior"

    def test_los_viejos_se_borran_despues_de_escribir_el_nuevo(self, base, monkeypatch):
        carpeta = self._carpeta(base)
        viejo = carpeta / "curp.pdf"
        viejo.write_bytes(b"viejo")
        vistos = []
        real = os.replace

        def _espia(src, dst):
            vistos.append(viejo.exists())
            return real(src, dst)

        monkeypatch.setattr(storage.os, "replace", _espia)

        meta = _save(small_pdf())

        assert vistos == [True], "al escribir el nuevo, el viejo seguia ahi"
        assert not viejo.exists()
        assert (base / meta["file_path"]).read_bytes() == small_pdf()


# ---------------------------------------------------------------------------
# Preparar (CPU, sin disco) y escribir por separado (m1)
# ---------------------------------------------------------------------------
class TestPrepararYEscribir:
    def test_preparar_comprime_sin_tocar_el_disco(self, base):
        prep = storage.prepare_document(raw=photo_pdf(), original_name="x.pdf",
                                        control_number=CONTROL, file_kind="pdf")

        assert list(base.iterdir()) == []
        assert (prep.ext, prep.mime_type, prep.file_kind) == ("pdf", "application/pdf", "pdf")
        assert prep.data.startswith(b"%PDF") and len(prep.data) <= 2 * MB
        assert prep.original_name == "x.pdf"

    def test_preparar_valida_igual_que_guardar(self, base):
        with pytest.raises(StorageError) as exc:
            storage.prepare_document(raw=bilevel_noise_pdf(), original_name="x.pdf",
                                     control_number=CONTROL, file_kind="pdf")
        assert str(exc.value) == _msg_incomprimible(bilevel_noise_pdf())
        with pytest.raises(StorageError):
            storage.prepare_document(raw=small_pdf(), original_name="x.pdf",
                                     control_number="99-01", file_kind="pdf")

    def test_escribir_guarda_lo_preparado(self, base):
        prep = storage.prepare_document(raw=photo_pdf(), original_name="x.pdf",
                                        control_number=CONTROL, file_kind="pdf")

        meta = storage.write_document(prep, period_code=PERIOD, control_number=CONTROL,
                                      type_code="curp")

        assert meta == {
            "file_path": f"{PERIOD}/{CONTROL}/documents/{CONTROL}_CURP.pdf",
            "original_name": "x.pdf", "mime_type": "application/pdf",
            "size_bytes": len(prep.data),
        }
        assert (base / meta["file_path"]).read_bytes() == prep.data


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
    def test_reenviar_un_rechazado_lo_deja_pendiente_y_sin_dictamen_previo(
            self, proceso, base, db_session, make_head):
        """El reenvío vuelve a «Pendiente» (cuenta «por evaluar») y no arrastra
        nada del dictamen anterior: ni la nota ni QUIÉN lo rechazó (2026-10-09:
        `reviewed_by_id` se quedaba con el revisor viejo)."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        revisora = make_head()

        DocumentService.save(db_session, proc, "curp", raw=small_pdf(),
                             original_name="curp.pdf", content_type="application/pdf",
                             uploaded_by_id=student.id)
        assert DocumentService.review(db_session, proc.id, "curp", status="rejected",
                                      note="Ilegible", reviewer_id=revisora.id)
        rechazado = _doc_row(db_session, proc.id)
        assert (rechazado.review_status, rechazado.reviewed_by_id) == ("rejected", revisora.id)

        DocumentService.save(db_session, proc, "curp", raw=small_pdf(),
                             original_name="curp-bien.pdf", content_type="application/pdf",
                             uploaded_by_id=student.id)
        doc = _doc_row(db_session, proc.id)

        assert doc.review_status == "pending"
        assert doc.version == 2
        assert doc.review_note is None
        assert doc.reviewed_by_id is None

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

    def test_con_lo_ya_preparado_no_vuelve_a_comprimir(self, proceso, base, db_session,
                                                        monkeypatch):
        """m1: la ruta comprime FUERA de la transaccion y aqui solo se persiste."""
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        prep = storage.prepare_document(raw=photo_pdf(), original_name="c.pdf",
                                        control_number=student.control_number,
                                        file_kind="pdf")

        def _no(*a, **k):
            raise AssertionError("ya venia preparado: no se comprime otra vez")
        monkeypatch.setattr(pdf_compress, "compress_pdf", _no)

        doc = DocumentService.save(db_session, proc, "curp", raw=photo_pdf(),
                                   original_name="c.pdf", content_type="application/pdf",
                                   uploaded_by_id=student.id, prepared=prep)

        assert (base / doc.file_path).read_bytes() == prep.data
        assert doc.size_bytes == len(prep.data)
        assert doc.file_path.endswith(f"/{student.control_number}_CURP.pdf")

    def test_lo_preparado_para_otro_tipo_de_archivo_es_error(self, proceso, base,
                                                              db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        prep = storage.PreparedDocument(data=b"\xff\xd8", ext="jpg", mime_type="image/jpeg",
                                        original_name="a.jpg", file_kind="image")

        with pytest.raises(ValueError):
            DocumentService.save(db_session, proc, "curp", raw=b"\xff\xd8",
                                 original_name="a.jpg", content_type="image/jpeg",
                                 uploaded_by_id=student.id, prepared=prep)

        assert _doc_row(db_session, proc.id) is None
        assert _files(base) == []

    def test_incomprimible_no_deja_fila_ni_archivo(self, proceso, base, db_session):
        from itcj2.apps.titulatec.services.document_service import DocumentService
        proc, student = proceso()
        raw = bilevel_noise_pdf()

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

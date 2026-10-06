"""Rutas de archivos de documentos con el tope de 2 MB (brief 2026-09-28).

* Subida del alumno (`POST /student/documents/{type_code}`):
  - PDF grande comprimible -> 200, fila con el tamano COMPRIMIDO y nombre
    `{control}_CURP.pdf` en disco.
  - incomprimible -> `X-Tt-Error` (percent-codificado, como el resto de
    este archivo: `student.py::_hdr`) + el parcial del slot con el error, sin
    fila ni archivo. El status es el de HOY (200: `render_titulatec` sin
    `status_code`): htmx 2 no hace swap en un 4xx, y el error vive DENTRO del
    slot. El manejo de `StorageError` no cambia.
  - mas de `TITULATEC_MAX_PDF_UPLOAD_SIZE` -> el mismo error ANTES de leer el
    cuerpo (ni `UploadFile.read` ni `DocumentService.save`).
  - comprimir (`storage.prepare_document`) y guardar (`DocumentService.save`)
    corren en el threadpool: comprimir es CPU y no debe congelar el event loop
    del worker.
  - ronda 1 (m1): se comprime SIN transaccion abierta (la de lectura se cierra
    antes de leer el cuerpo), para no dejar la conexion «idle in transaction».
  - la ayuda de la casilla dice el tope y el maximo, con los numeros de la
    config.
* Descargas (`documents.py` y `appointments.py`): `Content-Disposition` con
  `{control}_{ETIQUETA}.{ext}`, tambien para un archivo con nombre viejo, y
  nunca `original_name`.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from itcj2.config import get_settings
from tests.fastapi.titulatec._pdf_samples import MB, bilevel_noise_pdf, photo_pdf

UPLOAD = "/titulatec/student/documents/curp"


def _mb_arriba(size: int) -> str:
    """Un decimal, redondeado hacia arriba, como `storage._mb1`."""
    return f"{math.ceil(size * 10 / MB) / 10:.1f}"


@pytest.fixture()
def esc(db_session, seed_phase_defs, seed_document_types, make_program, make_cohort,
        make_student, make_process, tmp_path, monkeypatch):
    """Alumno en la fase 1 (la de los documentos iniciales) y su proceso."""
    def _build(control=None):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
        seed_phase_defs()
        seed_document_types()
        student = make_student(control_number=control)
        proc = make_process(student, cohort=make_cohort(),
                            program=make_program("Ingenieria Ficticia A"), current_phase=1)
        return SimpleNamespace(student=student, process=proc, base=tmp_path,
                               control=student.control_number)
    return _build


def _doc(db, process_id, type_code="curp"):
    from itcj2.apps.titulatec.models import Document
    db.expire_all()
    return db.query(Document).filter_by(process_id=process_id, type_code=type_code).first()


def _files(root) -> list:
    return [p for p in root.rglob("*") if p.is_file()]


def _post(cli, raw, name="curp escaneada.pdf"):
    return cli.post(UPLOAD, files={"archivo": (name, raw, "application/pdf")})


class TestLogDeSubida:
    """Rendimiento 2026-10-06: una línea «documento subido» por subida, con lo
    que explica su latencia (tamaños, pasadas de compresión, tiempos) y nada
    del archivo (ni su nombre). En Loki se cruza por `request_id`."""

    LOGGER = "itcj2.apps.titulatec.pages.student"

    def _registros(self, caplog):
        return [r for r in caplog.records
                if r.name == self.LOGGER and r.getMessage() == "documento subido"]

    def test_subida_comprimida_deja_tamanos_pasadas_y_tiempos(self, esc, client_as, caplog):
        import logging

        e = esc()
        raw = photo_pdf()
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            assert _post(client_as(e.student), raw).status_code == 200

        (r,) = self._registros(caplog)
        assert (r.doc_type, r.bytes_in, r.outcome) == ("curp", len(raw), "ok")
        assert r.bytes_out <= 2 * MB and r.compress_passes >= 1
        assert r.prepare_ms >= 0 and r.save_ms >= 0
        assert "curp escaneada" not in str(vars(r)), "nunca el nombre del archivo"

    def test_subida_rechazada_dice_el_tipo_de_error(self, esc, client_as, caplog):
        import logging

        e = esc()
        raw = bilevel_noise_pdf()
        with caplog.at_level(logging.INFO, logger=self.LOGGER):
            _post(client_as(e.student), raw)

        (r,) = self._registros(caplog)
        assert (r.outcome, r.error_type, r.bytes_in) == ("error", "StorageError", len(raw))
        assert not hasattr(r, "bytes_out")


# ---------------------------------------------------------------------------
# Subida
# ---------------------------------------------------------------------------
class TestSubida:
    def test_pdf_grande_comprimible_se_guarda_comprimido(self, esc, client_as, db_session):
        e = esc()
        raw = photo_pdf()
        assert len(raw) > 2 * MB

        resp = _post(client_as(e.student), raw)

        assert resp.status_code == 200, resp.text[:300]
        assert "X-Tt-Error" not in resp.headers
        doc = _doc(db_session, e.process.id)
        stored = e.base / doc.file_path
        assert stored.name == f"{e.control}_CURP.pdf"
        assert doc.size_bytes == len(stored.read_bytes()) <= 2 * MB
        assert doc.original_name == "curp escaneada.pdf"
        assert 'id="slot-curp"' in resp.text

    def test_incomprimible_da_error_en_el_slot_y_no_guarda_nada(self, esc, client_as,
                                                                db_session):
        e = esc()
        raw = bilevel_noise_pdf()
        esperado = (f"Tu PDF pesa {_mb_arriba(len(raw))} MB y aun comprimido supera 2 MB; "
                    "escanéalo en menor resolución o en blanco y negro.")

        resp = _post(client_as(e.student), raw)

        assert resp.status_code == 200, resp.text[:300]
        assert unquote(resp.headers.get("X-Tt-Error", "")) == esperado
        assert "aun comprimido supera 2 MB" in resp.text   # el error, dentro del slot
        assert _doc(db_session, e.process.id) is None
        assert _files(e.base) == []

    def test_mas_del_maximo_se_rechaza_sin_leer_el_cuerpo(self, esc, client_as,
                                                          db_session, monkeypatch):
        from starlette.datastructures import UploadFile
        from itcj2.apps.titulatec.services.document_service import DocumentService

        e = esc()
        monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_UPLOAD_SIZE", 1 * MB)

        async def _no_leer(self, *a, **k):
            raise AssertionError("leyo el cuerpo de un archivo que ya excede el maximo")

        def _no_guardar(*a, **k):
            raise AssertionError("intento guardar un archivo que ya excede el maximo")

        monkeypatch.setattr(UploadFile, "read", _no_leer)
        monkeypatch.setattr(DocumentService, "save", staticmethod(_no_guardar))
        raw = photo_pdf()

        resp = _post(client_as(e.student), raw)

        assert resp.status_code == 200, resp.text[:300]
        assert unquote(resp.headers.get("X-Tt-Error", "")) == (
            f"Tu PDF pesa {_mb_arriba(len(raw))} MB; el máximo que aceptamos es 1 MB.")
        assert _doc(db_session, e.process.id) is None

    def test_comprimir_y_guardar_corren_en_el_threadpool(self, esc, client_as, db_session,
                                                         monkeypatch):
        """R7 (spec §3.8): la ruta async solo lee el archivo; comprimir (CPU) y
        guardar (BD) corren en un hilo del threadpool, nunca dentro del event loop.
        Un hilo del pool no tiene loop corriendo; el loop del worker, si."""
        import asyncio

        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.utils import storage

        def _hay_loop() -> bool:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return False
            return True

        e = esc()
        en_el_loop: dict[str, bool] = {}
        real_prepare, real_save = storage.prepare_document, DocumentService.save

        def _espia_prepare(**kwargs):
            en_el_loop["comprimir"] = _hay_loop()
            return real_prepare(**kwargs)

        def _espia_save(*args, **kwargs):
            en_el_loop["guardar"] = _hay_loop()
            return real_save(*args, **kwargs)

        monkeypatch.setattr(storage, "prepare_document", _espia_prepare)
        monkeypatch.setattr(DocumentService, "save", staticmethod(_espia_save))

        resp = _post(client_as(e.student), photo_pdf())

        assert resp.status_code == 200, resp.text[:300]
        assert en_el_loop == {"comprimir": False, "guardar": False}
        assert _doc(db_session, e.process.id) is not None

    def test_comprime_sin_transaccion_abierta(self, esc, client_as, db_session, monkeypatch):
        """m1: mientras se comprime, la sesion de la ruta no tiene transaccion
        (la conexion volvio al pool; en PgBouncer transaccional, ni un backend
        fijado). La fila se escribe despues, en una transaccion corta."""
        from itcj2.apps.titulatec.utils import storage

        e = esc()
        durante = []
        real = storage.prepare_document

        def _espia(**kwargs):
            durante.append(db_session.in_transaction())
            return real(**kwargs)

        monkeypatch.setattr(storage, "prepare_document", _espia)

        resp = _post(client_as(e.student), photo_pdf())

        assert resp.status_code == 200, resp.text[:300]
        assert "X-Tt-Error" not in resp.headers
        assert durante == [False], "comprimio con una transaccion abierta"
        doc = _doc(db_session, e.process.id)
        assert doc is not None and doc.size_bytes <= 2 * MB


class TestAyuda:
    TEXTO = "PDF de hasta 2 MB. Si pesa más (hasta 20 MB), lo comprimimos automáticamente."

    def test_la_casilla_dice_el_tope_y_el_maximo(self, esc, client_as):
        e = esc()

        resp = client_as(e.student).get("/titulatec/student/documents")

        assert resp.status_code == 200, resp.text[:300]
        assert self.TEXTO in resp.text

    def test_los_numeros_salen_de_la_config(self, esc, client_as, monkeypatch):
        e = esc()
        monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_SIZE", 3 * MB)
        monkeypatch.setattr(get_settings(), "TITULATEC_MAX_PDF_UPLOAD_SIZE", 25 * MB)

        resp = client_as(e.student).get("/titulatec/student/documents")

        assert "PDF de hasta 3 MB. Si pesa más (hasta 25 MB)" in resp.text
        assert "2 MB" not in resp.text

    def test_el_parcial_con_error_conserva_la_ayuda(self, esc, client_as):
        e = esc()

        resp = _post(client_as(e.student), bilevel_noise_pdf())

        assert self.TEXTO in resp.text

    def test_la_ayuda_usa_una_clase_y_no_estilo_en_linea(self, esc, client_as):
        """m9: convencion de TitulaTec, sin CSS inline; la clase vive en
        `titulatec.css`."""
        from pathlib import Path

        import itcj2.apps.titulatec as tt

        e = esc()

        resp = client_as(e.student).get("/titulatec/student/documents")

        assert f'<div class="tt-dropzone-hint">{self.TEXTO}</div>' in resp.text
        css = (Path(tt.__file__).parent / "static" / "css" / "titulatec.css").read_text(
            encoding="utf-8")
        assert ".tt-dropzone-hint" in css

    def test_el_acordeon_ya_no_promete_10mb(self):
        from itcj2.apps.titulatec.pages.student import _PHASE_INFO, _with_pdf_limits

        textos = [_with_pdf_limits(n) for info in _PHASE_INFO.values()
                  for n in info.get("needs", [])]
        assert not any("10 MB" in t for t in textos)
        assert any("PDF de hasta 2 MB" in t and "hasta 20 MB" in t for t in textos)
        assert not any("{pdf_" in t for t in textos)


# ---------------------------------------------------------------------------
# Descargas
# ---------------------------------------------------------------------------
@pytest.fixture()
def con_curp(esc, make_head, make_document):
    """CURP con el nombre VIEJO en disco (`.../curp.pdf`) y un `original_name`
    que no debe salir en la descarga."""
    def _build(control=None):
        e = esc(control=control)
        doc = make_document(e.process, type_code="curp", original_name="MI CURP (1).pdf")
        dest = e.base / doc.file_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 curp de prueba")
        assert dest.name == "curp.pdf"
        e.head = make_head()
        return e
    return _build


class TestDescargas:
    def test_documentos_descarga_con_control_y_etiqueta(self, con_curp, client_as):
        e = con_curp()
        url = f"/titulatec/admin/documents/{e.process.id}/document/curp"

        adjunto = client_as(e.head).get(url + "?download=1")
        en_linea = client_as(e.head).get(url)

        assert adjunto.status_code == 200, adjunto.text[:300]
        assert adjunto.headers["Content-Disposition"] == \
            f'attachment; filename="{e.control}_CURP.pdf"'
        assert en_linea.headers["Content-Disposition"] == \
            f'inline; filename="{e.control}_CURP.pdf"'
        assert "MI CURP" not in adjunto.headers["Content-Disposition"]

    def test_citas_sirve_con_control_y_etiqueta(self, con_curp, client_as):
        e = con_curp()

        resp = client_as(e.head).get(
            f"/titulatec/admin/appointments/{e.process.id}/document/curp")

        assert resp.status_code == 200, resp.text[:300]
        assert resp.headers["Content-Disposition"] == \
            f'inline; filename="{e.control}_CURP.pdf"'

    def test_control_invalido_cae_a_la_etiqueta(self, con_curp, client_as):
        e = con_curp(control="99-000901")

        resp = client_as(e.head).get(
            f"/titulatec/admin/documents/{e.process.id}/document/curp?download=1")

        assert resp.status_code == 200, resp.text[:300]
        assert resp.headers["Content-Disposition"] == 'attachment; filename="CURP.pdf"'

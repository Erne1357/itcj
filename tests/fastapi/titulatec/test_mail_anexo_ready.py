"""Correo `anexo_ready` (fase 6 v2, spec 2026-10-29 §9): encolado, composición, obsolescencia.

Casi todas las pruebas parchean `AnexoService.stage`; la última recorre la etapa REAL.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.models import EmailOutbox
from itcj2.apps.titulatec.services.anexo_service import SIGNERS_FALLBACK_TEXT, AnexoService
from itcj2.apps.titulatec.services.mail_compose import Composed, MailComposer, Obsolete
from itcj2.apps.titulatec.services.student_mail import StudentMail


@pytest.fixture(autouse=True)
def _correo_encendido(monkeypatch):
    from itcj2.config import get_settings

    monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)


@pytest.fixture()
def proceso(make_student, make_process):
    student = make_student()
    return student, make_process(student)


def _encolar(db, process, note="Ventanilla 2, de 9 a 11"):
    assert StudentMail.anexo_ready(db, process, folio="AN-2026-001", note=note) is True
    db.flush()
    return db.query(EmailOutbox).filter_by(process_id=process.id, kind="anexo_ready").one()


def _vigente(monkeypatch, etapa, nota):
    monkeypatch.setattr(AnexoService, "stage", staticmethod(lambda db, p: etapa))
    monkeypatch.setattr(AnexoService, "get",
                        staticmethod(lambda db, pid: SimpleNamespace(pickup_note=nota)))


def _html(composed) -> str:
    from itcj2.apps.titulatec.pages.nav import titulatec_templates

    return titulatec_templates.get_template(
        f"titulatec/email/{composed.template}").render(**composed.context)


def test_encola_fila_individual_sin_secretos(db_session, proceso):
    student, process = proceso
    fila = _encolar(db_session, process)
    assert fila.group_key is None and fila.user_id == student.id
    assert fila.payload == {"folio": "AN-2026-001", "note": "Ventanilla 2, de 9 a 11"}


def test_kind_registrado():
    assert "anexo_ready" in MailComposer.REGISTRY
    assert "anexo_ready" in StudentMail.KIND_LABELS


def test_compone_con_la_nota_vigente_no_la_del_payload(db_session, proceso, monkeypatch):
    student, process = proceso
    fila = _encolar(db_session, process, note="NOTA VIEJA")
    _vigente(monkeypatch, "ready", "Nota corregida: jueves 10:00")
    c = MailComposer.compose(db_session, [fila], process, student)
    assert isinstance(c, Composed)
    assert c.subject.endswith("Tu Anexo III está listo para recoger")
    assert c.link.endswith(
        "next=%2Ftitulatec%2Fstudent%2Fanexo")
    html = _html(c)
    assert "Nota corregida: jueves 10:00" in html and "NOTA VIEJA" not in html
    assert "AN-2026-001" in html and "Escanéalo" in html


@pytest.mark.parametrize("etapa", ["reprint", "in_review", "approved", "observed", None])
def test_obsoleto_si_la_etapa_no_es_ready(db_session, proceso, monkeypatch, etapa):
    student, process = proceso
    fila = _encolar(db_session, process)
    _vigente(monkeypatch, etapa, "x")
    assert isinstance(MailComposer.compose(db_session, [fila], process, student), Obsolete)


def test_firmantes_ilegibles_usan_el_texto_de_respaldo(db_session, proceso, monkeypatch):
    student, process = proceso
    fila = _encolar(db_session, process)
    _vigente(monkeypatch, "ready", "x")

    def _falla(p):
        raise ValueError("regla desconocida")

    monkeypatch.setattr(AnexoService, "signers_text", staticmethod(_falla))
    c = MailComposer.compose(db_session, [fila], process, student)
    assert c.context["signers_text"] == SIGNERS_FALLBACK_TEXT


def test_etapa_real_ready_y_luego_subida_del_escaneo_lo_vuelve_obsoleto(
        db_session, make_anexo_case, seed_document_types, tmp_path, monkeypatch):
    """Review Focus 3 sin stub: mark_ready real encola; la subida real pasa la
    etapa a in_review; el compositor real dice Obsolete."""
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    monkeypatch.setattr("itcj2.apps.titulatec.utils.storage._base", lambda: tmp_path)
    seed_document_types([("anexo_iii", "Anexo III firmado", 6)])
    c = make_anexo_case()

    AnexoService.mark_ready(db_session, c.process, c.coordinator.id, "Ventanilla 2")
    fila = (db_session.query(EmailOutbox)
            .filter_by(process_id=c.process.id, kind="anexo_ready").one())
    assert AnexoService.stage(db_session, c.process) == "ready"
    assert isinstance(MailComposer.compose(db_session, [fila], c.process, c.student), Composed)

    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    DocumentService.save(db_session, c.process, "anexo_iii", raw=pdf, original_name="a.pdf",
                         content_type="application/pdf", uploaded_by_id=c.student.id)
    assert AnexoService.stage(db_session, c.process) == "in_review"
    assert isinstance(MailComposer.compose(db_session, [fila], c.process, c.student), Obsolete)

"""Correo `anexo_ready` (fase 6 v2, spec 2026-10-29 §9): encolado, composición, obsolescencia.

`AnexoService.stage` y `Anexo.pickup_note` son de la Tarea 1: aquí se parchean
(`raising=False`) para no depender de su calendario.
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
    monkeypatch.setattr(AnexoService, "stage", staticmethod(lambda db, p: etapa), raising=False)
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

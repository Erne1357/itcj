"""Fase 6, tarea 2: `AnexoService` (operable, firmas, folio y PDF; spec fase 6 §7-§10)."""
import re
from datetime import datetime

import pytest

from itcj2.apps.titulatec.models import Anexo, ProcessEvent, ProcessPhase
from itcj2.apps.titulatec.services import anexo_service
from itcj2.apps.titulatec.services.anexo_service import AnexoService
from itcj2.apps.titulatec.services.phase_service import PhaseService


@pytest.fixture()
def corte_9(monkeypatch):
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))


def _eventos(db, pid):
    return db.query(ProcessEvent).filter_by(process_id=pid, event_type="anexo_iii_issued").count()


def test_required_signers_integral(corte_9, make_anexo_case):
    c = make_anexo_case("integral_residencias")
    assert AnexoService.required_signers(c.process) == ["department_head", "president"]


def test_required_signers_tesis(corte_9, make_anexo_case):
    c = make_anexo_case("thesis")
    assert AnexoService.required_signers(c.process) == [
        "department_head", "president", "secretary", "vocal", "alternate"]


def test_required_signers_regla_desconocida(corte_9, make_anexo_case):
    c = make_anexo_case()
    c.modality.signature_rule = "rara"
    with pytest.raises(ValueError):
        AnexoService.required_signers(c.process)


def test_signers_text(corte_9, make_anexo_case):
    assert "Presidente" in AnexoService.signers_text(make_anexo_case("integral_residencias").process)
    assert "4 sinodales" in AnexoService.signers_text(make_anexo_case("thesis").process)


def test_folio_formato(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    a = AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
    assert re.fullmatch(r"AIII-\d{4}[AB]-\d{4}", a.folio)
    assert a.issued_by_id == c.coordinator.id


def test_folio_estable(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    a1 = AnexoService.ensure_folio(db_session, c.process, c.coordinator.id)
    a2 = AnexoService.ensure_folio(db_session, c.process, c.student.id)
    assert a1.folio == a2.folio
    assert db_session.query(Anexo).filter_by(process_id=c.process.id).count() == 1
    assert _eventos(db_session, c.process.id) == 1


def test_folio_consecutivo(corte_9, db_session, make_anexo_case):
    a = AnexoService.ensure_folio(db_session, make_anexo_case().process, None)
    b = AnexoService.ensure_folio(db_session, make_anexo_case().process, None)
    assert int(b.folio[-4:]) == int(a.folio[-4:]) + 1
    assert a.folio[:-4] == b.folio[:-4]


def test_released_at_es_fin_de_fase5(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    a = AnexoService.ensure_folio(db_session, c.process, None)
    assert a.released_at == datetime(2026, 3, 17, 10, 0)


def test_released_at_respaldo_evento(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    fase = db_session.query(ProcessPhase).filter_by(
        process_id=c.process.id, phase_number=c.review_phase).one()
    fase.completed_at = None
    ev = ProcessEvent(process_id=c.process.id, actor_id=None, event_type="phase_approved",
                      phase_number=c.review_phase)
    db_session.add(ev)
    db_session.flush()
    a = AnexoService.ensure_folio(db_session, c.process, None)
    assert a.released_at == ev.created_at


def test_context(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    AnexoService.ensure_folio(db_session, c.process, None)
    ctx = AnexoService.context(db_session, c.process)
    assert [i["letter"] for i in ctx["items"]] == list("abcde")
    assert ctx["product_label"] == "Informe técnico de residencia profesional"
    assert ctx["items"][4]["value"] == ctx["product_label"]
    assert ctx["items"][3]["value"] == "SISTEMA DE REVISION DE PRUEBA"
    assert len(ctx["synodals"]) == 4
    assert ctx["synodals"][0]["role_label"].lower().startswith("presidente")
    assert all(s["name"] for s in ctx["synodals"])
    assert ctx["signer"]["name"].startswith("JEFE")
    assert ctx["folio"].startswith("AIII-")
    assert ctx["date_label"] == "17/Marzo/2026"
    assert "addressee" in ctx


def test_pdf_empieza_con_pdf(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    pdf = AnexoService.render_pdf(db_session, c.process, c.coordinator.id)
    assert pdf.startswith(b"%PDF")
    assert AnexoService.get(db_session, c.process.id) is not None
    assert AnexoService.filename(db_session, c.process).endswith("_ANEXO_III.pdf")


def test_falla_cerrado_sin_cuatro_sinodales(corte_9, db_session, make_anexo_case):
    from itcj2.apps.titulatec.models import SynodalAssignment
    c = make_anexo_case()
    fila = db_session.query(SynodalAssignment).filter_by(
        process_id=c.process.id, role="alternate", is_active=True).one()
    fila.is_active = False
    db_session.flush()
    with pytest.raises(ValueError, match="sinodales"):
        AnexoService.render_pdf(db_session, c.process, None)
    assert AnexoService.get(db_session, c.process.id) is None


def test_falla_cerrado_sin_depto(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    c.process.program_id = None
    db_session.flush()
    with pytest.raises(ValueError, match="departamento"):
        AnexoService.context(db_session, c.process)


def test_falla_cerrado_sin_modalidad(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    c.modality.product_label = None
    db_session.flush()
    with pytest.raises(ValueError, match="modalidad"):
        AnexoService.context(db_session, c.process)


def test_no_operable_con_corte_3(db_session, monkeypatch, make_anexo_case):
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 9))
    c = make_anexo_case()
    monkeypatch.setattr(PhaseService, "_handoff_phase", staticmethod(lambda: 3))
    assert AnexoService.operable(db_session) is False
    with pytest.raises(ValueError, match=anexo_service.NOT_OPERABLE_MSG[:15]):
        AnexoService.ensure_folio(db_session, c.process, None)
    assert AnexoService.get(db_session, c.process.id) is None
    assert _eventos(db_session, c.process.id) == 0


def test_reached(corte_9, db_session, make_anexo_case):
    c = make_anexo_case()
    assert AnexoService.reached(db_session, c.process) is True
    c.process.current_phase = c.review_phase
    assert AnexoService.reached(db_session, c.process) is False
    c.process.current_phase = c.anexo_phase
    fase = db_session.query(ProcessPhase).filter_by(
        process_id=c.process.id, phase_number=c.anexo_phase).one()
    fase.status = "skipped"
    db_session.flush()
    assert AnexoService.reached(db_session, c.process) is False
    fase.status = "in_progress"
    c.process.status = "cancelled"
    assert AnexoService.reached(db_session, c.process) is False

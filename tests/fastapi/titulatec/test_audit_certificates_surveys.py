"""Bitácora de folios, no adeudos previos y encuestas (Tarea 7 del plan de la
bitácora): acciones explícitas `certificate.*`, `prior_clearance.*`, `survey.*`.

Se afirma sobre filas `source='action'` (la red ORM escribe además filas
`source='data'` en el mismo flush) y siempre filtradas por lo que la prueba
sembró: la BD de dev es compartida.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import func

import itcj2.models  # noqa: F401
from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog
from itcj2.apps.titulatec.services.certificate_service import CertificateService
from itcj2.apps.titulatec.services.folio_backfill_service import FolioBackfillService
from itcj2.apps.titulatec.services.prior_clearance_service import PriorClearanceService
from itcj2.apps.titulatec.services.survey_import_service import SurveyImportService
from itcj2.apps.titulatec.services.survey_service import SurveyService

_n = [0]


def _ref() -> str:
    _n[0] += 1
    return f"tt_audit7:{_n[0]}:{id(_n)}"


def _acciones(db, action, **filtros):
    db.flush()
    return (db.query(TitulatecAuditLog)
            .filter_by(source="action", action=action, **filtros)
            .order_by(TitulatecAuditLog.id).all())


@pytest.fixture()
def proc(db_session, make_student, make_process, make_cohort):
    return make_process(make_student(), cohort=make_cohort(), current_phase=2,
                        library_clearance=None)


@pytest.fixture()
def actor(make_user):
    return make_user(first_name="EMISOR", last_name="AUDIT")


# ---------------------------------------------------------------- folios
def test_issue_registra_certificate_issued(db_session, proc, actor):
    cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                    source_ref=_ref(), actor_id=actor.id)
    (fila,) = _acciones(db_session, "certificate.issued", entity_id=str(cert.id))
    assert fila.process_id == proc.id
    assert fila.actor_id == actor.id
    assert fila.payload["folio"] == cert.number
    assert fila.payload["kind"] == "library_clearance"


def test_issue_sin_actor_registra_la_fila(db_session, proc):
    cert = CertificateService.issue(db_session, kind="survey_release", process=proc,
                                    source_ref=_ref(), actor_id=None)
    (fila,) = _acciones(db_session, "certificate.issued", entity_id=str(cert.id))
    assert fila.payload["folio"] == cert.number


def test_void_registra_certificate_voided_con_motivo(db_session, proc, actor):
    ref = _ref()
    cert = CertificateService.issue(db_session, kind="library_clearance", process=proc,
                                    source_ref=ref, actor_id=actor.id)
    CertificateService.void(db_session, source_ref=ref, actor_id=actor.id,
                            reason="Se revirtió")
    (fila,) = _acciones(db_session, "certificate.voided", entity_id=str(cert.id))
    assert fila.reason == "Se revirtió"
    assert fila.payload["folio"] == cert.number


def test_void_sin_vigente_no_registra(db_session):
    antes = len(_acciones(db_session, "certificate.voided"))
    assert CertificateService.void(db_session, source_ref=_ref(), actor_id=None,
                                   reason=None) is None
    assert len(_acciones(db_session, "certificate.voided")) == antes


def test_create_batch_registra_conteo_y_folios(db_session, proc, actor):
    CertificateService.issue(db_session, kind="library_clearance", process=proc,
                             source_ref=_ref(), actor_id=actor.id)
    batch = CertificateService.create_batch(db_session, kind="library_clearance",
                                            actor_id=actor.id)
    (fila,) = _acciones(db_session, "certificate.batch_created",
                        entity_id=str(batch.id))
    assert fila.payload["count"] == batch.count >= 1
    assert fila.payload["kind"] == "library_clearance"
    assert fila.payload["first_folio"] and fila.payload["last_folio"]
    assert fila.actor_id == actor.id
    assert fila.payload["first_folio"] <= fila.payload["last_folio"]


def test_backfill_registra_resumen_y_el_folio_via_issue(db_session, proc, monkeypatch,
                                                        make_library_clearance):
    make_library_clearance(proc, status="cleared")
    orig = FolioBackfillService.candidates
    monkeypatch.setattr(
        FolioBackfillService, "candidates",
        staticmethod(lambda db, **kw: [c for c in orig(db, **kw)
                                       if c["process_id"] == proc.id]))
    conteo = FolioBackfillService.run(db_session, dry_run=False)
    assert sum(conteo.values()) == 1
    resumen = _acciones(db_session, "certificate.backfill_run")
    assert any(f.payload.get("total") == 1 for f in resumen)
    emitidas = _acciones(db_session, "certificate.issued", process_id=proc.id)
    assert len(emitidas) == 1 and emitidas[0].actor_id is None


def test_backfill_dry_run_no_registra(db_session, proc, make_library_clearance):
    make_library_clearance(proc, status="cleared")
    antes = len(_acciones(db_session, "certificate.backfill_run"))
    FolioBackfillService.run(db_session, dry_run=True)
    assert len(_acciones(db_session, "certificate.backfill_run")) == antes


# ------------------------------------------------------- previas (no adeudo)
HOY = date(2026, 10, 1)
_OPEN = ("itcj2.apps.titulatec.services.prior_clearance_service."
         "_open_process_for_control")


def test_import_rows_difiere_y_registra(db_session):
    control = "99790001"
    with patch(_OPEN, return_value=None):
        res = PriorClearanceService.import_rows(
            db_session, kind="library", rows=[{"control_number": control,
                                               "issued_on": HOY.isoformat()}],
            source="audit7.csv", today=HOY)
    assert [f["control_number"] for f in res["deferred"]] == [control]
    (dif,) = _acciones(db_session, "prior_clearance.deferred", subject_label=control)
    assert dif.after["source"] == "audit7.csv"
    assert dif.entity_id is not None
    runs = [f for f in _acciones(db_session, "prior_clearance.import_run")
            if f.payload.get("source") == "audit7.csv"]
    assert len(runs) == 1 and runs[0].payload["counts"]["deferred"] == 1


def test_import_rows_dry_run_no_registra(db_session):
    with patch(_OPEN, return_value=None):
        PriorClearanceService.import_rows(
            db_session, kind="library", rows=[{"control_number": "99790002",
                                               "issued_on": HOY.isoformat()}],
            source="audit7-dry.csv", dry_run=True, today=HOY)
    assert _acciones(db_session, "prior_clearance.deferred", subject_label="99790002") == []
    assert [f for f in _acciones(db_session, "prior_clearance.import_run")
            if f.payload.get("source") == "audit7-dry.csv"] == []


def test_reemplazo_de_una_aplicada_registra_before_after(db_session, proc):
    from itcj2.apps.titulatec.models import PriorClearance
    control = "99790003"
    db_session.add(PriorClearance(
        kind="library", control_number=control,
        issued_on=HOY - timedelta(days=100), note="vieja", source="old.csv",
        applied_process_id=proc.id, applied_at=datetime(2026, 1, 1)))
    db_session.flush()
    res = PriorClearanceService._defer(
        db_session, kind="library", control=control, issued_on=HOY - timedelta(days=1),
        note="nueva", source="new.csv", dry_run=False)
    assert res == "replaced"
    (fila,) = _acciones(db_session, "prior_clearance.replaced", subject_label=control)
    assert fila.before["source"] == "old.csv" and fila.after["source"] == "new.csv"
    assert fila.before["note"] == "vieja" and fila.after["note"] == "nueva"
    assert fila.before["applied_process_id"] == proc.id
    assert _acciones(db_session, "prior_clearance.deferred", subject_label=control) == []


# ------------------------------------------------------------ encuestas
def test_submit_registra_survey_submitted_sin_respuestas(db_session, make_survey_form):
    schema = {"enabled": True, "fields": [
        {"key": "comentario", "type": "textarea", "label": "Comentarios"}]}
    form = make_survey_form(code="tt_audit7", schema=schema)
    secreto = "RESPUESTA-SECRETA-XYZ"
    db_session.flush()
    ultimo = db_session.query(func.coalesce(func.max(TitulatecAuditLog.id), 0)).scalar()
    response, errors, _credit = SurveyService.submit(
        db_session, form, {"comentario": secreto}, user_id=None,
        client_ip="10.0.0.1", user_agent="pytest")
    assert errors == {} and response is not None
    (fila,) = _acciones(db_session, "survey.submitted", entity_id=str(response.id))
    assert fila.payload["credit_status"] == "anonymous"
    assert secreto not in json.dumps(
        [fila.payload, fila.before, fila.after, fila.reason, fila.subject_label], default=str)
    # Ninguna fila de la bitácora, de ningún origen, copia el contenido.
    todas = db_session.query(TitulatecAuditLog).filter(
        TitulatecAuditLog.id > ultimo).all()
    assert all(secreto not in json.dumps(
        [f.payload, f.before, f.after, f.reason, f.subject_label], default=str)
        for f in todas)
    assert not [f for f in todas if f.source == "data" and f.entity_type and
                f.entity_type.startswith("titulatec_survey_")]


def test_submit_invalido_no_registra(db_session, make_survey_form):
    schema = {"enabled": True, "fields": [
        {"key": "x", "type": "text", "label": "X", "required": True}]}
    form = make_survey_form(code="tt_audit7b", schema=schema)
    antes = len(_acciones(db_session, "survey.submitted"))
    _, errors, _ = SurveyService.submit(db_session, form, {}, user_id=None,
                                        client_ip=None, user_agent=None)
    assert errors
    assert len(_acciones(db_session, "survey.submitted")) == antes


def test_import_xlsx_registra_survey_import_run(db_session, make_survey_form):
    make_survey_form(code="egresados")
    out = SurveyImportService.import_rows(db_session, [], source="audit7.xlsx")
    assert all(v == [] for v in out.values())
    filas = [f for f in _acciones(db_session, "survey.import_run")
             if f.payload.get("file") == "audit7.xlsx"]
    assert len(filas) == 1 and filas[0].payload["rows"] == 0


def test_import_xlsx_dry_run_no_registra(db_session, make_survey_form):
    make_survey_form(code="egresados")
    SurveyImportService.import_rows(db_session, [], source="audit7-dry.xlsx", dry_run=True)
    assert [f for f in _acciones(db_session, "survey.import_run")
            if f.payload.get("file") == "audit7-dry.xlsx"] == []

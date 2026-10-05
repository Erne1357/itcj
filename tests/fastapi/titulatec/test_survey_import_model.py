"""Tarea 1 de la importación de la encuesta de egresados desde el Excel de
Microsoft Forms (spec `2026-10-05-titulatec-import-encuesta-xlsx-design.md`
§4.1/§4.3, D1/D3, R6/R7/R8).

Cubre el MODELO (columnas nuevas, índice único parcial de `import_ref`, el
evento nuevo) y los SERVICIOS DUEÑOS:

* `SurveyReviewService.register_prior(..., response_id=, paper_pending=)` liga
  la respuesta importada y marca la constancia por recoger;
* `SurveyReviewService.revoke` de una previa con respuesta borra la solicitud
  (Ruling R22) pero NUNCA la respuesta (R8);
* `SurveyReviewService.mark_paper_delivered` (D3);
* `PriorClearanceService` guarda `response_id`/`paper_pending` en la diferida
  y `apply_pending` los transmite (R7).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

import itcj2.models  # noqa: F401

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"
HOY_FIJO = datetime(2026, 10, 1, 10, 0, 0)

_MODULOS_RELOJ = (
    "itcj2.apps.titulatec.services.library_clearance_service",
    "itcj2.apps.titulatec.services.survey_review_service",
    "itcj2.apps.titulatec.services.prior_clearance_service",
)


def _version() -> int:
    """Versión única por llamada: `make_survey_form` purga una fila con el
    mismo `(code, version)`, y dos respuestas del mismo test no deben
    pisarse."""
    return 100000 + uuid.uuid4().int % 800000


def _review_svc():
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    return SurveyReviewService


def _prior_svc():
    from itcj2.apps.titulatec.services.prior_clearance_service import PriorClearanceService
    return PriorClearanceService


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


@pytest.fixture()
def reloj(monkeypatch):
    for modulo in _MODULOS_RELOJ:
        monkeypatch.setattr(f"{modulo}.db_now", lambda: HOY_FIJO)
    return HOY_FIJO.date()


@pytest.fixture()
def proceso(make_student, make_process, make_cohort):
    def _make(*, control_number=None, current_phase=1):
        student = make_student(control_number=control_number)
        return make_process(student, cohort=make_cohort(), current_phase=current_phase)
    return _make


@pytest.fixture()
def respuesta_importada(db_session, make_survey_form):
    """`SurveyResponse` con `identity_source='import'` (sin usuario: el
    egresado puede no tener cuenta todavía)."""
    from itcj2.apps.titulatec.models import SurveyResponse

    def _make(*, control_number=None, import_ref=None, form=None):
        form = form or make_survey_form(version=_version(), status="closed")
        row = SurveyResponse(
            form_id=form.id, form_version=form.version, identity_source="import",
            control_number=control_number, answers={"nombre_completo": "SINTÉTICO"},
            import_ref=import_ref or f"msforms:prueba.xlsx:{uuid.uuid4().hex[:8]}",
            submitted_at=HOY_FIJO,
        )
        db_session.add(row)
        db_session.flush()
        return row
    return _make


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
class TestModelo:
    def test_evento_nuevo_en_el_dominio(self):
        from itcj2.apps.titulatec.models.process_event import EVENT_TYPES
        assert "survey_paper_delivered" in EVENT_TYPES

    def test_import_ref_es_unico_por_formulario(
            self, db_session, make_survey_form, respuesta_importada):
        form = make_survey_form(version=_version(), status="closed")
        respuesta_importada(form=form, import_ref="msforms:a.xlsx:1")
        with pytest.raises(IntegrityError):
            with db_session.begin_nested():
                respuesta_importada(form=form, import_ref="msforms:a.xlsx:1")

    def test_import_ref_igual_en_otro_formulario_si_se_permite(
            self, db_session, make_survey_form, respuesta_importada):
        f1 = make_survey_form(version=_version(), status="closed")
        f2 = make_survey_form(version=_version(), status="closed")
        a = respuesta_importada(form=f1, import_ref="msforms:a.xlsx:2")
        b = respuesta_importada(form=f2, import_ref="msforms:a.xlsx:2")
        assert a.id != b.id

    def test_import_ref_null_no_choca(self, db_session, make_survey_form):
        """Índice PARCIAL: las respuestas de la plataforma (sin `import_ref`)
        nunca colisionan entre sí."""
        from itcj2.apps.titulatec.models import SurveyResponse

        form = make_survey_form(version=_version(), status="closed")
        for _ in range(2):
            db_session.add(SurveyResponse(form_id=form.id, form_version=form.version,
                                          identity_source="anonymous", answers={}))
        db_session.flush()

    def test_defaults_de_las_columnas_nuevas(
            self, db_session, respuesta_importada, make_survey_review, proceso):
        from itcj2.apps.titulatec.models import PriorClearance, SurveyAnswer

        resp = respuesta_importada()
        ans = SurveyAnswer(response_id=resp.id, field_key="sexo", field_type="radio",
                           value_text="Otro")
        prior = PriorClearance(kind="survey", control_number="99700001",
                               issued_on=HOY_FIJO.date(), source="t")
        db_session.add_all([ans, prior])
        db_session.flush()
        review = make_survey_review(proceso(), status="in_review")
        db_session.refresh(ans)
        db_session.refresh(prior)
        db_session.refresh(review)

        assert ans.is_raw is False
        assert prior.paper_pending is False
        assert prior.response_id is None
        assert review.paper_pending is False
        assert review.paper_delivered_at is None
        assert review.paper_delivered_by_id is None

    def test_borrar_la_respuesta_deja_la_diferida_sin_liga(
            self, db_session, respuesta_importada):
        """`PriorClearance.response_id` es `ON DELETE SET NULL`: el purgado de
        respuestas (fixture `make_survey_form`) no revienta por esta FK."""
        from itcj2.apps.titulatec.models import PriorClearance, SurveyResponse

        resp = respuesta_importada()
        prior = PriorClearance(kind="survey", control_number="99700002",
                               issued_on=HOY_FIJO.date(), source="t",
                               response_id=resp.id, paper_pending=True)
        db_session.add(prior)
        db_session.flush()
        db_session.query(SurveyResponse).filter_by(id=resp.id).delete(
            synchronize_session=False)
        db_session.flush()
        db_session.refresh(prior)
        assert prior.response_id is None


# ---------------------------------------------------------------------------
# register_prior con respuesta/papel
# ---------------------------------------------------------------------------
class TestRegisterPrior:
    def test_liga_la_respuesta_y_marca_el_papel(
            self, db_session, reloj, proceso, respuesta_importada):
        proc = proceso()
        resp = respuesta_importada()
        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10),
                response_id=resp.id, paper_pending=True)

        assert review.origin == "prior"
        assert review.status == "approved"
        assert review.response_id == resp.id
        assert review.paper_pending is True
        assert review.paper_delivered_at is None
        evento = _events(db_session, proc.id, "survey_review_prior")[-1]
        assert evento.payload["response_id"] == resp.id
        assert evento.payload["paper_pending"] is True

    def test_sin_argumentos_nuevos_queda_como_siempre(self, db_session, reloj, proceso):
        proc = proceso()
        with patch(NOTIFY):
            review = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10))
        assert review.response_id is None
        assert review.paper_pending is False


# ---------------------------------------------------------------------------
# revoke de una previa con respuesta (R8)
# ---------------------------------------------------------------------------
def test_revocar_previa_con_respuesta_conserva_la_respuesta(
        db_session, reloj, proceso, respuesta_importada, make_user):
    from itcj2.apps.titulatec.models import SurveyResponse

    proc = proceso()
    gtv = make_user(first_name="GTV", last_name="PRUEBA")
    resp = respuesta_importada()
    with patch(NOTIFY):
        previa = _review_svc().register_prior(
            db_session, proc, issued_on=reloj - timedelta(days=10),
            response_id=resp.id, paper_pending=True)
        db_session.flush()
        assert _review_svc().revoke(db_session, previa.id, gtv.id, "Control equivocado") is None

    assert _review_svc().get_for_process(db_session, proc.id) is None
    assert db_session.get(SurveyResponse, resp.id) is not None


# ---------------------------------------------------------------------------
# mark_paper_delivered (D3)
# ---------------------------------------------------------------------------
class TestMarkPaperDelivered:
    def test_feliz(self, db_session, reloj, proceso, respuesta_importada, make_user):
        proc = proceso()
        gtv = make_user(first_name="GTV", last_name="PRUEBA")
        with patch(NOTIFY):
            previa = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10),
                response_id=respuesta_importada().id, paper_pending=True)
        db_session.flush()

        review = _review_svc().mark_paper_delivered(db_session, previa.id, actor_id=gtv.id)

        assert review.paper_pending is True          # el hecho histórico se conserva
        assert review.paper_delivered_at is not None
        assert review.paper_delivered_by_id == gtv.id
        eventos = _events(db_session, proc.id, "survey_paper_delivered")
        assert len(eventos) == 1
        assert eventos[0].actor_id == gtv.id
        assert eventos[0].payload == {"review_id": previa.id}

    def test_sin_papel_pendiente(self, db_session, reloj, proceso, make_user):
        proc = proceso()
        gtv = make_user()
        with patch(NOTIFY):
            previa = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10))
        db_session.flush()
        with pytest.raises(ValueError):
            _review_svc().mark_paper_delivered(db_session, previa.id, actor_id=gtv.id)
        assert _events(db_session, proc.id, "survey_paper_delivered") == []

    def test_ya_entregada(self, db_session, reloj, proceso, make_user):
        proc = proceso()
        gtv = make_user()
        with patch(NOTIFY):
            previa = _review_svc().register_prior(
                db_session, proc, issued_on=reloj - timedelta(days=10),
                paper_pending=True)
        db_session.flush()
        _review_svc().mark_paper_delivered(db_session, previa.id, actor_id=gtv.id)
        with pytest.raises(ValueError):
            _review_svc().mark_paper_delivered(db_session, previa.id, actor_id=gtv.id)
        assert len(_events(db_session, proc.id, "survey_paper_delivered")) == 1

    def test_no_existe(self, db_session, make_user):
        with pytest.raises(LookupError):
            _review_svc().mark_paper_delivered(db_session, -1, actor_id=make_user().id)


# ---------------------------------------------------------------------------
# PriorClearanceService: diferida con respuesta/papel (R7)
# ---------------------------------------------------------------------------
class TestPriorClearanceConRespuesta:
    def test_aplicacion_inmediata_pasa_respuesta_y_papel(
            self, db_session, reloj, proceso, respuesta_importada):
        proc = proceso(control_number="99700010")
        resp = respuesta_importada(control_number="99700010")
        with patch(NOTIFY):
            out = _prior_svc().import_rows(
                db_session, kind="survey", source="x.xlsx", rows=[{
                    "control_number": "99700010", "issued_on": reloj,
                    "response_id": resp.id, "paper_pending": True}])
        assert [r["control_number"] for r in out["applied"]] == ["99700010"]
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review.response_id == resp.id
        assert review.paper_pending is True

    def test_diferida_guarda_y_apply_pending_transmite(
            self, db_session, reloj, proceso, respuesta_importada):
        from itcj2.apps.titulatec.models import PriorClearance

        resp = respuesta_importada(control_number="99700011")
        out = _prior_svc().import_rows(
            db_session, kind="survey", source="x.xlsx", rows=[{
                "control_number": "99700011", "issued_on": reloj - timedelta(days=3),
                "response_id": resp.id, "paper_pending": True}])
        assert [r["control_number"] for r in out["deferred"]] == ["99700011"]
        previa = (db_session.query(PriorClearance)
                  .filter_by(kind="survey", control_number="99700011").one())
        assert previa.response_id == resp.id
        assert previa.paper_pending is True

        proc = proceso(control_number="99700011")
        with patch(NOTIFY):
            aplicadas = _prior_svc().apply_pending(db_session, proc, "99700011")
        assert aplicadas == ["survey"]
        review = _review_svc().get_for_process(db_session, proc.id)
        assert review.response_id == resp.id
        assert review.paper_pending is True

    def test_fila_sin_las_llaves_no_borra_la_liga_de_una_pendiente(
            self, db_session, reloj, respuesta_importada):
        """Un CSV de `import-prior-clearances` (sin `response_id`/
        `paper_pending`) sobre una diferida que vino del Excel solo actualiza
        fecha/nota/origen: no le quita la respuesta ni el papel."""
        from itcj2.apps.titulatec.models import PriorClearance

        resp = respuesta_importada(control_number="99700012")
        _prior_svc().import_rows(
            db_session, kind="survey", source="x.xlsx", rows=[{
                "control_number": "99700012", "issued_on": reloj - timedelta(days=3),
                "response_id": resp.id, "paper_pending": True}])
        _prior_svc().import_rows(
            db_session, kind="survey", source="y.csv", rows=[{
                "control_number": "99700012", "issued_on": reloj - timedelta(days=1)}])
        previa = (db_session.query(PriorClearance)
                  .filter_by(kind="survey", control_number="99700012").one())
        assert previa.source == "y.csv"
        assert previa.response_id == resp.id
        assert previa.paper_pending is True

    def test_reemplazo_de_una_aplicada_toma_la_liga_nueva(
            self, db_session, reloj, proceso, respuesta_importada):
        """Ruling R28: una más nueva reemplaza a la ya aplicada; la liga y el
        papel son los de la NUEVA (sin llaves -> sin respuesta ni papel)."""
        from itcj2.apps.titulatec.models import PriorClearance

        viejo = proceso(control_number="99700013")
        resp = respuesta_importada(control_number="99700013")
        previa = PriorClearance(kind="survey", control_number="99700013",
                                issued_on=reloj - timedelta(days=200), source="old",
                                response_id=resp.id, paper_pending=True,
                                applied_process_id=viejo.id, applied_at=HOY_FIJO)
        db_session.add(previa)
        db_session.flush()
        # `viejo` sigue abierto: se cierra para que la fila se difiera.
        viejo.status = "cancelled"
        db_session.flush()

        out = _prior_svc().import_rows(
            db_session, kind="survey", source="new.csv", rows=[{
                "control_number": "99700013", "issued_on": reloj - timedelta(days=5)}])
        assert [r["control_number"] for r in out["deferred"]] == ["99700013"]
        db_session.refresh(previa)
        assert previa.applied_process_id is None
        assert previa.response_id is None
        assert previa.paper_pending is False

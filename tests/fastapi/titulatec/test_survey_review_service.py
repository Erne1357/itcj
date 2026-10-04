"""Tests de `SurveyReviewService`: el único dueño de las transiciones de
`titulatec_survey_reviews` (liberación GTV de la encuesta de egresados).

Espejo de `test_requirement_service.py` en estilo: helpers `_req`/`_events`
locales, `escenario` con proceso en fase 2, y `notify_student` siempre
parcheado en los caminos que sí lo alcanzan (los que fallan antes de llegar
a notificar no necesitan el parche).
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.survey_review_service import (
    REASON_MAX, REVIEW_STATUSES, SurveyReviewService,
)

AUTO_SURVEY = "graduate_survey"
NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"


def _req(db, cohort, *, label="Requisito de prueba", icon="check2-square",
         hint=None, code=None, auto_source=None, is_required=True,
         is_active=True, order_index=0):
    """Un `CotejoRequirement` escrito a mano (copia de `test_requirement_service.py`)."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(
        cohort_id=cohort.id, label=label, icon=icon, hint=hint, code=code,
        auto_source=auto_source, is_required=is_required, is_active=is_active,
        order_index=order_index,
    )
    db.add(row)
    db.flush()
    return row


def _events(db, process_id, tipo):
    from itcj2.apps.titulatec.models import ProcessEvent
    return (db.query(ProcessEvent)
            .filter_by(process_id=process_id, event_type=tipo)
            .order_by(ProcessEvent.id).all())


def _fulfillment(db, process_id, requirement_id):
    from itcj2.apps.titulatec.models import RequirementFulfillment
    return (db.query(RequirementFulfillment)
            .filter_by(process_id=process_id, requirement_id=requirement_id).first())


def _survey_response(db, process, form):
    """`SurveyResponse` mínima para probar `open_for_submission` directo (sin fixture)."""
    from itcj2.apps.titulatec.models import SurveyResponse
    row = SurveyResponse(
        form_id=form.id, form_version=form.version, user_id=process.student_id,
        process_id=process.id, cohort_id=process.cohort_id,
        identity_source="session", answers={},
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def escenario(db_session, make_student, make_process, make_cohort, make_user):
    """Convocatoria + proceso en fase 2 (cita de cotejo) + una persona de GTV."""
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort, current_phase=2)
    gtv = make_user(first_name="GTV", last_name="DE PRUEBA")
    return {"cohort": cohort, "process": process, "gtv": gtv}


def test_constantes_publicas():
    assert REVIEW_STATUSES == ("in_review", "approved", "rejected")
    assert REASON_MAX == 1000


# ---------------------------------------------------------------------------
# open_for_submission
# ---------------------------------------------------------------------------
class TestOpenForSubmission:
    def test_crea_la_solicitud_en_revision(self, db_session, escenario, make_survey_form):
        process = escenario["process"]
        response = _survey_response(db_session, process, make_survey_form())

        review = SurveyReviewService.open_for_submission(
            db_session, process, response, commit=False)

        assert review.id is not None
        assert review.process_id == process.id
        assert review.response_id == response.id
        assert review.status == "in_review"
        assert review.reviewed_by_id is None
        assert review.reviewed_at is None
        assert len(_events(db_session, process.id, "survey_review_submitted")) == 1

    def test_apertura_unica_por_proceso(self, db_session, escenario, make_survey_form):
        process = escenario["process"]
        form = make_survey_form()
        primera = _survey_response(db_session, process, form)
        SurveyReviewService.open_for_submission(db_session, process, primera, commit=False)

        segunda = _survey_response(db_session, process, form)
        with pytest.raises(ValueError):
            SurveyReviewService.open_for_submission(db_session, process, segunda, commit=False)

        # sigue habiendo UNA sola solicitud para el proceso
        assert len(_events(db_session, process.id, "survey_review_submitted")) == 1


# ---------------------------------------------------------------------------
# approve (Liberar)
# ---------------------------------------------------------------------------
class TestApprove:
    def test_libera_desde_in_review_y_acredita_el_requisito(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review", reason=None)

        with patch(NOTIFY) as mock_notify:
            resultado = SurveyReviewService.approve(db_session, review.id, gtv.id)

        assert resultado.status == "approved"
        assert resultado.rejection_reason is None
        assert resultado.reviewed_by_id == gtv.id
        assert resultado.reviewed_at is not None

        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        req = next(r for r in CotejoRequirementService.list(db_session, process.cohort_id)
                   if r.auto_source == AUTO_SURVEY)
        cumplimiento = _fulfillment(db_session, process.id, req.id)
        assert cumplimiento is not None
        assert cumplimiento.external_ref == f"survey_review:{review.id}"

        assert len(_events(db_session, process.id, "survey_review_approved")) == 1
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["type"] == "SURVEY_REVIEW_APPROVED"
        assert mock_notify.call_args.kwargs["phase_number"] == 2

    def test_libera_desde_rejected_y_limpia_el_motivo(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="rejected",
                                    reason="Debe Servicio Social", reviewer=gtv)

        with patch(NOTIFY):
            resultado = SurveyReviewService.approve(db_session, review.id, gtv.id)

        assert resultado.status == "approved"
        assert resultado.rejection_reason is None
        assert len(_events(db_session, process.id, "survey_review_approved")) == 1

    def test_no_se_puede_liberar_lo_ya_liberado(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="approved", reviewer=gtv)

        with pytest.raises(ValueError):
            SurveyReviewService.approve(db_session, review.id, gtv.id)

        assert review.status == "approved"   # el ValueError no mutó nada

    def test_sin_requisito_configurado_en_la_convocatoria(
            self, db_session, escenario, make_survey_review):
        process, gtv, cohort = escenario["process"], escenario["gtv"], escenario["cohort"]
        _req(db_session, cohort, label="Actas", auto_source=None)  # bloquea el auto-seed
        review = make_survey_review(process, status="in_review")

        with pytest.raises(ValueError):
            SurveyReviewService.approve(db_session, review.id, gtv.id)

        assert review.status == "in_review"

    def test_proceso_no_activo(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        process.status = "completed"
        db_session.flush()
        review = make_survey_review(process, status="in_review")

        with pytest.raises(ValueError):
            SurveyReviewService.approve(db_session, review.id, gtv.id)

    def test_id_inexistente(self, db_session, escenario):
        with pytest.raises(LookupError):
            SurveyReviewService.approve(db_session, 9_999_999, escenario["gtv"].id)


# ---------------------------------------------------------------------------
# reject (Observar)
# ---------------------------------------------------------------------------
class TestReject:
    def test_observa_desde_in_review(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with patch(NOTIFY) as mock_notify:
            resultado = SurveyReviewService.reject(
                db_session, review.id, gtv.id, "  Debe Servicio Social  ")

        assert resultado.status == "rejected"
        assert resultado.rejection_reason == "Debe Servicio Social"
        assert resultado.reviewed_by_id == gtv.id
        assert resultado.reviewed_at is not None
        assert len(_events(db_session, process.id, "survey_review_rejected")) == 1
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["type"] == "SURVEY_REVIEW_REJECTED"
        assert mock_notify.call_args.kwargs["body"] == "Debe Servicio Social"

    def test_actualiza_el_texto_desde_rejected(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="rejected",
                                    reason="Motivo viejo", reviewer=gtv)

        with patch(NOTIFY):
            resultado = SurveyReviewService.reject(db_session, review.id, gtv.id, "Motivo nuevo")

        assert resultado.status == "rejected"
        assert resultado.rejection_reason == "Motivo nuevo"
        assert len(_events(db_session, process.id, "survey_review_rejected")) == 1

    @pytest.mark.parametrize("motivo", ["", "   ", "x" * (REASON_MAX + 1)])
    def test_motivo_invalido(self, db_session, escenario, make_survey_review, motivo):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with pytest.raises(ValueError):
            SurveyReviewService.reject(db_session, review.id, gtv.id, motivo)

        assert review.status == "in_review"
        assert review.rejection_reason is None

    def test_no_se_puede_observar_lo_ya_liberado(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="approved", reviewer=gtv)

        with pytest.raises(ValueError):
            SurveyReviewService.reject(db_session, review.id, gtv.id, "Motivo")

    def test_proceso_no_activo(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        process.status = "on_hold"
        db_session.flush()
        review = make_survey_review(process, status="in_review")

        with pytest.raises(ValueError):
            SurveyReviewService.reject(db_session, review.id, gtv.id, "Motivo")

    def test_id_inexistente(self, db_session, escenario):
        with pytest.raises(LookupError):
            SurveyReviewService.reject(db_session, 4_242_424, escenario["gtv"].id, "Motivo")


# ---------------------------------------------------------------------------
# revoke (Revocar)
# ---------------------------------------------------------------------------
class TestRevoke:
    @staticmethod
    def _aprobar(db_session, process, gtv, make_survey_review):
        review = make_survey_review(process, status="in_review")
        with patch(NOTIFY):
            return SurveyReviewService.approve(db_session, review.id, gtv.id)

    def test_revoca_y_desacredita_si_la_fase_2_no_esta_aprobada(
            self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = self._aprobar(db_session, process, gtv, make_survey_review)

        with patch(NOTIFY) as mock_notify:
            resultado = SurveyReviewService.revoke(db_session, review.id, gtv.id, "Aclaración")

        assert resultado.status == "rejected"
        assert resultado.rejection_reason == "Aclaración"
        eventos = _events(db_session, process.id, "survey_review_revoked")
        assert len(eventos) == 1
        assert eventos[0].payload == {"reason": "Aclaración", "origin": "submission",
                                      "review_id": review.id}
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["type"] == "SURVEY_REVIEW_REVOKED"
        assert mock_notify.call_args.kwargs["body"] == "Aclaración"

        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        req = next(r for r in CotejoRequirementService.list(db_session, process.cohort_id)
                   if r.auto_source == AUTO_SURVEY)
        assert _fulfillment(db_session, process.id, req.id) is None

    def test_revocar_una_previa_la_borra_y_vuelve_a_sin_enviar(
            self, db_session, escenario, monkeypatch):
        """Ruling R22 (I4 de la revisión final): una liberación por constancia
        previa (D9) no tiene encuesta real detrás. Dejarla `rejected` atoraba
        al egresado para siempre (`SurveyService.submit` corta mientras exista
        CUALQUIER fila). Revocarla deja el evento (con `origin`) y el
        `unfulfill`, y BORRA la fila: la solicitud vuelve a `missing`."""
        from datetime import timedelta

        from itcj2.apps.titulatec.models import EmailOutbox
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )
        from itcj2.config import get_settings
        from itcj2.core.utils.timezone import db_now

        # Correo encendido sin depender del `.env` del contenedor.
        monkeypatch.setattr(get_settings(), "TITULATEC_EMAIL_ENABLED", True)
        process, gtv = escenario["process"], escenario["gtv"]
        with patch(NOTIFY):
            previa = SurveyReviewService.register_prior(
                db_session, process, issued_on=db_now().date() - timedelta(days=30))
        db_session.flush()
        previa_id = previa.id
        req = next(r for r in CotejoRequirementService.list(db_session, process.cohort_id)
                   if r.auto_source == AUTO_SURVEY)
        assert _fulfillment(db_session, process.id, req.id) is not None

        with patch(NOTIFY) as aviso:
            resultado = SurveyReviewService.revoke(
                db_session, previa_id, gtv.id, "Número de control equivocado")

        assert resultado is None, "la previa ya no existe: no hay solicitud que devolver"
        assert SurveyReviewService.get_for_process(db_session, process.id) is None
        assert SurveyReviewService.summary_for_process(db_session, process.id)["status"] == (
            "missing")
        assert _fulfillment(db_session, process.id, req.id) is None
        eventos = _events(db_session, process.id, "survey_review_revoked")
        assert [e.payload for e in eventos] == [
            {"reason": "Número de control equivocado", "origin": "prior",
             "review_id": previa_id}]
        aviso.assert_called_once()
        assert aviso.call_args.kwargs["type"] == "SURVEY_REVIEW_REVOKED"
        db_session.flush()
        correo = (db_session.query(EmailOutbox)
                  .filter_by(process_id=process.id, kind="survey_revoked").one())
        assert correo.payload["origin"] == "prior"

    def test_no_revoca_si_la_fase_2_ya_fue_aprobada(
            self, db_session, escenario, make_survey_review):
        from itcj2.apps.titulatec.models import ProcessPhase
        process, gtv = escenario["process"], escenario["gtv"]
        review = self._aprobar(db_session, process, gtv, make_survey_review)
        fase2 = (db_session.query(ProcessPhase)
                .filter_by(process_id=process.id, phase_number=2).first())
        fase2.status = "approved"
        db_session.flush()

        with pytest.raises(ValueError):
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "Aclaración")

        assert review.status == "approved"

    def test_solo_se_revoca_lo_liberado(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review")

        with pytest.raises(ValueError):
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "Motivo")

    def test_proceso_no_activo(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = self._aprobar(db_session, process, gtv, make_survey_review)
        process.status = "completed"
        db_session.flush()

        with pytest.raises(ValueError):
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "Motivo")

        assert review.status == "approved"

    @pytest.mark.parametrize("motivo", ["", "   ", "x" * (REASON_MAX + 1)])
    def test_motivo_invalido(self, db_session, escenario, make_survey_review, motivo):
        process, gtv = escenario["process"], escenario["gtv"]
        review = self._aprobar(db_session, process, gtv, make_survey_review)

        with pytest.raises(ValueError):
            SurveyReviewService.revoke(db_session, review.id, gtv.id, motivo)

        assert review.status == "approved"

    def test_id_inexistente(self, db_session, escenario):
        with pytest.raises(LookupError):
            SurveyReviewService.revoke(db_session, 1_357_924, escenario["gtv"].id, "Motivo")


# ---------------------------------------------------------------------------
# prior_outcome
# ---------------------------------------------------------------------------
class TestPriorOutcome:
    def test_sin_fila_ni_revocacion_previa_es_apply(self, db_session, escenario):
        assert SurveyReviewService.prior_outcome(
            db_session, escenario["process"].id) == "apply"

    def test_revocar_una_previa_deja_conflict_no_apply(self, db_session, escenario):
        """Ruling R30 #2 (re-revisión de la ola final): `revoke` (Ruling R22)
        BORRA la fila de una previa -sin este arreglo `prior_outcome` vería
        `missing` (como si nunca hubiera pasado nada) y devolvería `apply`:
        un re-import del mismo archivo la re-aprobaría sola, pisando la
        decisión de GTV de revocarla-. El evento `survey_review_revoked` con
        `origin='prior'` sobrevive al DELETE de la fila: mientras exista,
        este proceso se queda en `conflict` (lo decide GTV, nunca una
        importación), igual que una solicitud real `in_review`/`rejected`."""
        from datetime import timedelta

        from itcj2.core.utils.timezone import db_now

        process, gtv = escenario["process"], escenario["gtv"]
        with patch(NOTIFY):
            previa = SurveyReviewService.register_prior(
                db_session, process, issued_on=db_now().date() - timedelta(days=30))
            db_session.flush()
            SurveyReviewService.revoke(
                db_session, previa.id, gtv.id, "Número de control equivocado")

        assert SurveyReviewService.get_for_process(db_session, process.id) is None
        assert SurveyReviewService.prior_outcome(db_session, process.id) == "conflict"

    def test_revocar_una_solicitud_real_no_dispara_la_marca_de_previa(
            self, db_session, escenario, make_survey_review):
        """Contraste: revocar una encuesta REAL (`origin='submission'`) NO
        borra la fila -queda `rejected`- así que `prior_outcome` sigue
        leyendo la fila de siempre (`conflict` por la fila, no por el
        evento); el evento de esta revocación trae `origin='submission'`, no
        `'prior'`, así que tampoco activaría la marca nueva aunque la fila se
        borrara."""
        review = make_survey_review(escenario["process"], status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, escenario["gtv"].id)
            SurveyReviewService.revoke(db_session, review.id, escenario["gtv"].id, "Aclaración")

        assert SurveyReviewService.get_for_process(db_session, review.process_id) is not None
        assert SurveyReviewService.prior_outcome(db_session, review.process_id) == "conflict"


# ---------------------------------------------------------------------------
# prior_conflict_reason (m39)
# ---------------------------------------------------------------------------
class TestPriorConflictReason:
    """Submotivo fino de `prior_outcome == "conflict"`: distingue «GTV
    revocó la previa aquí» de «hay una solicitud real en revisión», para que
    `PriorClearanceService.import_rows` (la CLI) imprima el mensaje correcto
    sin leer `.status` ni eventos por su cuenta (§5, invariante 2)."""

    def test_none_si_no_hay_conflicto(self, db_session, escenario):
        assert SurveyReviewService.prior_conflict_reason(
            db_session, escenario["process"].id) is None

    def test_none_si_ya_esta_aprobada(self, db_session, escenario, make_survey_review):
        review = make_survey_review(escenario["process"], status="approved")
        assert SurveyReviewService.prior_conflict_reason(
            db_session, review.process_id) is None

    def test_revoked_si_gtv_revoco_una_previa_aqui(self, db_session, escenario):
        """Mismo escenario que `test_revocar_una_previa_deja_conflict_no_apply`
        de `TestPriorOutcome`, pero mirando el submotivo: debe ser `"revoked"`,
        no `"in_review"` -son casos que la CLI debe anunciar distinto (m39)."""
        from datetime import timedelta

        from itcj2.core.utils.timezone import db_now

        process, gtv = escenario["process"], escenario["gtv"]
        with patch(NOTIFY):
            previa = SurveyReviewService.register_prior(
                db_session, process, issued_on=db_now().date() - timedelta(days=30))
            db_session.flush()
            SurveyReviewService.revoke(
                db_session, previa.id, gtv.id, "Número de control equivocado")

        assert SurveyReviewService.prior_conflict_reason(db_session, process.id) == "revoked"

    def test_in_review_si_hay_una_solicitud_real_esperando(
            self, db_session, escenario, make_survey_review):
        review = make_survey_review(escenario["process"], status="in_review")
        assert SurveyReviewService.prior_conflict_reason(
            db_session, review.process_id) == "in_review"

    def test_in_review_si_la_solicitud_real_fue_observada(
            self, db_session, escenario, make_survey_review):
        review = make_survey_review(escenario["process"], status="rejected")
        assert SurveyReviewService.prior_conflict_reason(
            db_session, review.process_id) == "in_review"


# ---------------------------------------------------------------------------
# can_revoke
# ---------------------------------------------------------------------------
class TestCanRevoke:
    def test_true_si_fase_2_no_esta_aprobada_y_proceso_activo(
            self, db_session, escenario, make_survey_review):
        review = make_survey_review(escenario["process"], status="approved",
                                    reviewer=escenario["gtv"])
        assert SurveyReviewService.can_revoke(db_session, review) is True

    def test_false_si_la_fase_2_ya_fue_aprobada(
            self, db_session, escenario, make_survey_review):
        from itcj2.apps.titulatec.models import ProcessPhase
        process = escenario["process"]
        fase2 = (db_session.query(ProcessPhase)
                .filter_by(process_id=process.id, phase_number=2).first())
        fase2.status = "approved"
        db_session.flush()
        review = make_survey_review(process, status="approved", reviewer=escenario["gtv"])

        assert SurveyReviewService.can_revoke(db_session, review) is False

    def test_false_si_el_proceso_no_esta_activo(
            self, db_session, escenario, make_survey_review):
        process = escenario["process"]
        process.status = "completed"
        db_session.flush()
        review = make_survey_review(process, status="approved", reviewer=escenario["gtv"])

        assert SurveyReviewService.can_revoke(db_session, review) is False


# ---------------------------------------------------------------------------
# counts_by_status
# ---------------------------------------------------------------------------
class TestCountsByStatus:
    """`counts_by_status` cuenta la TABLA ENTERA: no recibe convocatoria ni
    alcance, y es lo que alimenta las pestañas de la bandeja de GTV.

    Por eso estos dos tests miden DELTA y no absolutos (2026-09-18). Asertar
    `{"approved": 0}` daba por hecho que la base no tiene ni una liberación de
    verdad, y se puso rojo el día que un alumno real de dev envió su encuesta y
    GTV se la aprobó: nada que ver con el código, solo con que la base dejó de
    estar vacía. La suite corre contra la base de dev (savepoint por test, pero
    la base es la real), así que un absoluto aquí es una bomba de tiempo.
    """

    def test_las_tres_llaves_siempre_presentes(self, db_session):
        """El contrato es que las tres llaves existan SIEMPRE, con o sin filas:
        la bandeja pinta `counts["rejected"]` sin comprobar nada."""
        counts = SurveyReviewService.counts_by_status(db_session)

        assert set(counts) == {"in_review", "approved", "rejected"}
        assert all(isinstance(v, int) and v >= 0 for v in counts.values()), counts

    def test_cuenta_por_estado(self, db_session, make_student, make_cohort,
                               make_process, make_survey_review):
        antes = SurveyReviewService.counts_by_status(db_session)

        cohort = make_cohort()
        p1 = make_process(make_student(), cohort=cohort, current_phase=2)
        p2 = make_process(make_student(), cohort=cohort, current_phase=2)
        p3 = make_process(make_student(), cohort=cohort, current_phase=2)
        make_survey_review(p1, status="in_review")
        make_survey_review(p2, status="in_review")
        make_survey_review(p3, status="rejected")

        despues = SurveyReviewService.counts_by_status(db_session)

        assert despues["in_review"] - antes["in_review"] == 2
        assert despues["rejected"] - antes["rejected"] == 1
        assert despues["approved"] - antes["approved"] == 0, (
            "ninguna de las tres sembradas es `approved`: si sube, el estado se "
            "está clasificando mal"
        )


# ---------------------------------------------------------------------------
# list_for_inbox
# ---------------------------------------------------------------------------
class TestListForInbox:
    def test_filtra_por_pestana_y_ordena_in_review_mas_antiguas_primero(
            self, db_session, make_student, make_cohort, make_process, make_survey_review):
        cohort = make_cohort()
        ana = make_student()
        beto = make_student()
        carla = make_student()
        p1 = make_process(ana, cohort=cohort, current_phase=2)
        p2 = make_process(beto, cohort=cohort, current_phase=2)
        p3 = make_process(carla, cohort=cohort, current_phase=2)
        r1 = make_survey_review(p1, status="in_review")
        r2 = make_survey_review(p2, status="in_review")
        make_survey_review(p3, status="rejected")

        pagina = SurveyReviewService.list_for_inbox(db_session, status="in_review")
        filas = pagina.items

        assert pagina.has_next is False
        assert pagina.total == 2
        assert [f["id"] for f in filas] == [r1.id, r2.id]
        primera = filas[0]
        assert primera["process_id"] == p1.id
        assert primera["control"] == ana.control_number
        assert primera["status"] == "in_review"
        assert primera["current_phase"] == 2
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", primera["submitted"])

    def test_busca_por_control_o_nombre(
            self, db_session, make_student, make_cohort, make_process, make_survey_review):
        cohort = make_cohort()
        ana = make_student(first_name="ANA", last_name="ZAPATA")
        beto = make_student(first_name="BETO", last_name="LOPEZ")
        p1 = make_process(ana, cohort=cohort, current_phase=2)
        p2 = make_process(beto, cohort=cohort, current_phase=2)
        make_survey_review(p1, status="in_review")
        make_survey_review(p2, status="in_review")

        por_nombre = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", q="ZAPATA").items
        assert [f["process_id"] for f in por_nombre] == [p1.id]

        por_control = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", q=beto.control_number).items
        assert [f["process_id"] for f in por_control] == [p2.id]

    def test_paginado_con_has_more(
            self, db_session, make_student, make_cohort, make_process, make_survey_review):
        cohort = make_cohort()
        reviews = [
            make_survey_review(make_process(make_student(), cohort=cohort, current_phase=2),
                               status="in_review")
            for _ in range(3)
        ]

        p1 = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", page=1, per_page=2)
        p2 = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", page=2, per_page=2)
        pagina1, pagina2 = p1.items, p2.items

        assert len(pagina1) == 2
        assert p1.has_next is True
        assert len(pagina2) == 1
        assert p2.has_next is False
        assert (p1.total, p2.total) == (3, 3)
        assert ({f["id"] for f in pagina1} | {f["id"] for f in pagina2}
                == {r.id for r in reviews})

    def test_inbox_muestra_rango_de_total(
            self, db_session, make_student, make_cohort, make_process, make_survey_review):
        cohort = make_cohort()
        for _ in range(3):
            make_survey_review(make_process(make_student(), cohort=cohort, current_phase=2),
                               status="in_review")

        p2 = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", page=2, per_page=2)
        p9 = SurveyReviewService.list_for_inbox(
            db_session, status="in_review", page=9, per_page=2)

        assert (p2.start, p2.end, p2.total) == (3, 3, 3)
        assert (p9.page, p9.start, p9.end) == (2, 3, 3)

    def test_can_revoke_en_lote(
            self, db_session, make_student, make_cohort, make_process, make_survey_review):
        from itcj2.apps.titulatec.models import ProcessPhase
        cohort = make_cohort()
        libre = make_process(make_student(), cohort=cohort, current_phase=2)
        cerrada = make_process(make_student(), cohort=cohort, current_phase=2)
        fase2_cerrada = (db_session.query(ProcessPhase)
                        .filter_by(process_id=cerrada.id, phase_number=2).first())
        fase2_cerrada.status = "approved"
        db_session.flush()

        r_libre = make_survey_review(libre, status="approved")
        r_cerrada = make_survey_review(cerrada, status="approved")

        filas = SurveyReviewService.list_for_inbox(db_session, status="approved").items

        por_id = {f["id"]: f for f in filas}
        assert por_id[r_libre.id]["can_revoke"] is True
        assert por_id[r_cerrada.id]["can_revoke"] is False

    def test_fila_trae_certificate_el_dict_de_print_status_map(
            self, db_session, make_student, make_cohort, make_process,
            make_survey_review, make_user):
        """Tarea 3 (`2026-10-02-titulatec-constancias-y-pendientes-design.md`
        §3.3): la fila agrega `certificate` -el dict de
        `CertificateService.print_status_map` para `survey_review:{id}`,
        UNA llamada por página- que la plantilla pinta con `certificate_cell`."""
        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        cohort = make_cohort()
        gtv = make_user(first_name="GTV", last_name="DE PRUEBA")
        proc = make_process(make_student(), cohort=cohort, current_phase=2)
        review = make_survey_review(proc, status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)
        batch = CertificateService.create_batch(db_session, kind="survey_release",
                                                actor_id=gtv.id)
        sin_liberar = make_survey_review(
            make_process(make_student(), cohort=cohort, current_phase=2), status="in_review")

        filas = SurveyReviewService.list_for_inbox(db_session, status="approved").items
        fila = next(f for f in filas if f["id"] == review.id)
        assert fila["certificate"]["printed"] is True
        assert fila["certificate"]["batch_id"] == batch.id

        filas_en_revision = SurveyReviewService.list_for_inbox(
            db_session, status="in_review").items
        fila_sin = next(f for f in filas_en_revision if f["id"] == sin_liberar.id)
        assert fila_sin["certificate"] is None


# ---------------------------------------------------------------------------
# summary_for_process
# ---------------------------------------------------------------------------
class TestSummaryForProcess:
    # Llaves del resumen. Sin `certificate` (Ruling R14, revisión final de
    # `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.4): el
    # estado de impresión lo cuelgan las dos vistas de SE con UNA llamada a
    # `print_status_map` para encuesta y no adeudo juntos.
    LLAVES = {"status", "reason", "reviewed_by", "reviewed_at", "review_id",
              "response_id", "origin"}

    def test_sin_solicitud(self, db_session, escenario):
        resumen = SurveyReviewService.summary_for_process(db_session, escenario["process"].id)
        assert resumen == {
            "status": "missing", "reason": None, "reviewed_by": None,
            "reviewed_at": None, "review_id": None, "response_id": None,
            "origin": None,
        }

    def test_con_solicitud_en_revision(self, db_session, escenario, make_survey_review):
        process = escenario["process"]
        review = make_survey_review(process, status="in_review")

        resumen = SurveyReviewService.summary_for_process(db_session, process.id)

        assert set(resumen) == self.LLAVES
        assert resumen["status"] == "in_review"
        assert resumen["review_id"] == review.id
        assert resumen["response_id"] == review.response_id
        assert resumen["reviewed_by"] is None
        assert resumen["reviewed_at"] is None

    def test_con_observaciones_y_revisor(self, db_session, escenario, make_survey_review):
        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="rejected",
                                    reason="Falta Servicio Social", reviewer=gtv)

        resumen = SurveyReviewService.summary_for_process(db_session, process.id)

        assert resumen["status"] == "rejected"
        assert resumen["reason"] == "Falta Servicio Social"
        assert resumen["reviewed_by"] == gtv.full_name
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", resumen["reviewed_at"])

    def test_no_commitea(self, db_session, escenario, monkeypatch):
        monkeypatch.setattr(
            db_session, "commit",
            lambda: pytest.fail("summary_for_process no debe commitear"))
        SurveyReviewService.summary_for_process(db_session, escenario["process"].id)

    def test_no_consulta_constancias_ni_la_marca(
            self, db_session, escenario, make_survey_review, monkeypatch):
        """Ruling R14 (M3/P2 de la revisión final): este resumen lo usan
        también el tablero del egresado, «Mi cita» y las páginas públicas de
        la encuesta, que no pintan la constancia. Ya no llama
        `print_status_map` ni toca `titulatec_certificates`/
        `titulatec_certificate_batches`, aun con la constancia `survey_release`
        emitida e impresa. Las variantes de la celda (sin imprimir, impresa,
        anulada tras imprimir, previa) las cubren ahora las vistas de SE, que
        cuelgan `certificate` ellas mismas con UNA llamada
        (`test_se_library_views.py::TestCeldaDeConstanciaEncuesta`)."""
        from sqlalchemy import event

        from itcj2.apps.titulatec.services.certificate_service import CertificateService

        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)
        CertificateService.create_batch(db_session, kind="survey_release", actor_id=gtv.id)
        llamadas = []
        monkeypatch.setattr(CertificateService, "print_status_map", staticmethod(
            lambda db, refs: llamadas.append(list(refs)) or {}))
        sentencias = []

        def _antes(_conn, _cursor, statement, *_a):
            sentencias.append(statement)

        bind = db_session.get_bind()
        event.listen(bind, "before_cursor_execute", _antes)
        try:
            resumen = SurveyReviewService.summary_for_process(db_session, process.id)
        finally:
            event.remove(bind, "before_cursor_execute", _antes)

        assert resumen["status"] == "approved" and set(resumen) == self.LLAVES
        assert llamadas == []
        assert not [s for s in sentencias if "titulatec_certificate" in s], sentencias

    def test_certificate_ref_es_el_source_ref_de_su_constancia(
            self, db_session, escenario, make_survey_review):
        """`certificate_ref` (Ruling R14): el `source_ref` con el que
        `approve()` emite la constancia `survey_release` -con él las vistas de
        SE piden la marca de impresión-; `None` sin solicitud."""
        from itcj2.apps.titulatec.models import Certificate

        process, gtv = escenario["process"], escenario["gtv"]
        review = make_survey_review(process, status="in_review")
        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, gtv.id)

        ref = SurveyReviewService.certificate_ref(review.id)
        assert db_session.query(Certificate).filter_by(
            source_ref=ref, voided_at=None).count() == 1
        assert SurveyReviewService.certificate_ref(None) is None

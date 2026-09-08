"""Cumplimientos de requisitos de cotejo por proceso (`RequirementService`).

La otra mitad de `titulatec_cotejo_requirements`: la tabla de la lista existia
desde la migracion `e8368b899ed1`, pero no habia donde anotar QUIEN ya cumplio
que. Sin esta pieza el checklist del alumno era una constante hardcodeada y el
dictamen de la fase 2 no podia mirar nada.

Regla de la casa: toda escritura deja `ProcessEvent`. Los asertos sobre la
bitacora no son decoracion — es lo unico que queda cuando alguien desmarca.
"""
from __future__ import annotations

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.requirement_service import RequirementService

AUTO_SURVEY = "graduate_survey"


def _req(db, cohort, *, label="Encuesta de egresados", icon="clipboard-check",
         hint=None, code=None, auto_source=None, is_required=True,
         is_active=True, order_index=0):
    """Un `CotejoRequirement` de esa convocatoria, escrito a mano."""
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


@pytest.fixture()
def escenario(db_session, make_student, make_process, make_cohort, make_user):
    """Una convocatoria con requisitos, un alumno con proceso y un oficial."""
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort, current_phase=2)
    oficial = make_user(first_name="OFICIAL", last_name="DE PRUEBA")
    return {"cohort": cohort, "process": process, "oficial": oficial}


class TestListWithStatus:
    def test_marca_lo_cumplido_y_deja_lo_pendiente(self, db_session, escenario):
        cohort, process = escenario["cohort"], escenario["process"]
        uno = _req(db_session, cohort, label="Actas de nacimiento", order_index=0)
        _req(db_session, cohort, label="12 fotografias", order_index=1)

        RequirementService.fulfill(db_session, process.id, uno.id, source="officer",
                                   checked_by_id=escenario["oficial"].id, commit=False)

        filas = RequirementService.list_with_status(db_session, process.id)

        assert [f["requirement"].label for f in filas] == [
            "Actas de nacimiento", "12 fotografias"]
        assert filas[0]["is_done"] is True
        assert filas[0]["fulfillment"].source == "officer"
        assert filas[1]["is_done"] is False
        assert filas[1]["fulfillment"] is None

    def test_proceso_inexistente_devuelve_lista_vacia(self, db_session):
        assert RequirementService.list_with_status(db_session, 987654321) == []


class TestFulfill:
    def test_escribe_snapshot_y_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="Encuesta de egresados",
                   code=AUTO_SURVEY, auto_source=AUTO_SURVEY)
        process = escenario["process"]

        fila = RequirementService.fulfill(
            db_session, process.id, req.id, source="self_service",
            external_ref="survey_response:42", commit=False)

        assert fila.status == "fulfilled"
        assert fila.requirement_code == AUTO_SURVEY
        assert fila.label_snapshot == "Encuesta de egresados"
        assert fila.external_ref == "survey_response:42"
        assert fila.fulfilled_at is not None
        eventos = _events(db_session, process.id, "requirement_fulfilled")
        assert len(eventos) == 1
        assert eventos[0].phase_number == 2
        assert eventos[0].payload["requirement_id"] == req.id

    def test_es_idempotente_y_no_duplica_el_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]

        a = RequirementService.fulfill(db_session, process.id, req.id,
                                       source="officer", commit=False)
        b = RequirementService.fulfill(db_session, process.id, req.id,
                                       source="officer", commit=False)

        assert a.id == b.id
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 1

    def test_cambiar_a_waived_reescribe_la_fila_y_deja_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        fila = RequirementService.fulfill(db_session, process.id, req.id,
                                          source="officer", status="waived",
                                          note="Caso legitimo", commit=False)

        assert fila.status == "waived"
        assert fila.note == "Caso legitimo"
        assert len(_events(db_session, process.id, "requirement_fulfilled")) == 2


class TestUnfulfill:
    def test_borra_la_fila_y_deja_el_evento(self, db_session, escenario):
        from itcj2.apps.titulatec.models import RequirementFulfillment

        req = _req(db_session, escenario["cohort"], label="No-adeudo de biblioteca")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id,
                                   source="officer", commit=False)

        ok = RequirementService.unfulfill(db_session, process.id, req.id,
                                          actor_id=escenario["oficial"].id, commit=False)

        assert ok is True
        assert db_session.query(RequirementFulfillment).filter_by(
            process_id=process.id, requirement_id=req.id).first() is None
        eventos = _events(db_session, process.id, "requirement_unfulfilled")
        assert len(eventos) == 1
        assert eventos[0].payload["label"] == "No-adeudo de biblioteca"

    def test_sin_fila_devuelve_false_y_no_escribe_evento(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"])
        process = escenario["process"]

        ok = RequirementService.unfulfill(db_session, process.id, req.id,
                                          actor_id=escenario["oficial"].id, commit=False)

        assert ok is False
        assert _events(db_session, process.id, "requirement_unfulfilled") == []


class TestMissingRequired:
    def test_ignora_opcionales_e_inactivos(self, db_session, escenario):
        cohort, process = escenario["cohort"], escenario["process"]
        obligatorio = _req(db_session, cohort, label="Obligatorio", order_index=0)
        _req(db_session, cohort, label="Opcional", is_required=False, order_index=1)
        _req(db_session, cohort, label="Retirado", is_active=False, order_index=2)

        faltan = RequirementService.missing_required(db_session, process.id)

        assert [r.id for r in faltan] == [obligatorio.id]

    def test_waived_cuenta_como_cumplido(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="Vigencia IMSS")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   status="waived", commit=False)

        assert RequirementService.missing_required(db_session, process.id) == []

    def test_rejected_no_cuenta_como_cumplido(self, db_session, escenario):
        req = _req(db_session, escenario["cohort"], label="e.Firma")
        process = escenario["process"]
        RequirementService.fulfill(db_session, process.id, req.id, source="officer",
                                   status="rejected", commit=False)

        assert [r.id for r in
                RequirementService.missing_required(db_session, process.id)] == [req.id]


class TestAutoRequirement:
    def test_encuentra_el_de_la_encuesta(self, db_session, escenario):
        cohort = escenario["cohort"]
        _req(db_session, cohort, label="Actas", order_index=0)
        encuesta = _req(db_session, cohort, label="Encuesta de egresados",
                        code=AUTO_SURVEY, auto_source=AUTO_SURVEY, order_index=1)

        hallado = RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)

        assert hallado is not None and hallado.id == encuesta.id

    def test_none_si_la_convocatoria_ya_tiene_lista_sin_ese_auto_source(
            self, db_session, escenario):
        cohort = escenario["cohort"]
        _req(db_session, cohort, label="Actas", order_index=0)

        assert RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY) is None

    def test_siembra_los_defaults_si_la_convocatoria_esta_vacia(self, db_session, make_cohort):
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService, DEFAULTS,
        )

        cohort = make_cohort()

        RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)

        assert len(CotejoRequirementService.list(db_session, cohort.id)) == len(DEFAULTS)

    def test_no_commitea(self, db_session, make_cohort, monkeypatch):
        """§4.4 exige UN solo commit al enviar la encuesta.

        Si el seed-or-la-lista commiteara aqui, la respuesta a medio escribir se
        quedaria en la BD aunque el cumplimiento fallara despues.
        """
        cohort = make_cohort()
        monkeypatch.setattr(
            db_session, "commit",
            lambda: pytest.fail("auto_requirement no debe commitear"))

        RequirementService.auto_requirement(db_session, cohort.id, AUTO_SURVEY)

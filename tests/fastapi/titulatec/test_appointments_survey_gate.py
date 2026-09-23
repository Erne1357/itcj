"""Puerta de agendar sin la encuesta de egresados enviada, cola "Sin encuesta"
del panel de citas y sufijo de estatus de GTV en la guarda de la fase 2.

Tarea 4 de `docs/superpowers/specs/2026-09-15-titulatec-liberacion-gtv-design.md`
(D2 en §5.1, D3 en §5.2). Consume de la Tarea 2: modelo `SurveyReview`,
`SurveyReviewService.summary_for_process` y la fixture `make_survey_review`
(crea SOLO la solicitud —y una respuesta mínima detrás—, NUNCA el cumplimiento
del requisito `graduate_survey`, ni siquiera con `status="approved"`: eso es
un EFECTO de `SurveyReviewService.approve`, así que los tests que necesitan la
fase 2 realmente liberable lo llaman aparte).
"""
from __future__ import annotations

from datetime import date, time
from unittest.mock import patch
from urllib.parse import unquote

import pytest

import itcj2.models  # noqa: F401

from tests.fastapi.titulatec.conftest import OFFICER_PERMS

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService
from itcj2.apps.titulatec.services.phase_service import PhaseService
from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

NOTIFY = "itcj2.apps.titulatec.services.notify.notify_student"

# El encargado de las pruebas de RUTA necesita el permiso de crear cita, que
# `OFFICER_PERMS` (el set por omisión de `make_officer`) no trae.
SCHEDULE_PERMS = OFFICER_PERMS + ("titulatec.appointment.api.create",)


def _msg(resp) -> str:
    return unquote(resp.headers.get("X-Tt-Error", ""))


def _req(db, cohort, *, label="Encuesta de egresados", auto_source="graduate_survey",
         is_required=True, is_active=True, order_index=0):
    """Un `CotejoRequirement` de la encuesta, escrito a mano (copia de
    `test_survey_review_service.py::_req`)."""
    from itcj2.apps.titulatec.models import CotejoRequirement
    row = CotejoRequirement(
        cohort_id=cohort.id, label=label, icon="clipboard-check",
        auto_source=auto_source, is_required=is_required, is_active=is_active,
        order_index=order_index,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# `AppointmentService.create`: la guarda dura (D2)
# ---------------------------------------------------------------------------
class TestCreateExigeSolicitud:
    def test_sin_solicitud_no_agenda(self, db_session, agenda_slots):
        esc = agenda_slots
        with pytest.raises(err.SurveyNotSubmitted):
            AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                      slot_start=time(9, 0), created_by_id=esc["off"].id)

    def test_el_mensaje_es_el_que_ve_el_usuario_y_no_refresca(self, db_session, agenda_slots):
        esc = agenda_slots
        with pytest.raises(err.SurveyNotSubmitted) as exc:
            AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                      slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert "encuesta de egresados" in str(exc.value)
        assert exc.value.refresca_la_vista is False, (
            "es entrada del usuario (falta la solicitud): 400, no un 200 que "
            "re-renderice como si algo hubiera cambiado de estado")

    def test_no_escribe_nada_al_rechazar(self, db_session, agenda_slots):
        esc = agenda_slots
        with pytest.raises(err.SurveyNotSubmitted):
            AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                      slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert AppointmentService.get_for_process(db_session, esc["p1"].id) is None

    @pytest.mark.parametrize("status", ["in_review", "rejected", "approved"])
    def test_con_solicitud_en_cualquier_estado_agenda(
        self, db_session, agenda_slots, make_survey_review, status,
    ):
        """D2: hace falta que la haya ENVIADO, no que GTV ya la haya liberado."""
        esc = agenda_slots
        make_survey_review(esc["p1"], status=status)

        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert ap.status == "scheduled"

    def test_aplica_al_reagendar_desde_no_show(self, db_session, agenda_slots, make_appointment):
        """`create` sobre una cita que quedó en `no_show` es un movimiento
        legal (matriz de transiciones); D2 dice que la guarda de la encuesta
        aplica igual ahí — no solo a la primera cita."""
        esc = agenda_slots
        make_appointment(esc["p1"], status="no_show")

        with pytest.raises(err.SurveyNotSubmitted):
            AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                      slot_start=time(9, 30), created_by_id=esc["off"].id)


# ---------------------------------------------------------------------------
# Por la ruta: 400 + X-Tt-Error. `_accion` (`pages/appointments.py`) ya
# traduce cualquier `AppointmentError` no-refrescante; la ruta `/schedule` NO
# se tocó para esta tarea.
# ---------------------------------------------------------------------------
@pytest.fixture()
def escenario_ruta(seed_phase_defs, seed_document_types, make_program, make_cohort,
                   make_review_day, make_review_window, make_officer, make_student,
                   make_process):
    """Un espacio abierto y un proceso listo para agendar, con un encargado
    que SÍ tiene el permiso de crear cita (`OFFICER_PERMS` no lo trae)."""
    def _build():
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria de la Encuesta")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=date(2029, 6, 4))
        officer, pos = make_officer([prog], perm_codes=SCHEDULE_PERMS)
        window = make_review_window(dia, officer, start="09:00", end="11:00",
                                    slot=30, cap=1, position=pos)
        student = make_student()
        process = make_process(student, cohort=cohort, program=prog, current_phase=2)
        return {"officer": officer, "window": window, "process": process, "cohort": cohort}
    return _build


class TestRutaSchedule:
    def test_sin_solicitud_400_con_x_tt_error(self, client_as, escenario_ruta):
        esc = escenario_ruta()
        resp = client_as(esc["officer"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/schedule",
            data={"window_id": esc["window"].id, "slot_start": "09:00"})

        assert resp.status_code == 400, resp.text[:300]
        assert "encuesta de egresados" in _msg(resp)

    def test_con_solicitud_agenda_200(self, client_as, db_session, escenario_ruta,
                                      make_survey_review):
        esc = escenario_ruta()
        make_survey_review(esc["process"])

        resp = client_as(esc["officer"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/schedule",
            data={"window_id": esc["window"].id, "slot_start": "09:00"})

        assert resp.status_code == 200, resp.text[:300]
        ap = AppointmentService.get_for_process(db_session, esc["process"].id)
        assert ap is not None and ap.status == "scheduled"


# ---------------------------------------------------------------------------
# La cola: `list_pending_processes` exige solicitud;
# `list_missing_survey_processes` es su complemento en el MISMO universo
# (activos, sin cita, 3 documentos iniciales aprobados).
# ---------------------------------------------------------------------------
@pytest.fixture()
def dos_procesos(seed_phase_defs, seed_document_types, make_program, make_cohort,
                 make_student, make_process, make_document):
    """Dos procesos gemelos, listos salvo por la encuesta: `con` la envía
    (via el test que la necesite), `sin` nunca la envía."""
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de la Cola")
    cohort = make_cohort()
    procesos = {}
    for key in ("con", "sin"):
        st = make_student(last_name="COLA" + key.upper())
        proc = make_process(st, cohort=cohort, program=prog, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code, review_status="approved")
        procesos[key] = proc
    return {"prog": prog, "cohort": cohort, "procesos": procesos}


class TestColaSinEncuesta:
    def test_excluye_al_que_no_tiene_solicitud_e_incluye_al_que_si(
        self, db_session, dos_procesos, make_survey_review,
    ):
        esc = dos_procesos
        make_survey_review(esc["procesos"]["con"])

        pendientes = [p.id for p in AppointmentService.list_pending_processes(db_session)]
        sin_encuesta = [p.id for p in
                       AppointmentService.list_missing_survey_processes(db_session)]

        assert esc["procesos"]["con"].id in pendientes
        assert esc["procesos"]["sin"].id not in pendientes
        assert esc["procesos"]["sin"].id in sin_encuesta
        assert esc["procesos"]["con"].id not in sin_encuesta

    def test_alcance_por_carrera_en_list_missing_survey_processes(
        self, db_session, dos_procesos, make_program, make_student, make_process,
        make_document,
    ):
        """Mismo predicado de alcance que `list_pending_processes`: una
        carrera fuera de `allowed_program_ids` queda excluida, y el set vacío
        cierra sin consultar nada (fail-closed)."""
        esc = dos_procesos
        ajena = make_program("Ingenieria Ajena a la Cola")
        proc_ajeno = make_process(make_student(last_name="AJENOCOLA"), cohort=esc["cohort"],
                                  program=ajena, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc_ajeno, type_code=code, review_status="approved")

        solo_prog = [p.id for p in AppointmentService.list_missing_survey_processes(
            db_session, allowed_program_ids={esc["prog"].id})]

        assert esc["procesos"]["sin"].id in solo_prog
        assert proc_ajeno.id not in solo_prog
        assert AppointmentService.list_missing_survey_processes(
            db_session, allowed_program_ids=set()) == []

    def test_la_agenda_pinta_el_cubo_sin_arrastre_ni_navegacion(
        self, client_as, dos_procesos, make_officer,
    ):
        """A nivel de página: la fila del que no envió sale en "Sin encuesta"
        y NO lleva ni arrastre ni `appt_nav` (D2: nada que hacer con ella
        todavía). El que sí tiene solicitud no debe caer en este cubo."""
        esc = dos_procesos
        officer, _pos = make_officer([esc["prog"]])

        resp = client_as(officer).get("/titulatec/admin/appointments")

        assert resp.status_code == 200
        assert "Sin encuesta" in resp.text
        assert f'id="appt-nosurvey-{esc["procesos"]["sin"].id}"' in resp.text
        assert f'data-tt-drag="{esc["procesos"]["sin"].id}"' not in resp.text


# ---------------------------------------------------------------------------
# La guarda de la fase 2: sufijo por estatus de la encuesta (D3)
# ---------------------------------------------------------------------------
@pytest.fixture()
def escenario_fase2(db_session, seed_phase_defs, make_student, make_cohort, make_process):
    seed_phase_defs()
    cohort = make_cohort()
    process = make_process(make_student(), cohort=cohort, current_phase=2)
    req = _req(db_session, cohort)
    return {"cohort": cohort, "process": process, "req": req}


class TestGuardaFase2ConSufijoDeEncuesta:
    def test_sin_enviar(self, db_session, escenario_fase2, make_user):
        revisor = make_user()
        with patch(NOTIFY):
            with pytest.raises(ValueError) as exc:
                PhaseService.approve_phase(db_session, escenario_fase2["process"], 2,
                                           reviewer_id=revisor.id)

        assert "Encuesta de egresados (sin enviar)" in str(exc.value)

    def test_en_revision_por_gtv(self, db_session, escenario_fase2, make_user,
                                 make_survey_review):
        make_survey_review(escenario_fase2["process"], status="in_review")
        revisor = make_user()

        with patch(NOTIFY):
            with pytest.raises(ValueError) as exc:
                PhaseService.approve_phase(db_session, escenario_fase2["process"], 2,
                                           reviewer_id=revisor.id)

        assert "Encuesta de egresados (en revision por GTV)" in str(exc.value)

    def test_con_observaciones_de_gtv(self, db_session, escenario_fase2, make_user,
                                      make_survey_review):
        make_survey_review(escenario_fase2["process"], status="rejected",
                           reason="Pendiente en Residencias")
        revisor = make_user()

        with patch(NOTIFY):
            with pytest.raises(ValueError) as exc:
                PhaseService.approve_phase(db_session, escenario_fase2["process"], 2,
                                           reviewer_id=revisor.id)

        assert "Encuesta de egresados (con observaciones de GTV)" in str(exc.value)

    def test_libera_tras_approve(self, db_session, escenario_fase2, make_user,
                                 make_survey_review):
        """Tras `SurveyReviewService.approve` el requisito queda `fulfilled` y
        la fase 2 SÍ se libera: la abre GTV, no el envío de la encuesta (D3)."""
        review = make_survey_review(escenario_fase2["process"], status="in_review")
        revisor = make_user()

        with patch(NOTIFY):
            SurveyReviewService.approve(db_session, review.id, revisor.id)
            result = PhaseService.approve_phase(db_session, escenario_fase2["process"], 2,
                                                reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}

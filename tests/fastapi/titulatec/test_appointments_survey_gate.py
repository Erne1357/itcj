"""Puerta de agendar sin la encuesta de egresados LIBERADA por GTV, cola
«Liberaciones pendientes» del panel de citas (antes «Encuesta sin liberar»;
renombrada por la Tarea 5 del plan 2026-10-01-titulatec-biblioteca-caja, que
suma el no adeudo de biblioteca al mismo candado -- `ClearanceGate`) y sufijo
de estatus de GTV en la guarda de la fase 2.

Tarea 1 de
`docs/superpowers/specs/2026-09-29-titulatec-cotejo-espacios-design.md` (D1,
D2 en §2). **Revierte a propósito D2 del 2026-09-15** («basta con la encuesta
enviada»): agendar ya no exige solo que el egresado haya ENVIADO la encuesta
(`SurveyReview` con cualquier estado), sino que Gestión Tecnológica y
Vinculación la haya LIBERADO (`SurveyReview.status == 'approved'`). Consume de
la Tarea 2 del plan anterior: modelo `SurveyReview`,
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
# `AppointmentService.create`: la guarda dura (D1)
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

    def test_con_encuesta_liberada_agenda(self, db_session, agenda_slots, make_survey_review):
        """D1: hace falta que GTV la haya LIBERADO, no solo que la haya enviado."""
        esc = agenda_slots
        make_survey_review(esc["p1"], status="approved")

        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert ap.status == "scheduled"

    @pytest.mark.parametrize("status,fragmento", [
        ("in_review", "sigue en revisión"),
        ("rejected", "tiene observaciones"),
    ])
    def test_con_encuesta_sin_liberar_no_agenda(
        self, db_session, agenda_slots, make_survey_review, status, fragmento,
    ):
        """D1 revierte D2 del 2026-09-15: enviarla YA NO basta. `in_review` y
        `rejected` levantan `SurveyNotReleased`, no `SurveyNotSubmitted` —son
        estados DISTINTOS de «nunca la envió»— y no escriben nada."""
        esc = agenda_slots
        make_survey_review(esc["p1"], status=status)

        with pytest.raises(err.SurveyNotReleased) as exc:
            AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                      slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert fragmento in str(exc.value)
        assert "Gestión Tecnológica y Vinculación" in str(exc.value)
        assert exc.value.status == status
        assert exc.value.refresca_la_vista is False, (
            "sigue siendo entrada del usuario (la encuesta no está liberada): "
            "400, no un 200 que re-renderice como si algo hubiera cambiado")
        assert AppointmentService.get_for_process(db_session, esc["p1"].id) is None

    def test_aplica_al_reagendar_desde_no_show(self, db_session, agenda_slots, make_appointment):
        """`create` sobre una cita que quedó en `no_show` es un movimiento
        legal (matriz de transiciones); D1 dice que la guarda de la encuesta
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

    def test_con_encuesta_liberada_agenda_200(self, client_as, db_session, escenario_ruta,
                                              make_survey_review):
        esc = escenario_ruta()
        make_survey_review(esc["process"], status="approved")

        resp = client_as(esc["officer"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/schedule",
            data={"window_id": esc["window"].id, "slot_start": "09:00"})

        assert resp.status_code == 200, resp.text[:300]
        ap = AppointmentService.get_for_process(db_session, esc["process"].id)
        assert ap is not None and ap.status == "scheduled"

    def test_con_encuesta_en_revision_400_con_x_tt_error(self, client_as, db_session,
                                                         escenario_ruta, make_survey_review):
        """La guarda nueva llega hasta la RUTA: `SurveyNotReleased` también es
        entrada del usuario (400), no colisión de estado."""
        esc = escenario_ruta()
        make_survey_review(esc["process"], status="in_review")

        resp = client_as(esc["officer"]).post(
            f"/titulatec/admin/appointments/{esc['process'].id}/schedule",
            data={"window_id": esc["window"].id, "slot_start": "09:00"})

        assert resp.status_code == 400, resp.text[:300]
        assert "sigue en revisión" in _msg(resp)
        assert AppointmentService.get_for_process(db_session, esc["process"].id) is None


# ---------------------------------------------------------------------------
# La cola: `list_pending_processes` exige la encuesta LIBERADA;
# `list_missing_clearance_processes` es su complemento en el MISMO universo
# (activos, sin cita, 3 documentos iniciales aprobados) — incluye tanto a
# quien nunca la envió como a quien la envió pero GTV no la ha liberado. Estas
# convocatorias no traen el requisito automático de no adeudo (sin
# `seed_defaults`), así que la biblioteca no cuenta: eso lo prueba
# `test_clearance_gate.py`.
# ---------------------------------------------------------------------------
@pytest.fixture()
def tres_procesos(seed_phase_defs, seed_document_types, make_program, make_cohort,
                  make_student, make_process, make_document):
    """Tres procesos gemelos, listos salvo por la encuesta:

        con         GTV ya la liberó                  -> "Por agendar"
        en_revision la envió, GTV todavía la revisa    -> "Liberaciones pendientes"
        sin         nunca la envió                     -> "Liberaciones pendientes"
    """
    seed_phase_defs()
    seed_document_types()
    prog = make_program("Ingenieria de la Cola")
    cohort = make_cohort()
    procesos = {}
    for key in ("con", "en_revision", "sin"):
        st = make_student(last_name="COLA" + key.upper())
        proc = make_process(st, cohort=cohort, program=prog, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc, type_code=code, review_status="approved")
        procesos[key] = proc
    return {"prog": prog, "cohort": cohort, "procesos": procesos}


class TestColaEncuestaSinLiberar:
    def test_solo_la_liberada_cuenta_como_por_agendar(
        self, db_session, tres_procesos, make_survey_review,
    ):
        esc = tres_procesos
        make_survey_review(esc["procesos"]["con"], status="approved")
        make_survey_review(esc["procesos"]["en_revision"], status="in_review")
        # "sin" no lleva ninguna solicitud.

        pendientes = [p.id for p in AppointmentService.list_pending_processes(db_session)]
        sin_liberar = [p.id for p in
                      AppointmentService.list_missing_clearance_processes(db_session)]

        assert esc["procesos"]["con"].id in pendientes
        assert esc["procesos"]["en_revision"].id not in pendientes
        assert esc["procesos"]["sin"].id not in pendientes
        assert esc["procesos"]["en_revision"].id in sin_liberar
        assert esc["procesos"]["sin"].id in sin_liberar
        assert esc["procesos"]["con"].id not in sin_liberar

    def test_alcance_por_carrera_en_list_missing_clearance_processes(
        self, db_session, tres_procesos, make_program, make_student, make_process,
        make_document,
    ):
        """Mismo predicado de alcance que `list_pending_processes`: una
        carrera fuera de `allowed_program_ids` queda excluida, y el set vacío
        cierra sin consultar nada (fail-closed)."""
        esc = tres_procesos
        ajena = make_program("Ingenieria Ajena a la Cola")
        proc_ajeno = make_process(make_student(last_name="AJENOCOLA"), cohort=esc["cohort"],
                                  program=ajena, current_phase=2)
        for code in ("birth_certificate", "high_school_cert", "curp"):
            make_document(proc_ajeno, type_code=code, review_status="approved")

        solo_prog = [p.id for p in AppointmentService.list_missing_clearance_processes(
            db_session, allowed_program_ids={esc["prog"].id})]

        assert esc["procesos"]["sin"].id in solo_prog
        assert proc_ajeno.id not in solo_prog
        assert AppointmentService.list_missing_clearance_processes(
            db_session, allowed_program_ids=set()) == []

    def test_la_agenda_pinta_el_cubo_renombrado_con_la_pildora_por_fila(
        self, client_as, db_session, tres_procesos, make_officer, make_survey_review,
    ):
        """A nivel de página: el cubo se llama «Liberaciones pendientes» (antes
        «Encuesta sin liberar»), la fila de quien nunca envió NO lleva ni
        arrastre ni `appt_nav` (D1: nada que hacer con ella todavía) y cada
        fila lleva la píldora de su estado real (`survey_review_pill`)."""
        esc = tres_procesos
        make_survey_review(esc["procesos"]["en_revision"], status="in_review")
        officer, _pos = make_officer([esc["prog"]])

        resp = client_as(officer).get("/titulatec/admin/appointments")

        assert resp.status_code == 200
        assert "Liberaciones pendientes" in resp.text
        assert "Encuesta sin liberar" not in resp.text, "se quedó el rótulo viejo"
        assert "Sin encuesta" not in resp.text, "se quedó el rótulo viejo"
        assert f'id="appt-clearance-{esc["procesos"]["sin"].id}"' in resp.text
        assert f'id="appt-clearance-{esc["procesos"]["en_revision"].id}"' in resp.text
        assert f'data-tt-drag="{esc["procesos"]["sin"].id}"' not in resp.text
        assert f'data-tt-drag="{esc["procesos"]["en_revision"].id}"' not in resp.text
        # La píldora distingue "nunca la envió" (Encuesta pendiente) de "la
        # envió y sigue en revisión" (En revisión): dos filas del MISMO cubo,
        # dos estados reales distintos.
        assert "Encuesta pendiente" in resp.text
        assert "En revisión" in resp.text


# ---------------------------------------------------------------------------
# `SurveyReviewService.release_status` / `.release_status_map` / `.is_released`
# — la fuente única de esta comparación (spec §2).
# ---------------------------------------------------------------------------
class TestReleaseStatusHelpers:
    def test_missing_sin_solicitud(self, db_session, make_student, make_process,
                                   seed_phase_defs):
        seed_phase_defs()
        proc = make_process(make_student(), current_phase=2)

        assert SurveyReviewService.release_status(db_session, proc.id) == "missing"
        assert SurveyReviewService.is_released(db_session, proc.id) is False

    @pytest.mark.parametrize("status", ["in_review", "rejected", "approved"])
    def test_devuelve_el_status_real_de_la_solicitud(
        self, db_session, make_student, make_process, seed_phase_defs,
        make_survey_review, status,
    ):
        seed_phase_defs()
        proc = make_process(make_student(), current_phase=2)
        make_survey_review(proc, status=status)

        assert SurveyReviewService.release_status(db_session, proc.id) == status
        assert SurveyReviewService.is_released(db_session, proc.id) is (status == "approved")

    def test_release_status_map_en_lote(self, db_session, make_student, make_process,
                                        seed_phase_defs, make_survey_review):
        """Una sola consulta para varios procesos; los ausentes se completan
        como 'missing' sin necesitar una fila propia."""
        seed_phase_defs()
        con_aprobada = make_process(make_student(last_name="MAPACON"), current_phase=2)
        en_revision = make_process(make_student(last_name="MAPAREV"), current_phase=2)
        sin_solicitud = make_process(make_student(last_name="MAPASIN"), current_phase=2)
        make_survey_review(con_aprobada, status="approved")
        make_survey_review(en_revision, status="in_review")

        mapa = SurveyReviewService.release_status_map(
            db_session, [con_aprobada.id, en_revision.id, sin_solicitud.id])

        assert mapa == {con_aprobada.id: "approved", en_revision.id: "in_review",
                        sin_solicitud.id: "missing"}

    def test_release_status_map_vacio_no_consulta_nada(self, db_session):
        assert SurveyReviewService.release_status_map(db_session, []) == {}


# ---------------------------------------------------------------------------
# La guarda de la fase 2: sufijo por estatus de la encuesta (D3 del plan del
# 2026-09-15). Desde la Tarea 5 del plan 2026-10-01-titulatec-biblioteca-caja
# el estado sale de `ClearanceGate.status` (los mismos cuatro de la encuesta);
# el sufijo del no adeudo lo prueba `test_clearance_gate.py`.
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


# ---------------------------------------------------------------------------
# Review Focus 5 del plan (spec §7.1, D2): GTV revoca la liberación con la
# cita YA agendada -> la cita sigue vigente. Revocar solo muta `SurveyReview`;
# ningún service de citas se entera ni se ejecuta.
# ---------------------------------------------------------------------------
class TestRevocarNoTocaLaCitaVigente:
    def test_revocar_la_liberacion_no_cambia_la_cita_ni_su_vigencia(
        self, db_session, agenda_slots, make_survey_review, make_user,
    ):
        esc = agenda_slots
        _req(db_session, esc["cohort"])
        review = make_survey_review(esc["p1"], status="approved")
        appt = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                         slot_start=time(9, 0), created_by_id=esc["off"].id)
        gtv = make_user(first_name="GTV", last_name="REVOCA")

        with patch(NOTIFY):
            SurveyReviewService.revoke(db_session, review.id, gtv.id, "Se liberó por error")

        db_session.refresh(appt)
        assert appt.is_current is True, "D2: la cita ya agendada no se toca al revocar"
        assert appt.status == "scheduled"

        vigente = AppointmentService.get_for_process(db_session, esc["p1"].id)
        assert vigente is not None and vigente.id == appt.id

        del_dia = {a.id for a in AppointmentService.list_for_day(
            db_session, esc["w"].review_day.date)}
        assert appt.id in del_dia, "la cita sigue en la agenda del día"


# ---------------------------------------------------------------------------
# Ruling R11 (revisión de la Tarea 5, spec 2026-10-01-titulatec-biblioteca-
# caja-design.md): `AppointmentService.reschedule` sobre una cita vigente
# `no_show` abre un intento NUEVO (`SlotService.assign` cierra la fila vieja
# e inserta la siguiente) y por eso debe pasar por el MISMO candado que
# `create` -- antes no lo hacía, ni siquiera revisaba la encuesta. Una cita
# `scheduled`/`confirmed` que se MUEVE no abre un intento nuevo en el sentido
# de D17 y sigue sin pasar por aquí
# (`test_la_cita_ya_agendada_sigue_vigente_y_se_puede_mover`,
# test_clearance_gate.py, sección 4).
# ---------------------------------------------------------------------------
class TestRescheduleDesdeNoShowExigeLiberaciones:
    def test_sin_encuesta_no_reagenda_y_no_abre_intento(
        self, db_session, agenda_slots, make_appointment,
    ):
        esc = agenda_slots
        appt = make_appointment(esc["p1"], status="no_show", is_current=True)

        with pytest.raises(err.SurveyNotSubmitted):
            AppointmentService.reschedule(db_session, appt, window_id=esc["w"].id,
                                          slot_start=time(9, 30), actor_id=esc["off"].id)

        vigente = AppointmentService.get_for_process(db_session, esc["p1"].id)
        assert vigente.id == appt.id and vigente.status == "no_show", (
            "no debió abrir un intento nuevo")

    def test_con_todo_liberado_si_reagenda(
        self, db_session, agenda_slots, make_appointment, make_survey_review,
    ):
        esc = agenda_slots
        make_survey_review(esc["p1"], status="approved")
        appt = make_appointment(esc["p1"], status="no_show", is_current=True)

        movida = AppointmentService.reschedule(db_session, appt, window_id=esc["w"].id,
                                               slot_start=time(9, 30), actor_id=esc["off"].id)

        assert movida.status == "scheduled" and movida.is_current is True
        assert movida.id != appt.id, "reagendar desde no_show abre un intento NUEVO"

    def test_con_biblioteca_pendiente_no_reagenda(
        self, db_session, seed_phase_defs, seed_document_types, make_program,
        make_cohort, make_review_day, make_review_window, make_officer,
        make_student, make_process, make_survey_review, make_appointment,
    ):
        """Con la convocatoria exigiendo el no adeudo (`seed_defaults`) y
        biblioteca `pending`, reagendar desde `no_show` levanta
        `LibraryNotCleared` -- el hueco que cierra R11."""
        from itcj2.apps.titulatec.services.cotejo_requirement_service import (
            CotejoRequirementService,
        )

        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria R11")
        cohort = make_cohort()
        CotejoRequirementService.seed_defaults(db_session, cohort.id, commit=False)
        db_session.flush()
        dia = make_review_day(cohort, day=date(2029, 5, 7))
        officer, pos = make_officer([prog])
        window = make_review_window(dia, officer, start="09:00", end="11:00",
                                    slot=30, cap=1, position=pos)
        proc = make_process(make_student(), cohort=cohort, program=prog,
                            current_phase=2, library_clearance="pending")
        make_survey_review(proc, status="approved")
        appt = make_appointment(proc, status="no_show", is_current=True)

        with pytest.raises(err.LibraryNotCleared) as exc:
            AppointmentService.reschedule(db_session, appt, window_id=window.id,
                                          slot_start=time(9, 30), actor_id=officer.id)

        assert exc.value.status == "pending"
        vigente = AppointmentService.get_for_process(db_session, proc.id)
        assert vigente.id == appt.id


class TestRutaRescheduleDesdeNoShow:
    """El hueco real: `POST .../reschedule` resuelve la vigente con
    `get_for_process` (que SÍ devuelve un `no_show`, sigue siendo vigente
    hasta que algo lo reemplaza) y llama a `AppointmentService.reschedule`
    directo, sin el branch de `pages/appointments.py::move` que para un
    `no_show` -fuera de `_ESTADOS_ACTIVOS`- ya pasaba por `create`."""

    def test_sin_encuesta_400_con_x_tt_error(
        self, client_as, db_session, seed_phase_defs, seed_document_types,
        make_program, make_cohort, make_review_day, make_review_window,
        make_officer, make_student, make_process, make_appointment,
    ):
        seed_phase_defs()
        seed_document_types()
        prog = make_program("Ingenieria R11 Ruta")
        cohort = make_cohort()
        dia = make_review_day(cohort, day=date(2029, 5, 7))
        officer, pos = make_officer(
            [prog], perm_codes=OFFICER_PERMS + ("titulatec.appointment.api.reschedule",))
        window = make_review_window(dia, officer, start="09:00", end="11:00",
                                    slot=30, cap=1, position=pos)
        proc = make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
        appt = make_appointment(proc, status="no_show", is_current=True)

        resp = client_as(officer).post(
            f"/titulatec/admin/appointments/{proc.id}/reschedule",
            data={"window_id": window.id, "slot_start": "09:30"})

        assert resp.status_code == 400, resp.text[:300]
        assert "encuesta de egresados" in _msg(resp)
        vigente = AppointmentService.get_for_process(db_session, proc.id)
        assert vigente.id == appt.id and vigente.status == "no_show"

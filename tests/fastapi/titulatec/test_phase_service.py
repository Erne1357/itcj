"""Tests del motor de fases (PhaseService) — avance, salto y notificaciones.

`TestSkipsYSiguiente` sigue siendo puro (no toca BD). `TestApprovePhase` y
`TestRejectPhase` pasaron de `MagicMock` a la sesion real del harness
(`conftest.py`) porque desde 2026-09 `approve_phase`/`reject_phase` leen el
catalogo de fases para validar la transicion: con un `MagicMock` por `db` la
guarda no se ejerce y el test volveria a ser decorativo. La guarda en si se
prueba en `test_phase_guard.py`.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.phase_service import PhaseService

# Ultima fase del catalogo real (`06_seed_catalogs.sql`: 0-8). Las pruebas puras
# la pasan explicita porque `_next_applicable` ya no la lleva escrita a mano.
LAST_PHASE = 8


@pytest.fixture()
def revisor(make_user):
    """Un revisor que EXISTE en `core_users`.

    Antes era el id 200 a pelo. En la base de dev ese usuario existe y el test
    pasaba; CI arranca de un `create_all` vacío y el FK de
    `titulatec_process_phases.reviewed_by_id` (y el de
    `titulatec_process_events.actor_id`) reventaba. Un id inventado solo prueba
    que la base de quien corre el test tiene a alguien con ese número.
    """
    return make_user(first_name="REVISOR", last_name="DE PRUEBA")


# ───────────────────────────── helpers puros ─────────────────────────────

def _proc(skips=None, current_phase=1):
    modality = SimpleNamespace(skips_phases=skips)
    return SimpleNamespace(id=1, student_id=7, modality=modality,
                           current_phase=current_phase, status="active",
                           completed_at=None)


class TestSkipsYSiguiente:
    def test_skips_desde_json(self):
        assert PhaseService._skips(_proc(skips=[4, 5])) == {4, 5}

    def test_skips_vacio_si_none(self):
        assert PhaseService._skips(_proc(skips=None)) == set()

    def test_skips_vacio_si_invalido(self):
        assert PhaseService._skips(_proc(skips=["x"])) == set()

    def test_siguiente_salta_las_fases_de_la_modalidad(self):
        # tras la fase 3, con 4 y 5 saltadas → 6
        assert PhaseService._next_applicable(_proc(skips=[4, 5]), 3, LAST_PHASE) == 6

    def test_siguiente_none_al_final(self):
        assert PhaseService._next_applicable(_proc(skips=None), 8, LAST_PHASE) is None


# ───────────────────────────── approve_phase ─────────────────────────────

class TestApprovePhase:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_avanza_a_la_siguiente_fase(self, mock_notify, db_session, seed_phase_defs,
                                        make_student, make_process, revisor):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=1)

        result = PhaseService.approve_phase(db_session, process, 1, reviewer_id=revisor.id)

        assert result == {"next_phase": 2, "completed": False}
        assert process.current_phase == 2
        assert process.status == "active"
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["type"] == "PHASE_APPROVED"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_ultima_fase_completa_el_proceso(self, mock_notify, db_session, seed_phase_defs,
                                             make_student, make_process, revisor):
        seed_phase_defs()
        process = make_process(make_student(), current_phase=8)

        result = PhaseService.approve_phase(db_session, process, 8, reviewer_id=revisor.id)

        assert result == {"next_phase": None, "completed": True}
        assert process.status == "completed"
        assert process.completed_at is not None
        assert mock_notify.call_args.kwargs["type"] == "PROCESS_COMPLETED"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_salta_las_fases_de_la_modalidad(self, mock_notify, db_session, seed_phase_defs,
                                             make_student, make_process, make_modality,
                                             revisor):
        """EGEL salta 4 y 5: aprobar la 3 lleva a la 6 y deja las saltadas en 'skipped'."""
        from itcj2.apps.titulatec.models import ProcessPhase

        seed_phase_defs()
        modality = make_modality(name="Modalidad que salta", skips_phases=[4, 5])
        process = make_process(make_student(), modality=modality, current_phase=3)

        result = PhaseService.approve_phase(db_session, process, 3, reviewer_id=revisor.id)

        assert result == {"next_phase": 6, "completed": False}
        assert process.current_phase == 6
        estados = {p.phase_number: p.status for p in
                   db_session.query(ProcessPhase).filter_by(process_id=process.id).all()}
        assert estados[4] == "skipped"
        assert estados[5] == "skipped"
        assert estados[6] == "in_progress"


# ───────────────────────────── reject_phase ──────────────────────────────

class TestRejectPhase:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechaza_y_notifica_con_motivo(self, mock_notify, db_session, seed_phase_defs,
                                           make_student, make_process, revisor):
        """Rechazar la fase ACTUAL la deja en 'rejected' para que el alumno corrija.

        Hasta 2026-09 este test rechazaba la fase 2 de un proceso parado en la 3 y
        afirmaba que `current_phase` bajaba a 2: fosilizaba justo el defecto que
        `test_phase_guard.py` documenta (un POST podia mover el proceso a cualquier
        fase). El escenario real es rechazar la fase en curso.
        """
        from itcj2.apps.titulatec.models import ProcessPhase

        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)

        PhaseService.reject_phase(db_session, process, 2, reviewer_id=revisor.id,
                                  reason="Faltan firmas")

        assert process.current_phase == 2
        fase2 = (db_session.query(ProcessPhase)
                 .filter_by(process_id=process.id, phase_number=2).one())
        assert fase2.status == "rejected"
        assert fase2.rejection_reason == "Faltan firmas"
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["type"] == "PHASE_REJECTED"
        assert kwargs["phase_number"] == 2
        assert "Faltan firmas" in kwargs["body"]


# ──────────────── auto-cierre de la cita de cotejo (Tarea B2) ────────────
# Hueco: desde el expediente se podia aprobar O RECHAZAR la fase 02 con la
# cita vigente todavia `in_progress` -el encargado la atiende y se le olvida
# marcar "Asistio" antes de dictaminar-. Esa cita no aparecia en ningun cubo
# de la cola (no es `no_show` ni `attended`) y D4 bloqueaba volver a agendar
# (una cita ACTIVA es la unica que lo impide): quedaba colgada para siempre.
# `PhaseService._auto_close_cotejo_appointment` la cierra a `attended` dentro
# de la MISMA transaccion del dictamen, sin pasar por `mark_attended` (que
# commitea por su cuenta).

class TestAutoCloseCotejoAppointment:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_aprobar_cierra_la_cita_in_progress_a_attended(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_process, make_appointment, revisor):
        from itcj2.apps.titulatec.models import ProcessEvent

        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)
        appt = make_appointment(process, status="in_progress")

        PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert appt.status == "attended"
        ev = (db_session.query(ProcessEvent)
              .filter_by(process_id=process.id, event_type="appointment_attended").one())
        assert ev.phase_number == 2
        assert ev.payload == {"auto": True, "via": "phase_approved"}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_rechazar_cierra_la_cita_in_progress_a_attended(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_process, make_appointment, revisor):
        from itcj2.apps.titulatec.models import ProcessEvent

        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)
        appt = make_appointment(process, status="in_progress")

        PhaseService.reject_phase(db_session, process, 2, reviewer_id=revisor.id,
                                  reason="Le falto el acta certificada.")

        assert appt.status == "attended"
        ev = (db_session.query(ProcessEvent)
              .filter_by(process_id=process.id, event_type="appointment_attended").one())
        assert ev.phase_number == 2
        assert ev.payload == {"auto": True, "via": "phase_rejected"}

    @pytest.mark.parametrize("estado", ["scheduled", "confirmed", "no_show", "attended"])
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_no_toca_citas_que_no_estan_in_progress(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_process, make_appointment, revisor, estado):
        from itcj2.apps.titulatec.models import ProcessEvent

        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)
        appt = make_appointment(process, status=estado)

        PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert appt.status == estado, "el auto-cierre solo toca `in_progress`"
        assert db_session.query(ProcessEvent).filter_by(
            process_id=process.id, event_type="appointment_attended").first() is None

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_sin_cita_no_revienta(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_process, revisor):
        """Dictaminar la fase 02 sin ninguna cita agendada no debe fallar."""
        seed_phase_defs()
        process = make_process(make_student(), current_phase=2)

        result = PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert result == {"next_phase": 3, "completed": False}

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_bloqueado_por_requisitos_faltantes_no_toca_la_cita(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_cohort, make_process, make_appointment, revisor):
        """La guarda de fase 2 (checklist, ver `test_phase2_cotejo_gate.py`)
        corre ANTES del auto-cierre: si aprobar falla, no se escribe nada -la
        cita sigue `in_progress`-, mismo contrato que el resto de las guardas.
        """
        from itcj2.apps.titulatec.models import CotejoRequirement, ProcessEvent

        seed_phase_defs()
        cohort = make_cohort()
        process = make_process(make_student(), cohort=cohort, current_phase=2)
        appt = make_appointment(process, status="in_progress")
        db_session.add(CotejoRequirement(
            cohort_id=cohort.id, label="12 fotografias", icon="check2-square",
            is_required=True, is_active=True, order_index=0))
        db_session.flush()

        with pytest.raises(ValueError):
            PhaseService.approve_phase(db_session, process, 2, reviewer_id=revisor.id)

        assert appt.status == "in_progress"
        assert db_session.query(ProcessEvent).filter_by(
            process_id=process.id, event_type="appointment_attended").first() is None

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_solo_aplica_a_la_fase_2(
            self, mock_notify, db_session, seed_phase_defs, make_student,
            make_process, make_appointment, revisor):
        """Dictaminar otra fase no debe tocar una cita de cotejo `in_progress`
        colgada del mismo proceso: el auto-cierre es EXCLUSIVO de la fase 02."""
        from itcj2.apps.titulatec.models import ProcessEvent

        seed_phase_defs()
        process = make_process(make_student(), current_phase=1)
        appt = make_appointment(process, status="in_progress")

        PhaseService.approve_phase(db_session, process, 1, reviewer_id=revisor.id)

        assert appt.status == "in_progress"
        assert db_session.query(ProcessEvent).filter_by(
            process_id=process.id, event_type="appointment_attended").first() is None

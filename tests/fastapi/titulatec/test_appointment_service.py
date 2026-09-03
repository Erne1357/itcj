"""Tests de AppointmentService — confirmación, solicitud de cambio y notificaciones."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.appointment_service import AppointmentService


class TestSolicitudDeCambio:
    """La solicitud del alumno vive en columna propia, no en un prefijo mágico.

    Con el prefijo dentro de `note`, tanto `create` como `reschedule` hacían
    `appt.note = note` y **la pisaban**: la petición se perdía justo al
    atenderla. Y una nota operativa que empezara con «[CAMBIO] » se leía como
    solicitud del alumno.
    """

    def test_solicitar_cambio_escribe_la_columna_y_su_fecha(self, db_session,
                                                            make_student, make_process,
                                                            make_appointment,
                                                            seed_phase_defs):
        seed_phase_defs()
        proc = make_process(make_student(), current_phase=2)
        appt = make_appointment(proc, status="scheduled")

        AppointmentService.request_change(db_session, appt, actor_id=proc.student_id,
                                          reason="tengo examen")

        assert appt.change_request == "tengo examen"
        assert appt.change_requested_at is not None
        assert appt.note is None, "la solicitud ya no invade `note`"

    def test_sin_motivo_queda_un_texto_util(self, db_session, make_student,
                                            make_process, make_appointment,
                                            seed_phase_defs):
        seed_phase_defs()
        proc = make_process(make_student(), current_phase=2)
        appt = make_appointment(proc, status="scheduled")

        AppointmentService.request_change(db_session, appt, actor_id=proc.student_id,
                                          reason=None)

        assert appt.change_request == "Sin motivo"

    def test_una_nota_operativa_no_se_confunde_con_una_solicitud(self, db_session,
                                                                 make_student,
                                                                 make_process,
                                                                 make_appointment,
                                                                 seed_phase_defs):
        seed_phase_defs()
        proc = make_process(make_student(), current_phase=2)
        appt = make_appointment(proc, status="scheduled", note="[CAMBIO] de edificio")

        assert appt.change_request is None


class TestConfirm:
    def test_confirma_y_sella_fecha(self):
        db = MagicMock()
        appt = MagicMock(status="scheduled", process_id=1, confirmed_at=None)

        AppointmentService.confirm(db, appt, actor_id=7)

        assert appt.status == "confirmed"
        assert appt.confirmed_at is not None
        db.commit.assert_called_once()


class TestNotificacionDeCita:
    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_notifica_al_alumno_con_fecha_y_lugar(self, mock_notify):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(student_id=7)

        AppointmentService._notify_appt(
            db, process_id=1, ntype="APPOINTMENT_SCHEDULED",
            title="Tu cita fue agendada",
            scheduled_at=datetime(2026, 6, 10, 11, 30), location="Edificio A",
        )

        kwargs = mock_notify.call_args.kwargs
        assert kwargs["type"] == "APPOINTMENT_SCHEDULED"
        assert kwargs["phase_number"] == 2
        assert "10 jun 2026 · 11:30" in kwargs["body"]
        assert "Edificio A" in kwargs["body"]

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_no_notifica_si_no_hay_proceso(self, mock_notify):
        db = MagicMock()
        db.get.return_value = None
        AppointmentService._notify_appt(
            db, process_id=99, ntype="X", title="t",
            scheduled_at=datetime(2026, 1, 1, 9, 0), location=None,
        )
        mock_notify.assert_not_called()

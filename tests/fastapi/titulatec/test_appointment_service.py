"""Tests de AppointmentService — confirmación, solicitud de cambio y notificaciones."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.appointment_service import (
    AppointmentService, CHANGE_REQUEST_PREFIX,
)


class TestSolicitudDeCambio:
    def test_detecta_solicitud_por_prefijo(self):
        appt = SimpleNamespace(note=CHANGE_REQUEST_PREFIX + "tengo examen")
        assert AppointmentService.has_change_request(appt) is True
        assert AppointmentService.change_request_text(appt) == "tengo examen"

    def test_sin_solicitud(self):
        assert AppointmentService.has_change_request(SimpleNamespace(note=None)) is False
        assert AppointmentService.has_change_request(SimpleNamespace(note="Edificio A")) is False
        assert AppointmentService.change_request_text(SimpleNamespace(note="x")) is None


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

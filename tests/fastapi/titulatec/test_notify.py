"""Tests del helper de notificaciones in-app de TitulaTec."""
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.apps.titulatec.services.notify import notify_student


@patch("itcj2.core.services.notification_service.NotificationService.create")
def test_notify_student_con_fase_enlaza_a_la_fase(mock_create):
    db = MagicMock()
    notify_student(db, 7, type="PHASE_APPROVED", title="Avanzaste de fase",
                   body="Fase 02 aprobada", process_id=3, phase_number=4)

    assert mock_create.call_count == 1
    kwargs = mock_create.call_args.kwargs
    assert kwargs["app_name"] == "titulatec"
    assert kwargs["user_id"] == 7
    assert kwargs["type"] == "PHASE_APPROVED"
    assert kwargs["data"]["url"] == "/titulatec/student/fase/4"
    assert kwargs["data"]["process_id"] == 3
    assert kwargs["data"]["phase_number"] == 4


@patch("itcj2.core.services.notification_service.NotificationService.create")
def test_notify_student_sin_fase_enlaza_al_dashboard(mock_create):
    db = MagicMock()
    notify_student(db, 7, type="PROCESS_COMPLETED", title="Completado", process_id=3)

    kwargs = mock_create.call_args.kwargs
    assert kwargs["data"]["url"] == "/titulatec/student/dashboard"
    assert kwargs["data"]["phase_number"] is None


@patch("itcj2.core.services.notification_service.NotificationService.create",
       side_effect=RuntimeError("boom"))
def test_notify_student_es_best_effort(mock_create):
    """Si la creación falla, no debe propagar la excepción (no rompe el flujo)."""
    db = MagicMock()
    notify_student(db, 7, type="X", title="t", process_id=1, phase_number=1)
    assert mock_create.call_count == 1

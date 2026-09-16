"""Contrato de ESQUEMA del historial de intentos de `ReviewAppointment`
(Tarea 1, auto-agendado de cotejo).

Cubre solo el indice UNICO PARCIAL `uq_titulatec_review_appt_current`: como
mucho una cita VIGENTE (`is_current`) por proceso. Abrir un intento nuevo
(reagendar, no-show, cancelar) es logica de `SlotService`/`AppointmentService`
(tareas aparte); aqui solo se prueba que la base lo hace cumplir.

Patron para la violacion de constraint: `with db_session.begin_nested():`. Un
`db_session.rollback()` pelado descarta tambien las filas que sembraron las
fixtures (`join_transaction_mode="create_savepoint"`, ver conftest); el
savepoint anidado solo descarta el INSERT que fallo. Ver
`test_review_window_model.py`.
"""
import pytest
from sqlalchemy.exc import IntegrityError


def test_como_mucho_una_cita_vigente_por_proceso(
        db_session, make_student, make_process, make_appointment, seed_phase_defs):
    """Dos filas `is_current=True` del mismo proceso chocan; con la segunda
    en `is_current=False` (intento superado, no vigente), pasa."""
    from itcj2.apps.titulatec.models import ReviewAppointment

    seed_phase_defs()
    proc = make_process(make_student(), current_phase=2)
    primera = make_appointment(proc, status="scheduled")
    assert primera.is_current is True         # server_default

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_appointment(proc, status="scheduled")   # is_current=True por default -> choca

    segunda = ReviewAppointment(
        process_id=proc.id,
        scheduled_at=primera.scheduled_at,
        status="scheduled",
        is_current=False,
        attempt_no=2,
        created_by_id=proc.student_id,
    )
    db_session.add(segunda)
    db_session.flush()          # is_current=False no choca con el indice parcial

    assert segunda.is_current is False

"""Historial de intentos de `ReviewAppointment` (auto-agendado de cotejo).

Tarea 1 dejo el CONTRATO DE ESQUEMA: el indice UNICO PARCIAL
`uq_titulatec_review_appt_current` (como mucho una cita VIGENTE por proceso).
Tarea 2 (este archivo, ampliado) cubre la LOGICA que lo respeta: `SlotService
.assign` ya no sobrescribe la cita existente — cierra la vigente (a
`superseded` si estaba activa; conserva su status si no, p. ej. `no_show`) e
inserta un intento nuevo con `attempt_no+1`. Es el arreglo del defecto de la
spec 2026-09-15 S0: reagendar a alguien marcado `no_show` movia su fila y por
lo tanto liberaba la franja que ya habia consumido, en contra de D10.

Patron para la violacion de constraint: `with db_session.begin_nested():`. Un
`db_session.rollback()` pelado descarta tambien las filas que sembraron las
fixtures (`join_transaction_mode="create_savepoint"`, ver conftest); el
savepoint anidado solo descarta el INSERT que fallo. Ver
`test_review_window_model.py`.
"""
from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.slot_service import SlotService


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


# --------------------------------------------------------- SlotService.assign
def test_reagendar_supera_la_cita_activa(db_session, agenda_slots):
    """Reagendar (`assign` de nuevo sobre el mismo proceso) no mueve la fila:
    la vieja pasa a `superseded` + `is_current=False`, y la nueva nace
    vigente con `attempt_no+1`."""
    esc = agenda_slots
    primera = SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    segunda = SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)

    assert primera.status == "superseded"
    assert primera.is_current is False
    assert segunda.status == "scheduled"
    assert segunda.is_current is True
    assert segunda.attempt_no == 2
    assert segunda.id != primera.id


def test_intento_nuevo_tras_no_show_conserva_el_estado(db_session, agenda_slots):
    """El no_show no es una transicion que `assign` deba pisar: la fila vieja
    se queda diciendo `no_show` (D7/D10), solo pierde `is_current`."""
    esc = agenda_slots
    primera = SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    primera.status = "no_show"
    db_session.flush()

    segunda = SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)

    assert primera.status == "no_show"         # NO se reescribe a superseded
    assert primera.is_current is False
    assert segunda.status == "scheduled"
    assert segunda.is_current is True
    assert segunda.attempt_no == 2


def test_tras_tres_intentos_solo_hay_una_vigente(db_session, agenda_slots):
    from itcj2.apps.titulatec.models import ReviewAppointment
    esc = agenda_slots
    SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)
    tercera = SlotService.assign(db_session, esc["w"].id, time(10, 0), esc["p1"].id, esc["off"].id)

    filas = (db_session.query(ReviewAppointment)
             .filter_by(process_id=esc["p1"].id).all())
    assert len(filas) == 3
    assert [a for a in filas if a.is_current] == [tercera]
    assert tercera.attempt_no == 3


def test_attempt_no_sigue_creciendo_aunque_no_haya_vigente(
        db_session, agenda_slots, make_appointment):
    """`attempt_no` sale de `max(attempt_no) del proceso`, no de `vigente
    .attempt_no + 1`: tras un intento historico ya cerrado (is_current=False,
    p. ej. una cancelacion) que NO deja ninguna vigente, `assign` tiene que
    seguir contando desde el maximo real y no reiniciar en 1."""
    esc = agenda_slots
    make_appointment(esc["p1"], status="cancelled", is_current=False, attempt_no=1)

    nueva = SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)

    assert nueva.attempt_no == 2
    assert nueva.is_current is True


def test_el_no_show_sigue_ocupando_su_franja_despues_de_reagendar(db_session, agenda_slots):
    """El defecto de la spec S0, convertido en regresor: reagendar a un
    `no_show` NO puede liberar la franja que ya consumio (D10)."""
    esc = agenda_slots
    primera = SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p1"].id, esc["off"].id)
    primera.status = "no_show"
    db_session.flush()

    SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id, esc["off"].id)

    ocup = SlotService.occupancy(db_session, esc["w"])
    assert ocup.get(time(9, 0)) == 1            # la franja ORIGINAL sigue ocupada
    with pytest.raises(err.SlotFull):
        SlotService.assign(db_session, esc["w"].id, time(9, 0), esc["p2"].id, esc["off"].id)

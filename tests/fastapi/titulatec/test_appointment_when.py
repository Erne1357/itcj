"""`AppointmentService.when(appt)`: el único formato de «cuándo es la cita»,
con su variante sin horario (D11, spec 2026-09-29-titulatec-cotejo-espacios-
design.md §6, Tarea 5).

Cubre el Step 1 del brief: una cita con hora normal, una reserva sin horario
(D3) y la regla de legado (Review Focus 3) — una cita que un encargado sentó
a mano a las 10:30 DENTRO de un `walkin` sigue anunciando su propia hora,
nunca el rango; la decide `SlotService.is_walkin_reservation` (Tarea 2), no
este helper. También cubre el cuerpo del aviso in-app (`_notify_appt`), que
ahora se arma con `when(appt)["label"]` + el lugar.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

import itcj2.models  # noqa: F401

_D = date(2029, 5, 7)          # lunes — mismo día que usan agenda_slots / test_walkin_core


@pytest.fixture()
def reloj(monkeypatch):
    """Fija `dates_es.db_now` (lo que lee `dia_largo` para decidir si la fecha
    lleva año) a un año DISTINTO del de la cita, para que «de 2029» sea
    determinista sin depender del año en curso. Mismo truco que
    `test_mail_compose.py::reloj`."""
    def _fijar(ahora=datetime(2028, 1, 1, 9, 0)):
        monkeypatch.setattr("itcj2.apps.titulatec.utils.dates_es.db_now", lambda: ahora)
        return ahora

    return _fijar


@pytest.fixture()
def esc(make_program, make_cohort, make_review_day, make_officer, make_student,
        make_process):
    """Un día de cotejo con un encargado y un proceso; cada test crea la
    ventana que necesita (bookable o walkin)."""
    prog = make_program("Ingenieria del Helper Cuando")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])
    proc = make_process(make_student(), cohort=cohort, program=prog, current_phase=2)
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos,
            "p": proc}


# ---------------------------------------------------------------------------
# Step 1: bookable, reserva walkin, legado (Review Focus 3)
# ---------------------------------------------------------------------------
def test_cita_con_hora_normal(db_session, esc, make_review_window, reloj):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    reloj()
    w = make_review_window(esc["dia"], esc["off"], start="09:00", end="11:00",
                           slot=30, cap=1, position=esc["pos"], visibility="bookable")
    appt = SlotService.assign(db_session, w.id, time(9, 30), esc["p"].id, esc["off"].id)

    assert AppointmentService.when(appt) == {
        "fecha": "lunes 7 de mayo de 2029",
        "fecha_corta": "07 may 2029",
        "hora": "09:30",
        "sin_horario": False,
        "label": "07 may 2029 · 09:30",
    }


def test_reserva_sin_horario_lleva_el_rango_de_la_ventana(db_session, esc,
                                                          make_review_window, reloj):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    reloj()
    w = make_review_window(esc["dia"], esc["off"], start="08:00", end="14:00",
                           slot=30, cap=3, position=esc["pos"], visibility="walkin")
    appt = SlotService.assign(db_session, w.id, time(8, 0), esc["p"].id, esc["off"].id)

    assert AppointmentService.when(appt) == {
        "fecha": "lunes 7 de mayo de 2029",
        "fecha_corta": "07 may 2029",
        "hora": "de 08:00 a 14:00",
        "sin_horario": True,
        "label": "07 may 2029 · de 08:00 a 14:00",
    }


def test_legado_a_las_1030_en_walkin_conserva_su_hora(db_session, esc, make_review_window,
                                                       make_appointment, reloj):
    """Review Focus 3: una cita sentada a mano a las 10:30 DENTRO de un
    `walkin` se anuncia «10:30», no el rango — sigue ocupando su lugar
    (`slot_service`) y aquí sigue hablando de su propia hora."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj()
    w = make_review_window(esc["dia"], esc["off"], start="08:00", end="14:00",
                           slot=30, cap=3, position=esc["pos"], visibility="walkin")
    appt = make_appointment(esc["p"], when=datetime.combine(_D, time(10, 30)))
    appt.window = w
    db_session.flush()

    assert AppointmentService.when(appt) == {
        "fecha": "lunes 7 de mayo de 2029",
        "fecha_corta": "07 may 2029",
        "hora": "10:30",
        "sin_horario": False,
        "label": "07 may 2029 · 10:30",
    }


def test_sin_ventana_no_es_sin_horario(db_session, esc, make_appointment, reloj):
    """Cita heredada sin `window_id` (de antes de que existieran las
    ventanas, §6): sin ventana no hay regla de legado que aplicar, así que
    nunca es sin horario."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    reloj()
    appt = make_appointment(esc["p"], when=datetime.combine(_D, time(8, 0)))

    info = AppointmentService.when(appt)

    assert info["sin_horario"] is False
    assert info["hora"] == "08:00"


# ---------------------------------------------------------------------------
# `_notify_appt`: el aviso in-app se arma con `when(appt)["label"]` + lugar
# ---------------------------------------------------------------------------
def _avisos(db, user_id, tipo):
    from itcj2.core.models.notification import Notification

    db.flush()
    return (db.query(Notification)
            .filter_by(user_id=user_id, app_name="titulatec", type=tipo)
            .order_by(Notification.id).all())


def test_notify_appt_en_sin_horario_avisa_con_el_rango(db_session, esc, make_review_window,
                                                        reloj):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    reloj()
    w = make_review_window(esc["dia"], esc["off"], start="08:00", end="14:00",
                           slot=30, cap=3, position=esc["pos"], visibility="walkin",
                           location="Sala de cotejo")
    appt = SlotService.assign(db_session, w.id, time(8, 0), esc["p"].id, esc["off"].id,
                              location="Sala de cotejo")

    AppointmentService._notify_appt(db_session, esc["p"].id, "APPOINTMENT_SCHEDULED",
                                    "Tu cita de cotejo fue agendada", appt)

    (aviso,) = _avisos(db_session, esc["p"].student_id, "APPOINTMENT_SCHEDULED")
    assert aviso.body == "07 may 2029 · de 08:00 a 14:00 · Sala de cotejo"


def test_notify_appt_sin_lugar_no_deja_separador_colgado(db_session, esc,
                                                          make_review_window, reloj):
    """El mismo `if location` de siempre: sin lugar, el cuerpo termina en la
    hora, no en un « · » vacío."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    reloj()
    w = make_review_window(esc["dia"], esc["off"], start="09:00", end="11:00",
                           slot=30, cap=1, position=esc["pos"], visibility="bookable")
    appt = SlotService.assign(db_session, w.id, time(9, 0), esc["p"].id, esc["off"].id,
                              location=None)

    AppointmentService._notify_appt(db_session, esc["p"].id, "APPOINTMENT_SCHEDULED",
                                    "Tu cita de cotejo fue agendada", appt)

    (aviso,) = _avisos(db_session, esc["p"].student_id, "APPOINTMENT_SCHEDULED")
    assert aviso.body == "07 may 2029 · 09:00"

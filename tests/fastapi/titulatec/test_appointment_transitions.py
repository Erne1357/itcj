"""Matriz de transiciones de la cita, y el fin del no-op silencioso.

Antes ningún método miraba el estado previo. Consecuencias reales, todas
alcanzables desde la UI con un clic:

  * `no_show -> attended`: un alumno marcado como ausente pasaba a «asistió» sin
    que quedara rastro de la corrección;
  * `scheduled -> attended`: se saltaba el cotejo entero;
  * `attended -> lo que fuera`: una cita concluida seguía siendo editable.

Y por el otro lado, `create`/`reschedule` estaban condicionados a que la fecha se
hubiera podido parsear (`if dt:`), así que sin hora la ruta respondía **200 con
el cuerpo re-renderizado y sin escribir nada**. Reproducido el 2026-09-03:
HTTP 200, sin `X-Tt-Error`, cero filas creadas.
"""
from datetime import time

import pytest

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService

LEGALES = [
    ("scheduled", "confirmed"), ("scheduled", "in_progress"), ("scheduled", "no_show"),
    ("confirmed", "in_progress"), ("confirmed", "no_show"),
    ("in_progress", "attended"), ("in_progress", "no_show"),
    ("no_show", "in_progress"),                      # «Deshacer no se presentó»
    ("scheduled", "scheduled"), ("confirmed", "scheduled"),
    ("in_progress", "scheduled"), ("no_show", "scheduled"),   # reagendar
]

ILEGALES = [
    ("no_show", "attended"),
    ("scheduled", "attended"),
    ("confirmed", "attended"),
    ("attended", "in_progress"),
    ("attended", "no_show"),
    ("attended", "scheduled"),
    ("attended", "confirmed"),
    ("attended", "attended"),
]


@pytest.mark.parametrize("desde,hacia", LEGALES)
def test_transiciones_legales(desde, hacia):
    AppointmentService.assert_transition(desde, hacia)          # no levanta


@pytest.mark.parametrize("desde,hacia", ILEGALES)
def test_transiciones_ilegales(desde, hacia):
    with pytest.raises(err.InvalidTransition):
        AppointmentService.assert_transition(desde, hacia)


def test_attended_es_terminal():
    for hacia in ("scheduled", "confirmed", "in_progress", "no_show", "attended"):
        with pytest.raises(err.InvalidTransition):
            AppointmentService.assert_transition("attended", hacia)


def test_el_error_de_transicion_refresca_la_vista():
    """htmx no swappea en 4xx. Si otro encargado ya movió la cita, el usuario
    tiene que ver el estado nuevo, no quedarse con la pantalla vieja."""
    e = err.InvalidTransition(desde="attended", hacia="no_show")
    assert e.refresca_la_vista is True
    assert "asistió" in str(e)


# ---------------------------------------------------------------- integración
def test_marcar_asistio_desde_no_show_se_rechaza(db_session, agenda_slots):
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.mark_attended(db_session, ap, esc["off"].id)
    assert ap.status == "no_show"


def test_deshacer_no_se_presento_devuelve_la_cita_a_en_proceso(db_session, agenda_slots):
    """Marcar una ausencia le dispara notificación al egresado. Un clic de más
    en una mañana de prisa tenía que poder corregirse."""
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    AppointmentService.undo_no_show(db_session, ap, esc["off"].id)

    assert ap.status == "in_progress"
    AppointmentService.mark_attended(db_session, ap, esc["off"].id)
    assert ap.status == "attended"


def test_no_se_puede_reagendar_una_cita_atendida(db_session, agenda_slots):
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)
    AppointmentService.mark_attended(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(9, 30), actor_id=esc["off"].id)


def test_agendar_encima_de_una_cita_atendida_tampoco(db_session, agenda_slots):
    """`create` sobre un proceso que ya tiene cita es un movimiento disfrazado."""
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)
    AppointmentService.mark_attended(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(10, 0), created_by_id=esc["off"].id)


# ---------------------------------------------------- guards que estaban fuera
def test_sin_franja_es_error_explicito_y_no_un_200_mudo(db_session, agenda_slots):
    esc = agenda_slots
    with pytest.raises(err.MissingSchedule):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=None, created_by_id=esc["off"].id)


def test_el_guard_de_dia_vive_en_el_service(db_session, agenda_slots):
    """Vivía en `pages/`, así que cualquier otro llamador escribía sin validar."""
    esc = agenda_slots
    esc["dia"].is_closed = True
    db_session.flush()

    with pytest.raises(err.DayNotAllowed):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)


def test_reagendar_no_pisa_la_solicitud_de_cambio(db_session, agenda_slots):
    """Defecto (a): `reschedule` hacía `appt.note = note` y borraba la petición
    del alumno justo cuando el encargado la estaba atendiendo."""
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.request_change(db_session, ap, esc["p1"].student_id,
                                      "tengo examen ese dia")

    AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                  slot_start=time(9, 30), actor_id=esc["off"].id)

    assert ap.change_request == "tengo examen ese dia"
    assert ap.scheduled_at.time() == time(9, 30)
    assert ap.status == "scheduled"


def test_reagendar_limpia_la_confirmacion(db_session, agenda_slots):
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.confirm(db_session, ap, esc["p1"].student_id)
    assert ap.confirmed_at is not None

    AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                  slot_start=time(10, 0), actor_id=esc["off"].id)

    assert ap.confirmed_at is None
    assert ap.status == "scheduled"


# ------------------------------------------------------------------ los cubos
def test_el_no_show_no_vuelve_a_por_agendar(db_session, agenda_slots):
    """Decisión del usuario: su lugar no se libera. Y como conserva su cita,
    tampoco puede aparecer entre los que nunca tuvieron una."""
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    pendientes = AppointmentService.list_pending_processes(
        db_session, allowed_program_ids={esc["prog"].id})
    assert esc["p1"].id not in [p.id for p in pendientes]


def test_el_no_show_sale_en_su_propio_cubo(db_session, agenda_slots):
    """«Reagendar (N)», separado de «Por agendar (N)»: en uno el alumno ya tuvo
    su lugar y no llegó; en el otro nunca lo tuvo. Mezclarlos haría que el
    contador dejara de significar una sola cosa."""
    esc = agenda_slots
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    reagendar = AppointmentService.list_reschedule_processes(
        db_session, allowed_program_ids={esc["prog"].id})
    assert esc["p1"].id in [p.id for p in reagendar]


def test_la_busqueda_encuentra_por_control_y_por_nombre(db_session, agenda_slots):
    esc = agenda_slots
    AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                              slot_start=time(9, 0), created_by_id=esc["off"].id)
    from itcj2.core.models.user import User
    alumno = db_session.get(User, esc["p1"].student_id)

    por_control = AppointmentService.list_appointments(
        db_session, allowed_program_ids={esc["prog"].id}, q=alumno.control_number)
    assert [a.process_id for a in por_control] == [esc["p1"].id]

    por_nombre = AppointmentService.list_appointments(
        db_session, allowed_program_ids={esc["prog"].id}, q=alumno.first_name)
    assert esc["p1"].id in [a.process_id for a in por_nombre]

    vacia = AppointmentService.list_appointments(
        db_session, allowed_program_ids={esc["prog"].id}, q="zzzz-no-existe")
    assert vacia == []

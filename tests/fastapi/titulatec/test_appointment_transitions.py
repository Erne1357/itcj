"""Matriz de transiciones de la cita, cancelacion y vigencia.

Antes ningun metodo miraba el estado previo. Consecuencias reales, todas
alcanzables desde la UI con un clic:

  * `no_show -> attended`: un alumno marcado como ausente pasaba a «asistio» sin
    que quedara rastro de la correccion;
  * `scheduled -> attended`: se saltaba el cotejo entero;
  * `attended -> lo que fuera`: una cita concluida seguia siendo editable.

Y por el otro lado, `create`/`reschedule` estaban condicionados a que la fecha se
hubiera podido parsear (`if dt:`), asi que sin hora la ruta respondia **200 con
el cuerpo re-renderizado y sin escribir nada**. Reproducido el 2026-09-03:
HTTP 200, sin `X-Tt-Error`, cero filas creadas.

LO QUE CAMBIA CON EL HISTORIAL DE INTENTOS (spec 2026-09-15 §2.2/§2.3)
----------------------------------------------------------------------
El dominio pasa de 5 a 7 estados (`cancelled`, `superseded`) y **`scheduled`
deja de ser destino de ninguna transicion**: abrir un intento nuevo ya no es
una mutacion de la fila, es una fila nueva. Por eso desaparecen los cuatro
casos `* -> scheduled` de la matriz vieja.

`is_current` es un eje **ORTOGONAL** a `status`, y confundirlos es el error
facil: un `no_show` que deja de ser la cita vigente **conserva su status y su
franja** (D7/D10), solo pierde `is_current`. Lo unico que pasa a `superseded`
es una cita ACTIVA a la que se le abre un intento nuevo encima.

Consecuencia directa para los tests de reagendado de este archivo: tras
`reschedule` la variable que el test traia apunta a la fila **vieja, ya
superada**, que conserva su hora original y su `confirmed_at`. Lo que hay que
afirmar es sobre la cita **vigente**, que es una fila distinta.
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.appointment_service import AppointmentService


@pytest.fixture()
def agenda_slots_survey(agenda_slots, make_survey_review):
    """`agenda_slots`, con la encuesta de egresados YA ENVIADA para `p1`.

    Tarea 4 (D2): `AppointmentService.create` exige una solicitud
    (`SurveyReview`) para agendar. Este archivo mide transiciones y guardas de
    horario, no la puerta de la encuesta, así que se siembra aquí para que
    cada `create(...)` de la matriz siga probando lo que probaba.
    """
    make_survey_review(agenda_slots["p1"])
    return agenda_slots


def _vigente(db, proc):
    return AppointmentService.get_for_process(db, proc.id)


# ---------------------------------------------------------------- la matriz
# Tabla de §2.3 de la spec, literal. `scheduled` NO aparece como destino en
# ninguna fila: reagendar dejo de ser una transicion.
LEGALES = [
    ("scheduled", "confirmed"), ("scheduled", "in_progress"),
    ("scheduled", "no_show"), ("scheduled", "cancelled"), ("scheduled", "superseded"),
    ("confirmed", "in_progress"), ("confirmed", "no_show"),
    ("confirmed", "cancelled"), ("confirmed", "superseded"),
    ("in_progress", "attended"), ("in_progress", "no_show"),
    ("no_show", "in_progress"),                      # «Deshacer no se presentó»
]

ILEGALES = [
    ("no_show", "attended"),
    ("scheduled", "attended"),
    ("confirmed", "attended"),
    ("attended", "in_progress"),
    ("attended", "no_show"),
    ("attended", "confirmed"),
    ("attended", "attended"),
    # Los cuatro que dejaron de ser transiciones: abrir un intento nuevo crea
    # una fila, no reescribe la que habia.
    ("scheduled", "scheduled"), ("confirmed", "scheduled"),
    ("in_progress", "scheduled"), ("no_show", "scheduled"),
    # Un cotejo empezado se cierra con `attended` o con `no_show`, nunca
    # cancelandolo ni moviendolo (spec §2.3).
    ("in_progress", "cancelled"), ("in_progress", "superseded"),
    ("no_show", "cancelled"), ("no_show", "superseded"),
]


@pytest.mark.parametrize("desde,hacia", LEGALES)
def test_transiciones_legales(desde, hacia):
    AppointmentService.assert_transition(desde, hacia)          # no levanta


@pytest.mark.parametrize("desde,hacia", ILEGALES)
def test_transiciones_ilegales(desde, hacia):
    with pytest.raises(err.InvalidTransition):
        AppointmentService.assert_transition(desde, hacia)


TERMINALES = ["attended", "cancelled", "superseded"]


@pytest.mark.parametrize("terminal", TERMINALES)
def test_los_tres_estados_terminales_no_van_a_ningun_lado(terminal):
    """`attended` ya lo era; `cancelled` y `superseded` nacen terminales.

    Una cita superada la hereda su intento siguiente y una cancelada ya
    devolvio su lugar al pozo: reanimar cualquiera de las dos dejaria dos
    filas disputandose la misma franja.
    """
    for hacia in ("scheduled", "confirmed", "in_progress", "no_show",
                  "attended", "cancelled", "superseded"):
        with pytest.raises(err.InvalidTransition):
            AppointmentService.assert_transition(terminal, hacia)


def test_el_error_de_transicion_refresca_la_vista():
    """htmx no swappea en 4xx. Si otro encargado ya movió la cita, el usuario
    tiene que ver el estado nuevo, no quedarse con la pantalla vieja."""
    e = err.InvalidTransition(desde="attended", hacia="no_show")
    assert e.refresca_la_vista is True
    assert "asistió" in str(e)


def test_el_conflicto_de_cita_activa_tambien_refresca_la_vista():
    """El hermano que faltaba del de arriba.

    `AppointmentConflict` es lo que produce un doble clic en «Agendar»: ahí la
    pantalla SÍ está rancia —ya existe una cita que quien pulsa no está
    viendo—, así que toca 200 con el cuerpo fresco y no un 4xx, que htmx no
    swappearía y dejaría al usuario mirando un selector muerto.
    """
    assert err.AppointmentConflict().refresca_la_vista is True


def test_los_estados_activos_son_UN_SOLO_objeto_en_los_dos_servicios():
    """Censo estructural: `_ESTADOS_ACTIVOS` no puede volver a duplicarse.

    Vivía copiado en `appointment_service` y en `slot_service`, atado solo por
    comentarios cruzados que se pedían mutuamente no divergir, y los tres
    consumidores se repartían entre las dos copias: `pages/appointments.py::move`
    importaba la de `appointment_service` mientras
    `SlotService._open_new_attempt` usaba la suya. Si divergían, una cita VIVA
    se iba por `create` -> `AppointmentConflict` donde se quería una reagenda.

    Se afirma la IDENTIDAD y no la igualdad a propósito: dos literales idénticos
    pasarían un `==` y volverían a poder separarse mañana.
    """
    from itcj2.apps.titulatec.services import appointment_service as a_mod
    from itcj2.apps.titulatec.services import slot_service as s_mod

    assert a_mod._ESTADOS_ACTIVOS is s_mod._ESTADOS_ACTIVOS, (
        "hay dos definiciones de `_ESTADOS_ACTIVOS` otra vez: impórtala de "
        "`slot_service` en vez de copiar el literal")
    assert a_mod._ESTADOS_ACTIVOS == {"scheduled", "confirmed", "in_progress"}


# ---------------------------------------------------------------- integración
def test_marcar_asistio_desde_no_show_se_rechaza(db_session, agenda_slots_survey):
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.mark_attended(db_session, ap, esc["off"].id)
    assert ap.status == "no_show"


def test_deshacer_no_se_presento_devuelve_la_cita_a_en_proceso(db_session, agenda_slots_survey):
    """Marcar una ausencia le dispara notificación al egresado. Un clic de más
    en una mañana de prisa tenía que poder corregirse."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    AppointmentService.undo_no_show(db_session, ap, esc["off"].id)

    assert ap.status == "in_progress"
    AppointmentService.mark_attended(db_session, ap, esc["off"].id)
    assert ap.status == "attended"


def test_no_se_puede_reagendar_una_cita_atendida(db_session, agenda_slots_survey):
    """Mover una cita ya atendida borraria la evidencia de que el cotejo
    ocurrio. Si al alumno le faltaron cosas, lo que procede es un intento
    NUEVO (`create`), no mover el que ya se uso."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)
    AppointmentService.mark_attended(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(9, 30), actor_id=esc["off"].id)


def test_agendar_sobre_una_cita_activa_es_conflicto(db_session, agenda_slots_survey):
    """D4: una cita activa a la vez. `create` sobre un proceso que ya tiene
    una viva es un movimiento disfrazado — se rechaza con un error propio,
    no con la matriz (abrir un intento nuevo no es una transicion)."""
    esc = agenda_slots_survey
    AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                              slot_start=time(9, 0), created_by_id=esc["off"].id)

    with pytest.raises(err.AppointmentConflict):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(10, 0), created_by_id=esc["off"].id)


def test_agendar_sobre_una_atendida_abre_un_intento_nuevo(db_session, agenda_slots_survey):
    """D5: atendida pero con faltantes -> si puede agendar otra. El corte real
    es la fase 2 aprobada (y eso lo decide la capa del alumno), no el estado
    `attended`. La fila vieja conserva su status y su franja."""
    from itcj2.apps.titulatec.models import ReviewAppointment
    esc = agenda_slots_survey
    primera = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                        slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, primera, esc["off"].id)
    AppointmentService.mark_attended(db_session, primera, esc["off"].id)

    segunda = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                        slot_start=time(10, 0), created_by_id=esc["off"].id)

    assert primera.status == "attended", "la evidencia del cotejo no se reescribe"
    assert primera.is_current is False
    assert segunda.is_current is True and segunda.attempt_no == 2
    filas = db_session.query(ReviewAppointment).filter_by(process_id=esc["p1"].id).count()
    assert filas == 2


def test_agendar_tras_un_no_show_abre_un_intento_nuevo(db_session, agenda_slots_survey):
    """D7: el no-show puede volver a agendarse, y su franja NO se libera."""
    esc = agenda_slots_survey
    primera = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                        slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, primera, esc["off"].id)

    segunda = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                        slot_start=time(10, 0), created_by_id=esc["off"].id)

    assert primera.status == "no_show" and primera.is_current is False
    assert segunda.status == "scheduled" and segunda.attempt_no == 2


def test_reagendar_un_no_show_es_un_intento_nuevo_no_una_transicion(
        db_session, agenda_slots_survey):
    """El encargado reagenda desde el tablero (`move` -> `reschedule`) a quien
    no se presento: D7 dice que si puede, y §2.2 dice que la fila vieja
    conserva su status. Si esto se rechazara, el cubo «Reagendar» de la cola
    quedaria sin salida."""
    esc = agenda_slots_survey
    primera = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                        slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, primera, esc["off"].id)

    AppointmentService.reschedule(db_session, primera, window_id=esc["w"].id,
                                  slot_start=time(10, 0), actor_id=esc["off"].id)

    assert primera.status == "no_show", "no se reescribe a superseded"
    assert primera.is_current is False
    vigente = _vigente(db_session, esc["p1"])
    assert vigente.status == "scheduled" and vigente.attempt_no == 2


def test_no_se_puede_reagendar_un_cotejo_empezado(db_session, agenda_slots_survey):
    """Un `in_progress` se cierra con `attended` o con `no_show` (§2.3).
    Moverlo dejaria al encargado atendiendo una cita que ya no existe."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.start(db_session, ap, esc["off"].id)

    with pytest.raises(err.InvalidTransition):
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(9, 30), actor_id=esc["off"].id)


def test_create_marca_quien_agendo(db_session, agenda_slots_survey):
    """`booked_by` es el distintivo «Agendada por el alumno» de D11."""
    esc = agenda_slots_survey
    por_encargado = AppointmentService.create(
        db_session, esc["p1"].id, window_id=esc["w"].id, slot_start=time(9, 0),
        created_by_id=esc["off"].id)
    assert por_encargado.booked_by == "officer", "el default no cambia"

    AppointmentService.cancel(db_session, por_encargado, esc["off"].id)
    por_alumno = AppointmentService.create(
        db_session, esc["p1"].id, window_id=esc["w"].id, slot_start=time(9, 30),
        created_by_id=esc["p1"].student_id, booked_by="student")
    assert por_alumno.booked_by == "student"


# ---------------------------------------------------- guards que estaban fuera
def test_sin_franja_es_error_explicito_y_no_un_200_mudo(db_session, agenda_slots_survey):
    esc = agenda_slots_survey
    with pytest.raises(err.MissingSchedule):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=None, created_by_id=esc["off"].id)


def test_el_guard_de_dia_vive_en_el_service(db_session, agenda_slots_survey):
    """Vivía en `pages/`, así que cualquier otro llamador escribía sin validar."""
    esc = agenda_slots_survey
    esc["dia"].is_closed = True
    db_session.flush()

    with pytest.raises(err.DayNotAllowed):
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)


def test_reagendar_no_pisa_la_solicitud_de_cambio(db_session, agenda_slots_survey):
    """Defecto (a): `reschedule` hacía `appt.note = note` y borraba la petición
    del alumno justo cuando el encargado la estaba atendiendo.

    Con historial la solicitud se conserva **en el intento al que pertenecia**,
    que es mejor que antes: no se destruye nada. La cita NUEVA nace limpia a
    proposito — la peticion de cambio ya quedo atendida al moverla, y
    arrastrarla haria que el tablero siguiera pidiendo un cambio ya hecho.
    """
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.request_change(db_session, ap, esc["p1"].student_id,
                                      "tengo examen ese dia")

    AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                  slot_start=time(9, 30), actor_id=esc["off"].id)

    assert ap.change_request == "tengo examen ese dia", "no se destruye la peticion"
    assert ap.status == "superseded" and ap.is_current is False

    vigente = _vigente(db_session, esc["p1"])
    assert vigente.id != ap.id
    assert vigente.scheduled_at.time() == time(9, 30)
    assert vigente.status == "scheduled"
    assert vigente.change_request is None


def test_reagendar_limpia_la_confirmacion(db_session, agenda_slots_survey):
    """La cita nueva nace SIN confirmar: el alumno confirmo la hora vieja, y
    darla por confirmada en la nueva seria ponerle en la boca algo que no
    dijo. La confirmacion del intento anterior se queda en su fila."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.confirm(db_session, ap, esc["p1"].student_id)
    assert ap.confirmed_at is not None

    AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                  slot_start=time(10, 0), actor_id=esc["off"].id)

    assert ap.confirmed_at is not None, "la confirmacion vieja no se borra, se archiva"
    vigente = _vigente(db_session, esc["p1"])
    assert vigente.id != ap.id
    assert vigente.confirmed_at is None
    assert vigente.status == "scheduled"
    assert vigente.scheduled_at.time() == time(10, 0)


# ------------------------------------------------------------------- cancelar
class TestCancelar:
    """`cancel` es compartido por el alumno y el encargado (spec §4.3). La
    ventana de 2 h y el tope de cancelaciones son de la capa del alumno
    (D13), no de aqui."""

    def test_cancelar_sella_la_auditoria_y_deja_de_ser_vigente(
            self, db_session, agenda_slots_survey):
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        AppointmentService.cancel(db_session, ap, esc["p1"].student_id,
                                  reason="me empalma con un examen")

        assert ap.status == "cancelled"
        assert ap.is_current is False
        assert ap.cancelled_at is not None
        assert ap.cancelled_by_id == esc["p1"].student_id
        assert ap.cancel_reason == "me empalma con un examen"

    def test_cancelar_sin_motivo_no_inventa_texto(self, db_session, agenda_slots_survey):
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert ap.cancel_reason is None

    def test_cancelar_escribe_el_evento_del_proceso(self, db_session, agenda_slots_survey):
        from itcj2.apps.titulatec.models import ProcessEvent
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        AppointmentService.cancel(db_session, ap, esc["off"].id, reason="duplicada")

        eventos = (db_session.query(ProcessEvent)
                   .filter_by(process_id=esc["p1"].id,
                              event_type="appointment_cancelled").all())
        assert len(eventos) == 1
        assert eventos[0].phase_number == 2
        assert eventos[0].actor_id == esc["off"].id

    def test_tras_cancelar_no_hay_cita_vigente(self, db_session, agenda_slots_survey):
        """D6: cancelada -> si puede agendar otra. Para el resto de la app el
        proceso vuelve a estar «sin cita»."""
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)

        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert _vigente(db_session, esc["p1"]) is None

    def test_cancelar_libera_la_franja(self, db_session, agenda_slots_survey):
        """D12, la asimetria deliberada contra D10: cancelar a tiempo devuelve
        el lugar al pozo; no presentarse ya lo consumio."""
        from itcj2.apps.titulatec.services.slot_service import SlotService
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        assert SlotService.occupancy(db_session, esc["w"]).get(time(9, 0)) == 1

        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert SlotService.occupancy(db_session, esc["w"]).get(time(9, 0)) is None

    def test_despues_de_cancelar_se_puede_agendar_de_nuevo(
            self, db_session, agenda_slots_survey):
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)

        nueva = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                          slot_start=time(9, 0), created_by_id=esc["off"].id)

        assert nueva.status == "scheduled" and nueva.is_current is True
        assert nueva.attempt_no == 2

    @pytest.mark.parametrize("estado", ["in_progress", "attended"])
    def test_no_se_cancela_un_cotejo_empezado_ni_uno_atendido(
            self, db_session, agenda_slots_survey, estado):
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        AppointmentService.start(db_session, ap, esc["off"].id)
        if estado == "attended":
            AppointmentService.mark_attended(db_session, ap, esc["off"].id)

        with pytest.raises(err.InvalidTransition):
            AppointmentService.cancel(db_session, ap, esc["off"].id)

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_si_cancela_el_encargado_se_le_avisa_al_alumno(
            self, mock_notify, db_session, agenda_slots_survey):
        """Una cancelación es más disruptiva que una reagenda, y a esa sí se le
        avisa. D11 quita la notificación AL ENCARGADO por un auto-agendado; no
        dice callarle al alumno."""
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        mock_notify.reset_mock()        # `create` ya notificó lo suyo

        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert mock_notify.called
        assert mock_notify.call_args.kwargs["type"] == "APPOINTMENT_CANCELLED"

    @patch("itcj2.apps.titulatec.services.notify.notify_student")
    def test_el_alumno_no_recibe_aviso_de_su_propio_clic(
            self, mock_notify, db_session, agenda_slots_survey):
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        mock_notify.reset_mock()

        AppointmentService.cancel(db_session, ap, esc["p1"].student_id)

        assert not mock_notify.called


# --------------------------------------------------------------- la vigencia
class TestVigencia:
    def test_get_for_process_devuelve_la_vigente_no_la_ultima(
            self, db_session, agenda_slots_survey, make_appointment):
        """Con historial, «la ultima por id» devolveria intentos superados.

        El intento superado se siembra con un id MAYOR que el de la vigente
        para que un `order_by(id.desc())` residual salga en rojo: sin esto el
        test pasaria por accidente de orden de insercion.
        """
        esc = agenda_slots_survey
        vigente = AppointmentService.create(
            db_session, esc["p1"].id, window_id=esc["w"].id, slot_start=time(9, 0),
            created_by_id=esc["off"].id)
        superado = make_appointment(esc["p1"], status="superseded",
                                    is_current=False, attempt_no=9)
        assert superado.id > vigente.id

        assert _vigente(db_session, esc["p1"]).id == vigente.id

    def test_sin_ninguna_cita_devuelve_none(self, db_session, agenda_slots_survey):
        assert _vigente(db_session, agenda_slots_survey["p2"]) is None

    def test_list_attempts_da_el_historial_del_mas_reciente_al_mas_viejo(
            self, db_session, agenda_slots_survey):
        """Alimenta la ficha de Atender y el expediente: sin esto, el encargado
        no tiene forma de ver que este es el tercer intento de alguien."""
        esc = agenda_slots_survey
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)
        ap = _vigente(db_session, esc["p1"])
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(9, 30), actor_id=esc["off"].id)
        ap = _vigente(db_session, esc["p1"])
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(10, 0), actor_id=esc["off"].id)

        intentos = AppointmentService.list_attempts(db_session, esc["p1"].id)

        assert [a.attempt_no for a in intentos] == [3, 2, 1]
        assert intentos[0].is_current is True
        assert [a.is_current for a in intentos[1:]] == [False, False]

    def test_list_attempts_de_un_proceso_sin_citas_es_vacio(
            self, db_session, agenda_slots_survey):
        assert AppointmentService.list_attempts(db_session, agenda_slots_survey["p2"].id) == []


class TestLosListadosNoPintanLosIntentosSuperados:
    """Sin el filtro `is_current` la agenda pinta cada intento superado como
    una cita mas: el dia se llena de fantasmas, el contador del carril miente
    y el encargado ve dos veces al mismo alumno."""

    @pytest.fixture()
    def con_historial(self, db_session, agenda_slots_survey):
        """Un proceso con 2 intentos: uno superado a las 9:00 y el vigente a
        las 9:30, los dos el MISMO dia."""
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                      slot_start=time(9, 30), actor_id=esc["off"].id)
        return esc

    def test_list_for_day_cuenta_una_sola_vez(self, db_session, con_historial):
        esc = con_historial
        filas = AppointmentService.list_for_day(
            db_session, date(2029, 5, 7), allowed_program_ids={esc["prog"].id})

        assert len(filas) == 1
        assert filas[0].scheduled_at.time() == time(9, 30)

    def test_counts_by_day_cuenta_una_sola_vez(self, db_session, con_historial):
        from datetime import datetime as _dt, timedelta
        esc = con_historial
        start = _dt(2029, 5, 7)
        conteo = AppointmentService.counts_by_day(
            db_session, start, start + timedelta(days=1),
            allowed_program_ids={esc["prog"].id})

        assert conteo.get(date(2029, 5, 7)) == 1

    def test_list_appointments_cuenta_una_sola_vez(self, db_session, con_historial):
        esc = con_historial
        filas = AppointmentService.list_appointments(
            db_session, allowed_program_ids={esc["prog"].id})

        assert [a.process_id for a in filas] == [esc["p1"].id]

    def test_agenda_process_ids_no_se_infla_con_el_historial(self, db_session, con_historial):
        esc = con_historial
        ids = AppointmentService.agenda_process_ids(
            db_session, allowed_program_ids={esc["prog"].id})

        assert ids == {esc["p1"].id}

    def test_una_cancelada_desaparece_de_la_agenda(self, db_session, agenda_slots_survey):
        """La cancelada no es historial de otro intento: es la unica fila del
        proceso, y aun asi no puede seguir ocupando un hueco en el dia."""
        esc = agenda_slots_survey
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert AppointmentService.list_for_day(
            db_session, date(2029, 5, 7), allowed_program_ids={esc["prog"].id}) == []


class TestElLockEsQuienDecide:
    """El TOCTOU de D4. La guarda de `create` corre FUERA de los locks, así que
    dos `create` concurrentes del mismo proceso la pasan los dos y el segundo
    supera al primero: un intento de más y, peor, **la franja del primero
    liberada** (`superseded` libera). Un doble clic en «Agendar» es exactamente
    ese escenario.

    La carrera real no se puede montar con una sola sesión de test, así que lo
    que se fija aquí es que la comprobación **existe dentro del lock**, que es
    la parte que un refactor futuro podría tirar sin que nada se quejara.
    """

    def test_assign_rechaza_abrir_un_intento_sobre_una_cita_viva(
            self, db_session, agenda_slots_survey):
        from itcj2.apps.titulatec.services.slot_service import SlotService
        esc = agenda_slots_survey
        AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                  slot_start=time(9, 0), created_by_id=esc["off"].id)

        with pytest.raises(err.AppointmentConflict):
            SlotService.assign(db_session, esc["w"].id, time(9, 30), esc["p1"].id,
                               esc["off"].id, rechazar_activa=True)

    def test_reagendar_y_el_reparto_masivo_no_piden_esa_guarda(
            self, db_session, agenda_slots_survey):
        """Superar una cita activa es justo lo que vienen a hacer: si la
        guarda fuera incondicional, reagendar dejaría de funcionar."""
        from itcj2.apps.titulatec.services.slot_service import SlotService
        esc = agenda_slots_survey
        primera = AppointmentService.create(
            db_session, esc["p1"].id, window_id=esc["w"].id,
            slot_start=time(9, 0), created_by_id=esc["off"].id)

        segunda = SlotService.assign(db_session, esc["w"].id, time(9, 30),
                                     esc["p1"].id, esc["off"].id)

        assert primera.status == "superseded"
        assert segunda.is_current is True and segunda.attempt_no == 2


# ------------------------------------------------------------------ los cubos
@pytest.fixture()
def p1_listo_para_agendar(agenda_slots_survey, make_document):
    """`p1` con los 3 documentos iniciales aprobados, que es lo que «Por
    agendar» exige además de la encuesta."""
    for code in ("birth_certificate", "high_school_cert", "curp"):
        make_document(agenda_slots_survey["p1"], type_code=code,
                      review_status="approved")
    return agenda_slots_survey


class TestElCanceladoVuelveAlCubo:
    """D6: cancelada -> sí puede agendar otra. «Sin cita» tiene que significar
    sin cita VIGENTE, no «sin ninguna fila jamás»."""

    @staticmethod
    def _pendientes(db, esc):
        return [p.id for p in AppointmentService.list_pending_processes(
            db, allowed_program_ids={esc["prog"].id})]

    def test_vuelve_a_por_agendar_despues_de_cancelar(self, db_session,
                                                      p1_listo_para_agendar):
        esc = p1_listo_para_agendar
        assert esc["p1"].id in self._pendientes(db_session, esc)

        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        assert esc["p1"].id not in self._pendientes(db_session, esc), \
            "con cita viva no puede seguir en «Por agendar»"

        AppointmentService.cancel(db_session, ap, esc["off"].id)

        assert esc["p1"].id in self._pendientes(db_session, esc)

    def test_el_cancelado_sigue_siendo_alcanzable_desde_citas(
            self, db_session, p1_listo_para_agendar):
        """La consecuencia que de verdad se sufre: `_shell_ctx` arma
        `visibles = agenda_process_ids | pendientes` y **descarta el
        `?selected=` que no esté ahí**. Fuera de los dos conjuntos, el
        encargado no puede ni abrirle la ficha: no es invisible, es
        inalcanzable."""
        esc = p1_listo_para_agendar
        ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                       slot_start=time(9, 0), created_by_id=esc["off"].id)
        AppointmentService.cancel(db_session, ap, esc["off"].id)

        visibles = (AppointmentService.agenda_process_ids(
                        db_session, allowed_program_ids={esc["prog"].id})
                    | set(self._pendientes(db_session, esc)))

        assert esc["p1"].id in visibles


def test_el_reagendado_tras_un_no_show_sale_del_cubo_reagendar(
        db_session, agenda_slots_survey):
    """Los cuatro cubos de la cola son mutuamente excluyentes. Sin el filtro
    de vigencia, quien ya fue reagendado se quedaba en «Reagendar» para
    siempre Y salía a la vez en la agenda."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)
    reagendar = lambda: [p.id for p in AppointmentService.list_reschedule_processes(
        db_session, allowed_program_ids={esc["prog"].id})]
    assert esc["p1"].id in reagendar()

    AppointmentService.reschedule(db_session, ap, window_id=esc["w"].id,
                                  slot_start=time(10, 0), actor_id=esc["off"].id)

    assert esc["p1"].id not in reagendar()


def test_dos_no_show_del_mismo_proceso_no_lo_listan_dos_veces(
        db_session, agenda_slots_survey, make_appointment):
    """Defecto nuevo del historial: el join multiplica. Con dos ausencias, el
    contador del cubo decía 2 y la misma persona salía dos veces en la lista."""
    esc = agenda_slots_survey
    make_appointment(esc["p1"], status="no_show", is_current=False, attempt_no=1)
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    reagendar = [p.id for p in AppointmentService.list_reschedule_processes(
        db_session, allowed_program_ids={esc["prog"].id})]

    assert reagendar.count(esc["p1"].id) == 1


def test_el_no_show_no_vuelve_a_por_agendar(db_session, agenda_slots_survey):
    """Decisión del usuario: su lugar no se libera. Y como conserva su cita,
    tampoco puede aparecer entre los que nunca tuvieron una."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    pendientes = AppointmentService.list_pending_processes(
        db_session, allowed_program_ids={esc["prog"].id})
    assert esc["p1"].id not in [p.id for p in pendientes]


def test_el_no_show_sale_en_su_propio_cubo(db_session, agenda_slots_survey):
    """«Reagendar (N)», separado de «Por agendar (N)»: en uno el alumno ya tuvo
    su lugar y no llegó; en el otro nunca lo tuvo. Mezclarlos haría que el
    contador dejara de significar una sola cosa."""
    esc = agenda_slots_survey
    ap = AppointmentService.create(db_session, esc["p1"].id, window_id=esc["w"].id,
                                   slot_start=time(9, 0), created_by_id=esc["off"].id)
    AppointmentService.mark_no_show(db_session, ap, esc["off"].id)

    reagendar = AppointmentService.list_reschedule_processes(
        db_session, allowed_program_ids={esc["prog"].id})
    assert esc["p1"].id in [p.id for p in reagendar]


def test_la_busqueda_encuentra_por_control_y_por_nombre(db_session, agenda_slots_survey):
    esc = agenda_slots_survey
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

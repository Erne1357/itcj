"""`offer` y `book`: qué se le ofrece al egresado y qué acepta el servidor.

Archivo NO previsto en el plan (que deja `book` para el test de rutas de T6).
Se añade porque el control de seguridad crítico de §4.1 —revalidar `window_id`
contra la oferta del proceso del usuario— vive en el SERVICE, y dejarlo sin
prueba hasta la tarea siguiente es exactamente como se cuelan los IDOR.

Lo que se fija aquí:

* la oferta reusa el predicado de alcance de `scope_service`, recorrido al
  revés (carrera -> puestos -> encargados);
* `private` no se ofrece nunca, `walkin` viaja sin franjas (D2: es un anuncio);
* la anticipación mínima (D8) recorta la oferta Y la escritura, con el mismo
  corte, para que no se pinte un botón que siempre falla;
* agendar en la ventana de otra carrera no es un error de validación: es
  `NotYours`, que la ruta traduce a un 404 limpio.
"""
from datetime import date, datetime, time, timedelta

import pytest

import itcj2.apps.titulatec.services.self_booking_service as sb_mod
from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

_DIA = date(2029, 5, 7)          # el mismo día que arma `agenda_slots`


@pytest.fixture()
def publicado(db_session, agenda_slots, make_survey_review):
    """La ventana de `agenda_slots` publicada como **agendable**, y `p1` listo
    (encuesta ya LIBERADA -- D1, revierte D2 del 2026-09-15 -- para que
    `SelfBookingService.book` no se pare en la regla 3)."""
    make_survey_review(agenda_slots["p1"], status="approved")
    agenda_slots["w"].visibility = "bookable"
    db_session.flush()
    return agenda_slots


def _ventanas(oferta):
    return [w for dia in oferta for o in dia["owners"] for w in o["windows"]]


def _ids(oferta):
    return {w["window_id"] for w in _ventanas(oferta)}


# =========================================================================
# Qué entra en la oferta
# =========================================================================
def test_un_espacio_agendable_de_mi_carrera_se_ofrece_con_sus_franjas(
        db_session, publicado):
    oferta = SelfBookingService.offer(db_session, publicado["p1"].id)

    assert [d["date"] for d in oferta] == [_DIA]
    ventana = _ventanas(oferta)[0]
    assert ventana["window_id"] == publicado["w"].id
    assert ventana["visibility"] == "bookable"
    # 09:00-11:00 en franjas de 30 = cuatro lugares, todos libres.
    assert ventana["slots"] == [time(9, 0), time(9, 30), time(10, 0), time(10, 30)]
    assert oferta[0]["owners"][0]["owner_id"] == publicado["off"].id
    assert oferta[0]["owners"][0]["owner_name"].strip()


def test_un_espacio_privado_no_se_ofrece(db_session, publicado):
    """`private` es el default y significa «el egresado no lo ve» (D1)."""
    publicado["w"].visibility = "private"
    db_session.flush()

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_un_espacio_en_pausa_no_se_ofrece(db_session, publicado):
    publicado["w"].status = "paused"
    db_session.flush()

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_un_dia_cerrado_no_se_ofrece(db_session, publicado):
    publicado["dia"].is_closed = True
    db_session.flush()

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_el_walkin_viaja_con_lugares_y_reservable(db_session, publicado):
    """D3/D4 (spec 2026-09-29 §3.3): «sin horario» ya no es solo un anuncio -el
    alumno APARTA LUGAR sin elegir hora-, así que la oferta trae cuánto queda y
    si todavía se puede. `agenda_slots` da `capacity=1` y nadie lo ocupa aún."""
    publicado["w"].visibility = "walkin"
    publicado["w"].location = "Edificio A"
    db_session.flush()

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert ventana["visibility"] == "walkin"
    assert ventana["start_time"] == time(9, 0) and ventana["end_time"] == time(11, 0)
    assert ventana["location"] == "Edificio A"
    assert ventana["capacity"] == 1
    assert ventana["places_left"] == 1
    assert ventana["reservable"] is True
    assert ventana["motivo"] is None, "reservable: no hay motivo que dar"
    assert ventana["slots"] == [time(9, 0)], "la apertura, NUNCA una franja elegida"


def test_el_walkin_lleno_no_es_reservable(db_session, publicado, make_survey_review):
    """`places_left` nunca negativo, y `reservable` sale de `slots` -nunca de
    una cuenta aparte que pudiera divergir (D5). I-2: sin lugares, `motivo`
    es "lleno" -el encargado puede «Abrir más lugares»-."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    publicado["w"].visibility = "walkin"
    db_session.flush()
    make_survey_review(publicado["p2"], status="approved")
    AppointmentService.create(db_session, publicado["p2"].id, window_id=publicado["w"].id,
                              slot_start=time(9, 0), created_by_id=publicado["off"].id)

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert ventana["places_left"] == 0
    assert ventana["reservable"] is False
    assert ventana["motivo"] == "lleno"
    assert ventana["slots"] == []


def test_el_walkin_que_cierra_en_menos_de_una_hora_no_es_reservable(
        db_session, publicado, monkeypatch):
    """D5: el corte se mide contra el CIERRE (11:00), no contra la apertura
    -que en un `walkin` ya pasó en cuanto el espacio abrió. I-2: con lugar
    libre pero fuera de la anticipación mínima, `motivo` es "cierra_pronto"
    -no "lleno": abrir más lugares no arregla esto-."""
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(10, 15)))
    publicado["w"].visibility = "walkin"
    db_session.flush()

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert ventana["places_left"] == 1, "todavia hay lugar..."
    assert ventana["reservable"] is False, "...pero cierra en 45 minutos"
    assert ventana["motivo"] == "cierra_pronto"
    assert ventana["slots"] == []


def test_un_walkin_que_ya_termino_hoy_deja_de_anunciarse(db_session, publicado,
                                                          monkeypatch):
    """El corte por DÍA no basta para el anuncio sin cita.

    A las 18:00, «abierto sin cita, 09:00-11:00» manda al egresado a caminar
    hasta un cubículo vacío. El corte vive en `offer`, no en la plantilla.
    """
    publicado["w"].visibility = "walkin"
    db_session.flush()
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(18, 0)))

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_un_walkin_en_curso_se_sigue_anunciando(db_session, publicado, monkeypatch):
    """Y el corte no se pasa de listo: a media atención sigue anunciándose."""
    publicado["w"].visibility = "walkin"
    db_session.flush()
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(10, 0)))

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert ventana["visibility"] == "walkin"


def test_la_oferta_no_pinta_franjas_que_arrancan_en_menos_de_una_hora(
        db_session, publicado, monkeypatch):
    """D8, y el mismo corte que usa `book`: una franja ofrecida tiene que
    poder tomarse de verdad.

    A las 09:15 el mínimo son las 10:15, así que de las cuatro franjas
    (09:00 · 09:30 · 10:00 · 10:30) solo sobrevive la última.
    """
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(9, 15)))

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert ventana["slots"] == [time(10, 30)]


def test_un_espacio_agendable_sin_franjas_a_tiempo_desaparece_de_la_oferta(
        db_session, publicado, monkeypatch):
    """A las 09:45 el mínimo son las 10:45 y ya no queda ninguna franja: el
    espacio se omite entero en vez de ofrecerse vacío.

    Un encargado con cero botones no es oferta, es ruido — y peor, invita a
    pulsar algo que el servidor va a rechazar.
    """
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(9, 45)))

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_un_dia_ya_pasado_no_se_ofrece(db_session, publicado, monkeypatch):
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA + timedelta(days=1), time(9, 0)))

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_una_franja_llena_desaparece_de_la_oferta(db_session, publicado,
                                                  make_survey_review):
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    make_survey_review(publicado["p2"], status="approved")
    AppointmentService.create(db_session, publicado["p2"].id, window_id=publicado["w"].id,
                              slot_start=time(9, 0), created_by_id=publicado["off"].id)

    ventana = _ventanas(SelfBookingService.offer(db_session, publicado["p1"].id))[0]

    assert time(9, 0) not in ventana["slots"]


# =========================================================================
# El alcance, recorrido al revés
# =========================================================================
def test_no_se_ofrece_el_espacio_de_un_encargado_de_otra_carrera(
        db_session, publicado, make_program, make_officer, make_review_window):
    """El predicado es el de `scope_service._program_ids_for_user`, del revés:
    carrera -> `ProgramPosition` -> `Position` -> `UserPosition` vigente."""
    otra = make_program("Ingenieria Ajena a la Oferta")
    ajeno, pos_ajeno = make_officer([otra])
    w_ajena = make_review_window(publicado["dia"], ajeno, start="12:00", end="13:00",
                                 slot=30, cap=1, position=pos_ajeno)
    w_ajena.visibility = "bookable"
    db_session.flush()

    assert _ids(SelfBookingService.offer(db_session, publicado["p1"].id)) == {
        publicado["w"].id}


def test_un_puesto_vencido_deja_de_ofrecer(db_session, publicado):
    """`_active_position_filter()` exige vigencia; el encargado cuyo puesto
    venció ayer ya no atiende esa carrera."""
    from itcj2.core.models.position import UserPosition

    (db_session.query(UserPosition)
     .filter_by(user_id=publicado["off"].id, position_id=publicado["pos"].id)
     .update({"end_date": date.today() - timedelta(days=1)}))
    db_session.flush()

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


def test_un_proceso_sin_carrera_no_recibe_oferta(db_session, publicado):
    """Fail-closed, igual que el alcance del encargado: `program_id IS NULL`
    no cae en el conjunto de nadie."""
    publicado["p1"].program_id = None
    db_session.flush()

    assert SelfBookingService.offer(db_session, publicado["p1"].id) == []


# =========================================================================
# `book`
# =========================================================================
def test_agendar_deja_la_cita_marcada_como_agendada_por_el_alumno(db_session, publicado):
    ap = SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                 time(9, 30), publicado["p1"].student_id)

    assert ap.booked_by == "student"          # el distintivo de D11
    assert ap.status == "scheduled" and ap.is_current is True
    assert ap.scheduled_at == datetime.combine(_DIA, time(9, 30))
    assert ap.created_by_id == publicado["p1"].student_id


def test_no_agenda_en_la_ventana_de_otra_carrera(db_session, publicado, make_program,
                                                 make_officer, make_review_window):
    """**El control crítico de §4.1.** `window_id` llega del formulario, así
    que el regresor estructural de rutas con `{process_id}` no lo ve. Sin esta
    revalidación bastaba con cambiar un número para sentarse con el encargado
    de cualquier carrera."""
    otra = make_program("Ingenieria Ajena al Book")
    ajeno, pos_ajeno = make_officer([otra])
    w_ajena = make_review_window(publicado["dia"], ajeno, start="12:00", end="13:00",
                                 slot=30, cap=1, position=pos_ajeno)
    w_ajena.visibility = "bookable"
    db_session.flush()

    with pytest.raises(err.NotYours):
        SelfBookingService.book(db_session, publicado["p1"].id, w_ajena.id,
                                time(12, 0), publicado["p1"].student_id)


def test_no_agenda_en_un_espacio_privado(db_session, publicado):
    """Aunque sea de su propio encargado: `private` no está publicado."""
    publicado["w"].visibility = "private"
    db_session.flush()

    with pytest.raises(err.NotYours):
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(9, 30), publicado["p1"].student_id)


def test_book_en_un_espacio_walkin_aparta_lugar_a_la_apertura(db_session, publicado):
    """D3/D4: el walk-in ya no es solo un anuncio -el egresado APARTA LUGAR sin
    elegir hora, por el mismo `book`. Lo que mande `slot_start` se IGNORA: la
    cita se sienta a la apertura del espacio, no a la hora que llegó."""
    publicado["w"].visibility = "walkin"
    db_session.flush()

    ap = SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                 time(10, 30), publicado["p1"].student_id)

    assert ap.booked_by == "student"
    assert ap.status == "scheduled" and ap.is_current is True
    assert ap.window_id == publicado["w"].id
    assert ap.scheduled_at == datetime.combine(_DIA, time(9, 0)), (
        "la apertura, no los 10:30 que mando el formulario")


def test_book_en_un_espacio_walkin_sin_slot_en_el_form(db_session, publicado):
    """El formulario de un `walkin` no manda `slot`: no hay hora que elegir."""
    publicado["w"].visibility = "walkin"
    db_session.flush()

    ap = SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                 None, publicado["p1"].student_id)

    assert ap.scheduled_at == datetime.combine(_DIA, time(9, 0))


def test_book_en_un_walkin_que_cierra_pronto(db_session, publicado, monkeypatch):
    """D5: `book` mide la anticipación contra el CIERRE del espacio, no contra
    la apertura -que ya pasó en cuanto el `walkin` abrió."""
    publicado["w"].visibility = "walkin"
    db_session.flush()
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(10, 15)))

    with pytest.raises(err.SlotTooSoon) as exc:
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                None, publicado["p1"].student_id)

    assert "Este espacio cierra" in str(exc.value), str(exc.value)


def test_no_agenda_en_el_walkin_de_otra_carrera(
        db_session, publicado, make_program, make_officer, make_review_window):
    """El control crítico de §4.1 (`_window_in_offer`) sigue aplicando: ahora
    `walkin` también agenda, pero solo el de la carrera del proceso."""
    otra = make_program("Ingenieria Ajena al Walkin de Book")
    ajeno, pos_ajeno = make_officer([otra])
    w_ajena = make_review_window(publicado["dia"], ajeno, start="12:00", end="13:00",
                                 slot=30, cap=1, position=pos_ajeno)
    w_ajena.visibility = "walkin"
    db_session.flush()

    with pytest.raises(err.NotYours):
        SelfBookingService.book(db_session, publicado["p1"].id, w_ajena.id,
                                None, publicado["p1"].student_id)


def test_no_agenda_una_franja_que_arranca_en_menos_de_una_hora(
        db_session, publicado, monkeypatch):
    monkeypatch.setattr(sb_mod, "db_now",
                        lambda: datetime.combine(_DIA, time(9, 45)))

    with pytest.raises(err.SlotTooSoon):
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(10, 0), publicado["p1"].student_id)


def test_quien_no_es_elegible_no_agenda_aunque_mande_el_formulario(
        db_session, publicado):
    """La elegibilidad se re-verifica DENTRO de la operación: lo que pintó la
    UI es informativo."""
    publicado["p1"].status = "completed"
    db_session.flush()

    with pytest.raises(err.SelfBookingNotAllowed) as exc:
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(9, 30), publicado["p1"].student_id)

    assert exc.value.reason == "proceso_inactivo"
    assert str(exc.value) == "Tu proceso no está activo."


def test_con_una_cita_viva_el_segundo_clic_no_abre_otra(db_session, publicado):
    """El segundo clic en «Agendar» choca con la regla 4 de `eligibility`.

    Es un test SECUENCIAL: mide la guarda de elegibilidad, que corre **fuera**
    de los locks. La comprobación equivalente DENTRO del advisory lock del
    proceso (`rechazar_activa`, la única que decide una carrera real) existe,
    pero no es lo que mide este test: la fija
    `test_appointment_transitions.py::TestElLockEsQuienDecide`.
    """
    SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                            time(9, 30), publicado["p1"].student_id)

    with pytest.raises(err.SelfBookingNotAllowed) as exc:
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(10, 0), publicado["p1"].student_id)

    assert exc.value.reason == "tiene_cita"


def test_no_agenda_el_proceso_de_otro(db_session, publicado):
    """Paridad con `cancel`: el service no se fía de que la ruta haya resuelto
    el proceso del usuario autenticado.

    De este emparejamiento depende además, en silencio, que `create` calle la
    notificación: si el actor no fuera el dueño, el «no le avises de su propio
    clic» estaría callando el aviso de otra persona.
    """
    with pytest.raises(err.NotYours):
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(9, 30), publicado["p2"].student_id)


def test_el_alumno_no_recibe_aviso_de_su_propio_clic(db_session, publicado):
    """§4.1: acaba de pulsar el botón. Misma condición que en `cancel`."""
    from unittest.mock import patch

    with patch("itcj2.apps.titulatec.services.notify.notify_student") as notificar:
        SelfBookingService.book(db_session, publicado["p1"].id, publicado["w"].id,
                                time(9, 30), publicado["p1"].student_id)

    assert not notificar.called


def test_cuando_agenda_el_encargado_el_alumno_si_recibe_aviso(db_session, publicado):
    """La rama POSITIVA del silencio de arriba.

    Sin esta aserción, una edición que quitara la notificación **por completo**
    pasaría todos los tests: la mudez del auto-agendado quedaría fijada y el
    aviso del encargado no lo fijaría nadie.
    """
    from unittest.mock import patch

    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    with patch("itcj2.apps.titulatec.services.notify.notify_student") as notificar:
        AppointmentService.create(db_session, publicado["p1"].id,
                                  window_id=publicado["w"].id, slot_start=time(9, 30),
                                  created_by_id=publicado["off"].id)

    assert notificar.called
    assert notificar.call_args.kwargs["type"] == "APPOINTMENT_SCHEDULED"

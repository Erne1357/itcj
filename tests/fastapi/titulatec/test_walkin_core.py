"""Núcleo del espacio «sin horario» (`walkin`): UNA franja con el cupo total.

Spec 2026-09-29-titulatec-cotejo-espacios §3.1-§3.2 (D3, D6). Un `walkin` deja
de ser un anuncio: es una sola franja que abarca todo el espacio, a la hora de
apertura, y su `capacity` es el TOTAL de personas. Todo lo demás
(`free_slots`, `window_occupancy`, `assign`) sale correcto por derivación; lo
que aquí se fija es la derivación misma, la ocupación de las citas de legado,
las cuatro reglas de `update` según el modo DESTINO y «Abrir más lugares».

Una «cita de legado» es la que un encargado sentó a una HORA dentro de un
`walkin` antes de este cambio (producción las tiene). Con la derivación nueva
`assign` ya no las crearía, así que se fabrican como las dejó producción: con
su ventana y su hora (`_legado`).
"""
import ast
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import text

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
from itcj2.apps.titulatec.services.slot_service import SlotService

_D = date(2029, 5, 7)
_RWS_SRC = (Path(__file__).resolve().parents[3]
            / "itcj2/apps/titulatec/services/review_window_service.py")


@pytest.fixture()
def sin_horario(make_program, make_cohort, make_review_day, make_officer,
                make_student, make_process, make_review_window):
    """Un sin horario 08:00-14:00 con TRES lugares en total, y cuatro procesos.

    Cuatro contra tres: el cuarto es el que choca con el cupo. `slot=30` queda
    guardado (la columna es NOT NULL) pero en sin horario no se usa; si se
    usara, el espacio tendría 12 franjas y no una.
    """
    prog = make_program("Ingenieria Sin Horario")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])
    w = make_review_window(dia, officer, start="08:00", end="14:00", slot=30,
                           cap=3, location="Sala de cotejo", position=pos,
                           visibility="walkin")
    procesos = [make_process(make_student(), cohort=cohort, program=prog,
                             current_phase=2) for _ in range(4)]
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer,
            "pos": pos, "w": w, "p": procesos}


def _apartar(db, esc, i, hora=time(8, 0)):
    """El proceso `i` aparta lugar: `assign` a la apertura, como lo harán el
    alumno (Tarea 8) y «Atender ahora» (Tarea 6)."""
    return SlotService.assign(db, esc["w"].id, hora, esc["p"][i].id, esc["off"].id)


def _legado(db, make_appointment, w, proc, hhmm, **kw):
    """Cita sentada a mano a una HORA dentro del espacio, con su ventana."""
    a = make_appointment(proc, when=datetime.combine(_D, hhmm), **kw)
    a.window = w
    db.flush()
    return a


def _guardar(db, w, **cambios):
    """Re-guarda el espacio con sus mismos valores salvo lo que se pise.

    Sin `visibility` (None) el modo se CONSERVA: es lo que manda un llamador
    que solo toca el horario, y el que decide contra qué modo se valida.
    """
    datos = {"start_time": w.start_time, "end_time": w.end_time,
             "slot_minutes": w.slot_minutes, "capacity": w.capacity,
             "location": w.location}
    datos.update(cambios)
    return ReviewWindowService.update(db, w, **datos)


# ================================================================ derivación
def test_el_sin_horario_es_una_sola_franja_a_la_apertura(sin_horario):
    assert SlotService.slots(sin_horario["w"]) == [time(8, 0)]


def test_el_mismo_horario_con_franjas_sigue_dando_su_rejilla(db_session, sin_horario):
    """La negativa: lo que colapsa la rejilla es el MODO, no el horario."""
    w = sin_horario["w"]
    w.visibility = "bookable"
    db_session.flush()

    franjas = SlotService.slots(w)

    assert len(franjas) == 12
    assert (franjas[0], franjas[-1]) == (time(8, 0), time(13, 30))


def test_slots_from_en_sin_horario_da_la_apertura_sin_mirar_la_duracion():
    """El editor calcula la rejilla del modo DESTINO antes de que exista."""
    assert SlotService.slots_from("08:00", "14:00", 30, walkin=True) == [time(8, 0)]
    # `slot_minutes` se conserva en un walkin (NOT NULL) pero no se usa.
    assert SlotService.slots_from(time(8, 0), time(14, 0), 0, walkin=True) == [time(8, 0)]
    assert SlotService.slots_from("14:00", "08:00", 30, walkin=True) == []
    # Sin `walkin`, lo de siempre.
    assert len(SlotService.slots_from("08:00", "14:00", 30)) == 12


# ================================================================= ocupación
def test_la_cita_de_legado_sigue_ocupando_bajo_la_apertura(
        db_session, sin_horario, make_appointment):
    """Review Focus 3: la de las 10:30 no se pierde; cuenta como un lugar más."""
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))

    assert SlotService.occupancy(db_session, esc["w"]) == {time(8, 0): 2}
    assert SlotService.window_occupancy(db_session, esc["w"]) == (2, 3)
    assert SlotService.free_slots(db_session, esc["w"]) == [time(8, 0)]


def test_la_cita_de_legado_gasta_cupo(db_session, sin_horario, make_appointment):
    """Si el legado no contara, el tercer lugar se vendería dos veces."""
    esc = sin_horario
    _legado(db_session, make_appointment, esc["w"], esc["p"][0], time(10, 30))
    _apartar(db_session, esc, 1)
    _apartar(db_session, esc, 2)

    with pytest.raises(err.SlotFull):
        _apartar(db_session, esc, 3)


def test_en_sin_horario_ninguna_cita_queda_fuera_de_la_rejilla(
        db_session, sin_horario, make_appointment):
    """Ni la de 10:15, que tampoco caería en la rejilla de 30 del mismo horario."""
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))
    _legado(db_session, make_appointment, esc["w"], esc["p"][2], time(10, 15))

    assert SlotService.out_of_grid(db_session, esc["w"]) == []


def test_la_ocupacion_se_puede_leer_en_el_modo_destino(
        db_session, sin_horario, make_appointment):
    """`walkin`/`inicio` explícitos: lo que usa `update` para validar un cambio
    ANTES de escribirlo. `walkin=None` es el modo actual de la ventana."""
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))

    assert SlotService.occupancy(db_session, esc["w"], walkin=False) == {
        time(8, 0): 1, time(10, 30): 1}
    assert SlotService.occupancy(db_session, esc["w"], inicio=time(9, 0)) == {
        time(9, 0): 2}

    esc["w"].visibility = "bookable"
    db_session.flush()
    assert SlotService.occupancy(db_session, esc["w"]) == {
        time(8, 0): 1, time(10, 30): 1}
    assert SlotService.occupancy(db_session, esc["w"], walkin=True) == {
        time(8, 0): 2}


@pytest.mark.parametrize("status,cuenta", [
    ("cancelled", 0), ("superseded", 0), ("no_show", 1), ("attended", 1)])
def test_cuenta_el_estado_nunca_la_vigencia(db_session, sin_horario, make_appointment,
                                            status, cuenta):
    """Todas NO vigentes a propósito: si el predicado fuera `is_current`, el
    `no_show` y la `attended` dejarían de ocupar (D10/D5)."""
    esc = sin_horario
    _legado(db_session, make_appointment, esc["w"], esc["p"][0], time(8, 0),
            status=status, is_current=False)

    assert sum(SlotService.occupancy(db_session, esc["w"]).values()) == cuenta
    assert SlotService.window_occupancy(db_session, esc["w"]) == (cuenta, 3)


# ================================================================ asignación
def test_apartar_a_la_apertura_entra(db_session, sin_horario):
    esc = sin_horario

    ap = _apartar(db_session, esc, 0)

    assert ap.scheduled_at == datetime.combine(_D, time(8, 0))
    assert ap.window_id == esc["w"].id
    assert ap.status == "scheduled"
    assert SlotService.window_occupancy(db_session, esc["w"]) == (1, 3)


@pytest.mark.parametrize("hora", [time(8, 30), time(10, 30)])
def test_sentar_a_otra_hora_del_espacio_es_invalid_slot(db_session, sin_horario, hora):
    """08:30 sería franja del mismo horario con rejilla; aquí no existe."""
    with pytest.raises(err.InvalidSlot):
        _apartar(db_session, sin_horario, 0, hora=hora)


def test_el_ultimo_lugar_lo_toma_uno_y_el_otro_recibe_slot_full(db_session, sin_horario):
    """Review Focus 2 (servicio): tres lugares, nunca cuatro de tres."""
    from itcj2.apps.titulatec.models import ReviewAppointment
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _apartar(db_session, esc, 1)
    _apartar(db_session, esc, 2)            # el último lugar

    with pytest.raises(err.SlotFull):
        _apartar(db_session, esc, 3)

    assert SlotService.window_occupancy(db_session, esc["w"]) == (3, 3)
    assert SlotService.free_slots(db_session, esc["w"]) == []
    assert (db_session.query(ReviewAppointment)
            .filter_by(process_id=esc["p"][3].id).count()) == 0


# ======================================================= is_walkin_reservation
def test_el_apartado_es_reserva_sin_horario_y_el_legado_no(
        db_session, sin_horario, make_appointment):
    """Review Focus 3: la de las 10:30 conserva su hora (regla de legado)."""
    esc = sin_horario
    reserva = _apartar(db_session, esc, 0)
    legado = _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))

    assert SlotService.is_walkin_reservation(reserva) is True
    assert SlotService.is_walkin_reservation(legado) is False


def test_fuera_de_un_sin_horario_nada_es_reserva(db_session, sin_horario, make_appointment):
    """Misma hora de apertura, pero en un espacio con franjas: es una cita con
    hora. Y una cita heredada sin ventana tampoco puede serlo."""
    esc = sin_horario
    esc["w"].visibility = "bookable"
    db_session.flush()
    con_hora = _apartar(db_session, esc, 0)
    sin_ventana = make_appointment(esc["p"][1], when=datetime.combine(_D, time(8, 0)))

    assert SlotService.is_walkin_reservation(con_hora) is False
    assert SlotService.is_walkin_reservation(sin_ventana) is False
    assert SlotService.is_walkin_reservation(None) is False


# ============================================= update: validar el modo DESTINO
def test_con_lugares_apartados_no_se_mueve_la_apertura(db_session, sin_horario):
    """Review Focus 1. Los apartados guardan día + apertura: moverla los dejaría
    a una hora que el espacio ya no anuncia."""
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _apartar(db_session, esc, 1)

    with pytest.raises(err.WalkinStartLocked) as exc:
        _guardar(db_session, esc["w"], start_time=time(9, 0))
    assert str(exc.value) == (
        "Ya hay 2 lugares apartados: no puedes cambiar la hora de apertura. "
        "Puedes ampliar el cierre o abrir más lugares.")

    # Pasar el modo explícito no abre otro camino.
    with pytest.raises(err.WalkinStartLocked):
        _guardar(db_session, esc["w"], start_time=time(9, 0), visibility="walkin")
    assert esc["w"].start_time == time(8, 0)


def test_con_lugares_apartados_si_se_amplia_el_cierre_y_se_abren_lugares(
        db_session, sin_horario):
    """Review Focus 1, la otra mitad: a quien ya apartó no le cambia nada."""
    esc = sin_horario
    _apartar(db_session, esc, 0)

    _guardar(db_session, esc["w"], end_time=time(16, 0))
    ReviewWindowService.add_places(db_session, esc["w"], 2)

    assert esc["w"].end_time == time(16, 0)
    assert esc["w"].capacity == 5
    assert esc["w"].visibility == "walkin", "sin `visibility` el modo se conserva"


def test_sin_apartados_vivos_la_apertura_si_se_mueve(db_session, sin_horario,
                                                     make_appointment):
    """Un lugar cancelado ya volvió al pozo: no ata la apertura."""
    esc = sin_horario
    _legado(db_session, make_appointment, esc["w"], esc["p"][0], time(8, 0),
            status="cancelled", is_current=False)

    _guardar(db_session, esc["w"], start_time=time(9, 0))

    assert esc["w"].start_time == time(9, 0)


def test_bajar_el_cupo_total_bajo_los_apartados_es_conflicto(
        db_session, sin_horario, make_appointment):
    """El cupo es del ESPACIO, no de cada hora: la de legado de las 10:30 y el
    apartado de las 08:00 son dos lugares aunque ninguna hora tenga dos."""
    esc = sin_horario
    _apartar(db_session, esc, 0)
    _legado(db_session, make_appointment, esc["w"], esc["p"][1], time(10, 30))

    with pytest.raises(err.WindowShrinkConflict) as exc:
        _guardar(db_session, esc["w"], capacity=1)
    assert str(exc.value) == ("1 cita quedaría fuera del horario nuevo. "
                              "Muévelas antes de reducirlo.")
    assert esc["w"].capacity == 3

    _guardar(db_session, esc["w"], capacity=2)
    assert esc["w"].capacity == 2


def test_pasar_a_sin_horario_junta_todas_las_vivas_contra_el_cupo_total(
        db_session, sin_horario):
    """Con franjas -> sin horario: las citas de cualquier hora cuentan juntas.

    Ruling 2026-09-29 (revision de T2, arrastrada a la Tarea 4): el horario no
    se toca (sigue 08:00-14:00), asi que esto NO es un horario que se quedo
    chico -- es el CUPO TOTAL del modo nuevo el que no aguanta a las 3 vivas.
    Antes disparaba `WindowShrinkConflict`, cuyo texto («fuera del horario
    nuevo») no describia lo que de verdad paso.
    """
    esc = sin_horario
    esc["w"].visibility = "bookable"            # 3 por franja
    db_session.flush()
    _apartar(db_session, esc, 0)
    _apartar(db_session, esc, 1)
    _apartar(db_session, esc, 2, hora=time(10, 30))

    with pytest.raises(err.WindowModeConflict) as exc:
        _guardar(db_session, esc["w"], visibility="walkin", capacity=2)
    assert str(exc.value) == ("Este espacio tiene 1 cita que no cabe en el modo "
                              "nuevo. Muévelas o cancélalas primero.")
    assert esc["w"].visibility == "bookable"

    _guardar(db_session, esc["w"], visibility="walkin", capacity=3)
    assert esc["w"].visibility == "walkin"
    assert SlotService.occupancy(db_session, esc["w"]) == {time(8, 0): 3}


def test_pasar_a_sin_horario_no_deja_citas_fuera_del_horario_nuevo(db_session, sin_horario):
    """Ruling 2026-09-29: el cupo total alcanza, pero la de las 13:30 quedaría
    viva fuera de un 09:00-12:00, y por la regla de legado se le seguiría
    anunciando «13:30». Con franjas, la rejilla ya lo atrapaba."""
    esc = sin_horario
    esc["w"].visibility = "bookable"
    db_session.flush()
    _apartar(db_session, esc, 0, hora=time(13, 30))

    with pytest.raises(err.WindowShrinkConflict) as exc:
        _guardar(db_session, esc["w"], visibility="walkin",
                 start_time=time(9, 0), end_time=time(12, 0))
    assert str(exc.value) == ("1 cita quedaría fuera del horario nuevo. "
                              "Muévelas antes de reducirlo.")
    assert esc["w"].visibility == "bookable"

    _guardar(db_session, esc["w"], visibility="walkin",
             start_time=time(9, 0), end_time=time(14, 0))
    assert esc["w"].visibility == "walkin"


def test_recortar_el_cierre_no_deja_fuera_la_cita_de_legado(
        db_session, sin_horario, make_appointment):
    """La de las 11:00 no cabe en un cierre a las 10:30; en uno a las 11:30 sí,
    y ampliarlo nunca deja a nadie fuera."""
    esc = sin_horario
    _legado(db_session, make_appointment, esc["w"], esc["p"][0], time(11, 0))

    with pytest.raises(err.WindowShrinkConflict):
        _guardar(db_session, esc["w"], end_time=time(10, 30))
    assert esc["w"].end_time == time(14, 0)

    _guardar(db_session, esc["w"], end_time=time(11, 30))
    _guardar(db_session, esc["w"], end_time=time(16, 0))
    assert esc["w"].end_time == time(16, 0)


def test_recortar_el_cierre_con_solo_apartados_si_se_puede(db_session, sin_horario):
    """La negativa: los apartados están a la apertura, así que ningún cierre
    posterior a ella los deja fuera."""
    esc = sin_horario
    _apartar(db_session, esc, 0)

    _guardar(db_session, esc["w"], end_time=time(10, 30))

    assert esc["w"].end_time == time(10, 30)


def test_salir_de_sin_horario_revisa_el_cupo_por_franja_nuevo(db_session, sin_horario):
    """Sin horario -> con franjas: los tres apartados vuelven a su hora real,
    la apertura, y ahí solo cabe UNO con cupo 1 por franja."""
    esc = sin_horario
    for i in range(3):
        _apartar(db_session, esc, i)

    with pytest.raises(err.WindowModeConflict) as exc:
        _guardar(db_session, esc["w"], visibility="bookable", capacity=1)
    assert str(exc.value) == ("Este espacio tiene 2 citas que no caben en el modo "
                              "nuevo. Muévelas o cancélalas primero.")
    assert esc["w"].visibility == "walkin"

    _guardar(db_session, esc["w"], visibility="bookable", capacity=3)
    assert esc["w"].visibility == "bookable"


def test_salir_de_sin_horario_revisa_la_rejilla_nueva(db_session, sin_horario,
                                                     make_appointment):
    """La de legado de las 10:30 no cae en una rejilla de 60 desde las 08:00."""
    esc = sin_horario
    _legado(db_session, make_appointment, esc["w"], esc["p"][0], time(10, 30))

    with pytest.raises(err.WindowModeConflict) as exc:
        _guardar(db_session, esc["w"], visibility="private", slot_minutes=60)
    assert str(exc.value) == ("Este espacio tiene 1 cita que no cabe en el modo "
                              "nuevo. Muévelas o cancélalas primero.")

    _guardar(db_session, esc["w"], visibility="private", slot_minutes=30)
    assert esc["w"].visibility == "private"


def test_entre_modos_con_franjas_se_valida_como_siempre(db_session, sin_horario):
    """Agendable -> privado no es cambio de modo de ocupación: si recorta el
    horario con gente dentro, es el encogimiento de siempre."""
    esc = sin_horario
    esc["w"].visibility = "bookable"
    db_session.flush()
    _apartar(db_session, esc, 0, hora=time(13, 30))

    with pytest.raises(err.WindowShrinkConflict):
        _guardar(db_session, esc["w"], visibility="private", end_time=time(13, 0))


# ======================================================== «Abrir más lugares»
def test_abrir_mas_lugares_suma_al_cupo_total(db_session, sin_horario):
    esc = sin_horario
    _apartar(db_session, esc, 0)

    w = ReviewWindowService.add_places(db_session, esc["w"], 5)

    assert w.capacity == 8
    assert SlotService.window_occupancy(db_session, esc["w"]) == (1, 8)


@pytest.mark.parametrize("n", [0, -3, 51, None, "x"])
def test_abrir_mas_lugares_fuera_de_rango(db_session, sin_horario, n):
    esc = sin_horario

    with pytest.raises(err.PlacesOutOfRange) as exc:
        ReviewWindowService.add_places(db_session, esc["w"], n)

    assert str(exc.value) == "Puedes abrir de 1 a 50 lugares a la vez, hasta 500 en total."
    assert esc["w"].capacity == 3


def test_abrir_mas_lugares_no_pasa_del_tope_total(db_session, sin_horario):
    """500 es el mismo `max` del editor: por encima ya no se podría re-guardar."""
    esc = sin_horario
    esc["w"].capacity = 480
    db_session.flush()

    with pytest.raises(err.PlacesOutOfRange):
        ReviewWindowService.add_places(db_session, esc["w"], 21)
    assert esc["w"].capacity == 480

    ReviewWindowService.add_places(db_session, esc["w"], 20)
    assert esc["w"].capacity == 500


@pytest.mark.parametrize("modo", ["bookable", "private"])
def test_abrir_mas_lugares_solo_en_sin_horario(db_session, sin_horario, modo):
    """Ruling 2026-09-29: con franjas `capacity` es POR FRANJA (el editor lo topa
    en 20); «+50» lo dejaría en un valor que el editor ya no deja re-guardar."""
    esc = sin_horario
    esc["w"].visibility = modo
    db_session.flush()

    with pytest.raises(err.InvalidSlot) as exc:
        ReviewWindowService.add_places(db_session, esc["w"], 5)

    assert str(exc.value) == "Solo los espacios sin horario abren lugares."
    assert esc["w"].capacity == 3


def test_abrir_mas_lugares_lee_el_modo_bajo_el_lock(db_session, sin_horario):
    """Otro encargado pasó el espacio a «Agendable» mientras este esperaba el
    lock: el objeto en memoria sigue diciendo `walkin`, la fila ya no."""
    esc = sin_horario
    db_session.execute(text("UPDATE titulatec_review_windows SET visibility = 'bookable' "
                            "WHERE id = :w"), {"w": esc["w"].id})
    assert esc["w"].visibility == "walkin", "el escenario necesita el modo viejo en memoria"

    with pytest.raises(err.InvalidSlot):
        ReviewWindowService.add_places(db_session, esc["w"], 5)
    assert esc["w"].capacity == 3


def test_abrir_mas_lugares_suma_sobre_el_cupo_releido_bajo_el_lock(db_session, sin_horario):
    """Otro encargado abrió lugares mientras este esperaba el lock.

    El objeto del mapa de identidad se cargó ANTES de esperar; `_lock_window`
    lo relee bajo el lock (la única relectura, Tarea 6). El UPDATE crudo hace
    de la transacción ajena ya commiteada: el objeto en memoria sigue diciendo
    3 y la fila dice 10. Sumarle al 3 perdería los siete lugares del otro.
    """
    esc = sin_horario
    db_session.execute(text("UPDATE titulatec_review_windows SET capacity = 10 "
                            "WHERE id = :w"), {"w": esc["w"].id})
    assert esc["w"].capacity == 3, "el escenario necesita el valor viejo en memoria"

    ReviewWindowService.add_places(db_session, esc["w"], 5)

    assert esc["w"].capacity == 15


def test_abrir_mas_lugares_espera_el_lock_de_la_ventana(db_session, sin_horario,
                                                       monkeypatch):
    """Sin el `FOR UPDATE` de la ventana, dos «+5» a la vez podrían pisarse.

    Mismo truco que `test_slot_service`: no hay dos conexiones reales en el
    harness, así que se prueba que el lock se PIDE y que su timeout se
    traduce a la frase de ventanilla.
    """
    from sqlalchemy.exc import OperationalError
    esc = sin_horario
    real = db_session.execute

    def _execute(stmt, *a, **kw):
        if "FOR UPDATE" in str(stmt):
            raise OperationalError("SELECT ... FOR UPDATE", {}, Exception("lock timeout"))
        return real(stmt, *a, **kw)

    monkeypatch.setattr(db_session, "execute", _execute)

    with pytest.raises(err.SlotLockTimeout):
        ReviewWindowService.add_places(db_session, esc["w"], 5)
    assert esc["w"].capacity == 3


# =================================================================== errores
@pytest.mark.parametrize("nombre,args", [
    ("WindowModeConflict", (1,)), ("WalkinStartLocked", (1,)), ("PlacesOutOfRange", ())])
def test_los_errores_nuevos_son_de_entrada(nombre, args):
    """400 + X-Tt-Error: lo que hay en pantalla sigue siendo verdad."""
    error = getattr(err, nombre)(*args)
    assert isinstance(error, err.AppointmentError)
    assert error.refresca_la_vista is False


def test_los_mensajes_concuerdan_en_numero():
    assert str(err.WalkinStartLocked(1)) == (
        "Ya hay 1 lugar apartado: no puedes cambiar la hora de apertura. "
        "Puedes ampliar el cierre o abrir más lugares.")
    assert str(err.WindowModeConflict(3)) == (
        "Este espacio tiene 3 citas que no caben en el modo nuevo. "
        "Muévelas o cancélalas primero.")


def test_review_window_service_no_commitea():
    """Como `SlotService`: un commit soltaría el lock de la ventana antes de
    tiempo. El dueño de la transacción es la ruta. Por AST y no por texto: el
    docstring del módulo nombra la regla."""
    arbol = ast.parse(_RWS_SRC.read_text(encoding="utf-8"), filename=str(_RWS_SRC))
    culpables = [f"linea {n.lineno}" for n in ast.walk(arbol)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "commit"]
    assert not culpables, "ReviewWindowService no puede commitear: " + ", ".join(culpables)

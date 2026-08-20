"""Split por bloques: cada cita es un ancla inamovible.

REGLA NUEVA (reemplaza la rejilla global anclada en start_efectivo):

  - La hora de INICIO de toda cita existente se respeta SIEMPRE.
  - Una cita se acorta si la duración nueva cabe; si no, se deja como está y el
    resto del rango sí se re-divide. El rango NUNCA se rechaza por esto.
  - Los huecos entre anclas se rellenan anclando en la rejilla canónica
    (start_efectivo + k·nuevos_min); solo si el hueco quedaría VACÍO pudiendo
    caber un slot, se ancla localmente al inicio del hueco.
  - El sobrante de un hueco queda sin slot.
  - Dos slots nunca pueden solaparse.

La regla vieja exigía `(inicio − start_efectivo) % nuevos_min == 0` para TODA
cita del rango, lo que rechazaba 15→10 con una cita en 9:15. Ahora eso es
válido: la cita conserva su 9:15 y solo se acorta a 9:15–9:25.
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from itcj2.apps.agendatec.helpers import app_dt
from itcj2.apps.agendatec.models import TimeSlot
from itcj2.apps.agendatec.services.slot_service import SlotService

DAY = date(2026, 9, 1)


def _at(t):
    return app_dt(DAY, t)


@pytest.fixture()
def temprano():
    with patch("itcj2.apps.agendatec.services.slot_service.now_app",
               return_value=_at(time(8, 0))):
        yield


def _slots(db, coord_id):
    return (db.query(TimeSlot)
            .filter_by(coordinator_id=coord_id, day=DAY)
            .order_by(TimeSlot.start_time).all())


def _intervals(db, coord_id):
    return [(s.start_time, s.end_time) for s in _slots(db, coord_id)]


def _assert_no_overlaps(db, coord_id):
    ivs = _intervals(db, coord_id)
    for (s1, e1), (s2, e2) in zip(ivs, ivs[1:]):
        assert e1 <= s2, f"solape {s1}-{e1} / {s2}-{e2}"


def _plan_and_apply(db, ctx, start, end, minutes, programs=None):
    programs = programs or ctx["program_ids"]
    plan = SlotService.plan_split(db, ctx["coord"].id, DAY, start, end, minutes, programs)
    result = SlotService.apply_split(db, ctx["coord"].id, DAY, plan, programs)
    db.flush()
    return plan, result


# ===========================================================================
# La invariante central: la hora de entrada NUNCA se mueve
# ===========================================================================
def test_start_time_is_preserved_for_every_booking(db_session, coord_setup, make_grid,
                                                   make_user, make_booking, temprano):
    """Tres citas en horas distintas, split a una duración que no divide a ninguna."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(11, 0), 15, ctx["program_ids"])
    reservados = [s for s in slots if s.start_time in (time(9, 15), time(9, 45), time(10, 30))]
    for i, s in enumerate(reservados):
        alum = make_user(first_name="P", last_name=str(i), control_number=f"2099100{i}")
        make_booking(s, alum, ctx["program_ids"][0], ctx["period"].id)
    esperados = {s.id: s.start_time for s in reservados}

    _plan_and_apply(db_session, ctx, time(9, 0), time(11, 0), 7)

    db_session.expire_all()
    for sid, inicio in esperados.items():
        assert db_session.get(TimeSlot, sid).start_time == inicio, \
            "la hora de entrada del alumno no se puede mover"
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_15_to_10_is_now_allowed(db_session, coord_setup, make_grid,
                                 make_user, make_booking, temprano):
    """El caso que la regla vieja rechazaba: 9:15 no cae en la rejilla de 10.

    Ahora la cita conserva su 9:15 y se acorta a 9:15–9:25.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="Q", last_name="UNO", control_number="20991010")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)
    rid = reservado.id

    plan, _ = _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 10)

    assert plan.blocked is False, "ya no se rechaza"
    db_session.expire_all()
    s = db_session.get(TimeSlot, rid)
    assert s.start_time == time(9, 15)
    assert s.end_time == time(9, 25)
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_a_booking_that_cannot_shrink_is_left_alone(db_session, coord_setup, make_grid,
                                                    make_user, make_booking, temprano):
    """Cita de 5 min con split a 15: no puede crecer, se queda igual.

    Y el resto del rango SÍ se re-divide: es "que se cumpla para unos bloques
    y no para otros".
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 5, ctx["program_ids"])
    reservado = slots[0]
    alum = make_user(first_name="Q", last_name="DOS", control_number="20991011")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)
    rid = reservado.id

    plan, _ = _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 15)

    assert plan.blocked is False
    db_session.expire_all()
    s = db_session.get(TimeSlot, rid)
    assert (s.start_time, s.end_time) == (time(9, 0), time(9, 5)), \
        "la cita que no cabe se deja intacta, no se alarga"
    assert any(sid == rid for sid in [k.slot_id for k in plan.kept_as_is]), \
        "debe reportarse como no modificada"
    # El resto sí se re-dividió a 15.
    nuevos = [s for s in _slots(db_session, ctx["coord"].id) if not s.is_booked]
    assert nuevos, "el resto del rango debe tener slots nuevos"
    _assert_no_overlaps(db_session, ctx["coord"].id)


# ===========================================================================
# Plan y aplicación no pueden divergir
# ===========================================================================
def test_plan_and_apply_produce_the_exact_same_intervals(db_session, coord_setup, make_grid,
                                                         make_user, make_booking, temprano):
    """El preview promete horarios concretos; el POST debe crear ESOS.

    Antes `apply_split` re-derivaba la rejilla globalmente, así que con citas
    desalineadas prometía 09:10–09:35 y creaba 09:25–09:50. Los tests que solo
    contaban filas no lo veían.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="R", last_name="UNO", control_number="20991020")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    plan, result = _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 25)

    assert result.slots_created == len(plan.to_create), \
        "el conteo del preview y el del POST tienen que coincidir"

    db_session.expire_all()
    libres = {(s.start_time, s.end_time) for s in _slots(db_session, ctx["coord"].id)
              if not s.is_booked}
    assert libres == set(plan.to_create), \
        "los horarios creados deben ser EXACTAMENTE los que prometió el plan"


def test_no_overlaps_with_misaligned_bookings(db_session, coord_setup, make_grid,
                                              make_user, make_booking, temprano):
    """Dos citas en offsets raros, duración que no divide nada."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(11, 0), 10, ctx["program_ids"])
    for i, hora in enumerate((time(9, 10), time(10, 20))):
        s = next(x for x in slots if x.start_time == hora)
        alum = make_user(first_name="S", last_name=str(i), control_number=f"2099103{i}")
        make_booking(s, alum, ctx["program_ids"][0], ctx["period"].id)

    _plan_and_apply(db_session, ctx, time(9, 0), time(11, 0), 13)

    db_session.expire_all()
    _assert_no_overlaps(db_session, ctx["coord"].id)


# ===========================================================================
# Relleno de huecos: rejilla canónica con fallback local
# ===========================================================================
def test_gap_fill_uses_the_canonical_grid(db_session, coord_setup, make_grid,
                                          make_user, make_booking, temprano):
    """El offset de una cita no debe contagiarse al resto del día.

    Cita 9:03–9:08 que no se puede acortar (5 min, split a 10). El relleno
    arranca en 9:10 (rejilla canónica desde 9:00), no en 9:08.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 5, ctx["program_ids"])
    # Se mueve un slot a un offset raro para simular un split previo.
    raro = slots[0]
    raro.start_time = time(9, 3)
    raro.end_time = time(9, 8)
    db_session.flush()
    alum = make_user(first_name="T", last_name="UNO", control_number="20991040")
    make_booking(raro, alum, ctx["program_ids"][0], ctx["period"].id)

    plan, _ = _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 10)

    inicios = sorted(s for s, _ in plan.to_create)
    assert time(9, 10) in inicios, "debe engancharse a la rejilla canónica"
    assert time(9, 8) not in inicios, "no debe contagiar el offset de la cita"
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_gap_falls_back_to_local_anchor_when_canonical_would_waste_it(
        db_session, coord_setup, make_grid, make_user, make_booking, temprano):
    """Si anclar en la rejilla canónica deja el hueco VACÍO pudiendo caber, se ancla local.

    Hueco de 9:08 a 9:20 (12 min) con slots de 10: la rejilla canónica solo
    ofrece 9:10, y 9:10–9:20 sí cabe, así que no hace falta el fallback. Aquí se
    fuerza el caso donde sí: hueco de 9:08 a 9:18 (10 min exactos) — canónica
    daría 9:10–9:20, que se sale; local da 9:08–9:18.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 5, ctx["program_ids"])
    primero, segundo = slots[0], slots[1]
    primero.start_time, primero.end_time = time(9, 3), time(9, 8)
    segundo.start_time, segundo.end_time = time(9, 18), time(9, 23)
    db_session.flush()
    for i, s in enumerate((primero, segundo)):
        alum = make_user(first_name="U", last_name=str(i), control_number=f"2099105{i}")
        make_booking(s, alum, ctx["program_ids"][0], ctx["period"].id)

    plan, _ = _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 10)

    en_hueco = [(s, e) for s, e in plan.to_create if time(9, 8) <= s < time(9, 18)]
    assert en_hueco == [(time(9, 8), time(9, 18))], \
        "el hueco de 10 min exactos debe aprovecharse con ancla local"
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_leftover_smaller_than_the_duration_gets_no_slot(db_session, coord_setup, temprano):
    """Rango de 55 min con slots de 20: se crean 2 y sobran 15 sin slot."""
    ctx = coord_setup(n_programs=1)
    plan, result = _plan_and_apply(db_session, ctx, time(9, 0), time(9, 55), 20)
    assert result.slots_created == 2
    assert plan.to_create == [(time(9, 0), time(9, 20)), (time(9, 20), time(9, 40))]


# ===========================================================================
# Slots con historial: se re-dimensionan, no se congelan
# ===========================================================================
def test_slot_with_history_is_resized_not_frozen(db_session, coord_setup, make_grid,
                                                 make_user, make_booking, temprano):
    """El CASCADE prohíbe BORRARLO, no cambiarle la duración.

    Congelarlo lo dejaba reservable con la duración vieja para siempre.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    con_historial = slots[0]
    alum = make_user(first_name="V", last_name="UNO", control_number="20991060")
    make_booking(con_historial, alum, ctx["program_ids"][0], ctx["period"].id,
                 ap_status="CANCELED", req_status="CANCELED")
    con_historial.is_booked = False       # cancelar libera el slot
    db_session.flush()
    hid = con_historial.id

    _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 5)

    db_session.expire_all()
    s = db_session.get(TimeSlot, hid)
    assert s is not None, "no se puede borrar: destruiría la cita CANCELED"
    assert s.end_time == time(9, 5), "pero sí se re-dimensiona a la duración nueva"
    _assert_no_overlaps(db_session, ctx["coord"].id)


# ===========================================================================
# Duraciones libres 5..60
# ===========================================================================
@pytest.mark.parametrize("minutos", [5, 7, 13, 25, 60])
def test_arbitrary_durations_are_accepted(db_session, coord_setup, minutos, temprano):
    ctx = coord_setup(n_programs=1)
    plan, result = _plan_and_apply(db_session, ctx, time(9, 0), time(11, 0), minutos)
    assert result.slots_created == 120 // minutos
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_adjacent_bookings_without_gap(db_session, coord_setup, make_grid,
                                       make_user, make_booking, temprano):
    """Dos citas pegadas: no hay hueco que rellenar entre ellas."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    for i, s in enumerate(slots[:2]):
        alum = make_user(first_name="W", last_name=str(i), control_number=f"2099107{i}")
        make_booking(s, alum, ctx["program_ids"][0], ctx["period"].id)

    _plan_and_apply(db_session, ctx, time(9, 0), time(10, 0), 5)

    db_session.expire_all()
    ivs = _intervals(db_session, ctx["coord"].id)
    assert (time(9, 0), time(9, 5)) in ivs
    assert (time(9, 10), time(9, 15)) in ivs
    _assert_no_overlaps(db_session, ctx["coord"].id)

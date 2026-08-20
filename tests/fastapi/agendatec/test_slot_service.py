"""SlotService: scope, generación de grilla, plan y aplicación del split.

Los casos de FRONTERA son los importantes. El diseño original filtraba los
slots del rango con `start_time >= start_efectivo`, que NO captura los que
*cruzan* la frontera — y la grilla nueva sí arranca ahí. Eso producía slots
solapados y doble-booking. El predicado correcto es "solapa el rango".
"""
from datetime import date, time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from itcj2.apps.agendatec.helpers import app_dt
from itcj2.apps.agendatec.models import TimeSlot, TimeSlotProgram
from itcj2.apps.agendatec.services.slot_service import SlotService

DAY = date(2026, 9, 1)


def _at(t):
    """`now_app()` congelado a una hora del día de prueba."""
    return app_dt(DAY, t)


def _slots_of(db, coord_id, day=DAY):
    return (db.query(TimeSlot)
            .filter_by(coordinator_id=coord_id, day=day)
            .order_by(TimeSlot.start_time)
            .all())


def _assert_no_overlaps(db, coord_id, day=DAY):
    slots = _slots_of(db, coord_id, day)
    for a, b in zip(slots, slots[1:]):
        assert a.end_time <= b.start_time, (
            f"slots solapados: {a.start_time}-{a.end_time} y {b.start_time}-{b.end_time}"
        )


# ===========================================================================
# resolve_programs
# ===========================================================================
def test_resolve_programs_none_means_all(db_session, coord_setup):
    ctx = coord_setup(n_programs=3)
    got = SlotService.resolve_programs(db_session, ctx["coord"].id, None)
    assert sorted(got) == sorted(ctx["program_ids"])


def test_resolve_programs_empty_means_all(db_session, coord_setup):
    ctx = coord_setup(n_programs=3)
    got = SlotService.resolve_programs(db_session, ctx["coord"].id, [])
    assert sorted(got) == sorted(ctx["program_ids"])


def test_resolve_programs_keeps_the_subset(db_session, coord_setup):
    ctx = coord_setup(n_programs=3)
    picked = [ctx["program_ids"][0]]
    assert SlotService.resolve_programs(db_session, ctx["coord"].id, picked) == picked


def test_resolve_programs_rejects_a_foreign_program(db_session, coord_setup, make_program):
    ctx = coord_setup(n_programs=1)
    ajena = make_program("Carrera Ajena RP")
    with pytest.raises(HTTPException) as exc:
        SlotService.resolve_programs(db_session, ctx["coord"].id, [ajena.id])
    assert exc.value.status_code == 400
    assert "invalid_programs" in str(exc.value.detail)


def test_resolve_programs_rejects_coordinator_without_programs(db_session, make_user,
                                                               grant_app_role):
    """Un coordinador sin carreras generaría slots invisibles para todos."""
    from itcj2.core.models.coordinator import Coordinator

    u = make_user(first_name="SIN", last_name="CARRERAS", role_name="staff")
    grant_app_role(u, "coordinator")
    c = Coordinator(user_id=u.id)
    db_session.add(c)
    db_session.flush()

    with pytest.raises(HTTPException) as exc:
        SlotService.resolve_programs(db_session, c.id, None)
    assert exc.value.status_code == 400
    assert "coordinator_has_no_programs" in str(exc.value.detail)


# ===========================================================================
# generate_range
# ===========================================================================
def test_generate_range_builds_the_grid(db_session, coord_setup):
    ctx = coord_setup(n_programs=1)
    slots = SlotService.generate_range(
        db_session, ctx["coord"].id, DAY, time(9, 0), time(10, 0), 10, ctx["program_ids"]
    )
    assert len(slots) == 6
    assert slots[0].start_time == time(9, 0) and slots[0].end_time == time(9, 10)
    assert slots[-1].end_time == time(10, 0)


def test_generate_range_materializes_scope(db_session, coord_setup):
    ctx = coord_setup(n_programs=2)
    slots = SlotService.generate_range(
        db_session, ctx["coord"].id, DAY, time(9, 0), time(9, 30), 10, ctx["program_ids"]
    )
    rows = (db_session.query(TimeSlotProgram)
            .filter(TimeSlotProgram.slot_id.in_([s.id for s in slots])).all())
    assert len(rows) == 6, "3 slots x 2 carreras"


def test_generate_range_leaves_the_remainder_unslotted(db_session, coord_setup):
    """25 min con paso de 10 da 2 slots; los últimos 5 quedan sin cubrir."""
    ctx = coord_setup(n_programs=1)
    slots = SlotService.generate_range(
        db_session, ctx["coord"].id, DAY, time(9, 0), time(9, 25), 10, ctx["program_ids"]
    )
    assert len(slots) == 2


def test_generate_range_skips_occupied_intervals(db_session, coord_setup):
    """El split regenera alrededor de las citas ya acortadas."""
    ctx = coord_setup(n_programs=1)
    slots = SlotService.generate_range(
        db_session, ctx["coord"].id, DAY, time(9, 0), time(9, 30), 5, ctx["program_ids"],
        skip_intervals=[(time(9, 0), time(9, 5))],
    )
    starts = [s.start_time for s in slots]
    assert time(9, 0) not in starts
    assert time(9, 5) in starts
    assert len(slots) == 5


# ===========================================================================
# plan_split — FRONTERA (el bug de diseño que la revisión destapó)
# ===========================================================================
def test_free_slot_straddling_the_cutoff_is_deleted(db_session, coord_setup, make_grid):
    """El slot LIBRE que cruza start_efectivo debe borrarse, no sobrevivir.

    Si sobrevive, la grilla nueva se crea encima y quedan dos slots libres
    solapados: dos alumnos reservan y el coordinador tiene citas encimadas.
    """
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(10, 30))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(12, 0), 5, ctx["program_ids"])

    assert plan.start_efectivo == time(10, 32)
    straddler = next(s for s in _slots_of(db_session, ctx["coord"].id)
                     if s.start_time == time(10, 30))
    assert straddler.id in plan.to_delete_ids, "10:30-10:40 cruza el corte y debe borrarse"


def test_live_appointment_pushes_the_cutoff_instead_of_being_shortened(
        db_session, coord_setup, make_grid, make_user, make_booking):
    """Acortar una cita que ya empezó es peor que no dividir el rango."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])
    en_curso = next(s for s in slots if s.start_time == time(10, 30))
    alum = make_user(first_name="EN", last_name="CURSO", control_number="20990400")
    make_booking(en_curso, alum, ctx["program_ids"][0], ctx["period"].id)

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(10, 30))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(12, 0), 5, ctx["program_ids"])

    assert plan.start_efectivo == time(10, 40)
    assert plan.to_shorten == [], "la cita en curso no debe acortarse"


def test_plan_produces_no_overlaps(db_session, coord_setup, make_grid):
    """Invariante global: nada de lo que sobrevive puede solapar con lo nuevo."""
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(10, 30))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(12, 0), 5, ctx["program_ids"])

    survivors = [(s.start_time, s.end_time) for s in _slots_of(db_session, ctx["coord"].id)
                 if s.id not in plan.to_delete_ids]
    intervals = sorted(survivors + plan.to_create)
    for (s1, e1), (s2, e2) in zip(intervals, intervals[1:]):
        assert e1 <= s2, f"solape entre {s1}-{e1} y {s2}-{e2}"


def test_range_fully_in_the_past_is_rejected(db_session, coord_setup, make_grid):
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(23, 0))):
        with pytest.raises(HTTPException) as exc:
            SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                   time(9, 0), time(10, 0), 5, ctx["program_ids"])
    assert "range_fully_in_past" in str(exc.value.detail)


def test_past_day_is_rejected(db_session, coord_setup):
    ctx = coord_setup(n_programs=1)
    with patch("itcj2.apps.agendatec.services.slot_service.now_app",
               return_value=app_dt(date(2026, 9, 2), time(10, 0))):
        with pytest.raises(HTTPException) as exc:
            SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                   time(9, 0), time(10, 0), 5, ctx["program_ids"])
    assert "day_in_past" in str(exc.value.detail)


# ===========================================================================
# plan_split — validación C1 / C2 / C3
# ===========================================================================
def test_10_to_5_with_a_booking_is_allowed(db_session, coord_setup, make_grid,
                                           make_user, make_booking):
    """El caso que pidió el usuario: 9:00-9:10 pasa a 9:00-9:05."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="A", last_name="UNO", control_number="20990401")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, ctx["program_ids"])

    assert plan.blocked is False
    assert len(plan.to_shorten) == 1
    assert plan.to_shorten[0].new_start == time(9, 0)
    assert plan.to_shorten[0].new_end == time(9, 5)
    assert len(plan.to_notify) == 1


def test_15_to_10_with_a_booking_is_now_allowed(db_session, coord_setup, make_grid,
                                                make_user, make_booking):
    """La regla vieja lo rechazaba; la de bloques lo permite.

    9:15 no cae en la rejilla de 10 anclada en 9:00, pero eso ya no importa: la
    cita es un ancla inamovible, conserva su 9:15 y solo se acorta a 9:15-9:25.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="A", last_name="DOS", control_number="20990402")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)
    rid = reservado.id

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 10, ctx["program_ids"])

    assert plan.blocked is False
    acortado = next(x for x in plan.to_shorten if x.slot_id == rid)
    assert acortado.new_start == time(9, 15), "la hora de entrada no se mueve"
    assert acortado.new_end == time(9, 25)


def test_a_booking_that_cannot_shrink_is_kept_as_is(db_session, coord_setup, make_grid,
                                                    make_user, make_booking):
    """5 -> 10 no puede acortar una cita de 5 min, pero ya no rechaza el rango.

    Esa cita conserva su geometria y se reporta en kept_as_is; el resto del
    rango si se re-divide.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 5, ctx["program_ids"])
    alum = make_user(first_name="A", last_name="TRES", control_number="20990403")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)
    rid = slots[0].id

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 10, ctx["program_ids"])

    assert plan.blocked is False, "una cita que no encaja ya no bloquea el rango"
    assert [k.slot_id for k in plan.kept_as_is] == [rid]
    assert rid not in [x.slot_id for x in plan.to_shorten], "no se alarga"
    assert plan.to_create, "el resto del rango si se re-divide"


def test_c2_only_applies_when_the_slot_actually_changes(db_session, coord_setup, make_grid,
                                                        make_user, make_booking):
    """Recortar la cola vacía no debe rechazarse por un slot que no cambia.

    Reservado 09:50-10:00, se reenvía 09:00-09:55 @10. C1 ok, C3 ok, y C2
    (10:00 <= 09:55) fallaría si se evaluara incondicionalmente.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    ultimo = next(s for s in slots if s.start_time == time(9, 50))
    alum = make_user(first_name="A", last_name="CUATRO", control_number="20990404")
    make_booking(ultimo, alum, ctx["program_ids"][0], ctx["period"].id)

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(9, 55), 10, ctx["program_ids"])

    assert plan.blocked is False
    assert plan.to_shorten == []


def test_done_appointment_is_shortened_but_not_notified(db_session, coord_setup, make_grid,
                                                        make_user, make_booking):
    """DONE y NO_SHOW dejan is_booked=True: hay que acortar, no notificar."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="A", last_name="CINCO", control_number="20990405")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id, ap_status="DONE")

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, ctx["program_ids"])

    assert len(plan.to_shorten) == 1, "el slot debe acortarse igual"
    assert plan.to_notify == [], "una cita ya atendida no se notifica"


def test_slot_with_canceled_appointment_is_preserved(db_session, coord_setup, make_grid,
                                                     make_user, make_booking):
    """El ON DELETE CASCADE destruiría historial: 89 filas asi en produccion."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="A", last_name="SEIS", control_number="20990406")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id,
                 ap_status="CANCELED", req_status="CANCELED")
    slots[0].is_booked = False          # cancelar libera el slot
    db_session.flush()

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, ctx["program_ids"])

    assert slots[0].id not in plan.to_delete_ids
    assert slots[0].id in plan.preserved_with_history


def test_out_of_scope_appointments_are_reported(db_session, coord_setup, make_grid,
                                                make_user, make_booking):
    """El coordinador debe ver a quién deja fuera antes de confirmar."""
    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="A", last_name="SIETE", control_number="20990407")
    make_booking(slots[0], alum, ctx["program_ids"][1], ctx["period"].id)

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, [ctx["program_ids"][0]])

    assert len(plan.out_of_scope) == 1
    assert plan.out_of_scope[0].student_id == alum.id


# ===========================================================================
# apply_split
# ===========================================================================
def test_apply_shortens_the_booking_and_frees_the_gap(db_session, coord_setup, make_grid,
                                                      make_user, make_booking):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="B", last_name="UNO", control_number="20990410")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)
    reservado_id = slots[0].id

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, ctx["program_ids"])
        result = SlotService.apply_split(db_session, ctx["coord"].id, DAY, plan,
                                         ctx["program_ids"])
    db_session.flush()

    reservado = db_session.get(TimeSlot, reservado_id)
    assert reservado.end_time == time(9, 5)
    assert reservado.is_booked is True
    hueco = next(s for s in _slots_of(db_session, ctx["coord"].id) if s.start_time == time(9, 5))
    assert hueco.end_time == time(9, 10) and hueco.is_booked is False
    assert result.slots_shortened == 1


def test_apply_never_leaves_overlapping_slots(db_session, coord_setup, make_grid,
                                              make_user, make_booking):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="B", last_name="DOS", control_number="20990411")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, ctx["program_ids"])
        SlotService.apply_split(db_session, ctx["coord"].id, DAY, plan, ctx["program_ids"])
    db_session.flush()

    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_apply_respects_the_live_cutoff(db_session, coord_setup, make_grid):
    """Lo anterior a start_efectivo queda intacto: ni se borra ni se re-divide."""
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])

    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(10, 30))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(12, 0), 5, ctx["program_ids"])
        SlotService.apply_split(db_session, ctx["coord"].id, DAY, plan, ctx["program_ids"])
    db_session.flush()

    todos = _slots_of(db_session, ctx["coord"].id)
    antes = [s for s in todos if s.start_time < time(10, 30)]
    assert all((s.end_time.hour * 60 + s.end_time.minute)
               - (s.start_time.hour * 60 + s.start_time.minute) == 10 for s in antes), \
        "los slots anteriores al corte deben conservar sus 10 minutos"
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_apply_grandfathers_the_program_of_a_live_appointment(db_session, coord_setup, make_grid,
                                                              make_user, make_booking):
    """La cita viva conserva su carrera aunque el coordinador la excluya."""
    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="B", last_name="TRES", control_number="20990412")
    excluida = ctx["program_ids"][1]
    make_booking(slots[0], alum, excluida, ctx["period"].id)
    reservado_id = slots[0].id

    solo_primera = [ctx["program_ids"][0]]
    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, solo_primera)
        SlotService.apply_split(db_session, ctx["coord"].id, DAY, plan, solo_primera)
    db_session.flush()

    scope = {r.program_id for r in
             db_session.query(TimeSlotProgram).filter_by(slot_id=reservado_id).all()}
    assert excluida in scope, "la carrera de la cita viva debe conservarse"
    assert solo_primera[0] in scope


def test_reconcile_restores_the_window_scope_on_release(db_session, coord_setup, make_grid,
                                                        make_user, make_booking):
    """Al liberarse el slot grandfathered, deja de ofrecer la carrera excluida.

    `reconcile_slot_programs` lee el scope de la VENTANA, que es la fuente de
    verdad. `apply_split` no la reescribe a propósito: eso lo hace el endpoint,
    que reemplaza la ventana con el scope nuevo. Aquí se simula ese paso.
    """
    from itcj2.apps.agendatec.models import AvailabilityWindowProgram

    ctx = coord_setup(n_programs=3)
    window, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="B", last_name="CUATRO", control_number="20990413")
    excluida = ctx["program_ids"][1]
    make_booking(slots[0], alum, excluida, ctx["period"].id)
    reservado_id = slots[0].id

    solo_primera = [ctx["program_ids"][0]]
    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))):
        plan = SlotService.plan_split(db_session, ctx["coord"].id, DAY,
                                      time(9, 0), time(10, 0), 5, solo_primera)
        SlotService.apply_split(db_session, ctx["coord"].id, DAY, plan, solo_primera)

    # Lo que hace el endpoint tras apply_split: la ventana pasa a tener el
    # scope nuevo.
    db_session.query(AvailabilityWindowProgram).filter_by(window_id=window.id).delete(
        synchronize_session=False)
    for pid in solo_primera:
        db_session.add(AvailabilityWindowProgram(window_id=window.id, program_id=pid))
    db_session.flush()

    # La carrera excluida sobrevive mientras la cita esté viva.
    scope_antes = {r.program_id for r in
                   db_session.query(TimeSlotProgram).filter_by(slot_id=reservado_id).all()}
    assert excluida in scope_antes

    slot = db_session.get(TimeSlot, reservado_id)
    slot.is_booked = False
    SlotService.reconcile_slot_programs(db_session, slot)
    db_session.flush()

    scope = {r.program_id for r in
             db_session.query(TimeSlotProgram).filter_by(slot_id=reservado_id).all()}
    assert scope == set(solo_primera), \
        "el slot liberado no debe seguir ofreciendo la carrera excluida"

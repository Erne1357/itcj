"""POST/GET/DELETE /coord/day-config: split, scope y preview.

El endpoint dejó de rechazar rangos con reservas: ahora acorta las citas
conservando su hora de inicio y notifica al alumno.
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from itcj2.apps.agendatec.helpers import app_dt
from itcj2.apps.agendatec.models import TimeSlot, TimeSlotProgram
from itcj2.core.models.notification import Notification

DAY = date(2026, 9, 1)
DAY_S = "2026-09-01"


def _at(t):
    return app_dt(DAY, t)


@pytest.fixture()
def frozen_morning():
    """Congela `now_app` a las 08:00 del día de prueba en TODOS los módulos que lo usan."""
    with patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=_at(time(8, 0))), \
         patch("itcj2.apps.agendatec.api.coord.day_config.now_app", return_value=_at(time(8, 0))):
        yield


def _slots(db, coord_id):
    return (db.query(TimeSlot)
            .filter_by(coordinator_id=coord_id, day=DAY)
            .order_by(TimeSlot.start_time).all())


def _assert_no_overlaps(db, coord_id):
    slots = _slots(db, coord_id)
    for a, b in zip(slots, slots[1:]):
        assert a.end_time <= b.start_time, \
            f"solape {a.start_time}-{a.end_time} / {b.start_time}-{b.end_time}"


# ===========================================================================
# Split
# ===========================================================================
def test_split_10_to_5_keeps_the_booking(client, db_session, coord_setup, make_grid,
                                         make_user, make_booking, frozen_morning):
    """El caso que pidió el usuario: 9:00-9:10 pasa a 9:00-9:05, se libera 9:05-9:10."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="C", last_name="UNO", control_number="20990500")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)
    reservado_id = slots[0].id

    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
    })
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    reservado = db_session.get(TimeSlot, reservado_id)
    assert reservado.end_time == time(9, 5)
    assert reservado.is_booked is True

    hueco = next(s for s in _slots(db_session, ctx["coord"].id) if s.start_time == time(9, 5))
    assert hueco.end_time == time(9, 10) and hueco.is_booked is False
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_split_notifies_the_affected_student(client, db_session, coord_setup, make_grid,
                                             make_user, make_booking, frozen_morning):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="C", last_name="DOS", control_number="20990501")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
    })

    n = (db_session.query(Notification)
         .filter_by(user_id=alum.id, type="APPOINTMENT_RESCHEDULED").one())
    assert n.data["url"] == "/agendatec/student/requests"
    assert n.data["old_end"] == "09:10"
    assert n.data["new_end"] == "09:05"


def test_regenerating_the_same_duration_notifies_nobody(client, db_session, coord_setup,
                                                        make_grid, make_user, make_booking,
                                                        frozen_morning):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="C", last_name="TRES", control_number="20990502")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    assert resp.status_code == 200
    assert resp.json()["appointments_notified"] == 0
    assert db_session.query(Notification).filter_by(
        type="APPOINTMENT_RESCHEDULED").count() == 0


def test_misaligned_split_is_rejected_with_offenders(client, coord_setup, make_grid,
                                                     make_user, make_booking, frozen_morning):
    """15 -> 10 con una cita en 9:15: no cae en la grilla nueva."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="C", last_name="CUATRO", control_number="20990503")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    assert resp.status_code == 409
    body = resp.json()
    # JSONResponse plano: NO el {"error": {...}} anidado del handler global.
    assert body["error"] == "misaligned_booked_slots"
    assert body["offenders"][0]["reason"] == "not_on_grid"
    assert body["offenders"][0]["start"] == "09:15"


def test_rejected_split_mutates_nothing(client, db_session, coord_setup, make_grid,
                                        make_user, make_booking, frozen_morning):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="C", last_name="CINCO", control_number="20990504")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)

    antes = [(s.start_time, s.end_time) for s in _slots(db_session, ctx["coord"].id)]
    client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    db_session.expire_all()
    despues = [(s.start_time, s.end_time) for s in _slots(db_session, ctx["coord"].id)]
    assert antes == despues


def test_empty_range_generates_the_grid(client, db_session, coord_setup, frozen_morning):
    ctx = coord_setup(n_programs=1)
    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["slots_created"] == 6
    assert len(_slots(db_session, ctx["coord"].id)) == 6


def test_live_split_respects_the_cutoff(client, db_session, coord_setup, make_grid):
    """A las 10:30, un split de 09:00-12:00 solo toca de las 10:32 en adelante."""
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])

    with patch("itcj2.apps.agendatec.services.slot_service.now_app",
               return_value=_at(time(10, 30))), \
         patch("itcj2.apps.agendatec.api.coord.day_config.now_app",
               return_value=_at(time(10, 30))):
        resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
            "day": DAY_S, "start": "09:00", "end": "12:00", "slot_minutes": 5,
        })
    assert resp.status_code == 200, resp.text
    assert resp.json()["start_efectivo"] == "10:32"

    db_session.expire_all()
    antes = [s for s in _slots(db_session, ctx["coord"].id) if s.start_time < time(10, 30)]
    assert all(
        (s.end_time.hour * 60 + s.end_time.minute)
        - (s.start_time.hour * 60 + s.start_time.minute) == 10
        for s in antes
    ), "lo anterior al corte debe conservar sus 10 minutos"
    _assert_no_overlaps(db_session, ctx["coord"].id)


# ===========================================================================
# Scope
# ===========================================================================
def test_scope_limits_the_range_to_selected_programs(client, db_session, coord_setup,
                                                     frozen_morning):
    ctx = coord_setup(n_programs=3)
    solo = [ctx["program_ids"][0]]
    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
        "programs": solo,
    })
    assert resp.status_code == 200, resp.text

    slot = _slots(db_session, ctx["coord"].id)[0]
    rows = db_session.query(TimeSlotProgram).filter_by(slot_id=slot.id).all()
    assert [r.program_id for r in rows] == solo


def test_no_programs_means_all(client, db_session, coord_setup, frozen_morning):
    """El default preserva el comportamiento anterior."""
    ctx = coord_setup(n_programs=3)
    client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    slot = _slots(db_session, ctx["coord"].id)[0]
    rows = db_session.query(TimeSlotProgram).filter_by(slot_id=slot.id).all()
    assert sorted(r.program_id for r in rows) == sorted(ctx["program_ids"])


def test_foreign_program_is_rejected(client, coord_setup, make_program, frozen_morning):
    ctx = coord_setup(n_programs=1)
    ajena = make_program("Carrera Ajena DC")
    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
        "programs": [ajena.id],
    })
    assert resp.status_code == 400


# ===========================================================================
# Preview
# ===========================================================================
def test_preview_reports_affected_without_mutating(client, db_session, coord_setup, make_grid,
                                                   make_user, make_booking, frozen_morning):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="D", last_name="UNO", control_number="20990510")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)
    reservado_id = slots[0].id

    resp = client.post("/api/agendatec/v2/coord/day-config/preview",
                       headers=ctx["headers"], json={
                           "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
                       })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["blocked"] is False
    assert len(body["appointments_affected"]) == 1
    assert body["appointments_affected"][0]["old"] == "09:00–09:10"
    assert body["appointments_affected"][0]["new"] == "09:00–09:05"

    db_session.expire_all()
    assert db_session.get(TimeSlot, reservado_id).end_time == time(9, 10), \
        "preview no debe mutar nada"


def test_preview_reports_offenders_when_blocked(client, coord_setup, make_grid,
                                                make_user, make_booking, frozen_morning):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="D", last_name="DOS", control_number="20990511")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config/preview",
                       headers=ctx["headers"], json={
                           "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
                       })
    assert resp.status_code == 200
    assert resp.json()["blocked"] is True


def test_preview_reports_out_of_scope_appointments(client, coord_setup, make_grid,
                                                   make_user, make_booking, frozen_morning):
    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="D", last_name="TRES", control_number="20990512")
    make_booking(slots[0], alum, ctx["program_ids"][1], ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config/preview",
                       headers=ctx["headers"], json={
                           "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
                           "programs": [ctx["program_ids"][0]],
                       })
    assert resp.status_code == 200
    assert len(resp.json()["out_of_scope_appointments"]) == 1


# ===========================================================================
# GET y DELETE
# ===========================================================================
def test_get_day_config_includes_programs(client, coord_setup, make_grid, frozen_morning):
    ctx = coord_setup(n_programs=2)
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])

    resp = client.get(f"/api/agendatec/v2/coord/day-config?day={DAY_S}", headers=ctx["headers"])
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert len(item["programs"]) == 2
    assert set(item["programs"][0]) >= {"id", "name"}


def test_delete_preserves_slots_with_history(client, db_session, coord_setup, make_grid,
                                             make_user, make_booking, frozen_morning):
    """El ON DELETE CASCADE destruiría las citas CANCELED que viven encima."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="E", last_name="UNO", control_number="20990520")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id,
                 ap_status="CANCELED", req_status="CANCELED")
    slots[0].is_booked = False
    db_session.flush()
    con_historial = slots[0].id

    resp = client.request("DELETE", "/api/agendatec/v2/coord/day-config",
                          headers=ctx["headers"],
                          json={"day": DAY_S, "start": "09:00", "end": "10:00"})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert db_session.get(TimeSlot, con_historial) is not None


def test_delete_rejects_when_there_are_bookings(client, coord_setup, make_grid,
                                                make_user, make_booking, frozen_morning):
    """Borrar un rango con citas vivas sigue siendo 409: es destructivo."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="E", last_name="DOS", control_number="20990521")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    resp = client.request("DELETE", "/api/agendatec/v2/coord/day-config",
                          headers=ctx["headers"],
                          json={"day": DAY_S, "start": "09:00", "end": "10:00"})
    assert resp.status_code == 409
    assert resp.json()["error"] == "overlap_booked_slots_exist"

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
    # Acotado al alumno del test: sin el filtro, cuenta también las
    # notificaciones reales de la BD de dev y falla en cuanto alguien usa el
    # feature en su navegador.
    assert db_session.query(Notification).filter_by(
        user_id=alum.id, type="APPOINTMENT_RESCHEDULED").count() == 0


def test_misaligned_split_is_now_applied(client, db_session, coord_setup, make_grid,
                                         make_user, make_booking, frozen_morning):
    """15 -> 10 con una cita en 9:15 ya no devuelve 409.

    La cita conserva su hora de entrada y se acorta a 9:15-9:25; el resto del
    rango se re-divide alrededor.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    reservado = next(s for s in slots if s.start_time == time(9, 15))
    alum = make_user(first_name="C", last_name="CUATRO", control_number="20990503")
    make_booking(reservado, alum, ctx["program_ids"][0], ctx["period"].id)
    rid = reservado.id

    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
    })
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    s_res = db_session.get(TimeSlot, rid)
    assert (s_res.start_time, s_res.end_time) == (time(9, 15), time(9, 25))
    _assert_no_overlaps(db_session, ctx["coord"].id)


def test_range_fully_in_the_past_mutates_nothing(client, db_session, coord_setup, make_grid):
    """Sustituye al viejo test de rechazo: ya no hay 409 por desalineacion.

    El unico rechazo que queda en el camino normal es el rango que ya paso.
    """
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 15, ctx["program_ids"])
    antes = [(s.start_time, s.end_time) for s in _slots(db_session, ctx["coord"].id)]

    with patch("itcj2.apps.agendatec.services.slot_service.now_app",
               return_value=_at(time(23, 0))),          patch("itcj2.apps.agendatec.api.coord.day_config.now_app",
               return_value=_at(time(23, 0))):
        resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
            "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
        })
    assert resp.status_code == 400
    assert "range_fully_in_past" in resp.text

    db_session.expire_all()
    despues = [(s.start_time, s.end_time) for s in _slots(db_session, ctx["coord"].id)]
    assert antes == despues


def test_preview_and_post_agree_on_the_exact_slots(client, db_session, coord_setup, make_grid,
                                                   make_user, make_booking, frozen_morning):
    """El preview promete horarios concretos; el POST debe crear ESOS.

    Antes apply_split re-derivaba la rejilla, asi que con citas desalineadas
    prometia unos horarios y creaba otros -- con el mismo conteo, que es lo que
    hacia que los tests no lo vieran.
    """
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_user(first_name="C", last_name="SEIS", control_number="20990506")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    cuerpo = {"day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 25}
    prev = client.post("/api/agendatec/v2/coord/day-config/preview",
                       headers=ctx["headers"], json=cuerpo)
    assert prev.status_code == 200, prev.text
    prometidos = prev.json()["slots_to_create"]

    post = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json=cuerpo)
    assert post.status_code == 200, post.text
    assert post.json()["slots_created"] == prometidos,         "el conteo del preview y el del POST tienen que coincidir"
    _assert_no_overlaps(db_session, ctx["coord"].id)


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


def test_preview_reports_what_could_not_change(client, coord_setup, make_grid,
                                               make_user, make_booking, frozen_morning):
    """Ya nada bloquea, pero el coordinador debe ver que bloques no cambiaron."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 5, ctx["program_ids"])
    alum = make_user(first_name="D", last_name="DOS", control_number="20990511")
    make_booking(slots[0], alum, ctx["program_ids"][0], ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config/preview",
                       headers=ctx["headers"], json={
                           "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 10,
                       })
    assert resp.status_code == 200
    body = resp.json()
    assert body["blocked"] is False
    assert len(body["kept_as_is"]) == 1
    assert body["kept_as_is"][0]["range"] == "09:00–09:05"


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


# ===========================================================================
# GET /coord/programs — alimenta el multi-select de scope
# ===========================================================================
def test_coord_programs_lists_own_programs(client, coord_setup):
    ctx = coord_setup(n_programs=3)
    resp = client.get("/api/agendatec/v2/coord/programs", headers=ctx["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert sorted(p["id"] for p in body["data"]) == sorted(ctx["program_ids"])
    assert all("name" in p for p in body["data"])


def test_coord_programs_excludes_other_coordinators_programs(client, coord_setup,
                                                             make_program, make_coordinator):
    ctx = coord_setup(n_programs=1)
    ajena = make_program("Carrera De Otro CP")
    make_coordinator([ajena.id], first_name="OTRO", last_name="CP")

    resp = client.get("/api/agendatec/v2/coord/programs", headers=ctx["headers"])
    assert resp.status_code == 200
    assert ajena.id not in [p["id"] for p in resp.json()["data"]]


# ===========================================================================
# Duraciones libres: cualquier entero de 5 a 60
# ===========================================================================
@pytest.mark.parametrize("minutos", [5, 7, 13, 25, 59, 60])
def test_arbitrary_durations_are_accepted(client, coord_setup, minutos, frozen_morning):
    """Antes solo se aceptaba el conjunto fijo 5/10/15/20/30/60."""
    ctx = coord_setup(n_programs=1)
    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "11:00", "slot_minutes": minutos,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["slots_created"] == 120 // minutos


@pytest.mark.parametrize("minutos", [0, -5, 4, 61, 1000])
def test_durations_outside_the_bounds_are_rejected(client, coord_setup, minutos,
                                                   frozen_morning):
    """El 0 y los negativos son los peligrosos: colgarían el generador."""
    ctx = coord_setup(n_programs=1)
    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "11:00", "slot_minutes": minutos,
    })
    assert resp.status_code in (400, 422), resp.text


def test_a_day_can_mix_durations_across_ranges(client, db_session, coord_setup,
                                               frozen_morning):
    """Dos rangos del mismo día con duraciones distintas conviven sin solaparse."""
    ctx = coord_setup(n_programs=1)
    for inicio, fin, mins in (("09:00", "10:00", 10), ("10:00", "11:00", 7)):
        r = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
            "day": DAY_S, "start": inicio, "end": fin, "slot_minutes": mins,
        })
        assert r.status_code == 200, r.text

    db_session.expire_all()
    todos = _slots(db_session, ctx["coord"].id)
    dur = lambda s: (s.end_time.hour * 60 + s.end_time.minute) - (s.start_time.hour * 60 + s.start_time.minute)  # noqa: E731
    assert {dur(s) for s in todos if s.start_time < time(10, 0)} == {10}
    assert {dur(s) for s in todos if s.start_time >= time(10, 0)} == {7}
    _assert_no_overlaps(db_session, ctx["coord"].id)

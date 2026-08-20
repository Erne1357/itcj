"""Scope por carrera: qué ve el alumno y qué puede reservar.

Sin endurecer la validación de reserva, el scope sería cosmético: un POST
armado a mano reservaría un slot fuera de scope igual.
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from itcj2.apps.agendatec.helpers import app_dt
from tests.conftest import make_jwt

DAY = date(2026, 9, 1)
DAY_S = "2026-09-01"


@pytest.fixture()
def frozen_morning():
    """Congela `now_app` a las 08:00 del día de prueba.

    Hay que parchear CADA módulo que lo importó por nombre: `from ... import
    now_app` copia la referencia, así que parchear solo el origen no los
    alcanza. `request_service` lo importa dentro de la función, y ahí sí basta
    con el origen.
    """
    frozen = app_dt(DAY, time(8, 0))
    with patch("itcj2.apps.agendatec.helpers.now_app", return_value=frozen), \
         patch("itcj2.apps.agendatec.services.slot_service.now_app", return_value=frozen), \
         patch("itcj2.apps.agendatec.api.coord.day_config.now_app", return_value=frozen), \
         patch("itcj2.apps.agendatec.api.availability.now_app", return_value=frozen), \
         patch("itcj2.apps.agendatec.api.admin.requests.now_app", return_value=frozen):
        yield


def _student_headers(student):
    return {"Cookie": f"itcj_token={make_jwt(user_id=student.id, role='student')}"}


def _slots_for(client, program_id, headers):
    resp = client.get(
        f"/api/agendatec/v2/availability/program/{program_id}/slots?day={DAY_S}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ===========================================================================
# Listado
# ===========================================================================
def test_student_of_a_scoped_program_sees_the_slots(client, coord_setup, make_grid,
                                                    make_student, frozen_morning):
    ctx = coord_setup(n_programs=3)
    industrial = ctx["program_ids"][0]
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    alum = make_student("20990600", first_name="F", last_name="UNO")

    items = _slots_for(client, industrial, _student_headers(alum))
    assert len(items) == 6


def test_student_of_an_excluded_program_sees_nothing(client, coord_setup, make_grid,
                                                     make_student, frozen_morning):
    """El coordinador dijo 'de 9 a 10 solo con Industrial'."""
    ctx = coord_setup(n_programs=3)
    industrial, mecatronica = ctx["program_ids"][0], ctx["program_ids"][1]
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    alum = make_student("20990601", first_name="F", last_name="DOS")

    assert _slots_for(client, mecatronica, _student_headers(alum)) == []


def test_without_scope_every_program_sees_the_slots(client, coord_setup, make_grid,
                                                    make_student, frozen_morning):
    """Paridad con el comportamiento anterior al feature."""
    ctx = coord_setup(n_programs=3)
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_student("20990602", first_name="F", last_name="TRES")
    headers = _student_headers(alum)

    for pid in ctx["program_ids"]:
        assert len(_slots_for(client, pid, headers)) == 6


def test_two_coordinators_of_the_same_program_are_unioned(client, coord_setup, make_grid,
                                                          make_coordinator, make_student,
                                                          frozen_morning):
    """Uno limita el rango y el otro no: el alumno ve la unión."""
    ctx = coord_setup(n_programs=2)
    industrial = ctx["program_ids"][0]
    # El primero solo ofrece Industrial de 9 a 10.
    make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    # El segundo coordina la misma carrera y ofrece 11 a 12 sin limitar.
    otro, _ = make_coordinator([industrial], first_name="SEGUNDO", last_name="COORD")
    make_grid(otro.id, time(11, 0), time(12, 0), 10, [industrial])

    alum = make_student("20990603", first_name="F", last_name="CUATRO")
    items = _slots_for(client, industrial, _student_headers(alum))
    assert len(items) == 12
    assert {i["coordinator_id"] for i in items} == {ctx["coord"].id, otro.id}


def test_past_slots_are_not_offered(client, coord_setup, make_grid, make_student):
    """Antes se ofrecían y el alumno solo se enteraba al confirmar."""
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(9, 0), time(12, 0), 10, ctx["program_ids"])
    alum = make_student("20990604", first_name="F", last_name="CINCO")

    with patch("itcj2.apps.agendatec.api.availability.now_app",
               return_value=app_dt(DAY, time(10, 30))):
        items = _slots_for(client, ctx["program_ids"][0], _student_headers(alum))

    assert items, "debe seguir habiendo slots futuros"
    assert all(i["start_time"] > "10:30" for i in items)


# ===========================================================================
# Reserva — el scope no puede ser cosmético
# ===========================================================================
def test_direct_post_outside_scope_is_rejected(client, coord_setup, make_grid,
                                               make_student, frozen_morning,
                                               patched_session_local):
    """Un alumno que arma el POST a mano no debe poder saltarse el scope."""
    ctx = coord_setup(n_programs=3)
    industrial, mecatronica = ctx["program_ids"][0], ctx["program_ids"][1]
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    alum = make_student("20990610", first_name="G", last_name="UNO")

    resp = client.post("/api/agendatec/v2/requests", headers=_student_headers(alum), json={
        "type": "APPOINTMENT", "program_id": mecatronica, "slot_id": slots[0].id,
        "description": "intento fuera de scope",
    })
    assert resp.status_code in (400, 403), resp.text
    assert "slot_not_for_program" in resp.text


def test_post_inside_scope_succeeds(client, coord_setup, make_grid, make_student,
                                    frozen_morning, patched_session_local):
    ctx = coord_setup(n_programs=3)
    industrial = ctx["program_ids"][0]
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    alum = make_student("20990611", first_name="G", last_name="DOS")

    resp = client.post("/api/agendatec/v2/requests", headers=_student_headers(alum), json={
        "type": "APPOINTMENT", "program_id": industrial, "slot_id": slots[0].id,
        "description": "dentro de scope",
    })
    assert resp.status_code == 201, resp.text


def test_admin_cannot_book_outside_scope(client, coord_setup, make_grid, make_student,
                                         auth_headers, frozen_morning):
    """El camino admin duplicaba el check y evadía el scope."""
    ctx = coord_setup(n_programs=3)
    industrial, mecatronica = ctx["program_ids"][0], ctx["program_ids"][1]
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, [industrial])
    alum = make_student("20990612", first_name="G", last_name="TRES")

    resp = client.post("/api/agendatec/v2/admin/requests/create", headers=auth_headers, json={
        "type": "APPOINTMENT", "student_id": alum.id, "program_id": mecatronica,
        "slot_id": slots[0].id, "description": "alta admin fuera de scope",
    })
    assert resp.status_code == 400, resp.text
    assert "slot_not_for_program" in resp.text


# ===========================================================================
# Grandfathering y reconciliación
# ===========================================================================
def test_existing_appointment_survives_a_scope_restriction(client, db_session, coord_setup,
                                                           make_grid, make_student, make_booking,
                                                           frozen_morning):
    """Limitar el rango no cancela las citas que ya existían."""
    from itcj2.apps.agendatec.models import Appointment

    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_student("20990620", first_name="H", last_name="UNO")
    excluida = ctx["program_ids"][1]
    _, ap = make_booking(slots[0], alum, excluida, ctx["period"].id)

    resp = client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
        "programs": [ctx["program_ids"][0]],
    })
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert db_session.get(Appointment, ap.id).status == "SCHEDULED"


def test_canceling_a_grandfathered_appointment_restores_the_scope(
        client, db_session, coord_setup, make_grid, make_student, make_booking, frozen_morning):
    """Al liberarse, el slot deja de ofrecer la carrera excluida."""
    from itcj2.apps.agendatec.models import TimeSlot, TimeSlotProgram

    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    alum = make_student("20990621", first_name="H", last_name="DOS")
    excluida = ctx["program_ids"][1]
    req, _ = make_booking(slots[0], alum, excluida, ctx["period"].id)
    reservado_id = slots[0].id

    client.post("/api/agendatec/v2/coord/day-config", headers=ctx["headers"], json={
        "day": DAY_S, "start": "09:00", "end": "10:00", "slot_minutes": 5,
        "programs": [ctx["program_ids"][0]],
    })

    # El coordinador cancela la solicitud: el slot se libera.
    resp = client.patch(f"/api/agendatec/v2/coord/requests/{req.id}/status",
                        headers=ctx["headers"], json={"status": "CANCELED"})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert db_session.get(TimeSlot, reservado_id).is_booked is False
    scope = {r.program_id for r in
             db_session.query(TimeSlotProgram).filter_by(slot_id=reservado_id).all()}
    assert scope == {ctx["program_ids"][0]}, \
        "el slot liberado no debe seguir ofreciendo la carrera excluida"


# ===========================================================================
# Endpoints retirados
# ===========================================================================
def test_generate_slots_endpoint_is_gone(client, coord_setup):
    """Generaba slots de TODOS los coordinadores, sin filtrar por el que llama."""
    ctx = coord_setup(n_programs=1)
    resp = client.post("/api/agendatec/v2/availability/generate-slots",
                       headers=ctx["headers"], json={"day": DAY_S})
    assert resp.status_code == 410, resp.text


def test_create_window_endpoint_is_gone(client, coord_setup):
    """Creaba la ventana sin sus slots ni su scope: configuración a medias."""
    ctx = coord_setup(n_programs=1)
    resp = client.post("/api/agendatec/v2/availability/windows", headers=ctx["headers"],
                       json={"day": DAY_S, "start": "09:00", "end": "10:00"})
    assert resp.status_code == 410, resp.text

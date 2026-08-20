"""El harness de agendatec funciona.

Si estos fallan, cualquier otro test del módulo falla por el motivo equivocado
(fixture inexistente, app sin sembrar, sesión no compartida) y el ciclo TDD
deja de tener valor.
"""
from datetime import date, time

from itcj2.apps.agendatec.models import AvailabilityWindow, TimeSlot


def test_agendatec_app_is_seeded(db_session, agendatec_app):
    """core_apps necesita la fila o require_app/require_perms no resuelven."""
    assert agendatec_app.key == "agendatec"
    assert agendatec_app.id is not None


def test_client_shares_session_with_fixtures(client, db_session, make_program):
    """El endpoint debe VER lo que crean las factories.

    Sin el override de get_db, la app abre otra sesión contra otro pool y las
    filas del test le son invisibles.
    """
    p = make_program("Carrera Harness")
    resp = client.get(f"/api/agendatec/v2/programs/{p.id}/coordinator")
    # 200 (sin coordinadores) o 401 (sin cookie), pero NUNCA 404: eso
    # significaría que el endpoint no encontró el programa que acabamos de crear.
    assert resp.status_code != 404, resp.text


def test_make_grid_creates_window_and_slots(db_session, coord_setup, make_grid):
    ctx = coord_setup(n_programs=3)
    w, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])

    assert w.slot_minutes == 10
    assert len(slots) == 6
    assert slots[0].start_time == time(9, 0)
    assert slots[0].end_time == time(9, 10)
    assert slots[-1].end_time == time(10, 0)
    assert all(s.is_booked is False for s in slots)

    assert db_session.query(AvailabilityWindow).filter_by(id=w.id).count() == 1
    assert db_session.query(TimeSlot).filter_by(coordinator_id=ctx["coord"].id).count() == 6


def test_make_booking_marks_slot_and_creates_appointment(db_session, coord_setup,
                                                         make_grid, make_user, make_booking):
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])
    student = make_user(first_name="ALUM", last_name="NO", control_number="20990001")

    req, ap = make_booking(slots[0], student, ctx["program_ids"][0], ctx["period"].id)

    assert slots[0].is_booked is True
    assert ap.slot_id == slots[0].id
    assert ap.status == "SCHEDULED"
    assert req.type == "APPOINTMENT"
    assert req.status == "PENDING"


def test_coord_setup_gives_three_programs(coord_setup):
    ctx = coord_setup(n_programs=3)
    assert len(ctx["program_ids"]) == 3
    assert ctx["headers"]["Cookie"].startswith("itcj_token=")
    assert ctx["period"].status == "ACTIVE"


# Día que la BD de dev no puede tener: el aislamiento se comprueba sobre datos
# exclusivamente nuestros. Filtrar por hora no sirve — el dump real ya trae
# slots de las 14:00.
_ISOLATION_DAY = date(2099, 1, 1)


def test_rollback_isolates_tests(db_session, coord_setup, make_grid):
    """Lo que este test crea NO debe sobrevivir al siguiente.

    Se apoya en que test_no_leftovers_from_previous_test corre después y no ve
    nada en `_ISOLATION_DAY`.
    """
    ctx = coord_setup(n_programs=1)
    make_grid(ctx["coord"].id, time(14, 0), time(15, 0), 20, ctx["program_ids"],
              day=_ISOLATION_DAY)
    assert db_session.query(TimeSlot).filter_by(day=_ISOLATION_DAY).count() == 3


def test_no_leftovers_from_previous_test(db_session):
    """Corre después del anterior; sus slots de 2099 no deben existir."""
    leftover = db_session.query(TimeSlot).filter_by(day=_ISOLATION_DAY).count()
    assert leftover == 0, "db_session no revirtió: los tests se contaminan entre sí"

"""Tablas puente del scope por carrera.

`agendatec_availability_window_programs` es la CONFIG que guardó el
coordinador; `agendatec_time_slot_programs` es su proyección materializada,
que es lo que consulta la query del alumno.

El default ("todas las carreras del coordinador") se materializa como filas
EXPLÍCITAS, no como ausencia de filas: así la query del alumno es un INNER
JOIN sin `OR NOT EXISTS`, y el backfill preserva el comportamiento anterior
exactamente.
"""
from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from itcj2.apps.agendatec.models import (
    AvailabilityWindow,
    AvailabilityWindowProgram,
    TimeSlot,
    TimeSlotProgram,
)


def test_models_are_mapped():
    assert TimeSlotProgram.__tablename__ == "agendatec_time_slot_programs"
    assert AvailabilityWindowProgram.__tablename__ == "agendatec_availability_window_programs"


def test_models_are_registered_in_the_global_registry():
    """Si no están en itcj2/models/__init__.py, el autogenerate de Alembic no los ve."""
    import itcj2.models as registry

    assert hasattr(registry, "TimeSlotProgram")
    assert hasattr(registry, "AvailabilityWindowProgram")


def test_slot_program_roundtrip(db_session, coord_setup, make_grid):
    ctx = coord_setup(n_programs=2)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(9, 30), 10, ctx["program_ids"])

    rows = (
        db_session.query(TimeSlotProgram)
        .filter(TimeSlotProgram.slot_id.in_([s.id for s in slots]))
        .all()
    )
    # 3 slots x 2 carreras
    assert len(rows) == 6
    assert {r.program_id for r in rows} == set(ctx["program_ids"])


def test_window_program_roundtrip(db_session, coord_setup, make_grid):
    ctx = coord_setup(n_programs=3)
    w, _ = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])

    rows = db_session.query(AvailabilityWindowProgram).filter_by(window_id=w.id).all()
    assert sorted(r.program_id for r in rows) == sorted(ctx["program_ids"])


def test_composite_pk_rejects_duplicates(db_session, coord_setup, make_grid):
    """La PK compuesta es lo que garantiza que el INNER JOIN no duplique filas."""
    ctx = coord_setup(n_programs=1)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(9, 10), 10, ctx["program_ids"])

    db_session.add(TimeSlotProgram(slot_id=slots[0].id, program_id=ctx["program_ids"][0]))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_deleting_a_slot_cascades_to_its_scope(db_session, coord_setup, make_grid):
    """El split borra slots con .delete(synchronize_session=False), que va a SQL
    directo: el CASCADE de la BD es quien limpia time_slot_programs."""
    ctx = coord_setup(n_programs=2)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(9, 20), 10, ctx["program_ids"])
    slot_id = slots[0].id

    db_session.query(TimeSlot).filter_by(id=slot_id).delete(synchronize_session=False)
    db_session.flush()

    assert db_session.query(TimeSlotProgram).filter_by(slot_id=slot_id).count() == 0


def test_deleting_a_window_cascades_to_its_scope(db_session, coord_setup, make_grid):
    ctx = coord_setup(n_programs=2)
    w, _ = make_grid(ctx["coord"].id, time(9, 0), time(9, 20), 10, ctx["program_ids"])
    win_id = w.id

    db_session.query(AvailabilityWindow).filter_by(id=win_id).delete(synchronize_session=False)
    db_session.flush()

    assert db_session.query(AvailabilityWindowProgram).filter_by(window_id=win_id).count() == 0


def test_scope_query_does_not_duplicate_rows(db_session, coord_setup, make_grid):
    """La query del alumno joinea con TimeSlotProgram filtrando por UN program_id.

    Con la PK compuesta, cada slot aporta como mucho una fila al join.
    """
    ctx = coord_setup(n_programs=3)
    _, slots = make_grid(ctx["coord"].id, time(9, 0), time(10, 0), 10, ctx["program_ids"])

    got = (
        db_session.query(TimeSlot)
        .join(TimeSlotProgram, TimeSlotProgram.slot_id == TimeSlot.id)
        .filter(
            TimeSlotProgram.program_id == ctx["program_ids"][0],
            TimeSlot.coordinator_id == ctx["coord"].id,
        )
        .all()
    )
    assert len(got) == len(slots) == 6
    assert len({s.id for s in got}) == 6

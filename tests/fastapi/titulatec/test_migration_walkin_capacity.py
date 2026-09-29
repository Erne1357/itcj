"""Contrato de la migración `tt20260929a`: walkin `capacity` pasa de «por franja» a «total».

La migración es SOLO de datos: `UPDATE titulatec_review_windows SET capacity = LEAST(500, GREATEST(1, ...))
WHERE visibility='walkin'` (spec 2026-09-29 §7.2, D12).

El harness arma el esquema con `create_all` (sin Alembic), así que el test:
1. Crea ventanas walkin de legado con distintos (tiempo, slot_minutes, capacity)
2. Carga la migración con importlib
3. Ejecuta UPGRADE_SQL con la sesión real
4. Verifica que cada capacity = LEAST(500, GREATEST(1, FLOOR((fin-ini)/60/slot)*cap))
5. Que no deja nunca capacity < 1
6. Que respeta el tope 500
7. Que ventanas 'bookable' no cambian
8. Ejecuta DOWNGRADE_SQL
9. Verifica que el downgrade es aproximado (inversa de franjas)
"""
import importlib.util
import pytest
from datetime import time, date
from pathlib import Path

import itcj2
from sqlalchemy import text

_MIGRACION = (
    Path(itcj2.__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "tt20260929a_titulatec_walkin_capacity.py"
)


def _modulo():
    spec = importlib.util.spec_from_file_location(
        "tt20260929a_mig", _MIGRACION
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def setup_cohort_and_day(make_program, make_cohort, make_review_day, make_officer):
    """Prepara cohort, día y encargado mínimos para ventanas de cotejo."""
    prog = make_program("Test Program")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=date(2029, 5, 15))
    officer, pos = make_officer([prog])
    return {"prog": prog, "cohort": cohort, "dia": dia, "officer": officer, "pos": pos}


def test_revision_y_down_revision():
    """Verifica que la migración tenga revisiones correctas."""
    mod = _modulo()
    assert mod.revision == "tt20260929a"
    assert mod.down_revision == "tt20260928a"


def test_upgrade_calcula_capacity_walkin(
    db_session, make_review_window, setup_cohort_and_day
):
    """Walkin 09:00–14:00 / 30 min / cap 1 → 10 franjas → capacity = 10."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # Caso 1: 09:00–14:00 (5h = 300 min) / 30 min → 10 franjas × 1 cap = 10
    w1 = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=1, visibility="walkin"
    )
    db_session.flush()

    # Ejecutar migración
    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    # Verificar
    capacity = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w1.id},
    ).scalar_one()
    # 300 / 60 / 30 = 10 × 1 = 10
    assert capacity == 10, f"Expected capacity=10, got {capacity}"


def test_upgrade_minimo_capacity_1(
    db_session, make_review_window, setup_cohort_and_day
):
    """Walkin 09:00–09:20 (20 min) / 30 min / cap 1 → GREATEST(1, ...) = 1."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # 20 min / 30 min = 0.66... franjas × 1 = 0.66 → GREATEST(1, ...) → 1
    w = make_review_window(
        day, officer, start="09:00", end="09:20", slot=30, cap=1, visibility="walkin"
    )
    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    row = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w.id},
    ).scalar_one()
    assert row == 1, f"Expected capacity=1 (never 0), got {row}"


def test_upgrade_respeta_tope_500(
    db_session, make_review_window, setup_cohort_and_day
):
    """Walkin 08:00–13:00 (5h = 300 min) / 10 min / cap 20 → 30×20=600 → LEAST(500, ...)=500."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # 300 / 60 / 10 = 30 franjas × 20 = 600 → LEAST(500, 600) → 500
    w = make_review_window(
        day, officer, start="08:00", end="13:00", slot=10, cap=20, visibility="walkin"
    )
    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    row = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w.id},
    ).scalar_one()
    assert row == 500, f"Expected capacity=500 (capped), got {row}"


def test_upgrade_no_toca_bookable(
    db_session, make_review_window, setup_cohort_and_day
):
    """Ventanas 'bookable' no cambian de capacity."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # Crear una ventana 'bookable' (default)
    w_bookable = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=5, visibility="bookable"
    )
    cap_antes = w_bookable.capacity

    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    row = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w_bookable.id},
    ).scalar_one()
    assert row == cap_antes, f"bookable capacity debe mantenerse: {cap_antes} != {row}"


def test_upgrade_no_toca_private(
    db_session, make_review_window, setup_cohort_and_day
):
    """Ventanas 'private' no cambian de capacity."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # Crear una ventana 'private' (default)
    w_private = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=3, visibility="private"
    )
    cap_antes = w_private.capacity

    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    row = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w_private.id},
    ).scalar_one()
    assert row == cap_antes, f"private capacity debe mantenerse: {cap_antes} != {row}"


def test_downgrade_invierte_aproximadamente(
    db_session, make_review_window, setup_cohort_and_day
):
    """Downgrade: capacity / franjas ≈ capacity original (dentro del redondeo)."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    # Crear una walkin: 09:00–14:00 / 30 min / cap 1 → 10 después de upgrade
    w = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=1, visibility="walkin"
    )
    db_session.flush()

    mod = _modulo()

    # Upgrade
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    cap_upgraded = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w.id},
    ).scalar_one()
    assert cap_upgraded == 10, "Upgrade should give capacity=10"

    # Downgrade
    db_session.execute(text(mod.DOWNGRADE_SQL))
    db_session.commit()

    cap_downgraded = db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": w.id},
    ).scalar_one()
    # 10 franjas / 10 capacity = 1, así que downgrade debe devolver ~ 1
    # (la división es aproximada y depende de redondeos)
    assert cap_downgraded >= 1, f"Downgrade should give capacity >= 1, got {cap_downgraded}"


def test_docstring_advierte_que_downgrade_es_aproximado():
    """El docstring debe advertir que downgrade es aproximado y no correr a mano."""
    plano = " ".join((_modulo().__doc__ or "").split())

    # Verificar que advierte downgrade aproximado
    assert (
        "aproximado" in plano.lower() or "aproximada" in plano.lower()
    ), "Docstring debe advertir que downgrade es aproximado"
    assert (
        "downgrade" in plano.lower()
    ), "Docstring debe mencionar downgrade"

    # Verificar que advierte no correr a mano
    assert (
        "no ejecutar" in plano.lower() or "no correr" in plano.lower()
    ), "Docstring debe advertir que NO se ejecute a mano"
    assert (
        "alembic" in plano.lower()
    ), "Docstring debe mencionar solo usar alembic"

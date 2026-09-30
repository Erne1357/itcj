"""Contrato de la migración `tt20260929a`: walkin `capacity` pasa de «por franja» a «total».

La migración es SOLO de datos (spec 2026-09-29-titulatec-cotejo-espacios-
design.md §7.2, D12 — decisión del usuario 2026-09-29: «no creo que se puedan
atender 500»):

    UPDATE titulatec_review_windows w SET capacity = GREATEST(30,
        (SELECT count(*) FROM titulatec_review_appointments a
         WHERE a.window_id = w.id AND a.status NOT IN ('cancelled', 'superseded')))
    WHERE w.visibility = 'walkin'

Todos los `walkin` quedan en **30** (el mismo default con el que nace un
espacio nuevo desde este deploy), salvo que ya tengan más de 30 citas VIVAS:
ahí el `GREATEST` es una red de seguridad que conserva ese número, nunca lo
recorta. El horario, las franjas y el `capacity` viejo (por franja) ya NO
entran en la cuenta -eso murió con el tope de 500 y la fórmula «franjas ×
capacity»-.

El harness arma el esquema con `create_all` (sin Alembic), así que el test:
1. Crea ventanas walkin de legado con distintos (horario, slot_minutes,
   capacity vieja) y verifica que TODAS quedan en 30 sin citas vivas.
2. Prueba la red de seguridad: más de 30 vivas → se conserva el número de
   vivas, no se recorta a 30.
3. Prueba que canceladas/superadas NO cuentan como vivas (mismo filtro por
   ESTADO que `SlotService.occupancy`).
4. Verifica que 'bookable' y 'private' no cambian.
5. Ejecuta DOWNGRADE_SQL y verifica que es aproximado (inversa de franjas).
"""
import importlib.util
import pytest
from datetime import date
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


def _capacity(db_session, window_id):
    return db_session.execute(
        text("SELECT capacity FROM titulatec_review_windows WHERE id = :id"),
        {"id": window_id},
    ).scalar_one()


def _sentar(db, make_appointment, window, process, status):
    """Cita ligada a `window` sin pasar por `SlotService`/`AppointmentService`:
    a la migración solo le importa la fila cruda (`window_id` + `status`),
    igual que a `SlotService.occupancy` (filtro por ESTADO, nunca por
    `is_current` -- aquí ni siquiera hace falta tocar ese campo)."""
    a = make_appointment(process, status=status)
    a.window = window
    db.flush()
    return a


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


# =========================================================== upgrade: default
@pytest.mark.parametrize("start,end,slot,cap", [
    ("09:00", "14:00", 30, 1),   # antes (fórmula franjas x cap): 10
    ("09:00", "09:20", 30, 1),   # antes (GREATEST(1, ...) mínimo): 1
    ("08:00", "13:00", 10, 20),  # antes (topado LEAST 500): 500
], ids=["antes_daba_10", "antes_daba_1", "antes_daba_500_topado"])
def test_upgrade_cualquier_walkin_sin_vivas_queda_en_30(
        db_session, make_review_window, setup_cohort_and_day, start, end, slot, cap):
    """D12: sin citas vivas, CUALQUIER horario/franjas/cupo viejo queda en el
    default plano (30) -- ya no "franjas x capacity" ni el tope de 500."""
    setup = setup_cohort_and_day
    w = make_review_window(
        setup["dia"], setup["officer"], start=start, end=end, slot=slot,
        cap=cap, visibility="walkin")
    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    assert _capacity(db_session, w.id) == 30


# ================================================= upgrade: red de seguridad
def test_upgrade_respeta_la_red_de_seguridad_con_mas_de_30_vivas(
        db_session, make_review_window, make_student, make_process,
        make_appointment, setup_cohort_and_day):
    """D12: "nunca por debajo de sus citas vivas". Con 35 citas VIVAS el
    `GREATEST` conserva las 35: no las recorta al default de 30."""
    setup = setup_cohort_and_day
    w = make_review_window(setup["dia"], setup["officer"], start="08:00",
                           end="20:00", cap=1, visibility="walkin")

    for _ in range(35):
        proc = make_process(make_student(), cohort=setup["cohort"],
                            program=setup["prog"])
        _sentar(db_session, make_appointment, w, proc, "scheduled")

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    assert _capacity(db_session, w.id) == 35


def test_upgrade_no_cuenta_canceladas_ni_superadas(
        db_session, make_review_window, make_student, make_process,
        make_appointment, setup_cohort_and_day):
    """Si canceladas/superadas contaran como vivas, 15 muertas + 20 vivas =
    35 > 30 activaría la red de seguridad de más (resultado 35). Filtrando
    por ESTADO -mismo predicado que `SlotService.occupancy`- las vivas son
    20 (< 30) y el resultado se queda en el default plano."""
    setup = setup_cohort_and_day
    w = make_review_window(setup["dia"], setup["officer"], start="08:00",
                           end="14:00", cap=1, visibility="walkin")

    for _ in range(8):
        proc = make_process(make_student(), cohort=setup["cohort"],
                            program=setup["prog"])
        _sentar(db_session, make_appointment, w, proc, "cancelled")
    for _ in range(7):
        proc = make_process(make_student(), cohort=setup["cohort"],
                            program=setup["prog"])
        _sentar(db_session, make_appointment, w, proc, "superseded")
    for _ in range(20):
        proc = make_process(make_student(), cohort=setup["cohort"],
                            program=setup["prog"])
        _sentar(db_session, make_appointment, w, proc, "scheduled")

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    assert _capacity(db_session, w.id) == 30, (
        "canceladas/superadas no deben contar como vivas")


# ======================================================= upgrade: otros modos
def test_upgrade_no_toca_bookable(
        db_session, make_review_window, setup_cohort_and_day
):
    """Ventanas 'bookable' no cambian de capacity."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    w_bookable = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=5, visibility="bookable"
    )
    cap_antes = w_bookable.capacity
    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    assert _capacity(db_session, w_bookable.id) == cap_antes


def test_upgrade_no_toca_private(
        db_session, make_review_window, setup_cohort_and_day
):
    """Ventanas 'private' no cambian de capacity."""
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    w_private = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=3, visibility="private"
    )
    cap_antes = w_private.capacity
    db_session.flush()

    mod = _modulo()
    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()

    assert _capacity(db_session, w_private.id) == cap_antes


# ===================================================================== downgrade
def test_downgrade_invierte_aproximadamente(
        db_session, make_review_window, setup_cohort_and_day
):
    """Downgrade: capacity / franjas, aproximado.

    09:00-14:00 / 30 min = 10 franjas. Sin citas vivas el upgrade deja
    capacity=30 (default D12); el downgrade lo vuelve a partir entre las 10
    franjas: 30 // 10 = 3.
    """
    setup = setup_cohort_and_day
    day = setup["dia"]
    officer = setup["officer"]

    w = make_review_window(
        day, officer, start="09:00", end="14:00", slot=30, cap=1, visibility="walkin"
    )
    db_session.flush()

    mod = _modulo()

    db_session.execute(text(mod.UPGRADE_SQL))
    db_session.commit()
    assert _capacity(db_session, w.id) == 30, "upgrade debe dejar el default, 30"

    db_session.execute(text(mod.DOWNGRADE_SQL))
    db_session.commit()
    assert _capacity(db_session, w.id) == 3, "30 entre 10 franjas = 3"


def test_docstring_advierte_que_downgrade_es_aproximado():
    """El docstring debe advertir que downgrade es aproximado y no correr a mano."""
    plano = " ".join((_modulo().__doc__ or "").split())

    assert (
        "aproximado" in plano.lower() or "aproximada" in plano.lower()
    ), "Docstring debe advertir que downgrade es aproximado"
    assert (
        "downgrade" in plano.lower()
    ), "Docstring debe mencionar downgrade"
    assert (
        "no ejecutar" in plano.lower() or "no correr" in plano.lower()
    ), "Docstring debe advertir que NO se ejecute a mano"
    assert (
        "alembic" in plano.lower()
    ), "Docstring debe mencionar solo usar alembic"

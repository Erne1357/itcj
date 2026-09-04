"""Reglas duras de la ventana de atencion de cotejo.

Lo que fija este archivo son los CHECK y la UNIQUE de la tabla, o sea las reglas
que la base hace cumplir aunque el service se equivoque. La logica de franjas y
de cupo vive en `test_slot_service.py`.

Cada `pytest.raises(IntegrityError)` va dentro de su propio `begin_nested()`: en
Postgres un error deja la transaccion abortada y el rollback del savepoint es lo
que permite seguir usando la sesion despues.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

_D = date(2029, 5, 7)


@pytest.fixture()
def dia_y_encargado(make_program, make_cohort, make_review_day, make_officer):
    """Un dia de cotejo y un encargado con carrera. Lo minimo para una ventana."""
    prog = make_program("Ingenieria de Ventanas")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos}


def test_la_ventana_se_crea_con_los_valores_dados(db_session, dia_y_encargado,
                                                  make_review_window):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], start="09:00", end="14:00",
                           slot=30, cap=1, location="Edificio A", position=esc["pos"])
    assert w.id is not None
    assert w.owner_user_id == esc["off"].id
    assert w.owner_position_id == esc["pos"].id
    assert w.status == "open"


def test_el_fin_tiene_que_ser_posterior_al_inicio(db_session, dia_y_encargado,
                                                  make_review_window):
    esc = dia_y_encargado
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_review_window(esc["dia"], esc["off"], start="14:00", end="09:00")


def test_la_capacidad_no_puede_ser_cero(db_session, dia_y_encargado, make_review_window):
    esc = dia_y_encargado
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_review_window(esc["dia"], esc["off"], cap=0)


@pytest.mark.parametrize("minutos", [0, 4, 481])
def test_la_duracion_de_franja_tiene_limites(db_session, dia_y_encargado,
                                             make_review_window, minutos):
    """Entre 5 y 480. Una franja de 0 minutos generaria franjas infinitas."""
    esc = dia_y_encargado
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_review_window(esc["dia"], esc["off"], slot=minutos)


def test_un_mismo_encargado_no_repite_hora_de_inicio_el_mismo_dia(
        db_session, dia_y_encargado, make_review_window):
    esc = dia_y_encargado
    make_review_window(esc["dia"], esc["off"], start="09:00", end="11:00")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_review_window(esc["dia"], esc["off"], start="09:00", end="13:00")


def test_dos_encargados_distintos_si_abren_a_la_misma_hora(
        db_session, dia_y_encargado, make_officer, make_review_window):
    """El dueno es el USUARIO, no el puesto.

    `core_positions.aux_school_services` tiene `allows_multiple = TRUE` y NUEVE
    ocupantes sembrados: con dueno = puesto, esas nueve personas compartirian
    una sola ventana y no podrian tener horarios distintos.
    """
    esc = dia_y_encargado
    otro, _ = make_officer([esc["prog"]], first_name="OTRO")
    make_review_window(esc["dia"], esc["off"], start="09:00")
    make_review_window(esc["dia"], otro, start="09:00")
    db_session.flush()          # no debe levantar


def test_la_ventana_conoce_su_dia_y_sus_citas(db_session, dia_y_encargado,
                                              make_review_window):
    """`back_populates` en AMBOS extremos, o el mapper no configura y revienta
    en la primera consulta, no al importar."""
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"])
    db_session.flush()
    assert w.review_day is esc["dia"]
    assert w in esc["dia"].windows
    assert w.appointments == []


def test_el_dia_hereda_de_la_convocatoria_cuando_no_pisa_nada(
        db_session, dia_y_encargado, set_cohort_defaults):
    """Las cinco columnas de horario del dia son NULLABLE a proposito: NULL
    significa «hereda». Asi los dias que ya existian quedan validos sin backfill."""
    esc = dia_y_encargado
    set_cohort_defaults(esc["cohort"], start="08:00", end="13:00", slot=20, cap=2)
    assert esc["dia"].start_time is None
    assert esc["dia"].slot_minutes is None
    assert esc["cohort"].default_slot_minutes == 20
    assert esc["cohort"].default_capacity == 2


def test_un_dia_nace_abierto(db_session, dia_y_encargado):
    assert dia_y_encargado["dia"].is_closed is False

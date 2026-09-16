"""Contrato de ESQUEMA de `ReviewWindow.visibility` (Tarea 1, auto-agendado de cotejo).

Cubre solo la columna nueva y su `CheckConstraint`: los tres modos del espacio
(privado/agendable/sin-cita) para el auto-agendado del egresado. Quien ve y
quien agenda segun el modo es logica de `SelfBookingService` (tarea aparte).

Patron para la violacion de constraint: `with db_session.begin_nested():`. Un
`db_session.rollback()` pelado descarta tambien las filas que sembraron las
fixtures (`join_transaction_mode="create_savepoint"`, ver conftest); el
savepoint anidado solo descarta el INSERT/UPDATE que fallo. Ver
`test_review_window_model.py`.
"""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

_D = date(2029, 5, 7)


@pytest.fixture()
def dia_y_encargado(make_program, make_cohort, make_review_day, make_officer):
    """Un dia de cotejo y un encargado con carrera. Lo minimo para una ventana."""
    prog = make_program("Ingenieria de Visibilidad")
    cohort = make_cohort()
    dia = make_review_day(cohort, day=_D)
    officer, pos = make_officer([prog])
    return {"prog": prog, "cohort": cohort, "dia": dia, "off": officer, "pos": pos}


def test_una_ventana_nueva_nace_privada(db_session, dia_y_encargado, make_review_window):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    assert w.visibility == "private"


@pytest.mark.parametrize("valor", ["private", "bookable", "walkin"])
def test_los_tres_valores_legales_se_guardan(db_session, dia_y_encargado,
                                             make_review_window, valor):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    w.visibility = valor
    db_session.flush()
    assert w.visibility == valor


def test_un_valor_fuera_del_dominio_levanta_integrity_error(db_session, dia_y_encargado,
                                                             make_review_window):
    esc = dia_y_encargado
    w = make_review_window(esc["dia"], esc["off"], position=esc["pos"])
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            w.visibility = "publico"
            db_session.flush()

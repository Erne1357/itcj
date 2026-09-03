"""Días de cotejo: cerrar en vez de borrar, y que el cierre se note.

Antes eran dos tests con `MagicMock`. Se reescriben contra Postgres real porque
lo que hay que probar es precisamente el efecto en la fila (`is_closed` puesto,
fila viva) y un mock no puede desmentirte: `MagicMock().is_closed` es verdadero
por accidente, así que `is_allowed` habría «pasado» diciendo lo contrario de la
verdad.
"""
from datetime import date

import pytest

from itcj2.apps.titulatec.services import appointment_errors as err
from itcj2.apps.titulatec.services.review_day_service import ReviewDayService

_D1 = date(2029, 5, 7)
_D2 = date(2029, 5, 8)
_D3 = date(2029, 5, 9)


def test_cerrar_un_dia_no_lo_borra(db_session, make_cohort, make_review_day):
    """Con ventanas y citas colgando, borrar un día es destructivo. Y la FK de
    `ReviewWindow` apunta aquí con ON DELETE RESTRICT: el DELETE ni pasaría."""
    from itcj2.apps.titulatec.models import CohortReviewDay
    coh = make_cohort()
    make_review_day(coh, day=_D1)

    quedo_abierto = ReviewDayService.toggle(db_session, coh.id, _D1, created_by_id=None)

    fila = (db_session.query(CohortReviewDay)
            .filter_by(cohort_id=coh.id, date=_D1).first())
    assert fila is not None, "el día se borró en vez de cerrarse"
    assert fila.is_closed is True
    assert quedo_abierto is False


def test_volver_a_alternar_lo_reabre(db_session, make_cohort, make_review_day):
    coh = make_cohort()
    make_review_day(coh, day=_D1)
    ReviewDayService.toggle(db_session, coh.id, _D1, created_by_id=None)
    assert ReviewDayService.toggle(db_session, coh.id, _D1, created_by_id=None) is True
    assert ReviewDayService.is_allowed(db_session, coh.id, _D1) is True


def test_un_dia_cerrado_no_esta_habilitado(db_session, make_cohort, make_review_day):
    coh = make_cohort()
    dia = make_review_day(coh, day=_D1)
    dia.is_closed = True
    db_session.flush()

    assert ReviewDayService.is_allowed(db_session, coh.id, _D1) is False
    assert _D1 not in ReviewDayService.list_days(db_session, coh.id)
    assert _D1 in ReviewDayService.list_days(db_session, coh.id, include_closed=True)


def test_assert_allowed_levanta_el_error_de_dominio(db_session, make_cohort, make_review_day):
    """El guard baja al service. Vivía en `pages/`, así que cualquier otro
    llamador de `AppointmentService` escribía sin validar."""
    coh = make_cohort()
    dia = make_review_day(coh, day=_D1)
    ReviewDayService.assert_allowed(db_session, coh.id, _D1)      # no levanta

    dia.is_closed = True
    db_session.flush()
    with pytest.raises(err.DayNotAllowed):
        ReviewDayService.assert_allowed(db_session, coh.id, _D1)


def test_un_dia_inexistente_tampoco_esta_habilitado(db_session, make_cohort):
    coh = make_cohort()
    assert ReviewDayService.is_allowed(db_session, coh.id, _D1) is False


def test_set_days_cierra_los_que_sobran_y_crea_los_nuevos(
        db_session, make_cohort, make_review_day):
    from itcj2.apps.titulatec.models import CohortReviewDay
    coh = make_cohort()
    make_review_day(coh, day=_D1)
    make_review_day(coh, day=_D2)

    ReviewDayService.set_days(db_session, coh.id, {_D2, _D3}, created_by_id=None)

    filas = {r.date: r for r in db_session.query(CohortReviewDay)
             .filter_by(cohort_id=coh.id).all()}
    assert set(filas) == {_D1, _D2, _D3}, "ninguna fila puede desaparecer"
    assert filas[_D1].is_closed is True
    assert filas[_D2].is_closed is False
    assert filas[_D3].is_closed is False


def test_list_rows_devuelve_las_filas_ordenadas(db_session, make_cohort, make_review_day):
    """La UI de espacios necesita el id y el override de horario del día, no
    solo la fecha."""
    coh = make_cohort()
    make_review_day(coh, day=_D2)
    make_review_day(coh, day=_D1)
    filas = ReviewDayService.list_rows(db_session, coh.id)
    assert [r.date for r in filas] == [_D1, _D2]
    assert all(hasattr(r, "id") for r in filas)


def test_months_with_days_ignora_los_cerrados(db_session, make_cohort, make_review_day):
    coh = make_cohort()
    d_junio = date(2029, 6, 1)
    make_review_day(coh, day=_D1)
    cerrado = make_review_day(coh, day=d_junio)
    cerrado.is_closed = True
    db_session.flush()
    assert ReviewDayService.months_with_days(db_session, coh.id) == [(2029, 5)]

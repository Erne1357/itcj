"""Flujo, ritmo y pronostico del tablero de la jefa de Servicios Escolares.

Las funciones puras (`fill_days`, `cumulative`, `pace`, `forecast`,
`liberated_by_day`) no tocan BD. `daily_counts` se prueba sobre filas
sembradas en convocatorias propias (la base de dev es compartida).
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from itcj2.apps.titulatec.services import report_flow
from itcj2.apps.titulatec.utils.business_days import add_business_days
from itcj2.apps.titulatec.services.report_flow import (
    cumulative, daily_counts, fill_days, forecast, liberated_by_day, pace,
)

# 2026-10-12 es lunes.
LUNES = date(2026, 10, 12)
VIERNES = date(2026, 10, 9)


# --- fill_days ---------------------------------------------------------------

def test_fill_days_rellena_con_cero_e_incluye_extremos():
    r = fill_days({date(2026, 10, 1): 3, date(2026, 10, 3): 2},
                  date(2026, 10, 1), date(2026, 10, 4))
    assert r == [(date(2026, 10, 1), 3), (date(2026, 10, 2), 0),
                 (date(2026, 10, 3), 2), (date(2026, 10, 4), 0)]


def test_fill_days_ignora_dias_fuera_del_rango_y_rango_invertido():
    assert fill_days({date(2026, 9, 1): 9}, date(2026, 10, 1), date(2026, 10, 2)) == [
        (date(2026, 10, 1), 0), (date(2026, 10, 2), 0)]
    assert fill_days({}, date(2026, 10, 5), date(2026, 10, 1)) == []


# --- cumulative --------------------------------------------------------------

def test_cumulative_acumula_con_base():
    s = [(date(2026, 10, 1), 2), (date(2026, 10, 2), 0), (date(2026, 10, 3), 3)]
    assert cumulative(s) == [(date(2026, 10, 1), 2), (date(2026, 10, 2), 2),
                             (date(2026, 10, 3), 5)]
    assert [v for _, v in cumulative(s, base=10)] == [12, 12, 15]
    assert cumulative([]) == []


# --- liberated_by_day --------------------------------------------------------

def test_liberated_by_day_cuenta_por_fecha_y_salta_none():
    items = [SimpleNamespace(liberated_on=date(2026, 10, 5)),
             SimpleNamespace(liberated_on=date(2026, 10, 5)),
             SimpleNamespace(liberated_on=date(2026, 10, 6)),
             SimpleNamespace(liberated_on=None)]
    assert liberated_by_day(items) == {date(2026, 10, 5): 2, date(2026, 10, 6): 1}
    assert liberated_by_day([]) == {}


# --- pace --------------------------------------------------------------------

def test_pace_promedia_sobre_dias_habiles_con_fin_de_semana_en_medio():
    # 10 habiles terminando en el lunes 12: 29/09..12/10 (sin sab/dom).
    lib = {
        date(2026, 9, 29): 4,
        date(2026, 10, 9): 6,      # viernes
        date(2026, 10, 10): 100,   # sabado: no es habil, no cuenta
        date(2026, 10, 12): 10,    # lunes
        date(2026, 9, 28): 50,     # fuera de la ventana de 10 habiles
    }
    assert pace(lib, LUNES) == pytest.approx(2.0)   # (4 + 6 + 10) / 10


def test_pace_con_hoy_en_fin_de_semana_termina_en_el_viernes():
    sabado = date(2026, 10, 10)
    assert pace({VIERNES: 5}, sabado, n=5) == pytest.approx(1.0)


def test_pace_sin_liberados_es_cero_y_n_cero_no_divide():
    assert pace({}, LUNES) == 0.0
    assert pace({LUNES: 3}, LUNES, n=0) == 0.0


# --- forecast ----------------------------------------------------------------

def test_forecast_con_ritmo_cero_o_negativo_es_none():
    assert forecast(10, 0.0, LUNES) is None
    assert forecast(10, -1.0, LUNES) is None


def test_forecast_sin_pendientes_es_hoy():
    assert forecast(0, 0.0, LUNES) == LUNES
    assert forecast(0, 3.0, LUNES) == LUNES


def test_forecast_cuenta_dias_habiles_hacia_adelante():
    # 10 pendientes a 2/dia = 5 habiles desde el lunes -> lunes siguiente.
    assert forecast(10, 2.0, LUNES) == date(2026, 10, 19)
    # Redondea hacia arriba: 11 a 2/dia = 6 habiles -> martes.
    assert forecast(11, 2.0, LUNES) == date(2026, 10, 20)
    # Cruza el fin de semana: 1 habil desde el viernes -> lunes.
    assert forecast(1, 1.0, VIERNES) == LUNES


def test_forecast_no_suma_un_dia_por_coma_flotante():
    # 21 / 0.7 = 30.000000000000004 en float: son exactamente 30 habiles.
    esperado = add_business_days(LUNES, 30)
    assert forecast(21, 0.7, LUNES) == esperado
    assert forecast(42, 1.4, LUNES) == esperado
    assert forecast(42, 0.7, LUNES) == add_business_days(LUNES, 60)
    assert forecast(21, 1.4, LUNES) == add_business_days(LUNES, 15)


def test_forecast_con_hoy_en_sabado_un_pendiente_cae_el_lunes():
    sabado = date(2026, 10, 10)
    assert forecast(1, 1.0, sabado) == LUNES


# --- daily_counts (BD) -------------------------------------------------------

def _req(db, cohort, n, *, created_at, reviewed_at=None, program=None, ctl=None):
    from itcj2.apps.titulatec.models import EnrollmentRequest

    row = EnrollmentRequest(
        cohort_id=cohort.id, control_number=ctl or f"98{n:06d}",
        first_name="EGRESADO", last_name="FLUJO", program_text="X",
        program_id=getattr(program, "id", None),
        phone="6561234567", contact_email="f@example.invalid",
        has_efirma=False, kind="unknown", status="pending",
        created_at=created_at, reviewed_at=reviewed_at, verify_send_count=0)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def escenario(db_session, make_cohort, make_period, make_program, make_student,
              make_process):
    """Dos convocatorias y tres carreras (A, B y sin carrera)."""
    c1 = make_cohort(period=make_period())
    c2 = make_cohort(period=make_period())
    pa = make_program("FLUJO CARRERA A")
    pb = make_program("FLUJO CARRERA B")
    d1, d2 = datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 6, 15, 30)

    # Solicitudes: c1/A (d1, revisada d2), c1/B (d1), c1/sin carrera (d2), c2/A (d1)
    _req(db_session, c1, 1, created_at=d1, reviewed_at=d2, program=pa)
    _req(db_session, c1, 2, created_at=d1, program=pb)
    _req(db_session, c1, 3, created_at=d2)
    _req(db_session, c2, 4, created_at=d1, program=pa)

    # Procesos: c1/A activo (d1), c1/A cancelado (d1), c1/B en pausa (d2), c2/A (d1)
    def proc(cohort, prog, status, created):
        p = make_process(make_student(), cohort=cohort, program=prog, status=status,
                         phases=False, library_clearance=None)
        p.created_at = created
        db_session.flush()
        return p

    proc(c1, pa, "active", d1)
    proc(c1, pa, "cancelled", d1)
    proc(c1, pb, "on_hold", d2)
    proc(c2, pa, "active", d1)
    return SimpleNamespace(c1=c1, c2=c2, pa=pa, pb=pb)


RANGO = dict(start=date(2026, 10, 1), end=date(2026, 10, 10))
D1, D2 = date(2026, 10, 5), date(2026, 10, 6)


def test_daily_counts_forma_y_llaves(db_session, escenario):
    r = daily_counts(db_session, cohort_ids=[escenario.c1.id], programs="ALL",
                     include_unmapped=False, **RANGO)
    assert set(r) == {"requests_new", "requests_reviewed", "enrolled"}


def test_daily_counts_todas_las_carreras_de_una_convocatoria(db_session, escenario):
    r = daily_counts(db_session, cohort_ids=[escenario.c1.id], programs="ALL",
                     include_unmapped=True, **RANGO)
    assert r["requests_new"] == {D1: 2, D2: 1}
    assert r["requests_reviewed"] == {D2: 1}
    # El cancelado no cuenta como inscrito.
    assert r["enrolled"] == {D1: 1, D2: 1}


def test_daily_counts_las_sin_carrera_solo_entran_con_include_unmapped(db_session, escenario):
    c = [escenario.c1.id]
    pa, pb = escenario.pa.id, escenario.pb.id
    f = lambda programs, un: daily_counts(  # noqa: E731
        db_session, cohort_ids=c, programs=programs, include_unmapped=un, **RANGO)
    # ALL x {True, False}
    assert f("ALL", False)["requests_new"] == {D1: 2}          # sin la solicitud NULL
    assert f("ALL", True)["requests_new"] == {D1: 2, D2: 1}
    # set x {True, False}
    assert f({pa, pb}, False)["requests_new"] == {D1: 2}
    assert f({pa, pb}, True)["requests_new"] == {D1: 2, D2: 1}


def test_daily_counts_cohort_ids_none_son_todas_las_convocatorias(db_session, escenario):
    r = daily_counts(db_session, cohort_ids=None, programs={escenario.pa.id},
                     include_unmapped=False, **RANGO)
    # Filtramos por carrera A para no depender de datos de dev de otras carreras.
    assert r["requests_new"] == {D1: 2}          # c1/A + c2/A
    assert r["enrolled"] == {D1: 2}              # c1/A activo + c2/A (cancelado fuera)


def test_daily_counts_filtra_por_carrera_y_sin_carrera(db_session, escenario):
    c = [escenario.c1.id]
    solo_b = daily_counts(db_session, cohort_ids=c, programs={escenario.pb.id},
                          include_unmapped=False, **RANGO)
    assert solo_b["requests_new"] == {D1: 1}
    assert solo_b["enrolled"] == {D2: 1}
    b_y_nulas = daily_counts(db_session, cohort_ids=c, programs={escenario.pb.id},
                             include_unmapped=True, **RANGO)
    assert b_y_nulas["requests_new"] == {D1: 1, D2: 1}   # B + sin carrera
    solo_nulas = daily_counts(db_session, cohort_ids=c, programs=set(),
                              include_unmapped=True, **RANGO)
    assert solo_nulas["requests_new"] == {D2: 1}
    assert solo_nulas["enrolled"] == {}
    nada = daily_counts(db_session, cohort_ids=c, programs=set(),
                        include_unmapped=False, **RANGO)
    assert nada == {"requests_new": {}, "requests_reviewed": {}, "enrolled": {}}


def test_daily_counts_respeta_el_rango_inclusivo(db_session, escenario):
    r = daily_counts(db_session, cohort_ids=[escenario.c1.id], programs="ALL",
                     include_unmapped=True, start=D2, end=D2)
    assert r["requests_new"] == {D2: 1}
    assert r["enrolled"] == {D2: 1}
    vacio = daily_counts(db_session, cohort_ids=[escenario.c1.id], programs="ALL",
                         include_unmapped=True, start=date(2026, 10, 7),
                         end=date(2026, 10, 9))
    assert vacio == {"requests_new": {}, "requests_reviewed": {}, "enrolled": {}}


def test_daily_counts_cohort_ids_vacio_no_trae_nada(db_session, escenario):
    r = daily_counts(db_session, cohort_ids=[], programs="ALL",
                     include_unmapped=True, **RANGO)
    assert r == {"requests_new": {}, "requests_reviewed": {}, "enrolled": {}}

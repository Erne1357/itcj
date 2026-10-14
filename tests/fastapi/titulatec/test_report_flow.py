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
    EXIT_KEYS, clear_days, cumulative, daily_counts, exit_counts, fill_days, forecast,
    liberated_by_day, liberated_by_program, pace,
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


# ===========================================================================
# Ronda 2 (R4): días hábiles para vaciar, liberados por carrera y ritmos de
# salida por motivo
# ===========================================================================
def test_clear_days_redondea_hacia_arriba_y_sin_coma_flotante():
    assert clear_days(10, 2.0) == 5
    assert clear_days(11, 2.0) == 6
    assert clear_days(21, 0.7) == 30            # 21 / 0.7 = 30.000000000000004 en float
    assert clear_days(1, 0.1) == 10


def test_clear_days_sin_cola_es_cero_y_sin_ritmo_es_none():
    assert clear_days(0, 0.0) == 0
    assert clear_days(-3, 2.0) == 0
    assert clear_days(5, 0.0) is None
    assert clear_days(5, -1.0) is None


def test_forecast_es_hoy_mas_clear_days_habiles():
    for pend, ritmo in ((10, 2.0), (21, 0.7), (1, 1.0), (7, 0.3)):
        assert forecast(pend, ritmo, LUNES) == add_business_days(LUNES, clear_days(pend, ritmo))


def test_liberated_by_program_separa_por_carrera_y_salta_sin_fecha():
    items = [SimpleNamespace(program_id=1, liberated_on=date(2026, 10, 5)),
             SimpleNamespace(program_id=1, liberated_on=date(2026, 10, 5)),
             SimpleNamespace(program_id=2, liberated_on=date(2026, 10, 6)),
             SimpleNamespace(program_id=None, liberated_on=date(2026, 10, 6)),
             SimpleNamespace(program_id=2, liberated_on=None)]
    assert liberated_by_program(items) == {
        1: {date(2026, 10, 5): 2}, 2: {date(2026, 10, 6): 1}, None: {date(2026, 10, 6): 1}}
    assert liberated_by_program([]) == {}


# --- exit_counts (BD) --------------------------------------------------------

@pytest.fixture()
def salidas(db_session, make_cohort, make_period, make_program, make_student,
            make_process, make_user):
    """Dos convocatorias, carreras A y B y una sin carrera. En D1/D2:

    * solicitudes revisadas (c1/A en D1 y D2, c1/sin carrera en D1, c1/B en
      D2, c2/A en D1);
    * accesos de Centro de Cómputo: c1/A en D2 y c2/A en D1 (CC ≠ quien
      revisó); la cuenta que Servicios Escolares creó al aprobar (mismo
      usuario, c1/B) NO cuenta;
    * eventos de procesos: dictámenes de documento (c1/A 2 en D1, c1/B 1 en
      D2, c2/A 1 en D1), de encuesta (c1/A aprobada y rechazada en D2),
      registros de Biblioteca (c1/A con adeudo en D1, c1/B sin cargo en D2) y
      ruido que no es salida (subida de documento, observación de Biblioteca,
      reversa del no adeudo, encuesta revocada).
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest, ProcessEvent

    c1 = make_cohort(period=make_period())
    c2 = make_cohort(period=make_period())
    pa = make_program("SALIDAS CARRERA A")
    pb = make_program("SALIDAS CARRERA B")
    se, cc = make_user(first_name="REVISORA"), make_user(first_name="COMPUTO")
    d1, d2 = datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 6, 15, 30)

    def req(cohort, program, n, *, revisada=None, por=None, acceso=None, acceso_por=None):
        db_session.add(EnrollmentRequest(
            cohort_id=cohort.id, control_number=f"97{n:06d}", first_name="EGRESADO",
            last_name="SALIDAS", program_text="X", program_id=getattr(program, "id", None),
            phone="6561234567", contact_email="s@example.invalid", has_efirma=False,
            kind="unknown", status="converted", created_at=d1, reviewed_at=revisada,
            reviewed_by_id=getattr(por, "id", None), access_granted_at=acceso,
            access_granted_by_id=getattr(acceso_por, "id", None), verify_send_count=0))
        db_session.flush()

    req(c1, pa, 1, revisada=d1, por=se, acceso=d2, acceso_por=cc)
    req(c1, pa, 2, revisada=d2, por=se)
    req(c1, None, 3, revisada=d1, por=se)
    req(c1, pb, 4, revisada=d2, por=se, acceso=d2, acceso_por=se)     # SE creó la cuenta
    req(c2, pa, 5, revisada=d1, por=se, acceso=d1, acceso_por=cc)

    def proc(cohort, program):
        return make_process(make_student(), cohort=cohort, program=program, phases=False,
                            library_clearance=None)

    pa1, pb1, pa2 = proc(c1, pa), proc(c1, pb), proc(c2, pa)
    for tipo, p, cuando in (
            ("document_approved", pa1, d1), ("document_rejected", pa1, d1),
            ("document_approved", pb1, d2),
            ("survey_review_approved", pa1, d2), ("survey_review_rejected", pa1, d2),
            ("library_debt_registered", pa1, d1), ("library_no_charge", pb1, d2),
            ("document_uploaded", pa1, d1), ("library_observed", pa1, d1),
            ("library_clearance_reverted", pb1, d2), ("survey_review_revoked", pa1, d2),
            ("document_approved", pa2, d1)):
        db_session.add(ProcessEvent(process_id=p.id, actor_id=se.id, event_type=tipo,
                                    created_at=cuando))
    db_session.flush()
    return SimpleNamespace(c1=c1, c2=c2, pa=pa, pb=pb)


def _salidas(db, s, **kw):
    args = {"cohort_ids": [s.c1.id], "programs": "ALL", "include_unmapped": True, **RANGO}
    args.update(kw)
    return exit_counts(db, **args)


def test_exit_counts_llaves_y_cada_serie(db_session, salidas):
    r = _salidas(db_session, salidas)
    assert tuple(r) == EXIT_KEYS == ("requests_reviewed", "access_granted", "docs_reviewed",
                                     "survey_reviewed", "library_registered")
    assert r["requests_reviewed"] == {D1: 2, D2: 2}
    assert r["access_granted"] == {D2: 1}           # la de SE al aprobar no es de CC
    assert r["docs_reviewed"] == {D1: 2, D2: 1}
    assert r["survey_reviewed"] == {D2: 2}          # aprobada + rechazada; revocar no
    assert r["library_registered"] == {D1: 1, D2: 1}


def test_exit_counts_respeta_carrera_y_sin_carrera(db_session, salidas):
    s = salidas
    solo_a = _salidas(db_session, s, programs={s.pa.id}, include_unmapped=False)
    assert solo_a["requests_reviewed"] == {D1: 1, D2: 1}
    assert solo_a["docs_reviewed"] == {D1: 2}
    assert solo_a["library_registered"] == {D1: 1}
    sin_nulas = _salidas(db_session, s, include_unmapped=False)
    assert sin_nulas["requests_reviewed"] == {D1: 1, D2: 2}
    nada = _salidas(db_session, s, programs=set(), include_unmapped=False)
    assert nada == {k: {} for k in EXIT_KEYS}


def test_exit_counts_convocatorias_y_rango(db_session, salidas):
    s = salidas
    todas_a = _salidas(db_session, s, cohort_ids=None, programs={s.pa.id},
                       include_unmapped=False)
    assert todas_a["docs_reviewed"] == {D1: 3}              # c1/A + c2/A
    assert todas_a["access_granted"] == {D1: 1, D2: 1}
    solo_d2 = _salidas(db_session, s, start=D2, end=D2)
    assert solo_d2["docs_reviewed"] == {D2: 1} and solo_d2["requests_reviewed"] == {D2: 2}
    assert _salidas(db_session, s, cohort_ids=[]) == {k: {} for k in EXIT_KEYS}


def _sentencias(db_session, fn) -> list[str]:
    from sqlalchemy import event

    vistas: list[str] = []

    def _ver(_c, _cur, statement, *_a):
        if "titulatec_audit_log" not in statement:
            vistas.append(statement)

    db_session.flush()
    conn = db_session.connection()
    event.listen(conn, "before_cursor_execute", _ver)
    try:
        fn()
    finally:
        event.remove(conn, "before_cursor_execute", _ver)
    return vistas


def test_exit_counts_dos_consultas_y_ninguna_sin_nada_visible(db_session, salidas):
    s = salidas
    assert len(_sentencias(db_session, lambda: _salidas(db_session, s))) == 2
    assert _sentencias(db_session, lambda: (
        _salidas(db_session, s, cohort_ids=[]),
        _salidas(db_session, s, programs=set(), include_unmapped=False))) == []

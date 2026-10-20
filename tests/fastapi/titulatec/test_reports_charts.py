"""Geometria de graficas y dias habiles del tablero de reportes (puro, sin BD)."""
from datetime import date
from itertools import pairwise

import pytest

from itcj2.apps.titulatec.utils import business_days as bd
from itcj2.apps.titulatec.utils import charts as ch

# 2026-10-12 es lunes.
LUN, MAR, VIE = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 16)
SAB, DOM, LUN2 = date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)


# === DIAS HABILES ===
def test_is_business_day():
    assert bd.is_business_day(LUN) and bd.is_business_day(VIE)
    assert not bd.is_business_day(SAB) and not bd.is_business_day(DOM)


def test_add_business_days_cero_y_fin_de_semana():
    assert bd.add_business_days(LUN, 0) == LUN
    assert bd.add_business_days(SAB, 0) == LUN2
    assert bd.add_business_days(DOM, 0) == LUN2


def test_add_business_days_cruza_fin_de_semana():
    assert bd.add_business_days(LUN, 1) == MAR
    assert bd.add_business_days(VIE, 1) == LUN2
    assert bd.add_business_days(VIE, 5) == date(2026, 10, 23)
    assert bd.add_business_days(SAB, 1) == LUN2
    assert bd.add_business_days(DOM, 1) == LUN2
    assert bd.add_business_days(SAB, 2) == date(2026, 10, 20)


def test_last_business_days_termina_en_hoy_si_es_habil():
    assert bd.last_business_days(MAR, 2) == [LUN, MAR]


def test_last_business_days_fin_de_semana_termina_en_viernes():
    assert bd.last_business_days(SAB, 2) == [date(2026, 10, 15), VIE]
    assert bd.last_business_days(DOM, 1) == [VIE]


def test_last_business_days_cruza_semana_y_orden_ascendente():
    got = bd.last_business_days(MAR, 4)
    assert got == [date(2026, 10, 8), date(2026, 10, 9), LUN, MAR]
    assert got == sorted(got)


def test_last_business_days_n_cero():
    assert bd.last_business_days(LUN, 0) == []


# === TICKS ===
def test_nice_ticks_vmax_no_positivo():
    assert ch.nice_ticks(0) == [0, 1]
    assert ch.nice_ticks(-5) == [0, 1]


def test_nice_ticks_empieza_en_cero_y_cubre_vmax():
    for vmax in (1, 3, 7, 10, 23, 99, 101, 1234, 0.4):
        t = ch.nice_ticks(vmax)
        assert t[0] == 0
        assert t[-1] >= vmax
        assert t == sorted(t)


def test_nice_ticks_pasos_1_2_5():
    assert ch.nice_ticks(100) == [0, 50, 100]
    assert ch.nice_ticks(23) == [0, 10, 20, 30]
    assert ch.nice_ticks(8) == [0, 2, 4, 6, 8]


# === BARRAS ===
def test_bar_rows_relativo_al_maximo():
    rows = ch.bar_rows([("a", 10), ("b", 5), ("c", 0)])
    assert [r["pct"] for r in rows] == [100, 50, 0]
    assert rows[0] == {"label": "a", "value": 10, "pct": 100}


def test_bar_rows_con_vmax_explicito_y_tope():
    rows = ch.bar_rows([("a", 5)], vmax=20)
    assert rows[0]["pct"] == 25
    assert ch.bar_rows([("a", 50)], vmax=20)[0]["pct"] == 100


def test_bar_rows_todo_cero_o_vacio():
    assert [r["pct"] for r in ch.bar_rows([("a", 0), ("b", 0)])] == [0, 0]
    assert ch.bar_rows([]) == []


# === BARRA APILADA ===
def test_stack_segments_suma_100_y_posiciones():
    segs = ch.stack_segments([("a", 1), ("b", 3)])
    assert [s["key"] for s in segs] == ["a", "b"]
    assert segs[0]["x_pct"] == 0 and segs[0]["w_pct"] == pytest.approx(25)
    assert segs[1]["x_pct"] == pytest.approx(25)
    assert sum(s["w_pct"] for s in segs) == pytest.approx(100)


def test_stack_segments_omite_ceros_y_vacio():
    segs = ch.stack_segments([("a", 0), ("b", 2), ("c", 0)])
    assert [s["key"] for s in segs] == ["b"]
    assert segs[0]["w_pct"] == pytest.approx(100)
    assert ch.stack_segments([("a", 0), ("b", 0)]) == []
    assert ch.stack_segments([]) == []


# === LINEA ===
def test_line_points_equiespaciado_e_invertido():
    pts = ch.line_points([0, 5, 10], width=100, height=50, vmax=10)
    assert pts == [(0.0, 50.0), (50.0, 25.0), (100.0, 0.0)]


def test_line_points_con_pad():
    pts = ch.line_points([0, 10], width=100, height=50, vmax=10, pad=5)
    assert pts == [(5.0, 45.0), (95.0, 5.0)]


def test_line_points_un_solo_valor_centrado():
    assert ch.line_points([10], width=100, height=50, vmax=10) == [(50.0, 0.0)]


def test_line_points_vmax_cero_y_vacio():
    pts = ch.line_points([0, 0], width=100, height=50, vmax=0)
    assert [p[1] for p in pts] == [50.0, 50.0]
    assert ch.line_points([], width=100, height=50, vmax=10) == []


def test_points_attr_un_decimal():
    assert ch.points_attr([(0, 50), (33.333, 25.04)]) == "0.0,50.0 33.3,25.0"
    assert ch.points_attr([]) == ""


def test_sparkline():
    s = ch.sparkline([0, 2, 4], width=100, height=20)
    assert len(s.split(" ")) == 3
    assert ch.sparkline([]) == ""
    # todos ceros: no revienta, linea plana
    z = ch.sparkline([0, 0, 0])
    ys = {p.split(",")[1] for p in z.split(" ")}
    assert len(ys) == 1


# === BINS ===
def test_bin_index():
    assert ch.bin_index(0, 10) == 0
    assert ch.bin_index(1, 10) == 1
    assert ch.bin_index(10, 10) == 5
    assert ch.bin_index(5, 10) == 3
    assert ch.bin_index(99, 10) == 5
    assert ch.bin_index(3, 0) == 1
    assert {ch.bin_index(n, 7) for n in range(0, 8)} <= set(range(0, 6))


# === CALENDARIO ===
def test_calendar_weeks_empieza_miercoles_termina_lunes():
    start, end = date(2026, 10, 7), date(2026, 10, 12)  # mie ... lun
    weeks = ch.calendar_weeks({date(2026, 10, 8): 4}, start, end, today=date(2026, 10, 9))
    assert len(weeks) == 2
    assert all(len(w) == 5 for w in weeks)
    assert weeks[0][0]["date"] == date(2026, 10, 5)
    assert weeks[0][0]["in_range"] is False
    assert weeks[0][1]["in_range"] is False
    assert weeks[0][2]["in_range"] is True
    jue = weeks[0][3]
    assert jue["n"] == 4 and jue["bin"] == 5 and jue["in_range"]
    assert weeks[0][4]["is_today"] is True
    assert sum(c["is_today"] for w in weeks for c in w) == 1
    assert weeks[1][0]["date"] == end and weeks[1][0]["in_range"]
    assert weeks[1][1]["in_range"] is False


def test_calendar_weeks_sin_datos_y_rango_invertido():
    weeks = ch.calendar_weeks({}, date(2026, 10, 12), date(2026, 10, 16), today=date(2026, 1, 1))
    assert len(weeks) == 1
    assert all(c["n"] == 0 and c["bin"] == 0 and not c["is_today"] for c in weeks[0])
    assert ch.calendar_weeks({}, date(2026, 10, 16), date(2026, 10, 12), today=LUN) == []


# === RONDA 2: segmentos a escala comun y tintes de un color ===
def test_scaled_segments_a_escala_comun():
    s = ch.scaled_segments([("a", 2), ("b", 0), ("c", 3)], 10)
    assert [(x["key"], x["value"], x["x_pct"], x["w_pct"]) for x in s] == [
        ("a", 2, 0, 20), ("c", 3, 20, 30)]


def test_scaled_segments_tope_y_vacio():
    assert ch.scaled_segments([("a", 5)], 0) == []
    assert ch.scaled_segments([], 10) == []
    assert ch.scaled_segments([("a", 0)], 10) == []
    s = ch.scaled_segments([("a", 8), ("b", 8)], 10)       # la suma rebasa la escala
    assert s[-1]["x_pct"] + s[-1]["w_pct"] == pytest.approx(100)
    assert all(0 <= x["w_pct"] <= 100 for x in s)


def _pasan_ordinal(pasos):
    """Los criterios de `validate_palette.js --ordinal`: L monótona, vecinos a
    >= 0.06 y el más claro >= 2:1 contra la superficie."""
    ls = [ch.ok_lightness(c) for c in pasos]
    assert ls == sorted(ls), pasos                          # oscuro -> claro
    assert all(b - a >= ch.MIN_STEP_L for a, b in pairwise(ls)), pasos
    assert ch.contrast_ratio(pasos[-1], ch.SURFACE_LIGHT) >= ch.LIGHT_FLOOR


def test_formulas_de_contraste_y_claridad():
    assert ch.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert ch.contrast_ratio("#2a78d6", "#fcfcfb") == pytest.approx(4.30, abs=0.01)
    assert ch.ok_lightness("#ffffff") == pytest.approx(1.0, abs=1e-4)
    assert ch.ok_lightness("#000000") == pytest.approx(0.0, abs=1e-4)


def test_ramp_steps_con_tintes_conserva_la_base():
    """Escolares: el tramo de tintes alcanza para 4 pasos; la base va primero."""
    pasos = ch.ramp_steps("#2a78d6", 4)
    assert len(pasos) == 4 and pasos[0] == "#2a78d6" and len(set(pasos)) == 4
    _pasan_ordinal(pasos)
    assert ch.ramp_steps("#2a78d6", 1) == ["#2a78d6"]
    assert ch.ramp_steps("#2a78d6", 0) == ["#2a78d6"]


def test_ramp_steps_baja_con_sombras_si_los_tintes_no_alcanzan():
    """Alumno (#eb6834, 3.1:1): aclarando solo caben 2 pasos antes de 2:1; los
    otros salen oscureciendo la base (misma rampa, mismo tono)."""
    pasos = ch.ramp_steps("#eb6834", 4)
    _pasan_ordinal(pasos)
    assert ch.ok_lightness(pasos[0]) < ch.ok_lightness("#eb6834")


def test_interleave_steps_separa_vecinos():
    pasos = ["a", "b", "c", "d"]
    ciclo = ch.interleave_steps(pasos, 9)
    assert ciclo == ["a", "c", "b", "d", "a", "c", "b", "d", "a"]
    assert all(ciclo[i] != ciclo[j] for i in range(9) for j in range(i + 1, min(i + 4, 9)))
    assert ch.interleave_steps(pasos, 3) == ["a", "b", "c"]

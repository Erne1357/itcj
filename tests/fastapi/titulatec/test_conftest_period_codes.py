"""La fábrica `make_period` no puede repetir código en corridas largas.

`core_academic_periods.code` es `String(6)`. El generador anterior,
`f"29{n:03d}A"[:6]`, TRUNCABA: desde n = 10 000 los valores consecutivos
(10020…10029) daban el MISMO código «291002». Como `make_period` es un
get-or-create por código, devolvía el mismo periodo, y la segunda
`make_cohort` reventaba con el UNIQUE `ix_titulatec_cohorts_period_id`.

Solo aparecía corriendo `tests/fastapi/titulatec/` entero en UN proceso: el
contador `_seq` de la conftest pasa de 10 000 hacia los últimos archivos
(`test_survey_review_submit.py`, `test_survey_reviews_admin_routes.py`).
Partida en varios procesos, la suite nunca llegaba ahí. Estas pruebas
adelantan el contador para reproducirlo sin correr la suite entera.
"""
import itertools


def _adelanta_contador(monkeypatch, fabrica, valor: int) -> None:
    """`_n()` lee el global `_seq` de la conftest en cada llamada: se sustituye
    en el módulo donde vive la fábrica (el que cargó pytest)."""
    monkeypatch.setitem(fabrica.__globals__, "_seq", itertools.count(valor))


def test_dos_periodos_seguidos_con_el_contador_pasado_de_10000(make_period, monkeypatch):
    _adelanta_contador(monkeypatch, make_period, 10020)

    uno = make_period()
    otro = make_period()

    assert uno.code != otro.code
    assert uno.id != otro.id


def test_dos_convocatorias_seguidas_con_el_contador_pasado_de_10000(
    make_cohort, make_period, monkeypatch,
):
    """El modo de fallo real: dos `make_cohort()` en la misma prueba."""
    _adelanta_contador(monkeypatch, make_period, 10020)

    una = make_cohort()
    otra = make_cohort()

    assert una.period_id != otra.period_id


def test_el_codigo_mide_seis_y_no_se_repite_en_un_rango_grande(make_period):
    """Rango muy por encima de lo que consume hoy una corrida completa."""
    period_code = make_period.__globals__["_period_code"]

    codigos = [period_code(n) for n in range(1, 300_000)]

    assert all(len(c) == 6 for c in codigos)
    assert len(set(codigos)) == len(codigos)
    # Nunca choca con los códigos explícitos de 5 caracteres de otras pruebas
    # (p. ej. «29997»), ni con un periodo real (AAAAS, 5 cifras).
    assert all(c.startswith("29") for c in codigos)

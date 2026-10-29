"""`utils/business_days.py::business_days_between`: el semáforo de días hábiles
de las bandejas FIFO (Formato B y Sinodales).

Antes cada bandeja traía su propio `_business_days_since`, copiado literal
(revisión de rama de la fase 4, hallazgo 13). Ahora las dos usan el helper
puro y estas pruebas fijan su regla: días hábiles (lun-vie) ESTRICTAMENTE
posteriores a `start` hasta `end` inclusive, sin feriados.
"""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

import itcj2.apps.titulatec as _tt_pkg
from itcj2.apps.titulatec.utils.business_days import business_days_between

SERVICES = Path(_tt_pkg.__file__).resolve().parent / "services"

LUNES = date(2026, 10, 19)
VIERNES = date(2026, 10, 23)
SABADO = date(2026, 10, 24)
DOMINGO = date(2026, 10, 25)


@pytest.mark.parametrize("start,end,esperado", [
    (LUNES, LUNES, 0),                            # mismo día: nada que contar
    (LUNES, LUNES + timedelta(days=1), 1),        # lunes -> martes
    (LUNES, VIERNES, 4),                          # martes a viernes
    (VIERNES, SABADO, 0),                         # el sábado no cuenta
    (VIERNES, DOMINGO, 0),                        # ni el domingo
    (VIERNES, DOMINGO + timedelta(days=1), 1),    # viernes -> lunes = 1
    (SABADO, DOMINGO + timedelta(days=1), 1),     # desde fin de semana
    (LUNES, LUNES + timedelta(days=14), 10),      # dos semanas
])
def test_cuenta_dias_habiles_estrictamente_posteriores(start, end, esperado):
    assert business_days_between(start, end) == esperado


def test_un_fin_anterior_al_inicio_es_cero():
    """Reloj desfasado o fecha futura: nunca un número negativo en el semáforo."""
    assert business_days_between(VIERNES, LUNES) == 0


def test_las_dos_bandejas_usan_el_helper_y_no_su_copia():
    """Estructural: ninguna bandeja define su propio contador de días hábiles."""
    for nombre in ("format_b_inbox_service.py", "synodal_inbox_service.py"):
        fuente = (SERVICES / nombre).read_text(encoding="utf-8")
        tree = ast.parse(fuente)
        propias = [n.name for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and "business_days" in n.name]
        assert propias == [], (nombre, propias)
        assert "business_days_between" in fuente, nombre


# ===========================================================================
# Calendario de dias inhabiles (fase 5, Task 2)
# ===========================================================================
from itcj2.apps.titulatec.utils import business_days as bd  # noqa: E402


def _old_is(d):
    return d.weekday() < 5


def _old_add(d, n):
    if n == 0:
        while not _old_is(d):
            d += timedelta(days=1)
        return d
    restantes = n
    while restantes > 0:
        d += timedelta(days=1)
        if _old_is(d):
            restantes -= 1
    return d


def _old_between(start, end):
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if _old_is(d):
            n += 1
    return n


def _old_last(today, n):
    dias, d = [], today
    while len(dias) < n:
        if _old_is(d):
            dias.append(d)
        d -= timedelta(days=1)
    dias.reverse()
    return dias


def test_oraculo_con_calendario_vacio_igual_que_antes_en_un_ano():
    """Con `holidays` vacio (por omision o explicito) cada funcion da lo mismo
    que la version anterior, sobre todas las fechas de un año."""
    d0 = date(2026, 1, 1)
    for i in range(366):
        d = d0 + timedelta(days=i)
        assert bd.is_business_day(d) == _old_is(d)
        assert bd.is_business_day(d, holidays=frozenset()) == _old_is(d)
        for n in (0, 1, 3, 10):
            assert bd.add_business_days(d, n) == _old_add(d, n)
            assert bd.add_business_days(d, n, holidays=frozenset()) == _old_add(d, n)
            assert bd.last_business_days(d, n) == _old_last(d, n)
        for k in (0, 1, 4, 9, 31):
            fin = d + timedelta(days=k)
            assert bd.business_days_between(d, fin) == _old_between(d, fin)
            assert bd.business_days_between(d, fin, holidays=frozenset()) == _old_between(d, fin)


MARTES = LUNES + timedelta(days=1)


def test_un_festivo_en_martes_recorre_los_dias_habiles():
    fest = frozenset({MARTES})
    miercoles = MARTES + timedelta(days=1)
    assert not bd.is_business_day(MARTES, holidays=fest)
    assert bd.is_business_day(MARTES)
    # lunes + 1 = martes normalmente; con festivo, miercoles
    assert bd.add_business_days(LUNES, 1) == MARTES
    assert bd.add_business_days(LUNES, 1, holidays=fest) == miercoles
    assert bd.add_business_days(MARTES, 0, holidays=fest) == miercoles
    # lunes -> viernes: 4 habiles, con el festivo 3
    assert business_days_between(LUNES, VIERNES) == 4
    assert business_days_between(LUNES, VIERNES, holidays=fest) == 3
    # los 3 ultimos habiles que terminan el jueves saltan el martes
    jueves = LUNES + timedelta(days=3)
    assert bd.last_business_days(jueves, 3) == [MARTES, miercoles, jueves]
    assert bd.last_business_days(jueves, 3, holidays=fest) == [LUNES, miercoles, jueves]


def test_un_festivo_en_fin_de_semana_no_cambia_nada():
    fest = frozenset({SABADO})
    assert business_days_between(VIERNES, DOMINGO + timedelta(days=1), holidays=fest) == 1


def test_toda_llamada_a_las_cuatro_funciones_pasa_holidays():
    """Estructural (f): fuera de `business_days.py`, cada llamada a las 4
    funciones del calendario pasa `holidays=` (un consumidor que lo olvide
    cuenta lun-vie sin enterarse del calendario)."""
    raiz = Path(_tt_pkg.__file__).resolve().parent
    nombres = {"is_business_day", "add_business_days", "business_days_between",
               "last_business_days"}
    faltan, vistas = [], 0
    for ruta in raiz.rglob("*.py"):
        if ruta.name == "business_days.py":
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            nombre = (f.id if isinstance(f, ast.Name)
                      else f.attr if isinstance(f, ast.Attribute) else None)
            if nombre in nombres:
                vistas += 1
                if not any(k.arg == "holidays" for k in n.keywords):
                    faltan.append(f"{ruta.name}:{n.lineno} {nombre}")
    assert vistas >= 8, "el barrido no encontro los consumidores conocidos"
    assert faltan == [], faltan

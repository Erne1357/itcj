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

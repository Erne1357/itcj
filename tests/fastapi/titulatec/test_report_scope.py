"""Predicados de alcance del tablero (`services/report_scope.py`), sin BD.

Las cuatro ramas de `scope_predicates` (y las dos variantes de set vacío) más
`cohort_predicates`, compiladas a SQL de PostgreSQL con valores literales: lo que
se fija es el predicado exacto, no un conteo sobre datos.
"""
from __future__ import annotations

import pytest
from sqlalchemy import and_, column, table
from sqlalchemy.dialects import postgresql

from itcj2.apps.titulatec.services.report_scope import (
    cohort_predicates,
    scope_predicates,
)

_T = table("t", column("program_id"), column("cohort_id"))
_COL = _T.c.program_id


def _sql(preds) -> str:
    if not preds:
        return ""
    expr = and_(*preds) if len(preds) > 1 else preds[0]
    return str(expr.compile(dialect=postgresql.dialect(),
                            compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize("programs, include_unmapped, esperado", [
    ("ALL", False, "t.program_id IS NOT NULL"),                     # read.all no abre «Sin carrera»
    ("ALL", True, ""),                                              # sin filtro
    ({3, 1}, False, "t.program_id IN (1, 3)"),
    (set(), False, "false"),                                        # sin alcance: nada
    ({3, 1}, True, "t.program_id IN (1, 3) OR t.program_id IS NULL"),
    (set(), True, "t.program_id IS NULL"),                          # solo «Sin carrera»
])
def test_las_ramas_de_scope_predicates(programs, include_unmapped, esperado):
    assert _sql(scope_predicates(_COL, programs, include_unmapped)) == esperado


def test_scope_predicates_acepta_cualquier_iterable_y_repetidos():
    assert _sql(scope_predicates(_COL, [2, 2, "5"], False)) == "t.program_id IN (2, 5)"
    assert _sql(scope_predicates(_COL, frozenset({7}), False)) == "t.program_id IN (7)"


@pytest.mark.parametrize("cohort_ids, esperado", [
    (None, ""),                                                     # todas
    ([4, 2, 4], "t.cohort_id IN (2, 4)"),
])
def test_cohort_predicates(cohort_ids, esperado):
    assert _sql(cohort_predicates(_T.c.cohort_id, cohort_ids)) == esperado


def test_cohort_predicates_lista_vacia_no_trae_nada():
    """Lista vacía = ninguna convocatoria: un IN vacío (siempre falso), no «todas»."""
    preds = cohort_predicates(_T.c.cohort_id, [])
    assert len(preds) == 1
    assert "IN" in _sql(preds) and "1 != 1" in _sql(preds)

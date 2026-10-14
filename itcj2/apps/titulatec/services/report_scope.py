"""Predicados de alcance (convocatoria y carrera) del tablero de la jefa de
Servicios Escolares.

Único lugar donde vive la regla «qué carreras entran» de las lecturas del
tablero (`report_snapshot.load_snapshot`, `report_flow.daily_counts`). Antes
cada módulo tenía su copia (`_scope_filters` y `_filtros`); la Task 6 las
consolidó aquí sin cambiar la semántica (Ruling del controlador).

Funciones puras: reciben una columna de SQLAlchemy y devuelven una lista de
predicados para `filter(*preds)`. No consultan nada.
"""
from __future__ import annotations

from collections.abc import Iterable


def scope_predicates(column, programs, include_unmapped: bool) -> list:
    """Predicados de carrera sobre `column` (un `program_id`).

    - `programs == "ALL"` y sin `include_unmapped` -> `column IS NOT NULL`
      (como `scope_service`: `read.all` no abre el cubo «Sin carrera»);
    - `"ALL"` con `include_unmapped` -> sin filtro;
    - un set sin `include_unmapped` -> `column IN (...)`; set vacío ->
      `false()` (sin alcance: no trae nada, ni «Sin carrera»);
    - un set con `include_unmapped` -> `column IN (...) OR column IS NULL`
      (set vacío -> solo `column IS NULL`).
    """
    from sqlalchemy import false, or_

    if programs == "ALL":
        return [] if include_unmapped else [column.isnot(None)]
    ids = sorted({int(p) for p in programs})
    if ids and include_unmapped:
        return [or_(column.in_(ids), column.is_(None))]
    if ids:
        return [column.in_(ids)]
    if include_unmapped:
        return [column.is_(None)]
    return [false()]


def cohort_predicates(column, cohort_ids: Iterable[int] | None) -> list:
    """`cohort_ids=None` = todas las convocatorias (sin filtro); una lista
    (vacía incluida) filtra `column IN (...)` (vacía no trae nada)."""
    if cohort_ids is None:
        return []
    return [column.in_(sorted({int(c) for c in cohort_ids}))]

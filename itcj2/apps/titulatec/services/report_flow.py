"""Flujo, ritmo y pronostico del tablero de la jefa de Servicios Escolares.

Solo lectura. `daily_counts` agrupa por dia en SQL (tres consultas); el resto
son funciones puras sobre series de `(fecha, conteo)`. El ritmo se mide en
dias habiles (lun-vie, sin feriados) con `utils/business_days`.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import TYPE_CHECKING

from sqlalchemy import Date, cast, false, func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.business_days import add_business_days, last_business_days

if TYPE_CHECKING:
    from itcj2.apps.titulatec.services.report_snapshot import Item


def _filtros(model, *, cohort_ids, programs, include_unmapped) -> list:
    """Predicados de convocatoria y carrera sobre `model` (solicitud o proceso).

    `cohort_ids=None` = todas las convocatorias; lista vacia = ninguna.
    Las de `program_id NULL` entran SOLO con `include_unmapped=True` (tambien
    con "ALL"). `programs="ALL"` no filtra por carrera; un set filtra por
    `program_id`.
    """
    preds = []
    if cohort_ids is not None:
        preds.append(model.cohort_id.in_(list(cohort_ids)))
    if programs == "ALL":
        if not include_unmapped:
            preds.append(model.program_id.is_not(None))
    else:
        ids = list(programs)
        if ids and include_unmapped:
            preds.append(model.program_id.in_(ids) | model.program_id.is_(None))
        elif ids:
            preds.append(model.program_id.in_(ids))
        elif include_unmapped:
            preds.append(model.program_id.is_(None))
        else:
            preds.append(false())   # sin alcance: no trae nada
    return preds


def _por_dia(db: Session, columna, preds: list, start: date, end: date) -> dict[date, int]:
    """Cuenta filas por dia de `columna` (rango inclusivo) en una consulta."""
    dia = cast(columna, Date)
    desde = datetime.combine(start, datetime.min.time())
    antes_de = datetime.combine(end + timedelta(days=1), datetime.min.time())
    q = (db.query(dia.label("d"), func.count().label("n"))
         .filter(columna >= desde, columna < antes_de, *preds)
         .group_by(dia))
    return {d: int(n) for d, n in q.all()}


def daily_counts(db: Session, *, cohort_ids, programs, include_unmapped: bool,
                 start: date, end: date) -> dict[str, dict[date, int]]:
    """Conteos por dia de `start` a `end` (inclusivos), tres consultas.

    - `requests_new`: solicitudes creadas (`EnrollmentRequest.created_at`).
    - `requests_reviewed`: solicitudes revisadas (`reviewed_at`).
    - `enrolled`: procesos creados (`TitulationProcess.created_at`), sin los
      `cancelled`.

    Los dias sin movimiento no aparecen; `fill_days` los rellena.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess

    kw = dict(cohort_ids=cohort_ids, programs=programs, include_unmapped=include_unmapped)
    p_req = _filtros(EnrollmentRequest, **kw)
    p_proc = _filtros(TitulationProcess, **kw) + [TitulationProcess.status != "cancelled"]
    return {
        "requests_new": _por_dia(db, EnrollmentRequest.created_at, p_req, start, end),
        "requests_reviewed": _por_dia(db, EnrollmentRequest.reviewed_at, p_req, start, end),
        "enrolled": _por_dia(db, TitulationProcess.created_at, p_proc, start, end),
    }


def liberated_by_day(items: "list[Item]") -> dict[date, int]:
    """Liberados por dia, desde `item.liberated_on` (los `None` se saltan)."""
    out: dict[date, int] = {}
    for it in items:
        d = it.liberated_on
        if d is not None:
            out[d] = out.get(d, 0) + 1
    return out


def fill_days(counts: dict[date, int], start: date, end: date) -> list[tuple[date, int]]:
    """Serie diaria de `start` a `end` (inclusivos) con 0 en los dias vacios."""
    out: list[tuple[date, int]] = []
    d = start
    while d <= end:
        out.append((d, counts.get(d, 0)))
        d += timedelta(days=1)
    return out


def cumulative(series: list[tuple[date, int]], base: int = 0) -> list[tuple[date, int]]:
    """Acumulado de la serie, partiendo de `base`."""
    total = base
    out: list[tuple[date, int]] = []
    for d, n in series:
        total += n
        out.append((d, total))
    return out


def pace(liberated: dict[date, int], today: date, n: int = 10) -> float:
    """Liberados por dia habil, promedio de los ultimos `n` dias habiles.

    Los fines de semana no cuentan ni en el numerador ni en el divisor.
    """
    if n <= 0:
        return 0.0
    dias = last_business_days(today, n)
    return sum(liberated.get(d, 0) for d in dias) / n


def forecast(pending: int, pace: float, today: date) -> date | None:
    """Fecha estimada en que se vacian los pendientes, sin contar feriados.

    `None` si el ritmo no es positivo; sin pendientes, `today`.
    """
    if pending <= 0:
        return today
    if pace <= 0:
        return None
    return add_business_days(today, math.ceil(Fraction(pending) / Fraction(pace).limit_denominator(10**6)))

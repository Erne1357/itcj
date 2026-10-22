"""Flujo, ritmo y pronostico del tablero de la jefa de Servicios Escolares.

Solo lectura. `daily_counts` agrupa por dia en SQL (tres consultas) y
`exit_counts` las salidas de cada cola de trabajo (dos consultas, Ronda 2,
R4c); el resto son funciones puras sobre series de `(fecha, conteo)`
(`pace`, `clear_days`, `forecast`, `liberated_by_day`,
`liberated_by_program`). El ritmo se mide en dias habiles (lun-vie, sin
feriados) con `utils/business_days`.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import TYPE_CHECKING

from sqlalchemy import Date, cast, func
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.report_scope import (
    cohort_predicates,
    scope_predicates,
)
from itcj2.apps.titulatec.utils.business_days import (
    add_business_days,
    last_business_days,
)

if TYPE_CHECKING:
    from itcj2.apps.titulatec.services.report_snapshot import Item


def _filtros(model, *, cohort_ids, programs, include_unmapped) -> list:
    """Predicados de convocatoria y carrera sobre `model` (solicitud o proceso).

    `cohort_ids=None` = todas las convocatorias; lista vacia = ninguna.
    Las de `program_id NULL` entran SOLO con `include_unmapped=True` (tambien
    con "ALL"). `programs="ALL"` no filtra por carrera; un set filtra por
    `program_id`. La regla vive en `report_scope` (la misma de
    `report_snapshot`).
    """
    return (cohort_predicates(model.cohort_id, cohort_ids)
            + scope_predicates(model.program_id, programs, include_unmapped))


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


def pace(liberated: dict[date, int], today: date, n: int = 10, *,
         holidays: frozenset[date] = frozenset()) -> float:
    """Liberados por dia habil, promedio de los ultimos `n` dias habiles.

    Los fines de semana no cuentan ni en el numerador ni en el divisor.
    """
    if n <= 0:
        return 0.0
    dias = last_business_days(today, n, holidays=holidays)
    return sum(liberated.get(d, 0) for d in dias) / n


def clear_days(queue: int, per_day: float) -> int | None:
    """Dias habiles para vaciar `queue` a `per_day` por dia habil:
    ⌈queue ÷ per_day⌉, sin el error de coma flotante (21 ÷ 0.7 son 30, no 31).

    Sin cola (0 o negativa), 0; con cola y ritmo no positivo, `None` («sin
    ritmo medible»): nunca divide entre cero.
    """
    if queue <= 0:
        return 0
    if per_day <= 0:
        return None
    return math.ceil(Fraction(int(queue)) / Fraction(per_day).limit_denominator(10**6))


def forecast(pending: int, pace: float, today: date, *,
             holidays: frozenset[date] = frozenset()) -> date | None:
    """Fecha estimada en que se vacian los pendientes, sin contar feriados:
    `add_business_days(today, clear_days(pending, pace))`.

    `None` si el ritmo no es positivo; sin pendientes, `today`.
    """
    if pending <= 0:
        return today
    dias = clear_days(pending, pace)
    return None if dias is None else add_business_days(today, dias, holidays=holidays)


def liberated_by_program(items: list[Item]) -> dict[int | None, dict[date, int]]:
    """Liberados por carrera y dia (`{program_id: {fecha: n}}`, `None` = sin
    carrera), desde `item.liberated_on`; los `None` se saltan. Puro: sale de la
    instantanea, sin consultar (Ronda 2, R4b: ritmo de cada carrera)."""
    out: dict[int | None, dict[date, int]] = {}
    for it in items:
        d = it.liberated_on
        if d is not None:
            serie = out.setdefault(it.program_id, {})
            serie[d] = serie.get(d, 0) + 1
    return out


# Ritmos de salida por motivo (Ronda 2, R4c): de que cola sale cada serie.
EXIT_KEYS = ("requests_reviewed", "access_granted", "docs_reviewed", "survey_reviewed",
             "library_registered")
# Eventos del expediente que son una SALIDA de su cola: dictamen de documento
# (Escolares), dictamen de la encuesta (GTV) y registro de Biblioteca (con
# adeudo o sin cargo). Revocar, revertir u observar no vacian la cola.
_EXIT_EVENTS = {
    "document_approved": "docs_reviewed",
    "document_rejected": "docs_reviewed",
    "survey_review_approved": "survey_reviewed",
    "survey_review_rejected": "survey_reviewed",
    "library_debt_registered": "library_registered",
    "library_no_charge": "library_registered",
}


def exit_counts(db: Session, *, cohort_ids, programs, include_unmapped: bool,
                start: date, end: date) -> dict[str, dict[date, int]]:
    """Salidas por dia de `start` a `end` (inclusivos), con el mismo alcance
    que `daily_counts`. Dos consultas, sin importar cuantas filas haya:

    1. solicitudes (UNION ALL de dos agregados):
       - `requests_reviewed`: revisadas (`reviewed_at`, la ULTIMA revision);
       - `access_granted`: accesos que dio Centro de Computo
         (`access_granted_at` con `access_granted_by_id` distinto de quien la
         reviso: la cuenta que Servicios Escolares crea al aprobar no es de
         Computo);
    2. eventos del expediente (`_EXIT_EVENTS`), por la carrera y convocatoria
       del proceso: `docs_reviewed` (dictamenes de documento),
       `survey_reviewed` (encuestas liberadas u observadas por GTV) y
       `library_registered` (registros de Biblioteca).

    Siempre trae las 5 llaves de `EXIT_KEYS` (dias sin salidas no aparecen).
    Sin nada visible (lista vacia de convocatorias, o ningun alcance sin
    `include_unmapped`) no consulta.
    """
    from sqlalchemy import literal_column, select, union_all

    from itcj2.apps.titulatec.models import (
        EnrollmentRequest,
        ProcessEvent,
        TitulationProcess,
    )

    out: dict[str, dict[date, int]] = {k: {} for k in EXIT_KEYS}
    if cohort_ids is not None and not list(cohort_ids):
        return out
    if programs != "ALL" and not programs and not include_unmapped:
        return out
    kw = {"cohort_ids": cohort_ids, "programs": programs, "include_unmapped": include_unmapped}
    desde = datetime.combine(start, datetime.min.time())
    antes_de = datetime.combine(end + timedelta(days=1), datetime.min.time())

    ER = EnrollmentRequest
    p_req = _filtros(ER, **kw)
    d_rev, d_acc = cast(ER.reviewed_at, Date), cast(ER.access_granted_at, Date)
    revisadas = (select(literal_column("'requests_reviewed'").label("k"), d_rev.label("d"),
                        func.count().label("n"))
                 .where(ER.reviewed_at >= desde, ER.reviewed_at < antes_de, *p_req)
                 .group_by(d_rev))
    accesos = (select(literal_column("'access_granted'").label("k"), d_acc.label("d"),
                      func.count().label("n"))
               .where(ER.access_granted_at >= desde, ER.access_granted_at < antes_de,
                      ER.access_granted_by_id.isnot(None),
                      ER.access_granted_by_id.is_distinct_from(ER.reviewed_by_id), *p_req)
               .group_by(d_acc))
    for k, d, n in db.execute(union_all(revisadas, accesos)).all():
        out[k][d] = out[k].get(d, 0) + int(n)

    PE, TP = ProcessEvent, TitulationProcess
    dia = cast(PE.created_at, Date)
    q = (db.query(PE.event_type, dia.label("d"), func.count().label("n"))
         .join(TP, TP.id == PE.process_id)
         .filter(PE.event_type.in_(sorted(_EXIT_EVENTS)),
                 PE.created_at >= desde, PE.created_at < antes_de, *_filtros(TP, **kw))
         .group_by(PE.event_type, dia))
    for tipo, d, n in q.all():
        serie = out[_EXIT_EVENTS[tipo]]
        serie[d] = serie.get(d, 0) + int(n)
    return out

"""Encargados del tablero de la jefa de Servicios Escolares: quiénes son, cuánta
cola cargan, cuánto produjeron y cuántos lugares de cita les quedan.

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §2 (D2),
§4.6 y §4.7. Solo lectura.

* `officers(db)` — encargados de carrera de Servicios Escolares (puestos
  `se_officer_*` del depto `school_services`, vía `OfficerService.list_officers`),
  UNA fila por persona con la unión de sus carreras. 4 consultas fijas.
* `queues(officers, items)` — **pura**, sobre los `Item` ya clasificados por
  `report_snapshot`. Traslape permitido (D2): cada encargado carga la cola
  COMPLETA de sus carreras, aunque otro encargado tenga las mismas; la suma por
  encargado rebasa los pendientes reales a propósito («cuánto pueden revisar
  aunque otros también puedan»).
* `production(db, ...)` — lo que hizo cada persona en un rango, por `actor_id`
  de `ProcessEvent` y `reviewed_by_id` de `EnrollmentRequest`; NO por alcance
  (la jefa o el admin también producen: la fachada los junta en «Otros»).
  2 consultas fijas. `by_day_from` (Ronda 2) alarga solo la serie `by_day`
  hasta los 10 días hábiles del ritmo, sin tocar los totales del rango.
* `capacity(db, ...)` — lugares de las ventanas abiertas en los próximos días
  hábiles, por dueño. 2 consultas fijas; la ocupación es la de
  `SlotService.window_occupancy_map` (regla única «¿esta cita ocupa lugar?»,
  CLAUDE.md de la app §15), no una cuenta propia.

Desviación verificada (reporte de la Task 5): la cola «solicitudes por
revisar» cuenta también `req_unverified` (legado). Es la misma pelota
(Escolares, «Revisar solicitud», ruling de la Task 3) y la bandeja la lista en
«Por revisar · anterior»: dejarla fuera escondería trabajo de Escolares.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Date, and_, cast, func, or_
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.utils.business_days import add_business_days

if TYPE_CHECKING:
    from itcj2.apps.titulatec.services.report_snapshot import Item

# Departamento y prefijo de los puestos que crea `OfficerService.create_officer`
# (`pages/officers.py::_DEPT_CODE_SCHOOL_SERVICES`).
DEPT_CODE = "school_services"
OFFICER_CODE_PREFIX = "se_officer_"

# Códigos del catálogo de `report_snapshot` (`STAGES`/`ACTORS`) que lee la cola;
# `test_report_officers.py` amarra que existan allá.
ESCOLARES = "escolares"
APPT_STAGE = "cita"
REQUEST_REVIEW_STAGES = frozenset({"req_unverified", "req_review"})

# Fase cuya aprobación es la liberación a Titulación (`HandoffService`; el
# mismo literal que `report_snapshot.PHASE_COTEJO`).
_PHASE_LIBERACION = 2

# Eventos de `ProcessEvent` que cuentan como producción -> llave de la fila.
# `phase_approved` solo cuenta con `phase_number = 2` (filtro en SQL).
_EVENT_KEYS = {
    "document_approved": "docs_approved",
    "document_rejected": "docs_rejected",
    "appointment_attended": "attended",
    "appointment_no_show": "no_show",
    "phase_approved": "liberated",
}
_DICTAMEN_KEYS = frozenset({"docs_approved", "docs_rejected"})
_PHASE_APPROVED = "phase_approved"

_WINDOW_OPEN = "open"


# ---------------------------------------------------------------------------
# Encargados
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Officer:
    """Un encargado de carrera (una PERSONA). `program_ids`: unión de las
    carreras de todos sus puestos `se_officer_*` vigentes (vacío = «Sin
    carreras asignadas»). `name`: `User.full_name`, el mismo que pinta la
    pestaña Encargados de la app."""
    user_id: int
    name: str
    program_ids: frozenset[int]


def _sort_key(name: str) -> str:
    """Orden alfabético sin distinguir mayúsculas ni acentos («Álvarez» junto
    a «Alvarez», no al final)."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", name or "")
                          if not unicodedata.combining(c))
    return sin_acentos.casefold()


def officers(db: Session) -> list[Officer]:
    """Encargados de carrera de Servicios Escolares, ordenados por nombre.

    `OfficerService.list_officers` (3 consultas) devuelve PUESTOS con sus
    ocupantes vigentes (`UserPosition.is_active`) y sus carreras; aquí se
    voltea a PERSONAS: quien ocupa varios puestos sale una vez, con la unión de
    carreras. Un puesto sin ocupantes no produce fila. Una cuenta desactivada
    (`User.is_active`) sale igual, como en la pestaña Encargados: su puesto y
    sus carreras siguen vigentes. Sin el departamento `school_services` (base
    sin sembrar), lista vacía. 4 consultas en total.
    """
    from itcj2.apps.titulatec.services.officer_service import OfficerService
    from itcj2.core.models.department import Department

    fila = (db.query(Department.id).filter(Department.code == DEPT_CODE)
            .order_by(Department.id).first())
    if fila is None:
        return []
    nombres: dict[int, str] = {}
    carreras: dict[int, set[int]] = {}
    for puesto in OfficerService.list_officers(db, fila[0],
                                               code_prefix=OFFICER_CODE_PREFIX):
        ids = {int(p["id"]) for p in puesto["programs"]}
        for u in puesto["users"]:
            uid = int(u["id"])
            nombres.setdefault(uid, u["name"] or "")
            carreras.setdefault(uid, set()).update(ids)
    salida = [Officer(user_id=uid, name=nombre, program_ids=frozenset(carreras[uid]))
              for uid, nombre in nombres.items()]
    salida.sort(key=lambda o: (_sort_key(o.name), o.user_id))
    return salida


# ---------------------------------------------------------------------------
# Cola (pura)
# ---------------------------------------------------------------------------
def queues(officers: list[Officer], items: list[Item]) -> dict[int, dict]:
    """Cola de cada encargado sobre los pendientes ya clasificados.

    `{user_id: {...}}` para TODO encargado pedido (ceros si no tiene nada):

    - `req_review`: solicitudes por revisar (`req_review` y la anterior
      `req_unverified`) de SUS carreras;
    - `docs_pending`: documentos por dictaminar (suma de `Item.pending_docs`,
      documentos, no procesos) de SUS carreras;
    - `appts_to_close`: pendientes en etapa `cita` con pelota de Escolares
      («Cerrar cita», «Dictaminar fase 2») cuya cita está en una ventana SUYA
      (`appt_owner_id`), sea de la carrera que sea;
    - `ready_to_book`: listos para agendar (`Item.ready_to_book`) de SUS
      carreras — informativo, no suma a la cola de Escolares;
    - `total_escolares` = `req_review` + `docs_pending` + `appts_to_close`.

    Traslape permitido (D2): dos encargados con la misma carrera ven la MISMA
    cola completa. Un pendiente sin carrera (`program_id` None) no cae en la
    cola de nadie. Sin BD: los `items` llegan ya filtrados por convocatoria y
    carreras visibles.
    """
    por_carrera: dict[int, list[int]] = {}       # program_id -> [req, docs, listos]
    cierres: dict[int, int] = {}                 # owner_user_id -> citas por cerrar
    for it in items:
        if (it.stage == APPT_STAGE and it.appt_owner_id is not None
                and any(actor == ESCOLARES for actor, _ in it.balls)):
            cierres[it.appt_owner_id] = cierres.get(it.appt_owner_id, 0) + 1
        if it.program_id is None:
            continue
        acc = por_carrera.setdefault(it.program_id, [0, 0, 0])
        if it.stage in REQUEST_REVIEW_STAGES:
            acc[0] += 1
        acc[1] += int(it.pending_docs or 0)
        if it.ready_to_book:
            acc[2] += 1

    salida: dict[int, dict] = {}
    for o in officers:
        req = docs = listos = 0
        for pid in o.program_ids:
            acc = por_carrera.get(pid)
            if acc is not None:
                req, docs, listos = req + acc[0], docs + acc[1], listos + acc[2]
        citas = cierres.get(o.user_id, 0)
        salida[o.user_id] = {
            "req_review": req,
            "docs_pending": docs,
            "appts_to_close": citas,
            "ready_to_book": listos,
            "total_escolares": req + docs + citas,
        }
    return salida


# ---------------------------------------------------------------------------
# Producción por actor
# ---------------------------------------------------------------------------
def _empty_production() -> dict:
    return {"req_reviewed": 0, "docs_approved": 0, "docs_rejected": 0,
            "reject_rate": None, "attended": 0, "no_show": 0, "liberated": 0,
            "by_day": {}}


def production(db: Session, *, start: date, end: date, cohort_ids,
               by_day_from: date | None = None) -> dict[int, dict]:
    """Lo que hizo cada persona entre `start` y `end` (días inclusivos).

    `by_day_from` (Ronda 2, R4a) alarga SOLO la serie `by_day` hacia atrás,
    hasta ese día: la proyección por encargado mide los últimos 10 días
    hábiles aunque el rango sea más corto. Los totales siguen siendo del rango
    y un actor que solo produjo en la parte alargada sale con totales en 0 (y
    su `by_day`). Un `by_day_from` posterior a `start` no recorta nada. Las
    mismas dos consultas, con la ventana ampliada.

    `{actor_id: {...}}` solo para quien hizo algo:

    - `req_reviewed`: solicitudes revisadas (`EnrollmentRequest.reviewed_by_id`
      con `reviewed_at` en rango; la columna guarda la ÚLTIMA revisión);
    - `docs_approved` / `docs_rejected`: dictámenes de documentos
      (`ProcessEvent` `document_approved` / `document_rejected`);
    - `reject_rate`: `docs_rejected / (docs_approved + docs_rejected)` como
      fracción 0..1, o `None` sin dictámenes;
    - `attended` / `no_show`: citas cerradas (`appointment_attended` /
      `appointment_no_show`);
    - `liberated`: fases 2 aprobadas (`phase_approved` con `phase_number = 2`);
    - `by_day`: `{fecha: dictámenes de documentos + revisiones de solicitud}`,
      solo días con algo (la serie de «Dictámenes por día»).

    Por actor, NO por alcance de carrera. Eventos sin actor (sistema) no
    cuentan. `cohort_ids=None` = todas las convocatorias; lista vacía, o
    `start > end`, no consulta nada. Dos consultas agregadas en SQL (por actor,
    tipo y día), sin importar cuántos eventos haya.
    """
    from itcj2.apps.titulatec.models import (
        EnrollmentRequest,
        ProcessEvent,
        TitulationProcess,
    )

    ids = None if cohort_ids is None else sorted({int(c) for c in cohort_ids})
    if ids is not None and not ids:
        return {}
    if start > end:
        return {}
    serie_desde = min(start, by_day_from) if by_day_from is not None else start
    desde = datetime.combine(serie_desde, time.min)
    antes_de = datetime.combine(end + timedelta(days=1), time.min)

    PE = ProcessEvent
    dia_ev = cast(PE.created_at, Date)
    contados = [e for e in _EVENT_KEYS if e != _PHASE_APPROVED]
    q_ev = (db.query(PE.actor_id, PE.event_type, dia_ev.label("d"), func.count().label("n"))
            .filter(PE.actor_id.isnot(None),
                    PE.created_at >= desde, PE.created_at < antes_de,
                    or_(PE.event_type.in_(contados),
                        and_(PE.event_type == _PHASE_APPROVED,
                             PE.phase_number == _PHASE_LIBERACION))))
    if ids is not None:
        q_ev = (q_ev.join(TitulationProcess, TitulationProcess.id == PE.process_id)
                .filter(TitulationProcess.cohort_id.in_(ids)))
    q_ev = q_ev.group_by(PE.actor_id, PE.event_type, dia_ev)

    ER = EnrollmentRequest
    dia_req = cast(ER.reviewed_at, Date)
    q_req = (db.query(ER.reviewed_by_id, dia_req.label("d"), func.count().label("n"))
             .filter(ER.reviewed_by_id.isnot(None),
                     ER.reviewed_at >= desde, ER.reviewed_at < antes_de))
    if ids is not None:
        q_req = q_req.filter(ER.cohort_id.in_(ids))
    q_req = q_req.group_by(ER.reviewed_by_id, dia_req)

    salida: dict[int, dict] = {}
    for actor, tipo, dia, n in q_ev.all():
        llave = _EVENT_KEYS[tipo]
        if dia < start and llave not in _DICTAMEN_KEYS:
            continue                    # fuera del rango y no es de la serie
        fila = salida.setdefault(int(actor), _empty_production())
        if dia >= start:
            fila[llave] += int(n)
        if llave in _DICTAMEN_KEYS:
            fila["by_day"][dia] = fila["by_day"].get(dia, 0) + int(n)
    for actor, dia, n in q_req.all():
        fila = salida.setdefault(int(actor), _empty_production())
        if dia >= start:
            fila["req_reviewed"] += int(n)
        fila["by_day"][dia] = fila["by_day"].get(dia, 0) + int(n)
    for fila in salida.values():
        dictamenes = fila["docs_approved"] + fila["docs_rejected"]
        fila["reject_rate"] = fila["docs_rejected"] / dictamenes if dictamenes else None
        fila["by_day"] = dict(sorted(fila["by_day"].items()))
    return salida


# ---------------------------------------------------------------------------
# Capacidad de citas
# ---------------------------------------------------------------------------
def _upcoming_business_days(today: date, days: int, *,
                            holidays: frozenset[date] = frozenset()) -> list[date]:
    """Los `days` días hábiles desde `today` inclusive (si `today` es fin de
    semana, desde el lunes siguiente)."""
    if days <= 0:
        return []
    primero = add_business_days(today, 0, holidays=holidays)
    return [primero] + [add_business_days(primero, i, holidays=holidays)
                        for i in range(1, days)]


def capacity(db: Session, *, today: date, days: int = 5,
             holidays: frozenset[date] = frozenset()) -> dict[int, tuple[int, int]]:
    """Lugares de cita en los próximos `days` días hábiles (desde hoy
    inclusive): `{owner_user_id: (ocupados, capacidad)}`, llave `0` = total
    (siempre presente, `(0, 0)` sin ventanas).

    Solo ventanas `status = 'open'` de días de cotejo habilitados
    (`CohortReviewDay.is_closed = False`, spec §4.6 «de días habilitados») cuya
    fecha es uno de esos días hábiles; de cualquier convocatoria. Ocupados y
    capacidad salen de `SlotService.window_occupancy_map` (citas vivas en una
    franja real; `cancelled`/`superseded` no ocupan). Dos consultas: las
    ventanas y la ocupación en lote.
    """
    from itcj2.apps.titulatec.models import CohortReviewDay, ReviewWindow
    from itcj2.apps.titulatec.services.slot_service import SlotService

    salida: dict[int, tuple[int, int]] = {0: (0, 0)}
    dias = _upcoming_business_days(today, days, holidays=holidays)
    if not dias:
        return salida
    ventanas = (db.query(ReviewWindow)
                .join(CohortReviewDay, CohortReviewDay.id == ReviewWindow.review_day_id)
                .filter(ReviewWindow.status == _WINDOW_OPEN,
                        CohortReviewDay.is_closed.is_(False),
                        CohortReviewDay.date.in_(dias))
                .order_by(ReviewWindow.id)
                .all())
    if not ventanas:
        return salida
    ocupacion = SlotService.window_occupancy_map(db, ventanas)
    total_ocupados = total_capacidad = 0
    for w in ventanas:
        ocupados, cap = ocupacion.get(w.id, (0, 0))
        previo = salida.get(w.owner_user_id, (0, 0))
        salida[w.owner_user_id] = (previo[0] + ocupados, previo[1] + cap)
        total_ocupados += ocupados
        total_capacidad += cap
    salida[0] = (total_ocupados, total_capacidad)
    return salida

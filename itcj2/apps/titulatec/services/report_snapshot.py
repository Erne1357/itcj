"""Instantánea del tablero de la jefa de Servicios Escolares: etapa, pelota y
días sin movimiento de cada pendiente.

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §4.1-§4.4
(las definiciones son el contrato de los números). Solo lectura.

Dos capas:

* **Puras** (`classify_request`, `classify_process`): de una fila ya cargada
  (`RequestRow`/`ProcessRow`) a un `Item` con su etapa (`STAGES`), quién debe
  moverlo (`balls`, una entrada por actor de `ACTORS`) y cuántos días lleva
  quieto (`idle_days`/`level`). «Hoy» entra como parámetro: nada aquí llama a
  `date.today()`.
* **Carga en lote** (`load_snapshot`): dos consultas propias (solicitudes
  vivas; procesos con su usuario, carrera, fase 2, cita vigente + ventana,
  último evento y documentos por dictaminar) más las de
  `ClearanceGate.status_map` (a lo más 4) para los procesos en fase 2. Las
  mismas consultas con 3 que con 300 pendientes.

Las liberaciones (encuesta de egresados y no adeudo de biblioteca) NO se leen
aquí: las responde `ClearanceGate` (invariante 2, `test_clearance_gate.py`)
como códigos de bloqueo de su conjunto cerrado `BLOCKERS`, y este módulo solo
los traduce a pelotas (`_BLOCKER_BALLS`). Así hereda también el candado
condicional por convocatoria (invariante 8: sin el requisito de no adeudo
activo, biblioteca pendiente no detiene a nadie).

Desviaciones verificadas contra el código (reporte de la Task 3):

* `unverified` (legado) es pelota de **Escolares**, no del alumno: la liga de
  confirmación ya no existe (`EnrollmentRequestService.verify` responde
  `invalid` a todo lo que no esté `approved`) y la bandeja la lista en «Por
  revisar · anterior» (`pages/requests_admin.py::_TAB_STATUSES`).
* `observed` (biblioteca «Con observaciones») es pelota del **alumno**: el
  correo le pide acudir a Biblioteca a aclararlas
  (`templates/titulatec/email/library_observed.html`); Biblioteca solo
  «Activa» después.
* La liga de una solicitud lleva la pestaña (`status`): la bandeja abre por
  omisión en «Por revisar» y con `?q=` a secas no encontraría una en Cómputo o
  con liga enviada.

Decisiones del controlador (ronda 0):

* `req_approved` cuenta los días desde lo ÚLTIMO entre `reviewed_at` y
  `access_granted_at` (la liga de una D10 sale cuando Cómputo da acceso);
  `req_access` sigue en `reviewed_at` (solo se entra al aprobar Escolares).
* `req_approved` con la liga VENCIDA es pelota de Escolares («Reenviar liga»):
  el egresado ya no puede activarla solo. Vencida = sin vigencia o con
  `verify_expires_at` de un día anterior a hoy (el servicio compara contra el
  instante, `verify()`; aquí solo se conoce «hoy»).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from urllib.parse import urlencode

from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Catálogos (orden fijo: lo pintan las gráficas tal cual)
# ---------------------------------------------------------------------------
# Grupos de etapa: rampa ordinal de 5 pasos validada (spec §7). Las 8 etapas
# toman el color de su grupo (una rampa de 8 falla la separación adyacente).
STAGE_GROUPS: list[tuple[str, str, str]] = [
    ("solicitud", "Solicitud", "#86b6ef"),
    ("documentos", "Documentos", "#3987e5"),
    ("requisitos", "Requisitos", "#256abf"),
    ("cita", "Cita", "#184f95"),
    ("liberado", "Liberado", "#0d366b"),
]

# (código, etiqueta, grupo) — §4.2, ordinales.
STAGES: list[tuple[str, str, str]] = [
    ("req_unverified", "Solicitud anterior (por revisar)", "solicitud"),
    ("req_review", "Solicitud por revisar", "solicitud"),
    ("req_access", "Esperando NIP", "solicitud"),
    ("req_approved", "Aprobada, sin activar", "solicitud"),
    ("docs", "Documentos iniciales", "documentos"),
    ("requisitos", "Requisitos de cotejo", "requisitos"),
    ("cita", "En cita de cotejo", "cita"),
    ("liberado", "Liberado a Titulación", "liberado"),
]

# (código, etiqueta, color) — identidad categórica de cada actor (spec §7).
ACTORS: list[tuple[str, str, str]] = [
    ("escolares", "Escolares", "#2a78d6"),
    ("alumno", "Alumno", "#eb6834"),
    ("gtv", "GTV", "#1baf7a"),
    ("biblioteca", "Biblioteca/Caja", "#eda100"),
    ("computo", "Cómputo", "#e87ba4"),
]

# Motivos (texto UI de la pelota, §4.3). Si un actor tiene dos motivos en el
# mismo pendiente, `balls` los une con " · " en UNA entrada.
MOTIVE_REVIEW_REQUEST = "Revisar solicitud"
MOTIVE_REVIEW_LEGACY = "Revisar solicitud (legado)"     # `unverified`, spec §4.3 corregida
MOTIVE_GIVE_NIP = "Dar NIP"
MOTIVE_ACTIVATE_ACCOUNT = "Activar su cuenta"
MOTIVE_RESEND_LINK = "Reenviar liga"
MOTIVE_REVIEW_DOCS = "Dictaminar documentos"
MOTIVE_UPLOAD_DOCS = "Subir o corregir documentos"
MOTIVE_FILL_SURVEY = "Llenar encuesta de egresados"
MOTIVE_RELEASE_SURVEY = "Liberar encuesta"
MOTIVE_FIX_SURVEY = "Corregir encuesta"
MOTIVE_REGISTER_CLEARANCE = "Registrar no adeudo"
MOTIVE_PAY = "Pagar en Caja"
MOTIVE_LIBRARY_OBSERVED = "Atender observación de Biblioteca"
MOTIVE_BOOK = "Agendar cita"
MOTIVE_CLOSE_APPT = "Cerrar cita"
MOTIVE_REVIEW_PHASE2 = "Dictaminar fase 2"
MOTIVE_RESCHEDULE = "Reagendar"
MOTIVE_FIX_PHASE2 = "Corregir lo señalado"
# Respaldo para un código de bloqueo que el gate agregue sin regla aquí (la
# prueba de contrato lo atrapa antes; en producción no truena la página).
MOTIVE_UNKNOWN_BLOCKER = "Revisar requisitos de cotejo"

# Números de fase (mismo literal que `PhaseService.PHASE_COTEJO` y los dueños
# de las liberaciones; la spec define las etapas por número).
PHASE_DOCS = 1
PHASE_COTEJO = 2

_ESCOLARES, _ALUMNO, _GTV, _BIBLIOTECA, _COMPUTO = (a for a, _, _ in ACTORS)
_ACTOR_ORDER = {a: i for i, (a, _, _) in enumerate(ACTORS)}

# Solicitudes: estado -> etapa, pelota, pestaña de la bandeja.
_REQUEST_STAGE = {
    "unverified": "req_unverified",
    "verified": "req_review",
    "pending_review": "req_review",
    "awaiting_access": "req_access",
    "approved": "req_approved",
}
_REQUEST_BALL = {
    "req_unverified": (_ESCOLARES, MOTIVE_REVIEW_LEGACY),    # desviación (docstring)
    "req_review": (_ESCOLARES, MOTIVE_REVIEW_REQUEST),
    "req_access": (_COMPUTO, MOTIVE_GIVE_NIP),
    "req_approved": (_ALUMNO, MOTIVE_ACTIVATE_ACCOUNT),
}
_REQUEST_TAB = {
    "req_unverified": "pending_review",
    "req_review": "pending_review",
    "req_access": "awaiting_access",
    "req_approved": "approved",
}
# Por revisar / anterior: tiempo de espera desde el alta. En Cómputo: desde la
# revisión de Escolares. Con liga: desde lo último entre esa revisión y el
# acceso de Cómputo (§4.4 + ronda 0, ver `classify_request`).
_WAIT_FROM_CREATION = frozenset({"req_unverified", "req_review"})
_REQUESTS_URL = "/titulatec/admin/solicitudes"
_PROCESS_URL = "/titulatec/admin/processes/{id}"

# Código de bloqueo de `ClearanceGate` -> pelota (§4.3, filas de requisitos).
_BLOCKER_BALLS = {
    "survey_missing": (_ALUMNO, MOTIVE_FILL_SURVEY),
    "survey_in_review": (_GTV, MOTIVE_RELEASE_SURVEY),
    "survey_rejected": (_ALUMNO, MOTIVE_FIX_SURVEY),
    "library_pending": (_BIBLIOTECA, MOTIVE_REGISTER_CLEARANCE),
    "library_awaiting_payment": (_ALUMNO, MOTIVE_PAY),
    "library_observed": (_ALUMNO, MOTIVE_LIBRARY_OBSERVED),   # desviación (docstring)
}

# Cita vigente: los estados VIVOS (= `SlotService._ESTADOS_ACTIVOS`) y los que
# además dejan el proceso en la etapa `cita` (§4.2). `cancelled`/`superseded`
# no son cita: el proceso vuelve a «requisitos».
_APPT_LIVE = frozenset({"scheduled", "confirmed", "in_progress"})
_APPT_BOOKED = frozenset({"scheduled", "confirmed"})
_APPT_IN_STAGE = _APPT_LIVE | {"attended", "no_show"}

# Procesos que se leen: los vivos, los pausados (se cuentan aparte) y los
# terminados (para «liberado»). `cancelled` queda fuera.
_PROCESS_STATUSES = ("active", "on_hold", "completed")


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportConfig:
    """Umbrales de «Lento» (`warn_days`) y «Atorado» (`crit_days`)."""
    warn_days: int
    crit_days: int

    @staticmethod
    def from_settings() -> ReportConfig:
        """`TITULATEC_IDLE_WARN_DAYS`/`TITULATEC_IDLE_CRIT_DAYS` (D8)."""
        from itcj2.config import get_settings

        s = get_settings()
        return ReportConfig(warn_days=int(s.TITULATEC_IDLE_WARN_DAYS),
                            crit_days=int(s.TITULATEC_IDLE_CRIT_DAYS))


@dataclass(frozen=True)
class Item:
    """Un pendiente (solicitud o proceso) o un liberado.

    `balls`: `((actor, motivo), ...)`, UNA entrada por actor en el orden de
    `ACTORS` (dos motivos del mismo actor van unidos con " · "); vacío si está
    en agenda (cita futura) o liberado. `len(balls) == 2` = «espera a dos
    áreas». `level`: `ok` | `warn` | `crit` (una cita futura nunca es atorado).
    `ready_to_book`: sin liberaciones pendientes y sin una cita que ocupe el
    cotejo (puede agendar, o que le agenden). `appt_owner_id`/`appt_date`: de
    la cita VIGENTE (dueño de su ventana). `liberated_on`: fecha de
    `ProcessPhase(2).completed_at`; `liberated_by_id`: quien aprobó la fase 2.
    """
    kind: str                                   # "request" | "process"
    id: int
    cohort_id: int
    program_id: int | None
    stage: str
    balls: tuple[tuple[str, str], ...]
    idle_days: int
    level: str
    label: str                                  # "Nombre Apellido · control"
    control: str
    href: str
    pending_docs: int = 0
    ready_to_book: bool = False
    appt_owner_id: int | None = None
    appt_date: date | None = None
    liberated_on: date | None = None
    liberated_by_id: int | None = None


@dataclass(frozen=True)
class RequestRow:
    """Lo mínimo de una `EnrollmentRequest` viva para clasificarla.

    `access_granted_at`: cuándo Cómputo dio acceso (en una D10, cuándo salió
    la liga). `verify_expires_at`: vigencia de la liga de activación; `None`
    en una `approved` cuenta como vencida, igual que en el servicio."""
    id: int
    cohort_id: int
    program_id: int | None
    status: str
    first_name: str
    last_name: str
    middle_name: str | None
    control_number: str | None
    created_at: datetime
    reviewed_at: datetime | None
    updated_at: datetime | None
    access_granted_at: datetime | None
    verify_expires_at: datetime | None


@dataclass(frozen=True)
class ProcessRow:
    """Lo mínimo de un `TitulationProcess` para clasificarlo.

    `blockers`: códigos de `ClearanceGate.blockers` (encuesta primero); vacío =
    liberaciones completas. Solo se llenan para procesos en fase 2.
    `appt_*`: la cita VIGENTE (`is_current`), sea cual sea su estado.
    """
    id: int
    cohort_id: int
    program_id: int | None
    process_status: str
    current_phase: int
    created_at: datetime
    last_event_at: datetime | None
    first_name: str
    last_name: str
    middle_name: str | None
    control_number: str | None
    pending_docs: int
    phase2_status: str | None
    phase2_completed_at: datetime | None
    phase2_reviewed_by_id: int | None
    appt_status: str | None
    appt_scheduled_at: datetime | None
    appt_owner_id: int | None
    blockers: tuple[str, ...] = ()


@dataclass
class Snapshot:
    """`items`: pendientes y liberados ya clasificados (solicitudes primero,
    luego procesos, cada grupo por id). `on_hold`: procesos «En pausa» sin
    liberar (no entran a etapas). `program_names`: carreras de `items`."""
    items: list[Item] = field(default_factory=list)
    on_hold: int = 0
    program_names: dict[int, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Puras
# ---------------------------------------------------------------------------
def idle_level(days: int, cfg: ReportConfig) -> str:
    """`crit` desde `crit_days`, `warn` desde `warn_days`, si no `ok`."""
    if days >= cfg.crit_days:
        return "crit"
    if days >= cfg.warn_days:
        return "warn"
    return "ok"


def _days_since(today: date, when: datetime | date | None) -> int:
    """Días naturales de `when` a `today`; nunca negativo, 0 sin fecha."""
    if when is None:
        return 0
    dia = when.date() if isinstance(when, datetime) else when
    return max(0, (today - dia).days)


def _latest(*moments):
    vivos = [m for m in moments if m is not None]
    return max(vivos) if vivos else None


def _label(first: str | None, last: str | None, middle: str | None,
           control: str | None) -> str:
    nombre = " ".join(p for p in (first, last, middle) if p)
    return f"{nombre} · {control}" if control else nombre


def _merge_balls(pairs) -> tuple[tuple[str, str], ...]:
    """Una entrada por actor, en el orden de `ACTORS`; motivos sin repetir."""
    by_actor: dict[str, list[str]] = {}
    for actor, motive in pairs:
        motivos = by_actor.setdefault(actor, [])
        if motive not in motivos:
            motivos.append(motive)
    return tuple((actor, " · ".join(by_actor[actor]))
                 for actor in sorted(by_actor, key=lambda a: _ACTOR_ORDER.get(a, len(ACTORS))))


def _link_expired(expires_at: datetime | None, today: date) -> bool:
    """¿Venció la liga de activación? Mismo criterio que el servicio
    (`EnrollmentRequestService.verify`: sin vigencia o ya pasada), pero por DÍA:
    aquí solo se conoce «hoy», así que una liga que vence hoy -a cualquier
    hora- sigue vigente hasta mañana."""
    return expires_at is None or expires_at.date() < today


def _is_liberated(row: ProcessRow) -> bool:
    """Liberado a Titulación = fase 2 aprobada (`HandoffService`)."""
    return row.phase2_status == "approved"


def classify_request(row: RequestRow, today: date, cfg: ReportConfig) -> Item:
    """Etapa, pelota y espera de una solicitud viva (`OPEN_STATUSES`).

    Espera: por revisar/anterior desde el alta; en Cómputo desde `reviewed_at`
    (a `awaiting_access` solo se entra al aprobar Escolares; un
    `access_granted_at` ahí es de un ciclo anterior); con liga desde lo último
    entre `reviewed_at` y `access_granted_at` (D10: Cómputo da acceso CON cuenta
    y en ese momento sale la liga). Sin ninguna, `updated_at`.

    Con la liga vencida (`_link_expired`) la aprobada es de Escolares.

    `ValueError` si la solicitud ya no está viva (`converted`/`rejected`)."""
    stage = _REQUEST_STAGE.get(row.status)
    if stage is None:
        raise ValueError(f"La solicitud {row.id} no es un pendiente: {row.status!r}")
    if stage in _WAIT_FROM_CREATION:
        since = row.created_at
    elif stage == "req_approved":
        since = _latest(row.reviewed_at, row.access_granted_at) or row.updated_at
    else:
        since = row.reviewed_at or row.updated_at
    ball = _REQUEST_BALL[stage]
    if stage == "req_approved" and _link_expired(row.verify_expires_at, today):
        ball = (_ESCOLARES, MOTIVE_RESEND_LINK)
    idle = _days_since(today, since)
    control = row.control_number or ""
    return Item(
        kind="request", id=row.id, cohort_id=row.cohort_id, program_id=row.program_id,
        stage=stage, balls=(ball,), idle_days=idle,
        level=idle_level(idle, cfg),
        label=_label(row.first_name, row.last_name, row.middle_name, control),
        control=control,
        href=f"{_REQUESTS_URL}?{urlencode({'status': _REQUEST_TAB[stage], 'q': control})}",
    )


def classify_process(row: ProcessRow, today: date, cfg: ReportConfig) -> Item:
    """Etapa, pelota y días sin movimiento de un proceso (§4.2-§4.4).

    Fase 2 aprobada = `liberado` (sin pelota, `idle_days` 0). `current_phase`
    menor que 2 (la 0 incluida) = `docs`. De la 2 en adelante sin la fase 2
    aprobada (no debería existir: solo aprobarla avanza) se lee como fase 2.

    Fase 2 sin veredicto, en este orden: una cita VIVA manda (futura = en
    agenda, sin pelota ni atorado; pasada o en curso = Escolares la cierra);
    si no, la fase 2 rechazada es del alumno; sin cita, los requisitos
    abiertos (o «Agendar cita» si no queda ninguno); `attended` sin dictamen
    es de Escolares y `no_show` del alumno. Las liberaciones abiertas se SUMAN
    salvo con una cita viva (D17: la cita agendada no vuelve a preguntar)."""
    control = row.control_number or ""
    pending_docs = int(row.pending_docs or 0)
    with_appt = row.appt_status in _APPT_IN_STAGE
    appt_date = (row.appt_scheduled_at.date()
                 if with_appt and row.appt_scheduled_at is not None else None)
    common = {
        "kind": "process", "id": row.id, "cohort_id": row.cohort_id,
        "program_id": row.program_id,
        "label": _label(row.first_name, row.last_name, row.middle_name, control),
        "control": control, "href": _PROCESS_URL.format(id=row.id),
        "pending_docs": pending_docs,
        "appt_owner_id": row.appt_owner_id if with_appt else None, "appt_date": appt_date,
    }

    if _is_liberated(row):
        done = row.phase2_completed_at
        return Item(**common, stage="liberado", balls=(), idle_days=0, level="ok",
                    liberated_on=done.date() if done is not None else None,
                    liberated_by_id=row.phase2_reviewed_by_id)

    idle = _days_since(today, _latest(row.last_event_at, row.created_at))

    if row.current_phase < PHASE_COTEJO:
        ball = ((_ESCOLARES, MOTIVE_REVIEW_DOCS) if pending_docs > 0
                else (_ALUMNO, MOTIVE_UPLOAD_DOCS))
        return Item(**common, stage="docs", balls=(ball,), idle_days=idle,
                    level=idle_level(idle, cfg))

    open_reqs = [_BLOCKER_BALLS.get(code, (_ESCOLARES, MOTIVE_UNKNOWN_BLOCKER))
                 for code in row.blockers]
    in_agenda = False
    if row.appt_status in _APPT_LIVE:
        if (row.appt_status in _APPT_BOOKED and appt_date is not None
                and appt_date >= today):
            in_agenda, pairs = True, []
        else:
            pairs = [(_ESCOLARES, MOTIVE_CLOSE_APPT)]
    elif row.phase2_status == "rejected":
        pairs = [(_ALUMNO, MOTIVE_FIX_PHASE2), *open_reqs]
    elif not with_appt:
        pairs = open_reqs or [(_ALUMNO, MOTIVE_BOOK)]
    elif row.appt_status == "attended":
        pairs = [(_ESCOLARES, MOTIVE_REVIEW_PHASE2), *open_reqs]
    else:                                                   # no_show
        pairs = [(_ALUMNO, MOTIVE_RESCHEDULE), *open_reqs]

    # ¿La cita vigente ocupa el cotejo? Mismo criterio que
    # `SelfBookingService.cita_ocupa_el_cotejo`: viva, o atendida sin veredicto.
    occupies = (row.appt_status in _APPT_LIVE
                or (row.appt_status == "attended" and row.phase2_status != "rejected"))
    return Item(**common, stage="cita" if with_appt else "requisitos",
                balls=_merge_balls(pairs), idle_days=idle,
                level="ok" if in_agenda else idle_level(idle, cfg),
                ready_to_book=not row.blockers and not occupies)


# ---------------------------------------------------------------------------
# Carga en lote
# ---------------------------------------------------------------------------
def _scope_filters(model, *, cohort_ids, programs, include_unmapped) -> list:
    """Predicados de convocatoria y carrera sobre `model` (solicitud o proceso).

    `cohort_ids=None` = todas. `programs="ALL"` no filtra por carrera; un set
    filtra por `program_id`. `program_id NULL` (cubo «Sin carrera») entra SOLO
    con `include_unmapped`, también con "ALL" (como `scope_service`: `read.all`
    no abre ese cubo). Set vacío sin `include_unmapped` = `false()`: no trae
    nada. Mismo criterio que `report_flow._filtros`. `load_snapshot` además
    corta ese caso antes de consultar.
    """
    from sqlalchemy import false, or_

    preds = []
    if cohort_ids is not None:
        preds.append(model.cohort_id.in_(sorted({int(c) for c in cohort_ids})))
    if programs == "ALL":
        if not include_unmapped:
            preds.append(model.program_id.isnot(None))
        return preds
    ids = sorted({int(p) for p in programs})
    if ids and include_unmapped:
        preds.append(or_(model.program_id.in_(ids), model.program_id.is_(None)))
    elif ids:
        preds.append(model.program_id.in_(ids))
    elif include_unmapped:
        preds.append(model.program_id.is_(None))
    else:
        preds.append(false())       # sin alcance: no trae nada (ni «Sin carrera»)
    return preds


def load_snapshot(db: Session, *, cohort_ids: list[int] | None, programs: set[int] | str,
                  include_unmapped: bool, today: date, cfg: ReportConfig) -> Snapshot:
    """Todos los pendientes (y liberados) de las convocatorias y carreras
    pedidas, clasificados. Consultas FIJAS, sin importar cuántos haya:

    1. solicitudes vivas (`OPEN_STATUSES`) con el nombre de su carrera;
    2. procesos `active`/`on_hold`/`completed` con su usuario, carrera, fase 2,
       cita VIGENTE + dueño de su ventana, último `ProcessEvent` y documentos
       de fase 1 por dictaminar (los dos últimos como subconsultas
       correlacionadas por índice, una fila por proceso);
    3. `ClearanceGate.status_map` (a lo más 4) para los procesos en fase 2 sin
       liberar.

    `cohort_ids=None` = todas; `programs="ALL"` o un set de ids. Lista vacía de
    convocatorias, o ningún alcance sin `include_unmapped`, no consulta nada.
    `on_hold` sin liberar va a `Snapshot.on_hold`; liberado, a `items` aunque
    esté en pausa o terminado (la liberación ocurrió). `cancelled` queda fuera.
    """
    from sqlalchemy import and_, func, select

    from itcj2.apps.titulatec.models import (
        Document,
        EnrollmentRequest,
        ProcessEvent,
        ProcessPhase,
        ReviewAppointment,
        ReviewWindow,
        TitulationProcess,
    )
    from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User

    if cohort_ids is not None and not list(cohort_ids):
        return Snapshot()
    if programs != "ALL" and not programs and not include_unmapped:
        return Snapshot()
    scope = {"cohort_ids": cohort_ids, "programs": programs, "include_unmapped": include_unmapped}

    # 1. Solicitudes vivas.
    ER = EnrollmentRequest
    req_rows = (
        db.query(ER.id, ER.cohort_id, ER.program_id, ER.status, ER.first_name,
                 ER.last_name, ER.middle_name, ER.control_number, ER.created_at,
                 ER.reviewed_at, ER.updated_at, ER.access_granted_at, ER.verify_expires_at,
                 Program.name.label("program_name"))
        .outerjoin(Program, Program.id == ER.program_id)
        .filter(ER.status.in_(OPEN_STATUSES), *_scope_filters(ER, **scope))
        .order_by(ER.id)
        .all()
    )

    # 2. Procesos. Las uniones son 1:1: `(process_id, phase_number)` es UNIQUE
    # y hay como mucho UNA cita vigente por proceso (`uq_titulatec_review_appt_
    # current`), así que ninguna multiplica filas.
    TP = TitulationProcess
    last_event = (select(func.max(ProcessEvent.created_at))
                  .where(ProcessEvent.process_id == TP.id)
                  .correlate(TP).scalar_subquery())
    pending_docs = (select(func.count(Document.id))
                    .where(Document.process_id == TP.id,
                           Document.phase_number == PHASE_DOCS,
                           Document.review_status == "pending")
                    .correlate(TP).scalar_subquery())
    proc_rows = (
        db.query(TP.id, TP.cohort_id, TP.program_id, TP.status.label("process_status"),
                 TP.current_phase, TP.created_at,
                 User.first_name, User.last_name, User.middle_name, User.control_number,
                 Program.name.label("program_name"),
                 ProcessPhase.status.label("phase2_status"),
                 ProcessPhase.completed_at.label("phase2_completed_at"),
                 ProcessPhase.reviewed_by_id.label("phase2_reviewed_by_id"),
                 ReviewAppointment.status.label("appt_status"),
                 ReviewAppointment.scheduled_at.label("appt_scheduled_at"),
                 ReviewWindow.owner_user_id.label("appt_owner_id"),
                 last_event.label("last_event_at"), pending_docs.label("pending_docs"))
        .join(User, User.id == TP.student_id)
        .outerjoin(Program, Program.id == TP.program_id)
        .outerjoin(ProcessPhase, and_(ProcessPhase.process_id == TP.id,
                                      ProcessPhase.phase_number == PHASE_COTEJO))
        .outerjoin(ReviewAppointment, and_(ReviewAppointment.process_id == TP.id,
                                           ReviewAppointment.is_current.is_(True)))
        .outerjoin(ReviewWindow, ReviewWindow.id == ReviewAppointment.window_id)
        .filter(TP.status.in_(_PROCESS_STATUSES), *_scope_filters(TP, **scope))
        .order_by(TP.id)
        .all()
    )

    snap = Snapshot()
    for r in req_rows:
        if r.program_id is not None and r.program_name:
            snap.program_names[r.program_id] = r.program_name
        snap.items.append(classify_request(RequestRow(
            id=r.id, cohort_id=r.cohort_id, program_id=r.program_id, status=r.status,
            first_name=r.first_name, last_name=r.last_name, middle_name=r.middle_name,
            control_number=r.control_number, created_at=r.created_at,
            reviewed_at=r.reviewed_at, updated_at=r.updated_at,
            access_granted_at=r.access_granted_at,
            verify_expires_at=r.verify_expires_at), today, cfg))

    rows: list[tuple[ProcessRow, str | None]] = []
    for r in proc_rows:
        row = ProcessRow(
            id=r.id, cohort_id=r.cohort_id, program_id=r.program_id,
            process_status=r.process_status, current_phase=int(r.current_phase or 0),
            created_at=r.created_at, last_event_at=r.last_event_at,
            first_name=r.first_name, last_name=r.last_name, middle_name=r.middle_name,
            control_number=r.control_number, pending_docs=int(r.pending_docs or 0),
            phase2_status=r.phase2_status, phase2_completed_at=r.phase2_completed_at,
            phase2_reviewed_by_id=r.phase2_reviewed_by_id, appt_status=r.appt_status,
            appt_scheduled_at=r.appt_scheduled_at, appt_owner_id=r.appt_owner_id)
        if not _is_liberated(row):
            if row.process_status == "on_hold":
                snap.on_hold += 1
                continue
            if row.process_status != "active":
                continue        # terminado sin la fase 2 aprobada: nada pendiente aquí
        rows.append((row, r.program_name))

    # 3. Liberaciones de los que están en fase 2: códigos de bloqueo del gate.
    gate_ids = [row.id for row, _ in rows
                if not _is_liberated(row) and row.current_phase >= PHASE_COTEJO]
    gate = ClearanceGate.status_map(db, gate_ids) if gate_ids else {}

    for row, program_name in rows:
        if row.id in gate:
            row = replace(row, blockers=tuple(ClearanceGate.blockers(gate[row.id])))
        if row.program_id is not None and program_name:
            snap.program_names[row.program_id] = program_name
        snap.items.append(classify_process(row, today, cfg))
    return snap

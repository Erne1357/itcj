"""Fachada del Tablero de la jefa de Servicios Escolares (2026-10-14).

Spec `docs/superpowers/specs/2026-10-14-titulatec-tablero-design.md` §3
(parámetros de URL), §4 (definiciones), §5 (pestañas) y §8 (bordes). Solo
lectura: une la instantánea (`report_snapshot`), el flujo (`report_flow`) y los
encargados (`report_officers`) en un contexto PLANO por pestaña.

* `ReportFilters` — el estado de la vista en la URL. `parse` nunca levanta: un
  valor inválido cae a su default (spec §8). `query`/`page_url`/`body_url` arman
  las ligas de pestañas, chips y celdas: orden fijo, `tab` siempre presente y
  los demás parámetros solo si no valen su default.
* `ReportService.build(db, *, user_id, filters, today)` — contexto común +
  el de la pestaña activa bajo la llave del mismo nombre (`panorama`, `ritmo`,
  `encargados`, `carreras`, `atorados`). Solo calcula lo que esa pestaña pinta.
  Todo número viene hecho y toda geometría sale de `utils/charts`: la plantilla
  no hace aritmética. Las llaves exactas de cada pestaña están en el docstring de
  su `_ctx_<tab>` (contrato con la Task 7); las comunes, en `_common_ctx`.

Alcance (defensa en profundidad, spec §3): la instantánea se carga con las
carreras de `scope_service.officer_programs()` menos las ocultas (`px`), y el
cubo «Sin carrera» solo con `can_see_unmapped()` y sin `px=0`. Las carreras
ocultas no se consultan: su chip sale del catálogo `core_programs` (una consulta,
solo cuando hay alguna oculta). La convocatoria por omisión es la `open` más
reciente; si no hay, la más reciente (`Cohort.status`: draft|open|closed).

Consultas por pestaña (`/body`, caché de authz tibia; techo 24 desde la
Ronda 2 -spec §12, R5-, lo fija `test_reports_pages.py` con 4 y 16 procesos):
convocatorias 1 + catálogo de carreras 0-1 (solo con `px`) + encargados 0-4
(solo con `ox`, para validarlo; se reusan en la pestaña) + instantánea 2-6 + lo
propio de la pestaña — Panorama: series 3 + salidas por motivo 2
(`report_flow.exit_counts`, Ronda 2) + capacidad 0-2 (solo con listos para
agendar); Ritmo: series 3 + nombres de quien liberó 0-1 (solo con `day`);
Encargados: encargados 4 + producción 2 (con la serie alargada a los 10 días
hábiles del ritmo, mismas 2) + capacidad 2 + nombres de carrera 0-1; Carreras
y Atorados: encargados 4 (las proyecciones por carrera y los motivos salen de
la instantánea, sin consultar). Medido el 2026-10-14 en el peor camino (con
`px` y `ox`; Atorados además con `motive`): Panorama 19 · Ritmo 16 ·
Encargados 16 · Carreras 12 · Atorados 12. Ninguna crece con el número de
procesos. Un usuario acotado por carrera suma 1 (sus carreras).

Ronda 2 (spec §12; contrato con la Task U2 en los docstrings de cada
`_ctx_<tab>`): motivos con código y barra partida por motivo en Panorama
(`balls[*].motives`, cada pendiente en su PRIMER motivo por área), filtro
`motive` en Atorados, tarjetas + mapa de calor en Encargados y proyecciones
(`_projection`) por motivo, por encargado y por carrera, siempre con el ritmo
de los últimos 10 días hábiles (independiente del rango).

`px` y `ox` se normalizan como `cohort`: una carrera inexistente o fuera del
alcance, «Sin carrera» sin `can_see_unmapped` y un encargado inexistente se
descartan y no viajan en ninguna liga; nunca se carga el nombre de una carrera
fuera del alcance del usuario.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services import report_flow as flow
from itcj2.apps.titulatec.services import report_officers as roff
from itcj2.apps.titulatec.services.non_working_day_service import NonWorkingDayService
from itcj2.apps.titulatec.services.report_snapshot import (
    ACTORS,
    MOTIVE_ACTOR,
    MOTIVE_CLOSE_APPT,
    MOTIVE_CODES,
    MOTIVE_LABEL,
    STAGE_GROUPS,
    STAGES,
    Item,
    ReportConfig,
    Snapshot,
    first_motives,
    item_motives,
    load_snapshot,
)
from itcj2.apps.titulatec.utils import charts
from itcj2.apps.titulatec.utils.business_days import (
    add_business_days,
    is_business_day,
    last_business_days,
)
from itcj2.apps.titulatec.utils.paging import paginate_list, parse_page

# ---------------------------------------------------------------------------
# Catálogos de la vista
# ---------------------------------------------------------------------------
BASE_URL = "/titulatec/admin/tablero"
BODY_URL = f"{BASE_URL}/body"
APPOINTMENTS_URL = "/titulatec/admin/appointments"
LIBERADOS_URL = "/titulatec/admin/liberados"          # bandeja Liberados (`handoff_admin.py`)

TABS: tuple[tuple[str, str], ...] = (
    ("panorama", "Panorama"),
    ("ritmo", "Ritmo"),
    ("encargados", "Encargados"),
    ("carreras", "Carreras"),
    ("atorados", "Atorados"),
)
TAB_CODES = tuple(code for code, _ in TABS)
_TAB_LABELS = dict(TABS)
DEFAULT_TAB = "panorama"

RANGE_CHOICES = (7, 14, 30)
DEFAULT_RANGE = 14
COHORT_ALL = "all"

# Atorados: `warn` = Lento o más (≥ WARN días), `crit` = Atorado (≥ CRIT), `all`.
LEVELS: tuple[tuple[str, str], ...] = (
    ("warn", "Lentos y atorados"),
    ("crit", "Solo atorados"),
    ("all", "Todos"),
)
LEVEL_CODES = tuple(code for code, _ in LEVELS)
DEFAULT_LEVEL = "warn"
# Nivel de un pendiente -> (texto, icono). Siempre icono + texto (spec §7).
LEVEL_UI = {
    "crit": ("Atorado", "bi-exclamation-octagon-fill"),
    "warn": ("Lento", "bi-hourglass-split"),
    "ok": ("Al día", "bi-check-circle"),
}

# `px=0` oculta el cubo «Sin carrera» (program_id NULL).
UNMAPPED_ID = 0
UNMAPPED_LABEL = "Sin carrera"

_STAGE_CODES = tuple(code for code, _, _ in STAGES)
_STAGE_LABEL = {code: label for code, label, _ in STAGES}
_STAGE_GROUP = {code: group for code, _, group in STAGES}
_GROUP_LABEL = {code: label for code, label, _ in STAGE_GROUPS}
_GROUP_COLOR = {code: color for code, _, color in STAGE_GROUPS}
_ACTOR_CODES = tuple(code for code, _, _ in ACTORS)
_ACTOR_LABEL = {code: label for code, label, _ in ACTORS}
_ACTOR_COLOR = {code: color for code, _, color in ACTORS}
_REQUEST_REVIEW_STAGES = ("req_review", "req_unverified")
_LIBERADO = "liberado"

# Calendario: 0 = `--tt-line-soft`; 1-5 la rampa ordinal de 5 pasos (spec §7).
CALENDAR_ZERO_COLOR = "var(--tt-line-soft)"
CALENDAR_RAMP = tuple(color for _, _, color in STAGE_GROUPS)

# Geometría (unidades del viewBox; la plantilla solo las pinta).
LINE_W, LINE_H, LINE_PAD = 600, 180, 8
SPARK_W, SPARK_H = 120, 28
PACE_WINDOW = 10                         # días hábiles del ritmo (spec §4.5)
CAPACITY_DAYS = 5                        # días hábiles de lugares (spec §4.6)
_FLOW_FLOOR = date(2000, 1, 1)           # «desde siempre» para las series acumuladas
_MAX_IDS = 200                           # tope de ids por csv (`px`/`ox`)
_MAX_DIGITS = 18                         # un id/página con más dígitos es basura (y
                                         # `int()` de > 4300 dígitos levanta)

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORECAST_NOTE = "a este ritmo, sin contar feriados ni nuevas solicitudes"
# Con días inhábiles registrados el pronóstico SÍ los descuenta (fase 5).
_FORECAST_NOTE_HOLIDAYS = ("a este ritmo, descontando los días inhábiles registrados y sin "
                           "nuevas solicitudes")

# --- Ronda 2 (spec §12) ---------------------------------------------------
_MOTIVE_SET = frozenset(MOTIVE_CODES)
# Frase obligatoria de toda proyección de la ronda 2 (R4).
_PROJECTION_NOTE = "a este ritmo, sin feriados ni nuevas entradas"
_PROJECTION_NOTE_HOLIDAYS = ("a este ritmo, descontando los días inhábiles registrados y sin "
                             "nuevas entradas")
_MOTIVE_NOTE = ("Cada pendiente cuenta una sola vez por área, en su primer motivo según el "
                "orden del proceso.")
# Motivo con un ritmo de salida claro (R4c) -> (serie de `report_flow.exit_counts`,
# unidad de la cola, verbo del ritmo). «Dictaminar documentos» mide DOCUMENTOS
# por dictaminar contra dictámenes por día; los demás, pendientes contra salidas.
# El alumno no lleva proyección: no es una cola de trabajo.
_MOTIVE_EXITS = {
    "review_request": ("requests_reviewed", "solicitudes", "revisiones"),
    "review_docs": ("docs_reviewed", "documentos", "dictámenes"),
    "release_survey": ("survey_reviewed", "encuestas", "dictámenes de encuesta"),
    "register_clearance": ("library_registered", "egresados", "registros"),
    "give_nip": ("access_granted", "solicitudes", "accesos"),
}


# Pasos de rampa por área (Ronda 0 de U2): con más llaves que pasos, el ciclo
# intercala la claridad. 4 es lo que cabe con L (OKLab) separada >= 0.06 y el
# paso más claro >= 2:1 contra la superficie (`charts.ramp_steps`).
TINT_STEPS = 4


def _tinted(keys, color: str) -> dict[str, str]:
    """`{llave: tono}` de la rampa de `color`, en el orden de `keys`. Estable:
    el color sigue a la llave aunque cambien los conteos (spec §7).

    - Hasta `TINT_STEPS` llaves: un paso por llave, del más oscuro al más claro
      (>= 2:1 contra la superficie; con Escolares el más oscuro es la base):
      las partes de la cola y de la producción de una tarjeta.
    - Con más (los 8-9 motivos de Escolares y del alumno): 4 pasos en ciclo
      intercalado (`charts.interleave_steps`), así dos motivos a menos de 4
      lugares en el catálogo nunca comparten tono y los vecinos quedan a uno o
      dos pasos (antes eran 9 tintes a 10 % de aclarado: indistinguibles).
      Repetir tono a 4 lugares es aceptable: la identidad del motivo la da su
      etiqueta en la lista, nunca el tono solo.
    Un área con una sola llave conserva su color tal cual."""
    keys = list(keys)
    n = len(keys)
    if n <= TINT_STEPS:
        tonos = charts.ramp_steps(color, n)
    else:
        tonos = charts.interleave_steps(charts.ramp_steps(color, TINT_STEPS), n)
    return dict(zip(keys, tonos))


# Color de cada motivo: tonos de la rampa de su área, en el orden del catálogo.
_MOTIVE_COLOR: dict[str, str] = {}
for _actor in _ACTOR_CODES:
    _MOTIVE_COLOR.update(_tinted((c for c in MOTIVE_CODES if MOTIVE_ACTOR[c] == _actor),
                                 _ACTOR_COLOR[_actor]))
del _actor
# Tarjetas de Encargados (R1): partes de las barras de cola y de producción,
# en tintes del color de Escolares (todo es trabajo de Escolares). «Listos sin
# cita» es informativo: no suma a la cola de Escolares (`total_escolares`).
_QUEUE_PARTS = (("req_review", "Solicitudes"), ("docs_pending", "Documentos"),
                ("appts_to_close", "Citas por cerrar"), ("ready_to_book", "Listos sin cita"))
_PROD_PARTS = (("req_reviewed", "Solicitudes revisadas"), ("docs_approved", "Documentos aprobados"),
               ("docs_rejected", "Documentos rechazados"))
_QUEUE_COLORS = _tinted((k for k, _ in _QUEUE_PARTS), _ACTOR_COLOR["escolares"])
_PROD_COLORS = _tinted((k for k, _ in _PROD_PARTS), _ACTOR_COLOR["escolares"])
# Mapa de calor (R3): columnas que caben en la tarjeta sin scroll propio.
HEATMAP_FIT_DAYS = 22


# ---------------------------------------------------------------------------
# Filtros de URL
# ---------------------------------------------------------------------------
def _raw(params, key: str) -> str:
    """Valor crudo de `params[key]` como texto recortado; nunca levanta. Si
    llega una lista (parámetro repetido), gana el último, como en Starlette."""
    try:
        value = params.get(key) if params is not None else None
    except Exception:  # noqa: BLE001 - un mapeo raro no tumba la página (spec §8)
        return ""
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else None
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # noqa: BLE001 - un `__str__` roto tampoco
        return ""


def _to_int(raw: str) -> int | None:
    """Entero no negativo de 1 a 18 dígitos ASCII; si no, `None`. `"²"` pasa
    `isdigit()` pero `int()` lo rechaza, y `int()` de más de 4300 dígitos levanta
    `ValueError` (límite de CPython): ambos son basura, nunca un 500."""
    if not (raw.isascii() and raw.isdigit()) or len(raw) > _MAX_DIGITS:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_ids(raw: str, *, allow_zero: bool) -> frozenset[int]:
    """csv de enteros (`"1,,x"` -> {1}); basura, negativos y repetidos fuera."""
    minimo = 0 if allow_zero else 1
    out: set[int] = set()
    for part in raw.split(",")[:_MAX_IDS]:
        n = _to_int(part.strip())
        if n is not None and n >= minimo:
            out.add(n)
    return frozenset(out)


def _parse_cohort(raw: str):
    if raw.lower() == COHORT_ALL:
        return COHORT_ALL
    n = _to_int(raw)
    return n if n is not None and n >= 1 else None


def _parse_range(raw: str) -> int | None:
    if raw.lower() == "all":
        return None
    n = _to_int(raw)
    return n if n in RANGE_CHOICES else DEFAULT_RANGE


def _parse_day(raw: str) -> date | None:
    if not _ISO_DAY.match(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_page(raw: str) -> int:
    """`utils/paging.parse_page` con el mismo tope de dígitos que los ids."""
    return parse_page(raw) if raw and len(raw) <= _MAX_DIGITS else 1


def _csv(ids) -> str:
    return ",".join(str(i) for i in sorted(ids))


@dataclass(frozen=True)
class ReportFilters:
    """Estado de la vista (spec §3). `cohort`: id, `"all"` o `None` (= por
    omisión). `range_days`: 7/14/30 o `None` (= toda la convocatoria).
    `hidden_programs`: carreras ocultas (`0` = «Sin carrera»).
    `hidden_officers`: encargados ocultos (solo pestaña Encargados). `ball`,
    `motive`, `level`, `stage`, `page`: Atorados. `day`: día del calendario de
    Ritmo.

    `motive` (Ronda 2, R2) es un código de `report_snapshot.MOTIVES`; se
    normaliza SIEMPRE (también construido a mano o con `replace`): un código
    desconocido, o de otra área que la `ball` vigente, cae a `None`. Así
    cambiar de pelota suelta solo un motivo que ya no le corresponde."""
    tab: str = DEFAULT_TAB
    cohort: int | str | None = None
    range_days: int | None = DEFAULT_RANGE
    hidden_programs: frozenset[int] = frozenset()
    hidden_officers: frozenset[int] = frozenset()
    ball: str | None = None
    motive: str | None = None
    idle_level: str = DEFAULT_LEVEL
    stage: str | None = None
    page: int = 1
    day: date | None = None

    def __post_init__(self):
        object.__setattr__(self, "hidden_programs",
                           frozenset(int(p) for p in self.hidden_programs))
        object.__setattr__(self, "hidden_officers",
                           frozenset(int(u) for u in self.hidden_officers))
        m = self.motive
        if m is not None and (m not in _MOTIVE_SET
                              or (self.ball and MOTIVE_ACTOR[m] != self.ball)):
            object.__setattr__(self, "motive", None)

    @classmethod
    def parse(cls, params: Mapping[str, str] | None) -> ReportFilters:
        """De los parámetros de la URL (todos `str`; HTMX manda vacíos). Un
        valor inválido cae a su default; nunca levanta."""
        tab = _raw(params, "tab").lower()
        ball = _raw(params, "ball").lower()
        motive = _raw(params, "motive").lower()
        level = _raw(params, "level").lower()
        stage = _raw(params, "stage").lower()
        return cls(
            tab=tab if tab in TAB_CODES else DEFAULT_TAB,
            cohort=_parse_cohort(_raw(params, "cohort")),
            range_days=_parse_range(_raw(params, "range")),
            hidden_programs=_parse_ids(_raw(params, "px"), allow_zero=True),
            hidden_officers=_parse_ids(_raw(params, "ox"), allow_zero=False),
            ball=ball if ball in _ACTOR_CODES else None,
            motive=motive if motive in _MOTIVE_SET else None,
            idle_level=level if level in LEVEL_CODES else DEFAULT_LEVEL,
            stage=stage if stage in _STAGE_CODES else None,
            page=_parse_page(_raw(params, "page")),
            day=_parse_day(_raw(params, "day")),
        )

    def query(self, **changes) -> str:
        """Querystring estable: `tab` siempre (identifica la vista y empata con
        la barra de pestañas), luego cohort, range, px, ox, ball, motive,
        level, stage, page y day, cada uno SOLO si no vale su default."""
        f = replace(self, **changes) if changes else self
        pairs: list[tuple[str, str]] = [("tab", f.tab)]
        if f.cohort is not None:
            pairs.append(("cohort", str(f.cohort)))
        if f.range_days != DEFAULT_RANGE:
            pairs.append(("range", "all" if f.range_days is None else str(f.range_days)))
        if f.hidden_programs:
            pairs.append(("px", _csv(f.hidden_programs)))
        if f.hidden_officers:
            pairs.append(("ox", _csv(f.hidden_officers)))
        if f.ball:
            pairs.append(("ball", f.ball))
        if f.motive:
            pairs.append(("motive", f.motive))
        if f.idle_level != DEFAULT_LEVEL:
            pairs.append(("level", f.idle_level))
        if f.stage:
            pairs.append(("stage", f.stage))
        if f.page != 1:
            pairs.append(("page", str(f.page)))
        if f.day is not None:
            pairs.append(("day", f.day.isoformat()))
        return urlencode(pairs, safe=",")

    def page_url(self, **changes) -> str:
        """URL de la PÁGINA (`hx-push-url`, `href`)."""
        return f"{BASE_URL}?{self.query(**changes)}"

    def body_url(self, **changes) -> str:
        """URL del parcial `#tt-report-body` (`hx-get`)."""
        return f"{BODY_URL}?{self.query(**changes)}"

    def toggle_program(self, pid: int) -> ReportFilters:
        """Oculta/muestra una carrera (`0` = «Sin carrera»). Involutivo."""
        return replace(self, hidden_programs=self.hidden_programs ^ {int(pid)})

    def toggle_officer(self, uid: int) -> ReportFilters:
        """Oculta/muestra un encargado. Involutivo."""
        return replace(self, hidden_officers=self.hidden_officers ^ {int(uid)})


# ---------------------------------------------------------------------------
# Formato (texto UI en español)
# ---------------------------------------------------------------------------
def _fmt_day(d: date) -> str:
    """«9 oct»."""
    return f"{d.day} {_MESES[d.month - 1]}"


def _fmt_day_long(d: date, today: date) -> str:
    """«jue 9 oct» (con el año si no es el de hoy)."""
    base = f"{_DIAS[d.weekday()]} {d.day} {_MESES[d.month - 1]}"
    return base if d.year == today.year else f"{base} {d.year}"


def _fmt_dec(x: float) -> str:
    """Un decimal, sin «.0» de sobra: 10.0 -> «10», 6.25 -> «6.2»."""
    redondo = round(x, 1)
    return str(int(redondo)) if float(redondo).is_integer() else f"{redondo:.1f}"


def _fmt_pct(pct: float | None) -> str:
    return "—" if pct is None else f"{_fmt_dec(pct)}%"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _name_key(name: str) -> str:
    """Orden alfabético sin mayúsculas ni acentos."""
    sin = "".join(c for c in unicodedata.normalize("NFKD", name or "")
                  if not unicodedata.combining(c))
    return sin.casefold()


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)] if start <= end else []


# ---------------------------------------------------------------------------
# Carga común
# ---------------------------------------------------------------------------
def _load_cohorts(db: Session) -> list:
    """Convocatorias (id, name, status, opens_at), la más nueva primero."""
    from itcj2.apps.titulatec.models import Cohort

    return (db.query(Cohort.id, Cohort.name, Cohort.status, Cohort.opens_at)
            .order_by(Cohort.id.desc()).all())


def _pick_cohort(cohorts: list, requested) -> tuple[list[int] | None, object | None]:
    """`(cohort_ids, fila elegida)`. `"all"` -> `(None, None)`; un id que
    existe -> esa; si no, la `open` más reciente o, sin abiertas, la más
    reciente. Sin convocatorias -> `([], None)`."""
    if not cohorts:
        return [], None
    if requested == COHORT_ALL:
        return None, None
    if isinstance(requested, int):
        for c in cohorts:
            if c.id == requested:
                return [c.id], c
    elegida = next((c for c in cohorts if c.status == "open"), cohorts[0])
    return [elegida.id], elegida


@dataclass
class _Data:
    """Lo que cargan TODAS las pestañas (una vez por petición)."""
    filters: ReportFilters
    today: date
    cfg: ReportConfig
    cohorts: list
    cohort_ids: list[int] | None
    selected: object | None
    cohort_start: date
    range_start: date
    scope: object
    can_unmapped: bool
    include_unmapped: bool
    programs: object                     # alcance VISIBLE: "ALL" | set[int]
    hidden_in_scope: frozenset[int]
    snapshot: Snapshot
    program_names: dict[int, str]
    officers_cache: list | None = None   # `report_officers.officers`, una vez por petición
    holidays: frozenset = frozenset()    # calendario de días inhábiles, UNA lectura por petición

    @property
    def forecast_note(self) -> str:
        return _FORECAST_NOTE_HOLIDAYS if self.holidays else _FORECAST_NOTE

    @property
    def projection_note(self) -> str:
        return _PROJECTION_NOTE_HOLIDAYS if self.holidays else _PROJECTION_NOTE

    def officer_list(self, db: Session) -> list[roff.Officer]:
        """Encargados de Servicios Escolares (4 consultas), cargados a lo más
        una vez por petición: `_load` ya los trae si hay `ox` que validar."""
        if self.officers_cache is None:
            self.officers_cache = roff.officers(db)
        return self.officers_cache

    def in_scope(self, pid: int | None) -> bool:
        """¿La carrera está en el alcance del usuario? (`None` nunca)."""
        return pid is not None and (self.scope == "ALL" or pid in self.scope)

    @property
    def items(self) -> list[Item]:
        return self.snapshot.items

    @property
    def pending(self) -> list[Item]:
        return [it for it in self.snapshot.items if it.stage != _LIBERADO]

    @property
    def nothing_visible(self) -> bool:
        return (self.cohort_ids == []
                or (self.programs != "ALL" and not self.programs and not self.include_unmapped))

    def pname(self, pid: int | None) -> str:
        if pid is None:
            return UNMAPPED_LABEL
        return self.program_names.get(pid, f"Carrera {pid}")


def _load(db: Session, user_id: int, filters: ReportFilters, today: date) -> _Data:
    from itcj2.apps.titulatec.services.scope_service import (
        can_see_unmapped,
        officer_programs,
    )
    from itcj2.core.models.program import Program

    cfg = ReportConfig.from_settings()
    cohorts = _load_cohorts(db)
    cohort_ids, selected = _pick_cohort(cohorts, filters.cohort)
    if isinstance(filters.cohort, int) and selected is not None and selected.id != filters.cohort:
        filters = replace(filters, cohort=None)        # id inexistente: no viaja en las ligas

    abiertas = [c.opens_at.date() for c in cohorts
                if c.opens_at is not None and (cohort_ids is None or c.id in cohort_ids)]
    cohort_start = min(min(abiertas, default=today), today)
    range_start = (today - timedelta(days=filters.range_days - 1)
                   if filters.range_days else cohort_start)

    scope = officer_programs(db, user_id)
    can_unmapped = bool(can_see_unmapped(db, user_id))

    # `px`: solo carreras que existen y están en el alcance; nombres solo de esas.
    hidden_real = {p for p in filters.hidden_programs if p != UNMAPPED_ID}
    names: dict[int, str] = {}
    if scope == "ALL":
        if hidden_real:
            names = dict(db.query(Program.id, Program.name).all())
            hidden_in_scope = frozenset(hidden_real & set(names))
            programs: object = set(names) - hidden_in_scope
        else:
            hidden_in_scope, programs = frozenset(), "ALL"
    else:
        candidatas = sorted(hidden_real & set(scope))
        if candidatas:
            names = dict(db.query(Program.id, Program.name)
                         .filter(Program.id.in_(candidatas)).all())
        hidden_in_scope = frozenset(set(candidatas) & set(names))
        programs = set(scope) - hidden_in_scope
    hide_unmapped = can_unmapped and UNMAPPED_ID in filters.hidden_programs
    include_unmapped = can_unmapped and not hide_unmapped

    # `ox`: solo encargados que existen (la lista se reusa en la pestaña).
    officers_cache = None
    hidden_officers = filters.hidden_officers
    if hidden_officers:
        officers_cache = roff.officers(db)
        hidden_officers = hidden_officers & {o.user_id for o in officers_cache}
    # Lo que no se pudo validar no viaja en ninguna liga (como `cohort`).
    filters = replace(filters,
                      hidden_programs=hidden_in_scope | ({UNMAPPED_ID} if hide_unmapped else set()),
                      hidden_officers=hidden_officers)

    snapshot = load_snapshot(db, cohort_ids=cohort_ids, programs=programs,
                             include_unmapped=include_unmapped, today=today, cfg=cfg)
    return _Data(filters=filters, today=today, cfg=cfg, cohorts=cohorts,
                 cohort_ids=cohort_ids, selected=selected, cohort_start=cohort_start,
                 range_start=range_start, scope=scope, can_unmapped=can_unmapped,
                 include_unmapped=include_unmapped, programs=programs,
                 hidden_in_scope=hidden_in_scope, snapshot=snapshot,
                 program_names={**names, **snapshot.program_names},
                 officers_cache=officers_cache,
                 holidays=NonWorkingDayService.holidays(db))


def _flow_counts(db: Session, d: _Data, start: date) -> dict[str, dict[date, int]]:
    """`report_flow.daily_counts` con el alcance visible (3 consultas); vacío
    sin nada visible (sin consultar)."""
    if d.nothing_visible:
        return {"requests_new": {}, "requests_reviewed": {}, "enrolled": {}}
    return flow.daily_counts(db, cohort_ids=d.cohort_ids, programs=d.programs,
                             include_unmapped=d.include_unmapped, start=start, end=d.today)


def _atorados_links(d: _Data, **changes) -> tuple[str, str]:
    """(url de página, url de parcial) de la pestaña Atorados con `changes`."""
    base = {"tab": "atorados", "ball": None, "motive": None, "stage": None,
            "idle_level": DEFAULT_LEVEL, "page": 1, "day": None}
    base.update(changes)
    return d.filters.page_url(**base), d.filters.body_url(**base)


def _range_text(d: _Data) -> str:
    if d.filters.range_days:
        return f"Últimos {d.filters.range_days} días"
    return f"Toda la convocatoria (desde el {_fmt_day(d.range_start)})"


def _liberados_url(d: _Data, pid: int | None) -> str | None:
    """Bandeja Liberados filtrada por carrera (y por la convocatoria, si hay
    UNA elegida). Nombres de parámetro de `pages/handoff_admin.py`. `None`
    para «Sin carrera»: esa bandeja no tiene un filtro de «sin carrera»."""
    if pid is None:
        return None
    pairs = []
    if d.cohort_ids is not None and len(d.cohort_ids) == 1:
        pairs.append(("cohort_id", str(d.cohort_ids[0])))
    pairs.append(("program_id", str(pid)))
    return f"{LIBERADOS_URL}?{urlencode(pairs)}"


# ---------------------------------------------------------------------------
# Contexto común
# ---------------------------------------------------------------------------
def _program_chips(d: _Data) -> list[dict]:
    f = d.filters
    conteo: dict[int | None, int] = {}
    for it in d.items:
        conteo[it.program_id] = conteo.get(it.program_id, 0) + 1
    ids = set(d.snapshot.program_names) | set(d.hidden_in_scope)
    chips = [{"id": pid, "name": d.pname(pid), "hidden": pid in f.hidden_programs,
              "n": None if pid in f.hidden_programs else conteo.get(pid, 0)}
             for pid in ids]
    chips.sort(key=lambda c: (_name_key(c["name"]), c["id"]))
    if d.can_unmapped and (None in conteo or UNMAPPED_ID in f.hidden_programs):
        oculto = UNMAPPED_ID in f.hidden_programs
        chips.append({"id": UNMAPPED_ID, "name": UNMAPPED_LABEL, "hidden": oculto,
                      "n": None if oculto else conteo.get(None, 0)})
    for c in chips:
        nuevo = f.toggle_program(c["id"])
        c["toggle_url"] = nuevo.page_url(page=1)
        c["body_toggle_url"] = nuevo.body_url(page=1)
    return chips


def _print_summary(d: _Data, chips: list[dict]) -> str:
    f = d.filters
    partes = [f"Pestaña: {_TAB_LABELS[f.tab]}"]
    if d.cohort_ids is None:
        partes.append("Convocatoria: todas")
    elif d.selected is not None:
        partes.append(f"Convocatoria: {d.selected.name}")
    partes.append(f"Rango: {_range_text(d)}")
    ocultas = [c["name"] for c in chips if c["hidden"]]
    if ocultas:
        partes.append(f"Carreras ocultas: {', '.join(ocultas)}")
    if f.tab == "encargados" and f.hidden_officers:
        partes.append(_plural(len(f.hidden_officers), "encargado oculto", "encargados ocultos"))
    if f.tab == "atorados":
        partes.append(f"Nivel: {dict(LEVELS)[f.idle_level]}")
        if f.ball:
            partes.append(f"Pelota: {_ACTOR_LABEL[f.ball]}")
        if f.motive:
            partes.append(f"Motivo: {MOTIVE_LABEL[f.motive]}")
        if f.stage:
            partes.append(f"Etapa: {_STAGE_LABEL[f.stage]}")
    if f.tab == "ritmo" and f.day is not None:
        partes.append(f"Día: {_fmt_day_long(f.day, d.today)}")
    return " · ".join(partes)


def _common_ctx(d: _Data) -> dict:
    """Llaves comunes a toda pestaña:

    - `filters`: el `ReportFilters` vigente (normalizado: un `cohort` que no
      existe vuelve a `None`); `tab`: su código (atajo para la plantilla).
    - `tabs`: `[{code, label, url, body_url, active}]` — `url`/`body_url` con
      TODOS los filtros vigentes (página 1, sin día).
    - `cohorts`: `[{id, name, status, selected, url, body_url}]`, la más nueva
      primero, más una última entrada `{id: "all", name: "Todas las
      convocatorias", status: None, ...}`; `[]` sin convocatorias.
      `selected_cohort`: `{id, name}` de la elegida, o `None` con «todas».
      `no_cohorts`: `True` si no existe ninguna (spec §8, «Aún no hay
      convocatorias»).
    - `program_chips`: `[{id, name, hidden, n, toggle_url, body_toggle_url}]`
      por nombre; `id = 0` es «Sin carrera» (al final). `n` = items visibles de
      esa carrera (`None` si está oculta). `hidden_programs_count`.
      `all_hidden`: todos los chips ocultos (spec §8: aviso + `show_all_url`/
      `show_all_body_url`, «Mostrar todas»).
    - `range_options`: `[{code ("7"|"14"|"30"|"all"), label, active, url,
      body_url}]`; `range_text` («Últimos 14 días»); `range_start` (date).
    - `today` (date); `print_summary` (texto de filtros activos para la
      cabecera de impresión); `idle`: `{warn, crit}` (días, D8).
    """
    f = d.filters
    chips = _program_chips(d)
    sin_filtros = replace(f, hidden_programs=frozenset())
    tabs = [{"code": code, "label": label, "active": code == f.tab,
             "url": f.page_url(tab=code, page=1, day=None),
             "body_url": f.body_url(tab=code, page=1, day=None)} for code, label in TABS]
    cohorts = []
    if d.cohorts:
        for c in d.cohorts:
            cohorts.append({"id": c.id, "name": c.name, "status": c.status,
                            "selected": d.selected is not None and c.id == d.selected.id,
                            "url": f.page_url(cohort=c.id, page=1, day=None),
                            "body_url": f.body_url(cohort=c.id, page=1, day=None)})
        cohorts.append({"id": COHORT_ALL, "name": "Todas las convocatorias", "status": None,
                        "selected": d.cohort_ids is None,
                        "url": f.page_url(cohort=COHORT_ALL, page=1, day=None),
                        "body_url": f.body_url(cohort=COHORT_ALL, page=1, day=None)})
    rangos = [{"code": str(n), "label": f"{n} días", "active": f.range_days == n,
               "url": f.page_url(range_days=n, page=1),
               "body_url": f.body_url(range_days=n, page=1)} for n in RANGE_CHOICES]
    rangos.append({"code": "all", "label": "Toda la convocatoria",
                   "active": f.range_days is None,
                   "url": f.page_url(range_days=None, page=1),
                   "body_url": f.body_url(range_days=None, page=1)})
    return {
        "filters": f,
        "tab": f.tab,
        "tabs": tabs,
        "cohorts": cohorts,
        "selected_cohort": ({"id": d.selected.id, "name": d.selected.name}
                            if d.selected is not None else None),
        "no_cohorts": not d.cohorts,
        "program_chips": chips,
        "hidden_programs_count": sum(1 for c in chips if c["hidden"]),
        "all_hidden": bool(chips) and all(c["hidden"] for c in chips),
        "show_all_url": sin_filtros.page_url(page=1),
        "show_all_body_url": sin_filtros.body_url(page=1),
        "range_options": rangos,
        "range_text": _range_text(d),
        "range_start": d.range_start,
        "today": d.today,
        "print_summary": _print_summary(d, chips),
        "idle": {"warn": d.cfg.warn_days, "crit": d.cfg.crit_days},
    }


# ---------------------------------------------------------------------------
# Piezas compartidas por pestañas
# ---------------------------------------------------------------------------
def _pace_ctx(d: _Data, liberated: dict[date, int]) -> dict:
    pendientes = len(d.pending)
    por_dia = flow.pace(liberated, d.today, PACE_WINDOW, holidays=d.holidays)
    cuando = flow.forecast(pendientes, por_dia, d.today, holidays=d.holidays)
    if cuando is None:
        texto = "sin ritmo medible"
    elif pendientes == 0:
        texto = "sin pendientes"
    else:
        texto = _fmt_day_long(cuando, d.today)
    return {"per_day": por_dia, "text": _fmt_dec(por_dia), "window": PACE_WINDOW,
            "pending": pendientes, "forecast": cuando, "forecast_text": texto,
            "note": d.forecast_note}


def _projection(queue: int, per_day: float, today: date, *, unit: str, verb: str,
                threshold: int | None = None,
                holidays: frozenset[date] = frozenset()) -> dict:
    """Proyección de una cola a un ritmo (Ronda 2, R4). Pura; nunca divide
    entre cero (`report_flow.clear_days`).

    `{queue, unit, per_day, per_day_text, verb, rate_text («0.5 dictámenes por
    día hábil»), days (int|None), date (date|None), date_text («jue 23 oct»|
    None), status, over_threshold, text}` con `status`:

    - `clear`: cola en cero -> `days` 0, `date` hoy, `text` «Al día»;
    - `no_pace`: cola con ritmo 0 -> `days`/`date` `None`, «Sin ritmo medible»;
    - `ok`: «Se vacía el jue 23 oct (7 días hábiles)»;
    - `over`: como `ok` pero `days` > `threshold` (solo si se pasa umbral).

    La frase «a este ritmo, sin feriados ni nuevas entradas» va aparte
    (`projection_note` de cada pestaña): es la misma para todas.
    """
    dias = flow.clear_days(queue, per_day)
    per_day = float(per_day)
    texto_ritmo = _fmt_dec(per_day)
    base = {"queue": max(0, int(queue)), "unit": unit, "per_day": per_day,
            "per_day_text": texto_ritmo, "verb": verb,
            "rate_text": f"{texto_ritmo} {verb} por día hábil"}
    if queue <= 0:
        return {**base, "days": 0, "date": today, "date_text": _fmt_day_long(today, today),
                "status": "clear", "over_threshold": False, "text": "Al día"}
    if dias is None:
        return {**base, "days": None, "date": None, "date_text": None, "status": "no_pace",
                "over_threshold": False, "text": "Sin ritmo medible"}
    cuando = add_business_days(today, dias, holidays=holidays)
    sobre = threshold is not None and dias > threshold
    texto_fecha = _fmt_day_long(cuando, today)
    return {**base, "days": dias, "date": cuando, "date_text": texto_fecha,
            "status": "over" if sobre else "ok", "over_threshold": sobre,
            "text": f"Se vacía el {texto_fecha} ({_plural(dias, 'día hábil', 'días hábiles')})"}


def _pace_days(d: _Data) -> list[date]:
    """Los 10 días hábiles del ritmo (spec §4.5; independientes del rango)."""
    return last_business_days(d.today, PACE_WINDOW, holidays=d.holidays)


def _exit_counts(db: Session, d: _Data) -> dict[str, dict[date, int]]:
    """`report_flow.exit_counts` de los 10 días hábiles del ritmo con el
    alcance visible (2 consultas); vacío sin nada visible (sin consultar)."""
    if d.nothing_visible:
        return {k: {} for k in flow.EXIT_KEYS}
    return flow.exit_counts(db, cohort_ids=d.cohort_ids, programs=d.programs,
                            include_unmapped=d.include_unmapped, start=_pace_days(d)[0],
                            end=d.today)


def _bin_legend(vmax: int) -> list[dict]:
    """Leyenda de una escala secuencial de 5 cubetas (`charts.bin_index`) + el
    0: `[{bin, label ("0" | "3" | "4–6"), color}]`; solo las cubetas con algún
    entero posible."""
    legend = [{"bin": 0, "label": "0", "color": CALENDAR_ZERO_COLOR}]
    for i in range(1, len(CALENDAR_RAMP) + 1):
        lo = math.floor((i - 1) * vmax / len(CALENDAR_RAMP)) + 1
        hi = math.floor(i * vmax / len(CALENDAR_RAMP))
        if lo <= hi:
            legend.append({"bin": i, "label": str(lo) if lo == hi else f"{lo}–{hi}",
                           "color": CALENDAR_RAMP[i - 1]})
    return legend


def _officer_names_by_program(d: _Data, officers: list[roff.Officer]) -> dict[int, list[str]]:
    """`{program_id: [nombres de encargados]}` solo de carreras del alcance."""
    out: dict[int, list[str]] = {}
    for o in officers:                                   # ya vienen por nombre
        for pid in o.program_ids:
            if d.in_scope(pid):
                out.setdefault(pid, []).append(o.name)
    return out


def _line_chart(dates: list[date], series: list[tuple[str, str, list[int]]]) -> dict:
    """Gráfica de líneas de UN eje (spec §7): ticks bonitos, polilíneas y una
    columna por día para crosshair/tooltip.

    `{width, height, pad, vmax, ticks: [{value, y, y_pct}], series: [{key,
    label, values, points, sum, last}], days: [{date, iso, label, x, x_pct,
    values: [{key, label, value, y}], tip}], x_labels: [{label, x, x_pct,
    anchor}]}`. Sin días -> listas vacías y ticks `[0, 1]`.
    """
    tope_datos = max((max(vals) for _, _, vals in series if vals), default=0)
    ticks = charts.nice_ticks(tope_datos)
    tope = ticks[-1]
    alto = LINE_H - 2 * LINE_PAD
    base = LINE_H - LINE_PAD

    def y_de(v: float) -> float:
        return float(base - alto * (v / tope if tope else 0))

    salida_series, puntos = [], []
    for key, label, vals in series:
        pts = charts.line_points(vals, width=LINE_W, height=LINE_H, vmax=tope, pad=LINE_PAD)
        puntos.append(pts)
        salida_series.append({"key": key, "label": label, "values": list(vals),
                              "points": charts.points_attr(pts), "sum": sum(vals),
                              "last": vals[-1] if vals else 0})
    dias = []
    for i, dia in enumerate(dates):
        x = puntos[0][i][0] if puntos and puntos[0] else 0.0
        valores = [{"key": key, "label": label, "value": vals[i], "y": puntos[j][i][1]}
                   for j, (key, label, vals) in enumerate(series)]
        tip = f"{_fmt_day(dia)} · " + " · ".join(f"{v['label']} {v['value']}" for v in valores)
        dias.append({"date": dia, "iso": dia.isoformat(), "label": _fmt_day(dia), "x": x,
                     "x_pct": x / LINE_W * 100, "values": valores, "tip": tip})
    etiquetas = []
    if dias:
        paso = max(1, math.ceil(len(dias) / 6))
        idx = list(range(0, len(dias), paso))
        if idx[-1] != len(dias) - 1:
            if len(dias) - 1 - idx[-1] < paso / 2 and len(idx) > 1:
                idx.pop()
            idx.append(len(dias) - 1)
        for i in idx:
            anchor = "start" if i == 0 and len(dias) > 1 else (
                "end" if i == len(dias) - 1 and len(dias) > 1 else "middle")
            etiquetas.append({"label": dias[i]["label"], "x": dias[i]["x"],
                              "x_pct": dias[i]["x_pct"], "anchor": anchor})
    return {
        "width": LINE_W, "height": LINE_H, "pad": LINE_PAD, "vmax": tope,
        "ticks": [{"value": t, "y": y_de(t), "y_pct": y_de(t) / LINE_H * 100} for t in ticks],
        "series": salida_series, "days": dias, "x_labels": etiquetas,
    }


# ---------------------------------------------------------------------------
# Pestañas
# ---------------------------------------------------------------------------
def _alerts(db: Session, d: _Data, liberated: dict[date, int]) -> list[dict]:
    """Reglas fijas de Panorama (spec §5.1), en este orden, máx. 5."""
    cfg, out = d.cfg, []
    icon = {"crit": "bi-exclamation-octagon-fill", "warn": "bi-exclamation-triangle-fill"}

    def alerta(code, level, text, url, body_url=None):
        out.append({"code": code, "level": level, "icon": icon[level], "text": text,
                    "url": url, "body_url": body_url})

    # 1. Solicitudes que esperan revisión >= CRIT días: UNA alerta, la anterior
    # (legado) sumada. La liga lleva `stage=req_review`, que en Atorados incluye
    # también `req_unverified` (`_matches`), así que cifra y lista cuadran.
    viejas = {stage: sum(1 for it in d.items
                         if it.stage == stage and it.idle_days >= cfg.crit_days)
              for stage in _REQUEST_REVIEW_STAGES}
    n = sum(viejas.values())
    if n:
        url, body = _atorados_links(d, stage="req_review", idle_level="crit")
        alerta("requests_crit", "crit",
               f"{_plural(n, 'solicitud por revisar lleva', 'solicitudes por revisar llevan')} "
               f"{cfg.crit_days} días o más esperando", url, body)
    # 2. Expedientes con documentos por dictaminar quietos >= WARN días.
    lentos = [it for it in d.items
              if it.stage == "docs" and it.pending_docs > 0 and it.idle_days >= cfg.warn_days]
    if lentos:
        docs = sum(it.pending_docs for it in lentos)
        url, body = _atorados_links(d, stage="docs", ball="escolares", idle_level="warn")
        alerta("docs_warn", "warn",
               f"{_plural(len(lentos), 'expediente', 'expedientes')} con documentos por "
               f"dictaminar ({_plural(docs, 'documento', 'documentos')}) sin movimiento en "
               f"{cfg.warn_days} días o más", url, body)
    # 3. Listos para agendar > lugares libres en los próximos días hábiles.
    listos = sum(1 for it in d.pending if it.ready_to_book)
    if listos:
        ocupados, capacidad = roff.capacity(db, today=d.today, days=CAPACITY_DAYS,
                                  holidays=d.holidays).get(0, (0, 0))
        libres = max(0, capacidad - ocupados)
        if listos > libres:
            alerta("capacity", "warn",
                   f"{_plural(listos, 'egresado listo', 'egresados listos')} para agendar y "
                   f"{_plural(libres, 'lugar libre', 'lugares libres')} en los próximos "
                   f"{CAPACITY_DAYS} días hábiles: el cuello es la capacidad de citas",
                   APPOINTMENTS_URL)
    # 4. Entradas > salidas en el rango.
    entradas = sum(_flow_counts(db, d, d.range_start)["requests_new"].values())
    salidas = sum(n for dia, n in liberated.items() if d.range_start <= dia <= d.today)
    if entradas > salidas:
        alerta("inflow", "warn",
               f"Entraron {_plural(entradas, 'solicitud', 'solicitudes')} y salieron "
               f"{_plural(salidas, 'liberado', 'liberados')} ({_range_text(d).lower()}): "
               f"la cola crece",
               d.filters.page_url(tab="ritmo", page=1, day=None),
               d.filters.body_url(tab="ritmo", page=1, day=None))
    # 5. Citas pasadas sin cerrar: por MOTIVO («Cerrar cita»), no por nivel, y
    # solo con fecha anterior a hoy (la `in_progress` de hoy es «En atención»).
    sin_cerrar = sum(1 for it in d.items
                     if it.appt_date is not None and it.appt_date < d.today
                     and any(MOTIVE_CLOSE_APPT in motivo.split(" · ") for _, motivo in it.balls))
    if sin_cerrar:
        url, body = _atorados_links(d, stage="cita", ball="escolares", idle_level="all")
        alerta("appts_unclosed", "warn",
               f"{_plural(sin_cerrar, 'cita pasada', 'citas pasadas')} sin cerrar", url, body)
    return out[:5]


def _ctx_panorama(db: Session, d: _Data) -> dict:
    """Pestaña Panorama (spec §5.1).

    - `kpis`:
        - `liberated`: `{total, in_range, spark, spark_values, spark_width,
          spark_height, url, body_url}` — `spark` es el atributo `points` de la
          sparkline diaria del rango; `url` lleva a Atorados con
          `stage=liberado&level=all`.
        - `pace`: `{per_day (float), text, window (10), pending, forecast (date|
          None), forecast_text ("jue 9 oct" | "sin ritmo medible" | "sin
          pendientes"), note}` — `note` es la frase obligatoria «a este ritmo,
          sin contar feriados ni nuevas solicitudes».
        - `requests`: `{pending, oldest_days (int|None), url, body_url}`
          (solicitudes por revisar, la anterior incluida).
        - `stuck`: `{crit, warn, total, url, body_url, crit_url,
          crit_body_url}` — `warn` = solo ámbar; `url` = Atorados ≥ WARN.
    - `stages`: 8 `{code, label, group, group_label, color, value, pct, url,
      body_url, tip}` en el orden de §4.2 (color = el de su grupo); `url` =
      Atorados con `stage` y `level=all` (la lista cuadra con la barra).
    - `balls`: 5 `{code, label, color, value, pct, stuck, crit, url, body_url,
      stuck_url, stuck_body_url, tip}` en el orden fijo de actores; `value` =
      procesos únicos con esa pelota; `url` = `ball` + `level=all`;
      `stuck_url` = `ball` con nivel ≥ WARN.
    - `pending_total` (pendientes vivos, etapa ≠ liberado), `with_ball`
      (pendientes con al menos una pelota), `multi_ball` (con dos o más:
      «N pendientes esperan a dos áreas»), `on_hold` («En pausa»).
    - `alerts`: ≤ 5 `{code, level ("crit"|"warn"), icon, text, url,
      body_url (None si la liga sale del tablero)}`; `[]` = «Sin alertas».
      `code` ∈ requests_crit · docs_warn · capacity · inflow · appts_unclosed,
      a lo más una de cada una (la de solicitudes suma la etapa anterior).

    Ronda 2 (spec §12, R2/R4c) — llaves NUEVAS:

    - `balls[*].motives`: la barra de cada área partida por motivo. SOLO los
      motivos con algún pendiente, en el orden del catálogo
      (`report_snapshot.MOTIVES`); cada pendiente cuenta UNA vez por área, en
      su PRIMER motivo, así que `sum(m.value) == ball.value` siempre. Cada uno
      `{code, label, value, share_pct (0-100 del área; suman 100),
      share_x_pct (inicio acumulado dentro del área), x_pct, w_pct (sobre el
      MISMO eje de las barras de área: suman `ball.pct`), color (tinte del
      color del área, estable por motivo: con contraste < 3:1 la etiqueta va
      fuera de la marca), url, body_url (Atorados con `ball` + `motive` +
      `level=all`: la lista cuadra con la cifra), tip («Dictaminar documentos:
      39 (52 documentos)»), docs (documentos por dictaminar, solo en
      `review_docs`; si no `None`), forecast}`.
    - `balls[*].motives[*].forecast`: `None` salvo en los 5 motivos con un
      ritmo de salida claro (R4c): `review_request` (revisiones/día),
      `review_docs` (dictámenes/día sobre DOCUMENTOS), `release_survey`
      (dictámenes de encuesta de GTV/día), `register_clearance` (registros de
      Biblioteca/día) y `give_nip` (accesos de Cómputo/día). Forma de
      `_projection`: `{queue, unit, per_day, per_day_text, verb, rate_text,
      days, date, date_text, status ("ok"|"no_pace"; "clear" no ocurre aquí),
      over_threshold (False), text («Se vacía el jue 23 oct (7 días
      hábiles)» | «Sin ritmo medible»)}`. El alumno nunca lleva proyección.
    - `motive_note` («Cada pendiente cuenta una sola vez por área, en su
      primer motivo…»), `projection_note` («a este ritmo, sin feriados ni
      nuevas entradas», obligatoria junto a cada proyección),
      `projection_window` (10 días hábiles).
    """
    pend = d.pending
    liberated = flow.liberated_by_day(d.items)
    rango = _days(d.range_start, d.today)
    spark_vals = [liberated.get(dia, 0) for dia in rango]

    por_etapa = {code: 0 for code in _STAGE_CODES}
    for it in d.items:
        por_etapa[it.stage] = por_etapa.get(it.stage, 0) + 1
    filas = charts.bar_rows([(code, por_etapa[code]) for code in _STAGE_CODES])
    stages = []
    for fila in filas:
        code = fila["label"]
        url, body = _atorados_links(d, stage=code, idle_level="all")
        stages.append({"code": code, "label": _STAGE_LABEL[code], "group": _STAGE_GROUP[code],
                       "group_label": _GROUP_LABEL[_STAGE_GROUP[code]],
                       "color": _GROUP_COLOR[_STAGE_GROUP[code]], "value": fila["value"],
                       "pct": fila["pct"], "url": url, "body_url": body,
                       "tip": f"{_STAGE_LABEL[code]}: {fila['value']}"})

    cuenta = {a: [0, 0, 0] for a in _ACTOR_CODES}           # [procesos, ≥warn, crit]
    por_motivo: dict[str, int] = {}                          # R2: primer motivo por área
    docs_por_motivo: dict[str, int] = {}
    for it in pend:
        for actor in {a for a, _ in it.balls}:
            acc = cuenta.setdefault(actor, [0, 0, 0])
            acc[0] += 1
            acc[1] += it.idle_level in ("warn", "crit")
            acc[2] += it.idle_level == "crit"
        for code in first_motives(it).values():
            por_motivo[code] = por_motivo.get(code, 0) + 1
            docs_por_motivo[code] = docs_por_motivo.get(code, 0) + int(it.pending_docs or 0)
    salidas = _exit_counts(db, d)
    filas_area = charts.bar_rows([(a, cuenta[a][0]) for a in _ACTOR_CODES])
    tope_areas = max((f["value"] for f in filas_area), default=0)
    balls = []
    for fila in filas_area:
        a = fila["label"]
        url, body = _atorados_links(d, ball=a, idle_level="all")
        s_url, s_body = _atorados_links(d, ball=a)
        balls.append({"code": a, "label": _ACTOR_LABEL[a], "color": _ACTOR_COLOR[a],
                      "value": fila["value"], "pct": fila["pct"], "stuck": cuenta[a][1],
                      "crit": cuenta[a][2], "url": url, "body_url": body,
                      "stuck_url": s_url, "stuck_body_url": s_body,
                      "tip": f"{_ACTOR_LABEL[a]}: {fila['value']} "
                             f"({_plural(cuenta[a][1], 'atorado o lento', 'atorados o lentos')})",
                      "motives": _area_motives(d, a, fila["value"], tope_areas, por_motivo,
                                               docs_por_motivo, salidas)})

    revisar = [it for it in d.items if it.stage in _REQUEST_REVIEW_STAGES]
    crit = sum(1 for it in pend if it.idle_level == "crit")
    warn = sum(1 for it in pend if it.idle_level == "warn")
    lib_url, lib_body = _atorados_links(d, stage=_LIBERADO, idle_level="all")
    req_url, req_body = _atorados_links(d, stage="req_review", idle_level="all")
    st_url, st_body = _atorados_links(d)
    cr_url, cr_body = _atorados_links(d, idle_level="crit")
    return {
        "kpis": {
            "liberated": {
                "total": sum(1 for it in d.items if it.stage == _LIBERADO),
                "in_range": sum(spark_vals),
                "spark": charts.sparkline(spark_vals, SPARK_W, SPARK_H),
                "spark_values": spark_vals, "spark_width": SPARK_W, "spark_height": SPARK_H,
                "url": lib_url, "body_url": lib_body,
            },
            "pace": _pace_ctx(d, liberated),
            "requests": {"pending": len(revisar),
                         "oldest_days": max((it.idle_days for it in revisar), default=None),
                         "url": req_url, "body_url": req_body},
            "stuck": {"crit": crit, "warn": warn, "total": crit + warn,
                      "url": st_url, "body_url": st_body,
                      "crit_url": cr_url, "crit_body_url": cr_body},
        },
        "stages": stages,
        "balls": balls,
        "pending_total": len(pend),
        "with_ball": sum(1 for it in pend if it.balls),
        "multi_ball": sum(1 for it in pend if len(it.balls) >= 2),
        "on_hold": d.snapshot.on_hold,
        "alerts": _alerts(db, d, liberated),
        "motive_note": _MOTIVE_NOTE,
        "projection_note": d.projection_note,
        "projection_window": PACE_WINDOW,
    }


def _area_motives(d: _Data, actor: str, area_value: int, scale: int,
                  por_motivo: dict[str, int], docs_por_motivo: dict[str, int],
                  salidas: dict[str, dict[date, int]]) -> list[dict]:
    """Motivos de un área de «¿Quién tiene la pelota?» (Ronda 2, R2/R4c): los
    que tienen algún pendiente, en el orden del catálogo, cada pendiente en su
    PRIMER motivo del área (suman `area_value`)."""
    codigos = [c for c in MOTIVE_CODES if MOTIVE_ACTOR[c] == actor and por_motivo.get(c)]
    segmentos = charts.scaled_segments([(c, por_motivo[c]) for c in codigos], scale)
    salida, acum = [], 0.0
    for seg in segmentos:
        code, n = seg["key"], seg["value"]
        share = n / area_value * 100 if area_value else 0.0
        url, body = _atorados_links(d, ball=actor, motive=code, idle_level="all")
        docs = docs_por_motivo.get(code, 0) if code == "review_docs" else None
        pronostico = None
        if code in _MOTIVE_EXITS:
            serie, unidad, verbo = _MOTIVE_EXITS[code]
            pronostico = _projection(docs if docs is not None else n,
                                     flow.pace(salidas[serie], d.today, PACE_WINDOW,
                                               holidays=d.holidays), d.today,
                                     unit=unidad, verb=verbo, holidays=d.holidays)
        tip = f"{MOTIVE_LABEL[code]}: {n}"
        if docs is not None:
            tip += f" ({_plural(docs, 'documento', 'documentos')})"
        salida.append({"code": code, "label": MOTIVE_LABEL[code], "value": n,
                       "share_pct": share, "share_x_pct": acum,
                       "x_pct": seg["x_pct"], "w_pct": seg["w_pct"],
                       "color": _MOTIVE_COLOR[code], "url": url, "body_url": body,
                       "tip": tip, "docs": docs, "forecast": pronostico})
        acum += share
    return salida


def _calendar(d: _Data, liberated: dict[date, int], start: date) -> dict:
    f = d.filters
    weeks = charts.calendar_weeks(liberated, start, d.today, d.today)
    vmax = max((liberated.get(dia, 0) for dia in _days(start, d.today)), default=0)
    for semana in weeks:
        for celda in semana:
            dia = celda["date"]
            celda["iso"] = dia.isoformat()
            celda["label"] = _fmt_day(dia)
            celda["color"] = CALENDAR_ZERO_COLOR if celda["bin"] == 0 else CALENDAR_RAMP[celda["bin"] - 1]
            celda["selected"] = f.day == dia
            celda["url"] = f.page_url(day=dia)
            celda["body_url"] = f.body_url(day=dia)
            celda["tip"] = f"{_fmt_day_long(dia, d.today)}: " + _plural(
                celda["n"], "liberado", "liberados")
    legend = _bin_legend(vmax)
    return {"weeks": weeks, "legend": legend, "weekdays": list(_DIAS[:5]), "start": start,
            "end": d.today, "max": vmax,
            "total": sum(n for dia, n in liberated.items() if start <= dia <= d.today)}


def _ctx_ritmo(db: Session, d: _Data) -> dict:
    """Pestaña Ritmo (spec §5.2).

    - `daily`: `_line_chart` del rango (días naturales) con las series
      `requests_new` («Solicitudes nuevas») y `liberated` («Liberados»), un
      solo eje. Llaves: `{width, height, pad, vmax, ticks: [{value, y, y_pct}],
      series: [{key, label, values, points, sum, last}], days: [{date, iso,
      label, x, x_pct, values: [{key, label, value, y}], tip}], x_labels:
      [{label, x, x_pct, anchor}]}`.
    - `cumulative`: mismo formato, series `enrolled` («Inscritos»: procesos
      creados NO revocados, pausados y terminados incluidos; misma definición
      que `carreras.rows[*].enrolled`) y `liberated` («Liberados»),
      desde el inicio de la convocatoria (o el primer dato, si es anterior).
    - `calendar`: `{weeks: [[{date, iso, label, n, bin (0-5), color, in_range,
      is_today, selected, url, body_url, tip}]], legend: [{bin, label, color}],
      weekdays: ["lun".."vie"], start, end, max, total}` (lun-vie × semanas;
      clic en un día = `?day=`).
    - `by_program`: liberados en el rango por carrera, mayor primero, solo los
      que tienen alguno: `[{id (None = «Sin carrera»), name, value, pct, tip,
      url}]`. `url` lleva a la bandeja **Liberados**
      (`/titulatec/admin/liberados?cohort_id=…&program_id=…`, mismos nombres
      de parámetro que `pages/handoff_admin.py`): `cohort_id` solo con UNA
      convocatoria elegida (con «todas», sin él). Esa bandeja no filtra por
      fecha, así que lista TODOS los liberados de la carrera, no solo los del
      rango. `None` para «Sin carrera» (la bandeja no filtra «sin carrera»).
    - `pace`: el mismo dict que `panorama.kpis.pace`.
    - `selected_day` (date|None), `selected_day_text`, `day_list`: liberados de
      ese día `[{id, label, control, program, officer ("—" sin dato), href}]`
      por carrera y nombre; `clear_day_url`/`clear_day_body_url` lo cierran.
    """
    from itcj2.core.models.user import User

    f = d.filters
    liberated = flow.liberated_by_day(d.items)
    counts = _flow_counts(db, d, _FLOW_FLOOR)
    rango = _days(d.range_start, d.today)
    nuevas = [counts["requests_new"].get(dia, 0) for dia in rango]
    salidas = [liberated.get(dia, 0) for dia in rango]
    daily = _line_chart(rango, [("requests_new", "Solicitudes nuevas", nuevas),
                                ("liberated", "Liberados", salidas)])

    primeros = [d.cohort_start] + [min(serie) for serie in (counts["enrolled"], liberated) if serie]
    inicio = min(min(primeros), d.today)
    span = _days(inicio, d.today)
    base_insc = sum(n for dia, n in counts["enrolled"].items() if dia < inicio)
    base_lib = sum(n for dia, n in liberated.items() if dia < inicio)
    insc = [n for _, n in flow.cumulative(flow.fill_days(counts["enrolled"], inicio, d.today),
                                          base_insc)]
    libs = [n for _, n in flow.cumulative(flow.fill_days(liberated, inicio, d.today), base_lib)]
    cumulative = _line_chart(span, [("enrolled", "Inscritos", insc), ("liberated", "Liberados", libs)])

    por_carrera: dict[int | None, int] = {}
    for it in d.items:
        if it.liberated_on is not None and d.range_start <= it.liberated_on <= d.today:
            por_carrera[it.program_id] = por_carrera.get(it.program_id, 0) + 1
    orden = sorted(por_carrera.items(), key=lambda kv: (-kv[1], kv[0] is None,
                                                        _name_key(d.pname(kv[0]))))
    by_program = []
    for (pid, n), fila in zip(orden, charts.bar_rows([(d.pname(p), n) for p, n in orden])):
        by_program.append({"id": pid, "name": fila["label"], "value": n, "pct": fila["pct"],
                           "tip": f"{fila['label']}: {_plural(n, 'liberado', 'liberados')}",
                           "url": _liberados_url(d, pid)})

    day_list = []
    if f.day is not None:
        del_dia = [it for it in d.items if it.liberated_on == f.day]
        ids = sorted({it.liberated_by_id for it in del_dia if it.liberated_by_id is not None})
        nombres = ({u.id: u.full_name for u in db.query(User).filter(User.id.in_(ids)).all()}
                   if ids else {})
        for it in sorted(del_dia, key=lambda x: (x.program_id is None, _name_key(d.pname(x.program_id)),
                                                 _name_key(x.label), x.id)):
            day_list.append({"id": it.id, "label": it.label, "control": it.control,
                             "program": d.pname(it.program_id),
                             "officer": nombres.get(it.liberated_by_id, "—"), "href": it.href})
    return {
        "daily": daily,
        "cumulative": cumulative,
        "calendar": _calendar(d, liberated, inicio),
        "by_program": by_program,
        "pace": _pace_ctx(d, liberated),
        "selected_day": f.day,
        "selected_day_text": _fmt_day_long(f.day, d.today) if f.day else None,
        "day_list": day_list,
        "clear_day_url": f.page_url(day=None),
        "clear_day_body_url": f.body_url(day=None),
    }


def _empty_prod() -> dict:
    return {"req_reviewed": 0, "docs_approved": 0, "docs_rejected": 0, "reject_rate": None,
            "attended": 0, "no_show": 0, "liberated": 0, "by_day": {}}


def _ctx_encargados(db: Session, d: _Data) -> dict:
    """Pestaña Encargados (spec §5.3, §4.7).

    - `officer_chips`: TODOS los encargados `[{user_id, name, hidden,
      color_index, toggle_url, body_toggle_url}]`; `color_index` = posición en
      la lista completa (no cambia al ocultar: el color sigue a la entidad).
      `hidden_officers_count`.
    - `rows`: un dict por encargado VISIBLE (orden por nombre): `{user_id,
      name, color_index, programs: [{id, name}] (SOLO las del alcance del
      usuario: nunca se cargan ni muestran nombres de otras carreras),
      programs_out_of_scope (int: cuántas suyas quedan fuera del alcance),
      no_programs (bool, «Sin carreras asignadas»: el encargado no tiene
      ninguna), queue: {req_review, docs_pending, appts_to_close,
      ready_to_book, total_escolares}, prod: {req_reviewed, docs_approved,
      docs_rejected, dictamenes, attended, no_show, liberated}, reject_rate
      (0-1|None), reject_text ("25%"|"—"), days_to_clear (float|None),
      days_to_clear_text ("—" sin producción), over_threshold (bool),
      places: {occupied, capacity, free}}`. La cola es la COMPLETA de sus
      carreras (traslape, D2) sobre los items visibles; producción en el rango,
      por actor; lugares de sus ventanas en los próximos 5 días hábiles.
      `days_to_clear` = `total_escolares` ÷ el ritmo de los ÚLTIMOS 10 días
      hábiles (`_officer_pace`, el MISMO de `cards[*].projection`; decisión
      del controlador, Ronda 0 de U1): independiente del rango, aunque la
      producción mostrada sí sea del rango. `None` sin producción en esos 10
      días; `over_threshold` coincide con `projection.over_threshold`.
    - `others`: producción de quienes NO son encargados (jefa, admin) en el
      rango, `{actors, req_reviewed, docs_approved, docs_rejected, dictamenes,
      attended, no_show, liberated, reject_rate, reject_text}`, o `None`.
    - `range_bdays` (días hábiles del rango), `capacity_total`: `{occupied,
      capacity, free}` (todas las ventanas, llave 0 de `capacity`).

    Ronda 2 (spec §12, R1/R3/R4a). La gráfica «Días para vaciar su cola»
    (`clear_bars`) y las sparklines (`sparks`) se RETIRARON con la Task U2: la
    proyección vive en cada tarjeta y el mapa de calor sustituye a las
    sparklines. Llaves de la ronda:

    - `cards`: una tarjeta por encargado VISIBLE, el más cargado primero
      (`_cards_sorted`: con cola y sin ritmo medible primero —cola mayor
      antes—, luego días hábiles para vaciar desc —desempate cola mayor—, al
      final los que están al día; nombre al último). Cada una `{user_id, name,
      color_index, programs, programs_out_of_scope, no_programs (como
      `rows`), queue: {req_review, docs_pending, appts_to_close,
      ready_to_book, total_escolares, total (las 4 partes: el largo de la
      barra)}, queue_segments, prod: {req_reviewed, docs_approved,
      docs_rejected, dictamenes, total (las 3 partes de la barra), attended,
      no_show, liberated} (del RANGO), prod_segments, reject_rate,
      reject_text, places: {occupied, capacity, free, pct (0-100 | None sin
      lugares abiertos), text («3 de 10»)} (próximos 5 días hábiles: el
      medidor), projection}`.
    - `*_segments`: `[{key, label, value, x_pct, w_pct, color, tip}]` sin las
      partes en 0, en el orden de `queue_legend`/`prod_legend`. `w_pct` es
      sobre la escala COMÚN `card_scale` (no sobre su propio total): las
      barras se comparan a lo largo entre tarjetas.
    - `card_scale`: `{queue, prod}` = el largo máximo de cada barra entre
      TODOS los encargados, ocultos incluidos (ocultar con `ox` no cambia la
      escala, como no cambia el color). 0 = sin barras.
    - `queue_legend` (Solicitudes · Documentos · Citas por cerrar · Listos sin
      cita) y `prod_legend` (Solicitudes revisadas · Documentos aprobados ·
      Documentos rechazados): `[{key, label, color}]` (un paso de la rampa de
      Escolares por parte, `_tinted`).
    - `cards[*].projection`: `_projection` de `total_escolares` al ritmo de
      dictámenes + revisiones por día hábil de los ÚLTIMOS 10 días hábiles
      (independiente del rango), con umbral: `status` ∈ clear · ok · over
      (`days` > `projection_threshold.days`: píldora de estado) · no_pace;
      `text` «Se vacía el jue 23 oct (7 días hábiles)» | «Sin ritmo medible» |
      «Al día». Mismo ritmo que `rows[*].days_to_clear` (`days` =
      ⌈days_to_clear⌉).
    - `projection_threshold`: `{days (CRIT en hábiles, 10), text}`;
      `projection_note`, `projection_window` (10).
    - `heatmap` (R3, sustituye a las sparklines): `{days: [{date, iso, label («lun
      13»), label_long («lun 13 oct»), week_start (lunes que no es la primera
      columna: separador), show_label (con `wide` solo la primera y los
      lunes), is_today}], rows: [{user_id (None en «Otros»), name, is_others,
      actors (personas sumadas en «Otros»; None en un encargado), total,
      cells: [{iso, n, bin (0-5), color (0 = `CALENDAR_ZERO_COLOR`; 1-5 la
      rampa), tip («Nombre · lun 13 oct: 4 dictámenes y revisiones»)}]}],
      legend: [{bin, label, color}], vmax, n_days, wide (más de
      `HEATMAP_FIT_DAYS` = 22 columnas: scroll horizontal propio de la
      tarjeta)}`. Columnas = días hábiles del rango; filas = encargados
      visibles por nombre (el orden de `rows`) y, AL FINAL, «Otros» (jefa,
      admin: los mismos de `others`, sumados por día; solo si `others`
      existe, y no se oculta con `ox`); `vmax`/cubetas salen de TODOS los
      encargados y de «Otros» (ocultar no recolorea a nadie).
    """
    from itcj2.core.models.program import Program

    f = d.filters
    todos = d.officer_list(db)
    color = {o.user_id: i for i, o in enumerate(todos)}
    visibles = [o for o in todos if o.user_id not in f.hidden_officers]
    # La cola de TODOS (pura): las escalas de tarjetas y del mapa de calor no
    # cambian al ocultar encargados (como el color, spec §4.7).
    colas = roff.queues(todos, d.items)
    # La serie diaria se alarga a los 10 días hábiles del ritmo (R4a); los
    # totales siguen siendo del rango.
    prod = (roff.production(db, start=d.range_start, end=d.today, cohort_ids=d.cohort_ids,
                            by_day_from=_pace_days(d)[0])
            if d.cohort_ids != [] else {})
    lugares = roff.capacity(db, today=d.today, days=CAPACITY_DAYS,
                                  holidays=d.holidays)
    habiles = [dia for dia in _days(d.range_start, d.today) if is_business_day(dia, holidays=d.holidays)]

    faltan = sorted({pid for o in visibles for pid in o.program_ids
                     if d.in_scope(pid)} - set(d.program_names))
    if faltan:
        d.program_names.update(dict(db.query(Program.id, Program.name)
                                    .filter(Program.id.in_(faltan)).all()))

    umbral = round(d.cfg.crit_days * 5 / 7)
    rows = []
    for o in visibles:
        p = prod.get(o.user_id, _empty_prod())
        dictamenes = p["docs_approved"] + p["docs_rejected"]
        cola = colas[o.user_id]
        # Decisión del controlador (Ronda 0 de U1): el MISMO ritmo que la
        # proyección de la tarjeta (10 días hábiles), no el del rango.
        ritmo = _officer_pace(d, p)
        dias = max(0, cola["total_escolares"]) / ritmo if ritmo > 0 else None
        ocupados, cap = lugares.get(o.user_id, (0, 0))
        rows.append({
            "user_id": o.user_id, "name": o.name, "color_index": color[o.user_id],
            "programs": sorted(({"id": pid, "name": d.pname(pid)}
                                for pid in o.program_ids if d.in_scope(pid)),
                               key=lambda x: (_name_key(x["name"]), x["id"])),
            "programs_out_of_scope": sum(1 for pid in o.program_ids if not d.in_scope(pid)),
            "no_programs": not o.program_ids,
            "queue": cola,
            "prod": {"req_reviewed": p["req_reviewed"], "docs_approved": p["docs_approved"],
                     "docs_rejected": p["docs_rejected"], "dictamenes": dictamenes,
                     "attended": p["attended"], "no_show": p["no_show"],
                     "liberated": p["liberated"]},
            "reject_rate": p["reject_rate"],
            "reject_text": _fmt_pct(None if p["reject_rate"] is None else p["reject_rate"] * 100),
            "days_to_clear": dias,
            "days_to_clear_text": "—" if dias is None else _fmt_dec(dias),
            "over_threshold": dias is not None and dias > umbral,
            "places": {"occupied": ocupados, "capacity": cap, "free": max(0, cap - ocupados)},
        })

    # Con la serie alargada, alguien pudo producir SOLO antes del rango (todos
    # sus totales en 0): no es «Otros» de este rango.
    ajenos = [uid for uid in prod if uid not in color and _produced(prod[uid])]
    others = None
    if ajenos:
        suma = {k: sum(prod[u][k] for u in ajenos)
                for k in ("req_reviewed", "docs_approved", "docs_rejected", "attended",
                          "no_show", "liberated")}
        dict_otros = suma["docs_approved"] + suma["docs_rejected"]
        rate = suma["docs_rejected"] / dict_otros if dict_otros else None
        others = {"actors": len(ajenos), **suma, "dictamenes": dict_otros, "reject_rate": rate,
                  "reject_text": _fmt_pct(None if rate is None else rate * 100)}

    chips = []
    for o in todos:
        nuevo = f.toggle_officer(o.user_id)
        chips.append({"user_id": o.user_id, "name": o.name, "color_index": color[o.user_id],
                      "hidden": o.user_id in f.hidden_officers,
                      "toggle_url": nuevo.page_url(page=1),
                      "body_toggle_url": nuevo.body_url(page=1)})
    ocupados_t, cap_t = lugares.get(0, (0, 0))
    escala = {"queue": max([_queue_total(colas[o.user_id]) for o in todos], default=0),
              "prod": max([_prod_total(prod.get(o.user_id, _empty_prod())) for o in todos],
                          default=0)}
    cards = _cards_sorted([
        _officer_card(d, o, color[o.user_id], colas[o.user_id],
                      prod.get(o.user_id, _empty_prod()), lugares.get(o.user_id, (0, 0)),
                      row, escala, umbral)
        for o, row in zip(visibles, rows)])
    return {
        "officer_chips": chips,
        "hidden_officers_count": sum(1 for c in chips if c["hidden"]),
        "rows": rows,
        "others": others,
        "range_bdays": len(habiles),
        "capacity_total": {"occupied": ocupados_t, "capacity": cap_t,
                           "free": max(0, cap_t - ocupados_t)},
        # Ronda 2 (spec §12, R1/R3/R4a)
        "cards": cards,
        "card_scale": escala,
        "queue_legend": [{"key": k, "label": label, "color": _QUEUE_COLORS[k]}
                         for k, label in _QUEUE_PARTS],
        "prod_legend": [{"key": k, "label": label, "color": _PROD_COLORS[k]}
                        for k, label in _PROD_PARTS],
        "heatmap": _heatmap(d, todos, visibles, prod, habiles,
                            ajenos if others is not None else []),
        "projection_threshold": {"days": umbral,
                                 "text": _plural(umbral, "día hábil", "días hábiles")},
        "projection_note": d.projection_note,
        "projection_window": PACE_WINDOW,
    }


def _officer_pace(d: _Data, p: dict) -> float:
    """Dictámenes + revisiones por día hábil de los ÚLTIMOS 10 días hábiles
    (`production.by_day` alargada con `by_day_from`): el ÚNICO ritmo de un
    encargado, para «Días para vaciar» de la tabla y para la proyección de su
    tarjeta (decisión del controlador, Ronda 0 de U1; R4)."""
    return flow.pace(p.get("by_day") or {}, d.today, PACE_WINDOW, holidays=d.holidays)


def _produced(p: dict) -> bool:
    """¿Hizo algo en el rango? (`production` con `by_day_from` también trae a
    quien solo produjo antes del rango, con todos sus totales en 0)."""
    return any(p.get(k) for k in ("req_reviewed", "docs_approved", "docs_rejected",
                                  "attended", "no_show", "liberated"))


def _queue_total(cola: dict) -> int:
    """Largo de la barra «Cola hoy»: las 4 partes, «Listos sin cita» incluida."""
    return sum(int(cola.get(k, 0)) for k, _ in _QUEUE_PARTS)


def _prod_total(p: dict) -> int:
    """Largo de la barra «Producción»: revisiones + dictámenes del rango."""
    return sum(int(p.get(k, 0)) for k, _ in _PROD_PARTS)


def _segments(parts, values: dict, colors: dict, scale: int) -> list[dict]:
    segs = charts.scaled_segments([(k, int(values.get(k, 0))) for k, _ in parts], scale)
    etiquetas = dict(parts)
    for s in segs:
        s.update({"label": etiquetas[s["key"]], "color": colors[s["key"]],
                  "tip": f"{etiquetas[s['key']]}: {s['value']}"})
    return segs


def _officer_card(d: _Data, o: roff.Officer, color_index: int, cola: dict, p: dict,
                  lugar: tuple[int, int], row: dict, escala: dict, umbral: int) -> dict:
    """Tarjeta de un encargado (R1). Las barras usan la escala COMÚN `escala`
    (todas las tarjetas se comparan a lo largo); la proyección mide los
    últimos 10 días hábiles (R4a), con el umbral en días hábiles."""
    ocupados, cap = lugar
    prod_vals = {k: int(p.get(k, 0)) for k, _ in _PROD_PARTS}
    return {
        "user_id": o.user_id, "name": o.name, "color_index": color_index,
        "programs": row["programs"], "programs_out_of_scope": row["programs_out_of_scope"],
        "no_programs": row["no_programs"],
        "queue": {**cola, "total": _queue_total(cola)},
        "queue_segments": _segments(_QUEUE_PARTS, cola, _QUEUE_COLORS, escala["queue"]),
        "prod": {**prod_vals, "dictamenes": prod_vals["docs_approved"] + prod_vals["docs_rejected"],
                 "total": _prod_total(prod_vals), "attended": int(p.get("attended", 0)),
                 "no_show": int(p.get("no_show", 0)), "liberated": int(p.get("liberated", 0))},
        "prod_segments": _segments(_PROD_PARTS, prod_vals, _PROD_COLORS, escala["prod"]),
        "reject_rate": row["reject_rate"], "reject_text": row["reject_text"],
        "places": {"occupied": ocupados, "capacity": cap, "free": max(0, cap - ocupados),
                   "pct": min(100.0, ocupados / cap * 100) if cap else None,
                   "text": f"{ocupados} de {cap}"},
        "projection": _projection(cola["total_escolares"], _officer_pace(d, p), d.today,
                                  unit="pendientes", verb="dictámenes y revisiones",
                                  threshold=umbral, holidays=d.holidays),
    }


def _cards_sorted(cards: list[dict]) -> list[dict]:
    """El más cargado primero (R1): primero quien tiene cola y no produjo
    nada medible (cola mayor primero), luego por días hábiles para vaciar
    (desc, desempate cola mayor), al final los que están al día; nombre al
    último."""
    def llave(c):
        p = c["projection"]
        if p["status"] == "no_pace":
            return (0, -p["queue"], 0, _name_key(c["name"]))
        if p["status"] == "clear":
            return (2, 0, 0, _name_key(c["name"]))
        return (1, -p["days"], -p["queue"], _name_key(c["name"]))
    return sorted(cards, key=llave)


def _heatmap(d: _Data, todos: list[roff.Officer], visibles: list[roff.Officer],
             prod: dict[int, dict], habiles: list[date], ajenos: list[int]) -> dict:
    """Mapa de calor encargado × día hábil del rango (R3): dictámenes de
    documento + revisiones de solicitud por día (`production.by_day`).

    La escala (`vmax`) sale de TODOS los encargados y de «Otros»: ocultar a
    uno no cambia el color de los demás. Filas = encargados visibles, por
    nombre (el orden de la tabla), y al FINAL la fila «Otros» (`ajenos`: los
    mismos no encargados de `others`, sumados por día) cuando existe
    `others` (decisión del controlador, Ronda 0 de U1). Columnas flexibles:
    con más de `HEATMAP_FIT_DAYS` días (`wide`) solo se rotulan los lunes y la
    tarjeta hace scroll propio."""
    def serie(uid):
        return (prod.get(uid) or {}).get("by_day") or {}

    otros: dict[date, int] = {}
    for uid in ajenos:
        for dia, n in serie(uid).items():
            otros[dia] = otros.get(dia, 0) + int(n)
    series = [serie(o.user_id) for o in todos] + ([otros] if ajenos else [])
    vmax = max([s.get(dia, 0) for s in series for dia in habiles], default=0)
    wide = len(habiles) > HEATMAP_FIT_DAYS
    days = [{"date": dia, "iso": dia.isoformat(), "label": f"{_DIAS[dia.weekday()]} {dia.day}",
             "label_long": _fmt_day_long(dia, d.today),
             "week_start": i > 0 and dia.weekday() == 0,
             "show_label": (not wide) or i == 0 or dia.weekday() == 0,
             "is_today": dia == d.today}
            for i, dia in enumerate(habiles)]
    def fila(user_id, nombre, datos, *, es_otros=False, actores=None):
        celdas = []
        for dia in days:
            n = int(datos.get(dia["date"], 0))
            cubeta = charts.bin_index(n, vmax)
            celdas.append({
                "iso": dia["iso"], "n": n, "bin": cubeta,
                "color": CALENDAR_ZERO_COLOR if cubeta == 0 else CALENDAR_RAMP[cubeta - 1],
                "tip": f"{nombre} · {dia['label_long']}: "
                       + _plural(n, "dictamen o revisión", "dictámenes y revisiones")})
        return {"user_id": user_id, "name": nombre, "is_others": es_otros, "actors": actores,
                "cells": celdas, "total": sum(c["n"] for c in celdas)}

    rows = [fila(o.user_id, o.name, serie(o.user_id)) for o in visibles]
    if ajenos:
        rows.append(fila(None, "Otros", otros, es_otros=True, actores=len(ajenos)))
    return {"days": days, "rows": rows, "legend": _bin_legend(vmax), "vmax": vmax,
            "n_days": len(days), "wide": wide}


def _ctx_carreras(db: Session, d: _Data) -> dict:
    """Pestaña Carreras (spec §5.4).

    - `rows`: una por carrera visible con algún pendiente, liberado o inscrito
      (más «Sin carrera» si aplica), orden atorados desc y luego nombre («Sin
      carrera» al final del empate): `{id (None = «Sin carrera»), name,
      segments: [{key, label, group, color, value, x_pct, w_pct, tip}] (barra
      apilada por etapa, color de su grupo, sin las vacías), total (items:
      pendientes + liberados), enrolled («Inscritos» = procesos creados NO
      revocados, pausados y terminados incluidos: la MISMA definición que la
      serie `enrolled` del acumulado de Ritmo, `Snapshot.enrolled_by_program`),
      liberated, pct_liberated (liberated / enrolled × 100, float|None),
      pct_text, stuck (lentos + atorados), crit, officers: [nombres]}`.
    - `stage_legend`: los 5 grupos `[{code, label, color}]` (mismo mapeo que
      «Dónde están hoy»).

    Ronda 2 (spec §12, R4b) — llaves NUEVAS:

    - `rows[*].pending`: pendientes de la carrera (items no liberados; en
      pausa no cuenta, como en todo el tablero).
    - `rows[*].forecast`: `_projection(pending, liberados de la carrera por
      día hábil en los últimos 10 días hábiles)` — `{queue, unit
      ("pendientes"), per_day, per_day_text, verb ("liberados"), rate_text,
      days, date, date_text, status ("clear" | "ok" | "no_pace"),
      over_threshold (False), text}`; independiente del rango.
    - `projection_note` («a este ritmo, sin feriados ni nuevas entradas»),
      `projection_window` (10).
    """
    por_carrera = _officer_names_by_program(d, d.officer_list(db))
    grupos: dict[int | None, list[Item]] = {pid: [] for pid in d.snapshot.enrolled_by_program}
    for it in d.items:
        grupos.setdefault(it.program_id, []).append(it)
    liberados_por_carrera = flow.liberated_by_program(d.items)
    rows = []
    for pid, items in grupos.items():
        conteo = {code: 0 for code in _STAGE_CODES}
        for it in items:
            conteo[it.stage] += 1
        segmentos = charts.stack_segments([(code, conteo[code]) for code in _STAGE_CODES])
        for s in segmentos:
            s.update({"label": _STAGE_LABEL[s["key"]], "group": _STAGE_GROUP[s["key"]],
                      "color": _GROUP_COLOR[_STAGE_GROUP[s["key"]]],
                      "tip": f"{_STAGE_LABEL[s['key']]}: {s['value']}"})
        inscritos = d.snapshot.enrolled_by_program.get(pid, 0)
        liberados = conteo[_LIBERADO]
        pct = liberados / inscritos * 100 if inscritos else None
        pendientes = len(items) - liberados
        rows.append({
            "id": pid, "name": d.pname(pid), "segments": segmentos, "total": len(items),
            "enrolled": inscritos, "liberated": liberados, "pct_liberated": pct,
            "pct_text": _fmt_pct(pct),
            "stuck": sum(1 for it in items if it.idle_level in ("warn", "crit")),
            "crit": sum(1 for it in items if it.idle_level == "crit"),
            "officers": list(por_carrera.get(pid, [])) if pid is not None else [],
            "pending": pendientes,
            "forecast": _projection(
                pendientes, flow.pace(liberados_por_carrera.get(pid, {}), d.today, PACE_WINDOW,
                                      holidays=d.holidays),
                d.today, unit="pendientes", verb="liberados", holidays=d.holidays),
        })
    rows.sort(key=lambda r: (-r["stuck"], r["id"] is None, _name_key(r["name"]),
                             r["id"] or 0))
    return {
        "rows": rows,
        "stage_legend": [{"code": code, "label": label, "color": color}
                         for code, label, color in STAGE_GROUPS],
        "projection_note": d.projection_note,
        "projection_window": PACE_WINDOW,
    }


def _matches(it: Item, *, ball, idle_level, stage, motive=None) -> bool:
    if motive and ball and MOTIVE_ACTOR.get(motive) != ball:
        motive = None                   # de otra área: se ignora (como `ReportFilters`)
    if ball and ball not in {a for a, _ in it.balls}:
        return False
    # Motivo (R2): el PRIMERO del área en el orden del catálogo, la misma regla
    # de la barra partida de Panorama (cifra y lista cuadran).
    if motive and first_motives(it).get(MOTIVE_ACTOR[motive]) != motive:
        return False
    if stage == "req_review":
        # «Por revisar» de Escolares = req_review + req_unverified (legado): la
        # misma suma que la KPI y la alerta de solicitudes (cifra y lista cuadran).
        if it.stage not in _REQUEST_REVIEW_STAGES:
            return False
    elif stage and it.stage != stage:
        return False
    if idle_level == "warn":
        return it.idle_level in ("warn", "crit")
    if idle_level == "crit":
        return it.idle_level == "crit"
    return True


def _ctx_atorados(db: Session, d: _Data) -> dict:
    """Pestaña Atorados (spec §5.5).

    - `page`: `utils/paging.Page` (50 por página) de los items visibles que
      pasan `ball`/`level`/`stage`, orden días sin movimiento desc (desempate:
      solicitudes primero, id). Cada elemento de `page.items` es un dict:
      `{item (el Item), kind, id, label, control, program, stage, stage_label,
      group_color, motives: [{actor, actor_label, color, text}], motive_text
      ("Escolares: Revisar solicitud" | "Cita el 16 oct" | "Liberado el 9
      oct"), days, days_text, level, level_label, level_icon, officers:
      [nombres de los encargados de su carrera], href (expediente o bandeja de
      Solicitudes)}`.
    - `chips`: `{"ball": [...], "level": [...], "stage": [...]}`; cada chip
      `{code (None = «Todas»/«Todos»), label, active, n, url, body_url}` con `n`
      = cuántos quedarían con ese chip y los otros dos filtros vigentes
      (página 1). Pelota y etapa traen color (`color`).
    - `officers_by_program`: `{program_id: [nombres]}`, solo carreras del
      alcance del usuario.
    - Filtro de etapa: `stage=req_review` incluye también `req_unverified`
      (ambas son «por revisar» de Escolares; así la KPI y la alerta de
      solicitudes, que suman las dos, cuadran con la lista). El chip
      `req_unverified` sigue filtrando solo el legado.
    - `total`: `page.total`; `pager_url`/`pager_page_url`: liga del parcial y
      de la página SIN `page` (el macro `pager` agrega `page` por `hx-vals`).

    Ronda 2 (spec §12, R2) — filtro `motive` y llaves NUEVAS:

    - Filtro `motive` (código de `report_snapshot.MOTIVES`): deja los items
      cuyo PRIMER motivo del área de ese motivo es él (la regla de la barra
      de Panorama: la lista cuadra con su cifra). Basura o de otra área que
      `ball` se ignora (`ReportFilters` lo normaliza).
    - `chips["motive"]`: grupos por área en el orden de actores `[{actor,
      label, color, n (pendientes del área con los demás filtros), motives:
      [{code, label, active, n, color (tinte del área), url, body_url}]}]`;
      TODOS los motivos del catálogo del área (con `n` 0 incluidos: la
      plantilla decide si los oculta). La liga de un motivo fija también
      `ball` = su área; las ligas de `chips["ball"]` sueltan un motivo de otra
      área.
    - `motive_clear`: `{active (sin motivo), url, body_url}` — «Todos los
      motivos» (conserva `ball`).
    - `active_motive`: `{code, label, actor, actor_label}` o `None`.
    - `page.items[*].motives[*]` suma `code` (el primer motivo de ese actor,
      el que cuenta) y `codes` (todos los de ese actor, orden del catálogo).
    """
    f = d.filters
    por_carrera = _officer_names_by_program(d, d.officer_list(db))
    filtrados = [it for it in d.items if _matches(it, ball=f.ball, idle_level=f.idle_level,
                                                  stage=f.stage, motive=f.motive)]
    filtrados.sort(key=lambda it: (-it.idle_days, it.kind != "request", it.id))
    page = paginate_list(filtrados, f.page)

    filas = []
    for it in page.items:
        lvl_label, lvl_icon = LEVEL_UI.get(it.idle_level, LEVEL_UI["ok"])
        primeros = first_motives(it)
        todos_codigos: dict[str, list[str]] = {}
        for a, code in item_motives(it):
            todos_codigos.setdefault(a, []).append(code)
        motivos = [{"actor": a, "actor_label": _ACTOR_LABEL.get(a, a),
                    "color": _ACTOR_COLOR.get(a), "text": m, "code": primeros.get(a),
                    "codes": todos_codigos.get(a, [])} for a, m in it.balls]
        if motivos:
            motivo = " · ".join(f"{m['actor_label']}: {m['text']}" for m in motivos)
        elif it.stage == _LIBERADO and it.liberated_on is not None:
            motivo = f"Liberado el {_fmt_day(it.liberated_on)}"
        elif it.stage == "cita" and it.appt_date is not None:
            motivo = f"Cita el {_fmt_day(it.appt_date)}"
        else:
            motivo = "—"
        filas.append({
            "item": it, "kind": it.kind, "id": it.id, "label": it.label, "control": it.control,
            "program": d.pname(it.program_id), "stage": it.stage,
            "stage_label": _STAGE_LABEL.get(it.stage, it.stage),
            "group_color": _GROUP_COLOR.get(_STAGE_GROUP.get(it.stage, ""), None),
            "motives": motivos, "motive_text": motivo, "days": it.idle_days,
            "days_text": _plural(it.idle_days, "día", "días"), "level": it.idle_level,
            "level_label": lvl_label, "level_icon": lvl_icon,
            "officers": list(por_carrera.get(it.program_id, [])) if it.program_id else [],
            "href": it.href,
        })
    page = replace(page, items=filas)

    def n_con(**kw) -> int:
        args = {"ball": f.ball, "idle_level": f.idle_level, "stage": f.stage,
                "motive": f.motive, **kw}
        return sum(1 for it in d.items if _matches(it, **args))

    def chip(code, label, campo, color=None) -> dict:
        cambio = {campo: code, "page": 1}
        return {"code": code, "label": label, "active": getattr(f, campo) == code,
                "n": n_con(**{campo: code}), "color": color,
                "url": f.page_url(**cambio), "body_url": f.body_url(**cambio)}

    chips = {
        "ball": [chip(None, "Todas", "ball")]
                + [chip(a, _ACTOR_LABEL[a], "ball", _ACTOR_COLOR[a]) for a in _ACTOR_CODES],
        "level": [chip(code, label, "idle_level") for code, label in LEVELS],
        "stage": [chip(None, "Todas", "stage")]
                 + [chip(code, _STAGE_LABEL[code], "stage", _GROUP_COLOR[_STAGE_GROUP[code]])
                    for code in _STAGE_CODES],
    }
    # Motivo (R2): chips agrupados por área. Elegir un motivo fija también su
    # pelota (el chip de área queda marcado); cambiar de pelota lo suelta.
    grupos = []
    for a in _ACTOR_CODES:
        motivos_area = []
        for code in MOTIVE_CODES:
            if MOTIVE_ACTOR[code] != a:
                continue
            cambio = {"ball": a, "motive": code, "page": 1}
            motivos_area.append({"code": code, "label": MOTIVE_LABEL[code],
                                 "active": f.motive == code,
                                 "n": n_con(ball=a, motive=code), "color": _MOTIVE_COLOR[code],
                                 "url": f.page_url(**cambio), "body_url": f.body_url(**cambio)})
        grupos.append({"actor": a, "label": _ACTOR_LABEL[a], "color": _ACTOR_COLOR[a],
                       "n": n_con(ball=a, motive=None), "motives": motivos_area})
    chips["motive"] = grupos
    activo = None
    if f.motive:
        activo = {"code": f.motive, "label": MOTIVE_LABEL[f.motive],
                  "actor": MOTIVE_ACTOR[f.motive],
                  "actor_label": _ACTOR_LABEL[MOTIVE_ACTOR[f.motive]]}
    return {
        "page": page,
        "total": page.total,
        "chips": chips,
        "officers_by_program": por_carrera,
        "pager_url": f.body_url(page=1),
        "pager_page_url": f.page_url(page=1),
        "active_motive": activo,
        "motive_clear": {"active": f.motive is None,
                         "url": f.page_url(motive=None, page=1),
                         "body_url": f.body_url(motive=None, page=1)},
    }


_BUILDERS = {
    "panorama": _ctx_panorama,
    "ritmo": _ctx_ritmo,
    "encargados": _ctx_encargados,
    "carreras": _ctx_carreras,
    "atorados": _ctx_atorados,
}


class ReportService:
    """Fachada del tablero. Solo lectura."""

    @staticmethod
    def build(db: Session, *, user_id: int, filters: ReportFilters, today: date) -> dict:
        """Contexto común (`_common_ctx`) + el de `filters.tab` bajo esa llave.

        `today` lo pone la ruta (`db_now().date()`); aquí nunca se lee el
        reloj. Nunca levanta por filtros raros: `ReportFilters.parse` ya los
        normalizó y aquí un `cohort` inexistente cae a la convocatoria por
        omisión. Sin convocatorias o sin nada visible, cada pestaña devuelve su
        forma con ceros y listas vacías.
        """
        if filters.tab not in _BUILDERS:                 # construido a mano, sin `parse`
            filters = replace(filters, tab=DEFAULT_TAB)
        d = _load(db, int(user_id), filters, today)
        ctx = _common_ctx(d)
        ctx[d.filters.tab] = _BUILDERS[d.filters.tab](db, d)
        return ctx

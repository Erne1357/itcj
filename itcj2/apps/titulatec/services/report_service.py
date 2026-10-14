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

Consultas por pestaña (`/body`, caché de authz tibia; techo 20, lo fija
`test_reports_pages.py` con 4 y 16 procesos): convocatorias 1 + catálogo de
carreras 0-1 (solo con `px`) + encargados 0-4 (solo con `ox`, para validarlo;
se reusan en la pestaña) + instantánea 2-6 + lo propio de la pestaña —
Panorama: series 3 + capacidad 0-2 (solo con listos para agendar); Ritmo:
series 3 + nombres de quien liberó 0-1 (solo con `day`); Encargados: encargados
4 + producción 2 + capacidad 2 + nombres de carrera 0-1; Carreras y Atorados:
encargados 4. Medido el 2026-10-14 en el peor camino (con `px` y `ox`):
Panorama 17 · Ritmo 16 · Encargados 16 · Carreras 12 · Atorados 12 (sin `ox`:
Panorama 13, Ritmo 12). Ninguna crece con el número de procesos. Un usuario
acotado por carrera suma 1 (sus carreras).

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
from itcj2.apps.titulatec.services.report_snapshot import (
    ACTORS,
    MOTIVE_CLOSE_APPT,
    STAGE_GROUPS,
    STAGES,
    Item,
    ReportConfig,
    Snapshot,
    load_snapshot,
)
from itcj2.apps.titulatec.utils import charts
from itcj2.apps.titulatec.utils.business_days import is_business_day
from itcj2.apps.titulatec.utils.paging import paginate_list, parse_page

# ---------------------------------------------------------------------------
# Catálogos de la vista
# ---------------------------------------------------------------------------
BASE_URL = "/titulatec/admin/tablero"
BODY_URL = f"{BASE_URL}/body"
APPOINTMENTS_URL = "/titulatec/admin/appointments"

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
    `level`, `stage`, `page`: Atorados. `day`: día del calendario de Ritmo."""
    tab: str = DEFAULT_TAB
    cohort: int | str | None = None
    range_days: int | None = DEFAULT_RANGE
    hidden_programs: frozenset[int] = frozenset()
    hidden_officers: frozenset[int] = frozenset()
    ball: str | None = None
    level: str = DEFAULT_LEVEL
    stage: str | None = None
    page: int = 1
    day: date | None = None

    def __post_init__(self):
        object.__setattr__(self, "hidden_programs",
                           frozenset(int(p) for p in self.hidden_programs))
        object.__setattr__(self, "hidden_officers",
                           frozenset(int(u) for u in self.hidden_officers))

    @classmethod
    def parse(cls, params: Mapping[str, str] | None) -> ReportFilters:
        """De los parámetros de la URL (todos `str`; HTMX manda vacíos). Un
        valor inválido cae a su default; nunca levanta."""
        tab = _raw(params, "tab").lower()
        ball = _raw(params, "ball").lower()
        level = _raw(params, "level").lower()
        stage = _raw(params, "stage").lower()
        return cls(
            tab=tab if tab in TAB_CODES else DEFAULT_TAB,
            cohort=_parse_cohort(_raw(params, "cohort")),
            range_days=_parse_range(_raw(params, "range")),
            hidden_programs=_parse_ids(_raw(params, "px"), allow_zero=True),
            hidden_officers=_parse_ids(_raw(params, "ox"), allow_zero=False),
            ball=ball if ball in _ACTOR_CODES else None,
            level=level if level in LEVEL_CODES else DEFAULT_LEVEL,
            stage=stage if stage in _STAGE_CODES else None,
            page=_parse_page(_raw(params, "page")),
            day=_parse_day(_raw(params, "day")),
        )

    def query(self, **changes) -> str:
        """Querystring estable: `tab` siempre (identifica la vista y empata con
        la barra de pestañas), luego cohort, range, px, ox, ball, level, stage,
        page y day, cada uno SOLO si no vale su default."""
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
        if f.level != DEFAULT_LEVEL:
            pairs.append(("level", f.level))
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
                 officers_cache=officers_cache)


def _flow_counts(db: Session, d: _Data, start: date) -> dict[str, dict[date, int]]:
    """`report_flow.daily_counts` con el alcance visible (3 consultas); vacío
    sin nada visible (sin consultar)."""
    if d.nothing_visible:
        return {"requests_new": {}, "requests_reviewed": {}, "enrolled": {}}
    return flow.daily_counts(db, cohort_ids=d.cohort_ids, programs=d.programs,
                             include_unmapped=d.include_unmapped, start=start, end=d.today)


def _atorados_links(d: _Data, **changes) -> tuple[str, str]:
    """(url de página, url de parcial) de la pestaña Atorados con `changes`."""
    base = {"tab": "atorados", "ball": None, "stage": None, "level": DEFAULT_LEVEL,
            "page": 1, "day": None}
    base.update(changes)
    return d.filters.page_url(**base), d.filters.body_url(**base)


def _range_text(d: _Data) -> str:
    if d.filters.range_days:
        return f"Últimos {d.filters.range_days} días"
    return f"Toda la convocatoria (desde el {_fmt_day(d.range_start)})"


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
        partes.append(f"Nivel: {dict(LEVELS)[f.level]}")
        if f.ball:
            partes.append(f"Pelota: {_ACTOR_LABEL[f.ball]}")
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
    por_dia = flow.pace(liberated, d.today, PACE_WINDOW)
    cuando = flow.forecast(pendientes, por_dia, d.today)
    if cuando is None:
        texto = "sin ritmo medible"
    elif pendientes == 0:
        texto = "sin pendientes"
    else:
        texto = _fmt_day_long(cuando, d.today)
    return {"per_day": por_dia, "text": _fmt_dec(por_dia), "window": PACE_WINDOW,
            "pending": pendientes, "forecast": cuando, "forecast_text": texto,
            "note": _FORECAST_NOTE}


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
    # (legado) sumada. La liga va a la etapa que más tiene (`req_review` en un
    # empate); con las dos, la lista de Atorados muestra solo esa etapa.
    viejas = {stage: sum(1 for it in d.items
                         if it.stage == stage and it.idle_days >= cfg.crit_days)
              for stage in _REQUEST_REVIEW_STAGES}
    n = sum(viejas.values())
    if n:
        etapa = max(_REQUEST_REVIEW_STAGES, key=lambda st: (viejas[st], st == "req_review"))
        url, body = _atorados_links(d, stage=etapa, level="crit")
        alerta("requests_crit", "crit",
               f"{_plural(n, 'solicitud por revisar lleva', 'solicitudes por revisar llevan')} "
               f"{cfg.crit_days} días o más esperando", url, body)
    # 2. Expedientes con documentos por dictaminar quietos >= WARN días.
    lentos = [it for it in d.items
              if it.stage == "docs" and it.pending_docs > 0 and it.idle_days >= cfg.warn_days]
    if lentos:
        docs = sum(it.pending_docs for it in lentos)
        url, body = _atorados_links(d, stage="docs", ball="escolares", level="warn")
        alerta("docs_warn", "warn",
               f"{_plural(len(lentos), 'expediente', 'expedientes')} con documentos por "
               f"dictaminar ({_plural(docs, 'documento', 'documentos')}) sin movimiento en "
               f"{cfg.warn_days} días o más", url, body)
    # 3. Listos para agendar > lugares libres en los próximos días hábiles.
    listos = sum(1 for it in d.pending if it.ready_to_book)
    if listos:
        ocupados, capacidad = roff.capacity(db, today=d.today, days=CAPACITY_DAYS).get(0, (0, 0))
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
        url, body = _atorados_links(d, stage="cita", ball="escolares", level="all")
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
        url, body = _atorados_links(d, stage=code, level="all")
        stages.append({"code": code, "label": _STAGE_LABEL[code], "group": _STAGE_GROUP[code],
                       "group_label": _GROUP_LABEL[_STAGE_GROUP[code]],
                       "color": _GROUP_COLOR[_STAGE_GROUP[code]], "value": fila["value"],
                       "pct": fila["pct"], "url": url, "body_url": body,
                       "tip": f"{_STAGE_LABEL[code]}: {fila['value']}"})

    cuenta = {a: [0, 0, 0] for a in _ACTOR_CODES}           # [procesos, ≥warn, crit]
    for it in pend:
        for actor in {a for a, _ in it.balls}:
            acc = cuenta.setdefault(actor, [0, 0, 0])
            acc[0] += 1
            acc[1] += it.level in ("warn", "crit")
            acc[2] += it.level == "crit"
    balls = []
    for fila in charts.bar_rows([(a, cuenta[a][0]) for a in _ACTOR_CODES]):
        a = fila["label"]
        url, body = _atorados_links(d, ball=a, level="all")
        s_url, s_body = _atorados_links(d, ball=a)
        balls.append({"code": a, "label": _ACTOR_LABEL[a], "color": _ACTOR_COLOR[a],
                      "value": fila["value"], "pct": fila["pct"], "stuck": cuenta[a][1],
                      "crit": cuenta[a][2], "url": url, "body_url": body,
                      "stuck_url": s_url, "stuck_body_url": s_body,
                      "tip": f"{_ACTOR_LABEL[a]}: {fila['value']} "
                             f"({_plural(cuenta[a][1], 'atorado o lento', 'atorados o lentos')})"})

    revisar = [it for it in d.items if it.stage in _REQUEST_REVIEW_STAGES]
    crit = sum(1 for it in pend if it.level == "crit")
    warn = sum(1 for it in pend if it.level == "warn")
    lib_url, lib_body = _atorados_links(d, stage=_LIBERADO, level="all")
    req_url, req_body = _atorados_links(d, stage="req_review", level="all")
    st_url, st_body = _atorados_links(d)
    cr_url, cr_body = _atorados_links(d, level="crit")
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
    }


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
    legend = [{"bin": 0, "label": "0", "color": CALENDAR_ZERO_COLOR}]
    for i in range(1, len(CALENDAR_RAMP) + 1):
        lo = math.floor((i - 1) * vmax / len(CALENDAR_RAMP)) + 1
        hi = math.floor(i * vmax / len(CALENDAR_RAMP))
        if lo <= hi:
            legend.append({"bin": i, "label": str(lo) if lo == hi else f"{lo}–{hi}",
                           "color": CALENDAR_RAMP[i - 1]})
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
      que tienen alguno: `[{id (None = «Sin carrera»), name, value, pct, tip}]`.
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
                           "tip": f"{fila['label']}: {_plural(n, 'liberado', 'liberados')}"})

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
    - `others`: producción de quienes NO son encargados (jefa, admin) en el
      rango, `{actors, req_reviewed, docs_approved, docs_rejected, dictamenes,
      attended, no_show, liberated, reject_rate, reject_text}`, o `None`.
    - `clear_bars`: `{rows: [{user_id, name, color_index, value, text, pct}]
      (mayor primero, solo con valor), threshold, threshold_text,
      threshold_pct, vmax}`; umbral = CRIT días naturales en días hábiles
      (14 -> 10).
    - `sparks`: small multiples de «Dictámenes por día» con la MISMA escala:
      `{width, height, vmax, days: [iso...], series: [{user_id, name,
      color_index, values, points, total}]}` sobre los días hábiles del rango.
    - `range_bdays` (días hábiles del rango), `capacity_total`: `{occupied,
      capacity, free}` (todas las ventanas, llave 0 de `capacity`).
    """
    from itcj2.core.models.program import Program

    f = d.filters
    todos = d.officer_list(db)
    color = {o.user_id: i for i, o in enumerate(todos)}
    visibles = [o for o in todos if o.user_id not in f.hidden_officers]
    colas = roff.queues(visibles, d.items)
    prod = (roff.production(db, start=d.range_start, end=d.today, cohort_ids=d.cohort_ids)
            if d.cohort_ids != [] else {})
    lugares = roff.capacity(db, today=d.today, days=CAPACITY_DAYS)
    habiles = [dia for dia in _days(d.range_start, d.today) if is_business_day(dia)]

    faltan = sorted({pid for o in visibles for pid in o.program_ids
                     if d.in_scope(pid)} - set(d.program_names))
    if faltan:
        d.program_names.update(dict(db.query(Program.id, Program.name)
                                    .filter(Program.id.in_(faltan)).all()))

    umbral = round(d.cfg.crit_days * 5 / 7)
    rows, barras, series = [], [], []
    for o in visibles:
        p = prod.get(o.user_id, _empty_prod())
        dictamenes = p["docs_approved"] + p["docs_rejected"]
        cola = colas[o.user_id]
        dias = roff.days_to_clear(cola["total_escolares"], p["by_day"], habiles)
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
        if dias is not None:
            barras.append((o, dias))
        series.append((o, [p["by_day"].get(dia, 0) for dia in habiles]))

    tope_barras = max([umbral] + [v for _, v in barras])
    barras.sort(key=lambda ov: (-ov[1], _name_key(ov[0].name)))
    clear_rows = []
    for (o, v), fila in zip(barras, charts.bar_rows([(o.name, v) for o, v in barras], tope_barras)):
        clear_rows.append({"user_id": o.user_id, "name": o.name, "color_index": color[o.user_id],
                           "value": v, "text": _fmt_dec(v), "pct": fila["pct"]})
    tope_spark = max([1] + [max(vals, default=0) for _, vals in series])
    sparks = [{"user_id": o.user_id, "name": o.name, "color_index": color[o.user_id],
               "values": vals, "total": sum(vals),
               "points": charts.points_attr(charts.line_points(
                   vals, width=SPARK_W, height=SPARK_H, vmax=tope_spark, pad=2))}
              for o, vals in series]

    ajenos = [uid for uid in prod if uid not in color]
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
    return {
        "officer_chips": chips,
        "hidden_officers_count": sum(1 for c in chips if c["hidden"]),
        "rows": rows,
        "others": others,
        "clear_bars": {"rows": clear_rows, "threshold": umbral,
                       "threshold_text": _plural(umbral, "día hábil", "días hábiles"),
                       "threshold_pct": umbral / tope_barras * 100 if tope_barras else 0,
                       "vmax": tope_barras},
        "sparks": {"width": SPARK_W, "height": SPARK_H, "vmax": tope_spark,
                   "days": [dia.isoformat() for dia in habiles], "series": sparks},
        "range_bdays": len(habiles),
        "capacity_total": {"occupied": ocupados_t, "capacity": cap_t,
                           "free": max(0, cap_t - ocupados_t)},
    }


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
    """
    por_carrera = _officer_names_by_program(d, d.officer_list(db))
    grupos: dict[int | None, list[Item]] = {pid: [] for pid in d.snapshot.enrolled_by_program}
    for it in d.items:
        grupos.setdefault(it.program_id, []).append(it)
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
        rows.append({
            "id": pid, "name": d.pname(pid), "segments": segmentos, "total": len(items),
            "enrolled": inscritos, "liberated": liberados, "pct_liberated": pct,
            "pct_text": _fmt_pct(pct),
            "stuck": sum(1 for it in items if it.level in ("warn", "crit")),
            "crit": sum(1 for it in items if it.level == "crit"),
            "officers": list(por_carrera.get(pid, [])) if pid is not None else [],
        })
    rows.sort(key=lambda r: (-r["stuck"], r["id"] is None, _name_key(r["name"]),
                             r["id"] or 0))
    return {
        "rows": rows,
        "stage_legend": [{"code": code, "label": label, "color": color}
                         for code, label, color in STAGE_GROUPS],
    }


def _matches(it: Item, *, ball, level, stage) -> bool:
    if ball and ball not in {a for a, _ in it.balls}:
        return False
    if stage and it.stage != stage:
        return False
    if level == "warn":
        return it.level in ("warn", "crit")
    if level == "crit":
        return it.level == "crit"
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
    - `total`: `page.total`; `pager_url`/`pager_page_url`: liga del parcial y
      de la página SIN `page` (el macro `pager` agrega `page` por `hx-vals`).
    """
    f = d.filters
    por_carrera = _officer_names_by_program(d, d.officer_list(db))
    filtrados = [it for it in d.items if _matches(it, ball=f.ball, level=f.level, stage=f.stage)]
    filtrados.sort(key=lambda it: (-it.idle_days, it.kind != "request", it.id))
    page = paginate_list(filtrados, f.page)

    filas = []
    for it in page.items:
        lvl_label, lvl_icon = LEVEL_UI.get(it.level, LEVEL_UI["ok"])
        motivos = [{"actor": a, "actor_label": _ACTOR_LABEL.get(a, a),
                    "color": _ACTOR_COLOR.get(a), "text": m} for a, m in it.balls]
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
            "days_text": _plural(it.idle_days, "día", "días"), "level": it.level,
            "level_label": lvl_label, "level_icon": lvl_icon,
            "officers": list(por_carrera.get(it.program_id, [])) if it.program_id else [],
            "href": it.href,
        })
    page = replace(page, items=filas)

    def n_con(**kw) -> int:
        args = {"ball": f.ball, "level": f.level, "stage": f.stage, **kw}
        return sum(1 for it in d.items if _matches(it, **args))

    def chip(code, label, campo, color=None) -> dict:
        cambio = {campo: code, "page": 1}
        return {"code": code, "label": label, "active": getattr(f, campo) == code,
                "n": n_con(**{campo: code}), "color": color,
                "url": f.page_url(**cambio), "body_url": f.body_url(**cambio)}

    chips = {
        "ball": [chip(None, "Todas", "ball")]
                + [chip(a, _ACTOR_LABEL[a], "ball", _ACTOR_COLOR[a]) for a in _ACTOR_CODES],
        "level": [chip(code, label, "level") for code, label in LEVELS],
        "stage": [chip(None, "Todas", "stage")]
                 + [chip(code, _STAGE_LABEL[code], "stage", _GROUP_COLOR[_STAGE_GROUP[code]])
                    for code in _STAGE_CODES],
    }
    return {
        "page": page,
        "total": page.total,
        "chips": chips,
        "officers_by_program": por_carrera,
        "pager_url": f.body_url(page=1),
        "pager_page_url": f.page_url(page=1),
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

"""Pestaña «Bitácora»: explorador de `titulatec_audit_log`, SOLO LECTURA.

Para el rol `admin` de TitulaTec (permiso `titulatec.audit.page.list`, decisión
D2 de la spec `2026-10-07-titulatec-bitacora-design.md`). Responde a «¿quién hizo
qué, cuándo y con qué antes/después?» sin entrar a la base.

Rutas: `GET ""` (página: filtros + resultados), `GET /body` (solo los
resultados, para HTMX: los filtros viven fuera del swap y no pierden el foco) y
`GET /entry/{id}` (detalle de una fila: antes/después, payload, huella de la
petición y las filas hermanas del mismo `request_id`).

Filtros (todos `str` y parseados a mano: HTMX manda `process_id=` vacío y un
`int | None` respondería 422): desde/hasta (default del shell: últimos 7 días;
en el parcial, vacío = sin límite), módulo, acción, quién, alumno (nº de
control, nombre o folio del proceso, más `subject_label`), expediente (sus filas
más las de su solicitud de inscripción, que no llevan `process_id`: las que
empiezan con el nº de control del alumno), texto en el motivo e «Incluir
cambios de datos» (apagado: solo `action` y `process_event`). Un valor fuera de
catálogo se ignora, nunca revienta.

`occurred_at` es naive en hora local: los filtros de fecha comparan naive
(`desde 00:00`, `hasta + 1 día`). NO HACE NADA más que leer.
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.utils.paging import (
    PAGE_SIZE, Page, like_pattern, normalize_q, paginate_query, parse_page,
)

logger = logging.getLogger("itcj2.apps.titulatec.pages.audit_admin")
router = APIRouter(prefix="/admin/bitacora", tags=["titulatec-pages-audit"])

_LIST = ["titulatec.audit.page.list"]
_DEFAULT_DAYS = 7
_SIBLINGS_MAX = 50
_BIGINT_MAX = 2**63 - 1
_REASON_CLIP = 90

# Insignia del tipo de actor distinto de un usuario con nombre.
_KIND_BADGES = {
    "public": "Público",
    "system": "Sistema",
    "cli": "CLI",
    "celery": "Tarea",
}
_DATA_OPS = {"insert": "Alta", "update": "Cambio", "delete": "Baja"}


# ---------------------------------------------------------------------------
# Parseo de filtros
# ---------------------------------------------------------------------------
def _date(raw) -> datetime | None:
    """`YYYY-MM-DD` -> medianoche local naive; basura/vacío -> None."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _int(raw) -> int | None:
    raw = (raw or "").strip() if isinstance(raw, str) else ""
    # `isdecimal` + `isascii`: `isdigit` acepta «²» y `int()` truena con él.
    return int(raw) if raw.isdecimal() and raw.isascii() and len(raw) < 10 else None


def _catalogo_acciones() -> dict[str, tuple[str, str]]:
    """código -> (módulo, etiqueta): explícitas + espejo de `ProcessEvent`."""
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI
    from itcj2.apps.titulatec.services.audit_actions import (
        AUDIT_ACTIONS, PROCESS_EVENT_PREFIX, process_event_module,
    )

    out = dict(AUDIT_ACTIONS)
    for tipo, ui in _EVENT_UI.items():
        out[PROCESS_EVENT_PREFIX + tipo] = (process_event_module(tipo), ui[0])
    return out


def _label(action: str, entity_type) -> str:
    """Etiqueta legible de una fila; nunca truena con un código desconocido."""
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI
    from itcj2.apps.titulatec.services.audit_actions import (
        AUDIT_ACTIONS, PROCESS_EVENT_PREFIX, TABLE_LABELS,
    )

    if action in AUDIT_ACTIONS:
        return AUDIT_ACTIONS[action][1]
    if action.startswith(PROCESS_EVENT_PREFIX):
        tipo = action[len(PROCESS_EVENT_PREFIX):]
        ui = _EVENT_UI.get(tipo)
        return ui[0] if ui else tipo
    if action.startswith("data."):
        op = _DATA_OPS.get(action[5:])
        if op:
            return f"{op} en {TABLE_LABELS.get(entity_type or '', entity_type or 'datos')}"
    return action


def _fecha(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S") if dt else ""


def _fmt(value) -> str:
    """Valor de una celda antes/después: escalares tal cual, estructuras en JSON."""
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def _filters(*, desde, hasta, module, action, who, student, process_id, q, data):
    """Parsea los crudos a un dict normalizado (lo que la plantilla repinta)."""
    from itcj2.apps.titulatec.services.audit_actions import AUDIT_MODULES

    return {
        "desde": desde,
        "hasta": hasta,
        "module": module if module in AUDIT_MODULES else "",
        "action": action if action in _catalogo_acciones() else "",
        "who": normalize_q(who) or "",
        "student": normalize_q(student) or "",
        "process_id": _int(process_id),
        "q": normalize_q(q) or "",
        "data": data == "1",
    }


def _process_control(db, process_id: int | None) -> str | None:
    """Nº de control del alumno de un proceso (una consulta), o `None`."""
    if process_id is None:
        return None
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess

    control = (db.query(User.control_number)
               .join(TitulationProcess, TitulationProcess.student_id == User.id)
               .filter(TitulationProcess.id == process_id).scalar())
    control = (control or "").strip()
    return control or None


def _predicates(f: dict, *, process_control: str | None = None) -> list:
    """Predicados SQL de los filtros. `process_control` es el nº de control del
    alumno de `f["process_id"]` (lo resuelve `_body_ctx`)."""
    from sqlalchemy import and_, func, or_, select

    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog as A

    out = []
    d0, d1 = _date(f["desde"]), _date(f["hasta"])
    if d0 is not None:
        out.append(A.occurred_at >= d0)
    if d1 is not None:
        out.append(A.occurred_at < d1 + timedelta(days=1))
    if f["module"]:
        out.append(A.module == f["module"])
    if f["action"]:
        out.append(A.action == f["action"])
    if f["process_id"] is not None:
        if process_control:
            # Lo de la SOLICITUD de inscripción (aprobar, rechazar, reabrir,
            # devolver, reenviar liga) pasó antes de que existiera el proceso:
            # no lleva `process_id`, pero su `subject_label` es «control ·
            # nombre» o el control solo (revisión final M4). Igualdad exacta o
            # control + espacio: un control más largo con el mismo prefijo no
            # entra.
            prefijo = like_pattern(process_control)[1:-1]   # escapado, sin los `%`
            previa = and_(A.process_id.is_(None), or_(
                A.subject_label == process_control,
                A.subject_label.like(prefijo + " %", escape="\\")))
            out.append(or_(A.process_id == f["process_id"], previa))
        else:
            out.append(A.process_id == f["process_id"])
    if not f["data"]:
        out.append(A.source != "data")

    def _like(col, text):
        return col.ilike(like_pattern(text), escape="\\")

    def _nombre(text):
        return or_(
            _like(func.concat_ws(" ", User.first_name, User.last_name, User.middle_name), text),
            _like(func.concat_ws(" ", User.last_name, User.middle_name, User.first_name), text),
        )

    if f["who"]:
        quien = select(User.id).where(or_(_nombre(f["who"]), _like(User.username, f["who"])))
        out.append(or_(A.actor_id.in_(quien), _like(A.actor_label, f["who"])))
    if f["student"]:
        # Nº de control, nombre o FOLIO del proceso: «Sobre qué» muestra el
        # folio primero, así que también se busca por él.
        alumnos = (select(TitulationProcess.id)
                   .join(User, User.id == TitulationProcess.student_id)
                   .where(or_(_like(User.control_number, f["student"]), _nombre(f["student"]),
                              _like(TitulationProcess.folio, f["student"]))))
        out.append(or_(A.process_id.in_(alumnos), _like(A.subject_label, f["student"])))
    if f["q"]:
        out.append(_like(A.reason, f["q"]))
    return out


def _body_ctx(db, *, user_id: int, f: dict, page, per_page: int = PAGE_SIZE) -> dict:
    """Contexto compartido por la página y el parcial. `rows` son dicts planos
    (la plantilla se pinta después del `db.close()` de la ruta); actores y
    procesos se cargan por lote, nunca uno por fila."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog as A
    from itcj2.apps.titulatec.pages.mail_admin import _process_opener
    from itcj2.apps.titulatec.services.audit_actions import AUDIT_MODULES, TABLE_LABELS

    preds = _predicates(f, process_control=_process_control(db, f["process_id"]))
    query = (db.query(A).filter(*preds)
             .order_by(A.occurred_at.desc(), A.id.desc()))
    pagina = paginate_query(query, parse_page(page), per_page)
    filas = pagina.items

    actor_ids = {r.actor_id for r in filas if r.actor_id is not None and r.actor_kind == "user"}
    proc_ids = {r.process_id for r in filas if r.process_id is not None}
    usuarios = ({u.id: u for u in db.query(User).filter(User.id.in_(actor_ids)).all()}
                if actor_ids else {})
    procesos = ({p.id: p for p in db.query(TitulationProcess)
                 .filter(TitulationProcess.id.in_(proc_ids)).all()} if proc_ids else {})
    alumnos = {}
    sids = {p.student_id for p in procesos.values() if p.student_id is not None}
    if sids:
        alumnos = {u.id: u for u in db.query(User).filter(User.id.in_(sids)).all()}
    puede_abrir = _process_opener(db, user_id) if procesos else (lambda _p: False)

    rows = []
    for r in filas:
        u = usuarios.get(r.actor_id)
        if r.actor_kind == "user":
            actor = u.full_name if u is not None else (
                f"Usuario #{r.actor_id}" if r.actor_id is not None else "—")
            badge = ""
        else:
            actor = r.actor_label or _KIND_BADGES.get(r.actor_kind, r.actor_kind)
            badge = _KIND_BADGES.get(r.actor_kind, r.actor_kind)
        proc = procesos.get(r.process_id)
        alumno = alumnos.get(proc.student_id) if proc is not None else None
        if r.subject_label:
            sobre = r.subject_label
        elif proc is not None:
            sobre = f"{proc.folio} · {alumno.full_name}" if alumno is not None else proc.folio
        elif r.entity_type:
            sobre = TABLE_LABELS.get(r.entity_type, r.entity_type)
            if r.entity_id is not None:
                sobre = f"{sobre} #{r.entity_id}"
        else:
            sobre = ""
        reason = r.reason or ""
        rows.append({
            "id": r.id,
            "when": _fecha(r.occurred_at),
            "actor": actor,
            "badge": badge,
            "module": AUDIT_MODULES.get(r.module, r.module),
            "label": _label(r.action, r.entity_type),
            "is_data": r.source == "data",
            "about": sobre,
            "process_url": (f"/titulatec/admin/processes/{proc.id}?from=/titulatec/admin/bitacora"
                            if proc is not None and puede_abrir(proc) else ""),
            "reason": reason if len(reason) <= _REASON_CLIP else reason[:_REASON_CLIP - 1] + "…",
        })
    return {
        "rows": rows,
        "page": Page(items=rows, total=pagina.total, page=pagina.page, per_page=per_page),
        "f": f,
    }


def _page_ctx(db, **kw) -> dict:
    """Contexto de la página: el del parcial + los catálogos de los selects."""
    from itcj2.apps.titulatec.services.audit_actions import AUDIT_MODULES

    ctx = _body_ctx(db, **kw)
    grupos: dict[str, list] = {}
    for code, (mod, label) in sorted(_catalogo_acciones().items(), key=lambda kv: kv[1][1]):
        grupos.setdefault(mod, []).append((code, label))
    ctx["modules"] = sorted(AUDIT_MODULES.items(), key=lambda kv: kv[1])
    ctx["action_groups"] = [(AUDIT_MODULES.get(m, m), items)
                            for m, items in sorted(grupos.items(),
                                                   key=lambda kv: AUDIT_MODULES.get(kv[0], kv[0]))]
    return ctx


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@router.get("", name="titulatec.pages.audit.list")
def list_audit(request: Request, desde: str | None = None, hasta: str | None = None,
               module: str = "", action: str = "", who: str = "", student: str = "",
               process_id: str = "", q: str = "", data: str = "", page: str = "",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    if desde is None and hasta is None and _int(process_id) is None:
        # Sin rango pedido ni expediente: últimos 7 días. Con `process_id` (la
        # liga del expediente) NO hay ventana: se ve todo su historial. El
        # parcial, en cambio, respeta el vacío.
        desde = (db_now() - timedelta(days=_DEFAULT_DAYS)).strftime("%Y-%m-%d")
    f = _filters(desde=desde or "", hasta=hasta or "", module=module, action=action,
                 who=who, student=student, process_id=process_id, q=q, data=data)
    db = SessionLocal()
    try:
        ctx = _page_ctx(db, user_id=int(user["sub"]), f=f, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/audit_log.html", ctx)


@router.get("/body", name="titulatec.pages.audit.body")
def body(request: Request, desde: str = "", hasta: str = "", module: str = "",
         action: str = "", who: str = "", student: str = "", process_id: str = "",
         q: str = "", data: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: LOS MISMOS query params, devuelve solo resultados."""
    from itcj2.database import SessionLocal

    f = _filters(desde=desde, hasta=hasta, module=module, action=action, who=who,
                 student=student, process_id=process_id, q=q, data=data)
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), f=f, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/audit_log_body.html", ctx)


def _entry_ctx(db, entry_id: int) -> dict | None:
    from sqlalchemy import func  # noqa: F401
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models.audit_log import TitulatecAuditLog as A
    from itcj2.apps.titulatec.services.audit_actions import AUDIT_MODULES

    r = db.get(A, entry_id)
    if r is None:
        return None
    actor = r.actor_label or ""
    if r.actor_kind == "user" and r.actor_id is not None:
        u = db.get(User, r.actor_id)
        actor = u.full_name if u is not None else f"Usuario #{r.actor_id}"
    antes, despues = r.before or {}, r.after or {}
    if not isinstance(antes, dict):
        antes = {"valor": antes}
    if not isinstance(despues, dict):
        despues = {"valor": despues}
    campos = [{"name": k, "before": _fmt(antes.get(k)) if k in antes else "",
               "after": _fmt(despues.get(k)) if k in despues else ""}
              for k in sorted(set(antes) | set(despues))]
    hermanas = []
    if r.request_id:
        for s in (db.query(A).filter(A.request_id == r.request_id, A.id != r.id)
                  .order_by(A.occurred_at.asc(), A.id.asc()).limit(_SIBLINGS_MAX).all()):
            hermanas.append({"id": s.id, "when": _fecha(s.occurred_at),
                             "label": _label(s.action, s.entity_type)})
    payload = None
    if r.payload not in (None, {}, []):
        payload = json.dumps(r.payload, ensure_ascii=False, indent=2, default=str)
    return {
        "e": {
            "id": r.id, "when": _fecha(r.occurred_at), "label": _label(r.action, r.entity_type),
            "action": r.action, "source": r.source, "module": AUDIT_MODULES.get(r.module, r.module),
            "actor": actor or "—", "actor_kind": _KIND_BADGES.get(r.actor_kind, ""),
            "entity": (f"{r.entity_type} #{r.entity_id}" if r.entity_type and r.entity_id is not None
                       else (r.entity_type or "")),
            "subject": r.subject_label or "", "process_id": r.process_id,
            "reason": r.reason or "", "ip": r.ip or "", "user_agent": r.user_agent or "",
            "route": r.route or "", "request_id": r.request_id or "",
        },
        "fields": campos,
        "payload": payload,
        "siblings": hermanas,
    }


@router.get("/entry/{entry_id}", name="titulatec.pages.audit.entry")
def entry(entry_id: int, request: Request,
          user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal

    if not 1 <= entry_id <= _BIGINT_MAX:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    db = SessionLocal()
    try:
        ctx = _entry_ctx(db, entry_id)
    finally:
        db.close()
    if ctx is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return render_titulatec(request, "titulatec/admin/partials/audit_log_entry.html", ctx)

"""Pestaña «Correos»: la bandeja de salida (`titulatec_email_outbox`), SOLO LECTURA.

Para el rol `admin` de TitulaTec (permiso `titulatec.email_outbox.page.list`,
`database/DML/titulatec/outbox_2026_10/24`, `titulatec init-outbox-admin`).
Muestra lo que la bitácora del expediente (`pages/admin.py::_bitacora_correos`)
muestra por alumno, pero de toda la plataforma: qué correo, a quién, cuándo,
cuántos intentos y por qué falló.

Pestañas por `EmailOutbox.status`: Pendientes (`pending`, la cola: primero lo
que sale antes), Entregados (`sent`), Fallidos (`failed`), Descartados
(`no_recipient` + `obsolete`: el despachador decidió no mandarlo) y Todos.
Paginada en servidor (`utils/paging`, 50 por página), con búsqueda en servidor
(destinatario, asunto, número de control, nombre o correo del alumno o de la
solicitud, folio) y filtro por tipo de correo.

NO HACE NADA: ni reintentar ni reenviar ni descartar (decisión del dueño,
2026-10-06). Solo el despachador (`mail_dispatch.py`) cambia el `status` de una
fila, y esta página no es la excepción. Tampoco pinta el `payload`: son los
hechos congelados del evento (motivos, nombres) y no son de esta vista.

Cubre SOLO lo que pasa por el outbox: los correos con secreto (liga de
activación, NIP) salen en línea y nunca llegan a esta tabla (regla del
outbox, `models/email_outbox.py`).

Una fila por AVISO, no por correo: un grupo (`group_key`, D7) que salió junto
aparece como varias filas con el mismo `sent_at` y destinatario. La bitácora
del expediente sí los junta; aquí cada aviso es auditable por separado.
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.utils.paging import (
    PAGE_SIZE, Page, like_pattern, normalize_q, paginate_query, parse_page,
)

logger = logging.getLogger("itcj2.apps.titulatec.pages.mail_admin")
router = APIRouter(prefix="/admin/correos", tags=["titulatec-pages-mail"])

_LIST = ["titulatec.email_outbox.page.list"]

# Pestañas, en el orden en que se pintan.
_TABS = (
    ("pending", "Pendientes"),
    ("sent", "Entregados"),
    ("failed", "Fallidos"),
    ("discarded", "Descartados"),
    ("all", "Todos"),
)
# Estados de cada pestaña; `None` = sin filtro. Dominio: `OUTBOX_STATUSES`.
_TAB_STATUSES = {
    "pending": ("pending",),
    "sent": ("sent",),
    "failed": ("failed",),
    "discarded": ("no_recipient", "obsolete"),
    "all": None,
}
_DEFAULT_TAB = "pending"


def _tab(raw) -> str:
    """La pestaña pedida, o «Pendientes». Nunca un filtro arbitrario."""
    return raw if isinstance(raw, str) and raw in _TAB_STATUSES else _DEFAULT_TAB


def _kind(raw) -> str | None:
    """El tipo pedido si es del catálogo; si no, sin filtro."""
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS

    return raw if isinstance(raw, str) and raw in OUTBOX_KINDS else None


def _fecha(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def _search_filter(q: str):
    """Predicado de búsqueda: destinatario, asunto, alumno (control, nombre,
    correo), solicitud (control, nombre, correo personal) o folio del proceso.

    Subconsultas `IN (SELECT id ...)` y no JOINs: una fila del outbox cuelga de
    un alumno O de una solicitud, y un JOIN externo a las dos duplicaría la
    cuenta del paginador."""
    from sqlalchemy import func, or_, select

    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import EmailOutbox, EnrollmentRequest, TitulationProcess

    p = like_pattern(q)

    def _like(col):
        return col.ilike(p, escape="\\")

    alumnos = select(User.id).where(or_(
        _like(User.control_number),
        _like(User.email),
        _like(func.concat_ws(" ", User.first_name, User.last_name, User.middle_name)),
        _like(func.concat_ws(" ", User.last_name, User.middle_name, User.first_name)),
    ))
    er = EnrollmentRequest
    solicitudes = select(er.id).where(or_(
        _like(er.control_number),
        _like(er.contact_email),
        _like(func.concat_ws(" ", er.first_name, er.last_name, er.middle_name)),
        _like(func.concat_ws(" ", er.last_name, er.middle_name, er.first_name)),
    ))
    procesos = select(TitulationProcess.id).where(_like(TitulationProcess.folio))
    return or_(
        _like(EmailOutbox.sent_to),
        _like(EmailOutbox.subject),
        EmailOutbox.user_id.in_(alumnos),
        EmailOutbox.enrollment_request_id.in_(solicitudes),
        EmailOutbox.process_id.in_(procesos),
    )


def _process_opener(db, user_id: int):
    """Predicado `proc -> bool`: ¿la fila liga al expediente? Solo si el actor
    puede abrirlo, con la MISMA regla que el expediente: algún permiso de vista
    de procesos (`pages/admin.py::_PROCESS_VIEW_PERMS`) y el proceso en su
    alcance (`scope_service.process_in_scope`, aquí sin un `db.get` por fila).
    Una liga que responde 404 es peor que no tenerla."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.apps.titulatec.pages.admin import _PROCESS_VIEW_PERMS
    from itcj2.apps.titulatec.services.scope_service import (
        can_see_unmapped, officer_programs,
    )

    if not (set(_PROCESS_VIEW_PERMS) & cached_perms(db, user_id, "titulatec")):
        return lambda _proc: False
    scope = officer_programs(db, user_id)
    unmapped = can_see_unmapped(db, user_id)

    def _can(proc) -> bool:
        if proc is None:
            return False
        if proc.program_id is None:
            return unmapped
        return scope == "ALL" or proc.program_id in scope

    return _can


def _body_ctx(db, *, user_id: int, status, kind, q=None, page=1,
              per_page: int = PAGE_SIZE) -> dict:
    """Contexto del parcial. `rows` son dicts PLANOS (la plantilla se pinta
    después del `db.close()` de la ruta).

    `tab_counts` = filas por pestaña con la MISMA búsqueda y el mismo tipo que
    la lista (un `GROUP BY status`); la pestaña no filtra su propio contador.
    Alumnos, solicitudes y procesos se cargan por lote (nunca uno por fila).
    """
    from sqlalchemy import func

    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import EmailOutbox, EnrollmentRequest, TitulationProcess
    from itcj2.apps.titulatec.models.email_outbox import ENROLLMENT_KINDS
    from itcj2.apps.titulatec.pages.admin import (
        _MAIL_STATUS_UI, _SIN_DESTINATARIO_INSCRIPCION,
    )
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    tab = _tab(status)
    kind = _kind(kind)
    q = normalize_q(q)
    page = parse_page(page)

    filtros = []
    if kind:
        filtros.append(EmailOutbox.kind == kind)
    if q:
        filtros.append(_search_filter(q))

    # Contadores por pestaña: el universo filtrado por tipo y búsqueda.
    por_estado = dict(
        db.query(EmailOutbox.status, func.count(EmailOutbox.id))
        .filter(*filtros)
        .group_by(EmailOutbox.status)
        .all()
    )
    tab_counts = {}
    for key, _label in _TABS:
        estados = _TAB_STATUSES[key]
        tab_counts[key] = (sum(por_estado.values()) if estados is None
                           else sum(por_estado.get(s, 0) for s in estados))

    query = db.query(EmailOutbox).filter(*filtros)
    estados = _TAB_STATUSES[tab]
    if estados is not None:
        query = query.filter(EmailOutbox.status.in_(estados))
    if tab == "pending":
        # La cola: primero lo que sale antes (el despachador toma por
        # `not_before`). Desempate por `id`, regla del paginador.
        query = query.order_by(EmailOutbox.not_before.asc(), EmailOutbox.id.asc())
    else:
        query = query.order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc())
    pagina = paginate_query(query, page, per_page)
    filas = pagina.items

    user_ids = {f.user_id for f in filas if f.user_id is not None}
    req_ids = {f.enrollment_request_id for f in filas if f.enrollment_request_id is not None}
    proc_ids = {f.process_id for f in filas if f.process_id is not None}
    usuarios = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
                if user_ids else {})
    solicitudes = ({r.id: r for r in db.query(EnrollmentRequest)
                    .filter(EnrollmentRequest.id.in_(req_ids)).all()} if req_ids else {})
    procesos = ({p.id: p for p in db.query(TitulationProcess)
                 .filter(TitulationProcess.id.in_(proc_ids)).all()} if proc_ids else {})
    puede_abrir = _process_opener(db, user_id) if procesos else (lambda _p: False)

    rows = []
    for f in filas:
        u = usuarios.get(f.user_id)
        r = solicitudes.get(f.enrollment_request_id)
        proc = procesos.get(f.process_id)
        if u is not None:
            who = {"name": u.full_name, "control": u.control_number or "", "request": False}
        elif r is not None:
            who = {"name": " ".join(x for x in (r.last_name, r.middle_name, r.first_name) if x),
                   "control": r.control_number or "", "request": True}
        else:
            who = {"name": "—", "control": "", "request": False}
        etiqueta, tono = _MAIL_STATUS_UI.get(f.status, (f.status, "neutral"))
        if f.status == "no_recipient" and f.kind in ENROLLMENT_KINDS:
            etiqueta = _SIN_DESTINATARIO_INSCRIPCION
        rows.append({
            "id": f.id,
            "kind_label": StudentMail.KIND_LABELS.get(f.kind, f.kind),
            "who": who,
            "folio": proc.folio if proc is not None else "",
            "process_url": (f"/titulatec/admin/processes/{proc.id}?from=/titulatec/admin/correos"
                            if puede_abrir(proc) else ""),
            "to": f.sent_to or "",
            "subject": f.subject or "",
            "attempts": f.attempts or 0,
            "error": f.last_error or "",
            "status": f.status,
            "status_label": etiqueta,
            "tone": tono,
            "created": _fecha(f.created_at),
            # Programado: solo si la cola lo retiene más allá del alta (espera
            # del grupo, D7, o un recordatorio a futuro).
            "scheduled": (_fecha(f.not_before)
                          if f.status == "pending" and f.not_before and f.created_at
                          and f.not_before > f.created_at else ""),
            "sent": _fecha(f.sent_at),
            "grouped": f.group_key is not None,
        })

    kinds = sorted(StudentMail.KIND_LABELS.items(), key=lambda kv: kv[1])
    return {
        "rows": rows,
        "page": Page(items=rows, total=pagina.total, page=pagina.page, per_page=per_page),
        "status": tab,
        "tabs": _TABS,
        "tab_counts": tab_counts,
        "kind": kind or "",
        "kinds": kinds,
        "q": q or "",
    }


@router.get("", name="titulatec.pages.mail.list")
def list_mail(request: Request, status: str = "", kind: str = "", q: str = "",
              page: str = "",
              user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status, kind=kind,
                        q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/mail_outbox.html", ctx)


@router.get("/body", name="titulatec.pages.mail.body")
def body(request: Request, status: str = "", kind: str = "", q: str = "",
         page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status, kind=kind,
                        q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/mail_outbox_body.html", ctx)

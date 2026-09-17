"""Bandeja de solicitudes de auto-inscripción (Servicios Escolares).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja entera.

Pestañas por estado, «Por revisar» por omisión. Aprobar, rechazar y reenviar
vuelven a pintar la pestaña donde estaba el oficial: cada formulario de fila la
manda de vuelta en `status` y `cohort_id`. Flujo completo en
`docs/flows/xcut_public_enrollment.md`.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.requests_admin")
router = APIRouter(prefix="/admin/solicitudes", tags=["titulatec-pages-requests"])

_LIST = ["titulatec.enrollment_request.page.list"]
_APPROVE = ["titulatec.enrollment_request.api.approve"]
_REJECT = ["titulatec.enrollment_request.api.reject"]

# Pestañas, en el orden en que se pintan.
_TABS = (
    ("pending_review", "Por revisar"),
    ("approved", "Liga enviada"),
    ("converted", "Inscritas"),
    ("rejected", "Rechazadas"),
    ("all", "Todas"),
)
# Estados de cada pestaña; `None` = sin filtro. «Por revisar» incluye el legado
# (`unverified`, `verified`): `EnrollmentRequestService.approve` lo aprueba y lo
# rechaza igual que `pending_review`.
_TAB_STATUSES = {
    "pending_review": ("pending_review", "unverified", "verified"),
    "approved": ("approved",),
    "converted": ("converted",),
    "rejected": ("rejected",),
    "all": None,
}
_DEFAULT_TAB = "pending_review"
# Etiqueta de la fila en «Todas», donde conviven estados.
_STATUS_LABELS = {
    "pending_review": "Por revisar",
    "unverified": "Por revisar · anterior",
    "verified": "Por revisar · anterior",
    "approved": "Liga enviada",
    "converted": "Inscrita",
    "rejected": "Rechazada",
}


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo del de `pages/admin.py:647`; `titulatec-utils.js::decodeHeaderMsg` lo
    deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _tab(raw) -> str:
    """La pestaña pedida, o «Por revisar». Nunca un filtro arbitrario."""
    return raw if isinstance(raw, str) and raw in _TAB_STATUSES else _DEFAULT_TAB


def _officer_scope(db, user_id: int):
    """Alcance del actor ('ALL' o `set[int]`). Import local, evita ciclos."""
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    return officer_programs(db, user_id)


def _program_in_scope(scope, program_id) -> bool:
    """Mismo criterio que `scope_service.process_in_scope`: 'ALL' pasa todo; un
    set vacío o parcial solo deja pasar un `program_id` que esté en él. `None`
    NUNCA pasa para un actor acotado — coincide con el `IN (...)` del listado,
    que ya descarta NULLs con UNKNOWN (la solicitud sin carrera solo la
    resuelve quien tiene alcance total).
    """
    return scope == "ALL" or (program_id is not None and program_id in scope)


def _load_scoped_request(db, scope, req_id: int):
    """Carga la solicitud solo si `scope` alcanza su `program_id`.

    Devuelve `None` tanto si no existe como si existe pero está fuera de
    alcance (Finding 1, ronda 1 de revisión): la ruta responde 404 liso, sin
    detalle, así que "no existe" y "no es tuya" son indistinguibles.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest

    req = db.get(EnrollmentRequest, req_id)
    if req is None:
        return None
    return req if _program_in_scope(scope, req.program_id) else None


def _body_ctx(db, *, user_id: int, status, cohort_id):
    """Contexto del parcial. Distingue los DOS vacíos (riesgo 3 del diseño).

    «¿Tiene cuenta?» se calcula aquí igual que en `approve()`: el número de
    control contra `core_users`, HOY. Si la bandeja y el servicio se separan, la
    fila promete un NIP que no se aplica o esconde una liga que sí sale.
    """
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest, TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    tab = _tab(status)
    scope = _officer_scope(db, user_id)
    ctx = {"rows": [], "status": tab, "tabs": _TABS, "cohort_id": cohort_id,
           "programs": [], "no_programs": False,
           "kpis": {"total": 0, "review": 0, "sent": 0, "converted": 0, "rejected": 0},
           "by_year": [], "year_max": 0}

    if scope != "ALL" and not scope:
        # Conjunto vacío = no ve nada, EN SILENCIO. Se marca explícitamente para
        # que la plantilla no muestre "no hay solicitudes" (ni KPIs: no hay
        # universo que contar).
        ctx["no_programs"] = True
        return ctx

    # KPIs y "por año de ingreso": MISMO alcance y convocatoria que el listado de
    # abajo, pero sin filtro de pestaña ni el límite de 300 — es el universo
    # completo, no la página visible.
    stats = EnrollmentRequestService.stats(db, scope=scope, cohort_id=cohort_id)
    ctx["kpis"] = stats["counts"]
    ctx["by_year"] = stats["by_year"]
    ctx["year_max"] = stats["year_max"]

    # El <select> del formulario de aprobar solo puede ofrecer carreras que la
    # ruta vaya a aceptar (Finding 1, ronda 1 de revisión).
    programs_q = db.query(Program).order_by(Program.name)
    if scope != "ALL":
        programs_q = programs_q.filter(Program.id.in_(scope))
    programs = [{"id": p.id, "name": p.name} for p in programs_q.all()]
    ctx["programs"] = programs

    q = db.query(EnrollmentRequest)
    if scope != "ALL":
        # Una solicitud sin `program_id` (carrera en texto libre) solo la ve
        # quien tiene alcance total: resolverla es justo lo que hace el jefe.
        q = q.filter(EnrollmentRequest.program_id.in_(scope))
    if _TAB_STATUSES[tab] is not None:
        q = q.filter(EnrollmentRequest.status.in_(_TAB_STATUSES[tab]))
    if cohort_id:
        q = q.filter(EnrollmentRequest.cohort_id == cohort_id)

    reqs = q.order_by(EnrollmentRequest.created_at.desc(),
                      EnrollmentRequest.id.desc()).limit(300).all()

    # Cuentas, folios y convocatorias en una consulta cada uno: un `db.get` por
    # fila sería N+1.
    controls = {r.control_number for r in reqs if r.control_number}
    users = ({u.control_number: u for u in db.query(User)
              .filter(User.control_number.in_(controls)).all()} if controls else {})
    pids = {r.converted_process_id for r in reqs if r.converted_process_id}
    folios = (dict(db.query(TitulationProcess.id, TitulationProcess.folio)
                   .filter(TitulationProcess.id.in_(pids)).all()) if pids else {})
    cohort_ids = {r.cohort_id for r in reqs}
    coh_names = (dict(db.query(Cohort.id, Cohort.name)
                      .filter(Cohort.id.in_(cohort_ids)).all()) if cohort_ids else {})
    prog_names = {p["id"]: p["name"] for p in programs}

    # «Rechazada antes» (riesgo 4b): TODAS las `rejected` de estos controles, en
    # UNA consulta — nunca un `db.get`/query por fila (N+1). Acotada al MISMO
    # alcance por carrera que el listado: una rechazada fuera de alcance no debe
    # delatarse a un encargado que no podría verla por sí misma. Se agrupa por
    # control y, por fila, se descarta lo que no sea estrictamente ANTERIOR
    # (`id` menor) antes de quedarse con la más reciente — una solicitud no
    # puede ser "antecedente" de sí misma, y una `rejected` puede tener SU
    # PROPIO antecedente más viejo.
    rejected_by_control: dict[str, list] = {}
    if controls:
        pq = (db.query(EnrollmentRequest.id, EnrollmentRequest.control_number,
                       EnrollmentRequest.created_at, EnrollmentRequest.review_note)
              .filter(EnrollmentRequest.control_number.in_(controls),
                      EnrollmentRequest.status == "rejected"))
        if scope != "ALL":
            pq = pq.filter(EnrollmentRequest.program_id.in_(scope))
        for pid, control, created_at, note in pq.all():
            rejected_by_control.setdefault(control, []).append((created_at, pid, note))

    for r in reqs:
        u = users.get(r.control_number)
        anteriores = [c for c in rejected_by_control.get(r.control_number, ()) if c[1] < r.id]
        prior_reject = None
        if anteriores:
            p_created_at, _p_id, p_note = max(
                anteriores, key=lambda c: (c[0] or datetime.min, c[1]))
            prior_reject = {
                "date": p_created_at.strftime("%d/%m/%Y") if p_created_at else "",
                "note": p_note or "",
            }
        ctx["rows"].append({
            "id": r.id,
            "control": r.control_number,
            "name": " ".join(x for x in (r.last_name, r.middle_name, r.first_name) if x),
            "program": prog_names.get(r.program_id) or r.program_text or "",
            "program_id": r.program_id,
            "email": r.contact_email,
            "phone": r.phone,
            "cohort": coh_names.get(r.cohort_id, ""),
            "created": r.created_at.strftime("%d/%m/%Y") if r.created_at else "",
            "status": r.status,
            "status_label": _STATUS_LABELS.get(r.status, r.status),
            "reviewable": r.status in _TAB_STATUSES["pending_review"],
            "has_account": u is not None,
            "has_password": bool(u is not None and u.password_hash),
            # Abrir la liga la reactiva (excepción aprobada, 2026-09-15): el
            # oficial tiene que verlo ANTES de aprobar. La plantilla solo lo pinta
            # donde la liga todavía puede abrirse.
            "account_inactive": bool(u is not None and not u.is_active),
            "sends": r.verify_send_count or 0,
            "last_sent": (r.verify_sent_at.strftime("%d/%m/%Y %H:%M")
                          if r.verify_sent_at else ""),
            "opened": r.verified_at is not None,
            "folio": folios.get(r.converted_process_id, ""),
            "note": r.review_note or "",
            # Solo tiene sentido leerla en una fila `rejected`: el correo de
            # rechazo es lo único que sella esta columna (`reject()`).
            "rejection_sent": r.rejection_sent_at is not None,
            "prior_reject": prior_reject,
        })
    return ctx


@router.get("", name="titulatec.pages.requests.list")
async def list_requests(request: Request, status: str = "", cohort_id: str = "",
                        user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status,
                        cohort_id=_to_int(cohort_id))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/requests.html", ctx)


@router.get("/body", name="titulatec.pages.requests.body")
async def body(request: Request, status: str = "", cohort_id: str = "",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status,
                        cohort_id=_to_int(cohort_id))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/aprobar", name="titulatec.pages.requests.approve")
async def approve(req_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Aprueba. Sin cuenta, con el NIP que se captura; con cuenta, emitiendo la
    liga de activación (el NIP se ignora). El NIP NO aparece en ningún log ni
    cabecera."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    nip = (form.get("nip") or "").strip()
    program_id = _to_int((form.get("program_id") or "").strip())
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        # Alcance por carrera (Finding 1, ronda 1 de revisión): 404 liso, sin
        # `X-Tt-Error`, para que "no existe" y "no es tuya" sean indistinguibles.
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        if program_id and not _program_in_scope(scope, program_id):
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Esa carrera no está en tu alcance.")})
        try:
            ok, detail = EnrollmentRequestService.approve(
                db, req_id, nip=nip, program_id=program_id, actor_id=uid)
        except Exception:
            # `approve` es dueña de su transacción: un fallo real en cualquier
            # punto se deshace entero aquí, mismo patrón que `enroll_verify`
            # (`pages/public.py`). El NIP NUNCA se loguea, ni aquí ni abajo.
            logger.exception("aprobar: fallo inesperado al aprobar la solicitud")
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("aprobar: rollback fallido tras el error")
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "No pudimos completar la aprobación; intenta de nuevo.")})
        if not ok:
            # `detail` nunca contiene el NIP, y `approve` no deja nada escrito
            # cuando devuelve `(False, ...)` (invariante de su docstring).
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/rechazar", name="titulatec.pages.requests.reject")
async def reject(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Rechaza, o cancela una solicitud con la liga enviada. Motivo obligatorio:
    es lo que la persona lee en su correo."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    note = (form.get("note") or "").strip()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    if not note:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Escribe el motivo del rechazo: es lo que la persona lee.")})

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        if not EnrollmentRequestService.reject(db, req_id, note=note, actor_id=uid):
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("Esa solicitud ya se resolvió.")})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/reenviar", name="titulatec.pages.requests.resend")
async def resend(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Reenvío desde la bandeja: ROTA la liga de una solicitud aprobada.

    Aquí SÍ se identifica por id y se rota, porque el actor ya está autenticado
    y acotado por carrera; el veto al id y a rotar es del endpoint PÚBLICO.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        ok, detail = EnrollmentRequestService.resend_link(db, req_id)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)

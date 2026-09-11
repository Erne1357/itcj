"""Bandeja de solicitudes de auto-inscripción (Servicios Escolares).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja entera.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.requests_admin")
router = APIRouter(prefix="/admin/solicitudes", tags=["titulatec-pages-requests"])

_LIST = ["titulatec.enrollment_request.page.list"]
_APPROVE = ["titulatec.enrollment_request.api.approve"]
_REJECT = ["titulatec.enrollment_request.api.reject"]

_STATUSES = ("unverified", "verified", "pending_review", "approved",
             "rejected", "converted")


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


def _body_ctx(db, *, user_id: int, status: str, cohort_id):
    """Contexto del parcial. Distingue los DOS vacíos (riesgo 3 del diseño)."""
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    cohorts = [{"id": c.id, "name": c.name}
               for c in db.query(Cohort).order_by(Cohort.id.desc()).all()]
    programs = [{"id": p.id, "name": p.name}
                for p in db.query(Program).order_by(Program.name).all()]
    ctx = {"rows": [], "status": status or "", "cohort_id": cohort_id,
           "cohorts": cohorts, "programs": programs, "no_programs": False,
           "statuses": _STATUSES}

    scope = officer_programs(db, user_id)
    if scope != "ALL" and not scope:
        # Conjunto vacío = no ve nada, EN SILENCIO. Se marca explícitamente para
        # que la plantilla no muestre "no hay solicitudes".
        ctx["no_programs"] = True
        return ctx

    q = db.query(EnrollmentRequest)
    if scope != "ALL":
        # Una solicitud sin `program_id` (carrera en texto libre) solo la ve
        # quien tiene alcance total: resolverla es justo lo que hace el jefe.
        q = q.filter(EnrollmentRequest.program_id.in_(scope))
    if status:
        q = q.filter(EnrollmentRequest.status == status)
    if cohort_id:
        q = q.filter(EnrollmentRequest.cohort_id == cohort_id)

    reqs = q.order_by(EnrollmentRequest.created_at.desc(),
                      EnrollmentRequest.id.desc()).limit(300).all()

    # Perfil del alumno en una sola consulta: el correo personal verificado se
    # muestra por fila y un `db.get` por fila sería N+1.
    controls = {r.control_number for r in reqs if r.control_number}
    users = ({u.control_number: u for u in db.query(User)
              .filter(User.control_number.in_(controls)).all()} if controls else {})
    verified = set()
    if users:
        from itcj2.core.models.student_profile import StudentProfile
        verified = {p.user_id for p in db.query(StudentProfile)
                    .filter(StudentProfile.user_id.in_([u.id for u in users.values()]),
                            StudentProfile.contact_email_verified_at.isnot(None)).all()}

    # Folio del proceso creado: una sola consulta para todas las filas resueltas.
    # Un `db.get` por fila reintroduciría el N+1 que el prefetch de arriba evita.
    pids = {r.converted_process_id for r in reqs if r.converted_process_id}
    folios = {}
    if pids:
        from itcj2.apps.titulatec.models import TitulationProcess
        folios = dict(db.query(TitulationProcess.id, TitulationProcess.folio)
                        .filter(TitulationProcess.id.in_(pids)).all())

    prog_names = {p["id"]: p["name"] for p in programs}
    coh_names = {c["id"]: c["name"] for c in cohorts}
    for r in reqs:
        u = users.get(r.control_number)
        ctx["rows"].append({
            "id": r.id,
            "control": r.control_number,
            "name": " ".join(x for x in (r.last_name, r.middle_name, r.first_name) if x),
            "email": r.contact_email,
            "phone": r.phone,
            "kind": r.kind,
            "status": r.status,
            "cohort": coh_names.get(r.cohort_id, ""),
            "program": prog_names.get(r.program_id) or r.program_text or "",
            "program_id": r.program_id,
            "has_efirma": r.has_efirma,
            "sends": r.verify_send_count or 0,
            "mail_sent": r.verify_sent_at is not None,
            "contact_verified": bool(u is not None and u.id in verified),
            "folio": folios.get(r.converted_process_id, ""),
            "note": r.review_note or "",
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
    """Aprueba capturando el NIP. El NIP NO aparece en ningún log ni cabecera."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    nip = (form.get("nip") or "").strip()
    program_id = _to_int((form.get("program_id") or "").strip())

    db = SessionLocal()
    try:
        ok, detail = EnrollmentRequestService.approve(
            db, req_id, nip=nip, program_id=program_id, actor_id=int(user["sub"]))
        if not ok:
            # `detail` nunca contiene el NIP: `approve` solo devuelve motivos.
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=int(user["sub"]), status="", cohort_id=None)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/rechazar", name="titulatec.pages.requests.reject")
async def reject(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    note = (form.get("note") or "").strip()
    if not note:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Escribe el motivo del rechazo: es lo que la persona lee.")})

    db = SessionLocal()
    try:
        if not EnrollmentRequestService.reject(db, req_id, note=note,
                                               actor_id=int(user["sub"])):
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("Esa solicitud ya se resolvió.")})
        ctx = _body_ctx(db, user_id=int(user["sub"]), status="", cohort_id=None)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/reenviar", name="titulatec.pages.requests.resend")
async def resend(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Reenvío desde la bandeja: aquí SÍ se identifica por id, porque el actor ya
    está autenticado y autorizado — el veto al id es del endpoint PÚBLICO."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    db = SessionLocal()
    try:
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return Response(status_code=404)
        EnrollmentRequestService._send_verify(db, req)
        ctx = _body_ctx(db, user_id=int(user["sub"]), status="", cohort_id=None)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)

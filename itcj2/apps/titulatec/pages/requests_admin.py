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
    alcance (Finding 1, ronda 1 de revisión): la ausencia es indistinguible
    del rechazo, para que la ruta no sea oráculo de existencia — mismo
    criterio que `scope_service.assert_process_in_scope`, pero en 404 liso,
    sin detalle.
    """
    from itcj2.apps.titulatec.models import EnrollmentRequest

    req = db.get(EnrollmentRequest, req_id)
    if req is None:
        return None
    return req if _program_in_scope(scope, req.program_id) else None


def _body_ctx(db, *, user_id: int, status: str, cohort_id):
    """Contexto del parcial. Distingue los DOS vacíos (riesgo 3 del diseño)."""
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest

    cohorts = [{"id": c.id, "name": c.name}
               for c in db.query(Cohort).order_by(Cohort.id.desc()).all()]

    scope = _officer_scope(db, user_id)
    ctx = {"rows": [], "status": status or "", "cohort_id": cohort_id,
           "cohorts": cohorts, "programs": [], "no_programs": False,
           "statuses": _STATUSES}

    if scope != "ALL" and not scope:
        # Conjunto vacío = no ve nada, EN SILENCIO. Se marca explícitamente para
        # que la plantilla no muestre "no hay solicitudes".
        ctx["no_programs"] = True
        return ctx

    # El <select> del formulario de aprobar solo puede ofrecer carreras que la
    # ruta vaya a aceptar (Finding 1, ronda 1 de revisión): si no, el
    # formulario promete algo que `_program_in_scope` rechazaría en el POST.
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
    # {user_id -> correo que TIENE SELLO}. Antes era un set de "este perfil
    # tiene sello", sin mirar la dirección: una persona que verificó un correo
    # en la convocatoria A y se reinscribe con otro en la B veía su correo
    # NUEVO —jamás confirmado— con la palomita verde. La palomita tiene que
    # hablar del correo que está a su lado (B2 de la revisión final).
    verified = {}
    if users:
        from itcj2.core.models.student_profile import StudentProfile
        verified = {p.user_id: (p.contact_email or "").strip().lower()
                    for p in db.query(StudentProfile)
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
        # Prueba del buzón INSTITUCIONAL: el mismo predicado que usa
        # `EnrollmentRequestService.approve` para decidir qué puede escribir
        # sobre una cuenta preexistente. Si los dos se separan, la bandeja
        # vuelve a prometer lo que el servicio no hace.
        prueba_institucional = r.kind == "known" and r.verified_at is not None
        # ¿El NIP que teclee el oficial será de verdad la contraseña? Solo si no
        # hay cuenta todavía, o si la hay sin `password_hash` Y con prueba
        # institucional. En los demás casos `approve` preserva lo que exista y
        # avisa por folio: el oficial tiene que saberlo ANTES de teclearlo.
        nip_aplica = u is None or (not u.password_hash and prueba_institucional)
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
            "contact_verified": bool(
                u is not None and (r.contact_email or "").strip()
                and verified.get(u.id) == (r.contact_email or "").strip().lower()),
            "verified": r.verified_at is not None,
            "institutional_proof": prueba_institucional,
            "nip_aplica": nip_aplica,
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
        uid = int(user["sub"])
        # Alcance por carrera (Finding 1, ronda 1 de revisión): antes de esto,
        # `api.approve` por sí solo aprobaba cualquier `req_id`, aunque la
        # bandeja ya lo hubiera ocultado por carrera. 404 liso, sin
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
            # `approve` es dueña de su transacción end-to-end (Finding 2, ronda
            # 1 de revisión: `import_rows` ya no commitea por su cuenta) — un
            # fallo real en cualquier punto se deshace entero aquí, mismo
            # patrón que `enroll_verify` (`pages/public.py`). El NIP NUNCA se
            # loguea, ni aquí ni en el mensaje que sigue.
            logger.exception("aprobar: fallo inesperado al aprobar la solicitud")
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                logger.warning("aprobar: rollback fallido tras el error")
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "No pudimos completar la aprobación; intenta de nuevo.")})
        if not ok:
            # `detail` nunca contiene el NIP: `approve` solo devuelve motivos.
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=uid, status="", cohort_id=None)
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
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        if not EnrollmentRequestService.reject(db, req_id, note=note, actor_id=uid):
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("Esa solicitud ya se resolvió.")})
        ctx = _body_ctx(db, user_id=uid, status="", cohort_id=None)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/reenviar", name="titulatec.pages.requests.resend")
async def resend(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Reenvío desde la bandeja: aquí SÍ se identifica por id, porque el actor ya
    está autenticado y autorizado — el veto al id es del endpoint PÚBLICO."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        req = _load_scoped_request(db, scope, req_id)
        if req is None:
            return Response(status_code=404)
        EnrollmentRequestService._send_verify(db, req)
        ctx = _body_ctx(db, user_id=uid, status="", cohort_id=None)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)

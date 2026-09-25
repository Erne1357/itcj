"""Bandeja «Accesos» de Centro de Cómputo (spec 2026-09-24 §8.2).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la acción entera.

Centro de Cómputo (CC) NO tiene alcance por carrera: ve todas las solicitudes
(patrón GTV, `survey_reviews_admin.py`), nunca usa `officer_programs`.

Modo (`EnrollmentRequestService.reviewer_mode()`):

- OFICIAL (`school_services`): SE aprueba y la solicitud sin cuenta llega aquí
  (`awaiting_access`). CC da el NIP (`grant_access`; si entretanto apareció una
  cuenta, se desvía a la liga — D10), la devuelve a SE con nota
  (`return_to_review`) o reasigna el NIP de una cuenta que nunca ha iniciado
  sesión (D8), con o sin correo.
  Pestañas: Por dar acceso · Con acceso · Devueltas.
- ALTERNO (`computer_center`): CC revisa todo. «Dar acceso» sobre una
  `pending_review` (o legado) APRUEBA (`approve`, con NIP si no hay cuenta, liga
  si la hay) y sobre una `awaiting_access` sobrante da el acceso
  (`grant_access`); además rechaza y reenvía la liga. Pestañas de revisión.

«Dar acceso» y «Reasignar NIP» responden el parcial con un aviso `X-Tt-Notice`
(folio y si el correo salió, `_grant_notice`): la fila sale de la pestaña en
que estaba CC y sin él no sabría si tiene que dictar el NIP.

Una acción que no es del modo responde 400 + `X-Tt-Error` ANTES de abrir sesión
(`_mode_block`): ni un POST directo sin la UI la ejecuta. Solicitud
inexistente = 404 liso. El NIP jamás vuelve al navegador ni a un log: el
formulario lo manda, el servicio lo usa y aquí no se lee más que para pasarlo.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
# Estados «por revisar» (incluido el legado): los del servicio, nunca una copia
# que se desincronice el día que el servicio sume uno.
from itcj2.apps.titulatec.services.enrollment_request_service import _REVIEWABLE

logger = logging.getLogger("itcj2.apps.titulatec.pages.access_admin")
router = APIRouter(prefix="/admin/accesos", tags=["titulatec-pages-access"])

_LIST = ["titulatec.enrollment_access.page.list"]
_GRANT = ["titulatec.enrollment_access.api.grant"]
_RETURN = ["titulatec.enrollment_access.api.return"]
_REJECT = ["titulatec.enrollment_access.api.reject"]

_OFFICIAL = "school_services"
_ALTERNATE = "computer_center"

_MSG_ONLY_OFFICIAL = ("En este modo Centro de Cómputo revisa las solicitudes: ya no se "
                      "devuelven a Servicios Escolares.")
_MSG_ONLY_ALTERNATE = "En este modo rechazar y reenviar la liga son de Servicios Escolares."
_MSG_GRANT_FAILED = "No pudimos completar el acceso; intenta de nuevo."
_MSG_REASSIGN_FAILED = "No pudimos reasignar el NIP; intenta de nuevo."

# Pestañas por modo, en el orden en que se pintan; la primera es la de omisión.
_TABS = {
    _OFFICIAL: (
        ("awaiting_access", "Por dar acceso"),
        ("granted", "Con acceso"),
        ("returned", "Devueltas"),
    ),
    _ALTERNATE: (
        ("pending_review", "Por revisar"),
        ("approved", "Liga enviada"),
        ("converted", "Inscritas"),
        ("rejected", "Rechazadas"),
        ("all", "Todas"),
    ),
}
# Pestañas donde conviven estados: la fila lleva su etiqueta.
_MIXED_TABS = ("granted", "returned", "all")
_STATUS_LABELS = {
    "pending_review": "Por revisar",
    "unverified": "Por revisar · anterior",
    "verified": "Por revisar · anterior",
    "awaiting_access": "Por dar acceso",
    "approved": "Liga enviada",
    "converted": "Inscrita",
    "rejected": "Rechazada",
}
# En el alterno no existe la pestaña «Por dar acceso»: la sobrante dice por qué
# no pasa por revisión.
_ALT_AWAITING_LABEL = "Aprobada por Servicios Escolares"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/requests_admin.py::_hdr`; `titulatec-utils.js::decodeHeaderMsg`
    lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _mode() -> str:
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    return EnrollmentRequestService.reviewer_mode()


def _mode_block(allowed: str):
    """400 con el motivo si la acción no es del modo vigente; si lo es, `None`.

    Va ANTES de abrir sesión: el corte es de la ruta, no de la plantilla.
    """
    if _mode() == allowed:
        return None
    msg = _MSG_ONLY_OFFICIAL if allowed == _OFFICIAL else _MSG_ONLY_ALTERNATE
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _tab(mode: str, raw) -> str:
    """La pestaña pedida si es de este modo; si no, la primera. Nunca un filtro arbitrario."""
    keys = [key for key, _ in _TABS[mode]]
    return raw if isinstance(raw, str) and raw in keys else keys[0]


def _fmt(dt, with_time=False) -> str:
    if dt is None:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def _tab_query(q, tab: str):
    """Filtro y orden de cada pestaña sobre `EnrollmentRequest`."""
    from itcj2.apps.titulatec.models import EnrollmentRequest as ER

    if tab == "awaiting_access":
        # Cola de trabajo: FIFO por cuando SE la aprobó.
        return (q.filter(ER.status == "awaiting_access")
                .order_by(ER.reviewed_at.asc(), ER.id.asc()))
    if tab == "granted":
        # Spec §8.2: `access_granted_at` no nulo. `approved` entra por D10 (se le
        # mandó liga) y `rejected` también: la D10 que SE canceló es un estado
        # final que en el modo oficial no sale en ninguna otra pestaña de CC.
        # Única excepción: la fila que volvió a una cola de trabajo conservando
        # el sello — la D10 que `verify()` devolvió a revisión de SE y, si SE la
        # reaprobó sin cuenta, la que está otra vez en «Por dar acceso».
        return (q.filter(ER.access_granted_at.isnot(None),
                         ER.status.notin_(_REVIEWABLE + ("awaiting_access",)))
                .order_by(ER.access_granted_at.desc(), ER.id.desc()))
    if tab == "returned":
        return (q.filter(ER.returned_at.isnot(None))
                .order_by(ER.returned_at.desc(), ER.id.desc()))
    if tab == "pending_review":
        # Modo alterno: la cola de revisión incluye las `awaiting_access` que
        # SE dejó antes de cambiar de modo (sobrantes). FIFO por llegada.
        return (q.filter(ER.status.in_(_REVIEWABLE + ("awaiting_access",)))
                .order_by(ER.created_at.asc(), ER.id.asc()))
    if tab in ("approved", "converted", "rejected"):
        q = q.filter(ER.status == tab)
    return q.order_by(ER.created_at.desc(), ER.id.desc())


def _returned_after(status: str, official: bool) -> str:
    """Lo que pasó con una devuelta después de devolverla ("" = sigue en revisión)."""
    if status in _REVIEWABLE:
        return ""
    if status == "rejected":
        return "Servicios Escolares la rechazó" if official else "Después se rechazó"
    # awaiting_access / approved / converted: alguien la volvió a aprobar. En el
    # oficial solo SE aprueba una `pending_review`.
    return "Servicios Escolares la volvió a aprobar" if official else "Después se aprobó"


def _body_ctx(db, *, status, cohort_id):
    """Contexto del parcial. Sin alcance por carrera: CC ve todo.

    «¿Tiene cuenta?» se calcula aquí igual que en `grant_access()`/`approve()`:
    el número de control contra `core_users`, HOY (D10).
    """
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest, TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService, entry_year,
    )

    mode = EnrollmentRequestService.reviewer_mode()
    tab = _tab(mode, status)
    ctx = {"rows": [], "status": tab, "tabs": _TABS[mode], "cohort_id": cohort_id,
           "mode": mode, "official": mode == _OFFICIAL, "programs": [],
           "link_days": EnrollmentRequestService.link_ttl_days()}

    if not ctx["official"]:
        # Solo el modo alterno aprueba, y aprobar deja escoger la carrera.
        ctx["programs"] = [{"id": p.id, "name": p.name}
                           for p in db.query(Program).order_by(Program.name).all()]

    q = db.query(EnrollmentRequest)
    if cohort_id:
        q = q.filter(EnrollmentRequest.cohort_id == cohort_id)
    reqs = _tab_query(q, tab).limit(300).all()

    # Cuentas, folios, convocatorias y carreras en una consulta cada uno: un
    # `db.get` por fila sería N+1.
    controls = {(r.control_number or "").strip() for r in reqs if r.control_number}
    users = ({u.control_number: u for u in db.query(User)
              .filter(User.control_number.in_(controls)).all()} if controls else {})
    pids = {r.converted_process_id for r in reqs if r.converted_process_id}
    folios = (dict(db.query(TitulationProcess.id, TitulationProcess.folio)
                   .filter(TitulationProcess.id.in_(pids)).all()) if pids else {})
    cohort_ids = {r.cohort_id for r in reqs}
    coh_names = (dict(db.query(Cohort.id, Cohort.name)
                      .filter(Cohort.id.in_(cohort_ids)).all()) if cohort_ids else {})
    prog_ids = {r.program_id for r in reqs if r.program_id}
    prog_names = (dict(db.query(Program.id, Program.name)
                       .filter(Program.id.in_(prog_ids)).all()) if prog_ids else {})

    # «Rechazada antes» (C6), la misma consulta sin N+1 de Solicitudes
    # (`requests_admin._body_ctx`), sin el filtro de alcance: CC ve todo.
    rejected_by_control: dict[str, list] = {}
    raw_controls = {r.control_number for r in reqs if r.control_number}
    if raw_controls:
        pq = (db.query(EnrollmentRequest.id, EnrollmentRequest.control_number,
                       EnrollmentRequest.created_at, EnrollmentRequest.review_note)
              .filter(EnrollmentRequest.control_number.in_(raw_controls),
                      EnrollmentRequest.status == "rejected"))
        for pid, control, created_at, note in pq.all():
            rejected_by_control.setdefault(control, []).append((created_at, pid, note))

    for r in reqs:
        u = users.get((r.control_number or "").strip())
        reviewable = r.status in _REVIEWABLE
        # Solo una solicitud ANTERIOR (`id` menor) es antecedente, nunca ella misma.
        anteriores = [c for c in rejected_by_control.get(r.control_number, ()) if c[1] < r.id]
        prior_reject = None
        if anteriores:
            p_created_at, _p_id, p_note = max(
                anteriores, key=lambda c: (c[0] or datetime.min, c[1]))
            prior_reject = {"date": _fmt(p_created_at), "note": p_note or ""}
        access_unsent = EnrollmentRequestService.access_mail_unsent(r)
        # Fecha de la columna Convocatoria/fecha: la que ordena la pestaña.
        if tab == "awaiting_access":
            when = ("Aprobada por SE", _fmt(r.reviewed_at, True))
        elif tab == "granted":
            when = ("Acceso", _fmt(r.access_granted_at, True))
        elif tab == "returned":
            when = ("Devuelta", _fmt(r.returned_at, True))
        else:
            when = ("Recibida", _fmt(r.created_at))
        ctx["rows"].append({
            "id": r.id,
            "control": r.control_number,
            "name": " ".join(x for x in (r.last_name, r.middle_name, r.first_name) if x),
            "entry_year": entry_year(r.control_number),
            "program": prog_names.get(r.program_id) or r.program_text or "",
            "program_id": r.program_id,
            "email": r.contact_email,
            "phone": r.phone,
            "cohort": coh_names.get(r.cohort_id, ""),
            "when_label": when[0],
            "when": when[1],
            "status": r.status,
            "status_label": (_ALT_AWAITING_LABEL
                             if r.status == "awaiting_access" and not ctx["official"]
                             else _STATUS_LABELS.get(r.status, r.status)),
            "reviewable": reviewable,
            # Donde CC puede dar acceso / aprobar según el modo.
            "grantable": (r.status == "awaiting_access"
                          or (not ctx["official"] and reviewable)),
            "has_account": u is not None,
            "has_password": bool(u is not None and u.password_hash),
            # D10: abrir la liga reactiva la cuenta; se avisa mientras la liga
            # todavía puede emitirse o abrirse.
            "account_inactive": bool(u is not None and not u.is_active
                                     and (reviewable or r.status in
                                          ("awaiting_access", "approved"))),
            "sends": r.verify_send_count or 0,
            "last_sent": _fmt(r.verify_sent_at, True),
            "opened": r.verified_at is not None,
            "folio": folios.get(r.converted_process_id, ""),
            "note": r.review_note or "",
            "returned": r.returned_at is not None,
            "returned_at": _fmt(r.returned_at, True),
            # Qué pasó DESPUÉS de devolverla: «Devuelta» a secas se leía como
            # estado actual aunque SE ya la hubiera vuelto a aprobar.
            "returned_after": _returned_after(r.status, ctx["official"]),
            "return_note": r.return_note or "",
            # Correo con usuario + NIP que no salió: ÚNICO predicado del servicio.
            "access_unsent": access_unsent,
            # Correo de la liga (D10 y alterno): lo sella `verify_sent_at`.
            "link_unsent": r.status == "approved" and r.verify_sent_at is None,
            # «Reasignar NIP» (ruling 2026-09-25, spec §8.2): basta
            # `can_reassign_nip` (cuenta creada por la solicitud que nunca ha
            # iniciado sesión), AUNQUE el correo haya salido: un correo mal
            # escrito también «sale». `reassign_nip` lo repite bajo el bloqueo
            # de la cuenta, junto con la señal positiva de la solicitud.
            "can_reassign": EnrollmentRequestService.can_reassign_nip(r, u),
            "rejection_sent": r.rejection_sent_at is not None,
            # «Por revisar» del alterno mezcla las `awaiting_access` sobrantes (y
            # el legado): esas llevan su estado; la `pending_review` no.
            "show_status": (tab in _MIXED_TABS
                            or (tab == "pending_review" and r.status != "pending_review")),
            "prior_reject": prior_reject,
        })
    return ctx


def _render_body(request: Request, db, form):
    ctx = _body_ctx(db, status=form.get("status"), cohort_id=_to_int(form.get("cohort_id")))
    return render_titulatec(request, "titulatec/admin/partials/access_body.html", ctx)


def _fail(db, what: str, req_id: int, exc: Exception, msg: str) -> Response:
    """Fallo inesperado de un servicio que escribe credenciales: rollback + 400.

    Se registra SOLO el tipo de la excepción, sin traza (`logger.exception` /
    `exc_info`): la de un `IntegrityError` del INSERT de `core_users` trae los
    parámetros, y su `password_hash` es un hash de un NIP de 4 dígitos.
    """
    logger.error("%s: fallo inesperado en la solicitud %s (%s)", what, req_id,
                 type(exc).__name__)
    try:
        db.rollback()
    except Exception:      # pragma: no cover - sesión ya inservible
        logger.warning("%s: rollback fallido tras el error", what)
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _with_notice(resp, msg: str, kind: str):
    """`X-Tt-Notice` (+ `X-Tt-Notice-Kind`) sobre la respuesta 200 del parcial.

    El listener global de `titulatec-utils.js` lo muestra como toast. Jamás
    lleva el NIP: solo el folio, que ya se pinta en la bandeja.
    """
    resp.headers["X-Tt-Notice"] = _hdr(msg)
    resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


def _folio(db, req, detail: str = "") -> str:
    """Folio del proceso de la solicitud: el que devolvió el servicio o el de BD."""
    if detail:
        return detail
    if not req.converted_process_id:
        return ""
    from itcj2.apps.titulatec.models import TitulationProcess
    proc = db.get(TitulationProcess, req.converted_process_id)
    return proc.folio if proc is not None else ""


def _granted_tab_label(official: bool) -> str:
    """Pestaña donde vive la fila convertida (y su «Reasignar NIP»)."""
    return "Con acceso" if official else "Inscritas"


def _grant_notice(db, req, detail: str):
    """Qué pasó tras «Dar acceso» / «Aprobar» (C4): `(mensaje, tipo)` o `None`.

    La fila sale de la pestaña en que estaba CC, así que sin esto no sabría si
    el correo salió. `req` ya viene refrescada tras los commits del servicio.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    official = _mode() == _OFFICIAL
    if req.status == "converted":
        folio = _folio(db, req, detail)
        if EnrollmentRequestService.access_mail_unsent(req):
            return (f"Acceso dado (folio {folio}), pero el correo no salió: dicta el NIP "
                    f"o reasígnalo en {_granted_tab_label(official)}", "warning")
        return f"Acceso dado · folio {folio} · correo enviado", "success"
    if req.status == "approved":
        # D10 (oficial) o «Aprobar y enviar liga» (alterno): el NIP no se usó.
        if req.verify_sent_at is not None:
            return "Ya tenía cuenta: se envió la liga", "success"
        donde = ("Servicios Escolares puede reenviarla desde Solicitudes" if official
                 else "reenvíala desde Liga enviada")
        return (f"Ya tenía cuenta: la liga se generó, pero el correo no salió; {donde}",
                "warning")
    return None


def _load(db, req_id: int):
    from itcj2.apps.titulatec.models import EnrollmentRequest
    return db.get(EnrollmentRequest, req_id)


@router.get("", name="titulatec.pages.access.list")
async def list_access(request: Request, status: str = "", cohort_id: str = "",
                      user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, cohort_id=_to_int(cohort_id))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/access.html", ctx)


@router.get("/body", name="titulatec.pages.access.body")
async def body(request: Request, status: str = "", cohort_id: str = "",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, status=status, cohort_id=_to_int(cohort_id))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/access_body.html", ctx)


@router.post("/{req_id}/dar-acceso", name="titulatec.pages.access.grant")
async def grant(req_id: int, request: Request,
                user: dict = Depends(require_page_app("titulatec", perms=_GRANT))):
    """Da el acceso (ambos modos) o, en el alterno, aprueba una por revisar.

    Oficial: SIEMPRE `grant_access`, que solo acepta `awaiting_access` — una
    `pending_review` sigue siendo de SE (Review Focus 3). Alterno: sobre una
    `awaiting_access` sobrante, `grant_access`; sobre el resto, `approve`.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    nip = (form.get("nip") or "").strip()

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        req = _load(db, req_id)
        if req is None:
            return Response(status_code=404)
        try:
            if _mode() == _OFFICIAL or req.status == "awaiting_access":
                ok, detail = EnrollmentRequestService.grant_access(
                    db, req_id, nip=nip, actor_id=uid)
            else:
                ok, detail = EnrollmentRequestService.approve(
                    db, req_id, nip=nip, program_id=_to_int(form.get("program_id")),
                    actor_id=uid)
        except Exception as exc:
            # El servicio es dueño de su transacción: un fallo real se deshace
            # entero aquí (patrón de `requests_admin.approve`). Sin el NIP ni
            # su hash (`_fail`).
            return _fail(db, "dar-acceso", req_id, exc, _MSG_GRANT_FAILED)
        if not ok:
            # `detail` nunca contiene el NIP, y `(False, ...)` no deja nada escrito.
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        db.refresh(req)
        aviso = _grant_notice(db, req, detail)
        resp = _render_body(request, db, form)
        return _with_notice(resp, *aviso) if aviso else resp
    finally:
        db.close()


@router.post("/{req_id}/devolver", name="titulatec.pages.access.return")
async def return_to_review(req_id: int, request: Request,
                           user: dict = Depends(require_page_app("titulatec", perms=_RETURN))):
    """Devuelve a SE con nota (solo modo oficial). Sin correo al alumno."""
    bloqueo = _mode_block(_OFFICIAL)
    if bloqueo is not None:
        return bloqueo
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()

    db = SessionLocal()
    try:
        if _load(db, req_id) is None:
            return Response(status_code=404)
        ok, detail = EnrollmentRequestService.return_to_review(
            db, req_id, note=form.get("note") or "", actor_id=int(user["sub"]))
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        return _render_body(request, db, form)
    finally:
        db.close()


@router.post("/{req_id}/rechazar", name="titulatec.pages.access.reject")
async def reject(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Rechaza o cancela (solo modo alterno). Motivo obligatorio: lo lee la persona."""
    bloqueo = _mode_block(_ALTERNATE)
    if bloqueo is not None:
        return bloqueo
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
        if _load(db, req_id) is None:
            return Response(status_code=404)
        if not EnrollmentRequestService.reject(db, req_id, note=note,
                                               actor_id=int(user["sub"])):
            return Response(status_code=400, headers={
                "X-Tt-Error": _hdr("Esa solicitud ya se resolvió.")})
        return _render_body(request, db, form)
    finally:
        db.close()


@router.post("/{req_id}/reenviar", name="titulatec.pages.access.resend")
async def resend(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_GRANT))):
    """Reenvía (ROTA) la liga de una aprobada (solo modo alterno)."""
    bloqueo = _mode_block(_ALTERNATE)
    if bloqueo is not None:
        return bloqueo
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()

    db = SessionLocal()
    try:
        if _load(db, req_id) is None:
            return Response(status_code=404)
        ok, detail = EnrollmentRequestService.resend_link(db, req_id)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        return _render_body(request, db, form)
    finally:
        db.close()


@router.post("/{req_id}/reasignar-nip", name="titulatec.pages.access.reassign")
async def reassign_nip(req_id: int, request: Request,
                       user: dict = Depends(require_page_app("titulatec", perms=_GRANT))):
    """Reasigna el NIP (D8, ambos modos) y lo reenvía, o no si viene `no_mail`
    («lo dicto por teléfono»: el correo mal escrito). La elegibilidad la decide
    el servicio bajo el bloqueo de la cuenta; el botón aparece con
    `can_reassign_nip` (nunca ha iniciado sesión), haya salido o no el correo."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
    send_mail = not form.get("no_mail")

    db = SessionLocal()
    try:
        req = _load(db, req_id)
        if req is None:
            return Response(status_code=404)
        try:
            ok, detail = EnrollmentRequestService.reassign_nip(
                db, req_id, nip=(form.get("nip") or "").strip(),
                actor_id=int(user["sub"]), send_mail=send_mail)
        except Exception as exc:
            # Mismo trato que dar-acceso: reescribe `password_hash`, y si no
            # pudo revocar las sesiones lanza antes de commitear.
            return _fail(db, "reasignar-nip", req_id, exc, _MSG_REASSIGN_FAILED)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        # El aviso dice si el correo salió (C4); sin él la fila no cambia de
        # pestaña y CC no sabría si tiene que dictarlo. Nunca el NIP.
        db.refresh(req)
        if not send_mail:
            aviso = ("NIP reasignado; no se envió correo", "success")
        elif req.access_sent_at is None:
            aviso = ("NIP reasignado, pero el correo no salió: díctalo por teléfono", "warning")
        else:
            aviso = ("NIP reasignado · correo enviado", "success")
        return _with_notice(_render_body(request, db, form), *aviso)
    finally:
        db.close()

"""Bandeja de solicitudes de auto-inscripción (Servicios Escolares).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja entera.

Pestañas por estado, «Por revisar» por omisión. Aprobar, rechazar y reenviar
vuelven a pintar la pestaña donde estaba el oficial: cada formulario de fila la
manda de vuelta en `status` y `cohort_id`. Flujo completo en
`docs/flows/xcut_public_enrollment.md`.

Modo (`EnrollmentRequestService.reviewer_mode()`, 2026-09-24): en el OFICIAL,
SE aprueba sin NIP y la solicitud sin cuenta pasa a «En Cómputo»
(`awaiting_access`) — el NIP lo da Centro de Cómputo en su bandeja. En el
ALTERNO la revisión es de Centro de Cómputo: esta bandeja queda de SOLO LECTURA
y sus tres POST responden 400 ANTES de abrir sesión (`_alternate_mode_block`),
así que ni un POST directo sin la UI aprueba, rechaza o reenvía.

En el modo `sii` (spec 2026-09-25 §3.5) SE actúa como en el oficial (la cuenta
nueva nace con el NIP DEL SII, `approve()`), y cada fila «Por revisar» trae el
veredicto VIGENTE del SII (`_sii_row`): reglas con su motivo, diferencias de
identidad, intentos y, si era apta, por qué no se aprobó sola. «Reintentar
consulta» (`reconsultar`) encola una consulta forzada. La aprobada sola se
reconoce en Liga enviada/Inscritas con la regla del servicio
(`enrollment_request_service._auto_approval_marker`). El NIP del SII nunca pasa
por aquí: la bandeja lee la `EligibilityCheck`, que no lo guarda.

«Revocar inscripción» (spec 2026-09-25 §3.6, `revocar`): en Inscritas, sobre el
proceso en que se convirtió la solicitud, con `titulatec.process.api.cancel` y
motivo obligatorio; la escritura es de `ProcessService.cancel`. La fila revocada
dice «Inscripción revocada: motivo» (`ProcessService.cancellation_info`). Como
aprobar, rechazar y reenviar, queda cortada en el modo alterno: la bandeja es de
solo lectura, «sin formularios» (spec 2026-09-24 §8.1), y el spec 2026-09-25
conserva ese modo tal cual (S1). En ese modo se revoca desde el expediente
(`admin.process_cancel`), que no depende del modo.
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.requests_admin")
router = APIRouter(prefix="/admin/solicitudes", tags=["titulatec-pages-requests"])

_LIST = ["titulatec.enrollment_request.page.list"]
_APPROVE = ["titulatec.enrollment_request.api.approve"]
_REJECT = ["titulatec.enrollment_request.api.reject"]
_CANCEL = ["titulatec.process.api.cancel"]

_MSG_ALTERNATE = "En este modo la revisión la hace Centro de Cómputo."
_MSG_NOT_SII = "La consulta al SII solo existe en el modo sii."
_MSG_RESOLVED = "Esa solicitud ya se resolvió."
_MSG_IN_FLIGHT = "Ya se está consultando al SII; espera el resultado."
_MSG_RECHECK_QUEUED = "Consulta al SII solicitada: el veredicto aparece al terminar."
_MSG_NO_REASON = "Escribe el motivo de la revocación: es lo que el alumno lee."
_MSG_NOT_ENROLLED = "Esa solicitud no tiene una inscripción que revocar."

# Veredicto de la consulta vigente → (etiqueta, tono de `.tt-pill--*`, icono).
# `pending` fresca = otro proceso consulta ahora; `stale` = `pending` colgada
# (más de `_PENDING_STALE`), que `force` sí retoma.
_SII_STATES = {
    "none": ("Sin consultar", "neutral", "bi-question-circle"),
    "pending": ("Consultando…", "navy", "bi-hourglass-split"),
    "stale": ("Consultando… sin respuesta", "amber", "bi-hourglass-bottom"),
    "apt": ("Apta", "success", "bi-check-circle"),
    "not_apt": ("No apta", "danger", "bi-x-circle"),
    "error": ("Error de consulta", "amber", "bi-exclamation-triangle"),
}
# Campos de `identity_mismatch` → etiqueta legible. Otro campo sale tal cual.
_DIFF_LABELS = {"first_name": "Nombre", "last_name": "Apellido paterno",
                "middle_name": "Apellido materno", "program": "Carrera"}
_AUTO_OFF = "La aprobación automática está apagada en esta convocatoria."
_COHORT_NOT_OPEN = "La convocatoria no está abierta: no se aprueba sola."
_AUTO_WAITING = "Apta: se aprobará sola en el siguiente barrido."

# Pestañas, en el orden en que se pintan.
_TABS = (
    ("pending_review", "Por revisar"),
    ("awaiting_access", "En Cómputo"),
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
    "awaiting_access": ("awaiting_access",),
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
    "awaiting_access": "En Cómputo",
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


def _alternate_mode_block():
    """En modo alterno, el 400 con el motivo; en el oficial, `None`.

    Va ANTES de abrir sesión y de leer la solicitud: el corte es de la ruta, no
    de la plantilla (un POST directo tampoco pasa), y no deja nada escrito.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    if EnrollmentRequestService.reviewer_mode() == "computer_center":
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_ALTERNATE)})
    return None


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


def _fmt(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def _in_flight(chk, now: datetime) -> bool:
    """¿La consulta VIGENTE `chk` sigue en curso? ÚNICA copia en la página.

    Es el corte con el que `EligibilityService.check` se niega a consultar otra
    vez, ni con `force`: `pending` más joven que `_PENDING_STALE`. Lo usan la
    fila («Consultando…» sin botón, `_sii_row`) y la ruta (`reconsultar`
    responde 400), así que las dos dicen lo mismo. Vive aquí y no en el
    servicio solo por el reparto de archivos del plan (T5 no tocaba
    `eligibility_service.py`); que coincida con el servicio lo fija
    `test_requests_reconsultar.py::test_la_bandeja_y_el_servicio_coinciden_en_que_es_una_consulta_en_curso`.
    """
    from itcj2.apps.titulatec.services.eligibility_service import _PENDING_STALE

    return (chk is not None and chk.status == "pending"
            and chk.started_at is not None and chk.started_at > now - _PENDING_STALE)


def _sii_row(chk, *, note: str, cohort: dict, delay_hours: int, max_attempts: int,
             now: datetime, requested: bool) -> dict:
    """El bloque del SII de una fila «Por revisar» (modo `sii`).

    `chk` es la consulta VIGENTE (`last_check_id`) ya cargada en lote. Solo
    se leen `results`, `error`, `identity_mismatch` y los tiempos: nada de
    eso trae el NIP (el servicio no corre `[credential]` al consultar), y
    todo se pinta escapado por Jinja. `requested` = SE acaba de pedir la
    consulta en esta misma respuesta: se pinta «Consultando…» aunque el
    worker aún no haya abierto la fila, para no ofrecer el botón otra vez.

    `why` dice por qué una APTA sigue aquí, en el orden en que la frena
    `EligibilityService.auto_approve`: la nota que dejó la automática
    (`review_note`), el interruptor de la convocatoria, la convocatoria
    cerrada, la ventana de veto; si nada la frena, la toma el barrido.
    """
    if chk is None:
        state = "none"
    elif chk.status == "pending":
        state = "pending" if _in_flight(chk, now) else "stale"
    else:
        state = chk.status if chk.status in _SII_STATES else "error"
    if requested and state != "pending":
        state = "pending"
    label, tone, icon = _SII_STATES[state]
    if state == "stale" and chk.started_at is not None:
        label = f"{label} desde {_fmt(chk.started_at)}"

    results = (chk.results or []) if chk is not None and state != "pending" else []
    failed = [str(r.get("message") or r.get("rule") or "") for r in results
              if isinstance(r, dict) and not r.get("ok")]
    passed = [str(r.get("message") or r.get("rule") or "") for r in results
              if isinstance(r, dict) and r.get("ok")]

    diffs = []
    for campo, par in ((chk.identity_mismatch or {}) if chk is not None else {}).items():
        if isinstance(par, dict):
            diffs.append({"label": _DIFF_LABELS.get(campo, campo),
                          "form": par.get("form") or "", "sii": par.get("sii") or ""})

    why = ""
    if state == "apt":
        if note:
            why = f"No se aprobó sola: {note}"
        elif not cohort.get("auto", True):
            why = _AUTO_OFF
        elif cohort.get("status") != "open":
            why = _COHORT_NOT_OPEN
        elif delay_hours and chk.finished_at is not None:
            desde = chk.finished_at + timedelta(hours=delay_hours)
            why = (f"Se aprobará sola a partir del {_fmt(desde)}." if desde > now
                   else _AUTO_WAITING)
        else:
            why = _AUTO_WAITING

    return {
        "state": state, "label": label, "tone": tone, "icon": icon,
        "attempt": chk.attempt if chk is not None else 0,
        "max": max_attempts,
        "when": _fmt(chk.finished_at or chk.started_at) if chk is not None else "",
        "failed": failed, "passed": passed,
        "error": (chk.error or "") if state == "error" else "",
        "diffs": diffs, "why": why,
        # La nota ya va en `why`: la fila no la repite como «Nota:».
        "note_shown": bool(state == "apt" and note),
        # Una consulta en curso no se duplica (el servicio tampoco la repite).
        "can_recheck": state != "pending",
    }


def _body_ctx(db, *, user_id: int, status, cohort_id, requested_id: int | None = None):
    """Contexto del parcial. Distingue los DOS vacíos (riesgo 3 del diseño).

    «¿Tiene cuenta?» se calcula aquí igual que en `approve()`: el número de
    control contra `core_users`, HOY. Si la bandeja y el servicio se separan, la
    fila promete un NIP que no se aplica o esconde una liga que sí sale.

    Modo `sii`: la consulta VIGENTE de cada fila se carga en UNA consulta
    (nunca `latest_check` por fila) y `_sii_row` arma su bloque. `requested_id`
    = la solicitud cuya consulta SE acaba de pedir (`reconsultar`).
    """
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import (
        Cohort, EligibilityCheck, EnrollmentRequest, TitulationProcess,
    )
    from itcj2.apps.titulatec.services import enrollment_request_service as ers
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    tab = _tab(status)
    scope = _officer_scope(db, user_id)
    mode = EnrollmentRequestService.reviewer_mode()
    sii = mode == "sii"
    ctx = {"rows": [], "status": tab, "tabs": _TABS, "cohort_id": cohort_id,
           "programs": [], "no_programs": False,
           # Modo alterno = solo lectura: la plantilla no pinta ni un formulario
           # (las rutas POST lo cortan aparte, `_alternate_mode_block`).
           "mode": mode, "can_act": mode != "computer_center", "sii": sii,
           # «Revocar inscripción»: el formulario solo a quien la ruta va a
           # dejar pasar (patrón `can_export` de `handoff_admin.py`); se
           # calcula abajo, después del corte de «sin alcance».
           "can_revoke": False,
           # Días de la liga para el texto de la cabecera: de la MISMA fuente
           # que el vencimiento en BD y el correo, nunca un literal.
           "link_days": EnrollmentRequestService.link_ttl_days(),
           "kpis": {"total": 0, "review": 0, "access": 0, "sent": 0, "converted": 0,
                    "rejected": 0},
           "by_year": [], "year_max": 0, "years_summary": None}

    if scope != "ALL" and not scope:
        # Conjunto vacío = no ve nada, EN SILENCIO. Se marca explícitamente para
        # que la plantilla no muestre "no hay solicitudes" (ni KPIs: no hay
        # universo que contar).
        ctx["no_programs"] = True
        return ctx

    if ctx["can_act"]:
        from itcj2.core.services.authz_service import get_user_permissions_for_app
        ctx["can_revoke"] = _CANCEL[0] in get_user_permissions_for_app(
            db, user_id, "titulatec")

    # KPIs y "por año de ingreso": MISMO alcance y convocatoria que el listado de
    # abajo, pero sin filtro de pestaña ni el límite de 300 — es el universo
    # completo, no la página visible.
    stats = EnrollmentRequestService.stats(db, scope=scope, cohort_id=cohort_id)
    ctx["kpis"] = stats["counts"]
    ctx["by_year"] = stats["by_year"]
    ctx["year_max"] = stats["year_max"]
    ctx["years_summary"] = stats["summary"]

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

    if tab == "pending_review":
        # FIFO (2026-09-24): «Por revisar» es una cola de trabajo, no un
        # archivo — se atiende en el orden en que llegó. Con el límite de 300
        # esto deja fuera las solicitudes MÁS NUEVAS si hay más de 300
        # pendientes, que es lo correcto en una cola: las viejas nunca se
        # pierden de vista por más que sigan llegando solicitudes después.
        reqs = q.order_by(EnrollmentRequest.created_at.asc(),
                          EnrollmentRequest.id.asc()).limit(300).all()
    else:
        # El resto de pestañas son historial: se sigue leyendo de lo último
        # que pasó hacia atrás.
        reqs = q.order_by(EnrollmentRequest.created_at.desc(),
                          EnrollmentRequest.id.desc()).limit(300).all()

    # Cuentas, folios y convocatorias en una consulta cada uno: un `db.get` por
    # fila sería N+1.
    controls = {r.control_number for r in reqs if r.control_number}
    users = ({u.control_number: u for u in db.query(User)
              .filter(User.control_number.in_(controls)).all()} if controls else {})
    # El proceso entero, no solo el folio: su `status` decide si la fila
    # ofrece «Revocar inscripción» o dice «Inscripción revocada».
    pids = {r.converted_process_id for r in reqs if r.converted_process_id}
    procs = ({p.id: p for p in db.query(TitulationProcess)
              .filter(TitulationProcess.id.in_(pids)).all()} if pids else {})
    cohort_ids = {r.cohort_id for r in reqs}
    cohorts = ({cid: {"name": name, "status": st, "auto": bool(auto)}
                for cid, name, st, auto in db.query(
                    Cohort.id, Cohort.name, Cohort.status, Cohort.sii_auto_approve)
                .filter(Cohort.id.in_(cohort_ids)).all()} if cohort_ids else {})
    prog_names = {p["id"]: p["name"] for p in programs}
    # Consultas VIGENTES del SII, en lote. Se cargan en cualquier modo porque
    # «Aprobada automáticamente (SII)» es un hecho histórico de la fila; el
    # bloque del veredicto solo se pinta en el modo `sii`. El lote las deja en
    # el mapa de identidad de la sesión: el `db.get` de `_auto_approval_marker`
    # las toma de ahí, sin una consulta por fila.
    check_ids = {r.last_check_id for r in reqs if r.last_check_id}
    checks = ({c.id: c for c in db.query(EligibilityCheck)
               .filter(EligibilityCheck.id.in_(check_ids)).all()} if check_ids else {})
    if sii:
        from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
        delay_hours = EligibilityService.delay_hours()
        max_attempts = EligibilityService.max_attempts()
        now = datetime.now()

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

    from itcj2.apps.titulatec.services.process_service import ProcessService

    for r in reqs:
        u = users.get(r.control_number)
        proc = procs.get(r.converted_process_id)
        # Solo una revocada paga la consulta de su motivo (una por fila
        # revocada, que es la excepción): la regla es la del servicio, que lee
        # el ÚLTIMO `process_cancelled` y solo si el proceso sigue `cancelled`.
        revoked = (ProcessService.cancellation_info(db, proc)
                   if r.status == "converted" and proc is not None else None)
        chk = checks.get(r.last_check_id)
        cohort = cohorts.get(r.cohort_id, {})
        sii_block = None
        if sii and r.status == "pending_review":
            # Solo `pending_review`: `EligibilityService.check` no consulta el
            # legado (`unverified`/`verified`) ni lo ya resuelto.
            sii_block = _sii_row(chk, note=r.review_note or "", cohort=cohort,
                                 delay_hours=delay_hours, max_attempts=max_attempts,
                                 now=now, requested=(r.id == requested_id))
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
            "cohort": cohort.get("name", ""),
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
            "folio": proc.folio if proc is not None else "",
            # Lo mismo que `ProcessService.cancel` acepta revocar; el permiso
            # lo pone `can_revoke`, arriba.
            "revocable": (r.status == "converted" and proc is not None
                          and proc.status in ProcessService.REVOCABLE_STATUSES),
            "revoked": ({"reason": revoked["reason"] or ""}
                        if revoked is not None else None),
            "note": r.review_note or "",
            # «En Centro de Cómputo desde …»: `reviewed_at` es cuando SE la
            # aprobó, y `grant_access` no la toca.
            "awaiting_since": (r.reviewed_at.strftime("%d/%m/%Y %H:%M")
                               if r.status == "awaiting_access" and r.reviewed_at else ""),
            # Devuelta por CC: solo mientras vuelve a ser trabajo de SE. Una
            # aprobada de nuevo conserva `returned_at`, pero ya no se anuncia.
            "returned": (r.returned_at is not None
                         and r.status in _TAB_STATUSES["pending_review"]),
            "return_note": r.return_note or "",
            # Solo tiene sentido leerla en una fila `rejected`: el correo de
            # rechazo es lo único que sella esta columna (`reject()`).
            "rejection_sent": r.rejection_sent_at is not None,
            "prior_reject": prior_reject,
            "sii": sii_block,
            # Aprobada SOLA (EligibilityService.auto_approve). La regla es la
            # del servicio (`_auto_approval_marker`, la misma que marca el
            # evento `auto: true`), no una copia: si cambia, la píldora la sigue.
            "auto_approved": (r.status in ("approved", "converted")
                              and bool(ers._auto_approval_marker(db, r))),
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
    """Aprueba (modo oficial). Sin cuenta pasa a Centro de Cómputo
    (`awaiting_access`), que da el NIP; con cuenta, emite la liga de activación.
    La ruta ya no lee `nip`: un formulario viejo en caché que lo mande se
    ignora, y nunca aparece en un log ni cabecera."""
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    form = await request.form()
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
            # `nip=""`: en modo oficial `approve` no lo usa, y en el alterno
            # esta ruta ya cortó arriba.
            ok, detail = EnrollmentRequestService.approve(
                db, req_id, nip="", program_id=program_id, actor_id=uid)
        except Exception as exc:
            # `approve` es dueña de su transacción: un fallo real en cualquier
            # punto se deshace entero aquí, mismo patrón que `enroll_verify`
            # (`pages/public.py`). El NIP NUNCA se loguea, ni aquí ni abajo, y
            # tampoco la traza: la de un `IntegrityError` trae los parámetros
            # del INSERT (mismo criterio que `access_admin._fail`).
            logger.error("aprobar: fallo inesperado al aprobar la solicitud %s (%s)",
                         req_id, type(exc).__name__)
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
    """Rechaza, o cancela una solicitud con la liga enviada o en Centro de
    Cómputo. Motivo obligatorio: es lo que la persona lee en su correo."""
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo
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
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo
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


@router.post("/{req_id}/reconsultar", name="titulatec.pages.requests.recheck")
async def reconsultar(req_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """«Reintentar consulta» (modo `sii`): encola una consulta FORZADA al SII.

    `enqueue_check(req_id, force=True)` después de validar; la consulta corre
    en celery (el SII puede tardar lo que sus timeouts: nunca en la petición
    web). No duplica: con la consulta vigente `pending` y fresca responde 400
    sin encolar (`EligibilityService.check` tampoco la repetiría), y la bandeja
    que devuelve ya pinta esa fila «Consultando…» sin el botón. Una `pending`
    colgada (más de `_PENDING_STALE`) sí se reintenta: `force` la retoma.
    Mismo permiso y alcance por carrera que aprobar; 404 liso fuera de alcance.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    if EnrollmentRequestService.reviewer_mode() != "sii":
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_NOT_SII)})
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services import eligibility_service as elig

    form = await request.form()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        req = _load_scoped_request(db, scope, req_id)
        if req is None:
            return Response(status_code=404)
        if req.status != "pending_review":
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_RESOLVED)})
        if _in_flight(elig.EligibilityService.latest_check(db, req), datetime.now()):
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_IN_FLIGHT)})
        # Sin escrituras propias: la fila `pending` la abre la tarea bajo el lock
        # de la solicitud. `enqueue_check` es best-effort y nunca lanza; con el
        # broker caído la recoge el barrido (no hay consulta en curso).
        elig.enqueue_check(req.id, force=True)
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        requested_id=req.id)
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(_MSG_RECHECK_QUEUED)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


@router.post("/{req_id}/revocar", name="titulatec.pages.requests.revoke")
async def revocar(req_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=_CANCEL))):
    """«Revocar inscripción» desde Inscritas (spec 2026-09-25 §3.6).

    Revoca el proceso en que se convirtió la solicitud (`converted_process_id`)
    con `ProcessService.cancel`, que es dueña de la transacción, del lock y del
    aviso al alumno. Motivo obligatorio: es lo que el alumno lee. Alcance por
    carrera de la SOLICITUD, como aprobar y rechazar (404 liso). Una solicitud
    sin inscripción, o con el proceso ya revocado o concluido, es 400 con el
    motivo; el del servicio va por `_hdr` (trae acentos). En el modo alterno la
    bandeja es de solo lectura, también para esto (`_alternate_mode_block`); ahí
    se revoca desde el expediente.
    """
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService

    form = await request.form()
    reason = (form.get("reason") or "").strip()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    if not reason:
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_NO_REASON)})

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        req = _load_scoped_request(db, scope, req_id)
        if req is None:
            return Response(status_code=404)
        if req.status != "converted" or not req.converted_process_id:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_NOT_ENROLLED)})
        ok, msg = ProcessService.cancel(db, req.converted_process_id, reason=reason,
                                        actor_id=uid)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)

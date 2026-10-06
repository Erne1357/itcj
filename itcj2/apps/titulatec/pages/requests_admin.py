"""Bandeja de solicitudes de auto-inscripción (Servicios Escolares).

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py:131`), así que un código de más abre la bandeja entera.

Pestañas por estado, «Por revisar» por omisión. Aprobar, rechazar y reenviar
(la liga o el aviso de acceso) vuelven a pintar la pestaña donde estaba el
oficial: cada formulario de fila la manda de vuelta en `status` y
`cohort_id`. Flujo completo en `docs/flows/xcut_public_enrollment.md`.

Modo (`EnrollmentRequestService.reviewer_mode()`, 2026-09-24): en el OFICIAL,
SE aprueba sin NIP y la solicitud sin cuenta pasa a «En Cómputo»
(`awaiting_access`) — el NIP lo da Centro de Cómputo en su bandeja. En el
ALTERNO la revisión es de Centro de Cómputo: esta bandeja queda de SOLO LECTURA
y sus POST (aprobar, rechazar, reenviar la liga o el aviso, revocar) responden
400 ANTES de abrir sesión (`_alternate_mode_block`), así que ni un POST directo
sin la UI aprueba, rechaza o reenvía.

En el modo `sii` (spec 2026-09-25 §3.5; spec 2026-09-27 «el SII informa,
Servicios Escolares decide») SE es quien aprueba SIEMPRE: nada se aprueba solo.
Sin cuenta, la cuenta nace con el NIP DEL SII o, con `to_access`, la solicitud
pasa a Accesos (`approve_detailed`); si el SII no da un NIP válido al aprobar,
nada se escribe y la ruta avisa en 200. Cada fila, en TODAS las pestañas, trae
la columna «SII» con la consulta VIGENTE (`_sii_cell`): en lo pendiente,
reglas con su motivo, diferencias de identidad, intentos y el estado del NIP;
en el historial, compacta. El botón de aprobar lo decide `_approve_action`
(«enviar liga» / «dar acceso» / «pasar a Accesos», con la MISMA decisión que
`sii-check`: `EnrollmentRequestService.approval_path`, Ruling R8), y pide
confirmación (`hx-confirm`) cuando el SII no dijo «Apta» o el nombre no
coincide (D7). Con el SII sin configurar (D11) hay un aviso de página, sin
«Reintentar consulta» ni «Se reintenta sola»; solo pide confirmación una
consulta VIEJA que marcó «No apta» o la identidad, y aprobar sin cuenta ES
pasar a Accesos. «Reintentar consulta» (`reconsultar`) encola una consulta
forzada. En este modo aprobar responde con un aviso (`_approve_notice`): cuenta
creada y si el correo salió, pasó a Accesos, o liga enviada. El NIP del SII nunca pasa por aquí: la bandeja lee
la `EligibilityCheck`, que solo guarda su ESTADO (`nip_status`). En Inscritas,
una cuenta que nació con el NIP del SII y cuyo correo de acceso no salió lleva
«correo no enviado» y «Reenviar aviso» (`reenviar-aviso`, D12): el correo no
lleva NIP y no se toca ninguna credencial.

«Revocar inscripción» (spec 2026-09-25 §3.6, `revocar`): en Inscritas, sobre el
proceso en que se convirtió la solicitud, con `titulatec.process.api.cancel` y
motivo obligatorio; la escritura es de `ProcessService.cancel`. La fila revocada
dice «Inscripción revocada: motivo» (`ProcessService.cancellation_info`). Como
aprobar, rechazar y reenviar, queda cortada en el modo alterno: la bandeja es de
solo lectura, «sin formularios» (spec 2026-09-24 §8.1), y el spec 2026-09-25
conserva ese modo tal cual (S1). En ese modo se revoca desde el expediente
(`admin.process_cancel`), que no depende del modo.
"""
import dataclasses
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func
from starlette.concurrency import run_in_threadpool

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.utils.paging import (
    PAGE_SIZE, Page, normalize_q, paginate_query, parse_page,
)

logger = logging.getLogger("itcj2.apps.titulatec.pages.requests_admin")
router = APIRouter(prefix="/admin/solicitudes", tags=["titulatec-pages-requests"])

_LIST = ["titulatec.enrollment_request.page.list"]
_APPROVE = ["titulatec.enrollment_request.api.approve"]
_REJECT = ["titulatec.enrollment_request.api.reject"]
_CANCEL = ["titulatec.process.api.cancel"]

_MSG_ALTERNATE = "En este modo la revisión la hace Centro de Cómputo."
_MSG_NOT_SII = "La consulta al SII solo existe en el modo sii."
_MSG_SII_OFF = "El SII no está configurado."
_MSG_RESOLVED = "Esa solicitud ya se resolvió."
_MSG_IN_FLIGHT = "Ya se está consultando al SII; espera el resultado."
_MSG_RECHECK_QUEUED = "Consulta al SII solicitada: el veredicto aparece al terminar."
_MSG_RECHECK_NOT_QUEUED = "No se pudo solicitar la consulta; intenta de nuevo."
_MSG_NO_REASON = "Escribe el motivo de la revocación: es lo que el alumno lee."
_MSG_NOT_ENROLLED = "Esa solicitud no tiene una inscripción que revocar."
_MSG_NOTICE_RESENT = "Aviso reenviado."
# Tras rechazar: el correo con el motivo quedó en el outbox (spec 2026-10-05
# §3.7); sale con el despachador, no en la petición. Gemelo en
# `access_admin._MSG_REJECT_QUEUED` (mismo texto).
_MSG_REJECT_QUEUED = "Se enviará el correo al egresado."
_MSG_REOPENED = "Rechazo deshecho: la solicitud está otra vez en Por revisar."
# Aviso tras aprobar en el modo `sii` (revisión final F9, `_approve_notice`):
# la fila sale de «Por revisar» y sin él SE no sabría si el correo salió.
_MSG_ACCOUNT_MAILED = "Cuenta creada (folio {folio}); se le avisó por correo."
_MSG_ACCOUNT_UNMAILED = ("Cuenta creada (folio {folio}), pero el correo no salió: "
                         "reenvíalo desde Inscritas.")
_MSG_TO_ACCESS = "Pasó a Accesos: Centro de Cómputo le capturará el NIP."
_MSG_LINK_MAILED = "Liga enviada al correo del solicitante."
_MSG_LINK_UNMAILED = "Liga generada, pero el correo no salió: reenvíala desde Liga enviada."
# Sigue al motivo de `ApproveResult.detail` cuando el SII no dio un NIP válido
# al aprobar (modo `sii`, aviso en 200).
_MSG_NIP_FAILURE_TAIL = "Puedes pasarla a Accesos o reintentar la consulta."

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
# `EligibilityCheck.nip_status` (solo SIN cuenta) → (etiqueta, tono). Cualquier
# otro valor —`None` (no se revisó) o `not_needed` (tenía cuenta al consultar y
# ya no)— es `_NIP_UNCHECKED`.
_NIP_LABELS = {
    "available": ("NIP en el SII: disponible", "success"),
    "missing": ("El SII no tiene NIP", "amber"),
    "invalid": ("NIP del SII con formato inválido", "amber"),
    "unavailable": ("No se pudo leer el NIP (SII sin respuesta)", "amber"),
    "error": ("No se pudo leer el NIP (configuración)", "amber"),
}
_NIP_UNCHECKED = ("NIP sin revisar", "neutral")
# Botón de aprobar del modo OFICIAL sin cuenta (con cuenta es el mismo «enviar
# liga» que `APPROVAL_LABELS["link"]`).
_LABEL_TO_COMPUTER_CENTER = "Aprobar y pasar a Cómputo"
# Confirmación de aprobar (spec 2026-09-27 D7): el motivo + `_CONFIRM_TAIL`.
_CONFIRM_TAIL = "¿Aprobar de todos modos?"
_CONFIRM_NO_CHECK = "No se ha consultado al SII."
_CONFIRM_NOT_APT = "El SII dijo «No apta»"
_CONFIRM_PENDING = "La consulta al SII sigue en curso."
# `pending` colgada (no `_in_flight`): ya no se afirma que siga en curso.
_CONFIRM_STALE = "La consulta al SII no terminó."
_CONFIRM_ERROR = "La consulta al SII terminó en error."

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


def _recheck_block():
    """«Reintentar consulta»: el 400 con el motivo si el modo no es `sii` o el SII
    no está configurado (D11); si no, `None`.

    Solo lee configuración (nunca BD ni red) y, como el corte de modo, va ANTES de
    leer el cuerpo y de abrir sesión: el corte es de la ruta, no de la plantilla.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    from itcj2.apps.titulatec.services import eligibility_service as elig

    if EnrollmentRequestService.reviewer_mode() != "sii":
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_NOT_SII)})
    if not elig.EligibilityService.sii_configured():
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(_MSG_SII_OFF)})
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
    fila («Consultando…» sin botón, `_sii_cell`) y la ruta (`reconsultar`
    responde 400), así que las dos dicen lo mismo. Vive aquí y no en el
    servicio solo por el reparto de archivos del plan (T5 no tocaba
    `eligibility_service.py`); que coincida con el servicio lo fija
    `test_requests_reconsultar.py::test_la_bandeja_y_el_servicio_coinciden_en_que_es_una_consulta_en_curso`.
    """
    from itcj2.apps.titulatec.services.eligibility_service import _PENDING_STALE

    return (chk is not None and chk.status == "pending"
            and chk.started_at is not None and chk.started_at > now - _PENDING_STALE)


def _rule_messages(chk, *, ok: bool) -> list[str]:
    """Los `message` de las reglas de `chk` que se cumplieron (`ok`) o no."""
    results = (chk.results or []) if chk is not None else []
    return [str(r.get("message") or r.get("rule") or "") for r in results
            if isinstance(r, dict) and bool(r.get("ok")) is ok]


def _sii_cell(chk, *, has_account: bool, compact: bool, now: datetime,
              max_attempts: int, requested: bool, configured: bool) -> dict:
    """La celda «SII» de una fila (modo `sii`), en TODAS las pestañas.

    `chk` es la consulta VIGENTE (`last_check_id`) ya cargada en lote. Solo
    se leen `results`, `error`, `identity_mismatch`, `nip_status` y los
    tiempos: el NIP no está en ninguno (la consulta guarda solo su ESTADO), y
    todo se pinta escapado por Jinja. `requested` = SE acaba de pedir la
    consulta en esta misma respuesta: se pinta «Consultando…» aunque el
    worker aún no haya abierto la fila, para no ofrecer el botón otra vez.

    `compact` (historial: ya no es trabajo de nadie): la plantilla pinta solo
    la píldora y las reglas incumplidas plegadas; sin NIP ni «Reintentar».

    Informa, no promete: una apta sigue aquí como cualquier otra, porque la
    aprueba siempre Servicios Escolares (spec 2026-09-27 §A3).

    `retry` = «Se reintenta sola (intento N de M).» en un `error`
    reintentable (el SII no respondió) que no llegó al tope: N es el intento
    que sigue (lo que se reintenta es la CONSULTA, no una aprobación). Solo
    con el SII configurado, como `can_recheck`: sin él (D11) `check`, `sweep`
    y `recheck_errors` no hacen nada y nadie la reintentaría.

    `nip` = `{label, tone}` del NIP del SII, solo SIN cuenta y fuera del
    historial: con cuenta sale la liga y el NIP del SII no importa.
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

    leer = chk if state != "pending" else None
    diffs = []
    for campo, par in ((chk.identity_mismatch or {}) if chk is not None else {}).items():
        if isinstance(par, dict):
            diffs.append({"label": _DIFF_LABELS.get(campo, campo),
                          "form": par.get("form") or "", "sii": par.get("sii") or ""})

    nip = None
    if not (has_account or compact):
        nip_label, nip_tone = _NIP_LABELS.get(
            chk.nip_status if chk is not None else None, _NIP_UNCHECKED)
        nip = {"label": nip_label, "tone": nip_tone}

    return {
        "state": state, "label": label, "tone": tone, "icon": icon,
        "attempt": chk.attempt if chk is not None else 0,
        "max": max_attempts,
        "when": _fmt(chk.finished_at or chk.started_at) if chk is not None else "",
        "failed": _rule_messages(leer, ok=False),
        "passed": _rule_messages(leer, ok=True),
        "error": (chk.error or "") if state == "error" else "",
        "retry": (f"Se reintenta sola (intento {chk.attempt + 1} de {max_attempts})."
                  if (configured and state == "error" and chk.retryable
                      and chk.attempt < max_attempts)
                  else ""),
        "diffs": diffs,
        "nip": nip,
        # Una consulta en curso no se duplica (el servicio tampoco la repite),
        # y sin SII configurado la ruta respondería 400 (D11).
        "can_recheck": configured and not compact and state != "pending",
        "compact": compact,
    }


def _approve_confirm(chk, *, now: datetime, requested: bool = False) -> str | None:
    """Por qué aprobar pide confirmación (spec 2026-09-27 D7), o `None`.

    Sin consulta; el SII no dijo «Apta» (no apta con sus reglas incumplidas,
    en curso, colgada o en error); o apta con la identidad sin confirmar
    (`identity_block`: nombre distinto o no comparable). La carrera distinta
    NO cuenta: el SII la manda como clave (spec §11).

    «Sigue en curso» solo si lo está de verdad (`_in_flight`, el mismo corte
    que la celda y la ruta) o si SE la acaba de pedir en esta respuesta
    (`requested`: la celda ya dice «Consultando…», y el veredicto de `chk` es
    el VIEJO, que no vale para no confirmar). Una `pending` colgada dice solo
    que no terminó.
    """
    from itcj2.apps.titulatec.services.eligibility_service import identity_block

    if requested or _in_flight(chk, now):
        return f"{_CONFIRM_PENDING} {_CONFIRM_TAIL}"
    if chk is None:
        return f"{_CONFIRM_NO_CHECK} {_CONFIRM_TAIL}"
    if chk.status == "not_apt":
        # Van unidos por «; »: a cada mensaje se le quita COMO MUCHO un punto
        # final (el de una abreviatura que lo cierra, «etc..», se conserva).
        motivos = "; ".join(m for m in (x.strip().removesuffix(".").rstrip() for x in
                                        _rule_messages(chk, ok=False)) if m)
        return (f"{_CONFIRM_NOT_APT}{': ' + motivos if motivos else ''}. "
                f"{_CONFIRM_TAIL}")
    if chk.status == "pending":
        return f"{_CONFIRM_STALE} {_CONFIRM_TAIL}"
    if chk.status != "apt":
        return f"{_CONFIRM_ERROR} {_CONFIRM_TAIL}"
    bloqueo = identity_block(chk)
    return f"{bloqueo} {_CONFIRM_TAIL}" if bloqueo else None


def _approve_action(row_ctx: dict, chk, *, configured: bool, requested: bool,
                    now: datetime) -> dict:
    """El botón de aprobar de una fila revisable en el modo `sii`.

    `label` y el camino salen de `EnrollmentRequestService.approval_path` +
    `APPROVAL_LABELS` (Ruling R8, la misma decisión que `sii-check`): con
    cuenta, la liga; sin cuenta y con el NIP del SII `available`, «dar
    acceso»; cualquier otro estado —o sin consulta— «pasar a Accesos», que
    es lo único que manda `to_access`. Lo que ocurre de verdad lo decide
    `approve_detailed` bajo el lock (si entretanto apareció la cuenta, sale
    la liga aunque diga Accesos).

    Con el SII sin configurar (D11) el `nip_status` de una consulta vieja NO
    cuenta (Ruling R10): «dar acceso» le pediría el NIP a un SII que no hay,
    así que sin cuenta es siempre «pasar a Accesos» (la celda sí sigue
    mostrando ese último veredicto).

    `confirm`: el texto de `_approve_confirm` (`requested` = SE acaba de pedir
    la consulta de esta fila). Con el SII sin configurar (D11) no hay consulta
    nueva posible: sin consulta, o con una que no terminó o terminó en error,
    no hay veredicto que discutir (`None`); pero una consulta VIEJA que sí
    marcó un problema —«No apta» o la identidad sin confirmar
    (`identity_block`) en una apta— se sigue pintando en la celda (Ruling R10)
    y pide la MISMA confirmación con su motivo (revisión final F6): con
    cuenta, aprobar manda la liga al correo tecleado, justo lo que D7 ataja.
    """
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        APPROVAL_LABELS, EnrollmentRequestService,
    )

    nip_status = chk.nip_status if (configured and chk is not None) else None
    path = EnrollmentRequestService.approval_path(row_ctx["has_account"], nip_status)
    if configured:
        confirm = _approve_confirm(chk, now=now, requested=requested)
    elif chk is not None and chk.status in ("not_apt", "apt"):
        # Veredicto terminado: `_approve_confirm` da el motivo de «No apta» o
        # el de `identity_block` (una apta limpia sigue sin confirmación).
        confirm = _approve_confirm(chk, now=now)
    else:
        confirm = None
    return {
        "label": APPROVAL_LABELS[path],
        "to_access": path == "access",
        "confirm": confirm,
    }


def _approve_notice(db, req, detail: str):
    """Qué pasó tras aprobar en el modo `sii`: `(mensaje, tipo)` o `None`.

    Mismo patrón que `access_admin._grant_notice`: la fila sale de «Por
    revisar», así que sin esto SE no sabría si el correo salió. `req` ya viene
    refrescada tras los commits del servicio (el sello del correo va en uno
    propio). Nunca lleva el NIP: solo el folio, que ya se pinta en Inscritas.

    - `converted` con `nip_source == "sii"` («Aprobar y dar acceso»): folio y,
      con `EnrollmentRequestService.access_mail_unsent` (ÚNICO predicado de
      «correo no enviado»), si el correo de acceso salió.
    - `awaiting_access` (pasó a Accesos): a dónde fue.
    - `approved` (liga): si salió (`verify_sent_at`; `_issue_activation` lo
      pone en NULL al emitir, así que no es el de una liga anterior).
    """
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )

    if req.status == "converted" and req.nip_source == "sii":
        folio = detail
        if not folio and req.converted_process_id:
            proc = db.get(TitulationProcess, req.converted_process_id)
            folio = proc.folio if proc is not None else ""
        if EnrollmentRequestService.access_mail_unsent(req):
            return _MSG_ACCOUNT_UNMAILED.format(folio=folio), "warning"
        return _MSG_ACCOUNT_MAILED.format(folio=folio), "success"
    if req.status == "awaiting_access":
        return _MSG_TO_ACCESS, "success"
    if req.status == "approved":
        if req.verify_sent_at is not None:
            return _MSG_LINK_MAILED, "success"
        return _MSG_LINK_UNMAILED, "warning"
    return None


def _filters_from(form) -> dict:
    """Los filtros de la bandeja que viajan en cada formulario de fila
    (`tab_fields`): una acción re-pinta con la MISMA carrera y el MISMO año."""
    return {"program": form.get("program"), "year": form.get("year")}


def _body_ctx(db, *, user_id: int, status, cohort_id, q=None, page=1,
              requested_id: int | None = None, per_page: int = PAGE_SIZE,
              program=None, year=None):
    """Contexto del parcial. Distingue los DOS vacíos (riesgo 3 del diseño).

    Paginado (spec 2026-10-04 §4): `page` es un `Page` cuyas `items` son las
    filas YA armadas (`rows` es la misma lista); una página fuera de rango cae
    en la última válida, así que una acción que vacía la última página
    re-pinta la anterior. `q` filtra con `enrollment_request_search`.
    `tab_counts` = solicitudes por pestaña con el MISMO alcance, convocatoria
    y búsqueda que la lista (un `GROUP BY status`); los KPIs (`stats()`) siguen
    siendo el universo sin pestaña, sin búsqueda y sin página.

    Filtros (2026-10-06): `program` (Carrera) y `year` (Año de ingreso, el
    `slug` de `by_year`), con nombres propios porque `program_id` ya es la
    carrera que se elige al APROBAR. Se normalizan contra las opciones que la
    plantilla ofrece, como `status`: una carrera fuera del alcance (o que no
    existe) o un año que no aparece cae a «todas», nunca amplía nada.
    - La carrera acota TODO como si fuera el alcance: KPIs, «Por año de
      ingreso», contadores de pestaña y lista.
    - El año acota la lista y los contadores de pestaña (como `q`); KPIs y
      «Por año de ingreso» siguen siendo el universo de la carrera, así que el
      bloque por año muestra todos los años.

    «¿Tiene cuenta?» se calcula aquí igual que en `approve()`: el número de
    control contra `core_users`, HOY, y solo si casa `CONTROL_NUMBER_RE` (la
    misma guarda que `EligibilityService.check`, la aprobación y `sii-check`:
    un control mal formado cuenta como SIN cuenta). Si la bandeja y el
    servicio se separan, la fila promete un NIP que no se aplica o esconde una
    liga que sí sale.

    Modo `sii`: la consulta VIGENTE de cada fila, en TODAS las pestañas, se
    carga en UNA consulta (nunca `latest_check` por fila); `_sii_cell` arma su
    celda y `_approve_action` su botón. `requested_id` = la solicitud cuya
    consulta SE acaba de pedir (`reconsultar`).
    """
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import (
        Cohort, EligibilityCheck, EnrollmentRequest, TitulationProcess,
    )
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        APPROVAL_LABELS, EnrollmentRequestService, enrollment_request_search,
        entry_year_filter,
    )
    from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

    tab = _tab(status)
    q = normalize_q(q)
    page = parse_page(page)
    scope = _officer_scope(db, user_id)
    mode = EnrollmentRequestService.reviewer_mode()
    sii = mode == "sii"
    configured = EligibilityService.sii_configured()
    ctx = {"rows": [], "status": tab, "tabs": _TABS, "cohort_id": cohort_id,
           "q": q or "", "page": Page(items=[], total=0, page=1, per_page=per_page),
           "tab_counts": {key: 0 for key, _label in _TABS},
           "programs": [], "no_programs": False,
           # Modo alterno = solo lectura: la plantilla no pinta ni un formulario
           # (las rutas POST lo cortan aparte, `_alternate_mode_block`).
           "mode": mode, "can_act": mode != "computer_center", "sii": sii,
           # D11: con el backend `disabled` la plantilla avisa arriba de la
           # tabla (solo en el modo `sii`: fuera de él no se habla del SII).
           "sii_configured": configured,
           # «Revocar inscripción»: el formulario solo a quien la ruta va a
           # dejar pasar (patrón `can_export` de `handoff_admin.py`); se
           # calcula abajo, después del corte de «sin alcance».
           "can_revoke": False,
           # Días de la liga para el texto de la cabecera: de la MISMA fuente
           # que el vencimiento en BD y el correo, nunca un literal.
           "link_days": EnrollmentRequestService.link_ttl_days(),
           "kpis": {"total": 0, "review": 0, "access": 0, "sent": 0, "converted": 0,
                    "rejected": 0},
           "by_year": [], "year_max": 0, "years_summary": None,
           # Filtros (ya normalizados abajo): `program_filter` es el id o None,
           # `year_filter` el `slug` de `by_year` o "". `scope_all` cambia el
           # texto de la opción vacía («Todas las carreras» / «Todas mis carreras»).
           "program_filter": None, "year_filter": "", "scope_all": scope == "ALL"}

    if scope != "ALL" and not scope:
        # Conjunto vacío = no ve nada, EN SILENCIO. Se marca explícitamente para
        # que la plantilla no muestre "no hay solicitudes" (ni KPIs: no hay
        # universo que contar).
        ctx["no_programs"] = True
        return ctx

    if ctx["can_act"]:
        from itcj2.core.services.authz_cache import cached_perms
        ctx["can_revoke"] = _CANCEL[0] in cached_perms(
            db, user_id, "titulatec")

    # El <select> del formulario de aprobar solo puede ofrecer carreras que la
    # ruta vaya a aceptar (Finding 1, ronda 1 de revisión). Es también la lista
    # del filtro «Carrera»: lo que no está aquí no se puede filtrar.
    programs_q = db.query(Program).order_by(Program.name)
    if scope != "ALL":
        programs_q = programs_q.filter(Program.id.in_(scope))
    programs = [{"id": p.id, "name": p.name} for p in programs_q.all()]
    ctx["programs"] = programs

    # Filtro «Carrera»: solo una de las opciones; acota todo como el alcance.
    eff_scope = scope
    pid = _to_int(program)
    if pid is not None and any(p["id"] == pid for p in programs):
        ctx["program_filter"] = pid
        eff_scope = {pid}

    # KPIs y "por año de ingreso": MISMO alcance (y carrera) y convocatoria que
    # el listado de abajo, pero sin filtro de pestaña, sin búsqueda, sin año y
    # sin paginar — es el universo completo, no la página visible.
    stats = EnrollmentRequestService.stats(db, scope=eff_scope, cohort_id=cohort_id)
    ctx["kpis"] = stats["counts"]
    ctx["by_year"] = stats["by_year"]
    ctx["year_max"] = stats["year_max"]
    ctx["years_summary"] = stats["summary"]

    # Filtro «Año de ingreso»: solo un año que el bloque de arriba cuenta (sus
    # `slug`), así el filtro y el conteo salen de la misma regla (`entry_year`).
    year_value = next((y["year"] for y in ctx["by_year"] if y["slug"] == year), None)
    if year_value is not None:
        ctx["year_filter"] = year

    # Alcance + convocatoria + búsqueda: lo comparten la lista y el contador por
    # pestaña (el alcance se aplica ANTES de contar y paginar, §3.3).
    base = db.query(EnrollmentRequest)
    if eff_scope != "ALL":
        # Una solicitud sin `program_id` (carrera en texto libre) solo la ve
        # quien tiene alcance total: resolverla es justo lo que hace el jefe.
        base = base.filter(EnrollmentRequest.program_id.in_(eff_scope))
    if cohort_id:
        base = base.filter(EnrollmentRequest.cohort_id == cohort_id)
    search = enrollment_request_search(q)
    if search is not None:
        base = base.filter(search)
    if year_value is not None:
        base = base.filter(entry_year_filter(EnrollmentRequest.control_number, year_value))

    # Contador por pestaña (D7): un GROUP BY status sobre el mismo universo.
    by_status = dict(base.with_entities(EnrollmentRequest.status, func.count())
                     .group_by(EnrollmentRequest.status).order_by(None).all())
    for key, _label in _TABS:
        statuses = _TAB_STATUSES[key]
        ctx["tab_counts"][key] = (sum(by_status.values()) if statuses is None
                                  else sum(by_status.get(st, 0) for st in statuses))

    lq = base
    if _TAB_STATUSES[tab] is not None:
        lq = lq.filter(EnrollmentRequest.status.in_(_TAB_STATUSES[tab]))
    if tab == "pending_review":
        # FIFO (2026-09-24): «Por revisar» es una cola de trabajo, no un
        # archivo — se atiende en el orden en que llegó; la página 1 siempre
        # es la de las más viejas.
        lq = lq.order_by(EnrollmentRequest.created_at.asc(), EnrollmentRequest.id.asc())
    elif tab == "awaiting_access":
        # FIFO también (spec 2026-09-27 D10; Ruling R4: en todos los modos, es
        # la misma cola): se atiende en el orden en que SE la mandó a Centro de
        # Cómputo, `reviewed_at`, no en el de llegada del formulario.
        lq = lq.order_by(EnrollmentRequest.reviewed_at.asc(), EnrollmentRequest.id.asc())
    else:
        # El resto de pestañas son historial: se sigue leyendo de lo último
        # que pasó hacia atrás.
        lq = lq.order_by(EnrollmentRequest.created_at.desc(), EnrollmentRequest.id.desc())
    pg = paginate_query(lq, page, per_page)
    reqs = pg.items

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
    cohort_names = ({cid: name for cid, name in db.query(Cohort.id, Cohort.name)
                     .filter(Cohort.id.in_(cohort_ids)).all()} if cohort_ids else {})
    prog_names = {p["id"]: p["name"] for p in programs}
    # Consultas VIGENTES del SII, en lote (nunca `latest_check` por fila), de
    # TODAS las filas: la columna «SII» está en cada pestaña. Solo en el modo
    # `sii`: fuera de él la bandeja no habla del SII.
    checks = {}
    if sii:
        check_ids = {r.last_check_id for r in reqs if r.last_check_id}
        checks = ({c.id: c for c in db.query(EligibilityCheck)
                   .filter(EligibilityCheck.id.in_(check_ids)).all()} if check_ids else {})
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

    # Motivo de cada revocada en UNA consulta (antes, una por fila revocada).
    revocations = ProcessService.cancellation_info_map(
        db, [procs[r.converted_process_id] for r in reqs
             if r.status == "converted" and r.converted_process_id in procs])

    # Rechazadas sin `rejection_sent_at` cuyo correo sigue en el outbox (spec
    # 2026-10-05 §3.7): «en cola», no «correo no enviado». UNA consulta, y
    # solo si en la página hay alguna rechazada sin sello.
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    queued = StudentMail.queued_requests(
        db, [r.id for r in reqs if r.status == "rejected" and r.rejection_sent_at is None])

    for r in reqs:
        # Un control mal formado no se busca (ya viene en el lote, sin N+1):
        # `approve` tampoco lo haría, así que la fila no promete la liga.
        u = (users.get(r.control_number)
             if CONTROL_NUMBER_RE.fullmatch((r.control_number or "").strip()) else None)
        proc = procs.get(r.converted_process_id)
        # La regla es la del servicio: el ÚLTIMO `process_cancelled` y solo si
        # el proceso sigue `cancelled` (`cancellation_info_map`).
        revoked = (revocations.get(proc.id)
                   if r.status == "converted" and proc is not None else None)
        has_account = u is not None
        reviewable = r.status in _TAB_STATUSES["pending_review"]
        chk = checks.get(r.last_check_id) if sii else None
        # Celda completa en lo pendiente (también en «Todas»), compacta en el
        # historial. El legado (`unverified`/`verified`) no tiene consulta
        # posible (`check` no lo consulta): queda «Sin consultar», y la
        # plantilla solo ofrece «Reintentar» a `pending_review`.
        sii_cell = (_sii_cell(chk, has_account=has_account, compact=not reviewable,
                              now=now, max_attempts=max_attempts,
                              requested=(r.id == requested_id), configured=configured)
                    if sii else None)
        if not reviewable:
            approve = None
        elif sii:
            approve = _approve_action({"has_account": has_account}, chk,
                                      configured=configured,
                                      requested=(r.id == requested_id), now=now)
        else:
            # Modos oficial y alterno: los botones de siempre, sin confirmar.
            approve = {"label": (APPROVAL_LABELS["link"] if has_account
                                 else _LABEL_TO_COMPUTER_CENTER),
                       "to_access": False, "confirm": None}
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
            "cohort": cohort_names.get(r.cohort_id, ""),
            "created": r.created_at.strftime("%d/%m/%Y") if r.created_at else "",
            "status": r.status,
            "status_label": _STATUS_LABELS.get(r.status, r.status),
            "reviewable": reviewable,
            "has_account": has_account,
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
            # Rechazo deshecho por SE (`reopen`): igual que `returned`, solo
            # mientras vuelve a ser trabajo de SE.
            "reopened": (r.reopened_at is not None
                         and r.status in _TAB_STATUSES["pending_review"]),
            "reopen_note": r.reopen_note or "",
            # Solo tiene sentido leerla en una fila `rejected`: el correo de
            # rechazo es lo único que sella esta columna (el despachador del
            # outbox, o `reject()` con el correo apagado).
            "rejection_sent": r.rejection_sent_at is not None,
            "rejection_queued": r.id in queued,
            "prior_reject": prior_reject,
            # «Reenviar aviso» (spec 2026-09-27 D12): la cuenta nació con el
            # NIP del SII y su correo de acceso no salió. Lo mismo que exige
            # `EnrollmentRequestService.resend_access_notice` (que además
            # comprueba, bajo el lock, que la cuenta sea la del proceso).
            "access_unsent_sii": (r.status == "converted" and r.nip_source == "sii"
                                  and r.access_sent_at is None),
            "sii": sii_cell,
            "approve": approve,
        })
    ctx["page"] = dataclasses.replace(pg, items=ctx["rows"])
    return ctx


@router.get("", name="titulatec.pages.requests.list")
def list_requests(request: Request, status: str = "", cohort_id: str = "",
                  q: str = "", page: str = "", program: str = "", year: str = "",
                  user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status,
                        cohort_id=_to_int(cohort_id), q=q, page=page,
                        program=program, year=year)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/requests.html", ctx)


@router.get("/body", name="titulatec.pages.requests.body")
def body(request: Request, status: str = "", cohort_id: str = "",
         q: str = "", page: str = "", program: str = "", year: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status=status,
                        cohort_id=_to_int(cohort_id), q=q, page=page,
                        program=program, year=year)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/aprobar", name="titulatec.pages.requests.approve")
async def approve(req_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """Aprueba una solicitud (`EnrollmentRequestService.approve_detailed`).

    Con cuenta emite la liga de activación. Sin cuenta: en el modo oficial pasa
    a «En Cómputo» (`awaiting_access`); en el modo `sii` crea la cuenta con el
    NIP del SII, o la pasa a Accesos si el formulario manda `to_access=1`
    («Aprobar y pasar a Accesos»). Si en `sii` el SII no da un NIP válido al
    aprobar, responde 200 con la bandeja re-pintada y el motivo en
    `X-Tt-Notice` (warning): un 4xx no dejaría a HTMX re-pintar la fila, que
    ya ofrece Accesos. Cualquier otro fallo, 400 + `X-Tt-Error`. Con el SII
    sin configurar (D11) aprobar sin cuenta ES pasar a Accesos
    (`approve_detailed`, revisión final F8).

    En el modo `sii` un éxito lleva además `X-Tt-Notice` con lo que pasó
    (`_approve_notice`, revisión final F9): cuenta creada con su folio y si
    el correo salió, pasó a Accesos, o liga enviada / sin enviar. Los modos
    oficial y alterno quedan sin aviso, como siempre.

    La ruta no lee `nip`: un formulario viejo en caché que lo mande se ignora,
    y el NIP nunca aparece en un log ni en una cabecera (los motivos del
    servicio no lo llevan)."""
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_approve, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_approve(req_id, request, user, form):
    """Cuerpo síncrono de `approve`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    program_id = _to_int((form.get("program_id") or "").strip())
    to_access = (form.get("to_access") or "").strip() == "1"
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")

    aviso = None
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        # Alcance por carrera (Finding 1, ronda 1 de revisión): 404 liso, sin
        # `X-Tt-Error`, para que "no existe" y "no es tuya" sean indistinguibles.
        scope = _officer_scope(db, uid)
        req = _load_scoped_request(db, scope, req_id)
        if req is None:
            return Response(status_code=404)
        if program_id and not _program_in_scope(scope, program_id):
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Esa carrera no está en tu alcance.")})
        try:
            # `nip=""`: ni el modo oficial ni el `sii` lo usan, y en el alterno
            # esta ruta ya cortó arriba. Todo el cuerpo corre en el threadpool
            # (`_cuerpo_approve`), no en el event loop: en modo `sii` pide el NIP
            # al SII (pyodbc, bloqueante, hasta sus timeouts) y congelaría el
            # proceso HTTP entero (revisión final C6).
            result = EnrollmentRequestService.approve_detailed(
                db, req_id, nip="", program_id=program_id, actor_id=uid,
                to_access=to_access)
        except Exception as exc:
            # `approve_detailed` es dueña de su transacción: un fallo real en cualquier
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
        if not result.ok and not result.nip_failure:
            # `detail` nunca contiene el NIP, y `approve_detailed` no deja nada
            # escrito cuando falla (invariante de su docstring).
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(result.detail)})
        if result.ok and EnrollmentRequestService.reviewer_mode() == "sii":
            # Tras los commits del servicio (el sello del correo va en uno
            # propio): el estado y los sellos que decide el aviso.
            db.refresh(req)
            aviso = _approve_notice(db, req, result.detail)
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)
    if result.nip_failure:
        # Nada escrito de la solicitud; su consulta ya dice el estado del NIP.
        aviso = (f"{result.detail} {_MSG_NIP_FAILURE_TAIL}", "warning")
    if aviso is not None:
        resp.headers["X-Tt-Notice"] = _hdr(aviso[0])
        resp.headers["X-Tt-Notice-Kind"] = aviso[1]
    return resp


@router.post("/{req_id}/rechazar", name="titulatec.pages.requests.reject")
async def reject(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Rechaza, o cancela una solicitud con la liga enviada o en Centro de
    Cómputo. Motivo obligatorio: es lo que la persona lee en su correo.

    El correo se encola (spec 2026-10-05 §3.7): la respuesta lleva
    `X-Tt-Notice` «Se enviará el correo al egresado» (`_MSG_REJECT_QUEUED`)
    mientras su fila siga en el outbox. Con el correo apagado ya salió en
    línea, y la respuesta es la de siempre (sin aviso; la píldora dice si
    salió)."""
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_reject, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_reject(req_id, request, user, form):
    """Cuerpo síncrono de `reject`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    from itcj2.apps.titulatec.services.student_mail import StudentMail
    note = (form.get("note") or "").strip()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")
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
        en_cola = req_id in StudentMail.queued_requests(db, [req_id])
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)
    if en_cola:
        resp.headers["X-Tt-Notice"] = _hdr(_MSG_REJECT_QUEUED)
        resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


@router.post("/{req_id}/reabrir", name="titulatec.pages.requests.reopen")
async def reopen(req_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REJECT))):
    """Deshace un rechazo: la persona aclaró en ventanilla y la solicitud
    vuelve a «Por revisar» (`EnrollmentRequestService.reopen`). Nota
    obligatoria con lo que se aclaró; sin correo. Mismo permiso que rechazar:
    quien puede rechazar puede deshacerlo."""
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_reopen, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_reopen(req_id, request, user, form):
    """Cuerpo síncrono de `reopen`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    note = form.get("note") or ""
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        ok, detalle = EnrollmentRequestService.reopen(db, req_id, note=note, actor_id=uid)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detalle)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(_MSG_REOPENED)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


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

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_resend, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_resend(req_id, request, user, form):
    """Cuerpo síncrono de `resend`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        ok, detail = EnrollmentRequestService.resend_link(db, req_id)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)


@router.post("/{req_id}/reenviar-aviso", name="titulatec.pages.requests.resend_notice")
async def resend_notice(req_id: int, request: Request,
                        user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """«Reenviar aviso» desde Inscritas (spec 2026-09-27 D12).

    Vuelve a mandar el correo de acceso de una cuenta que nació con el NIP DEL
    SII y cuyo correo no salió (`EnrollmentRequestService.resend_access_notice`).
    El correo no lleva el NIP y no se toca ninguna credencial. Mismo permiso,
    corte del modo alterno y alcance por carrera que aprobar (404 liso). Sin
    aviso pendiente o si el correo no sale, 400 + `X-Tt-Error`; si sale, la
    bandeja re-pintada (la fila ya sin la marca) + `X-Tt-Notice`.
    """
    bloqueo = _alternate_mode_block()
    if bloqueo is not None:
        return bloqueo

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_resend_notice, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_resend_notice(req_id, request, user, form):
    """Cuerpo síncrono de `resend_notice`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        scope = _officer_scope(db, uid)
        if _load_scoped_request(db, scope, req_id) is None:
            return Response(status_code=404)
        ok, detail = EnrollmentRequestService.resend_access_notice(db, req_id)
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(detail)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    resp = render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(_MSG_NOTICE_RESENT)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


@router.post("/{req_id}/reconsultar", name="titulatec.pages.requests.recheck")
async def reconsultar(req_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=_APPROVE))):
    """«Reintentar consulta» (modo `sii`): encola una consulta FORZADA al SII.

    `enqueue_check(req_id, force=True)` después de validar; la consulta corre
    en celery (el SII puede tardar lo que sus timeouts: nunca en la petición
    web). Si no se pudo encolar (broker caído), 400 con el motivo: no se
    anuncia una consulta que nadie va a hacer. No duplica: con la consulta vigente `pending` y fresca responde 400
    sin encolar (`EligibilityService.check` tampoco la repetiría), y la bandeja
    que devuelve ya pinta esa fila «Consultando…» sin el botón. Una `pending`
    colgada (más de `_PENDING_STALE`) sí se reintenta: `force` la retoma.
    Mismo permiso y alcance por carrera que aprobar; 404 liso fuera de alcance.
    Con el SII sin configurar (spec 2026-09-27 D11) no hay a quién preguntar:
    400 `_MSG_SII_OFF` antes de abrir sesión, como el corte de modo.
    """
    bloqueo = _recheck_block()
    if bloqueo is not None:
        return bloqueo
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_reconsultar, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_reconsultar(req_id, request, user, form):
    """Cuerpo síncrono de `reconsultar`: corre en el threadpool, no en el event loop."""
    from itcj2.apps.titulatec.services import eligibility_service as elig
    from itcj2.database import SessionLocal

    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")

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
        # de la solicitud. `enqueue_check` nunca lanza: dice si encoló.
        if not elig.enqueue_check(req.id, force=True):
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr(_MSG_RECHECK_NOT_QUEUED)})
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form), requested_id=req.id)
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

    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_revocar, req_id=req_id, request=request, user=user, form=form)


def _cuerpo_revocar(req_id, request, user, form):
    """Cuerpo síncrono de `revocar`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService

    reason = (form.get("reason") or "").strip()
    tab, tab_cohort = form.get("status"), _to_int(form.get("cohort_id"))
    tab_q, tab_page = form.get("q"), form.get("page")
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
        ctx = _body_ctx(db, user_id=uid, status=tab, cohort_id=tab_cohort,
                        q=tab_q, page=tab_page, **_filters_from(form))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/requests_body.html", ctx)

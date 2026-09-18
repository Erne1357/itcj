"""Páginas del alumno en TitulaTec (mobile-first)."""
import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.student")

router = APIRouter(prefix="/student", tags=["titulatec-pages-student"])

# Documentos de la fase 1 (iniciales). egel_proof solo aplica a modalidad EGEL.
_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

# --- Contenido del acordeón de fase (alumno) -------------------------------
# Una entrada por código de fase (titulatec_phase_definitions.code):
#   desc  : qué es la fase, en 1-2 frases.
#   needs : "Qué vas a necesitar" — 2-5 viñetas concretas (docs, requisitos, pagos, firmas).
#   who   : qué hace el alumno vs. qué hace la institución, en una línea.
# `_PHASE_HELP` se deriva de aquí (abajo) para no romper a quien ya lo consume.
_PHASE_INFO = {
    "cohort_intake": {
        "desc": "Servicios Escolares te dio de alta en la convocatoria. Tu proceso ya está "
                "activo con la carrera y la modalidad que registraste.",
        "needs": [
            "Tu número de control: es tu usuario y también tu contraseña la primera vez "
            "(la app te obliga a cambiarla).",
            "Tu correo institucional @cdjuarez.tecnm.mx.",
            "Tu carrera y tu modalidad de titulación bien registradas.",
        ],
        "who": "Servicios Escolares te da de alta; tú solo revisas que tus datos estén correctos.",
    },
    "initial_docs": {
        "desc": "Sube tu acta de nacimiento, tu certificado de bachillerato y tu CURP "
                "certificada. Son los mismos que vas a llevar en físico a la cita de cotejo.",
        "needs": [
            "Acta de nacimiento (PDF).",
            "Certificado de bachillerato (PDF).",
            "CURP certificada (PDF): la impresión certificada, no la simple.",
            "Cada archivo va en PDF y pesa máximo 10 MB.",
            "Cuando estén los 3, toca «Enviar a revisión».",
        ],
        "who": "Tú subes los tres archivos; Servicios Escolares los revisa y los aprueba "
               "o te pide corregir.",
    },
    "review_appointment": {
        "desc": "Servicios Escolares te asigna fecha, hora y lugar del cotejo. Confirma tu "
                "asistencia y preséntate con tus documentos físicos. Si no puedes ese día, "
                "solicita un cambio.",
        "needs": [
            "Actas de nacimiento: original y copias.",
            "CURP certificada, e.Firma del SAT vigente y vigencia de derechos del IMSS.",
            "No-adeudo de biblioteca y comprobante de la encuesta de egresados.",
            "12 fotografías tamaño credencial: ovaladas, B/N, fondo blanco, papel mate.",
            "$1,900 en efectivo para el pago del proceso.",
        ],
        "who": "Tú confirmas y llevas los documentos; Servicios Escolares hace el cotejo "
               "y aprueba la fase.",
    },
    "format_b": {
        "desc": "Llena el Formato B en tres pasos: datos personales, datos escolares y "
                "proyecto. Se guarda al pasar de paso, así que puedes ir y volver.",
        "needs": [
            "Personales: nombre completo, sexo, edad, celular, teléfono y domicilio "
            "(CP, colonia, calle, número exterior e interior).",
            "Escolares: plan de estudios, mes de ingreso y mes de egreso.",
            "Proyecto: el nombre de tu proyecto.",
            "Tu número de control, tu carrera y tu modalidad ya vienen precargados.",
        ],
        "who": "Tú lo llenas y lo envías; el Depto. de Titulación lo aprueba o te lo "
               "regresa con observaciones.",
    },
    "synodal_assignment": {
        "desc": "Vinculación asigna a tus sinodales (presidente, secretario y vocal) y abre "
                "el chat de titulación de tu proceso. Aquí no tienes nada que entregar.",
        "needs": [
            "Tener tu Formato B aprobado: es lo único que detona esta fase.",
            "Esperar el aviso; el plazo de referencia son 5 días hábiles (informativo).",
            "Ir preparando tu trabajo en PDF: lo vas a compartir en la fase siguiente.",
        ],
        "who": "Vinculación asigna a los sinodales y abre el chat; tú esperas el aviso.",
    },
    "synodal_review": {
        "desc": "Tus sinodales revisan tu trabajo en el chat de titulación de la app. Ahí te "
                "piden cambios y ahí subes las versiones corregidas.",
        "needs": [
            "Tu trabajo en PDF (informe de residencia, tesis o proyecto) para subirlo al chat.",
            "Atender los cambios que te pidan y volver a subir la versión corregida.",
            "Por residencias basta el Vo.Bo. del presidente; en tesis y proyecto de "
            "investigación aprueban todos los sinodales.",
        ],
        "who": "Tus sinodales revisan y votan; tú corriges hasta que liberen tu trabajo.",
    },
    "anexo_iii": {
        "desc": "Ya que liberan tu trabajo, descargas el Anexo III, juntas las firmas en "
                "físico y lo subes escaneado.",
        "needs": [
            "Descargar el Anexo III desde la app.",
            "Las firmas: por residencias, solo la del presidente; en tesis y proyecto de "
            "investigación, la de todos los sinodales.",
            "Escanearlo y subirlo en PDF (máximo 10 MB).",
        ],
        "who": "El Depto. de Titulación habilita el documento; tú consigues las firmas y "
               "lo subes escaneado.",
    },
    "final_docs": {
        "desc": "Entregas los documentos que cierran tu expediente y pasas a la primera "
                "revisión con el Depto. de Titulación.",
        "needs": [
            "Identificación oficial (INE) en PDF.",
            "Comprobante de acreditación de residencias en PDF.",
            "Tu Anexo III firmado, ya subido en la fase anterior.",
            "El listado exacto de copias para la revisión presencial del expediente está "
            "pendiente de confirmar por Servicios Escolares.",
        ],
        "who": "Tú subes los archivos; el Depto. de Titulación revisa tu expediente y "
               "aprueba la fase.",
    },
    "ceremony": {
        "desc": "El Depto. de Titulación te asigna fecha y aula del acto protocolario. Hasta "
                "entonces subes tu trabajo final y tu presentación.",
        "needs": [
            "Estar pendiente de la fecha, el aula y el grupo de WhatsApp del acto.",
            "Trabajo final en PDF.",
            "Presentación del acto.",
            "De tu trabajo final solo se revisa la portada; la presentación es libre.",
        ],
        "who": "El Depto. de Titulación organiza el acto; tú subes tu trabajo final y tu "
               "presentación.",
    },
}

# Compatibilidad: la instrucción breve sigue disponible como antes.
_PHASE_HELP = {code: info["desc"] for code, info in _PHASE_INFO.items()}

# CTA del alumno por código de fase (solo las soportadas hoy).
_PHASE_CTA = {
    "initial_docs":       ("/titulatec/student/documents", "Ir a documentos", "file-earmark-arrow-up"),
    "review_appointment": ("/titulatec/student/cita", "Ver requisitos", "calendar-check"),
    "format_b":           ("/titulatec/student/formato-b", "Llenar Formato B", "pencil-square"),
}

# Quién es responsable de la fase (para fases que el alumno no acciona).
_RESPONSIBLE_LABEL = {
    "school_services": "Servicios Escolares",
    "titulaciones":    "el Depto. de Titulación",
    "vinculacion":     "Vinculación",
    "synodals":        "tus sinodales",
    "student":         "ti",
}

# Etiqueta legible de cada evento del timeline.
_EVENT_LABELS = {
    "phase_approved":              "Fase aprobada",
    "phase_rejected":              "Fase rechazada",
    "appointment_scheduled":       "Cita agendada",
    "appointment_confirmed":       "Confirmaste tu asistencia",
    "appointment_in_progress":     "Cotejo en proceso",
    "appointment_attended":        "Asististe al cotejo",
    "appointment_rescheduled":     "Cita reagendada",
    "appointment_change_requested":"Solicitaste un cambio de cita",
    "appointment_no_show":         "No te presentaste a la cita",
    # Lo escribe `AppointmentService.cancel`, que comparten el alumno (desde
    # «Cancelar mi cita») y el encargado. La etiqueta es NEUTRAL a propósito:
    # es el mismo `event_type` para los dos actores, así que «Cancelaste tu
    # cita» sería mentira cuando quien canceló fue Servicios Escolares. Sin
    # esta fila la línea de tiempo del alumno enseñaba el código crudo.
    "appointment_cancelled":       "Cita cancelada",
    # Mismo defecto que el de arriba, en el mismo dict: lo escribe
    # `AppointmentService.undo_no_show` y salía en crudo.
    "appointment_undo_no_show":    "Se corrigió tu asistencia",
    "process_completed":           "Proceso completado",
    # Solicitud de liberación de GTV para la encuesta de egresados (D3, spec
    # 2026-09-15-titulatec-liberacion-gtv §6.1). Mismos `event_type` que
    # escribe `SurveyReviewService._log`.
    "survey_review_submitted":     "Enviaste la encuesta de egresados",
    "survey_review_approved":      "Gestión Tecnológica y Vinculación liberó tu encuesta",
    "survey_review_rejected":      "Gestión Tecnológica y Vinculación dejó observaciones",
    "survey_review_revoked":       "Se revocó la liberación de tu encuesta",
}


_DASHBOARD_URL = "/titulatec/student/dashboard"

# Encuesta de egresados: mismo path que `pages/public.py::SURVEY_URL` (Tarea 3).
# Literal propio y no un import de ese módulo (en edición paralela en este
# checkout) para no acoplar dos archivos que dos tareas tocan a la vez.
_SURVEY_URL = "/titulatec/encuesta-egresados"


# ===========================================================================
# Guarda de fase del alumno (traducción HTTP de PhaseService)
# ===========================================================================
# La regla la decide `PhaseService.assert_student_can_act` (gemela de
# `assert_can_transition`, la del admin). Aquí solo se traduce al canal que
# corresponde, que son DOS porque las rutas del alumno son de dos naturalezas:
#
#   * mutación o parcial HTMX  -> `_phase_guard`      -> 400 + `X-Tt-Error`
#   * página completa          -> `_phase_guard_page` -> 302 al acordeón
#
# **Por qué 400 y no 409.** Los 14 `X-Tt-Error` del árbol viajan en 400 —incluida
# la guarda gemela del admin, fijada por `tests/.../test_phase_guard.py`— mientras
# que el 409 pelado ya significa otra cosa en ESTAS MISMAS rutas ("no tienes
# proceso": abajo, 4 sitios). Reusar 409 haría indistinguibles dos condiciones
# distintas sobre la misma URL.
#
# **Por qué 302 y no 404 en las páginas.** El alumno que llega por un enlace viejo
# —una notificación que sigue viva en `core_notifications`, un marcador, el
# historial del shell— tiene que aterrizar donde SE LE EXPLICA la fase. Eso es
# exactamente el acordeón del dashboard: `_phases_ctx` emite `desc`/`needs`/`who`
# de las 9 fases y `_cta_for` no emite ninguna acción fuera de la actual, así que
# ya ES la vista de solo lectura — no hace falta una segunda plantilla que se
# desincronice. Un 404 sería un callejón sin salida y además mentiría: la página
# existe, no es su turno. Mismo mecanismo, mismo 302 y mismo motivo que
# `/student/fase/{n}` (ver su docstring: un 301/308 lo cachearía el navegador
# para siempre).
#
# **Por qué las páginas NO usan 400.** Y al revés: los parciales NO usan 302. htmx
# sigue el redirect de forma transparente y metería el dashboard entero dentro de
# `#formato-b-body`.


def _phase_of(db, code: str) -> int | None:
    """Número de la fase de este código, desde el catálogo. None = fallo cerrado."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    return PhaseService.phase_number_for_code(db, code)


def _phase_guard(db, process, phase_number) -> Response | None:
    """400 + `X-Tt-Error` si el alumno no puede actuar en esa fase, o None.

    Sin proceso devuelve None a propósito: "no tienes proceso" ya tiene su propia
    respuesta en cada ruta (409, o el estado vacío de la página) y no hay fase que
    guardar. La guarda solo opina cuando hay un proceso con `current_phase`.
    """
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    if process is None:
        return None
    try:
        PhaseService.assert_student_can_act(db, process, phase_number)
    except ValueError as exc:
        return Response(status_code=400, headers={"X-Tt-Error": str(exc)})
    return None


def _phase_guard_page(db, process, phase_number) -> Response | None:
    """302 al acordeón de esa fase si la página no es la fase en curso, o None."""
    from fastapi.responses import RedirectResponse
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    if process is None or PhaseService.can_student_act(db, process, phase_number):
        return None
    destino = _DASHBOARD_URL
    if isinstance(phase_number, int) and not isinstance(phase_number, bool):
        destino += f"?fase={phase_number}"
    return RedirectResponse(destino, status_code=302)


def _slot_ctx(dtype, doc, *, error: str | None = None) -> dict:
    """Contexto autónomo de un slot de documento para el parcial."""
    return {
        "dtype": {"code": dtype.code, "name": dtype.name, "file_kind": dtype.file_kind},
        "doc": ({
            "review_status": doc.review_status,
            "review_note": doc.review_note,
            "original_name": doc.original_name,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes or 0,
            "version": doc.version,
        } if doc else None),
        "upload_url": f"/titulatec/student/documents/{dtype.code}",
        "delete_url": f"/titulatec/student/documents/{dtype.code}",
        "error": error,
    }


# ===========================================================================
# Acordeón de fases del dashboard del alumno
# ===========================================================================
# Reemplaza a la pantalla `/student/fase/{n}`: la descripción de cada fase se
# despliega dentro de la propia lista, y la fase ACTUAL no se despliega — su
# información y su CTA salen en grande en la tarjeta "Tu proceso".

# Estado de la cita en lenguaje del alumno: (etiqueta, tono de `pill()`).
_APPT_STUDENT_LABEL = {
    "scheduled":   ("Agendada · falta que confirmes tu asistencia", "navy"),
    "confirmed":   ("Confirmaste tu asistencia", "violet"),
    "in_progress": ("Cotejo en proceso", "amber"),
    "attended":    ("Asististe al cotejo", "success"),
    "no_show":     ("No te presentaste a la cita", "danger"),
    # Los dos estados del historial de intentos (spec 2026-09-15 §2.3). Una
    # cita `cancelled` o `superseded` nunca es la VIGENTE, así que hoy no se
    # alcanzan por `get_for_process`; van aquí porque el respaldo del `.get()`
    # imprime el codigo crudo en ingles, y basta con que alguien pinte el
    # historial en el panel del alumno para que se vuelva visible.
    "cancelled":   ("Cita cancelada", "neutral"),
    "superseded":  ("Cita reagendada", "neutral"),
}


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _docs_progress(summary: dict) -> dict:
    """Sub-progreso de la fase 1: los 3 documentos iniciales."""
    c = summary["counts"]
    total, uploaded = summary["total"], summary["uploaded"]
    if c["rejected"]:
        label = _plural(c["rejected"], "documento", "documentos") + " por corregir"
        tone = "danger"
    elif c["approved"] == total:
        label, tone = f"Los {total} documentos aprobados", "success"
    elif uploaded == 0:
        label, tone = "Aún no subes ningún documento", "neutral"
    elif c["missing"]:
        label, tone = f"{uploaded} de {total} subidos", "amber"
    else:
        label = f"{c['approved']} de {total} aprobados · {c['pending']} en revisión"
        tone = "amber"
    return {
        "kind": "documents",
        "started": uploaded > 0,
        "label": label,
        "tone": tone,
        "total": total,
        "uploaded": uploaded,
        "counts": c,
        "items": summary["items"],
    }


def _appt_progress(appt) -> dict:
    """Sub-progreso de la fase 2: estado de la cita de cotejo."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    if not appt:
        return {"kind": "appointment", "started": False,
                "label": "Aún no te asignan fecha y hora", "tone": "neutral",
                "status": None, "scheduled_label": None, "location": None,
                "confirmed": False, "change_requested": False}

    change_requested = bool(appt and appt.change_request)
    label, tone = _APPT_STUDENT_LABEL.get(appt.status, (appt.status, "neutral"))
    if change_requested:
        label, tone = "Solicitaste un cambio de fecha", "amber"
    return {
        "kind": "appointment",
        "started": True,
        "label": label,
        "tone": tone,
        "status": appt.status,
        "scheduled_label": _cita_label(appt.scheduled_at),
        "location": appt.location,
        "confirmed": appt.confirmed_at is not None,
        "change_requested": change_requested,
    }


def _format_b_progress(fb) -> dict:
    """Sub-progreso de la fase 3: en qué paso va el Formato B y si está enviado."""
    from itcj2.apps.titulatec.services.format_b_service import FormatBService

    prog = FormatBService.progress(fb)
    started = fb is not None and any(s["done"] for s in prog["steps"])
    status = prog["status"]

    if not started and status == "draft":
        label, tone = "Aún no lo empiezas", "neutral"
    elif status == "approved":
        label, tone = "Formato B aprobado", "success"
    elif status == "rejected":
        label, tone = "Te lo regresaron con observaciones", "danger"
    elif status == "submitted":
        label, tone = "Enviado · en revisión del Depto. de Titulación", "amber"
    elif all(s["done"] for s in prog["steps"]):
        label, tone = "Listo para enviar", "amber"
    else:
        label, tone = f"Paso {prog['step']} de {prog['total_steps']}", "amber"

    # Las claves de presentacion van AL FINAL: si `progress()` gana un `label`
    # propio, el del alumno no debe quedar pisado por el del service.
    return {**prog, "kind": "format_b", "started": started, "label": label, "tone": tone}


def _cta_for(code: str, *, is_current: bool, status: str) -> dict | None:
    """CTA de una fase. `_PHASE_CTA` sigue siendo la ÚNICA fuente de los enlaces.

    Solo acciona la fase ACTUAL: las anteriores están cerradas (inmutables) y las
    siguientes son informativas — el alumno se prepara ahí, no ejecuta.
    """
    if not is_current or status == "skipped":
        return None
    entry = _PHASE_CTA.get(code)
    if not entry:
        return None
    url, label, icon = entry
    return {"url": url, "label": label, "icon": icon}


def _phases_ctx(db, process, *, open_phase: int | None = None) -> dict:
    """Contexto del acordeón de las 9 fases + la tarjeta grande de la fase actual.

    **Consultas fijas, no una por fase.** Es la pantalla más visitada del alumno y
    el acordeón se pinta 9 veces por carga: todo lo que necesita se trae de una
    (fases, `ProcessPhase`, `ProcessEvent`, los 3 documentos, la cita, el Formato B)
    y se indexa en memoria. Sin proceso es 1 sola consulta.

    Devuelve::

        {
          "has_process":   bool,
          "current_phase": int,          # 0 si no hay proceso
          "progress_pct":  int,
          "open_phase":    int | None,   # deep-link ?fase=N ya resuelto
          "current":       card | None,  # la MISMA card de la fase actual (col. A)
          "phases":        [card, ...],  # las 9, en orden de catálogo
        }

    Cada ``card``::

        number, code, name, icon, responsible, responsible_label
        status            pending|in_progress|in_review|approved|rejected|skipped
        rel               "past" | "current" | "future"
        is_current        bool
        can_expand        bool   False SOLO en la actual (va grande en la col. A)
        is_open           bool   deep-link: sale desplegada ya en el HTML
        is_target         bool   deep-link: la fase a RESALTAR. Difiere de `is_open`
                                 solo cuando el deep-link apunta a la fase actual,
                                 que no se despliega pero sí se resalta (col. A).
        desc, needs, who         copy de `_PHASE_INFO` ("qué vas a necesitar" = needs)
        cta               {url,label,icon} | None   solo la actual y si está soportada
        rejection_reason  str | None
        events            [{label, when}]   historial de ESTA fase
        progress          dict | None       sub-progreso (fases 1, 2 y 3)
        survey            dict | None       SOLO en la card `review_appointment`
                                             (dict plano de `summary_for_process`
                                             + `url`, D3, spec §6.1)
    """
    from itcj2.apps.titulatec.models import (
        FormatB, PhaseDefinition, ProcessEvent, ProcessPhase,
    )
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.document_service import DocumentService

    pdefs = (
        db.query(PhaseDefinition)
        .filter_by(is_active=True)
        .order_by(PhaseDefinition.order_index)
        .all()
    )

    def _base_card(pd, **over) -> dict:
        info = _PHASE_INFO.get(pd.code, {})
        card = {
            "number": pd.number,
            "code": pd.code,
            "name": pd.name,
            "icon": pd.icon,
            "responsible": pd.responsible,
            "responsible_label": _RESPONSIBLE_LABEL.get(pd.responsible, "el área responsable"),
            "status": "pending",
            "rel": "future",
            "is_current": False,
            "can_expand": True,
            "is_open": pd.number == open_phase,
            "is_target": pd.number == open_phase,
            "desc": info.get("desc", ""),
            "needs": info.get("needs", []),
            "who": info.get("who", ""),
            "cta": None,
            "rejection_reason": None,
            "events": [],
            "progress": None,
            "survey": None,
        }
        card.update(over)
        return card

    if process is None:
        # Sin proceso no hay fase actual: las 9 son informativas y desplegables.
        return {"has_process": False, "current_phase": 0, "progress_pct": 0,
                "open_phase": open_phase, "current": None,
                "phases": [_base_card(pd) for pd in pdefs]}

    current_phase = process.current_phase

    # Estatus de la solicitud de liberación de GTV para la encuesta de
    # egresados (D3, spec §6.1). UNA sola consulta fija, igual que el resto de
    # este contexto: no una por fase. Se cuelga solo de la card
    # `review_appointment` (nunca por número) y es visible desde la fase 0:
    # a diferencia del resto de esta pantalla, la encuesta NO está sujeta a la
    # guarda de fase del alumno.
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    survey = SurveyReviewService.summary_for_process(db, process.id)
    survey["url"] = _SURVEY_URL if survey["status"] == "missing" else None

    ph_by_number = {
        ph.phase_number: ph for ph in
        db.query(ProcessPhase).filter_by(process_id=process.id).all()
    }

    events_by_phase: dict[int, list] = {}
    for ev in (db.query(ProcessEvent)
               .filter_by(process_id=process.id)
               .order_by(ProcessEvent.created_at).all()):
        # Un evento sin fase no pertenece a ningún acordeón; no lo colgamos de una
        # fase arbitraria para no inventar historial.
        if ev.phase_number is None:
            continue
        events_by_phase.setdefault(ev.phase_number, []).append({
            "label": _EVENT_LABELS.get(ev.event_type, ev.event_type),
            "when": _cita_label(ev.created_at),
        })

    progress_by_code = {
        "initial_docs": _docs_progress(DocumentService.initial_docs_summary(db, process.id)),
        "review_appointment": _appt_progress(AppointmentService.get_for_process(db, process.id)),
        "format_b": _format_b_progress(db.get(FormatB, process.id)),
    }

    cards = []
    for pd in pdefs:
        ph = ph_by_number.get(pd.number)
        status = ph.status if ph else "pending"
        is_current = pd.number == current_phase
        rel = "current" if is_current else ("past" if pd.number < current_phase else "future")

        progress = progress_by_code.get(pd.code)
        # Una fase futura que nadie ha tocado no muestra un sub-progreso vacío.
        if progress and rel == "future" and not progress["started"]:
            progress = None

        cards.append(_base_card(
            pd,
            status=status,
            rel=rel,
            is_current=is_current,
            can_expand=not is_current,
            is_open=(not is_current) and pd.number == open_phase,
            is_target=pd.number == open_phase,
            cta=_cta_for(pd.code, is_current=is_current, status=status),
            rejection_reason=(ph.rejection_reason if ph else None),
            events=events_by_phase.get(pd.number, []),
            progress=progress,
            survey=(survey if pd.code == "review_appointment" else None),
        ))

    total = len(pdefs) or 9
    return {
        "has_process": True,
        "current_phase": current_phase,
        "progress_pct": int(round(current_phase / total * 100)),
        "open_phase": open_phase,
        "current": next((c for c in cards if c["is_current"]), None),
        "phases": cards,
    }


def _parse_open_phase(raw) -> int | None:
    """``?fase=N`` → entero o None. Nunca revienta la pantalla principal.

    Se parsea a mano en vez de declarar ``fase: int | None`` porque esta URL viaja
    dentro de notificaciones que viven en BD (`services/notify.py:31-33`): un valor
    viejo, vacío o basura debe degradar a "sin acordeón abierto", no a un 422 en el
    dashboard del alumno. Que el número exista en el catálogo lo resuelve
    `_phases_ctx` (ninguna card se marca abierta si no coincide).
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@router.get("/dashboard", name="titulatec.pages.student.dashboard")
async def dashboard(
    request: Request,
    fase: str | None = None,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.dashboard.student"])),
):
    """Dashboard del alumno: hero + tarjeta grande de la fase actual + acordeón de las 9.

    Ya no hay pantalla intermedia de fase: la descripción de cada fase se despliega
    aquí mismo (`_phases_ctx`), y la fase ACTUAL no se despliega — sale en grande en
    la columna A con su CTA. `?fase=N` es el deep-link: deja esa fase abierta y
    resaltada ya en el HTML de la respuesta (lo usa el redirect de `/fase/{n}`, al
    que siguen apuntando las notificaciones).
    """
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        u = db.get(User, user_id)
        process = DocumentService.get_active_process(db, user_id)

        ctx = _phases_ctx(db, process, open_phase=_parse_open_phase(fase))
        ctx["first_name"] = u.first_name if u else None
        # Compat del hero: nombre de la fase actual como texto suelto.
        ctx["phase_name"] = ctx["current"]["name"] if ctx["current"] else None
    finally:
        db.close()

    return render_titulatec(request, "titulatec/student/dashboard.html", ctx)


@router.get("/perfil", name="titulatec.pages.student.perfil")
async def perfil(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.dashboard.student"])),
):
    """Mini-perfil del alumno: identidad + resumen del proceso + cerrar sesión.

    Solo se enlaza en modo standalone (el shell mobile del core cubre el perfil
    cuando la app corre embebida).
    """
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import PhaseDefinition
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        u = db.get(User, user_id)
        process = DocumentService.get_active_process(db, user_id)

        proc_ctx = None
        if process:
            program = db.get(Program, process.program_id) if process.program_id else None
            pdef = db.query(PhaseDefinition).filter_by(number=process.current_phase).first()
            proc_ctx = {
                "folio": process.folio,
                "modality": process.modality.name if process.modality else "—",
                "program": program.name if program else None,
                "period": process.cohort.period_code if process.cohort else None,
                "current_phase": process.current_phase,
                "phase_name": pdef.name if pdef else None,
                "status": process.status,
            }

        ctx = {
            "u": {
                "name": (u.full_name if u else None) or "Alumno",
                "control_number": (u.control_number or u.username) if u else None,
                "email": u.email if u else None,
            },
            "proc": proc_ctx,
        }
    finally:
        db.close()
    return render_titulatec(request, "titulatec/student/perfil.html", ctx)


@router.get("/fase/{n}", name="titulatec.pages.student.phase_detail")
async def phase_detail(
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=[
        "titulatec.process.page.my", "titulatec.process.api.read.own"])),
):
    """Compat: la pantalla de fase ya no existe — redirige al acordeón del dashboard.

    **No se puede borrar esta ruta.** `services/notify.py:31-33` escribe
    ``data['url'] = /titulatec/student/fase/{n}`` dentro de `core_notifications`, y
    esas filas ya están en BD: todo aviso emitido hasta hoy sigue apuntando aquí.

    **302 y no 301/308.** Un redirect permanente lo cachea el navegador (y cualquier
    intermediario) sin volver a preguntar: si mañana cambia el mecanismo de
    deep-link, o la fase vuelve a tener pantalla propia, los alumnos que ya lo
    tengan cacheado no volverían a tocar el servidor nunca. Además es la convención
    de redirect de página del monorepo (`pages/landing.py:23` y ~20 sitios más).

    **`?fase=N` y no `#fase-N`.** El fragmento no viaja al servidor: el acordeón
    llegaría cerrado en el HTML y solo lo abriría JS después de pintar. Con query
    param el servidor emite ya el `aria-expanded` correcto — sin parpadeo y sin
    depender de JS.
    """
    from fastapi.responses import RedirectResponse, Response
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import PhaseDefinition
    from itcj2.apps.titulatec.services.document_service import DocumentService

    if n < 0 or n > 8:
        return Response(status_code=404)

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        pdef = db.query(PhaseDefinition).filter_by(number=n).first()
        if not process or not pdef:
            return Response(status_code=404)
    finally:
        db.close()

    return RedirectResponse(f"/titulatec/student/dashboard?fase={n}", status_code=302)


@router.get("/documents", name="titulatec.pages.student.documents")
async def documents(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.read.own"])),
):
    """Página de documentos iniciales (fase 1) con dropzones HTMX."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        fuera_de_fase = _phase_guard_page(db, process, _phase_of(db, "initial_docs"))
        if fuera_de_fase:
            return fuera_de_fase
        slots = []
        if process:
            for code in _INITIAL_DOC_TYPES:
                dtype = db.query(DocumentType).filter_by(code=code, is_active=True).first()
                if not dtype:
                    continue
                doc = DocumentService.get_document(db, process.id, code)
                slots.append(_slot_ctx(dtype, doc))
        all_uploaded = bool(slots) and all(s["doc"] for s in slots)
        ctx = {
            "process": process.to_dict() if process else None,
            "slots": slots,
            "all_uploaded": all_uploaded,
        }
    finally:
        db.close()

    return render_titulatec(request, "titulatec/student/documents.html", ctx)


@router.post("/documents/{type_code}", name="titulatec.pages.student.document_upload")
async def document_upload(
    type_code: str,
    request: Request,
    archivo: UploadFile = File(...),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.upload.own"])),
):
    """Sube/sobreescribe un documento. Devuelve el parcial del slot (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils.storage import StorageError

    db = SessionLocal()
    try:
        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            return Response(status_code=404)
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        # La fase la manda el TIPO, no la URL: `DocumentService.save` escribe
        # `phase_number=dtype.phase_number`. Sin esto, un alumno de la fase 1
        # podía sembrar `anexo_iii` (fase 6) o `final_project` (fase 8).
        fuera_de_fase = _phase_guard(db, process, dtype.phase_number)
        if fuera_de_fase:
            return fuera_de_fase

        raw = await archivo.read()
        error = None
        doc = DocumentService.get_document(db, process.id, type_code)
        try:
            doc = DocumentService.save(
                db, process, type_code,
                raw=raw, original_name=archivo.filename,
                content_type=archivo.content_type, uploaded_by_id=int(user["sub"]),
            )
        except (StorageError, ValueError) as exc:
            error = str(exc)

        ctx = _slot_ctx(dtype, doc, error=error)
        resp = render_titulatec(request, "titulatec/partials/document_slot.html", ctx)
        if error:
            resp.headers["X-Tt-Error"] = error
        return resp
    finally:
        db.close()


@router.delete("/documents/{type_code}", name="titulatec.pages.student.document_delete")
async def document_delete(
    type_code: str,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.delete.own"])),
):
    """Elimina un documento. Devuelve el parcial del slot vacío (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            return Response(status_code=404)
        process = DocumentService.get_active_process(db, int(user["sub"]))
        # `DocumentService.delete` borra la fila Y el fichero
        # (`storage.delete_document_file`): fuera de su fase esto destruía
        # evidencia ya dictaminada de una fase cerrada.
        fuera_de_fase = _phase_guard(db, process, dtype.phase_number)
        if fuera_de_fase:
            return fuera_de_fase
        if process:
            DocumentService.delete(db, process.id, type_code, actor_id=int(user["sub"]))
        return render_titulatec(request, "titulatec/partials/document_slot.html", _slot_ctx(dtype, None))
    finally:
        db.close()


def _programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()]


@router.get("/formato-b", name="titulatec.pages.student.formato_b")
async def formato_b(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.page.fill"])),
):
    """Shell del Formato B multi-step (arranca en el paso 1)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        # ANTES de `get_or_create`, que hace `db.commit()`: sin la guarda, el mero
        # GET desde otra fase ya creaba la fila `titulatec_format_b`.
        fuera_de_fase = _phase_guard_page(db, process, _phase_of(db, "format_b"))
        if fuera_de_fase:
            return fuera_de_fase
        ctx = {"process": process.to_dict() if process else None}
        if process:
            fb = FormatBService.get_or_create(db, process)
            ctx.update({"step": 1, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)})
    finally:
        db.close()
    return render_titulatec(request, "titulatec/student/formato_b.html", ctx)


@router.get("/formato-b/step/{n}", name="titulatec.pages.student.formato_b_step")
async def formato_b_step(
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.page.fill"])),
):
    """Devuelve el parcial de un paso (navegación atrás, HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from fastapi.responses import Response

    if n not in (1, 2, 3):
        return Response(status_code=404)
    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        # Parcial HTMX, no página: error por `X-Tt-Error`, nunca un 302 (htmx lo
        # seguiría y metería el dashboard entero dentro de `#formato-b-body`).
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "format_b"))
        if fuera_de_fase:
            return fuera_de_fase
        fb = FormatBService.get_or_create(db, process)
        ctx = {"step": n, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/formato_b_step.html", ctx)


@router.post("/formato-b/step/{n}", name="titulatec.pages.student.formato_b_save")
async def formato_b_save(
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.api.save"])),
):
    """Guarda el paso n y devuelve el parcial del siguiente (o 'done' al enviar)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from fastapi.responses import Response

    if n not in (1, 2, 3):
        return Response(status_code=404)
    form = dict(await request.form())
    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "format_b"))
        if fuera_de_fase:
            return fuera_de_fase
        fb = FormatBService.get_or_create(db, process)
        FormatBService.save_step(db, fb, n, form)

        if n < 3:
            ctx = {"step": n + 1, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)}
        else:
            FormatBService.submit(db, fb, process)
            ctx = {"step": "done", "datos": FormatBService.to_ctx(fb), "programs": []}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/formato_b_step.html", ctx)


# ===========================================================================
# Cita de cotejo (fase 2)
# ===========================================================================

_MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]

def _checklist_ctx(db, process) -> list[dict]:
    """Requisitos de cotejo de SU convocatoria, cruzados con lo que ya acreditó.

    Sustituye a `_COTEJO_CHECKLIST`, que era un duplicado byte a byte de
    `CotejoRequirementService.DEFAULTS`: la jefa de Servicios Escolares editaba
    la lista por convocatoria y el alumno seguía viendo la fija.

    Devuelve DICCIONARIOS PLANOS, no objetos ORM: la plantilla se renderiza
    después del `db.close()` de la ruta y un atributo expirado sobre una
    instancia ya desanclada lanzaría `DetachedInstanceError`.

    ATENCION, y es deliberado: `list_with_status` enruta a `list_or_seed`, que
    en una convocatoria sin requisitos configurados SIEMBRA los 8 por defecto y
    COMMITEA. Es decir, este GET puede escribir. Se conserva a proposito porque
    el spec 5.3 lo pide asi y porque toda convocatoria creada antes de este
    trabajo tiene cero requisitos: una lectura no sembradora le mostraria al
    alumno un checklist VACIO. La lectura NO sembradora es la del expediente
    del oficial (Tarea 8), donde navegar no debe crear configuracion.
    """
    if process is None:
        return []
    from itcj2.apps.titulatec.services.requirement_service import RequirementService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html

    # Estatus de la solicitud de liberación de GTV (D3, spec §6.1): una sola
    # consulta fija, igual que `_phases_ctx`, aunque solo la use la fila con
    # `auto_source == "graduate_survey"`.
    survey = SurveyReviewService.summary_for_process(db, process.id)

    out = []
    for it in RequirementService.list_with_status(db, process.id):
        req, ful = it["requirement"], it["fulfillment"]
        es_encuesta = req.auto_source == "graduate_survey"
        out.append({
            # Ancla del botón «i» con SU modal (`#tt-reqinfo-modal-{id}`).
            "id": req.id,
            # «Información para el alumno», re-sanitizada AL PINTAR (la primera
            # sanitización es al guardar): una fila escrita por fuera del editor
            # —un UPDATE a mano, un DML— tampoco inyecta. La plantilla la pinta
            # con `|safe` y SOLO este campo; `None` = sin botón «i». Sin tope
            # (`max_len=None`): una fila ya guardada nunca tumba la página.
            "info_html": sanitize_info_html(req.info_html, max_len=None),
            "icon": req.icon or "check2-square",
            "title": req.label,
            "hint": req.hint or "",
            "required": bool(req.is_required),
            "done": it["is_done"],
            "status": (ful.status if ful else None),
            "source": (ful.source if ful else None),
            "when": (f"{ful.fulfilled_at:%d/%m/%Y}" if ful and ful.fulfilled_at else None),
            # La libera GTV, no el alumno (D3): el estatus real de la
            # solicitud sustituye al "Listo"/"Dispensado" genérico en la
            # plantilla. `None` en cualquier otro requisito.
            "survey": (survey if es_encuesta else None),
            # El único requisito que el alumno puede resolver desde aquí mismo,
            # y SOLO si de verdad no ha enviado nada todavía (pseudo-estado
            # "missing" = sin fila en `titulatec_survey_reviews`).
            "survey_url": (_SURVEY_URL if es_encuesta and survey["status"] == "missing"
                           else None),
        })
    return out


_DAYS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _hdr(msg) -> str:
    """Codifica un mensaje para que quepa en un header HTTP.

    Gemelo de `pages/appointments.py::_hdr`, y por el mismo motivo: los valores
    de header son latin-1 por especificación y Starlette los escribe así, pero
    el cliente los lee UTF-8, así que un mensaje con acentos —o sea, TODOS los
    de `SelfBookingService` y los de `appointment_errors`— llega roto.

    Se percent-codifica aquí y lo decodifica `static/js/student/errors.js`.
    """
    from urllib.parse import quote
    return quote(str(msg), safe="")


def _to_int(raw):
    """'12' -> 12; basura -> None. Un `window_id` inventado NO revienta la ruta:
    cae en `None` y el service lo traduce a `NotYours` (404 limpio)."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _parse_hhmm(raw):
    """'09:30' -> time(9,30), o None (-> `MissingSchedule`, 400 con mensaje)."""
    from datetime import datetime as _dt
    if not raw:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return _dt.strptime(str(raw).strip(), fmt).time()
        except (ValueError, TypeError):
            continue
    return None


def _dia_label(d) -> str:
    return f"{_DAYS_ES[d.weekday()]} {d.day:02d} {_MONTHS_ES[d.month]}"


def _agenda_ctx(db, process, *, dia: str | None = None) -> dict:
    """Las cuatro caras de §7, resueltas en DATOS PLANOS.

    Planos porque la plantilla se renderiza DESPUÉS del `db.close()` de la ruta:
    un atributo perezoso sobre una instancia ya desanclada lanzaría
    `DetachedInstanceError` (mismo motivo que `_checklist_ctx`). `offer()` ya
    devuelve dicts, así que aquí solo se les da forma de pantalla: las horas se
    formatean AQUÍ y no en Jinja, para que la plantilla no haga aritmética.

    `eligibility` decide QUIÉN puede y `offer` QUÉ hay. Se consumen juntos, y de
    ahí sale lo que a primera vista parece una contradicción: la tarjeta de
    «atención sin cita» convive con la frase de la cara 4, porque el bloqueado
    por D9 no puede reservar pero sí presentarse.
    """
    vacio = {"can_book": False, "can_walkin": False, "reason": None,
             "message": None, "dias": [], "dia_sel": None, "dia_actual": None,
             "walkins": []}
    if process is None:
        return vacio

    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    elig = SelfBookingService.eligibility(db, process.id)
    oferta = SelfBookingService.offer(db, process.id)

    dias, walkins = [], []
    for jornada in oferta:
        fecha = jornada["date"]
        duenos = []
        for dueno in jornada["owners"]:
            ventanas = []
            for w in dueno["windows"]:
                if w["visibility"] == "walkin":
                    # D2: anuncio, no agenda. Viaja sin franjas desde `offer`.
                    walkins.append({
                        "date_label": _dia_label(fecha),
                        "start": f'{w["start_time"]:%H:%M}',
                        "end": f'{w["end_time"]:%H:%M}',
                        "location": w["location"],
                        "owner_name": dueno["owner_name"],
                    })
                    continue
                ventanas.append({
                    "window_id": w["window_id"],
                    "range": f'{w["start_time"]:%H:%M} a {w["end_time"]:%H:%M}',
                    "location": w["location"],
                    "slots": [f"{s:%H:%M}" for s in w["slots"]],
                })
            if ventanas:
                duenos.append({"owner_name": dueno["owner_name"], "windows": ventanas})
        if duenos:
            dias.append({"iso": fecha.isoformat(), "label": _dia_label(fecha),
                         "dow": _DAYS_ES[fecha.weekday()], "dom": f"{fecha.day:02d}",
                         "mon": _MONTHS_ES[fecha.month], "owners": duenos})

    # El día pedido, si sigue en la oferta; si no, el primero que la tenga. Un
    # `?dia=` viejo —un enlace guardado, un día que el encargado cerró— degrada
    # al primer día con oferta en vez de dejar una rejilla vacía sin explicar
    # por qué (mismo criterio que `_parse_open_phase`: la URL no tumba la vista).
    dia_sel = next((d["iso"] for d in dias if d["iso"] == dia), None)
    if dia_sel is None and dias:
        dia_sel = dias[0]["iso"]
    dia_actual = next((d for d in dias if d["iso"] == dia_sel), None)

    # La cara 4 NO se pinta cuando el motivo es `tiene_cita`: esa pantalla YA
    # explica el porqué, con la tarjeta de la cita justo encima. Repetirlo
    # debajo sería decirle dos veces lo mismo al alumno. Las demás razones no
    # tienen ninguna otra señal en pantalla, y sin la frase quedaría un hueco.
    message = (None if elig["reason"] == "tiene_cita"
               else SelfBookingService.message_for(
                   elig["reason"], cancellations=elig["cancellations"]))

    return {"can_book": elig["can_book"], "can_walkin": elig["can_walkin"],
            "reason": elig["reason"], "message": message, "dias": dias,
            "dia_sel": dia_sel, "dia_actual": dia_actual, "walkins": walkins}


def _cita_label(dt) -> str:
    if not dt:
        return "—"
    return f"{dt.day:02d} {_MONTHS_ES[dt.month]} {dt.year} · {dt:%H:%M}"


def _cita_card_ctx(db, user_id: int) -> dict:
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    # `ProcessService.creditable_process` y NO `DocumentService.get_active_process`:
    # aquel no filtra por status pese al nombre, y esta tarjeta tiene que hablar
    # del MISMO proceso que acredita la encuesta (§5.3 del diseño).
    process = ProcessService.creditable_process(db, user_id)
    appt = AppointmentService.get_for_process(db, process.id) if process else None
    appt_ctx = None
    if appt:
        appt_ctx = {
            "scheduled_label": _cita_label(appt.scheduled_at),
            "location": appt.location,
            "status": appt.status,
            "confirmed": appt.confirmed_at is not None,
            "change_requested": bool(appt and appt.change_request),
            # D8. Lo decide el MISMO predicado que va a aplicar el servidor, no
            # una cuenta repetida aquí: si divergieran, la tarjeta ofrecería
            # «Cancelar mi cita» justo cuando la ruta ya va a rechazarlo.
            "can_cancel": SelfBookingService.can_self_cancel(appt),
        }
    # Fase 02 con observaciones (Tarea B2): dato PLANO, nunca la fila `ProcessPhase`
    # completa (la plantilla se renderiza después del `db.close()` de la ruta). Se
    # lee de `ProcessPhase`, igual que `_fase_cotejo_aprobada` en
    # `SelfBookingService`, y NUNCA de `appt.status`: una `attended` con fase 2
    # todavía sin dictaminar no es un rechazo.
    fase_rechazada = None
    if process is not None:
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        ph2 = (db.query(ProcessPhase)
               .filter_by(process_id=process.id, phase_number=PhaseService.PHASE_COTEJO)
               .first())
        if ph2 is not None and ph2.status == "rejected":
            fase_rechazada = {"motivo": ph2.rejection_reason or None}
    return {
        "process": process.to_dict() if process else None,
        "appt": appt_ctx,
        "fase_rechazada": fase_rechazada,
    }


def _cita_panel_ctx(db, user_id: int, *, dia: str | None = None) -> dict:
    """Contexto del panel completo: la tarjeta MÁS las cuatro caras de §7.

    Resuelve el proceso con el mismo selector que `_cita_card_ctx`
    (`creditable_process`): la tarjeta y el selector de agendado TIENEN que
    hablar del mismo proceso, o el alumno vería la cita de uno y agendaría en
    el otro.
    """
    from itcj2.apps.titulatec.services.process_service import ProcessService

    ctx = _cita_card_ctx(db, user_id)
    ctx["agenda"] = _agenda_ctx(db, ProcessService.creditable_process(db, user_id),
                                dia=dia)
    return ctx


def _cita_panel(request, db, user_id: int, *, dia: str | None = None):
    """El parcial que devuelven los dos POST del auto-agendado.

    App pages-only: un POST responde con el cuerpo re-renderizado, no con JSON.
    """
    return render_titulatec(request, "titulatec/partials/student/_cita_panel.html",
                            _cita_panel_ctx(db, user_id, dia=dia))


@router.get("/cita", name="titulatec.pages.student.cita")
async def cita(
    request: Request,
    dia: str | None = None,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.page.my"])),
):
    """Página de la cita de cotejo del alumno: estado + requisitos de SU convocatoria.

    Sin proceso acreditable se redirige al dashboard. `_phase_guard_page` deja
    pasar el `None` a propósito, y antes eso nunca ocurría porque el selector
    viejo devolvía un proceso pasara lo que pasara; `creditable_process` sí puede
    no devolver ninguno, y entonces el alumno caía en la página vacía con una
    copia que le decía que faltaba configurar su convocatoria. Todo el alumno
    tiene un solo contrato —solo la fase en curso, solo con el proceso `active`—
    y quien no tiene trámite vivo no tiene fase en curso: ninguna página del
    alumno es suya. Es lo que ya hacen `/student/documents` y sus hermanas.
    """
    from itcj2.database import SessionLocal
    from fastapi.responses import RedirectResponse
    from itcj2.apps.titulatec.services.process_service import ProcessService

    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        process = ProcessService.creditable_process(db, user_id)
        if process is None:
            return RedirectResponse(_DASHBOARD_URL, status_code=302)
        # Lo que decide parcial-contra-página es `HX-Request`, NO la mera
        # presencia de `?dia=`: ese mismo enlace abierto sin htmx —sin JS, o
        # pegado en la barra de direcciones— es una navegación de PÁGINA, y
        # contestarle un fragmento pelado (sin shell, sin estilos) es peor que
        # no contestar.
        es_htmx = request.headers.get("HX-Request") == "true"
        # Mismo criterio para el canal de la guarda de fase: 302 en páginas,
        # 400 + `X-Tt-Error` en parciales. htmx sigue los redirects de forma
        # transparente y metería el dashboard entero dentro del selector.
        n = _phase_of(db, "review_appointment")
        fuera_de_fase = (_phase_guard(db, process, n) if es_htmx
                         else _phase_guard_page(db, process, n))
        if fuera_de_fase:
            return fuera_de_fase
        ctx = _cita_panel_ctx(db, user_id, dia=dia)
        ctx["checklist"] = _checklist_ctx(db, process)
    finally:
        db.close()

    # `?dia=` es la MISMA ruta con querystring —no suma al censo de rutas del
    # alumno— y con htmx devuelve solo el selector del día elegido, que es
    # justo lo que se swappea (`#tt-cita-agendar`, `outerHTML`).
    if dia and es_htmx:
        agenda = ctx["agenda"]
        # La rejilla SOLO si de verdad puede agendar. Sin esta condición, quien
        # dejó la pestaña abierta y ya agendó (o perdió el derecho) recibía
        # franjas vivas y ninguna explicación: exactamente el «botón mudo» que
        # §7 existe para prohibir. El POST lo revalida, así que no era un
        # agujero — era una mentira en pantalla, que es lo que esta vista no
        # puede permitirse.
        if agenda["can_book"] and agenda["dias"]:
            return render_titulatec(
                request, "titulatec/partials/student/_cita_agendar.html", ctx)
        # Ya no aplica: se refresca el PANEL entero (tarjeta + la frase que
        # dice por qué). El destino original era solo el selector, así que se
        # redirige el swap; sin esto, el panel entraría DENTRO del selector y
        # habría dos `#tt-cita-card` en el documento.
        resp = render_titulatec(
            request, "titulatec/partials/student/_cita_panel.html", ctx)
        resp.headers["HX-Retarget"] = "#tt-cita-panel"
        resp.headers["HX-Reswap"] = "innerHTML"
        return resp
    return render_titulatec(request, "titulatec/student/cita.html", ctx)


@router.post("/cita/confirmar", name="titulatec.pages.student.cita_confirm")
async def cita_confirm(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.confirm.own"])),
):
    """El alumno confirma asistencia. Devuelve la tarjeta re-renderizada (HTMX).

    Mismo selector que la página que aloja este botón (`_cita_card_ctx`): si la
    guarda mirara otro proceso, el alumno vería la cita del suyo y el POST le
    contestaría 400 por el estado de uno distinto.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    db = SessionLocal()
    try:
        process = ProcessService.creditable_process(db, int(user["sub"]))
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "review_appointment"))
        if fuera_de_fase:
            return fuera_de_fase
        appt = AppointmentService.get_for_process(db, process.id) if process else None
        if appt and appt.status in ("scheduled",):
            AppointmentService.confirm(db, appt, int(user["sub"]))
        return render_titulatec(request, "titulatec/partials/cita_card.html",
                                _cita_card_ctx(db, int(user["sub"])))
    finally:
        db.close()


@router.post("/cita/solicitar-cambio", name="titulatec.pages.student.cita_request_change")
async def cita_request_change(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.confirm.own"])),
):
    """El alumno solicita un cambio de cita (el encargado decide). Devuelve la tarjeta.

    Mismo selector que `cita_confirm` y que la página, por lo mismo: los dos
    botones de la tarjeta tienen que hablar del proceso que la tarjeta pinta.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    form = dict(await request.form())
    reason = form.get("reason", "")
    db = SessionLocal()
    try:
        process = ProcessService.creditable_process(db, int(user["sub"]))
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "review_appointment"))
        if fuera_de_fase:
            return fuera_de_fase
        appt = AppointmentService.get_for_process(db, process.id) if process else None
        if appt:
            AppointmentService.request_change(db, appt, int(user["sub"]), reason)
        return render_titulatec(request, "titulatec/partials/cita_card.html",
                                _cita_card_ctx(db, int(user["sub"])))
    finally:
        db.close()


# ===========================================================================
# Auto-agendado del egresado (spec 2026-09-15 §5)
# ===========================================================================
# NINGUNA de las dos lleva `{process_id}`: el proceso sale del usuario
# autenticado, igual que las dos rutas de cita que ya existían. Es lo correcto y
# además lo que mantiene verde a `test_scope_guard.py` sin excepciones nuevas.
#
# Las dos pasan por `_phase_guard` (fase 2), como sus hermanas: una ruta del
# alumno sin guarda de fase sale en rojo en `test_student_phase_guard.py`, y el
# modo de fallo del olvido sería ABIERTO.


def _cita_accion(request, db, user_id: int, fn):
    """Ejecuta una acción del auto-agendado y traduce sus errores de dominio.

    Tres salidas, y la diferencia entre ellas es el contrato de T4:

    * `NotYours` -> **404 limpio, SIN `X-Tt-Error`**. Mismo criterio que
      `assert_process_in_scope`: los ids son enteros secuenciales, y un mensaje
      distintivo convertiría la ruta en un detector de lo que existe. Lo levanta
      por dos motivos —ventana fuera de su oferta y proceso ajeno— y los dos
      salen igual a propósito: distinguirlos sería el oráculo que se quiere
      cerrar.
    * entrada del usuario (`SlotTooSoon`, `CancelTooLate`, casi toda
      `SelfBookingNotAllowed`) -> 400 + `X-Tt-Error`. htmx no swappea en 4xx, y
      está bien: lo que hay en pantalla sigue siendo verdad.
    * colisión de estado (`refresca_la_vista`, o sea `reason == "tiene_cita"`)
      -> **200 con el panel fresco** + `X-Tt-Notice`. Es lo que produce un doble
      clic en «Agendar»: ahí la pantalla SÍ está rancia —ya existe una cita que
      el alumno no está viendo— y un 4xx lo dejaría mirando un selector muerto.
    """
    from itcj2.apps.titulatec.services.appointment_errors import (
        AppointmentError, NotYours,
    )
    try:
        fn()
    except NotYours:
        # `NotYours` hereda de `AppointmentError`: va PRIMERO o el 404 nunca
        # llegaría a ejecutarse.
        return Response(status_code=404)
    except AppointmentError as e:
        if not e.refresca_la_vista:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(e)})
        resp = _cita_panel(request, db, user_id)
        resp.headers["X-Tt-Notice"] = _hdr(e)
        return resp
    return _cita_panel(request, db, user_id)


@router.post("/cita/agendar", name="titulatec.pages.student.cita_book")
async def cita_book(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.book.own"])),
):
    """El egresado toma una franja publicada. Devuelve el panel re-renderizado.

    `window_id` llega en el CUERPO del formulario, no en la ruta, así que quien
    lo revalida contra la oferta de ESTE proceso es
    `SelfBookingService.book` (`_window_in_offer`) — el regresor estructural de
    alcance, que barre rutas con `{process_id}`, no puede verlo. Aquí solo se
    traduce el `NotYours` resultante al 404 limpio.

    El actor va como `int(user["sub"])`: `sub` es **string** (gotcha 5), y de
    esa comparación depende en silencio que `create` calle la notificación del
    propio clic del alumno.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    form = dict(await request.form())
    window_id = _to_int(form.get("window_id"))
    slot = _parse_hhmm(form.get("slot"))
    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        process = ProcessService.creditable_process(db, user_id)
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "review_appointment"))
        if fuera_de_fase:
            return fuera_de_fase
        if process is None:
            return Response(status_code=409)
        return _cita_accion(request, db, user_id, lambda: SelfBookingService.book(
            db, process.id, window_id, slot, user_id))
    finally:
        db.close()


@router.post("/cita/cancelar", name="titulatec.pages.student.cita_cancel")
async def cita_cancel(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.cancel.own"])),
):
    """El egresado cancela su propia cita (D8: hasta 2 h antes).

    `motivo` es opcional y se guarda tal cual: `AppointmentService.cancel` lo
    deja en NULL si viene vacío en vez de inventar un texto que se leería como
    algo que el alumno escribió.

    La franja vuelve al pozo en el acto (D12), así que el panel que se devuelve
    ya trae el selector de agendado otra vez.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    form = dict(await request.form())
    motivo = (form.get("motivo") or "").strip() or None
    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        process = ProcessService.creditable_process(db, user_id)
        fuera_de_fase = _phase_guard(db, process, _phase_of(db, "review_appointment"))
        if fuera_de_fase:
            return fuera_de_fase
        if process is None:
            return Response(status_code=409)
        appt = AppointmentService.get_for_process(db, process.id)
        if appt is None:
            # Doble clic en «Cancelar»: la segunda vez ya no hay cita vigente.
            # Lo que el alumno pidió YA está hecho, así que se le devuelve el
            # panel tal como quedó. Un 4xx aquí sería un error inventado.
            return _cita_panel(request, db, user_id)
        return _cita_accion(request, db, user_id, lambda: SelfBookingService.cancel(
            db, appt, user_id, motivo))
    finally:
        db.close()


@router.post("/phase/1/submit", name="titulatec.pages.student.submit_initial_docs")
async def submit_initial_docs(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.advance"])),
):
    """Marca la fase 1 como 'en revisión' si los 3 documentos están subidos."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import ProcessPhase, Document
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        # La guarda va ANTES del conteo: una fase cerrada no discute documentos.
        # `n` sale del catálogo y es el mismo número que se escribe abajo, para
        # que la guarda y la escritura no puedan desincronizarse (el `1` del path
        # es histórico: lo conservan los enlaces de la UI).
        n = _phase_of(db, "initial_docs")
        fuera_de_fase = _phase_guard(db, process, n)
        if fuera_de_fase:
            return fuera_de_fase
        count = db.query(Document).filter(
            Document.process_id == process.id,
            Document.type_code.in_(_INITIAL_DOC_TYPES),
        ).count()
        if count < len(_INITIAL_DOC_TYPES):
            return Response(status_code=400, headers={"X-Tt-Error": "Faltan documentos por subir."})

        phase = db.query(ProcessPhase).filter_by(process_id=process.id, phase_number=n).first()
        if not phase:
            phase = ProcessPhase(process_id=process.id, phase_number=n)
            db.add(phase)
        phase.status = "in_review"
        db.commit()
        return Response(status_code=204)
    finally:
        db.close()

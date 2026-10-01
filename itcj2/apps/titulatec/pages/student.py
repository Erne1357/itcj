"""Páginas del alumno en TitulaTec (mobile-first)."""
import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.student")

router = APIRouter(prefix="/student", tags=["titulatec-pages-student"])

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
            "Cada archivo va en PDF de hasta {pdf_max_mb} MB. Si pesa más "
            "(hasta {pdf_upload_mb} MB), lo comprimimos automáticamente.",
            "Al subir los 3, tu fase pasa sola a revisión: no hay que enviarla a mano.",
        ],
        "who": "Tú subes los tres archivos; Servicios Escolares los revisa y los aprueba "
               "o te pide corregir.",
    },
    "review_appointment": {
        # Neutral a proposito (2026-09-18): desde el auto-agendado hay convocatorias
        # donde el alumno elige dia y hora, y otras donde se atiende por orden de
        # llegada. El texto anterior prometia que Servicios Escolares asignaba la
        # fecha SIEMPRE, y se contradecia con el selector de la propia pantalla.
        # Aqui no se consulta la agenda -esto lo lee el dashboard para las 9
        # fases- : se dice lo que vale en los tres casos y se manda a la pestaña,
        # que si lo sabe. Y el cotejo NO es solo lo que el alumno subio: la lista
        # `needs` de abajo trae fotografias, no-adeudo, IMSS, e.firma y el pago.
        "desc": "En el cotejo revisan tus documentos EN FÍSICO: los que ya subiste y los "
                "demás requisitos de tu convocatoria. Según tu convocatoria, agendas tú "
                "o Servicios Escolares te asigna la fecha; en la pestaña de tu cita viene "
                "lo que te toca.",
        "needs": [
            "Actas de nacimiento: original y copias.",
            "CURP certificada, e.Firma del SAT vigente y vigencia de derechos del IMSS.",
            "Las constancias de no adeudo y de la encuesta las envían las áreas a "
            "Servicios Escolares; si registraste una constancia previa, llévala.",
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
            "Escanearlo y subirlo en PDF de hasta {pdf_max_mb} MB (si pesa más, hasta "
            "{pdf_upload_mb} MB, lo comprimimos automáticamente).",
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

# Variante de `_PHASE_INFO` SOLO para "initial_docs" en perfil posgrado (spec
# 2026-09-30-titulatec-posgrado-design.md §4.4, invariante 1): un egresado de
# posgrado sube 7 documentos en la fase 1 (los 3 de siempre + 4 extras), no 3,
# y el acordeón del dashboard tiene que decirlo. No es un dict de 9 fases:
# solo trae la ÚNICA que cambia por perfil -- el resto es igual para
# cualquier egresado (D8, spec §2).
_PHASE_INFO_POSGRADO = {
    "initial_docs": {
        "desc": "Sube tu acta de nacimiento, tu certificado de bachillerato, tu CURP "
                "certificada y los 4 documentos adicionales de posgrado. Son los mismos "
                "que vas a llevar en físico a la cita de cotejo.",
        "needs": [
            "Acta de nacimiento (PDF).",
            "Certificado de bachillerato (PDF).",
            "CURP certificada (PDF): la impresión certificada, no la simple.",
            "Cédula profesional y título de tu grado anterior (licenciatura si "
            "cursaste maestría; maestría si cursaste doctorado).",
            "Oficios de autorización de la División de Estudios de Posgrado e "
            "Investigación (DEPI), en un solo PDF.",
            "Comprobante de tu e.firma o de tu cita con el SAT.",
            "Cada archivo va en PDF de hasta {pdf_max_mb} MB. Si pesa más "
            "(hasta {pdf_upload_mb} MB), lo comprimimos automáticamente.",
            "Al subir los 7, tu fase pasa sola a revisión: no hay que enviarla a mano.",
        ],
        "who": "Tú subes los siete archivos; Servicios Escolares los revisa y los "
               "aprueba o te pide corregir.",
    },
}


def _phase_info(code: str, track: str) -> dict:
    """`_PHASE_INFO[code]`, con la variante de posgrado SOLO en `initial_docs`.

    `track` es lo que devuelve `TrackService` (invariante 2: el perfil sale
    SOLO de ahí). Fuera de `initial_docs` -- y para licenciatura siempre -- es
    exactamente `_PHASE_INFO.get(code, {})`: ninguna otra fase distingue
    perfil (D8, spec §2).
    """
    from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO

    if track == TRACK_POSGRADO:
        override = _PHASE_INFO_POSGRADO.get(code)
        if override is not None:
            return override
    return _PHASE_INFO.get(code, {})


# Compatibilidad: la instrucción breve sigue disponible como antes. SIEMPRE
# derivado de `_PHASE_INFO` (licenciatura): nada aquí distingue perfil -- un
# consumidor que algún día necesite la variante de posgrado debe pedirla vía
# `_phase_info`, no aquí.
_PHASE_HELP = {code: info["desc"] for code, info in _PHASE_INFO.items()}


def _with_pdf_limits(text: str) -> str:
    """Rellena `{pdf_max_mb}` / `{pdf_upload_mb}` con los topes de la config.

    Los topes de PDF viven en `TITULATEC_MAX_PDF_SIZE` / `..._UPLOAD_SIZE` y se
    cambian por `.env`: el copy de `_PHASE_INFO` no puede llevar el número
    escrito (decía «máximo 10 MB» cuando el tope bajó a 2). `replace` y no
    `str.format` para que una llave suelta en otro texto no truene.
    """
    if "{pdf_" not in text:
        return text
    from itcj2.apps.titulatec.utils.storage import pdf_limits_mb

    max_mb, upload_mb = pdf_limits_mb()
    return (text.replace("{pdf_max_mb}", str(max_mb))
                .replace("{pdf_upload_mb}", str(upload_mb)))


# CTA del alumno por código de fase (solo las soportadas hoy).
_PHASE_CTA = {
    "initial_docs":       ("/titulatec/student/documents", "Ir a documentos", "file-earmark-arrow-up"),
    "review_appointment": ("/titulatec/student/cita", "Ver requisitos", "calendar-check"),
    "format_b":           ("/titulatec/student/formato-b", "Llenar Formato B", "pencil-square"),
}

# Quién es responsable de la fase (para fases que el alumno no acciona).
# El artículo va INCLUIDO en el valor ("el Depto. de Titulación") porque
# `dashboard.html:115` lo usa tal cual detrás de "En proceso por " -- "por el"
# es correcto en español y no contrae. `_con_de` (abajo) es para el OTRO
# consumidor, `dashboard.html:73` ("A cargo de "), donde "de" + "el" sí
# contrae.
_RESPONSIBLE_LABEL = {
    "school_services": "Servicios Escolares",
    "titulaciones":    "el Depto. de Titulación",
    "vinculacion":     "Vinculación",
    "synodals":        "tus sinodales",
    "student":         "ti",
}


def _con_de(label: str) -> str:
    """"de" + `label`, con la contracción obligatoria "del" cuando `label`
    empieza con "el " (regla dura del español: "de"+"el"→"del", "a"+"el"→"al";
    "por"/"para"/"con"+"el" NO contraen, así que esto no sirve para esos).

    Ronda de fix 1 (Hallazgo 2, 2026-09-21): `dashboard.html:73` armaba
    "A cargo de {{ responsible_label }}", y con `_RESPONSIBLE_LABEL["titulaciones"]`
    = "el Depto. de Titulación" salía "A cargo de el Depto. de Titulación".
    Genérica sobre el prefijo "el " (no un `if label == "el Depto. de Titulación"`
    hardcodeado) para que un responsable nuevo que empiece con "el " no vuelva
    a colarse sin la contracción -- cubre también el fallback
    "el área responsable" de `_base_card`, que nunca se probó a mano.
    """
    if label.startswith("el "):
        return "del " + label[3:]
    return "de " + label


# Etiqueta legible de cada evento del timeline, EN LA VOZ DEL ALUMNO: aquí el
# mismo evento dice «Confirmaste tu asistencia» y en `pages/admin.py` «El alumno
# confirmó». Las dos caras del mismo suceso, cada una para quien la lee.
#
# COMPLETADO EL 2026-09-18. Faltaban diez entradas —todo el bloque de documentos,
# los tres de proceso, los dos de requisitos y el alta pública—, y como el
# `.get()` de abajo cae al `event_type` crudo, el egresado veía
# «document_uploaded» y «document_approved» en su propio historial. El dominio
# completo vive en `models/process_event.py::EVENT_TYPES` y `test_event_labels.py`
# cruza este dict contra él: agregar un evento sin etiqueta aquí rompe el test.
_EVENT_LABELS = {
    # ---- Proceso -------------------------------------------------------
    "process_created":             "Te dieron de alta en la convocatoria",
    # Lo escribe `CohortService.set_window` al cerrar y reabrir la convocatoria.
    # Es la explicación de por qué el trámite se quedó quieto sin que el alumno
    # hiciera nada, así que callarlo es justo lo contrario de lo que sirve.
    "process_paused":              "Tu proceso quedó en pausa",
    "process_resumed":             "Tu proceso se reanudó",
    # `ProcessService.cancel`: la inscripción se revocó (texto neutro: no se
    # atribuye a un área; mismo término que la tarjeta del dashboard).
    "process_cancelled":           "Tu inscripción fue revocada",
    "enrollment_self_service":     "Te inscribiste desde el formulario público",
    # `EnrollmentRequestService.reassign_nip` (el correo con tu NIP no salió).
    "enrollment_access_reset":     "Se reasignó tu NIP de acceso",
    # ---- Documentos iniciales ------------------------------------------
    "document_uploaded":           "Subiste un documento",
    "document_approved":           "Te aprobaron un documento",
    "document_rejected":           "Te rechazaron un documento",
    # Neutral a propósito: lo escribe `DocumentService` tanto cuando el alumno
    # borra el suyo como cuando lo retira Servicios Escolares.
    "document_deleted":            "Se eliminó un documento",
    # ---- Requisitos de cotejo ------------------------------------------
    "requirement_fulfilled":       "Te acreditaron un requisito",
    "requirement_unfulfilled":     "Se desmarcó un requisito",
    # ---- Fases ----------------------------------------------------------
    "phase_approved":              "Fase aprobada",
    "phase_rejected":              "Fase rechazada",
    # ---- Cita de cotejo --------------------------------------------------
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
    # Constancia previa de la encuesta (D9, spec 2026-10-01-titulatec-
    # biblioteca-caja-design.md §4.12): `SurveyReviewService.register_prior`.
    "survey_review_prior":         "Tu encuesta quedó liberada por tu constancia previa",
    # ---- No adeudo de biblioteca (Biblioteca -> Caja), spec 2026-10-01 ----
    "library_debt_registered":     "Biblioteca registró tu adeudo",
    "library_no_charge":           "Biblioteca registró que no debes nada",
    "library_amount_corrected":    "Biblioteca corrigió tu monto",
    "library_payment_registered":  "Pagaste tu no adeudo en Caja",
    "library_prior_registered":    "Registraste tu constancia previa de biblioteca",
    "library_payment_reverted":    "Se revirtió tu pago de biblioteca",
    "library_clearance_reverted":  "Se revirtió tu no adeudo de biblioteca",
    "library_prior_undone":        "Se deshizo tu constancia previa de biblioteca",
}


_DASHBOARD_URL = "/titulatec/student/dashboard"

# Encuesta de egresados: mismo path que `pages/public.py::SURVEY_URL` (Tarea 3).
# Literal propio y no un import de ese módulo (en edición paralela en este
# checkout) para no acoplar dos archivos que dos tareas tocan a la vez.
_SURVEY_URL = "/titulatec/encuesta-egresados"

# Corte a T-soft (Tarea 3, spec 2026-09-21-titulatec-dpto-titulacion §4): copy
# de PANTALLA para la fase actual y las futuras a partir de
# `PhaseService._handoff_phase()`. CON acentos a propósito -- a diferencia de
# `PhaseService.HANDOFF_MSG` (sin acentos, viaja en el header `X-Tt-Error` de
# las guardas), esto es texto Jinja normal, no un header HTTP. Constante de
# módulo para que el contexto (`_phases_ctx`) y la plantilla usen la MISMA
# cadena, en vez de repetirla a mano.
_HANDOFF_COPY = ("Tu proceso continúa en el Departamento de Titulación, en el sistema "
                 "T-soft. El departamento te contactará por correo para darte tu usuario.")

# Ruling R12 (revisión de T5, spec 2026-10-01-titulatec-biblioteca-caja-
# design.md §4.4.4/§4.10, D17): la regla 3 de `SelfBookingService.eligibility`
# (liberaciones) corre ANTES que la 4/5 (`tiene_cita`/`cotejo_en_dictamen`)
# -- es CONTRATO, no se reordena --, así que un egresado cuya cita vigente
# OCUPA el cotejo (D17: las citas previas no se tocan) y le falta el no
# adeudo reporta el motivo de biblioteca (`biblioteca_en_revision`/
# `pago_pendiente`), nunca `tiene_cita`/`cotejo_en_dictamen`. El texto de
# `SelfBookingService.MENSAJES` para esos dos motivos promete "Podrás agendar
# en cuanto se libere tu no adeudo", que es FALSO con una cita que ocupa el
# cotejo: no le falta agendar, le falta que Servicios Escolares pueda
# LIBERAR su cotejo -el mismo verbo que ya usa `PhaseService._cotejo_gate_
# error`, "No se puede liberar la fase 02" mientras falte algún requisito
# ACTIVO y OBLIGATORIO (biblioteca incluida, una vez que la convocatoria la
# exige) -, porque el no adeudo es uno de esos requisitos. `_agenda_ctx`
# sustituye el texto SOLO para esta pantalla (`agenda.message`, cara 4 de
# `_cita_panel.html`); `SelfBookingService.MENSAJES` no cambia -lo sigue
# usando quien SÍ puede agendar, el cubo D10 de la cola y los correos (D11)-.
#
# Ruling R18 (revisión de la Tarea 12): "OCUPA el cotejo" NO es "tiene una
# cita vigente" a secas -una `no_show`, o una `attended` con la fase 2 YA
# `rejected`, SÍ van a agendar otra, y ahí el mensaje correcto sigue siendo
# el de `MENSAJES`-. El predicado exacto es `SelfBookingService.
# cita_ocupa_el_cotejo` (gemelo del que ya usaba `mail_compose.py::
# _que_falta`, D11/Ruling R17).
_LIBRARY_REASONS_CON_CITA = ("biblioteca_en_revision", "pago_pendiente")
_LIBRARY_BLOCK_WITH_CITA_MSG = (
    "Ya tienes una cita de cotejo. Tu no adeudo de biblioteca debe quedar "
    "liberado (Biblioteca y, si corresponde, Caja) para que Servicios "
    "Escolares pueda liberar tu cotejo."
)


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


def _initial_docs_set_guard(db, process, dtype) -> Response | None:
    """400 + `X-Tt-Error` si `dtype` es de la fase `initial_docs` pero su código
    NO está en el set del PERFIL de `process` (spec 2026-09-30-titulatec-
    posgrado-design.md §4.4, "hueco cerrado"; invariante 4).

    Cierra el hueco que `_phase_guard` no tapa: esa guarda solo compara
    `dtype.phase_number` contra `process.current_phase` (CUALQUIER tipo de la
    fase 1 la pasa), así que sin esto licenciatura podía subir los 4 extras de
    posgrado (`professional_license`, `degree_title`, `postgrad_authorization`,
    `efirma_sat`) y CUALQUIER perfil podía subir un tipo de fase 1 activo en el
    catálogo pero fuera de las dos listas de `DocumentService` (p. ej.
    `egel_proof`).

    Solo opina sobre `initial_docs`: el resto de fases no tiene sets por
    perfil y sigue dependiendo nada más de `_phase_guard`. Sin proceso, `None`
    (nada que guardar aquí; cada ruta ya resuelve "no tienes proceso" por su
    cuenta) -- mismo criterio que `_phase_guard`.
    """
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    if process is None:
        return None
    if dtype.phase_number != PhaseService.phase_number_for_code(db, "initial_docs"):
        return None
    if dtype.code in DocumentService.initial_doc_types_for(db, process):
        return None
    return Response(status_code=400, headers={
        "X-Tt-Error": _hdr("Este documento no aplica a tu proceso."),
    })


def _slot_ctx(dtype, doc, *, error: str | None = None, sent_at=None) -> dict:
    """Contexto autónomo de un slot de documento para el parcial.

    `hint` es la ayuda de la casilla; la de PDF sale de la config
    (`storage.pdf_upload_hint`), nunca escrita en la plantilla.

    `sent_at` (Tarea 2, 2026-09-28, spec §4 A3): fecha/hora de la ULTIMA
    subida real de este documento -- el llamador la resuelve con
    `DocumentService.last_uploads` (respaldo `doc.created_at`) porque esta
    función no abre sesión de BD. Se formatea aquí a `sent_label`
    ("Enviado el {dia_mes_hora}") con `utils/dates_es`, o `None` sin fecha o
    sin documento (nada que enviar).
    """
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.apps.titulatec.utils.storage import pdf_upload_hint

    hint = pdf_upload_hint() if dtype.file_kind == "pdf" else "Imagen (jpg, png, webp)"
    return {
        "dtype": {"code": dtype.code, "name": dtype.name, "file_kind": dtype.file_kind},
        "hint": hint,
        "doc": ({
            "review_status": doc.review_status,
            "review_note": doc.review_note,
            "original_name": doc.original_name,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes or 0,
            "version": doc.version,
        } if doc else None),
        "sent_label": (f"Enviado el {dia_mes_hora(sent_at)}" if (doc and sent_at) else None),
        "upload_url": f"/titulatec/student/documents/{dtype.code}",
        "delete_url": f"/titulatec/student/documents/{dtype.code}",
        "error": error,
    }


def _docs_status_ctx(db, process) -> dict:
    """Contexto del aviso de pie de Documentos (`#tt-docs-status`, Tarea 2,
    2026-09-28, spec §4 A4).

    Prioridad YA resuelta aquí (rechazados > faltantes > aprobados >
    enviados): `initial_docs_summary` reparte los documentos iniciales DEL
    PERFIL del proceso (spec 2026-09-30-titulatec-posgrado-design.md §4.4:
    licenciatura, 3; posgrado, 7) entre exactamente un `status` cada uno
    (`approved|rejected|pending|missing`), así que los 4 estados de salida son
    mutuamente excluyentes.

    `contact_email` solo se resuelve para `state == "sent"` (el único texto
    que lo usa, spec A4 #4): evita la consulta de respaldo a
    `EnrollmentRequest` cuando no hace falta. `next_url` solo para
    `state == "approved"` (spec A4 #3, liga a la cita de cotejo). `total` es
    el tamaño del set del PROPIO proceso -- lo usa `_docs_status.html` para
    "Tus N documentos..." (con N=3 el texto de licenciatura queda igual).
    """
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    summary = DocumentService.initial_docs_summary(db, process.id, process=process)
    counts = summary["counts"]
    if counts["rejected"]:
        state = "rejected"
    elif counts["missing"]:
        state = "missing"
    elif counts["approved"] == summary["total"]:
        state = "approved"
    else:
        state = "sent"

    return {
        "state": state,
        "missing_names": [it["name"] for it in summary["items"] if it["status"] == "missing"],
        "contact_email": (StudentMail.contact_email(db, process) if state == "sent" else None),
        "next_url": ("/titulatec/student/cita" if state == "approved" else None),
        "total": summary["total"],
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
        "scheduled_label": AppointmentService.when(appt)["label"],
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


def _library_block_ctx(summary: dict) -> dict:
    """Shapea `LibraryClearanceService.summary_for_process` para el bloque del
    dashboard y la fila de «Mi cita» (spec 2026-10-01-titulatec-biblioteca-
    caja-design.md §4.10): mismas llaves, más `total_fmt` y `breakdown` YA
    FORMATEADOS -- la plantilla no hace aritmética ni decide moneda
    (`format_amount`, nunca `float`).

    `breakdown` es el MISMO texto que ya arma `LibraryClearanceService.
    _mark_ready` para el aviso in-app del alumno («adeudo $800.00 + donación
    voluntaria de libro $200.00»): solo las partes > 0 -- Biblioteca puede
    registrar adeudo 0 con donación > 0 (D18: total 0, las DOS en 0, es lo
    único que libera sin pasar por Caja; adeudo 0 con donación sí pasa).
    """
    from itcj2.apps.titulatec.services.library_clearance_service import format_amount

    out = dict(summary)
    out["total_fmt"] = format_amount(summary.get("total"))
    debt = summary.get("debt") or 0
    donation = summary.get("donation") or 0
    partes = []
    if debt > 0:
        partes.append(f"adeudo {format_amount(debt)}")
    if donation > 0:
        partes.append(f"donación voluntaria de libro {format_amount(donation)}")
    out["breakdown"] = " + ".join(partes)
    return out


def _cta_for(code: str, *, is_current: bool, status: str, handoff: bool) -> dict | None:
    """CTA de una fase. `_PHASE_CTA` sigue siendo la ÚNICA fuente de los enlaces.

    Solo acciona la fase ACTUAL: las anteriores están cerradas (inmutables) y las
    siguientes son informativas — el alumno se prepara ahí, no ejecuta.

    `handoff` (Tarea 3, spec 2026-09-21-titulatec-dpto-titulacion): a partir del
    corte a T-soft ninguna fase se acciona desde aquí, ni la actual. Hoy la única
    entrada de `_PHASE_CTA` que puede caer en el corte es `format_b` (fase 3 por
    defecto) — sin esto, el alumno vería un botón que lo manda a una pantalla que
    el guardia del backend (Tarea 2) ya le bloquea.
    """
    if not is_current or status == "skipped" or handoff:
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
          "handoff_copy":  str,          # copy de pantalla del corte a T-soft
                                          # (constante `_HANDOFF_COPY`, D3 Tarea 3)
          "current":       card | None,  # la MISMA card de la fase actual (col. A)
          "phases":        [card, ...],  # las 9, en orden de catálogo
        }

    Cada ``card``::

        number, code, name, icon, responsible, responsible_label
        responsible_label_de    str    `responsible_label` ya con "de"/"del" al
                                 frente (`_con_de`, ronda de fix 1, Hallazgo 2):
                                 el único consumidor correcto de "A cargo de/del
                                 X" (dashboard.html:73). NO uses `responsible_label`
                                 a secas ahí -- "de el Depto." es el bug que este
                                 campo arregla. `dashboard.html:115` ("En proceso
                                 por…") sigue usando `responsible_label` sin
                                 contraer: "por el" no contrae en español.
        status            pending|in_progress|in_review|approved|rejected|skipped
        rel               "past" | "current" | "future"
        is_current        bool
        can_expand        bool   False SOLO en la actual (va grande en la col. A)
        is_open           bool   deep-link: sale desplegada ya en el HTML
        is_target         bool   deep-link: la fase a RESALTAR. Difiere de `is_open`
                                 solo cuando el deep-link apunta a la fase actual,
                                 que no se despliega pero sí se resalta (col. A).
        handoff           bool   `number >= PhaseService._handoff_phase()` (Tarea 3,
                                 spec 2026-09-21-titulatec-dpto-titulacion). Formula
                                 pura sobre el número de fase: no depende de si hay
                                 proceso ni de en qué fase va el alumno. El template
                                 la usa para pintar `handoff_copy` en vez de "en
                                 proceso por…" (actual) o "se habilitará…" (futura).
        desc, needs, who         copy de `_PHASE_INFO` ("qué vas a necesitar" = needs)
        cta               {url,label,icon} | None   solo la actual, soportada, Y NO
                                                      handoff (`_cta_for`)
        rejection_reason  str | None
        events            [{label, when}]   historial de ESTA fase
        progress          dict | None       sub-progreso (fases 1, 2 y 3); tambien
                                             None cuando `handoff` es True (arreglo
                                             A1, revision final 2026-09-21) -- la
                                             fase ACTUAL congelada por el corte no
                                             puede pintar "Paso 2 de 3" o "Listo
                                             para enviar" AL LADO del aviso de que
                                             esta fase ya no se opera aqui
        survey            dict | None       SOLO en la card `review_appointment`
                                             (dict plano de `summary_for_process`
                                             + `url`, D3, spec §6.1)
        library           dict | None       SOLO en la card `review_appointment`,
                                             Y SOLO si la convocatoria exige el no
                                             adeudo (`ClearanceGate.library_required`,
                                             spec 2026-10-01-titulatec-biblioteca-
                                             caja-design.md §4.4/§4.10): dict plano
                                             de `_library_block_ctx` (= `summary_for_
                                             process` + `total_fmt`/`breakdown`). Sin
                                             el requisito, `None` -- no hay bloque que
                                             pintar, igual que `not_required` del gate.
    """
    from itcj2.apps.titulatec.models import (
        FormatB, PhaseDefinition, ProcessEvent, ProcessPhase,
    )
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.track_service import TrackService, TRACK_LICENCIATURA

    # Corte a T-soft (Tarea 3): se LEE aquí, en cada llamada a `_phases_ctx`
    # (una por carga del dashboard) -- nunca una constante de módulo ni un
    # valor de import time, o la reversibilidad por env var / monkeypatch de
    # `PhaseService._handoff_phase` deja de funcionar (ver su propio docstring).
    handoff_phase = PhaseService._handoff_phase()
    # Perfil del proceso (spec 2026-09-30-titulatec-posgrado-design.md §4.4,
    # invariante 2: el perfil sale SOLO de `TrackService`): decide la variante
    # de `initial_docs` en `_phase_info`. Sin proceso, licenciatura -- mismo
    # criterio que `TrackService.for_process`, sin reventar por `process is
    # None` (esa función exige un proceso real).
    track = TrackService.for_process(db, process) if process is not None else TRACK_LICENCIATURA

    pdefs = (
        db.query(PhaseDefinition)
        .filter_by(is_active=True)
        .order_by(PhaseDefinition.order_index)
        .all()
    )

    def _base_card(pd, **over) -> dict:
        info = _phase_info(pd.code, track)
        resp_label = _RESPONSIBLE_LABEL.get(pd.responsible, "el área responsable")
        card = {
            "number": pd.number,
            "code": pd.code,
            "name": pd.name,
            "icon": pd.icon,
            "responsible": pd.responsible,
            "responsible_label": resp_label,
            "responsible_label_de": _con_de(resp_label),
            "status": "pending",
            "rel": "future",
            "is_current": False,
            "can_expand": True,
            "is_open": pd.number == open_phase,
            "is_target": pd.number == open_phase,
            "handoff": pd.number >= handoff_phase,
            "desc": info.get("desc", ""),
            "needs": [_with_pdf_limits(n) for n in info.get("needs", [])],
            "who": info.get("who", ""),
            "cta": None,
            "rejection_reason": None,
            "events": [],
            "progress": None,
            "survey": None,
            "library": None,
        }
        card.update(over)
        return card

    if process is None:
        # Sin proceso no hay fase actual: las 9 son informativas y desplegables.
        return {"has_process": False, "current_phase": 0, "progress_pct": 0,
                "open_phase": open_phase, "handoff_copy": _HANDOFF_COPY,
                "current": None, "phases": [_base_card(pd) for pd in pdefs]}

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

    # No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-
    # design.md §4.10): UNA consulta fija más -- `ClearanceGate.library_required`
    # nunca siembra (su propio docstring) -- y, SOLO si la convocatoria exige el
    # no adeudo, otra para la foto plana. Convocatoria sin el requisito ACTIVO
    # (incluida toda convocatoria hasta que corra `init-biblioteca-caja`, §4.4):
    # `library` se queda `None` y el bloque no existe, igual que `survey` nunca
    # se apaga (la encuesta es incondicional, D6) pero el no adeudo sí puede
    # estarlo.
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate
    library = None
    if ClearanceGate.library_required(db, process.cohort_id):
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        library = _library_block_ctx(
            LibraryClearanceService.summary_for_process(db, process.id))

    ph_by_number = {
        ph.phase_number: ph for ph in
        db.query(ProcessPhase).filter_by(process_id=process.id).all()
    }

    events_by_phase: dict[int, list] = {}
    # `(created_at, id)`, como el expediente y `process_service`: los eventos de
    # una misma transacción comparten `created_at` (el `NOW()` de la
    # transacción) y Postgres no promete el orden de los empates. «Atender
    # ahora» escribe dos seguidos, y sin el `id` «Cotejo en proceso» podía salir
    # antes que «Cita agendada».
    for ev in (db.query(ProcessEvent)
               .filter_by(process_id=process.id)
               .order_by(ProcessEvent.created_at, ProcessEvent.id).all()):
        # Un evento sin fase no pertenece a ningún acordeón; no lo colgamos de una
        # fase arbitraria para no inventar historial.
        if ev.phase_number is None:
            continue
        events_by_phase.setdefault(ev.phase_number, []).append({
            "label": _EVENT_LABELS.get(ev.event_type, ev.event_type),
            "when": _cita_label(ev.created_at),
        })

    progress_by_code = {
        "initial_docs": _docs_progress(
            DocumentService.initial_docs_summary(db, process.id, process=process)),
        "review_appointment": _appt_progress(AppointmentService.get_for_process(db, process.id)),
        "format_b": _format_b_progress(db.get(FormatB, process.id)),
    }

    cards = []
    for pd in pdefs:
        ph = ph_by_number.get(pd.number)
        status = ph.status if ph else "pending"
        is_current = pd.number == current_phase
        rel = "current" if is_current else ("past" if pd.number < current_phase else "future")
        handoff = pd.number >= handoff_phase

        progress = progress_by_code.get(pd.code)
        # Arreglo A1 (revision final 2026-09-21): la fase >= corte NUNCA pinta
        # sub-progreso, ni siquiera la ACTUAL (`rel == "current"`) -- un
        # Formato B a medias ("Paso 2 de 3") justo encima del aviso de que esa
        # fase ya no se opera aqui es la contradiccion que este `if` cierra.
        # Antes solo se anulaba en `rel == "future"`, que nunca cubria la
        # propia fase congelada. Y, aparte del corte: una fase futura que
        # nadie ha tocado tampoco muestra un sub-progreso vacío.
        if progress and (handoff or (rel == "future" and not progress["started"])):
            progress = None

        cards.append(_base_card(
            pd,
            status=status,
            rel=rel,
            is_current=is_current,
            can_expand=not is_current,
            is_open=(not is_current) and pd.number == open_phase,
            is_target=pd.number == open_phase,
            handoff=handoff,
            cta=_cta_for(pd.code, is_current=is_current, status=status, handoff=handoff),
            rejection_reason=(ph.rejection_reason if ph else None),
            events=events_by_phase.get(pd.number, []),
            progress=progress,
            survey=(survey if pd.code == "review_appointment" else None),
            library=(library if pd.code == "review_appointment" else None),
        ))

    total = len(pdefs) or 9
    return {
        "has_process": True,
        "current_phase": current_phase,
        "progress_pct": int(round(current_phase / total * 100)),
        "open_phase": open_phase,
        "handoff_copy": _HANDOFF_COPY,
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
        # Inscripción revocada (`ProcessService.cancel`): «Tu inscripción fue
        # cancelada: motivo» EN LUGAR de la tarjeta de la fase actual, que
        # ofrecería una acción que la guarda de fase ya no deja hacer.
        from itcj2.apps.titulatec.services.process_service import ProcessService
        info = ProcessService.cancellation_info(db, process)
        ctx["cancelled"] = ({"reason": info["reason"],
                             "when": _cita_label(info["at"]) if info["at"] else None}
                            if info else None)
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
    """Página de documentos iniciales (fase 1) con dropzones HTMX.

    El set de espacios sale del PERFIL del proceso
    (`DocumentService.initial_doc_types_for`, spec 2026-09-30-titulatec-
    posgrado-design.md §4.4, invariante 1): licenciatura, 3; posgrado, 7 (los
    3 de siempre + 4 extras). Los 4 extras traen su propia línea de ayuda
    (`DocumentService.INITIAL_DOC_HINTS`, `doc_hint` en el contexto del slot)
    -- ADEMÁS de la ayuda de formato (PDF/imagen) que ya trae `_slot_ctx`, no
    en su lugar. Con licenciatura (`docs_total == 3`) los textos dinámicos de
    la plantilla quedan byte a byte como antes (Controller ruling R1).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.track_service import TrackService, TRACK_LICENCIATURA

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        fuera_de_fase = _phase_guard_page(db, process, _phase_of(db, "initial_docs"))
        if fuera_de_fase:
            return fuera_de_fase
        track = TrackService.for_process(db, process) if process else TRACK_LICENCIATURA
        slots = []
        status_ctx = None
        if process:
            codes = DocumentService.initial_doc_types_for(db, process)
            # UN lote para todos los slots (Tarea 2, spec A3): "Enviado el ..." es
            # la ULTIMA subida real de cada tipo, no `doc.created_at` (que no
            # se resetea al resubir).
            sent_map = DocumentService.last_uploads(db, [process.id], codes=codes)
            for code in codes:
                dtype = db.query(DocumentType).filter_by(code=code, is_active=True).first()
                if not dtype:
                    continue
                doc = DocumentService.get_document(db, process.id, code)
                sent_at = sent_map.get((process.id, code)) or (doc.created_at if doc else None)
                slot = _slot_ctx(dtype, doc, sent_at=sent_at)
                slot["doc_hint"] = DocumentService.INITIAL_DOC_HINTS.get(code)
                slots.append(slot)
            status_ctx = _docs_status_ctx(db, process)
        all_uploaded = bool(slots) and all(s["doc"] for s in slots)
        ctx = {
            "process": process.to_dict() if process else None,
            "slots": slots,
            "all_uploaded": all_uploaded,
            "status": status_ctx,
            "track": track,
            "docs_total": len(slots),
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
    """Sube/sobreescribe un documento. Devuelve el parcial del slot (HTMX).

    Tarea 2 (2026-09-28, spec §4 A4): la respuesta trae ADEMÁS el aviso de
    estado (`#tt-docs-status`) pegado por `hx-swap-oob` -- esta ruta solo
    reemplaza su propio `#slot-{code}`, así que el refresco del aviso viaja
    aparte, en la MISMA respuesta (también cuando hay error: 200 +
    `X-Tt-Error`, el estado del proceso no cambió pero el aviso puede seguir
    diciendo lo mismo que antes de intentar)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils import storage
    from itcj2.apps.titulatec.utils.storage import StorageError, check_pdf_upload_size

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
        # Hueco cerrado (spec §4.4): `_phase_guard` solo mira la FASE del tipo,
        # no si el CÓDIGO aplica al perfil del proceso -- sin esto, licenciatura
        # subía los 4 extras de posgrado y cualquiera subía un tipo de fase 1
        # activo pero fuera de las dos listas de `DocumentService`. Antes de
        # leer el cuerpo o tocar storage (orden: dtype -> proceso ->
        # `_phase_guard` -> set -> storage).
        fuera_del_set = _initial_docs_set_guard(db, process, dtype)
        if fuera_del_set:
            return fuera_del_set

        error = None
        doc = DocumentService.get_document(db, process.id, type_code)
        try:
            # Antes de leer el cuerpo: un PDF que ya excede lo que se acepta
            # para comprimir (`TITULATEC_MAX_PDF_UPLOAD_SIZE`) no se sube a
            # memoria. `prepare_document` lo vuelve a comprobar sobre los bytes.
            if dtype.file_kind == "pdf":
                check_pdf_upload_size(archivo.size)
            file_kind = dtype.file_kind
            _, control = DocumentService._storage_keys(db, process)
            # Fin de la transacción de LECTURA antes de lo lento (leer el cuerpo
            # y comprimir tardan segundos): abierta, la conexión quedaba «idle in
            # transaction» y, con PgBouncer transaccional, un backend fijado.
            # No hay nada pendiente (solo se leyó); al volver a tocar `process`
            # o `dtype`, la sesión abre otra transacción, ya corta.
            db.commit()
            raw = await archivo.read()
            # En el threadpool: comprimir un PDF escaneado es CPU (segundos) y
            # en el event loop congelaría el worker entero.
            prepared = await run_in_threadpool(
                storage.prepare_document, raw=raw, original_name=archivo.filename,
                control_number=control, file_kind=file_kind,
            )
            doc = await run_in_threadpool(
                DocumentService.save, db, process, type_code,
                raw=raw, original_name=archivo.filename,
                content_type=archivo.content_type, uploaded_by_id=int(user["sub"]),
                prepared=prepared,
            )
        except (StorageError, ValueError) as exc:
            error = str(exc)

        # Tarea 2: la fecha de envio (exito) o la ULTIMA subida buena previa
        # (error: no se escribio ProcessEvent nuevo) sale del mismo lote.
        sent_map = DocumentService.last_uploads(db, [process.id], codes=[type_code])
        sent_at = sent_map.get((process.id, type_code)) or (doc.created_at if doc else None)
        ctx = _slot_ctx(dtype, doc, error=error, sent_at=sent_at)
        ctx["doc_hint"] = DocumentService.INITIAL_DOC_HINTS.get(type_code)
        ctx["status_oob"] = _docs_status_ctx(db, process)
        resp = render_titulatec(request, "titulatec/partials/document_slot.html", ctx)
        if error:
            # Percent-codificado (`_hdr`): los mensajes de `storage` llevan
            # acentos («escanéalo», «máximo») y un header se escribe en latin-1.
            # `static/js/student/errors.js` lo decodifica.
            resp.headers["X-Tt-Error"] = _hdr(error)
        return resp
    finally:
        db.close()


@router.delete("/documents/{type_code}", name="titulatec.pages.student.document_delete")
async def document_delete(
    type_code: str,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.delete.own"])),
):
    """Elimina un documento. Devuelve el parcial del slot vacío (HTMX).

    Tarea 2 (2026-09-28, spec §4 A4): igual que la subida, la respuesta trae
    el aviso de estado (`#tt-docs-status`) pegado por `hx-swap-oob` -- borrar
    puede regresar la fase a "en curso" o descompletar la fase 1, y el aviso
    tiene que reflejarlo sin recargar la página."""
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
        # Mismo hueco que en la subida (spec §4.4): un código de fase 1 que no
        # aplica al perfil del proceso tampoco se BORRA -- da igual que la fila
        # exista o no (`DocumentService.delete` ya no-opea sin fila). Orden:
        # dtype -> proceso -> `_phase_guard` -> set -> storage.
        fuera_del_set = _initial_docs_set_guard(db, process, dtype)
        if fuera_del_set:
            return fuera_del_set
        if process:
            DocumentService.delete(db, process.id, type_code, actor_id=int(user["sub"]))
        ctx = _slot_ctx(dtype, None)
        ctx["doc_hint"] = DocumentService.INITIAL_DOC_HINTS.get(type_code)
        if process:
            ctx["status_oob"] = _docs_status_ctx(db, process)
        return render_titulatec(request, "titulatec/partials/document_slot.html", ctx)
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
    from itcj2.apps.titulatec.services.library_clearance_service import (
        AUTO_SOURCE_LIBRARY, LibraryClearanceService,
    )
    from itcj2.apps.titulatec.services.requirement_service import RequirementService
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html

    # Estatus de la solicitud de liberación de GTV (D3, spec §6.1): una sola
    # consulta fija, igual que `_phases_ctx`, aunque solo la use la fila con
    # `auto_source == "graduate_survey"`.
    survey = SurveyReviewService.summary_for_process(db, process.id)
    # Gemela para el no adeudo de biblioteca (spec 2026-10-01-titulatec-
    # biblioteca-caja-design.md §4.10, "Mi cita"): otra consulta fija, aunque
    # solo la use la fila `auto_source == AUTO_SOURCE_LIBRARY` -esa fila solo
    # existe en `list_with_status` si la convocatoria tiene el requisito
    # ACTIVO (`list_or_seed(..., active_only=True)`), así que no hace falta
    # volver a preguntarle a `ClearanceGate`: su sola presencia ya lo dice.
    library = _library_block_ctx(LibraryClearanceService.summary_for_process(db, process.id))

    out = []
    for it in RequirementService.list_with_status(db, process.id):
        req, ful = it["requirement"], it["fulfillment"]
        es_encuesta = req.auto_source == "graduate_survey"
        es_biblioteca = req.auto_source == AUTO_SOURCE_LIBRARY
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
            # Gemela de "survey" (§4.10): lo liberan Biblioteca y Caja, no el
            # alumno -- MISMA píldora que el dashboard (`library_clearance_pill`),
            # sin liga propia: a diferencia de la encuesta, aquí no hay nada que
            # el alumno pueda resolver desde esta pantalla.
            "library": (library if es_biblioteca else None),
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
    """Las cuatro caras de §7, resueltas en DATOS PLANOS (D10/D11, Tarea 9).

    Planas porque la plantilla se renderiza DESPUÉS del `db.close()` de la
    ruta: un atributo perezoso sobre una instancia ya desanclada lanzaría
    `DetachedInstanceError` (mismo motivo que `_checklist_ctx`). `offer()` ya
    devuelve dicts, así que aquí solo se les da forma de pantalla: las horas se
    formatean AQUÍ y no en Jinja, para que la plantilla no haga aritmética.

    `eligibility` decide QUIÉN puede y `offer` QUÉ hay. Un espacio `walkin`
    (D3/D4, spec 2026-09-29-titulatec-cotejo-espacios-design.md §3.3) YA es
    agendable -el egresado aparta lugar sin hora-, así que desde la Tarea 9
    viaja DENTRO de `dias`, junto a las franjas: ya no hay una lista `walkins`
    aparte.

    `modo` es lo que decide la plantilla para pintar el selector:

    * `"agendar"` -- `can_book` y algo publicado (franjas O sin horario: D3/D4
      hace que apartar lugar SEA agendar). Se ofrecen las dos clases de ventana.
    * `"presentarse"` -- `can_walkin` sin `can_book` (el bloqueado de la regla 6,
      D9): perdió el derecho a RESERVAR, no el de PRESENTARSE. Se filtran las
      franjas -no puede tomarlas- y solo quedan los espacios `walkin`, SIN
      botón: el texto dice que se presente, no que aparte.
    * `None` -- ninguna de las dos: cara 4 sola, con `message`.

    La 3 y la 4 conviven a propósito en el único caso donde eso importa: el
    bloqueado por D9 no puede reservar pero sí presentarse, y `message` no se
    apaga por `modo == "presentarse"`.

    Ruling R12 (spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.4.4/
    §4.10), refinada por Ruling R18: con un motivo de biblioteca Y una cita
    vigente que OCUPA el cotejo (`SelfBookingService.cita_ocupa_el_cotejo`
    -scheduled/confirmed/in_progress, o `attended` sin veredicto de fase 2-),
    `message` NO es el de `SelfBookingService.MENSAJES` -ese promete
    agendar-, sino `_LIBRARY_BLOCK_WITH_CITA_MSG` (constante de módulo). Una
    cita `no_show`, o `attended` con la fase 2 ya `rejected`, NO ocupa el
    cotejo -el egresado sí va a agendar otra- y sigue con el mensaje normal.
    """
    vacio = {"can_book": False, "can_walkin": False, "reason": None,
             "message": None, "modo": None, "dias": [], "dia_sel": None,
             "dia_actual": None, "hay_sin_horario": False}
    if process is None:
        return vacio

    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    elig = SelfBookingService.eligibility(db, process.id)
    oferta = SelfBookingService.offer(db, process.id)

    todas_las_ventanas = [w for jornada in oferta for dueno in jornada["owners"]
                          for w in dueno["windows"]]
    hay_sin_horario = any(w["visibility"] == "walkin" for w in todas_las_ventanas)
    if elig["can_book"] and todas_las_ventanas:
        modo = "agendar"
    elif elig["can_walkin"] and hay_sin_horario:
        modo = "presentarse"
    else:
        modo = None

    dias = []
    for jornada in oferta:
        fecha = jornada["date"]
        duenos = []
        for dueno in jornada["owners"]:
            ventanas = []
            for w in dueno["windows"]:
                es_walkin = w["visibility"] == "walkin"
                if modo == "presentarse" and not es_walkin:
                    # Bloqueado por D9: solo se PRESENTA, y solo a un espacio
                    # SIN HORARIO. Una franja agendable no le sirve -no puede
                    # reservarla- y mezclarla aquí prometería un botón que el
                    # servidor va a rechazar.
                    continue
                if es_walkin:
                    slots_visible, slots_more = [], []
                else:
                    horas = [f"{s:%H:%M}" for s in w["slots"]]
                    slots_visible, slots_more = horas[:12], horas[12:]
                ventanas.append({
                    "window_id": w["window_id"],
                    "kind": "sin_horario" if es_walkin else "franjas",
                    "range": f'{w["start_time"]:%H:%M} a {w["end_time"]:%H:%M}',
                    "location": w["location"],
                    # 12 visibles + «Ver N horas más» (D10). Vacío en un
                    # `sin_horario`: ahí no hay franjas que listar.
                    "slots_visible": slots_visible,
                    "slots_more": slots_more,
                    "places_left": w.get("places_left") if es_walkin else None,
                    "capacity": w.get("capacity") if es_walkin else None,
                    "reservable": w.get("reservable") if es_walkin else None,
                    # I-2 (revisión final): por qué no es reservable, y el
                    # cierre ya formateado para el texto de «cierra pronto».
                    "motivo": w.get("motivo") if es_walkin else None,
                    "cierre": f'{w["end_time"]:%H:%M}' if es_walkin else None,
                })
            if ventanas:
                duenos.append({"owner_name": dueno["owner_name"], "windows": ventanas})
        if duenos:
            # Encargados plegables (D10): abiertos los dos si son ≤2 ese día,
            # si no solo el primero -mismo orden que ya trae `offer()`, por
            # nombre-.
            pocos = len(duenos) <= 2
            for i, du in enumerate(duenos):
                du["open"] = pocos or i == 0
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
    #
    # Ruling R12: con una cita VIGENTE que OCUPA el cotejo (D17) el motivo
    # reportado puede ser de biblioteca -la regla 3 de `eligibility` corre
    # antes que la 4/5, es contrato- y el texto normal de `SelfBookingService.
    # MENSAJES` prometería "podrás agendar" bajo la cita que ya tiene, que es
    # falso. Se sustituye SOLO aquí, sin tocar `eligibility` ni `MENSAJES`
    # (constantes `_LIBRARY_REASONS_CON_CITA`/`_LIBRARY_BLOCK_WITH_CITA_MSG`).
    #
    # Ruling R18 (revisión de la Tarea 12): "OCUPA el cotejo" es
    # `SelfBookingService.cita_ocupa_el_cotejo`, NO un simple `elig["current"]
    # is not None` -ese blanco también atrapaba `no_show` y `attended` con la
    # fase 2 YA `rejected`, los dos casos en que el egresado SÍ tiene que
    # agendar otra y el mensaje correcto vuelve a ser el de `MENSAJES`
    # ("Podrás agendar en cuanto se libere tu no adeudo"), no este.
    if elig["reason"] == "tiene_cita":
        message = None
    elif (elig["reason"] in _LIBRARY_REASONS_CON_CITA
          and SelfBookingService.cita_ocupa_el_cotejo(db, process, elig["current"])):
        message = _LIBRARY_BLOCK_WITH_CITA_MSG
    else:
        message = SelfBookingService.message_for(
            elig["reason"], cancellations=elig["cancellations"],
            total=elig.get("library_total"))

    return {"can_book": elig["can_book"], "can_walkin": elig["can_walkin"],
            "reason": elig["reason"], "message": message, "modo": modo,
            "dias": dias, "dia_sel": dia_sel, "dia_actual": dia_actual,
            "hay_sin_horario": hay_sin_horario}


def _cita_label(dt) -> str:
    if not dt:
        return "—"
    return f"{dt.day:02d} {_MONTHS_ES[dt.month]} {dt.year} · {dt:%H:%M}"


def _cita_card_ctx(db, user_id: int, *, agenda: dict | None = None) -> dict:
    """Contexto de la tarjeta de estado de la cita.

    `agenda` (2026-09-18) viaja hasta aqui porque la rama «todavia no tienes
    cita» tiene que decir COSAS DISTINTAS segun lo que el alumno pueda hacer:
    con auto-agendado le toca a el, con atencion sin cita se presenta y ya, y
    solo cuando no hay ninguna de las dos es verdad que Servicios Escolares le
    asignara la fecha. Antes decia siempre lo ultimo, y quedaba contradiciendo
    al selector de horas que estaba tres centimetros mas abajo en la misma
    pantalla.

    Se acepta como parametro para que `_cita_panel_ctx` lo calcule UNA vez y lo
    preste; si nadie lo pasa (los dos POST que swappean solo la tarjeta) se
    calcula aqui, porque un parcial que depende de quien lo incluya es un
    parcial roto esperando su turno.
    """
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
        when = AppointmentService.when(appt)
        appt_ctx = {
            "scheduled_label": when["label"],
            # D11 (Tarea 9): la tarjeta rotula «de HH:MM a HH:MM · por orden
            # de llegada» en vez de una hora fija cuando `sin_horario`.
            "sin_horario": when["sin_horario"],
            "hora": when["hora"],
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
    # lee de `ProcessPhase`, igual que `_fase_cotejo_status` en
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
        "agenda": agenda if agenda is not None else _agenda_ctx(db, process),
    }


def _cita_panel_ctx(db, user_id: int, *, dia: str | None = None) -> dict:
    """Contexto del panel completo: la tarjeta MÁS las cuatro caras de §7.

    Resuelve el proceso con el mismo selector que `_cita_card_ctx`
    (`creditable_process`): la tarjeta y el selector de agendado TIENEN que
    hablar del mismo proceso, o el alumno vería la cita de uno y agendaría en
    el otro.

    La agenda se calcula AQUÍ y se le presta a la tarjeta: las dos la necesitan
    —el selector para pintarse y la tarjeta para saber qué decir cuando no hay
    cita— y `offer()` recorre las jornadas de la convocatoria, así que hacerlo
    dos veces por carga sería pagar el doble por el mismo dato.

    `checklist` (Tarea 9, D10): el «Qué llevar» se mudó AL PANEL -antes vivía
    aparte, en `cita.html`-, así que ahora lo calcula este contexto y no la
    ruta `cita()` sola: los dos POST del auto-agendado (`/cita/agendar` y
    `/cita/cancelar`) responden el panel entero y tienen que re-pintarlo igual.
    """
    from itcj2.apps.titulatec.services.process_service import ProcessService

    process = ProcessService.creditable_process(db, user_id)
    agenda = _agenda_ctx(db, process, dia=dia)
    ctx = _cita_card_ctx(db, user_id, agenda=agenda)
    ctx["checklist"] = _checklist_ctx(db, process)
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
        # `_cita_panel_ctx` ya calcula `checklist` (Tarea 9): el panel y la
        # página completa tienen que llevar el mismo dato.
        ctx = _cita_panel_ctx(db, user_id, dia=dia)
    finally:
        db.close()

    # `?dia=` es la MISMA ruta con querystring —no suma al censo de rutas del
    # alumno— y con htmx devuelve solo el selector del día elegido, que es
    # justo lo que se swappea (`#tt-cita-agendar`, `outerHTML`).
    if dia and es_htmx:
        agenda = ctx["agenda"]
        # El selector SOLO si de verdad hay algo que hacer (Tarea 9:
        # `agenda.modo`, no solo `can_book` -el bloqueado por D9 sigue
        # cambiando de día en modo "presentarse"-). Sin esta condición, quien
        # dejó la pestaña abierta y ya agendó (o perdió el derecho) recibía
        # franjas vivas y ninguna explicación: exactamente el «botón mudo» que
        # §7 existe para prohibir. El POST lo revalida, así que no era un
        # agujero — era una mentira en pantalla, que es lo que esta vista no
        # puede permitirse.
        if agenda["modo"] and agenda["dias"]:
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
    * colisión de estado (`refresca_la_vista`, o sea `reason in ("tiene_cita",
      "cotejo_en_dictamen")`) -> **200 con el panel fresco** + `X-Tt-Notice`.
      Es lo que produce un doble clic en «Agendar» -ahí la pantalla SÍ está
      rancia, ya existe una cita que el alumno no está viendo- y, desde D13
      (2026-09-30), también lo que produce que el encargado marque «asistió»
      mientras el alumno tiene esta pantalla abierta: los dos son el servidor
      cambiando de opinión a mitad del clic, y un 4xx lo dejaría mirando un
      selector muerto.
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

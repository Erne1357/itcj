"""Vocabulario CERRADO de la bitácora de TitulaTec (spec 2026-10-07 §4.1 y §5).

Mismo patrón que `models/process_event.py::EVENT_TYPES`: una lista que obliga.
`test_audit_actions_contract.py` cruza contra estas constantes todo literal que
el código le pasa a `AuditService.record(`, cada tabla `titulatec_*` del
registro y cada `event_type` de `ProcessEvent`.

Sin dependencias de modelos ni de servicios, a propósito: lo importan la
escucha `after_flush` (que se instala al cargar `models/`), el servicio y la
página de la bitácora, y ninguno puede arrastrar un ciclo de imports.

Reglas de nombres (las barre el contrato):
- Códigos con PUNTO: `{segmento}.{verbo}` (`cohort.window_changed`). El segmento
  nunca empieza como un `event_type` de `ProcessEvent` (`process_`,
  `document_`, `phase_`, `requirement_`, `appointment_`, `survey_review_`,
  `enrollment_`, `library_` + guion bajo): `test_event_labels.py` barre esos
  literales en `services/` y los confundiría con eventos.
- `process.*` y `data.*` NO van en `AUDIT_ACTIONS`: los escribe la escucha (el
  espejo de `ProcessEvent` y la red ORM), nunca `record`.
- Etiquetas en español, en pasado, cortas, sin punto final.

Para agregar una acción: en el bloque de SU módulo, aquí, en la misma tarea que
la registra.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Módulos (filtro principal de la UI): clave -> etiqueta
# ---------------------------------------------------------------------------
AUDIT_MODULES: dict[str, str] = {
    "processes": "Procesos",
    "documents": "Documentos",
    "appointments": "Citas",
    "cohorts": "Convocatorias",
    "windows": "Espacios de cotejo",
    "format_b": "Formato B",
    "enrollment": "Solicitudes",
    "access": "Accesos",
    "officers": "Encargados",
    "import": "Importaciones",
    "library": "Biblioteca",
    "cashier": "Caja",
    "certificates": "Folios",
    "surveys": "Encuestas",
    "mail": "Correos",
    "sii": "SII",
    "system": "Sistema",
    "data": "Datos",
}

# ---------------------------------------------------------------------------
# Acciones explícitas (`AuditService.record`): código -> (módulo, etiqueta)
# ---------------------------------------------------------------------------
AUDIT_ACTIONS: dict[str, tuple[str, str]] = {
    # --- cohorts: convocatorias, días y requisitos de cotejo -------------------
    "cohort.created": ("cohorts", "Creó una convocatoria"),
    "cohort.window_changed": ("cohorts", "Movió la ventana de la convocatoria"),
    "cohort.donation_changed": ("cohorts", "Cambió la donación de libros de la convocatoria"),
    "cohort.review_day_toggled": ("cohorts", "Abrió o cerró un día de cotejo"),
    "cohort.requirement_created": ("cohorts", "Agregó un requisito de cotejo"),
    "cohort.requirement_updated": ("cohorts", "Editó un requisito de cotejo"),
    "cohort.requirement_deleted": ("cohorts", "Borró un requisito de cotejo"),

    # --- windows: espacios de cotejo -----------------------------------------
    "window.created": ("windows", "Creó espacios de cotejo"),
    "window.updated": ("windows", "Editó un espacio de cotejo"),
    "window.paused": ("windows", "Pausó un espacio de cotejo"),
    "window.resumed": ("windows", "Reanudó un espacio de cotejo"),
    "window.places_added": ("windows", "Abrió más lugares en un espacio de cotejo"),
    "window.deleted": ("windows", "Borró un espacio de cotejo"),
    "window.copied": ("windows", "Copió un espacio de cotejo"),

    # --- format_b -------------------------------------------------------------
    "format_b.step_saved": ("format_b", "Guardó un paso del Formato B"),
    "format_b.submitted": ("format_b", "Envió el Formato B"),
    "format_b.reviewed": ("format_b", "Dictaminó el Formato B"),

    # --- enrollment: solicitudes de inscripción ------------------------------
    "enrollment.request_created": ("enrollment", "Envió una solicitud de inscripción"),
    "enrollment.approved": ("enrollment", "Aprobó una solicitud de inscripción"),
    "enrollment.rejected": ("enrollment", "Rechazó una solicitud de inscripción"),
    "enrollment.reopened": ("enrollment", "Reabrió una solicitud de inscripción"),
    "enrollment.link_resent": ("enrollment", "Reenvió la liga de activación"),
    "enrollment.notice_resent": ("enrollment", "Reenvió el aviso de acceso"),
    "enrollment.sii_recheck_requested": ("enrollment", "Pidió volver a consultar al SII"),

    # --- access: bandeja de Accesos de Centro de Cómputo ---------------------
    "access.returned": ("access", "Devolvió una solicitud a revisión"),

    # --- officers: encargados de carrera --------------------------------------
    "officer.created": ("officers", "Dio de alta a un encargado"),
    "officer.users_changed": ("officers", "Cambió las personas de un encargado"),
    "officer.programs_changed": ("officers", "Cambió las carreras de un encargado"),
    "officer.deactivated": ("officers", "Dio de baja a un encargado"),
    "officer.account_reactivated": ("officers", "Reactivó cuentas de un encargado"),

    # --- import: importación de alumnos y cuentas ---------------------------
    "import.students_committed": ("import", "Importó alumnos a una convocatoria"),
    "import.mapping_saved": ("import", "Guardó el mapeo de columnas de la importación"),
    "import.credential_set": ("import", "Asignó credenciales a una cuenta"),
    "import.user_email_changed": ("import", "Cambió el correo de una cuenta"),
    "import.roles_synced": ("import", "Sincronizó los roles de egresado"),

    # --- certificates: folios -------------------------------------------------
    "certificate.issued": ("certificates", "Emitió un folio"),
    "certificate.voided": ("certificates", "Anuló un folio"),
    "certificate.batch_created": ("certificates", "Generó un lote de impresión de folios"),
    "certificate.backfill_run": ("certificates", "Emitió folios de previas y legado"),

    # --- library: liberaciones previas ----------------------------------------
    "prior_clearance.deferred": ("library", "Dejó pendiente una liberación previa"),
    "prior_clearance.replaced": ("library", "Reemplazó una liberación previa"),
    "prior_clearance.import_run": ("library", "Importó liberaciones previas"),

    # --- surveys --------------------------------------------------------------
    "survey.submitted": ("surveys", "Envió la encuesta de egresados"),
    "survey.import_run": ("surveys", "Importó encuestas de Microsoft Forms"),

    # --- system ---------------------------------------------------------------
    "system.cli_command": ("system", "Ejecutó un comando de consola"),
    "system.audit_purged": ("system", "Purgó la bitácora"),
}

# ---------------------------------------------------------------------------
# Lo que escribe la escucha (no `record`)
# ---------------------------------------------------------------------------
# `source` de cada fila: llamada explícita, espejo de `ProcessEvent`, red ORM.
AUDIT_SOURCES: tuple[str, ...] = ("action", "process_event", "data")

# `actor_kind`: usuario con sesión, petición sin sesión, sin contexto, comando
# de consola, tarea de Celery.
ACTOR_KINDS: tuple[str, ...] = ("user", "public", "system", "cli", "celery")

# Espejo: `action = PROCESS_EVENT_PREFIX + event_type` (`process.phase_approved`).
# Su etiqueta la resuelve la página con `pages/admin.py::_EVENT_UI`.
PROCESS_EVENT_PREFIX = "process."

# Red ORM: «Alta / Cambio / Baja en {TABLE_LABELS[tabla]}».
DATA_ACTIONS: dict[str, str] = {
    "data.insert": "Alta",
    "data.update": "Cambio",
    "data.delete": "Baja",
}

# Módulo del espejo por prefijo del `event_type`. El orden importa
# (`library_payment_` antes que `library_`) y es el MISMO `CASE` del backfill de
# la migración `tt20261007b`: el historial copiado y el espejo en vivo caen en
# el mismo módulo.
_EVENT_PREFIX_MODULES: tuple[tuple[str, str], ...] = (
    ("document_", "documents"),
    ("appointment_", "appointments"),
    ("library_payment_", "cashier"),
    ("library_", "library"),
    ("survey_", "surveys"),
    ("enrollment_", "access"),
    ("phase_", "processes"),
    ("process_", "processes"),
    ("requirement_", "processes"),
)


def process_event_module(event_type: str) -> str:
    """Módulo de la fila espejo de un `ProcessEvent`; `processes` si no casa."""
    tipo = event_type or ""
    for prefijo, modulo in _EVENT_PREFIX_MODULES:
        if tipo.startswith(prefijo):
            return modulo
    return "processes"


# ---------------------------------------------------------------------------
# Red ORM: cada tabla titulatec -> módulo y nombre legible
# ---------------------------------------------------------------------------
# El contrato exige que TODA tabla `titulatec_*` de `Base.metadata` esté aquí o
# en `NET_EXCLUDED_TABLES`: una tabla nueva obliga a decidir su módulo.
TABLE_MODULES: dict[str, str] = {
    "titulatec_audit_log": "system",
    "titulatec_ceremonies": "processes",
    "titulatec_ceremony_processes": "processes",
    "titulatec_certificate_batches": "certificates",
    "titulatec_certificate_counters": "certificates",
    "titulatec_certificates": "certificates",
    "titulatec_chat_messages": "processes",
    "titulatec_chats": "processes",
    "titulatec_cohort_review_days": "cohorts",
    "titulatec_cohorts": "cohorts",
    "titulatec_cotejo_requirements": "cohorts",
    "titulatec_document_types": "documents",
    "titulatec_documents": "documents",
    "titulatec_eligibility_checks": "sii",
    "titulatec_email_outbox": "mail",
    "titulatec_enrollment_requests": "enrollment",
    "titulatec_format_b": "format_b",
    "titulatec_library_clearances": "library",
    "titulatec_modalities": "processes",
    "titulatec_phase_definitions": "processes",
    "titulatec_prior_clearances": "library",
    "titulatec_process_events": "processes",
    "titulatec_process_phases": "processes",
    "titulatec_processes": "processes",
    "titulatec_requirement_fulfillments": "processes",
    "titulatec_review_appointments": "appointments",
    "titulatec_review_windows": "windows",
    "titulatec_survey_answers": "surveys",
    "titulatec_survey_drafts": "surveys",
    "titulatec_survey_forms": "surveys",
    "titulatec_survey_responses": "surveys",
    "titulatec_survey_reviews": "surveys",
    "titulatec_synodal_assignments": "processes",
}

TABLE_LABELS: dict[str, str] = {
    "titulatec_audit_log": "Bitácora",
    "titulatec_ceremonies": "Acto protocolario",
    "titulatec_ceremony_processes": "Egresado en acto protocolario",
    "titulatec_certificate_batches": "Lote de impresión de folios",
    "titulatec_certificate_counters": "Contador de folios",
    "titulatec_certificates": "Folio",
    "titulatec_chat_messages": "Mensaje del chat",
    "titulatec_chats": "Chat del proceso",
    "titulatec_cohort_review_days": "Día de cotejo",
    "titulatec_cohorts": "Convocatoria",
    "titulatec_cotejo_requirements": "Requisito de cotejo",
    "titulatec_document_types": "Tipo de documento",
    "titulatec_documents": "Documento",
    "titulatec_eligibility_checks": "Consulta al SII",
    "titulatec_email_outbox": "Correo de la bandeja de salida",
    "titulatec_enrollment_requests": "Solicitud de inscripción",
    "titulatec_format_b": "Formato B",
    "titulatec_library_clearances": "No adeudo de biblioteca",
    "titulatec_modalities": "Modalidad de titulación",
    "titulatec_phase_definitions": "Definición de fase",
    "titulatec_prior_clearances": "Liberación previa",
    "titulatec_process_events": "Evento del proceso",
    "titulatec_process_phases": "Fase del proceso",
    "titulatec_processes": "Proceso de titulación",
    "titulatec_requirement_fulfillments": "Requisito de cotejo cumplido",
    "titulatec_review_appointments": "Cita de cotejo",
    "titulatec_review_windows": "Espacio de cotejo",
    "titulatec_survey_answers": "Respuesta de encuesta",
    "titulatec_survey_drafts": "Borrador de encuesta",
    "titulatec_survey_forms": "Formulario de encuesta",
    "titulatec_survey_responses": "Encuesta respondida",
    "titulatec_survey_reviews": "Liberación de encuesta",
    "titulatec_synodal_assignments": "Sinodal asignado",
}

# D14: la bitácora misma, la tabla de eventos (ya espejada, no se duplica) y la
# bandeja de correos (es su propio registro y Celery la toca cada 5 minutos).
NET_EXCLUDED_TABLES: frozenset[str] = frozenset({
    "titulatec_audit_log",
    "titulatec_process_events",
    "titulatec_email_outbox",
})

# ---------------------------------------------------------------------------
# D9: nunca secretos
# ---------------------------------------------------------------------------
# Toda clave (columna, llave de payload, campo de `before/after`) que CONTENGA
# alguna de estas partes, sin importar mayúsculas, se guarda como "***". Peca de
# más a propósito: `nip_status`/`nip_source` también salen enmascaradas.
SENSITIVE_KEY_PARTS: tuple[str, ...] = ("password", "nip", "token", "secret", "hash")


def is_sensitive_key(key) -> bool:
    """¿La clave nombra algo que nunca debe guardarse en claro?"""
    k = str(key).lower()
    return any(parte in k for parte in SENSITIVE_KEY_PARTS)

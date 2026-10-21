"""Lógica del Formato B (multi-step, reemplaza el Tsoft).

`FormatBService` es la ÚNICA puerta que mueve el Formato B y la fase 3 (spec
2026-10-21-titulatec-fase3-formato-b-titulacion §7): guarda pasos validados,
envía con validación total y congelado, dictamina acoplado a `PhaseService` en
una sola transacción y corrige los datos del registro (§8.5). Del lado del
motor, `approve_phase`/`reject_phase` de la fase `format_b` exigen que el
Formato B ya venga dictaminado en la sesión (`PhaseService.FORMAT_B_ONLY_MSG`):
no hay otra forma de mover la fase 3.

Las reglas de cada campo viven en `format_b_validation` (puro, sin BD); aquí
solo se decide CUÁNDO se valida y qué se escribe.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping

from sqlalchemy.orm import Session
from itcj2.core.utils.timezone import db_now

from itcj2.apps.titulatec.services.format_b_validation import (
    EDITABLE_FIELDS, FIELD_LABELS, FormatBValidationError, ValidationCtx, normalize_phone,
    validate_all, validate_step,
)

# Etiqueta de cada paso (la misma del stepper del alumno).
STEP_LABELS = {1: "Personales", 2: "Escolares", 3: "Proyecto"}

# Campos por paso: los que llena el alumno (fuente única: `EDITABLE_FIELDS`).
STEP_FIELDS = {n: list(campos) for n, campos in EDITABLE_FIELDS.items()}

# Todos los campos que el alumno llena, en orden de pantalla. Son los únicos
# que el revisor puede observar (los del registro los corrige Titulación, D9).
OBSERVABLE_FIELDS = tuple(c for n in sorted(EDITABLE_FIELDS) for c in EDITABLE_FIELDS[n])

# Campos que `get_or_create` PRECARGA del alumno/proceso. No sirven como señal de
# "el alumno pasó por este paso": pueden estar llenos desde el minuto cero (el
# teléfono y la retícula del perfil, la modalidad del alta manual). Los del
# registro (nombre, control, carrera) tampoco cuentan: el alumno no los edita.
PRELOADED_FIELDS = {"first_name", "last_name", "middle_name", "control_number",
                    "program_id", "titulation_type", "mobile_phone", "study_plan",
                    "modality_id"}

# Datos del registro: el alumno no los edita y se congelan al enviar (§6). El
# nº de control no se corrige aquí (es identidad, D9); nombre y carrera sí.
REGISTRY_FIELDS = ("first_name", "last_name", "middle_name", "control_number", "program_id")
CORRECTABLE_FIELDS = ("first_name", "last_name", "middle_name", "program_id")

# Bloques de solo lectura (alumno en «Revisa y envía», pestaña Titulación,
# expediente), con TODOS los campos (corrige P7). Orden de la tabla §5.1.
SECTIONS = (
    ("personal", "Personal", ("first_name", "last_name", "middle_name", "gender", "age",
                              "mobile_phone", "phone", "postal_code", "neighborhood",
                              "street", "ext_number", "int_number")),
    ("escolar", "Escolar", ("control_number", "program_id", "study_plan", "modality_id",
                            "admission_date", "graduation_date")),
    ("proyecto", "Proyecto", ("project_name",)),
)

GENDER_LABELS = {"male": "Hombre", "female": "Mujer", "unspecified": "Prefiero no decir"}
_MESES = ("", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")
_VACIO = "—"
_NO_APLICA = "No aplica para esta modalidad"

# Topes de texto libre del revisor (mismo orden que las observaciones de Biblioteca).
_MAX_NOTE = 1000
_MAX_REASON = 500
_MAX_NAME = 120          # columnas String(120) de la copia del Formato B

# Mensajes (viajan por `X-Tt-Error` con `_hdr`, así que pueden llevar acentos).
EDIT_LOCKED_MSG = "Tu Formato B ya fue enviado: ya no se puede editar."
ALREADY_SUBMITTED_MSG = "Tu Formato B ya fue enviado; no se puede enviar de nuevo."
NOT_IN_REVIEW_MSG = "Este Formato B no está en revisión: el alumno aún no lo envía."
NEED_OBSERVATION_MSG = "Escribe al menos una observación: la nota general o la de algún campo."
NOT_OBSERVABLE_MSG = ("Solo se observan los datos que llena el alumno (nombre y carrera "
                      "se corrigen en el registro). No se puede observar: {campos}.")
NOTE_TOO_LONG_MSG = "Cada observación admite hasta 1000 caracteres."
NO_MODALITY_MSG = ("El Formato B no tiene tipo de titulación: obsérvalo para que el "
                   "alumno lo elija.")
REGISTRY_NOT_IN_REVIEW_MSG = ("El registro solo se corrige mientras el Formato B "
                              "está en revisión.")
REGISTRY_NAME_MSG = "El nombre y el apellido paterno son obligatorios."
REGISTRY_NAME_LONG_MSG = "Cada parte del nombre admite hasta 120 caracteres."
REGISTRY_REASON_MSG = "Escribe el motivo de la corrección (hasta 500 caracteres)."
REGISTRY_PROGRAM_MSG = "La carrera elegida no existe."
REGISTRY_NO_PROGRAM_MSG = ("El proceso no tiene carrera registrada: no se puede comparar "
                           "el nivel de la nueva.")
REGISTRY_LEVEL_MSG = ("La carrera nueva debe ser del mismo nivel que la actual: cambiar de "
                      "nivel cambiaría el perfil de titulación.")
REGISTRY_NO_CHANGES_MSG = "No hay cambios que guardar: los datos ya son esos."


def _to_month_str(d) -> str:
    """Date → 'YYYY-MM' para <input type=month>."""
    return d.strftime("%Y-%m") if d else ""


def _canon(value) -> str | None:
    """Texto canónico de un valor del modelo: lo que el formulario mandaría.

    Es la forma en que `review_observations.fields[*].value` guarda el valor al
    observarse, y la misma con la que se compara después («Corregido ✓»): una
    sola función para los dos lados. Mes → 'YYYY-MM'; vacío → None.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}"
    texto = str(value).strip()
    return texto or None


def _clean(raw) -> str:
    """strip() + colapsar espacios internos (la normalización común, §5.1)."""
    return " ".join(str(raw).split()) if raw is not None else ""


def _modality_of(db: Session, fb):
    """La modalidad ELEGIDA del Formato B, leída por id (no por la relación,
    que puede venir vieja si `modality_id` cambió en esta misma sesión)."""
    from itcj2.apps.titulatec.models import Modality
    mid = getattr(fb, "modality_id", None)
    return db.get(Modality, mid) if mid else None


def _user_name(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) if user else ""


def already_reviewed_msg(fb) -> str:
    """Por qué un dictamen llega tarde: «Este Formato B ya fue dictaminado por
    X el …» si ya tiene dictamen; si nunca se envió, `NOT_IN_REVIEW_MSG`."""
    from sqlalchemy.orm import object_session

    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.core.models.user import User

    if getattr(fb, "status", None) not in ("approved", "rejected"):
        return NOT_IN_REVIEW_MSG
    msg = "Este Formato B ya fue dictaminado"
    sesion = object_session(fb)
    if sesion is not None and fb.reviewed_by_id:
        quien = _user_name(sesion.get(User, fb.reviewed_by_id))
        if quien:
            msg += f" por {quien}"
    if fb.reviewed_at:
        msg += f" el {dia_mes_hora(fb.reviewed_at)}"
    return msg + "."


class FormatBService:
    # Mismos mensajes como atributos de clase (patrón de `PhaseService.HANDOFF_MSG`).
    EDIT_LOCKED_MSG = EDIT_LOCKED_MSG
    ALREADY_SUBMITTED_MSG = ALREADY_SUBMITTED_MSG
    NEED_OBSERVATION_MSG = NEED_OBSERVATION_MSG

    # ------------------------------------------------------------------
    # Lectura y precarga
    # ------------------------------------------------------------------
    @staticmethod
    def validation_ctx(db: Session, fb) -> ValidationCtx:
        """Contexto de validación sacado del CATÁLOGO (§5.7): las modalidades
        activas y si la elegida pide proyecto (`requires_synodals`). Sin
        modalidad elegida, `requires_project=None` (el proyecto se exige)."""
        from itcj2.apps.titulatec.models import Modality

        ids = frozenset(
            int(i) for (i,) in db.query(Modality.id).filter(Modality.is_active.is_(True)).all())
        modalidad = _modality_of(db, fb)
        requiere = None if modalidad is None else bool(modalidad.requires_synodals)
        return ValidationCtx(today=db_now().date(), modality_ids=ids, requires_project=requiere)

    @staticmethod
    def get_or_create(db: Session, process):
        """Devuelve el FormatB del proceso; si no existe lo crea con precargas.

        Precarga (solo al crearlo, §5.1): la modalidad del proceso (alta manual
        o CSV), el celular del perfil si queda en 10 dígitos y la retícula del
        perfil como plan de estudios. La carrera ya NO se escribe aquí: es dato
        del registro y se copia del proceso al enviar.
        """
        from itcj2.apps.titulatec.models import FormatB
        from itcj2.core.models.student_profile import StudentProfile
        from itcj2.core.models.user import User

        fb = db.get(FormatB, process.id)
        if fb:
            return fb

        user = db.get(User, process.student_id)
        perfil = db.get(StudentProfile, process.student_id)
        celular = normalize_phone(perfil.phone) if perfil and perfil.phone else None
        if not (celular and celular.isascii() and celular.isdigit() and len(celular) == 10):
            celular = None
        plan = _clean(perfil.reticula).upper()[:40] if perfil and perfil.reticula else ""
        fb = FormatB(
            process_id=process.id,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
            middle_name=user.middle_name if user else None,
            control_number=(user.control_number if user else None),
            modality_id=process.modality_id,
            mobile_phone=celular,
            study_plan=plan or None,
            status="draft",
        )
        db.add(fb)
        db.commit()
        db.refresh(fb)
        return fb

    @staticmethod
    def _reload(db: Session, process_id: int):
        """El Formato B del proceso releído de la BD (`populate_existing`), o
        None. Va DESPUÉS del bloqueo del proceso: así la verificación de estado
        ve lo que dejó quien llegó antes, no lo que se cargó al abrir la página."""
        from itcj2.apps.titulatec.models import FormatB
        return (db.query(FormatB).filter_by(process_id=process_id)
                .populate_existing().first())

    @staticmethod
    def _lock(db: Session, process):
        """Bloquea la fila del proceso y relee el Formato B (o None).

        Mismo bloqueo que el motor (`PhaseService._lock_process_row`, `FOR NO
        KEY UPDATE`, que también relee `process`): serializa guardado, envío,
        dictamen y corrección del registro entre sí y contra el dictamen de
        fase. `process` tiene que ser un objeto de ESTA sesión.

        Patrón de todos los que lo toman: las verificaciones van PRIMERO sin
        bloqueo (lo común —datos inválidos, ya dictaminado, fuera de fase— falla
        sin tomar candado ni deshacer nada) y se REPITEN bajo el bloqueo sobre lo
        releído (lo que cambió otra petición mientras tanto). Desde `_lock` hasta
        el commit, cualquier excepción hace `db.rollback()` antes de re-lanzar:
        el candado nunca se queda tomado esperando a que el llamador cierre.
        """
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        PhaseService._lock_process_row(db, process)
        return FormatBService._reload(db, process.id)

    # ------------------------------------------------------------------
    # Alumno: guardar y enviar
    # ------------------------------------------------------------------
    @staticmethod
    def save_step(db: Session, fb, step: int, form: Mapping) -> None:
        """Valida el paso y, solo si es válido, guarda lo normalizado.

        - `submitted`/`approved` → `ValueError(EDIT_LOCKED_MSG)` (corrige P8).
        - Paso inválido → `FormatBValidationError` SIN escribir nada (ni los
          campos que sí eran válidos: el alumno ve todo lo que escribió).
        - `rejected` se CONSERVA hasta el reenvío (corrige P9): el alumno sigue
          viendo las observaciones mientras corrige.

        Validación SIN bloqueo; bloqueo + relectura + re-verificación solo para
        escribir, con `rollback` ante cualquier error ya bajo el bloqueo (ver `_lock`).
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService

        if fb.status in ("submitted", "approved"):
            raise ValueError(EDIT_LOCKED_MSG)
        valores, errores = validate_step(step, form, FormatBService.validation_ctx(db, fb))
        if errores:
            raise FormatBValidationError(errores, step)

        try:
            fb = FormatBService._lock(db, fb.process)
            if fb is None or fb.status in ("submitted", "approved"):
                raise ValueError(EDIT_LOCKED_MSG)
            campos = STEP_FIELDS.get(step, [])
            antes = AuditService.snapshot(fb, campos)
            for campo, valor in valores.items():
                setattr(fb, campo, valor)
            # Solo los NOMBRES de los campos que cambiaron: los valores (domicilio,
            # teléfonos) ya los guarda la red ORM como `data.*` y no se duplican aquí.
            cambiados, _ = AuditService.changes(antes, AuditService.snapshot(fb, campos))
            if cambiados:
                AuditService.record(
                    db, "format_b.step_saved",
                    entity_type="format_b", entity_id=fb.process_id,
                    process_id=fb.process_id, subject=fb.control_number,
                    payload={"step": step, "label": STEP_LABELS.get(step),
                             "changed_fields": sorted(cambiados)},
                )
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def submit(db: Session, fb, process) -> None:
        """Envía el Formato B a revisión: valida TODO y congela el registro.

        **Guarda propia, no solo en la ruta** (`assert_student_can_act`, fase
        del CATÁLOGO): sin ella el proceso entraba a la cola de Titulación desde
        la fase 1. Bajo el bloqueo del proceso y solo desde `draft`/`rejected`:
        un doble clic o dos pestañas dan `ALREADY_SUBMITTED_MSG` al segundo y la
        ronda sube una vez (RF1). Un borrador viejo con datos hoy inválidos da
        `FormatBValidationError` con el primer paso que falla (RF3).

        Congela (§6) nombre y nº de control del `User`, la carrera del proceso y
        el NOMBRE de la modalidad elegida; sin proyecto requerido (catálogo:
        `requires_synodals = false`) el proyecto se guarda NULL. Luego:
        `submitted`, `submitted_at` (llave FIFO, D3), ronda + 1, fase 3
        `in_review` y el evento `format_b_submitted` del timeline.
        """
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.core.models.user import User

        n = PhaseService.phase_number_for_code(db, "format_b")

        def _verificar(formato):
            """Fase, estado y validación total; devuelve el contexto validado."""
            PhaseService.assert_student_can_act(db, process, n)
            if formato.status not in ("draft", "rejected"):
                raise ValueError(ALREADY_SUBMITTED_MSG)
            contexto = FormatBService.validation_ctx(db, formato)
            validate_all({c: getattr(formato, c) for c in OBSERVABLE_FIELDS}, contexto)
            return contexto

        _verificar(fb)                                   # sin bloqueo (ver `_lock`)
        try:
            PhaseService._lock_process_row(db, process)
            fb = FormatBService._reload(db, process.id) or fb
            ctx = _verificar(fb)                         # sobre lo releído

            user = db.get(User, process.student_id)
            fb.first_name = user.first_name if user else None
            fb.last_name = user.last_name if user else None
            fb.middle_name = user.middle_name if user else None
            fb.control_number = user.control_number if user else None
            fb.program_id = process.program_id
            modalidad = _modality_of(db, fb)
            fb.titulation_type = modalidad.name if modalidad else None
            if ctx.requires_project is False:
                fb.project_name = None
            fb.status = "submitted"
            fb.submitted_at = db_now()
            fb.submission_count = (fb.submission_count or 0) + 1
            ronda = fb.submission_count

            phase = (db.query(ProcessPhase)
                     .filter_by(process_id=process.id, phase_number=n).first())
            if not phase:
                phase = ProcessPhase(process_id=process.id, phase_number=n)
                db.add(phase)
            phase.status = "in_review"
            PhaseService._log(db, process.id, process.student_id, "format_b_submitted", n,
                              {"round": ronda})
            AuditService.record(
                db, "format_b.submitted",
                entity_type="format_b", entity_id=fb.process_id,
                process_id=fb.process_id, subject=fb.control_number,
                payload={"phase_number": n, "round": ronda},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    # ------------------------------------------------------------------
    # Titulación: dictamen
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_in_review(db: Session, process, fb, n: int, *, not_in_review: str | None = None,
                          require_modality: bool = False) -> None:
        """«Sigue en revisión» + guarda del motor (+ modalidad), sin escribir.

        Común a aprobar, observar y corregir el registro, y se corre DOS veces
        (ver `_lock`): sin bloqueo sobre lo cargado y bajo el bloqueo sobre lo
        releído. Si otro dictaminó primero: «ya fue dictaminado por X el …»
        (RF2). La guarda del motor (`assert_can_transition`) va aquí, antes de
        escribir: proceso pausado o revocado y corte a T-soft fallan con el
        mensaje del motor sin dejar nada a medias (RF4). Aprobar exige además la
        modalidad elegida (un Formato B enviado antes de la columna no la tiene:
        se observa para que el alumno la elija).
        """
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if fb is None or fb.status != "submitted":
            raise ValueError(not_in_review or already_reviewed_msg(fb))
        PhaseService.assert_can_transition(db, process, n)
        if require_modality and not fb.modality_id:
            raise ValueError(NO_MODALITY_MSG)

    @staticmethod
    def _current(db: Session, process):
        """El Formato B del proceso tal como está en la sesión (sin releer)."""
        from itcj2.apps.titulatec.models import FormatB
        return db.get(FormatB, process.id)

    @staticmethod
    def approve(db: Session, process, reviewer_id: int) -> dict:
        """Aprueba el Formato B y, en la MISMA transacción, la fase 3.

        Exige la modalidad elegida (`NO_MODALITY_MSG`) y graba
        `process.modality_id = fb.modality_id` (D8) ANTES de aprobar la fase:
        `_next_applicable` lee los saltos del catálogo de esa modalidad
        (residencias → 4, EGEL → 6). El flush va antes del motor porque
        `approve_phase` relee el proceso con `populate_existing`, que pisaría un
        cambio sin flush. La puerta del motor se abre con la marca
        `PhaseService.FORMAT_B_VERDICT_KEY` (se quita al terminar, pase lo que
        pase). Cualquier error bajo el bloqueo: `rollback` y se re-lanza.
        Devuelve lo que devuelve `approve_phase`.
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, "format_b")
        FormatBService._assert_in_review(db, process, FormatBService._current(db, process), n,
                                         require_modality=True)
        try:
            fb = FormatBService._lock(db, process)
            FormatBService._assert_in_review(db, process, fb, n, require_modality=True)
            ahora = db_now()
            fb.status = "approved"
            fb.approved_by_id = reviewer_id
            fb.approved_at = ahora
            fb.reviewed_by_id = reviewer_id
            fb.reviewed_at = ahora
            fb.rejection_reason = None
            process.modality_id = fb.modality_id
            ronda = fb.submission_count or 0
            AuditService.record(
                db, "format_b.reviewed",
                entity_type="format_b", entity_id=fb.process_id,
                process_id=fb.process_id, subject=fb.control_number,
                payload={"status": "approved", "round": ronda},
                actor_id=reviewer_id,
            )
            db.flush()
            db.info[PhaseService.FORMAT_B_VERDICT_KEY] = (process.id, "approved")
            return PhaseService.approve_phase(db, process, n, reviewer_id,
                                              event_payload={"format_b": {"round": ronda}})
        except Exception:
            db.rollback()
            raise
        finally:
            db.info.pop(PhaseService.FORMAT_B_VERDICT_KEY, None)

    @staticmethod
    def reject(db: Session, process, reviewer_id: int, *, general_note: str | None,
               field_notes: Mapping[str, str]) -> None:
        """Regresa el Formato B al alumno con observaciones (D2).

        `field_notes` = `{campo: nota}`; un campo cuenta como observado si su
        nota no queda en blanco (la pestaña puede mandar las notas de todos los
        campos, y una nota en blanco nunca es error). Exige al menos una
        observación (general o de campo) y solo campos que llena el alumno
        (`EDITABLE_FIELDS`, incluida la modalidad; el proyecto no, si la
        modalidad elegida no lo pide): nombre, control y carrera se corrigen en
        el registro (§8.5). La puerta del motor se abre con la marca
        `PhaseService.FORMAT_B_VERDICT_KEY`; error bajo el bloqueo → `rollback`.

        `review_observations` guarda, por campo, la nota y el valor que tenía
        («Corregido ✓» y «antes → ahora»); sobrevive al reenvío y un nuevo
        rechazo la reemplaza. Rechaza la fase 3 por el motor con un motivo
        legible («… Campos a corregir: C.P., Calle.»), que es el del aviso y el
        correo; el evento lleva la ronda y los campos.
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        general = _clean(general_note) or None
        # Una nota en blanco = campo no observado, sea cual sea el campo.
        notas = {str(campo): texto for campo, nota in (field_notes or {}).items()
                 if (texto := _clean(nota))}

        n = PhaseService.phase_number_for_code(db, "format_b")
        actual = FormatBService._current(db, process)
        FormatBService._assert_in_review(db, process, actual, n)
        # Observables: lo que llena el alumno, menos el proyecto si la modalidad
        # elegida no lo pide (catálogo, §5.7): ese campo ni se le muestra.
        modalidad = _modality_of(db, actual)
        sin_proyecto = modalidad is not None and not modalidad.requires_synodals
        observables = [c for c in OBSERVABLE_FIELDS
                       if not (c == "project_name" and sin_proyecto)]
        ajenos = sorted(c for c in notas if c not in observables)
        if ajenos:
            raise ValueError(NOT_OBSERVABLE_MSG.format(
                campos=", ".join(FIELD_LABELS.get(c, c) for c in ajenos)))
        observados = [c for c in observables if c in notas]
        if not general and not observados:
            raise ValueError(NEED_OBSERVATION_MSG)
        if (general and len(general) > _MAX_NOTE) or any(
                len(notas[c]) > _MAX_NOTE for c in observados):
            raise ValueError(NOTE_TOO_LONG_MSG)

        # Motivo legible del aviso y del correo: la nota general tal cual y, si
        # hay campos, «Campos a corregir: …» con sus etiquetas de pantalla.
        motivo = general
        if observados:
            lista = ("Campos a corregir: "
                     + ", ".join(FIELD_LABELS.get(c, c) for c in observados) + ".")
            motivo = (f"{general if general[-1] in '.!?' else general + '.'} {lista}"
                      if general else lista)

        try:
            fb = FormatBService._lock(db, process)
            FormatBService._assert_in_review(db, process, fb, n)
            ahora = db_now()
            fb.status = "rejected"
            fb.reviewed_by_id = reviewer_id
            fb.reviewed_at = ahora
            fb.rejection_reason = general
            fb.review_observations = {
                "general": general,
                "fields": {c: {"note": notas[c], "value": _canon(getattr(fb, c, None))}
                           for c in observados},
                "reviewer_id": reviewer_id,
                "at": ahora.isoformat(),
            }
            ronda = fb.submission_count or 0
            AuditService.record(
                db, "format_b.reviewed",
                entity_type="format_b", entity_id=fb.process_id,
                process_id=fb.process_id, subject=fb.control_number,
                reason=general,
                payload={"status": "rejected", "round": ronda, "fields": observados},
                actor_id=reviewer_id,
            )
            db.flush()
            db.info[PhaseService.FORMAT_B_VERDICT_KEY] = (process.id, "rejected")
            PhaseService.reject_phase(
                db, process, n, reviewer_id, motivo,
                event_payload={"format_b": {"round": ronda, "fields": observados,
                                            "general": general,
                                            "notes": {c: notas[c] for c in observados}}})
        except Exception:
            db.rollback()
            raise
        finally:
            db.info.pop(PhaseService.FORMAT_B_VERDICT_KEY, None)

    @staticmethod
    def correct_registry(db: Session, process, reviewer_id: int, *, first_name: str,
                         last_name: str, middle_name: str | None, program_id: int,
                         reason: str) -> dict[str, tuple]:
        """Titulación corrige nombre y carrera del registro (D9, §8.5).

        Solo con el Formato B `submitted` (durante la revisión), bajo el mismo
        bloqueo y la misma guarda del motor que el dictamen. Nombre(s) y
        apellido paterno obligatorios, materno opcional, misma normalización;
        la carrera nueva debe existir y ser del MISMO nivel (`core_programs.
        level`) que la actual — cambiar de nivel cambiaría el perfil de
        titulación a media marcha —; motivo obligatorio.

        Actualiza el `User` (el nombre cambia en toda la plataforma: es la
        intención), el proceso y la copia congelada del Formato B, sin
        regresarlo. Bitácora `format_b.registry_corrected` con antes/después y
        motivo, evento `format_b_registry_corrected` y aviso al alumno.
        Devuelve `{campo: (antes, después)}` solo de lo que cambió.

        El nivel lo compara `TrackService.same_level` (único lector de
        `Program.level`, invariante 2). Verificaciones primero sin bloqueo y
        repetidas bajo el bloqueo; cualquier error bajo el bloqueo —incluso
        tras escribir— hace `rollback` (ver `_lock`).
        """
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.notify import notify_student
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.services.track_service import TrackService
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        nombre, paterno = _clean(first_name), _clean(last_name)
        materno = _clean(middle_name) or None
        motivo = _clean(reason)
        if not nombre or not paterno:
            raise ValueError(REGISTRY_NAME_MSG)
        if any(len(p) > _MAX_NAME for p in (nombre, paterno, materno or "")):
            raise ValueError(REGISTRY_NAME_LONG_MSG)
        if not motivo or len(motivo) > _MAX_REASON:
            raise ValueError(REGISTRY_REASON_MSG)
        try:
            nuevo_id = int(program_id)
        except (TypeError, ValueError):
            raise ValueError(REGISTRY_PROGRAM_MSG) from None

        n = PhaseService.phase_number_for_code(db, "format_b")

        def _plan(formato):
            """En revisión + guarda del motor + carrera + cambios: `(user, antes,
            después, before, after)`. Sin escribir nada."""
            FormatBService._assert_in_review(db, process, formato, n,
                                             not_in_review=REGISTRY_NOT_IN_REVIEW_MSG)
            if db.get(Program, nuevo_id) is None:
                raise ValueError(REGISTRY_PROGRAM_MSG)
            if process.program_id is None:
                raise ValueError(REGISTRY_NO_PROGRAM_MSG)
            if not TrackService.same_level(db, process.program_id, nuevo_id):
                raise ValueError(REGISTRY_LEVEL_MSG)
            user = (db.query(User).filter_by(id=process.student_id)
                    .populate_existing().first())
            antes = {"first_name": user.first_name, "last_name": user.last_name,
                     "middle_name": user.middle_name, "program_id": process.program_id}
            despues = {"first_name": nombre, "last_name": paterno,
                       "middle_name": materno, "program_id": nuevo_id}
            before, after = AuditService.changes(antes, despues)
            if not after:
                raise ValueError(REGISTRY_NO_CHANGES_MSG)
            return user, antes, despues, before, after

        _plan(FormatBService._current(db, process))      # sin bloqueo
        try:
            fb = FormatBService._lock(db, process)
            user, antes, despues, before, after = _plan(fb)   # sobre lo releído
            campos = [c for c in CORRECTABLE_FIELDS if c in after]

            user.first_name, user.last_name, user.middle_name = nombre, paterno, materno
            process.program_id = nuevo_id
            fb.first_name, fb.last_name, fb.middle_name = nombre, paterno, materno
            fb.program_id = nuevo_id

            AuditService.record(
                db, "format_b.registry_corrected",
                entity_type="format_b", entity_id=fb.process_id,
                process_id=fb.process_id, subject=fb.control_number,
                reason=motivo, before=before, after=after,
                payload={"fields": campos},
                actor_id=reviewer_id,
            )
            PhaseService._log(db, process.id, reviewer_id, "format_b_registry_corrected", n,
                              {"fields": campos, "reason": motivo})
            corregido = " y ".join(x for x, hay in (
                ("nombre", any(c != "program_id" for c in campos)),
                ("carrera", "program_id" in campos)) if hay)
            notify_student(db, process.student_id, type="REGISTRY_CORRECTED",
                           title="Titulación corrigió tu registro",
                           body=f"Titulación corrigió tu {corregido} en tu registro.",
                           process_id=process.id, phase_number=n)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {c: (antes[c], despues[c]) for c in campos}

    # ------------------------------------------------------------------
    # Presentación
    # ------------------------------------------------------------------
    @staticmethod
    def display_sections(db: Session, fb, process) -> list[dict]:
        """Los tres bloques de solo lectura con TODOS los campos (lo usan la
        revisión del alumno, la pestaña Titulación y el expediente).

        `[{"key", "label", "rows": [{"field", "label", "value", "editable",
        "registry", "correctable", "observation", "changed"}]}]`:

        - `value`: texto para pintar («—» si está vacío; sexo, carrera,
          modalidad y meses ya en palabras).
        - Registro (Ruling R3): con el Formato B en `draft` (o sin él) nombre,
          control y carrera salen EN VIVO del `User`/proceso; en cualquier otro
          estado, de la copia congelada.
        - `editable`: lo llena el alumno y se puede observar. El proyecto deja
          de serlo si la modalidad elegida no lo pide (se pinta «No aplica»).
        - `observation`: `{"note", "value_at_review"}` de `review_observations`
          (sobrevive al reenvío) o None; `changed`: el valor actual ya no es el
          que tenía al observarse.
        """
        from itcj2.apps.titulatec.models import Modality
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        estado = getattr(fb, "status", None) or "draft"
        en_vivo = fb is None or estado == "draft"
        if en_vivo:
            user = db.get(User, process.student_id)
            registro = {
                "first_name": getattr(user, "first_name", None),
                "last_name": getattr(user, "last_name", None),
                "middle_name": getattr(user, "middle_name", None),
                "control_number": getattr(user, "control_number", None),
                "program_id": process.program_id,
            }
        else:
            registro = {c: getattr(fb, c, None) for c in REGISTRY_FIELDS}

        modalidad = _modality_of(db, fb) if fb is not None else None
        sin_proyecto = modalidad is not None and not modalidad.requires_synodals
        crudo = getattr(fb, "review_observations", None)
        observaciones = crudo.get("fields") if isinstance(crudo, dict) else None
        if not isinstance(observaciones, dict):
            observaciones = {}

        def _texto(campo, canon):
            if canon is None:
                return _VACIO
            if campo == "gender":
                return GENDER_LABELS.get(canon, canon)
            if campo in ("program_id", "modality_id"):
                modelo = Program if campo == "program_id" else Modality
                try:
                    fila = db.get(modelo, int(canon))
                except (TypeError, ValueError):
                    fila = None
                return fila.name if fila else canon
            if campo in ("admission_date", "graduation_date"):
                try:
                    anio, mes = (int(x) for x in canon.split("-")[:2])
                    return f"{_MESES[mes]} de {anio}"
                except (ValueError, IndexError):
                    return canon
            return canon

        secciones = []
        for clave, etiqueta, campos in SECTIONS:
            filas = []
            for campo in campos:
                del_registro = campo in REGISTRY_FIELDS
                actual = registro[campo] if del_registro else getattr(fb, campo, None)
                canon = _canon(actual)
                valor = _texto(campo, canon)
                if campo == "modality_id" and not en_vivo and fb.titulation_type:
                    valor = fb.titulation_type      # el nombre congelado al enviar
                editable = campo in OBSERVABLE_FIELDS
                if campo == "project_name" and sin_proyecto:
                    valor, editable = _NO_APLICA, False
                obs = observaciones.get(campo) if editable else None
                filas.append({
                    "field": campo,
                    "label": FIELD_LABELS.get(campo, campo),
                    "value": valor,
                    "editable": editable,
                    "registry": del_registro,
                    "correctable": campo in CORRECTABLE_FIELDS,
                    "observation": ({"note": obs.get("note"),
                                     "value_at_review": _texto(campo, obs.get("value"))}
                                    if isinstance(obs, dict) else None),
                    "changed": isinstance(obs, dict) and canon != obs.get("value"),
                })
            secciones.append({"key": clave, "label": etiqueta, "rows": filas})
        return secciones

    @staticmethod
    def progress(fb) -> dict:
        """En qué paso va el Formato B y si ya se envió. Solo lee, a lo más, la
        modalidad elegida (por id, en la sesión del Formato B).

        La señal de "paso hecho" es **si el alumno dejó datos suyos en ese
        paso**: `save_step` solo escribe pasos válidos, y los obligatorios de
        cada paso quedan llenos. De ahí la resta de `PRELOADED_FIELDS` (lo que
        `get_or_create` pudo precargar). Con una modalidad que no pide proyecto
        (catálogo, §5.7) el paso 3 no tiene nada que llenar: cuenta como hecho
        en cuanto el paso 2 lo está.

        Devuelve ``{"status", "submitted", "step", "total_steps", "steps",
        "rejection_reason"}``; `step` es el primer paso sin datos propios (3 si
        todos los tienen).
        """
        from sqlalchemy.orm import object_session

        sin_proyecto = False
        sesion = object_session(fb) if fb is not None else None
        if sesion is not None and getattr(fb, "modality_id", None):
            modalidad = _modality_of(sesion, fb)
            sin_proyecto = modalidad is not None and not modalidad.requires_synodals
        steps, first_open, previo = [], None, False
        for n in sorted(STEP_FIELDS):
            fields = [f for f in STEP_FIELDS[n] if f not in PRELOADED_FIELDS]
            done = any(
                getattr(fb, f, None) not in (None, "") for f in fields
            ) if fb is not None else False
            if n == max(STEP_FIELDS) and sin_proyecto:
                done = done or previo
            if not done and first_open is None:
                first_open = n
            steps.append({"n": n, "label": STEP_LABELS.get(n, f"Paso {n}"), "done": done})
            previo = done

        status = getattr(fb, "status", None) or "draft"
        return {
            "status": status,
            "submitted": status in ("submitted", "approved"),
            "step": first_open or max(STEP_FIELDS),
            "total_steps": len(STEP_FIELDS),
            "steps": steps,
            "rejection_reason": getattr(fb, "rejection_reason", None),
        }

    @staticmethod
    def to_ctx(fb) -> dict:
        """Datos del FormatB para los templates (con meses formateados)."""
        return {
            "first_name": fb.first_name or "", "last_name": fb.last_name or "",
            "middle_name": fb.middle_name or "", "gender": fb.gender or "",
            "age": fb.age or "", "mobile_phone": fb.mobile_phone or "", "phone": fb.phone or "",
            "postal_code": fb.postal_code or "", "neighborhood": fb.neighborhood or "",
            "street": fb.street or "", "ext_number": fb.ext_number or "", "int_number": fb.int_number or "",
            "control_number": fb.control_number or "", "program_id": fb.program_id,
            "modality_id": fb.modality_id,
            "study_plan": fb.study_plan or "", "titulation_type": fb.titulation_type or "",
            "admission_date": _to_month_str(fb.admission_date),
            "graduation_date": _to_month_str(fb.graduation_date),
            "project_name": fb.project_name or "", "status": fb.status,
        }

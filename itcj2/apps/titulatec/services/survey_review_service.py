"""Servicio de la solicitud de liberación de GTV para la encuesta de egresados.

Gestión Tecnológica y Vinculación (GTV, `core_departments.code = 'tech_management'`)
revisa la encuesta que el egresado ya envió y decide si libera el requisito de
cotejo `graduate_survey` o deja observaciones. El egresado no mueve NINGÚN
estado desde el sistema: lo que GTV revisa lo atiende físicamente en su
ventanilla (Residencias, Prácticas, Servicio Social).

Máquina de estados completa (modelo `SurveyReview`; detalle en
`docs/superpowers/specs/2026-09-15-titulatec-liberacion-gtv-design.md` §4.2):

    (envío de la encuesta)  ─────────────────────────>  in_review
    in_review  ──Liberar  (approve)───────────────────>  approved
    in_review  ──Observar (reject, motivo)─────────────>  rejected
    rejected   ──Liberar  (approve)───────────────────>  approved   (sin acción del egresado)
    rejected   ──Observar (reject, motivo)─────────────>  rejected   (actualiza el texto)
    approved   ──Revocar  (revoke, motivo)─────────────>  rejected   (solo si `can_revoke`)
    (constancia previa, register_prior) ───────────────>  approved   (sin pasar por in_review; D9, §4.12)
    approved/prior ──Revocar (revoke, motivo)──────────>  (fila BORRADA: vuelve a `missing`,
                                                           el egresado contesta; Ruling R22)

Este service es el ÚNICO dueño de esas transiciones: nadie fuera de aquí debe
mutar `SurveyReview.status`. Efecto sobre el requisito `graduate_survey`
(§4.3): `approve` lo `fulfill`-ea, `revoke` lo `unfulfill`-ea; `reject` nunca lo
toca (ni desde `in_review` ni desde `rejected` hay cumplimiento que tocar).
`register_prior` (D9, §4.12) es la sexta transición: un camino aparte que NO
pasa por `in_review` -no hay encuesta real detrás-, solo la usa
`PriorClearanceService` (CLI `titulatec import-prior-clearances`, nunca una
ruta) y acredita el requisito con `external_ref=f"survey_prior:{id}"` (no
`survey_review:{id}`, para que el cumplimiento diga de dónde vino).

Gancho de folios (spec `2026-10-01-titulatec-biblioteca-caja-design.md`
§4.5, D7/D21/D22, y `2026-10-05-titulatec-folios-design.md` §3.3): `approve`
emite el folio `survey_release` vía `CertificateService.issue` -- salvo que
`review.origin == 'prior'`, porque una previa NUNCA pasa por `approve`: su
folio lo emite `register_prior` (mismo `source_ref=survey_review:{id}`), en el
semestre ANTERIOR al del registro (`previous_semester_key`; para una previa
diferida, el de su importación: kwarg `registered_at`, D5). `revoke` siempre
llama a `CertificateService.void` ANTES de borrar una previa (Ruling R22), así
que el folio queda anulado aunque la solicitud ya no exista; `void` es un
no-op (`None`) cuando no había nada que anular. Todo en la MISMA transacción:
`register_prior` sin commit propio (lo da el llamador) y el resto antes del
único `commit` de la transición.

Reglas fijas, iguales a `RequirementService`/`PhaseService`:

* Métodos `@staticmethod`, `db: Session` primero, UN solo `commit` al final de
  cada transición (nunca a medias).
* `ValueError` = regla de negocio, con el mensaje YA listo para el usuario
  (mensajes en español de ventanilla: la ruta los codifica después con
  `_hdr()`, así que los acentos están permitidos). `LookupError` = el
  `review_id` no existe (la ruta lo traduce a 404).
* Toda transición con actor (`approve`/`reject`/`revoke`) exige
  `process.status == 'active'`, y TODA la validación ocurre ANTES de mutar
  nada: un `ValueError` a medio camino nunca debe dejar `review` con atributos
  cambiados en memoria (la sesión de test no hace rollback solo porque el
  service lanzó una excepción).
* `approve`/`reject`/`revoke` bloquean la fila con `SELECT … FOR UPDATE`: dos
  personas de GTV pueden estar mirando la misma solicitud.
* `updated_at` NO tiene `onupdate` (ver el modelo): se fija a mano en cada
  transición, junto con `reviewed_at` cuando aplica.
* Imports de modelos y de otros services SIEMPRE locales, dentro de cada
  método: `survey_service.py` (Tarea 3) importa este módulo, y
  `AUTO_SOURCE_SURVEY` vive allá — un import a nivel de módulo en cualquiera
  de los dos lados cerraría un ciclo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, like_pattern, paginate_query
from itcj2.core.utils.timezone import db_now

# Estados reales de `SurveyReview.status`. El pseudo-estado "missing" de
# `summary_for_process` NO está aquí: no se guarda, se infiere de la ausencia
# de fila (igual que "ausencia de fila = pendiente" en `RequirementService`).
REVIEW_STATUSES = ("in_review", "approved", "rejected")

# Motivo de Observar/Revocar: obligatorio, recortado, 1..1000 caracteres.
REASON_MAX = 1000

# La cita de cotejo es la fase 2 del catálogo. Todo evento de esta solicitud
# se cuelga de ella para que salga en el acordeón del expediente — mismo valor
# que `RequirementService.PHASE_COTEJO` y `PhaseService.PHASE_COTEJO`.
PHASE_COTEJO = 2


def _no_revocada_en_revision():
    """Predicado de la bandeja de GTV: fuera la solicitud EN REVISIÓN de una
    inscripción revocada (`ProcessService.cancel`).

    Ahí sería trabajo que nadie puede hacer: toda acción de GTV exige el
    proceso `active` (`_active_process`) y respondería 400. Las pestañas de
    historial (liberadas / con observaciones) la conservan: el dictamen sí
    ocurrió. El llamador ya hizo JOIN a `TitulationProcess`.
    """
    from itcj2.apps.titulatec.models import SurveyReview, TitulationProcess
    return or_(SurveyReview.status != "in_review",
               TitulationProcess.status != "cancelled")


class SurveyReviewService:
    """Único dueño de las transiciones de `titulatec_survey_reviews`."""

    # ----------------------------------------------------------------- bitácora
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int | None,
             event_type: str, payload: dict | None = None) -> None:
        """Escribe un `ProcessEvent` en la fase 2. No commitea (gemelo de
        `RequirementService._log`)."""
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id, event_type=event_type,
            phase_number=PHASE_COTEJO, payload=payload,
        ))

    # ------------------------------------------------------------------ lectura
    @staticmethod
    def get_for_process(db: Session, process_id: int) -> SurveyReview | None:
        """La solicitud de ese proceso, o `None` si el egresado no ha enviado."""
        from itcj2.apps.titulatec.models import SurveyReview
        return db.query(SurveyReview).filter_by(process_id=process_id).first()

    @staticmethod
    def release_status(db: Session, process_id: int) -> str:
        """Estado de LIBERACIÓN de la encuesta para la guarda dura de citas.

        `'missing'` si el egresado no ha enviado nada (no existe fila);
        si no, el `status` real de la solicitud: `'in_review'` | `'approved'`
        | `'rejected'`. Fuente ÚNICA de esta comparación (spec
        2026-09-29-titulatec-cotejo-espacios-design.md §2, D1): nadie más
        debe comparar `SurveyReview.status == 'approved'` para decidir si se
        puede agendar. Revierte D2 del 2026-09-15 («basta con enviarla»).
        """
        review = SurveyReviewService.get_for_process(db, process_id)
        return review.status if review is not None else "missing"

    @staticmethod
    def release_status_map(db: Session, process_ids: list[int]) -> dict[int, str]:
        """`release_status` para varios procesos EN LOTE (una sola consulta).

        Para las filas de la cola: sin esto, pintar `survey_status` por fila
        dispararía una consulta por alumno. Los ids ausentes en la tabla (el
        egresado no ha enviado la encuesta) se completan como `'missing'`.
        """
        from itcj2.apps.titulatec.models import SurveyReview

        if not process_ids:
            return {}
        filas = (db.query(SurveyReview.process_id, SurveyReview.status)
                .filter(SurveyReview.process_id.in_(process_ids))
                .all())
        out = {pid: "missing" for pid in process_ids}
        out.update({pid: status for pid, status in filas})
        return out

    @staticmethod
    def is_released(db: Session, process_id: int) -> bool:
        """¿GTV ya liberó la encuesta de este proceso? Azúcar sobre
        `release_status`: la ÚNICA comparación con `'approved'` para esta
        regla debe vivir aquí o en `release_status`, nunca reimplementada."""
        return SurveyReviewService.release_status(db, process_id) == "approved"

    @staticmethod
    def prior_outcome(db: Session, process_id: int) -> str:
        """Clasifica, SOLO LECTURA, qué le tocaría a una constancia previa de
        encuesta sobre este proceso (D9, spec §4.12): `"apply"` (no hay
        solicitud todavía -> `register_prior` la crearía liberada),
        `"already"` (ya hay una `approved`: nada que aplicar) o `"conflict"`
        (hay una `in_review`/`rejected`: lo decide GTV desde su bandeja, NUNCA
        una importación).

        Distinta a propósito de `release_status`/`is_released` -esas son SOLO
        para `ClearanceGate` y la guarda de agendar (§4.4)-: esta es la ÚNICA
        lectura de `SurveyReview.status` permitida para la clasificación de
        constancias previas fuera de este service. `PriorClearanceService`
        llama aquí en vez de comparar `.status` por su cuenta (§5, invariante
        2: fuera de los dos services dueños y del gate, nadie compara esos
        estados).

        Ruling R30 #2 (re-revisión de la ola final): `revoke` (Ruling R22)
        BORRA la fila de una previa revocada -la solicitud vuelve a
        `missing`, para que el egresado conteste la encuesta normal-, así que
        sin fila NO basta para decir `"apply"`: si este proceso ya tiene un
        evento `survey_review_revoked` con `origin == "prior"` en su
        bitácora, es que GTV YA revocó una previa aquí, y reimportar el mismo
        archivo la re-aprobaría sola, pisando esa decisión. En ese caso
        `"conflict"` -como una solicitud real `in_review`/`rejected`-: lo
        vuelve a decidir GTV (una encuesta real nueva), nunca una
        importación."""
        review = SurveyReviewService.get_for_process(db, process_id)
        if review is None:
            if SurveyReviewService._revoked_prior_event(db, process_id):
                return "conflict"
            return "apply"
        if review.status == "approved":
            return "already"
        return "conflict"

    @staticmethod
    def prior_conflict_reason(db: Session, process_id: int) -> str | None:
        """Por qué una constancia previa de encuesta choca con este proceso.
        SOLO LECTURA. Devuelve:

        - `"revoked"`: GTV ya revocó una constancia previa en este proceso
          (`_revoked_prior_event`, Ruling R30 #2) y la solicitud se borró;
        - `"in_review"`: hay una solicitud real `in_review` o `rejected` que
          espera la decisión de GTV;
        - `None`: el proceso no está en conflicto (`prior_outcome` daría
          `"apply"` o `"already"`).

        La usa la importación de constancias previas
        (`PriorClearanceService.import_rows`, m39) para que el motivo de un
        conflicto diga la verdad: con `"revoked"` no es «ya envió la encuesta
        de este semestre; lo decide GTV», sino «GTV revocó su constancia
        previa; debe contestar la encuesta de egresados».

        Vive aquí, en el dueño, por el invariante 2 (§5): solo este service
        compara `SurveyReview.status` y lee el evento de revocación;
        `PriorClearanceService` le pregunta a este método en vez de hacerlo
        por su cuenta, igual que con `prior_outcome`. No cambia los tres
        valores de `prior_outcome` (`apply`/`already`/`conflict`), de los que
        dependen otros llamadores: es una clasificación más fina, aparte,
        solo para `conflict`."""
        review = SurveyReviewService.get_for_process(db, process_id)
        if review is None:
            if SurveyReviewService._revoked_prior_event(db, process_id):
                return "revoked"
            return None
        if review.status == "approved":
            return None
        return "in_review"

    @staticmethod
    def _revoked_prior_event(db: Session, process_id: int) -> bool:
        """¿Este proceso tiene un `survey_review_revoked` con `origin ==
        'prior'` en su bitácora? Único rastro que sobrevive al DELETE de
        `revoke` sobre una previa (Ruling R22) -lo usa `prior_outcome` para
        no confundir "GTV revocó esto" con "nunca pasó nada aquí". Un
        proceso puede acumular varios (una previa revocada, luego una
        encuesta real revocada): basta con que UNO traiga `origin='prior'`."""
        from itcj2.apps.titulatec.models import ProcessEvent

        eventos = (db.query(ProcessEvent.payload)
                  .filter_by(process_id=process_id, event_type="survey_review_revoked")
                  .all())
        return any((payload or {}).get("origin") == "prior" for (payload,) in eventos)

    @staticmethod
    def summary_for_process(db: Session, process_id: int) -> dict:
        """Foto plana de la solicitud para pintar en otras pantallas (checklist
        de Escolares, home del alumno). Nunca commitea ni siembra nada: es
        SOLO lectura — quien la llame decide después si sigue con su propia
        transacción o no.

        `status="missing"` es un PSEUDO-estado: no existe fila todavía (el
        egresado no ha enviado la encuesta). Llaves: `status`, `reason`,
        `reviewed_by`, `reviewed_at`, `review_id`, `response_id`, `origin`,
        `paper_to_collect`.

        NO trae la constancia ni su estado de impresión (Ruling R14, revisión
        final de `2026-10-02-titulatec-constancias-y-pendientes-design.md`
        §3.4): este resumen también lo usan el tablero del egresado, «Mi
        cita» y las páginas públicas de la encuesta, que no la pintan, así
        que no consulta `titulatec_certificates`. Las dos vistas de SE la
        cuelgan ellas como `certificate`, con UNA llamada a
        `CertificateService.print_status_map` para encuesta y no adeudo
        juntos (refs de `certificate_ref`).
        """
        from itcj2.core.models.user import User

        review = SurveyReviewService.get_for_process(db, process_id)
        if review is None:
            return {"status": "missing", "reason": None, "reviewed_by": None,
                    "reviewed_at": None, "review_id": None, "response_id": None,
                    "origin": None, "paper_to_collect": False}

        reviewer = db.get(User, review.reviewed_by_id) if review.reviewed_by_id else None
        return {
            "status": review.status,
            "reason": review.rejection_reason,
            "reviewed_by": reviewer.full_name if reviewer else None,
            "reviewed_at": (f"{review.reviewed_at:%d/%m/%Y}"
                           if review.reviewed_at else None),
            "review_id": review.id,
            "response_id": review.response_id,
            # 'submission' | 'prior' (D9, §4.12): la tarjeta de estatus pública
            # (`partials/survey_status.html`) y la bandeja de GTV lo usan para
            # distinguir una liberación real de una constancia previa.
            "origin": review.origin,
            # D3 (spec 2026-10-05-titulatec-import-encuesta-xlsx §4.4): el
            # egresado tiene que recoger su constancia en papel en GTV.
            "paper_to_collect": SurveyReviewService.paper_to_collect(review),
        }

    @staticmethod
    def paper_to_collect(review) -> bool:
        """«Constancia por recoger» (D3): la previa importada marcó papel
        pendiente (`paper_pending`) y GTV todavía no lo entrega
        (`paper_delivered_at` vacío). `paper_pending` se conserva tras la
        entrega como hecho histórico, así que nunca basta por sí solo."""
        return bool(review is not None and review.paper_pending
                    and review.paper_delivered_at is None)

    @staticmethod
    def certificate_ref(review_id: int | None) -> str | None:
        """El `source_ref` de las constancias `survey_release` de la solicitud
        `review_id` -el MISMO `survey_review:{id}` con que `approve()` las
        emite y `revoke()` las anula-, o `None` sin solicitud. Con él las dos
        vistas de SE piden la marca de impresión en su UNA llamada a
        `CertificateService.print_status_map` (Ruling R14); un ref que no
        existe no se pide."""
        return f"survey_review:{review_id}" if review_id is not None else None

    # ------------------------------------------------------------- transiciones
    @staticmethod
    def open_for_submission(db: Session, process, response, *,
                            commit: bool = False) -> SurveyReview:
        """Abre la solicitud al enviarse la encuesta. Una por proceso.

        La llama `SurveyService.submit` (Tarea 3) dentro de SU transacción
        (`commit=False`, igual que `RequirementService.fulfill`), y esa ruta
        ya comprueba "no existe solicitud" antes de llamar aquí (§5.3). El
        chequeo de abajo es la MISMA regla vista desde este lado: defensa en
        profundidad, no confianza ciega en el llamador. El `UNIQUE` de
        `process_id` es el cinturón; esto es el aviso legible en español en
        vez de un `IntegrityError` crudo.
        """
        from itcj2.apps.titulatec.models import SurveyReview

        if SurveyReviewService.get_for_process(db, process.id) is not None:
            raise ValueError(
                "Ya existe una solicitud de liberación para este proceso.")

        review = SurveyReview(
            process_id=process.id,
            response_id=response.id,
            status="in_review",
            submitted_at=db_now(),
            updated_at=db_now(),
        )
        db.add(review)
        db.flush()                      # necesitamos `review.id` para el evento

        SurveyReviewService._log(db, process.id, None, "survey_review_submitted",
                                 {"review_id": review.id, "response_id": response.id})
        if commit:
            db.commit()
        return review

    @staticmethod
    def register_prior(db: Session, process, *, issued_on: date,
                       note: str | None = None,
                       actor_id: int | None = None,
                       response_id: int | None = None,
                       paper_pending: bool = False,
                       registered_at: datetime | None = None) -> SurveyReview:
        """Constancia previa de la encuesta (D9, spec `2026-10-01-titulatec-
        biblioteca-caja-design.md` §4.12): el egresado YA traía, de ANTES de
        este sistema, su liberación de encuesta -otro semestre, en papel-.
        Crea DIRECTO una solicitud `approved`/`origin='prior'`, sin encuesta
        real detrás (`response_id=None`). La llama `PriorClearanceService`
        (`import_rows`/`apply_pending`), NUNCA una ruta: no hay UI que
        registre esto a mano (solo la CLI `titulatec
        import-prior-clearances`), así que el proceso siempre llega ya
        validado como "abierto" por el llamador, pero esta transición vuelve
        a comprobar TODO por su cuenta (defensa en profundidad, igual que el
        resto de la app).

        `issued_on` obligatoria, no futura y vigente (`>= hoy -
        PRIOR_VALIDITY_DAYS`, el MISMO límite que
        `LibraryClearanceService.PRIOR_VALIDITY_DAYS`: exactamente 365 días
        vale, 366 no). Acredita `graduate_survey` con
        `external_ref=f"survey_prior:{review.id}"` -DISTINTO del
        `survey_review:{id}` que usa `approve()`, para que el cumplimiento
        diga de dónde vino-. EMITE el folio `survey_release` (`source_ref=
        f"survey_review:{review.id}"`) con `semester=previous_semester_key(
        registered_at or ahora)`: la previa es del semestre ANTERIOR al del
        registro (spec folios 2026-10-05 §3.3). `actor_id=None`
        (importación/CLI) lo deja sin emisor. El gancho de `approve()` no
        interviene: una previa nunca pasa por ahí.

        `registered_at` (spec folios D5, «previa diferida»): la fecha de
        registro que decide el semestre del folio. `None` = «ahora» de este
        método (el registro directo). `PriorClearanceService._apply_survey` pasa
        `PriorClearance.created_at` -la IMPORTACIÓN-: una previa importada
        sin proceso y aplicada al inscribirse el egresado, a veces semestres
        después, debe seguir en el semestre anterior al de su importación, no
        al de su inscripción. SOLO elige el semestre: `reviewed_at`/
        `submitted_at`/`updated_at` siguen siendo «ahora».

        SIN commit: el llamador (`PriorClearanceService`) es dueño de la
        transacción completa del lote; aquí solo se hace `flush()` para que
        `review.id` exista antes del evento, del cumplimiento y del folio.

        `response_id`/`paper_pending` (spec `2026-10-05-titulatec-import-
        encuesta-xlsx-design.md` R7/D3): la importación del Excel de
        Microsoft Forms SÍ trae respuesta detrás -se liga aquí para que GTV
        vea «Ver respuestas»- y puede marcar la constancia en papel como
        «por recoger» (`paper_pending=True`; GTV la cierra con
        `mark_paper_delivered`). Sin ellos, la previa queda como siempre
        (`response_id=None`, `paper_pending=False`). Ambos viajan en el
        payload de `survey_review_prior`.
        """
        from itcj2.apps.titulatec.models import SurveyReview
        from itcj2.apps.titulatec.services.library_clearance_service import (
            PRIOR_VALIDITY_DAYS,
        )

        if process.status not in ("active", "on_hold"):
            raise ValueError(
                f"El proceso ya no admite cambios (estado: {process.status}).")
        if SurveyReviewService.get_for_process(db, process.id) is not None:
            raise ValueError(
                "Ya existe una solicitud de liberación para este proceso.")
        fecha = SurveyReviewService._check_prior_date(issued_on, PRIOR_VALIDITY_DAYS)
        nota = SurveyReviewService._clean_note(note)
        requirement = SurveyReviewService._graduate_survey_requirement(
            db, process.cohort_id)

        ahora = db_now()
        review = SurveyReview(
            process_id=process.id, response_id=response_id, status="approved",
            origin="prior", prior_issued_on=fecha, rejection_reason=None,
            paper_pending=bool(paper_pending),
            reviewed_by_id=actor_id, reviewed_at=ahora,
            submitted_at=ahora, updated_at=ahora,
        )
        db.add(review)
        db.flush()                      # necesitamos `review.id` para el evento

        # Folio de la previa (spec folios 2026-10-05 §3.3): semestre ANTERIOR
        # al del registro, misma transacción y sin commit (el llamador es
        # dueño). `revoke` lo anula antes de borrar la solicitud.
        from itcj2.apps.titulatec.services.certificate_service import (
            CertificateService, previous_semester_key,
        )
        CertificateService.issue(
            db, kind="survey_release", process=process,
            source_ref=f"survey_review:{review.id}", actor_id=actor_id,
            semester=previous_semester_key(registered_at or ahora),
        )

        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.fulfill(
            db, process.id, requirement.id, source="system", checked_by_id=actor_id,
            external_ref=f"survey_prior:{review.id}", commit=False,
        )
        SurveyReviewService._log(db, process.id, actor_id, "survey_review_prior",
                                 {"review_id": review.id, "issued_on": fecha.isoformat(),
                                  "note": nota, "response_id": response_id,
                                  "paper_pending": bool(paper_pending)})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_APPROVED",
                       title="Tu encuesta de egresados quedó liberada",
                       body=("Se registró tu constancia previa. Recoge tu constancia de "
                             "liberación en Gestión Tecnológica y Vinculación."
                             if paper_pending else
                             "Se registró tu constancia previa; llévala a tu cita de cotejo."),
                       process_id=process.id, phase_number=PHASE_COTEJO)

        # Correo (spec §4.11/§4.12): `origin='prior'` cambia el texto del
        # resultado "approved" a la variante de constancia previa; con
        # `paper_pending` (R10, spec 2026-10-05) añade la línea de recoger la
        # constancia en GTV.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.survey_result(db, process, result="approved", origin="prior",
                                  paper_pending=bool(paper_pending))

        return review

    @staticmethod
    def approve(db: Session, review_id: int, actor_id: int) -> SurveyReview:
        """Libera la solicitud (Liberar). Válido desde `in_review` o `rejected`.

        Acredita `graduate_survey` con `RequirementService.fulfill` y limpia
        cualquier observación vigente. Toda la validación ocurre ANTES de
        mutar `review`.
        """
        review = SurveyReviewService._locked_review(db, review_id)
        process = SurveyReviewService._active_process(db, review)
        if review.status not in ("in_review", "rejected"):
            raise ValueError("Esta solicitud ya fue liberada.")
        requirement = SurveyReviewService._graduate_survey_requirement(
            db, process.cohort_id)

        review.status = "approved"
        review.rejection_reason = None
        review.reviewed_by_id = actor_id
        review.reviewed_at = db_now()
        review.updated_at = db_now()

        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.fulfill(
            db, process.id, requirement.id, source="system", checked_by_id=actor_id,
            external_ref=f"survey_review:{review.id}", commit=False,
        )
        SurveyReviewService._log(db, process.id, actor_id, "survey_review_approved",
                                 {"review_id": review.id})

        # Folio de liberación de encuesta (spec §4.5, D7/D21/D22): NUNCA aquí
        # para origin='prior' -- una previa no pasa por `approve`; su folio
        # (semestre anterior) lo emite `register_prior`. Misma transacción,
        # antes del commit.
        if review.origin != "prior":
            from itcj2.apps.titulatec.services.certificate_service import CertificateService
            CertificateService.issue(
                db, kind="survey_release", process=process,
                source_ref=f"survey_review:{review.id}", actor_id=actor_id,
            )

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_APPROVED",
                       title="Tu encuesta de egresados fue liberada",
                       process_id=process.id, phase_number=PHASE_COTEJO)

        # Correo (spec 2026-09-28 §5, #4), en esta misma transacción.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.survey_result(db, process, result="approved")

        db.commit()
        return review

    @staticmethod
    def reject(db: Session, review_id: int, actor_id: int, reason: str) -> SurveyReview:
        """Deja observaciones (Observar). Válido desde `in_review` o `rejected`
        (en este segundo caso, ACTUALIZA el texto vigente). Nunca toca el
        cumplimiento: ni `in_review` ni `rejected` tienen nada que desacreditar.
        """
        review = SurveyReviewService._locked_review(db, review_id)
        process = SurveyReviewService._active_process(db, review)
        if review.status not in ("in_review", "rejected"):
            raise ValueError(
                "No se pueden dejar observaciones a una solicitud ya liberada; "
                "revócala primero.")
        motivo = SurveyReviewService._clean_reason(reason)

        review.status = "rejected"
        review.rejection_reason = motivo
        review.reviewed_by_id = actor_id
        review.reviewed_at = db_now()
        review.updated_at = db_now()

        SurveyReviewService._log(db, process.id, actor_id, "survey_review_rejected",
                                 {"reason": motivo})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_REJECTED",
                       title="Gestión Tecnológica y Vinculación dejó observaciones",
                       body=motivo, process_id=process.id, phase_number=PHASE_COTEJO)

        # Correo (spec 2026-09-28 §5, #5): las observaciones, ya recortadas.
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.survey_result(db, process, result="rejected", reason=motivo)

        db.commit()
        return review

    @staticmethod
    def revoke(db: Session, review_id: int, actor_id: int,
               reason: str) -> SurveyReview | None:
        """Revoca una liberación (Revocar). Solo desde `approved` y solo si
        `can_revoke` (la fase 2 de ese proceso todavía no está `approved`).
        Desacredita `graduate_survey` con `RequirementService.unfulfill` y deja
        `survey_review_revoked` (payload con `reason`, `origin` y `review_id`).

        Una encuesta REAL (`origin='submission'`) queda `rejected` con el
        motivo: su respuesta sigue guardada y GTV la puede volver a liberar.

        Una constancia previa (`origin='prior'`, D9) NO tiene encuesta detrás
        (`response_id` NULL): dejarla `rejected` atoraba al egresado para
        siempre -`SurveyService.submit` corta mientras exista CUALQUIER fila y
        la tarjeta pública le decía que ya no tenía que contestar-. Ruling R22
        (I4 de la revisión final): tras el evento, el `unfulfill`, el aviso y
        el correo (que le pide contestar la encuesta), la fila se BORRA y la
        solicitud vuelve a `missing`; el egresado contesta normalmente. Sigue
        siendo este service el único que la toca.

        Una previa IMPORTADA del Excel puede traer `response_id` (R8, spec
        `2026-10-05-titulatec-import-encuesta-xlsx-design.md`): se borra solo
        la SOLICITUD; la `SurveyResponse` NUNCA se borra -sigue en
        «Encuestas», ligada por `control_number`-. La FK va de la solicitud a
        la respuesta, así que el `db.delete(review)` no la arrastra.

        Devuelve la solicitud revocada, o `None` si era una previa (ya no
        existe).
        """
        review = SurveyReviewService._locked_review(db, review_id)
        process = SurveyReviewService._active_process(db, review)
        if review.status != "approved":
            raise ValueError("Solo se puede revocar una solicitud liberada.")
        if not SurveyReviewService.can_revoke(db, review):
            raise ValueError("La fase 2 ya fue liberada; ya no se puede revocar.")
        motivo = SurveyReviewService._clean_reason(reason)
        requirement = SurveyReviewService._graduate_survey_requirement(
            db, process.cohort_id)
        origen = review.origin or "submission"
        es_previa = origen == "prior"

        if not es_previa:
            review.status = "rejected"
            review.rejection_reason = motivo
            review.reviewed_by_id = actor_id
            review.reviewed_at = db_now()
            review.updated_at = db_now()

        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.unfulfill(db, process.id, requirement.id,
                                     actor_id=actor_id, commit=False)
        SurveyReviewService._log(db, process.id, actor_id, "survey_review_revoked",
                                 {"reason": motivo, "origin": origen,
                                  "review_id": review.id})

        # Anula el folio vigente de esta solicitud, si lo hay: la liberación
        # normal lo emite en `approve` y la previa en `register_prior` (desde
        # 2026-10-05). `void` regresa `None` sin problema si no hay ninguno
        # (una previa registrada antes de eso que el backfill aún no folia).
        # Misma transacción, antes del commit.
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        CertificateService.void(
            db, source_ref=f"survey_review:{review.id}", actor_id=actor_id,
            reason=motivo,
        )

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_REVOKED",
                       title="Se revocó la liberación de tu encuesta",
                       body=motivo, process_id=process.id, phase_number=PHASE_COTEJO)

        # Correo (spec 2026-09-28 §5, #6): el motivo de la revocación; con
        # `origin='prior'` le pide contestar la encuesta (Ruling R22).
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        StudentMail.survey_result(db, process, result="revoked", reason=motivo,
                                  origin=origen)

        if es_previa:
            db.delete(review)

        db.commit()
        return None if es_previa else review

    @staticmethod
    def mark_paper_delivered(db: Session, review_id: int, *,
                             actor_id: int) -> SurveyReview:
        """«Marcar constancia entregada» (D3, spec `2026-10-05-titulatec-
        import-encuesta-xlsx-design.md` §4.4): GTV entregó al egresado la
        constancia en papel de una previa importada con `paper_pending`.

        Llena `paper_delivered_at`/`paper_delivered_by_id` (`paper_pending`
        se CONSERVA como hecho histórico: «había papel por recoger y se
        entregó») y deja `survey_paper_delivered` (payload `{"review_id"}`).
        No cambia `status` ni el cumplimiento, ni manda correo (R10). No
        exige el proceso `active`: es la entrega física de un papel ya
        expedido, no un dictamen.

        `LookupError` si no existe; `ValueError` si no tiene papel pendiente
        o ya se entregó. Fila bloqueada `FOR UPDATE`; UN commit.
        """
        review = SurveyReviewService._locked_review(db, review_id)
        if not review.paper_pending:
            raise ValueError("Esta liberación no tiene constancia por recoger.")
        if review.paper_delivered_at is not None:
            raise ValueError("La constancia ya se había marcado como entregada.")

        ahora = db_now()
        review.paper_delivered_at = ahora
        review.paper_delivered_by_id = actor_id
        review.updated_at = ahora
        SurveyReviewService._log(db, review.process_id, actor_id,
                                 "survey_paper_delivered", {"review_id": review.id})
        db.commit()
        return review

    @staticmethod
    def attach_imported_response(db: Session, review, *, response_id: int,
                                 paper_pending: bool) -> bool:
        """Adjunta una respuesta importada del Excel de Forms a una previa que
        se liberó SIN respuesta (spec `2026-10-05-titulatec-import-encuesta-
        xlsx-design.md` R7; p. ej. la del CSV de `import-prior-clearances`).

        Solo actúa sobre `origin='prior'` con `response_id` vacío: una
        solicitud nacida de un envío real, o una previa que ya tiene su
        respuesta, NUNCA se pisa. `paper_pending` solo se ENCIENDE (`is
        True`); nunca apaga una marca previa. No cambia `status`, el
        cumplimiento ni la bitácora. Devuelve `True` si adjuntó. La llama
        `PriorClearanceService.attach_imported_response`; sin commit.
        """
        if review is None or response_id is None:
            return False
        if review.origin != "prior" or review.response_id is not None:
            return False
        review.response_id = response_id
        if paper_pending is True:
            review.paper_pending = True
        review.updated_at = db_now()
        db.flush()
        return True

    @staticmethod
    def can_revoke(db: Session, review) -> bool:
        """¿Puede GTV revocar esta liberación ahora mismo?

        Pregunta sobre la FASE, no sobre `review.status`: la fase 2 de su
        proceso no debe estar ya `approved`, y el proceso debe seguir activo.
        `revoke()` combina esto con "la solicitud SÍ está `approved`" como una
        guarda aparte, igual que `PhaseService.approve_phase` combina
        `assert_can_transition` con `_cotejo_gate_error`.
        """
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

        process = db.get(TitulationProcess, review.process_id)
        if process is None or process.status != "active":
            return False
        fase2 = (db.query(ProcessPhase)
                .filter_by(process_id=review.process_id, phase_number=PHASE_COTEJO)
                .first())
        return fase2 is None or fase2.status != "approved"

    # ------------------------------------------------------------------ listas
    @staticmethod
    def counts_by_status(db: Session, q: str | None = None) -> dict[str, int]:
        """Conteo por estado. Las 3 llaves de `REVIEW_STATUSES` siempre
        presentes (0 si no hay ninguna solicitud en ese estado).

        Con `q` aplica el MISMO criterio de búsqueda que `list_for_inbox`
        (`ILIKE` sobre nombre completo y número de control del alumno), para
        que las pestañas no anuncien un total global mientras la tabla ya
        está filtrada por texto."""
        from itcj2.apps.titulatec.models import SurveyReview, TitulationProcess
        from itcj2.core.models.user import User

        query = (db.query(SurveyReview.status, func.count(SurveyReview.id))
                 .join(TitulationProcess, TitulationProcess.id == SurveyReview.process_id)
                 .filter(_no_revocada_en_revision()))
        if q:
            patron = like_pattern(q.strip())
            query = (
                query
                .join(User, User.id == TitulationProcess.student_id)
                .filter(or_(User.full_name.ilike(patron, escape="\\"),
                            User.control_number.ilike(patron, escape="\\")))
            )
        filas = query.group_by(SurveyReview.status).all()
        out = {estado: 0 for estado in REVIEW_STATUSES}
        for estado, total in filas:
            if estado in out:
                out[estado] = total
        return out

    @staticmethod
    def list_for_inbox(db: Session, *, status: str, q: str | None = None,
                       page: int = 1, per_page: int = PAGE_SIZE) -> Page:
        """Página de la bandeja de GTV para una pestaña (`status`).

        `in_review` sale de más antigua a más nueva (a quien lleva más tiempo
        esperando se le atiende primero); `approved`/`rejected` salen por
        `reviewed_at` descendente (el último dictamen primero). `can_revoke`
        se calcula EN LOTE con una sola consulta extra a `ProcessPhase` (fase
        2 de los procesos de la página) — nunca una consulta por fila; el
        estado del PROCESO ya viene del `JOIN` principal, sin consulta aparte.

        `certificate` (Tarea 3 de `2026-10-02-titulatec-constancias-y-
        pendientes-design.md` §3.3, invariante 2): el dict de
        `CertificateService.print_status_map` para `survey_review:{id}` -una
        sola llamada por página, hasta 2 consultas MÁS- o `None`; la
        plantilla lo pinta con la macro `certificate_cell`.
        """
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import (
            Cohort, ProcessPhase, SurveyReview, TitulationProcess,
        )

        per_page = max(1, per_page)
        Reviewer = aliased(User)

        query = (
            db.query(SurveyReview, TitulationProcess, User, Program, Cohort, Reviewer)
            .join(TitulationProcess, TitulationProcess.id == SurveyReview.process_id)
            .join(User, User.id == TitulationProcess.student_id)
            .outerjoin(Program, Program.id == TitulationProcess.program_id)
            .join(Cohort, Cohort.id == TitulationProcess.cohort_id)
            .outerjoin(Reviewer, Reviewer.id == SurveyReview.reviewed_by_id)
            .filter(SurveyReview.status == status)
            .filter(_no_revocada_en_revision())
        )
        if q:
            patron = like_pattern(q.strip())
            query = query.filter(or_(User.full_name.ilike(patron, escape="\\"),
                                     User.control_number.ilike(patron, escape="\\")))

        if status == "in_review":
            query = query.order_by(SurveyReview.submitted_at.asc(), SurveyReview.id.asc())
        else:
            query = query.order_by(SurveyReview.reviewed_at.desc(), SurveyReview.id.desc())

        pagina = paginate_query(query, max(1, page), per_page)
        filas = pagina.items

        process_ids = [process.id for _, process, *_ in filas]
        fase2_status = dict(
            db.query(ProcessPhase.process_id, ProcessPhase.status)
            .filter(ProcessPhase.process_id.in_(process_ids),
                   ProcessPhase.phase_number == PHASE_COTEJO)
            .all()
        ) if process_ids else {}
        from itcj2.apps.titulatec.services.certificate_service import CertificateService
        refs = [f"survey_review:{review.id}" for review, *_ in filas]
        estado_impresion = CertificateService.print_status_map(db, refs)

        out = []
        for review, process, student, program, cohort, reviewer in filas:
            out.append({
                "id": review.id,
                "process_id": review.process_id,
                "response_id": review.response_id,
                "student": student.full_name,
                "control": student.control_number or "",
                "program": program.name if program else "",
                "cohort": cohort.name,
                "submitted": (f"{review.submitted_at:%d/%m/%Y}"
                             if review.submitted_at else ""),
                "current_phase": process.current_phase,
                "status": review.status,
                # 'submission' | 'prior' (D9, §4.12): la plantilla pinta la
                # píldora «Constancia previa». «Ver respuestas» sale siempre
                # que haya `response_id`: NULL en una previa del CSV, ligado
                # en una previa del Excel de Forms (spec 2026-10-05-titulatec-
                # import-encuesta-xlsx R7).
                "origin": review.origin,
                # «Constancia por recoger» (D3): papel pendiente y aún sin
                # entregar; con él la fila ofrece «Marcar constancia entregada».
                "paper_to_collect": SurveyReviewService.paper_to_collect(review),
                "reason": review.rejection_reason,
                "reviewed_by": reviewer.full_name if reviewer else None,
                "reviewed_at": (f"{review.reviewed_at:%d/%m/%Y}"
                               if review.reviewed_at else None),
                "can_revoke": (process.status == "active"
                              and fase2_status.get(process.id) != "approved"),
                "certificate": estado_impresion.get(f"survey_review:{review.id}"),
                # Inscripción revocada (`ProcessService.cancel`): el historial la
                # conserva, pero toda acción respondería 400 (`_active_process`).
                "revoked": process.status == "cancelled",
            })
        return Page(items=out, total=pagina.total, page=pagina.page,
                    per_page=pagina.per_page)

    # ------------------------------------------------------------------ guardas
    @staticmethod
    def _locked_review(db: Session, review_id: int) -> SurveyReview:
        """La solicitud, bloqueada con `FOR UPDATE` (dos personas de GTV sobre
        la misma fila). `LookupError` si no existe — la ruta lo traduce a 404."""
        from itcj2.apps.titulatec.models import SurveyReview

        review = (db.query(SurveyReview).filter_by(id=review_id)
                 .with_for_update().first())
        if review is None:
            raise LookupError(f"No existe la solicitud {review_id}.")
        return review

    @staticmethod
    def _active_process(db: Session, review) -> TitulationProcess:
        """El proceso de `review`, exigiendo que siga activo (§4.2: "Toda
        acción de GTV exige `process.status == 'active'`"). Mismo mensaje que
        `PhaseService._transition_error`."""
        from itcj2.apps.titulatec.models import TitulationProcess

        process = db.get(TitulationProcess, review.process_id)
        if process is None or process.status != "active":
            estado = process.status if process is not None else "desconocido"
            raise ValueError(f"El proceso ya no admite cambios (estado: {estado}).")
        return process

    @staticmethod
    def _graduate_survey_requirement(db: Session, cohort_id: int):
        """El `CotejoRequirement` con `auto_source='graduate_survey'` de esa
        convocatoria (sembrando los defaults si hace falta, vía
        `RequirementService.auto_requirement`). `ValueError` si esa
        convocatoria no lo tiene configurado: sin esto no hay qué
        `fulfill`/`unfulfill`."""
        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        from itcj2.apps.titulatec.services.survey_service import AUTO_SOURCE_SURVEY

        requirement = RequirementService.auto_requirement(db, cohort_id, AUTO_SOURCE_SURVEY)
        if requirement is None:
            raise ValueError(
                "Esta convocatoria no tiene configurado el requisito de la "
                "encuesta de egresados; pide a Servicios Escolares que lo revise.")
        return requirement

    @staticmethod
    def _clean_reason(reason: str | None) -> str:
        """Motivo listo para guardar: recortado, 1..`REASON_MAX` caracteres."""
        limpio = (reason or "").strip()
        if not limpio:
            raise ValueError("Escribe el motivo antes de continuar.")
        if len(limpio) > REASON_MAX:
            raise ValueError(f"El motivo no puede superar los {REASON_MAX} caracteres.")
        return limpio

    @staticmethod
    def _clean_note(note: str | None) -> str | None:
        """Nota opcional de una constancia previa: recortada; en blanco ->
        `None`; <= `REASON_MAX` caracteres. Gemela de
        `LibraryClearanceService._clean_note`."""
        limpio = (note or "").strip()
        if len(limpio) > REASON_MAX:
            raise ValueError(f"La nota no puede superar los {REASON_MAX} caracteres.")
        return limpio or None

    @staticmethod
    def _check_prior_date(issued_on, validity_days: int) -> date:
        """`issued_on` de una constancia previa (D9): obligatoria, no futura
        y vigente (`>= hoy - validity_days`). Gemela de
        `LibraryClearanceService._check_prior_date`."""
        if issued_on is None:
            raise ValueError("Escribe la fecha de la constancia previa.")
        if isinstance(issued_on, datetime):
            issued_on = issued_on.date()
        if not isinstance(issued_on, date):
            raise ValueError("La fecha de la constancia previa no es válida.")
        hoy = db_now().date()
        if issued_on > hoy:
            raise ValueError("La fecha de la constancia previa no puede ser futura.")
        if issued_on < hoy - timedelta(days=validity_days):
            raise ValueError("La constancia venció: tiene más de un año.")
        return issued_on

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

Este service es el ÚNICO dueño de esas transiciones: nadie fuera de aquí debe
mutar `SurveyReview.status`. Efecto sobre el requisito `graduate_survey`
(§4.3): `approve` lo `fulfill`-ea, `revoke` lo `unfulfill`-ea; `reject` nunca lo
toca (ni desde `in_review` ni desde `rejected` hay cumplimiento que tocar).

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

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

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
    def summary_for_process(db: Session, process_id: int) -> dict:
        """Foto plana de la solicitud para pintar en otras pantallas (checklist
        de Escolares, home del alumno). Nunca commitea ni siembra nada: es
        SOLO lectura — quien la llame decide después si sigue con su propia
        transacción o no.

        `status="missing"` es un PSEUDO-estado: no existe fila todavía (el
        egresado no ha enviado la encuesta).
        """
        from itcj2.core.models.user import User

        review = SurveyReviewService.get_for_process(db, process_id)
        if review is None:
            return {"status": "missing", "reason": None, "reviewed_by": None,
                    "reviewed_at": None, "review_id": None, "response_id": None}

        reviewer = db.get(User, review.reviewed_by_id) if review.reviewed_by_id else None
        return {
            "status": review.status,
            "reason": review.rejection_reason,
            "reviewed_by": reviewer.full_name if reviewer else None,
            "reviewed_at": (f"{review.reviewed_at:%d/%m/%Y}"
                           if review.reviewed_at else None),
            "review_id": review.id,
            "response_id": review.response_id,
        }

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

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_APPROVED",
                       title="Tu encuesta de egresados fue liberada",
                       process_id=process.id, phase_number=PHASE_COTEJO)

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

        db.commit()
        return review

    @staticmethod
    def revoke(db: Session, review_id: int, actor_id: int, reason: str) -> SurveyReview:
        """Revoca una liberación (Revocar). Solo desde `approved` y solo si
        `can_revoke` (la fase 2 de ese proceso todavía no está `approved`).
        Desacredita `graduate_survey` con `RequirementService.unfulfill`.
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

        review.status = "rejected"
        review.rejection_reason = motivo
        review.reviewed_by_id = actor_id
        review.reviewed_at = db_now()
        review.updated_at = db_now()

        from itcj2.apps.titulatec.services.requirement_service import RequirementService
        RequirementService.unfulfill(db, process.id, requirement.id,
                                     actor_id=actor_id, commit=False)
        SurveyReviewService._log(db, process.id, actor_id, "survey_review_revoked",
                                 {"reason": motivo})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="SURVEY_REVIEW_REVOKED",
                       title="Se revocó la liberación de tu encuesta",
                       body=motivo, process_id=process.id, phase_number=PHASE_COTEJO)

        db.commit()
        return review

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
    def counts_by_status(db: Session) -> dict[str, int]:
        """Conteo por estado. Las 3 llaves de `REVIEW_STATUSES` siempre
        presentes (0 si no hay ninguna solicitud en ese estado)."""
        from itcj2.apps.titulatec.models import SurveyReview

        filas = (db.query(SurveyReview.status, func.count(SurveyReview.id))
                .group_by(SurveyReview.status).all())
        out = {estado: 0 for estado in REVIEW_STATUSES}
        for estado, total in filas:
            if estado in out:
                out[estado] = total
        return out

    @staticmethod
    def list_for_inbox(db: Session, *, status: str, q: str | None = None,
                       page: int = 1, per_page: int = 50) -> tuple[list[dict], bool]:
        """Página de la bandeja de GTV para una pestaña (`status`).

        `in_review` sale de más antigua a más nueva (a quien lleva más tiempo
        esperando se le atiende primero); `approved`/`rejected` salen por
        `reviewed_at` descendente (el último dictamen primero). `can_revoke`
        se calcula EN LOTE con una sola consulta extra a `ProcessPhase` (fase
        2 de los procesos de la página) — nunca una consulta por fila; el
        estado del PROCESO ya viene del `JOIN` principal, sin consulta aparte.
        """
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import (
            Cohort, ProcessPhase, SurveyReview, TitulationProcess,
        )

        page = max(1, page)
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
        )
        if q:
            patron = f"%{q.strip()}%"
            query = query.filter(or_(User.full_name.ilike(patron),
                                     User.control_number.ilike(patron)))

        if status == "in_review":
            query = query.order_by(SurveyReview.submitted_at.asc(), SurveyReview.id.asc())
        else:
            query = query.order_by(SurveyReview.reviewed_at.desc(), SurveyReview.id.desc())

        filas = query.offset((page - 1) * per_page).limit(per_page + 1).all()
        has_more = len(filas) > per_page
        filas = filas[:per_page]

        process_ids = [process.id for _, process, *_ in filas]
        fase2_status = dict(
            db.query(ProcessPhase.process_id, ProcessPhase.status)
            .filter(ProcessPhase.process_id.in_(process_ids),
                   ProcessPhase.phase_number == PHASE_COTEJO)
            .all()
        ) if process_ids else {}

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
                "reason": review.rejection_reason,
                "reviewed_by": reviewer.full_name if reviewer else None,
                "reviewed_at": (f"{review.reviewed_at:%d/%m/%Y}"
                               if review.reviewed_at else None),
                "can_revoke": (process.status == "active"
                              and fase2_status.get(process.id) != "approved"),
            })
        return out, has_more

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

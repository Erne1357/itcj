"""Candado único de liberaciones para agendar el cotejo (`ClearanceGate`).

Spec `docs/superpowers/specs/2026-10-01-titulatec-biblioteca-caja-design.md`
§4.4, D6, D11, D17 y §5 (invariantes 2 y 8). Responde UNA pregunta —«¿a este
egresado le falta alguna liberación para agendar, o para que le agenden?»— y
es la ÚNICA fuente de esa respuesta (invariante 2): fuera de aquí y de los dos
services dueños (`SurveyReviewService`, `LibraryClearanceService`) ningún
módulo de la app compara `SurveyReview.status` ni `LibraryClearance.status`, ni
les pregunta a los dueños por su liberación. Lo fija la prueba estructural de
`tests/fastapi/titulatec/test_clearance_gate.py`.

Dos liberaciones, siempre en este orden (encuesta primero):

* **Encuesta de egresados**: la libera GTV (`SurveyReviewService`).
  Incondicional, toda convocatoria la exige.
* **No adeudo de biblioteca**: lo liberan Biblioteca y Caja
  (`LibraryClearanceService`). SOLO donde la convocatoria del proceso tiene el
  requisito de cotejo `library_clearance` ACTIVO y automático
  (`auto_source='library_clearance'`; invariante 8, `library_required`). Hasta
  que corre `titulatec activar-biblioteca-caja` —que marca así ese requisito
  en las convocatorias que ya existían (Ruling R19: `init-biblioteca-caja`
  ya no lo enciende)— nada cambia para nadie: desplegar el código no bloquea
  el agendado antes de que Biblioteca y Caja tengan ocupante. Una
  convocatoria nueva ya nace con él (`CotejoRequirementService.DEFAULTS`). Sin
  el requisito, `library` vale el pseudo-estado `not_required`.

Cuatro formas de preguntar, con la MISMA respuesta (las cruza la prueba):

* `status(db, pid)` / `status_map(db, pids)` →
  `{"survey": SURVEY_STATES, "library": LIBRARY_STATES}` (dominios CERRADOS,
  abajo). `missing` = sin fila (no ha enviado la encuesta / el proceso no
  tiene fila de no adeudo: alta durante el blue/green); en biblioteca cuenta
  como pendiente. `not_applicable` (Ruling R21) = el proceso ya pasó su
  cotejo -fase 2 `approved`- sin un no adeudo liberado: lo decide el dueño
  (`LibraryClearanceService.release_status_map`) y aquí cuenta igual que
  `not_required`, sin bloqueo. `status_map` va en consultas FIJAS (a lo más
  4), nunca una por proceso. Un proceso inexistente falla cerrado (`missing`
  en las dos).
* `blockers(status)` → lista ORDENADA (encuesta primero) del conjunto cerrado
  `BLOCKERS`; un estado desconocido también bloquea (falla cerrado).
* `is_clear(db, pid)` → sin bloqueos.
* `released_clause()` / `not_released_clause()` → lo mismo en SQL,
  correlacionado a `TitulationProcess`, para las consultas de la cola
  (incluida la fase 2 aprobada de `not_applicable`).

D17 (transición): el candado se pregunta al ABRIR un intento
(`AppointmentService.create`, y `reschedule` SOLO sobre un `no_show`, que abre
un intento nuevo -Ruling R11-). Una cita `scheduled`/`confirmed` que se mueve
de franja no lo vuelve a consultar, aunque una liberación vuelva a quedar
pendiente. Quien ya tenía el requisito `library_clearance` cumplido a mano
quedó `cleared/legacy`: en el backfill de `tt20261001a` y, para lo marcado a
mano DESPUÉS de la migración, en la promoción de `activar-biblioteca-caja`
(Ruling R20); quien ya pasó su cotejo sin él es `not_applicable`.

Consumidores (barrido de lectores, spec §4.4; ninguno guarda su propia
comparación): `AppointmentService.create` (`LibraryNotCleared`, tras las dos de
la encuesta), `AppointmentService.queue_candidates` y
`list_missing_clearance_processes` (las dos cláusulas),
`SelfBookingService.eligibility` (regla 3), `pages/appointments.py` (filas de
la cola y ficha de atender) y `PhaseService._requirement_label`. Las vistas del
egresado, el expediente y los correos (D11) lo consumen en sus propias tareas.

Reglas del módulo: `@staticmethod`, `db: Session` primero, imports de modelos y
services LOCALES (`appointment_service` y `self_booking_service` importan este
módulo, y los dueños importan media app). Solo lectura: nunca commitea ni
siembra requisitos (como `RequirementService.missing_required`).
"""
from __future__ import annotations

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

# Pseudo-estado de `library` cuando la convocatoria no exige el no adeudo.
LIBRARY_NOT_REQUIRED = "not_required"
# Pseudo-estado que produce el DUEÑO (`library_clearance_service.
# NOT_APPLICABLE`, mismo literal; lo cruza la prueba): ya pasó su cotejo sin
# un no adeudo liberado (Ruling R21). Aquí cuenta igual que `not_required`.
LIBRARY_NOT_APPLICABLE = "not_applicable"

# Dominios CERRADOS de `status`/`status_map` (los fija la prueba): todo valor
# que sale de aquí es uno de estos, y cada uno tiene respuesta en `blockers`.
SURVEY_STATES = ("missing", "in_review", "approved", "rejected")
LIBRARY_STATES = ("missing", "pending", "awaiting_payment", "cleared",
                  LIBRARY_NOT_REQUIRED, LIBRARY_NOT_APPLICABLE)

# El estado que LIBERA cada una. Son las únicas comparaciones contra
# 'approved'/'cleared' de esta regla en toda la app (invariante 2).
_SURVEY_RELEASED = "approved"
_LIBRARY_RELEASED = "cleared"
# Lo que NO bloquea en biblioteca: liberado, no exigido o que ya no aplica.
_LIBRARY_FREE = (_LIBRARY_RELEASED, LIBRARY_NOT_REQUIRED, LIBRARY_NOT_APPLICABLE)

# Códigos de bloqueo: conjunto CERRADO, en el orden en que se reportan. Cada
# consumidor traduce cada código a su mensaje (`SelfBookingService.
# _CLEARANCE_REASONS`, las excepciones de `AppointmentService.create`), así que
# nunca sale de aquí un código fuera de esta lista.
SURVEY_BLOCKERS = ("survey_missing", "survey_in_review", "survey_rejected")
LIBRARY_BLOCKERS = ("library_pending", "library_awaiting_payment")
BLOCKERS = SURVEY_BLOCKERS + LIBRARY_BLOCKERS

_SURVEY_BLOCKER = {"missing": "survey_missing", "in_review": "survey_in_review",
                   "rejected": "survey_rejected"}
# `missing` (sin fila) cuenta como pendiente: Biblioteca todavía no lo revisa.
_LIBRARY_BLOCKER = {"missing": "library_pending", "pending": "library_pending",
                    "awaiting_payment": "library_awaiting_payment"}


class ClearanceGate:
    """«¿Le falta alguna liberación para agendar?»: la única respuesta."""

    # ------------------------------------------------------- dónde aplica
    @staticmethod
    def library_required(db: Session, cohort_id: int | None) -> bool:
        """¿La convocatoria exige el no adeudo de biblioteca? Hay un requisito
        de cotejo ACTIVO con `auto_source='library_clearance'`. Nunca siembra:
        una convocatoria sin lista todavía no lo exige."""
        if cohort_id is None:
            return False
        return ClearanceGate.library_required_map(db, [cohort_id]).get(int(cohort_id), False)

    @staticmethod
    def library_required_map(db: Session, cohort_ids) -> dict[int, bool]:
        """`library_required` de varias convocatorias en UNA consulta (los
        `None` se ignoran; lista vacía → `{}` sin consultar)."""
        from itcj2.apps.titulatec.models import CotejoRequirement
        from itcj2.apps.titulatec.services.library_clearance_service import (
            AUTO_SOURCE_LIBRARY,
        )

        ids = {int(cid) for cid in cohort_ids if cid is not None}
        if not ids:
            return {}
        con_candado = {cid for (cid,) in
                       db.query(CotejoRequirement.cohort_id)
                       .filter(CotejoRequirement.cohort_id.in_(ids),
                               CotejoRequirement.auto_source == AUTO_SOURCE_LIBRARY,
                               CotejoRequirement.is_active.is_(True))
                       .distinct()}
        return {cid: cid in con_candado for cid in ids}

    # ------------------------------------------------------------- estado
    @staticmethod
    def status(db: Session, process_id: int) -> dict:
        """`{"survey": ..., "library": ...}` de un proceso. Es `status_map`
        con un solo id: una sola implementación, imposible que diverjan."""
        return ClearanceGate.status_map(db, [process_id])[int(process_id)]

    @staticmethod
    def status_map(db: Session, process_ids) -> dict[int, dict]:
        """`status` de varios procesos en consultas FIJAS: procesos,
        requisitos de sus convocatorias, encuestas y filas de no adeudo (esta
        última solo para los que la exigen). Nunca una consulta por proceso."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.library_clearance_service import (
            LibraryClearanceService,
        )
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        ids = list(dict.fromkeys(int(pid) for pid in process_ids))
        if not ids:
            return {}
        cohorte_de = dict(db.query(TitulationProcess.id, TitulationProcess.cohort_id)
                          .filter(TitulationProcess.id.in_(ids))
                          .all())
        exige = ClearanceGate.library_required_map(db, cohorte_de.values())
        # Un proceso que no existe no tiene convocatoria que lo exima: falla
        # cerrado y sale `missing`, igual que la encuesta.
        con_candado = [pid for pid in ids
                       if pid not in cohorte_de or exige.get(cohorte_de[pid], False)]
        encuesta = SurveyReviewService.release_status_map(db, ids)
        biblioteca = LibraryClearanceService.release_status_map(db, con_candado)
        return {pid: {"survey": encuesta.get(pid, "missing"),
                      "library": biblioteca.get(pid, LIBRARY_NOT_REQUIRED)}
                for pid in ids}

    @staticmethod
    def blockers(status: dict) -> list[str]:
        """Lo que le falta, en orden (encuesta primero), de `BLOCKERS`. Vacía
        = puede agendar. En biblioteca no bloquean `cleared`, `not_required`
        ni `not_applicable` (`_LIBRARY_FREE`). Un estado que no se reconoce
        bloquea (falla cerrado)."""
        bloqueos = []
        encuesta = status.get("survey")
        if encuesta != _SURVEY_RELEASED:
            bloqueos.append(_SURVEY_BLOCKER.get(encuesta, "survey_missing"))
        biblioteca = status.get("library")
        if biblioteca not in _LIBRARY_FREE:
            bloqueos.append(_LIBRARY_BLOCKER.get(biblioteca, "library_pending"))
        return bloqueos

    @staticmethod
    def is_clear(db: Session, process_id: int) -> bool:
        """¿Tiene todas sus liberaciones? (puede agendar o que le agenden)."""
        return not ClearanceGate.blockers(ClearanceGate.status(db, process_id))

    # ---------------------------------------------------------------- SQL
    @staticmethod
    def _exists():
        """Los cuatro `EXISTS` de las cláusulas, correlacionados a
        `TitulationProcess` (la consulta que los use debe tenerlo en su FROM):
        encuesta liberada, convocatoria con candado, no adeudo liberado y
        cotejo ya liberado (fase 2 `approved`: lo que hace `not_applicable`
        al no adeudo, Ruling R21)."""
        from itcj2.apps.titulatec.models import (
            CotejoRequirement, LibraryClearance, ProcessPhase, SurveyReview,
            TitulationProcess,
        )
        from itcj2.apps.titulatec.services.library_clearance_service import (
            AUTO_SOURCE_LIBRARY, PHASE_COTEJO,
        )

        encuesta = (exists()
                    .where(SurveyReview.process_id == TitulationProcess.id,
                           SurveyReview.status == _SURVEY_RELEASED)
                    .correlate(TitulationProcess))
        exige = (exists()
                 .where(CotejoRequirement.cohort_id == TitulationProcess.cohort_id,
                        CotejoRequirement.auto_source == AUTO_SOURCE_LIBRARY,
                        CotejoRequirement.is_active.is_(True))
                 .correlate(TitulationProcess))
        biblioteca = (exists()
                      .where(LibraryClearance.process_id == TitulationProcess.id,
                             LibraryClearance.status == _LIBRARY_RELEASED)
                      .correlate(TitulationProcess))
        cotejo = (exists()
                  .where(ProcessPhase.process_id == TitulationProcess.id,
                         ProcessPhase.phase_number == PHASE_COTEJO,
                         ProcessPhase.status == "approved")
                  .correlate(TitulationProcess))
        return encuesta, exige, biblioteca, cotejo

    @staticmethod
    def released_clause():
        """`is_clear` en SQL: encuesta liberada Y (la convocatoria no exige el
        no adeudo O ya está liberado O el cotejo ya se liberó -
        `not_applicable`-). Sin fila de no adeudo = no liberado."""
        encuesta, exige, biblioteca, cotejo = ClearanceGate._exists()
        return and_(encuesta, or_(~exige, biblioteca, cotejo))

    @staticmethod
    def not_released_clause():
        """La negación exacta de `released_clause` (le falta alguna)."""
        encuesta, exige, biblioteca, cotejo = ClearanceGate._exists()
        return or_(~encuesta, and_(exige, ~biblioteca, ~cotejo))

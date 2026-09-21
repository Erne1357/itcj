"""Consulta de solo lectura: egresados liberados al Departamento de Titulacion.

Tarea 4 del deslinde a T-soft (spec `2026-09-21-titulatec-dpto-titulacion`,
design doc S5). El criterio de "liberado" es UNA sola fila:
`ProcessPhase(phase_number, status='approved')` para la fase de Cita de
cotejo (`review_appointment`, hoy el numero 2 del catalogo). El numero se
resuelve contra `PhaseService.phase_number_for_code` -- nunca a mano -- para
no divergir si el catalogo se renumera.

Deliberadamente NO se consulta `ReviewAppointment`: es la fase, no la cita,
la que decide si el alumno esta liberado. Consultar la cita haria que los
reintentos (no_show, superseded, reagendados) duplicaran la fila o -peor-
dejaran pasar a alguien que aun debe el cotejo. El UNIQUE constraint de
`titulatec_process_phases` (`process_id`, `phase_number`) ya garantiza como
mucho una fila por proceso para esta fase, asi que "una sola vez por
proceso" sale gratis del modelo, sin necesidad de DISTINCT.

Servicio de SOLO LECTURA: ningun `commit`, ningun `add`. Lo consumira
`pages/handoff_admin.py` (Tarea 5): `list_released` pagina la bandeja,
`export_rows` arma el CSV sin paginar. El llamador resuelve el alcance por
carrera (`scope_service.officer_programs`) y lo pasa YA CALCULADO en
`allowed_program_ids` -- este service no sabe de permisos ni de scope_service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

_RELEASE_PHASE_CODE = "review_appointment"


@dataclass(frozen=True)
class ReleasedRow:
    process_id: int
    folio: str
    control_number: str
    full_name: str
    email: str | None
    program_name: str
    modality_name: str | None
    cohort_name: str
    released_at: datetime          # ProcessPhase(2).completed_at


class HandoffService:
    """Bandeja "Liberados" del Departamento de Titulacion (design doc S5)."""

    @staticmethod
    def _query(db: Session, *, allowed_program_ids: Literal["ALL"] | Iterable[int],
              cohort_id: int | None, program_id: int | None,
              modality_id: int | None, q: str | None):
        """Query filtrada (SIN order_by), o `None` si no hay nada que mirar.

        `None` cubre los dos "fail closed" del contrato: alcance vacio
        (`allowed_program_ids` != "ALL" y sin elementos) y fase de liberacion
        ausente del catalogo (`phase_number_for_code` -> None, catalogo sin
        sembrar). Vive separado de `list_released`/`export_rows` porque
        ambos comparten TODO menos el paginado final.
        """
        from itcj2.apps.titulatec.models import Cohort, Modality, ProcessPhase, TitulationProcess
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.core.models.program import Program
        from itcj2.core.models.user import User

        scoped = allowed_program_ids != "ALL"
        if scoped:
            allowed_program_ids = set(allowed_program_ids or ())
            if not allowed_program_ids:
                return None

        release_phase = PhaseService.phase_number_for_code(db, _RELEASE_PHASE_CODE)
        if release_phase is None:
            return None

        query = (
            db.query(TitulationProcess, User, Program, Cohort, Modality,
                     ProcessPhase.completed_at)
            .join(ProcessPhase, and_(
                ProcessPhase.process_id == TitulationProcess.id,
                ProcessPhase.phase_number == release_phase,
                ProcessPhase.status == "approved",
            ))
            .join(User, User.id == TitulationProcess.student_id)
            # INNER a proposito: un proceso sin carrera (`program_id IS NULL`)
            # es la cola de reparacion de `scope_service.can_see_unmapped`,
            # no un egresado liberado -- no sale ni con alcance "ALL".
            # `program_name` en `ReleasedRow` sale siempre poblado porque
            # esta fila nunca aparece sin `Program`.
            .join(Program, Program.id == TitulationProcess.program_id)
            .join(Cohort, Cohort.id == TitulationProcess.cohort_id)
            .outerjoin(Modality, Modality.id == TitulationProcess.modality_id)
        )
        if scoped:
            query = query.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if cohort_id:
            query = query.filter(TitulationProcess.cohort_id == cohort_id)
        if program_id:
            query = query.filter(TitulationProcess.program_id == program_id)
        if modality_id:
            query = query.filter(TitulationProcess.modality_id == modality_id)
        if q and q.strip():
            needle = f"%{q.strip()}%"
            # Misma forma que `AppointmentService.list_appointments`
            # (services/appointment_service.py:150-189): `core_users` no
            # tiene columna `full_name`, se arma primer+ultimo apellido con
            # coalesce para que un NULL no apague el concat entero.
            nombre = func.concat(func.coalesce(User.first_name, ""), " ",
                                 func.coalesce(User.last_name, ""))
            query = query.filter(or_(User.control_number.ilike(needle),
                                     nombre.ilike(needle)))
        return query

    @staticmethod
    def _row(proc, user, program, cohort, modality, completed_at) -> ReleasedRow:
        return ReleasedRow(
            process_id=proc.id,
            folio=proc.folio,
            control_number=user.control_number,
            full_name=f"{user.first_name} {user.last_name}",
            email=user.email,
            program_name=program.name,
            modality_name=modality.name if modality else None,
            cohort_name=cohort.name,
            released_at=completed_at,
        )

    @staticmethod
    def list_released(db: Session, *, allowed_program_ids, cohort_id=None, program_id=None,
                      modality_id=None, q=None, page=1, per_page=50
                      ) -> tuple[list[ReleasedRow], int]:
        """Filas de la bandeja + total (para paginar). Orden `released_at` desc,
        desempate por `process_id` desc."""
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

        query = HandoffService._query(
            db, allowed_program_ids=allowed_program_ids, cohort_id=cohort_id,
            program_id=program_id, modality_id=modality_id, q=q,
        )
        if query is None:
            return [], 0

        total = query.count()
        page = max(1, page or 1)
        per_page = max(1, per_page or 1)
        rows = (
            query.order_by(ProcessPhase.completed_at.desc(), TitulationProcess.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return [HandoffService._row(*r) for r in rows], total

    @staticmethod
    def export_rows(db: Session, *, allowed_program_ids, cohort_id=None, program_id=None,
                    modality_id=None, q=None) -> list[ReleasedRow]:
        """Las mismas filas de `list_released`, completas y sin paginar (CSV).
        Mismo orden que la bandeja."""
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

        query = HandoffService._query(
            db, allowed_program_ids=allowed_program_ids, cohort_id=cohort_id,
            program_id=program_id, modality_id=modality_id, q=q,
        )
        if query is None:
            return []

        rows = query.order_by(ProcessPhase.completed_at.desc(), TitulationProcess.id.desc()).all()
        return [HandoffService._row(*r) for r in rows]

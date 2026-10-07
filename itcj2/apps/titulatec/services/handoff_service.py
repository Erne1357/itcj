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

Correo de la fila (spec 2026-10-07 §7, D9): el PERSONAL, con la misma
resolucion que `StudentMail.contact_email` -- `core_student_profile.
contact_email` -> `contact_email` de la `EnrollmentRequest` mas reciente que
convirtio ESTE proceso -- y, como ultimo respaldo de la bandeja, el
institucional (`core_users.email`, casi siempre vacio en egresados). Vacio o
solo espacios cuenta como ausente. Viaja en la MISMA consulta (perfil por PK y
un agregado `max(id)` por proceso, unidos UNA vez): sin N+1 y sin subconsulta
por fila (`converted_process_id` no tiene indice).

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

from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, paginate_query

_RELEASE_PHASE_CODE = "review_appointment"


def _like_escape(s: str) -> str:
    """Escapa `\\`, `%` y `_` para que `q` viaje LITERAL dentro de un ILIKE.

    Sin esto un '%' o '_' tecleado en el buscador actua como comodin SQL: una
    busqueda que deberia ser "contiene exactamente este texto" trae de mas
    (o, con `_`, cualquier caracter en esa posicion). Se usa junto con
    `escape="\\"` en el `.ilike(...)` de `_query`.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _limpio(correo: str | None) -> str | None:
    """`None` si vacio o solo espacios; si no, sin espacios a los lados."""
    correo = (correo or "").strip()
    return correo or None


@dataclass(frozen=True)
class ReleasedRow:
    process_id: int
    folio: str
    control_number: str
    full_name: str
    email: str | None              # personal -> institucional (ver docstring del modulo)
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
        from sqlalchemy.orm import aliased

        from itcj2.apps.titulatec.models import (
            Cohort, EnrollmentRequest, Modality, ProcessPhase, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.core.models.program import Program
        from itcj2.core.models.student_profile import StudentProfile
        from itcj2.core.models.user import User

        scoped = allowed_program_ids != "ALL"
        if scoped:
            allowed_program_ids = set(allowed_program_ids or ())
            if not allowed_program_ids:
                return None

        release_phase = PhaseService.phase_number_for_code(db, _RELEASE_PHASE_CODE)
        if release_phase is None:
            return None

        # La solicitud MAS RECIENTE que convirtio cada proceso (mismo criterio
        # que `StudentMail.contact_email`: `order_by(id.desc()).first()`): UN
        # agregado sobre la tabla, unido por `process_id`, y la fila por PK.
        ultima = (
            db.query(EnrollmentRequest.converted_process_id.label("process_id"),
                     func.max(EnrollmentRequest.id).label("request_id"))
            .filter(EnrollmentRequest.converted_process_id.isnot(None))
            .group_by(EnrollmentRequest.converted_process_id)
            .subquery()
        )
        Solicitud = aliased(EnrollmentRequest)

        query = (
            db.query(TitulationProcess, User, Program, Cohort, Modality,
                     ProcessPhase.completed_at,
                     StudentProfile.contact_email, Solicitud.contact_email)
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
            # Las tres son 1:1 (PK, agregado por proceso, PK): no multiplican filas.
            .outerjoin(StudentProfile, StudentProfile.user_id == TitulationProcess.student_id)
            .outerjoin(ultima, ultima.c.process_id == TitulationProcess.id)
            .outerjoin(Solicitud, Solicitud.id == ultima.c.request_id)
            # Una inscripción REVOCADA (`ProcessService.cancel`) conserva su
            # fase 2 aprobada, pero no se entrega a T-soft ni sale en el CSV.
            .filter(TitulationProcess.status != "cancelled")
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
            needle = f"%{_like_escape(q.strip())}%"
            # Misma forma que `AppointmentService.list_appointments`
            # (services/appointment_service.py:150-189): `core_users` no
            # tiene columna `full_name`, se arma primer+ultimo apellido con
            # coalesce para que un NULL no apague el concat entero.
            nombre = func.concat(func.coalesce(User.first_name, ""), " ",
                                 func.coalesce(User.last_name, ""))
            query = query.filter(or_(User.control_number.ilike(needle, escape="\\"),
                                     nombre.ilike(needle, escape="\\")))
        return query

    @staticmethod
    def _row(proc, user, program, cohort, modality, completed_at,
             perfil_email=None, solicitud_email=None) -> ReleasedRow:
        # Personal (perfil -> solicitud, como `StudentMail.contact_email`) y,
        # sin ninguno, el institucional como ultimo respaldo de la bandeja.
        personal = _limpio(perfil_email) or _limpio(solicitud_email)
        return ReleasedRow(
            process_id=proc.id,
            folio=proc.folio,
            control_number=user.control_number,
            full_name=f"{user.first_name} {user.last_name}",
            email=personal or _limpio(user.email),
            program_name=program.name,
            modality_name=modality.name if modality else None,
            cohort_name=cohort.name,
            released_at=completed_at,
        )

    @staticmethod
    def list_released(db: Session, *, allowed_program_ids, cohort_id=None, program_id=None,
                      modality_id=None, q=None, page=1, per_page=PAGE_SIZE
                      ) -> Page:
        """Página de la bandeja (`Page` de `ReleasedRow`). Orden `released_at`
        desc, desempate por `process_id` desc."""
        from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

        query = HandoffService._query(
            db, allowed_program_ids=allowed_program_ids, cohort_id=cohort_id,
            program_id=program_id, modality_id=modality_id, q=q,
        )
        page = max(1, page or 1)
        per_page = max(1, per_page or 1)
        if query is None:
            return Page(items=[], total=0, page=1, per_page=per_page)

        pagina = paginate_query(
            query.order_by(ProcessPhase.completed_at.desc(), TitulationProcess.id.desc()),
            page, per_page)
        return Page(items=[HandoffService._row(*r) for r in pagina.items],
                    total=pagina.total, page=pagina.page, per_page=pagina.per_page)

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

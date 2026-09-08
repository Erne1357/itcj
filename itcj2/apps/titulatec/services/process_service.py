"""Selector canónico del proceso de titulación de un alumno.

Existe por un motivo concreto: hay DOS lados que tienen que hablar del mismo
proceso —el checklist que el alumno ve en su cita y el cumplimiento que le
escribe la encuesta de egresados— y si cada uno lo resuelve por su cuenta el
crédito aterriza en un proceso distinto del que el alumno está mirando.

**No uses `DocumentService.get_active_process` para esto.** Pese al nombre
(`document_service.py:89-98`) NO filtra por `status`: ordena por `created_at`
descendente y devuelve el más reciente aunque esté `completed` o `cancelled`.
"""
from __future__ import annotations

from sqlalchemy.orm import Session


class ProcessService:
    # Un proceso pausado entre convocatorias (`on_hold`, D5 del diseño) sigue
    # siendo el trámite vivo del alumno: conserva folio, `cohort_id` y rutas en
    # disco, y al reabrir la convocatoria vuelve a `active`. Excluirlo dejaría a
    # media generación sin poder acreditar nada durante el receso.
    CREDITABLE_STATUSES = ("active", "on_hold")

    @staticmethod
    def creditable_process(db: Session, user_id: int):
        """Proceso vivo del alumno, o `None`.

        Si tiene más de uno gana el de mayor `(created_at, id)`. El `id` no es
        decorativo: sin él el orden no es total y dos procesos creados en el
        mismo instante darían un ganador distinto según el plan de Postgres.
        """
        from itcj2.apps.titulatec.models import TitulationProcess
        return (
            db.query(TitulationProcess)
            .filter(TitulationProcess.student_id == user_id,
                    TitulationProcess.status.in_(ProcessService.CREDITABLE_STATUSES))
            .order_by(TitulationProcess.created_at.desc(), TitulationProcess.id.desc())
            .first()
        )

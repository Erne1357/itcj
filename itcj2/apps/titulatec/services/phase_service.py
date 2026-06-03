"""Motor de avance de fases del proceso de titulación."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session


class PhaseService:
    @staticmethod
    def get_phases(db: Session, process_id: int) -> list:
        from itcj2.apps.titulatec.models import ProcessPhase
        return (
            db.query(ProcessPhase)
            .filter_by(process_id=process_id)
            .order_by(ProcessPhase.phase_number)
            .all()
        )

    @staticmethod
    def _skips(process) -> set[int]:
        """Fases que la modalidad del proceso salta (JSON)."""
        mod = process.modality
        if mod and mod.skips_phases:
            try:
                return {int(x) for x in mod.skips_phases}
            except (TypeError, ValueError):
                return set()
        return set()

    @staticmethod
    def _next_applicable(process, after: int) -> int | None:
        """Siguiente fase aplicable (0..8) tras `after`, saltando las de la modalidad."""
        skips = PhaseService._skips(process)
        n = after + 1
        while n <= 8:
            if n not in skips:
                return n
            n += 1
        return None

    @staticmethod
    def _ensure_phase(db: Session, process_id: int, n: int):
        from itcj2.apps.titulatec.models import ProcessPhase
        ph = db.query(ProcessPhase).filter_by(process_id=process_id, phase_number=n).first()
        if not ph:
            ph = ProcessPhase(process_id=process_id, phase_number=n, status="pending")
            db.add(ph)
            db.flush()
        return ph

    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int, event_type: str, phase_number: int, payload: dict | None = None):
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id,
            event_type=event_type, phase_number=phase_number, payload=payload,
        ))

    @staticmethod
    def _phase_label(db: Session, phase_number: int) -> str:
        """'Fase NN · Nombre' para copys de notificación."""
        from itcj2.apps.titulatec.models import PhaseDefinition
        pdef = db.query(PhaseDefinition).filter_by(number=phase_number).first()
        return f"Fase {phase_number:02d}" + (f" · {pdef.name}" if pdef else "")

    @staticmethod
    def approve_phase(db: Session, process, phase_number: int, reviewer_id: int) -> dict:
        """Aprueba una fase, activa la siguiente aplicable (o completa el proceso)."""
        from itcj2.apps.titulatec.models import TitulationProcess

        ph = PhaseService._ensure_phase(db, process.id, phase_number)
        ph.status = "approved"
        ph.completed_at = datetime.utcnow()
        ph.reviewed_by_id = reviewer_id
        ph.rejection_reason = None

        # marca fases saltadas por modalidad como 'skipped'
        for s in PhaseService._skips(process):
            sph = PhaseService._ensure_phase(db, process.id, s)
            if sph.status not in ("approved",):
                sph.status = "skipped"

        nxt = PhaseService._next_applicable(process, phase_number)
        if nxt is None:
            process.status = "completed"
            process.completed_at = datetime.utcnow()
            PhaseService._log(db, process.id, reviewer_id, "process_completed", phase_number)
        else:
            nph = PhaseService._ensure_phase(db, process.id, nxt)
            if nph.status in ("pending", "rejected"):
                nph.status = "in_progress"
                nph.started_at = datetime.utcnow()
            process.current_phase = nxt

        PhaseService._log(db, process.id, reviewer_id, "phase_approved", phase_number)

        from itcj2.apps.titulatec.services.notify import notify_student
        if nxt is None:
            notify_student(db, process.student_id, type="PROCESS_COMPLETED",
                           title="¡Proceso de titulación completado!",
                           body="Felicidades, concluiste todas las fases de tu titulación.",
                           process_id=process.id)
        else:
            notify_student(db, process.student_id, type="PHASE_APPROVED",
                           title="Avanzaste de fase",
                           body=f"{PhaseService._phase_label(db, phase_number)} fue aprobada.",
                           process_id=process.id, phase_number=nxt)

        db.commit()
        return {"next_phase": nxt, "completed": nxt is None}

    @staticmethod
    def reject_phase(db: Session, process, phase_number: int, reviewer_id: int, reason: str) -> None:
        """Rechaza una fase: el alumno debe corregir; vuelve a in_progress."""
        ph = PhaseService._ensure_phase(db, process.id, phase_number)
        ph.status = "rejected"
        ph.reviewed_by_id = reviewer_id
        ph.rejection_reason = reason or None
        process.current_phase = phase_number
        PhaseService._log(db, process.id, reviewer_id, "phase_rejected", phase_number, {"reason": reason})

        from itcj2.apps.titulatec.services.notify import notify_student
        notify_student(db, process.student_id, type="PHASE_REJECTED",
                       title="Una fase necesita correcciones",
                       body=(reason or f"{PhaseService._phase_label(db, phase_number)} fue rechazada."),
                       process_id=process.id, phase_number=phase_number)

        db.commit()

"""Motor de avance de fases del proceso de titulación."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session
from itcj2.core.utils.timezone import db_now


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
    def phase_numbers(db: Session) -> list[int]:
        """Números de fase del catálogo, ordenados.

        Fuente ÚNICA del dominio de fases. Antes estaba escrito a mano en dos
        sitios (`while n <= 8` aquí y `range(9)` en `import_service`), que podían
        desincronizarse del catálogo sin que nada avisara.
        """
        from itcj2.apps.titulatec.models import PhaseDefinition
        return [
            int(n) for (n,) in
            db.query(PhaseDefinition.number).order_by(PhaseDefinition.number).all()
        ]

    @staticmethod
    def phase_range(db: Session) -> tuple[int, int]:
        """(primera, última) fase del catálogo. Sin catálogo no hay fase válida."""
        nums = PhaseService.phase_numbers(db)
        if not nums:
            raise ValueError("No hay fases dadas de alta en el sistema.")
        return nums[0], nums[-1]

    @staticmethod
    def _transition_error(process, phase_number, first: int, last: int) -> str | None:
        """Motivo por el que `phase_number` NO puede aprobarse/rechazarse, o None.

        Las tres reglas de `docs/flows/00_state_machine.md`: la fase existe, el
        proceso está vivo, y solo se actúa sobre la fase actual (ni saltar hacia
        adelante ni retroceder a una ya cerrada).

        Los mensajes van SIN acentos a propósito, no por descuido: viajan al toast
        por el header `X-Tt-Error`, y ahí Starlette es asimétrico — escribe la
        respuesta con `value.encode("latin-1")` (`datastructures.py:515`) pero su
        TestClient la lee con `value.decode()`, o sea UTF-8
        (`testclient.py:333`). Un solo byte >127 hace que el request entero
        reviente en cualquier test de ruta que caiga en este camino. En el
        navegador funcionaría; en la suite, no.
        """
        # `bool` es subclase de `int`: True colaría como fase 1.
        if isinstance(phase_number, bool) or not isinstance(phase_number, int):
            return f"Fase no reconocida: se espera un entero entre {first} y {last}."
        if not (first <= phase_number <= last):
            return (f"Fase {phase_number} fuera de rango: el proceso solo tiene "
                    f"las fases {first} a {last}.")
        if process.status != "active":
            return f"El proceso ya no admite cambios de fase (estado: {process.status})."
        if phase_number != process.current_phase:
            return (f"Solo puedes actuar sobre la fase en curso "
                    f"(fase {process.current_phase:02d}, no la {phase_number:02d}).")
        return None

    @staticmethod
    def can_transition(db: Session, process, phase_number: int) -> bool:
        """¿Se puede aprobar/rechazar esa fase? Para quien prefiere preguntar a atrapar.

        Lo usa el auto-avance del dictamen de documentos (`pages/documents.py`),
        que decide si llamar a `approve_phase` en vez de manejar la excepción.
        """
        try:
            first, last = PhaseService.phase_range(db)
        except ValueError:
            return False
        return PhaseService._transition_error(process, phase_number, first, last) is None

    @staticmethod
    def assert_can_transition(db: Session, process, phase_number) -> tuple[int, int]:
        """Guarda de aprobar/rechazar. Devuelve el rango del catálogo (para reusarlo).

        Vive en el service, no en la ruta, porque `approve_phase` tiene más de un
        llamador (botón manual y auto-avance de documentos) y el siguiente que se
        agregue la hereda gratis.
        """
        first, last = PhaseService.phase_range(db)
        err = PhaseService._transition_error(process, phase_number, first, last)
        if err:
            raise ValueError(err)
        return first, last

    @staticmethod
    def _next_applicable(process, after: int, last_phase: int) -> int | None:
        """Siguiente fase aplicable tras `after`, saltando las de la modalidad.

        `last_phase` es la última del catálogo (`phase_range`), no un literal.
        """
        skips = PhaseService._skips(process)
        n = after + 1
        while n <= last_phase:
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
        """Aprueba una fase, activa la siguiente aplicable (o completa el proceso).

        Solo la fase ACTUAL de un proceso ACTIVO. Lanza `ValueError` si no
        (la ruta lo traduce a 400 + `X-Tt-Error`).
        """
        _first, last = PhaseService.assert_can_transition(db, process, phase_number)

        ph = PhaseService._ensure_phase(db, process.id, phase_number)
        ph.status = "approved"
        ph.completed_at = db_now()
        ph.reviewed_by_id = reviewer_id
        ph.rejection_reason = None

        # marca fases saltadas por modalidad como 'skipped'
        for s in PhaseService._skips(process):
            sph = PhaseService._ensure_phase(db, process.id, s)
            if sph.status not in ("approved",):
                sph.status = "skipped"

        nxt = PhaseService._next_applicable(process, phase_number, last)
        if nxt is None:
            process.status = "completed"
            process.completed_at = db_now()
            PhaseService._log(db, process.id, reviewer_id, "process_completed", phase_number)
        else:
            nph = PhaseService._ensure_phase(db, process.id, nxt)
            if nph.status in ("pending", "rejected"):
                nph.status = "in_progress"
                nph.started_at = db_now()
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
        """Rechaza una fase: la deja en 'rejected' con motivo y fija current_phase en ella.

        El alumno corrige y reenvía; ese reenvío la pasa a 'in_review', no a 'in_progress'.
        Misma guarda que `approve_phase`: sin ella un `n` arbitrario se escribía tal cual
        en `process.current_phase`.
        """
        PhaseService.assert_can_transition(db, process, phase_number)

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

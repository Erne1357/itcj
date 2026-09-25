"""Selector canónico del proceso de titulación de un alumno, y su revocación.

Existe por un motivo concreto: hay DOS lados que tienen que hablar del mismo
proceso —el checklist que el alumno ve en su cita y el cumplimiento que le
escribe la encuesta de egresados— y si cada uno lo resuelve por su cuenta el
crédito aterriza en un proceso distinto del que el alumno está mirando.

**No uses `DocumentService.get_active_process` para esto.** Pese al nombre
(`document_service.py:89-98`) NO filtra por `status`: ordena por `created_at`
descendente y devuelve el más reciente aunque esté `completed` o `cancelled`.

REVOCAR (spec 2026-09-25-titulatec-elegibilidad-sii §3.6)
---------------------------------------------------------
`cancel` es el ÚNICO escritor de `status = 'cancelled'`. El motivo no tiene
columna: vive en el payload del `ProcessEvent` `process_cancelled`, y
`cancellation_info` lo lee de ahí (expediente, dashboard del alumno, bandeja
de Solicitudes). Qué hace cada lector de `TitulationProcess.status` con el
valor nuevo está en el reporte de la tarea y en `docs/flows/`.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Mismo tope que el motivo de devolución de la bandeja de Accesos.
_REASON_MAX = 2000

_MSG_NOT_FOUND = "Ese proceso ya no existe."
_MSG_NO_REASON = "Escribe el motivo de la revocación: es lo que el alumno lee."
_MSG_REASON_LONG = f"El motivo no puede pasar de {_REASON_MAX} caracteres."
_MSG_ALREADY = "Esta inscripción ya estaba revocada."
_MSG_COMPLETED = "El proceso ya concluyó: no se puede revocar."
_MSG_OK = "Inscripción revocada."


class ProcessService:
    # Un proceso pausado entre convocatorias (`on_hold`, D5 del diseño) sigue
    # siendo el trámite vivo del alumno: conserva folio, `cohort_id` y rutas en
    # disco, y al reabrir la convocatoria vuelve a `active`. Excluirlo dejaría a
    # media generación sin poder acreditar nada durante el receso.
    CREDITABLE_STATUSES = ("active", "on_hold")

    # Lo que se puede revocar: lo mismo que está vivo. `completed` no (el
    # trámite ya terminó) y `cancelled` tampoco (idempotencia, abajo).
    REVOCABLE_STATUSES = CREDITABLE_STATUSES

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

    @staticmethod
    def cancel(db: Session, process_id: int, *, reason: str | None,
               actor_id: int | None) -> tuple[bool, str]:
        """Revoca la inscripción. Dueña de la transacción. `(ok, mensaje)`.

        En UNA transacción, bajo `FOR UPDATE` del proceso (dos personas de
        Servicios Escolares sobre la misma fila): `status='cancelled'`, cancela
        la cita VIGENTE si todavía se puede cancelar (`scheduled`/`confirmed`:
        libera su franja, D12) y deja el evento `process_cancelled` con el
        motivo. Una vigente `in_progress`, `no_show` o `attended` se deja como
        está: la matriz de citas no las deja pasar a `cancelled` y las dos
        últimas ya consumieron su franja (D10).

        Idempotente: sobre un proceso ya `cancelled` no escribe nada, no avisa
        y devuelve `(False, …)` para que la bandeja lo diga. `completed` no se
        revoca.

        El aviso al alumno (correo personal + institucional) sale DESPUÉS del
        commit y es best-effort: un buzón caído no deshace la revocación. El
        aviso en la app va dentro de la transacción (es una fila más). No se le
        quita el rol `graduate`: sigue entrando para leer el motivo y puede
        inscribirse en otra convocatoria (D5 solo cuenta procesos vivos).
        """
        from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.appointment_service import AppointmentService
        from itcj2.apps.titulatec.services.notify import notify_student
        from itcj2.core.utils.timezone import db_now

        motivo = (reason or "").strip()
        if not motivo:
            return False, _MSG_NO_REASON
        if len(motivo) > _REASON_MAX:
            return False, _MSG_REASON_LONG

        proc = (db.query(TitulationProcess).filter_by(id=process_id)
                .with_for_update().first())
        if proc is None:
            return False, _MSG_NOT_FOUND
        # Refresca DESPUÉS del lock: la fila pudo cambiar mientras esperaba.
        db.refresh(proc)
        if proc.status == "cancelled":
            return False, _MSG_ALREADY
        if proc.status not in ProcessService.REVOCABLE_STATUSES:
            return False, _MSG_COMPLETED

        anterior = proc.status
        cita_cancelada = False
        appt = AppointmentService.get_for_process(db, proc.id)
        if appt is not None and "cancelled" in AppointmentService._TRANSICIONES.get(
                appt.status, set()):
            AppointmentService.cancel(db, appt, actor_id, motivo,
                                      commit=False, notify=False)
            cita_cancelada = True

        proc.status = "cancelled"
        proc.updated_at = db_now()
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=actor_id,
            event_type="process_cancelled", phase_number=proc.current_phase,
            payload={"reason": motivo, "previous_status": anterior,
                     "appointment_cancelled": cita_cancelada},
        ))
        notify_student(db, proc.student_id, type="PROCESS_CANCELLED",
                       title="Tu inscripción a titulación fue cancelada",
                       body="Entra a TitulaTec para ver el motivo.",
                       process_id=proc.id)
        db.commit()

        try:
            from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
            TitulaTecEmailHelper.send_process_cancelled(db, proc)
        except Exception:
            logger.exception("[titulatec] No se pudo avisar la revocación del proceso %s",
                             proc.id)
        return True, _MSG_OK

    @staticmethod
    def cancellation_info(db: Session, process) -> dict | None:
        """`{reason, at, actor_id}` de la revocación vigente, o `None`.

        Sale del ÚLTIMO `process_cancelled` del proceso, y solo si el proceso
        sigue `cancelled`: un evento viejo no puede pintar un aviso sobre un
        proceso que ya no lo está.
        """
        from itcj2.apps.titulatec.models import ProcessEvent

        if process is None or process.status != "cancelled":
            return None
        ev = (db.query(ProcessEvent)
              .filter_by(process_id=process.id, event_type="process_cancelled")
              .order_by(ProcessEvent.created_at.desc(), ProcessEvent.id.desc())
              .first())
        if ev is None:
            return {"reason": None, "at": None, "actor_id": None}
        return {"reason": (ev.payload or {}).get("reason"), "at": ev.created_at,
                "actor_id": ev.actor_id}

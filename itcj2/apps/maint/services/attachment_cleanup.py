"""
Servicio de limpieza automática de adjuntos de mantenimiento.

Ciclo de vida:
  1. set_auto_delete_on_resolved_tickets — asigna auto_delete_at a adjuntos
     de tickets terminados que aún no lo tienen.
  2. cleanup_expired_attachments — para cada adjunto con auto_delete_at vencido:
       - elimina el archivo físico
       - marca is_purged=True, purged_at=ahora, filepath=None
       - conserva la fila para trazabilidad (diferencia clave vs helpdesk)

Ambas funciones son idempotentes y se pueden llamar desde un cron o CLI.
"""
import os
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

# Estados que indican que el ticket ya no está en curso
TERMINAL_STATUSES = {"RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED"}


def set_auto_delete_on_resolved_tickets(db: Session) -> int:
    """
    Para tickets en estado terminal (RESOLVED_SUCCESS, RESOLVED_FAILED, CLOSED, CANCELED),
    asigna auto_delete_at en los adjuntos no purgados que aún no lo tienen.

    auto_delete_at = max(resolved_at, closed_at, canceled_at, updated_at) + MAINT_AUTO_DELETE_DAYS

    Retorna el número de adjuntos actualizados.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.attachment import MaintAttachment
    from itcj2.config import get_settings

    s = get_settings()
    delta = timedelta(days=s.MAINT_AUTO_DELETE_DAYS)

    tickets = (
        db.query(MaintTicket)
        .filter(MaintTicket.status.in_(list(TERMINAL_STATUSES)))
        .all()
    )

    updated = 0
    for ticket in tickets:
        # Fecha de referencia: la más reciente entre los timestamps de cierre
        dates = [
            d for d in [
                getattr(ticket, "resolved_at", None),
                getattr(ticket, "closed_at", None),
                getattr(ticket, "canceled_at", None),
                ticket.updated_at,
            ]
            if d is not None
        ]
        ref_date = max(dates) if dates else now_local()
        auto_delete_at = ref_date + delta

        attachments = (
            db.query(MaintAttachment)
            .filter_by(ticket_id=ticket.id, is_purged=False)
            .filter(MaintAttachment.auto_delete_at.is_(None))
            .all()
        )

        for att in attachments:
            att.auto_delete_at = auto_delete_at
            updated += 1

    if updated:
        db.commit()
        logger.info(f"auto_delete_at asignado a {updated} adjuntos de maint")

    return updated


def cleanup_expired_attachments(db: Session) -> int:
    """
    Purga archivos físicos vencidos.

    Para cada MaintAttachment con:
        is_purged=False AND auto_delete_at <= now()

    - Elimina el archivo del disco si existe.
    - Marca is_purged=True, purged_at=now(), filepath=None.
    - Conserva la fila (diferencia semántica vs helpdesk).

    Commit único al final. Retorna el número de adjuntos purgados.
    """
    from itcj2.apps.maint.models.attachment import MaintAttachment

    now = now_local()

    expired = (
        db.query(MaintAttachment)
        .filter(
            MaintAttachment.is_purged.is_(False),
            MaintAttachment.auto_delete_at.isnot(None),
            MaintAttachment.auto_delete_at <= now,
        )
        .all()
    )

    purged = 0
    for att in expired:
        original_path = att.filepath
        try:
            if original_path and os.path.exists(original_path):
                os.remove(original_path)
                logger.info(
                    f"Archivo purgado: {att.original_filename} "
                    f"(ticket {att.ticket_id}, attachment {att.id})"
                )
        except OSError as exc:
            logger.warning(
                f"No se pudo eliminar archivo {original_path} "
                f"(attachment {att.id}): {exc}"
            )

        att.is_purged = True
        att.purged_at = now
        att.filepath = None
        purged += 1

    if purged:
        db.commit()
        logger.info(f"Purga completada: {purged} adjuntos de maint marcados como purgados")

    return purged

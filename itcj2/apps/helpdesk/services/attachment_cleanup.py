"""
Servicio para limpieza automática de attachments
"""
from datetime import datetime
import os
import logging

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.attachment import Attachment

logger = logging.getLogger(__name__)


def cleanup_expired_attachments(db: Session) -> int:
    """
    Elimina attachments cuya fecha de auto-delete ya pasó.

    Ejecutar periódicamente con cron o celery.
    """
    now = datetime.now()

    expired = db.query(Attachment).filter(
        Attachment.auto_delete_at.isnot(None),
        Attachment.auto_delete_at <= now
    ).all()

    deleted_count = 0

    for attachment in expired:
        try:
            if os.path.exists(attachment.filepath):
                os.remove(attachment.filepath)
                logger.info(f"Archivo eliminado: {attachment.filepath}")

            db.delete(attachment)
            deleted_count += 1

        except Exception as e:
            logger.error(f"Error al eliminar attachment {attachment.id}: {e}")

    if deleted_count > 0:
        db.commit()
        logger.info(f"Limpieza completada: {deleted_count} attachments eliminados")

    return deleted_count


def set_auto_delete_on_resolved_tickets(db: Session) -> int:
    """
    Marca attachments para auto-delete cuando su ticket se resuelve.

    Ejecutar periódicamente con cron o celery.
    """
    from itcj2.apps.helpdesk.models.ticket import Ticket

    resolved_tickets = db.query(Ticket).filter(
        Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']),
        Ticket.resolved_at.isnot(None)
    ).all()

    updated_count = 0

    for ticket in resolved_tickets:
        for attachment in ticket.attachments:
            if attachment.auto_delete_at is None:
                attachment.set_auto_delete(days=7)
                updated_count += 1

    if updated_count > 0:
        db.commit()
        logger.info(f"Marcados {updated_count} attachments para auto-delete")

    return updated_count

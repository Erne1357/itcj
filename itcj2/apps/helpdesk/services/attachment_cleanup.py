"""
Servicio para limpieza automática de attachments
"""
from datetime import datetime, timedelta
import os
import logging

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.attachment import Attachment

logger = logging.getLogger(__name__)

AUTO_DELETE_DAYS = 7


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


def set_auto_delete_on_closed_tickets(db: Session) -> int:
    """
    Marca attachments para auto-delete en tickets con status CLOSED.

    Calcula: auto_delete_at = ticket.updated_at + AUTO_DELETE_DAYS días.
    Se usa updated_at porque una vez cerrado el ticket ya no recibe más
    cambios, por lo que updated_at equivale a la fecha de cierre.

    Ejecutar periódicamente con cron o celery.
    """
    from itcj2.apps.helpdesk.models.ticket import Ticket

    closed_tickets = db.query(Ticket).filter(
        Ticket.status == 'CLOSED',
    ).all()

    updated_count = 0

    for ticket in closed_tickets:
        delete_at = ticket.updated_at + timedelta(days=AUTO_DELETE_DAYS)
        for attachment in ticket.attachments:
            if attachment.auto_delete_at is None:
                attachment.auto_delete_at = delete_at
                updated_count += 1

    if updated_count > 0:
        db.commit()
        logger.info(f"Marcados {updated_count} attachments para auto-delete")

    return updated_count

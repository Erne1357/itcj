"""
Servicio para limpieza automática de attachments
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import Attachment
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


def cleanup_expired_attachments():
    """
    Elimina attachments cuya fecha de auto-delete ya pasó.
    
    Ejecutar periódicamente con cron o celery.
    """
    now = datetime.now()
    
    expired = Attachment.query.filter(
        Attachment.auto_delete_at.isnot(None),
        Attachment.auto_delete_at <= now
    ).all()
    
    deleted_count = 0
    
    for attachment in expired:
        try:
            # Eliminar archivo físico
            if os.path.exists(attachment.filepath):
                os.remove(attachment.filepath)
                logger.info(f"Archivo eliminado: {attachment.filepath}")
            
            # Eliminar registro de DB
            db.session.delete(attachment)
            deleted_count += 1
            
        except Exception as e:
            logger.error(f"Error al eliminar attachment {attachment.id}: {e}")
    
    if deleted_count > 0:
        db.session.commit()
        logger.info(f"Limpieza completada: {deleted_count} attachments eliminados")
    
    return deleted_count


def set_auto_delete_on_resolved_tickets():
    """
    Marca attachments para auto-delete cuando su ticket se resuelve.
    
    Ejecutar periódicamente con cron o celery.
    """
    from itcj.apps.helpdesk.models import Ticket
    
    # Buscar tickets resueltos cuyas fotos no tienen auto_delete_at
    resolved_tickets = Ticket.query.filter(
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
        db.session.commit()
        logger.info(f"Marcados {updated_count} attachments para auto-delete")
    
    return updated_count
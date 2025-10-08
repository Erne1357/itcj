from datetime import datetime
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import Ticket
import logging

logger = logging.getLogger(__name__)


def generate_ticket_number() -> str:
    """
    Genera un número único de ticket en formato: TK-YYYY-####
    
    Ejemplo: TK-2025-0001, TK-2025-0042
    
    Returns:
        String con el número de ticket generado
    
    Raises:
        Exception si no se puede generar después de varios intentos
    """
    current_year = datetime.utcnow().year
    
    # Obtener el último ticket del año actual
    last_ticket = (
        Ticket.query
        .filter(Ticket.ticket_number.like(f'TK-{current_year}-%'))
        .order_by(Ticket.ticket_number.desc())
        .first()
    )
    
    if last_ticket:
        # Extraer el número secuencial del último ticket
        try:
            last_number = int(last_ticket.ticket_number.split('-')[-1])
            new_number = last_number + 1
        except (ValueError, IndexError):
            logger.warning(f"No se pudo parsear el número del ticket {last_ticket.ticket_number}")
            new_number = 1
    else:
        # Primer ticket del año
        new_number = 1
    
    # Formatear el número con padding de 4 dígitos
    ticket_number = f"TK-{current_year}-{new_number:04d}"
    
    # Verificar que no exista (por seguridad)
    max_attempts = 10
    attempt = 0
    
    while Ticket.query.filter_by(ticket_number=ticket_number).first() and attempt < max_attempts:
        new_number += 1
        ticket_number = f"TK-{current_year}-{new_number:04d}"
        attempt += 1
    
    if attempt >= max_attempts:
        raise Exception("No se pudo generar un número de ticket único después de varios intentos")
    
    logger.info(f"Generado número de ticket: {ticket_number}")
    return ticket_number
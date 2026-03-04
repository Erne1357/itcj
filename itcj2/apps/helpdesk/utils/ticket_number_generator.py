from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.utils.timezone_utils import now_local
import logging

logger = logging.getLogger(__name__)


def generate_ticket_number(db: Session) -> str:
    """
    Genera un número único de ticket en formato: TK-YYYY-####
    """
    from itcj2.apps.helpdesk.models.ticket import Ticket

    current_year = now_local().year

    last_ticket = (
        db.query(Ticket)
        .filter(Ticket.ticket_number.like(f'TK-{current_year}-%'))
        .order_by(Ticket.ticket_number.desc())
        .first()
    )

    if last_ticket:
        try:
            last_number = int(last_ticket.ticket_number.split('-')[-1])
            new_number = last_number + 1
        except (ValueError, IndexError):
            logger.warning(f"No se pudo parsear el número del ticket {last_ticket.ticket_number}")
            new_number = 1
    else:
        new_number = 1

    ticket_number = f"TK-{current_year}-{new_number:04d}"

    max_attempts = 10
    attempt = 0

    while db.query(Ticket).filter_by(ticket_number=ticket_number).first() and attempt < max_attempts:
        new_number += 1
        ticket_number = f"TK-{current_year}-{new_number:04d}"
        attempt += 1

    if attempt >= max_attempts:
        raise Exception("No se pudo generar un número de ticket único después de varios intentos")

    logger.info(f"Generado número de ticket: {ticket_number}")
    return ticket_number

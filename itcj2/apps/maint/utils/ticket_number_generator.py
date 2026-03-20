import logging

from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)


def generate_ticket_number(db: Session) -> str:
    """
    Genera un número único de ticket en formato: MANT-YYYY-######
    Ejemplo: MANT-2026-000001
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    current_year = now_local().year
    prefix = f"MANT-{current_year}-"

    last_ticket = (
        db.query(MaintTicket)
        .filter(MaintTicket.ticket_number.like(f"{prefix}%"))
        .order_by(MaintTicket.ticket_number.desc())
        .first()
    )

    if last_ticket:
        try:
            last_number = int(last_ticket.ticket_number.split("-")[-1])
            new_number = last_number + 1
        except (ValueError, IndexError):
            logger.warning(f"No se pudo parsear el número del ticket {last_ticket.ticket_number}")
            new_number = 1
    else:
        new_number = 1

    ticket_number = f"{prefix}{new_number:06d}"

    max_attempts = 10
    attempt = 0
    while (
        db.query(MaintTicket).filter_by(ticket_number=ticket_number).first()
        and attempt < max_attempts
    ):
        new_number += 1
        ticket_number = f"{prefix}{new_number:06d}"
        attempt += 1

    if attempt >= max_attempts:
        raise Exception("No se pudo generar un número de ticket único después de varios intentos")

    logger.info(f"Generado número de ticket maint: {ticket_number}")
    return ticket_number

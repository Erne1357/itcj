"""
Servicio para gestión de equipos asociados a tickets
"""
import logging

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.ticket_inventory_item import TicketInventoryItem
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.ticket import Ticket

logger = logging.getLogger(__name__)


class TicketInventoryService:
    """Servicio para asociar equipos a tickets"""

    @staticmethod
    def add_items_to_ticket(db: Session, ticket_id: int, item_ids: list) -> list:
        """
        Asocia múltiples equipos a un ticket.

        Args:
            db: Sesión de SQLAlchemy
            ticket_id: ID del ticket
            item_ids: Lista de IDs de equipos

        Returns:
            Lista de TicketInventoryItem creados
        """
        try:
            ticket = db.get(Ticket, ticket_id)
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} no encontrado")

            added = []

            for item_id in item_ids:
                item = db.get(InventoryItem, item_id)
                if not item or not item.is_active:
                    logger.warning(f"Equipo {item_id} no encontrado o inactivo, omitiendo")
                    continue

                existing = db.query(TicketInventoryItem).filter_by(
                    ticket_id=ticket_id,
                    inventory_item_id=item_id
                ).first()

                if existing:
                    logger.warning(f"Equipo {item_id} ya asociado al ticket {ticket_id}, omitiendo")
                    continue

                ticket_item = TicketInventoryItem(
                    ticket_id=ticket_id,
                    inventory_item_id=item_id
                )

                db.add(ticket_item)
                added.append(ticket_item)

            db.commit()
            logger.info(f"{len(added)} equipos asociados al ticket {ticket_id}")

            return added

        except Exception as e:
            db.rollback()
            logger.error(f"Error al asociar equipos al ticket: {str(e)}")
            raise

    @staticmethod
    def remove_item_from_ticket(db: Session, ticket_id: int, item_id: int) -> bool:
        """
        Remueve un equipo de un ticket.
        """
        try:
            ticket_item = db.query(TicketInventoryItem).filter_by(
                ticket_id=ticket_id,
                inventory_item_id=item_id
            ).first()

            if not ticket_item:
                raise ValueError("Asociación no encontrada")

            db.delete(ticket_item)
            db.commit()

            logger.info(f"Equipo {item_id} removido del ticket {ticket_id}")
            return True

        except Exception as e:
            db.rollback()
            logger.error(f"Error al remover equipo del ticket: {str(e)}")
            raise

    @staticmethod
    def replace_ticket_items(db: Session, ticket_id: int, item_ids: list) -> list:
        """
        Reemplaza todos los equipos de un ticket.
        """
        try:
            db.query(TicketInventoryItem).filter_by(ticket_id=ticket_id).delete()
            added = TicketInventoryService.add_items_to_ticket(db, ticket_id, item_ids)
            return added

        except Exception as e:
            db.rollback()
            logger.error(f"Error al reemplazar equipos del ticket: {str(e)}")
            raise

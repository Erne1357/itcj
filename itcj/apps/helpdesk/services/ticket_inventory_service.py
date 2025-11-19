"""
Servicio para gestión de equipos asociados a tickets
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import TicketInventoryItem, InventoryItem, Ticket
import logging

logger = logging.getLogger(__name__)


class TicketInventoryService:
    """Servicio para asociar equipos a tickets"""
    
    @staticmethod
    def add_items_to_ticket(ticket_id: int, item_ids: list) -> list:
        """
        Asocia múltiples equipos a un ticket.
        
        Args:
            ticket_id: ID del ticket
            item_ids: Lista de IDs de equipos
        
        Returns:
            Lista de TicketInventoryItem creados
        """
        try:
            # Validar ticket
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} no encontrado")
            
            added = []
            
            for item_id in item_ids:
                # Validar que el equipo exista
                item = InventoryItem.query.get(item_id)
                if not item or not item.is_active:
                    logger.warning(f"Equipo {item_id} no encontrado o inactivo, omitiendo")
                    continue
                
                # Verificar que no esté ya asociado
                existing = TicketInventoryItem.query.filter_by(
                    ticket_id=ticket_id,
                    inventory_item_id=item_id
                ).first()
                
                if existing:
                    logger.warning(f"Equipo {item_id} ya asociado al ticket {ticket_id}, omitiendo")
                    continue
                
                # Crear asociación
                ticket_item = TicketInventoryItem(
                    ticket_id=ticket_id,
                    inventory_item_id=item_id
                )
                
                db.session.add(ticket_item)
                added.append(ticket_item)
            
            db.session.commit()
            logger.info(f"{len(added)} equipos asociados al ticket {ticket_id}")
            
            return added
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al asociar equipos al ticket: {str(e)}")
            raise
    
    @staticmethod
    def remove_item_from_ticket(ticket_id: int, item_id: int) -> bool:
        """
        Remueve un equipo de un ticket.
        
        Args:
            ticket_id: ID del ticket
            item_id: ID del equipo
        """
        try:
            ticket_item = TicketInventoryItem.query.filter_by(
                ticket_id=ticket_id,
                inventory_item_id=item_id
            ).first()
            
            if not ticket_item:
                raise ValueError("Asociación no encontrada")
            
            db.session.delete(ticket_item)
            db.session.commit()
            
            logger.info(f"Equipo {item_id} removido del ticket {ticket_id}")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al remover equipo del ticket: {str(e)}")
            raise
    
    @staticmethod
    def replace_ticket_items(ticket_id: int, item_ids: list) -> list:
        """
        Reemplaza todos los equipos de un ticket.
        
        Args:
            ticket_id: ID del ticket
            item_ids: Nueva lista de IDs de equipos
        """
        try:
            # Eliminar asociaciones existentes
            TicketInventoryItem.query.filter_by(ticket_id=ticket_id).delete()
            
            # Agregar nuevas
            added = TicketInventoryService.add_items_to_ticket(ticket_id, item_ids)
            
            return added
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al reemplazar equipos del ticket: {str(e)}")
            raise
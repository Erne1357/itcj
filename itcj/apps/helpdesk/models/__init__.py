"""
Modelos del sistema de Helpdesk
"""
from itcj.apps.helpdesk.models.ticket import Ticket
from itcj.apps.helpdesk.models.category import Category
from itcj.apps.helpdesk.models.assignment import Assignment
from itcj.apps.helpdesk.models.comment import Comment
from itcj.apps.helpdesk.models.attachment import Attachment
from itcj.apps.helpdesk.models.status_log import StatusLog
from itcj.apps.helpdesk.models.collaborator import TicketCollaborator
from itcj.apps.helpdesk.models.ticket_edit_log import TicketEditLog

# NUEVOS MODELOS DE INVENTARIO
from itcj.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj.apps.helpdesk.models.inventory_item import InventoryItem
from itcj.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj.apps.helpdesk.models.inventory_group import InventoryGroup  
from itcj.apps.helpdesk.models.inventory_group_capacity import InventoryGroupCapacity  
from itcj.apps.helpdesk.models.ticket_inventory_item import TicketInventoryItem  
__all__ = [
    'Ticket',
    'Category',
    'Assignment',
    'Comment',
    'Attachment',
    'StatusLog',
    'TicketEditLog',
    'InventoryCategory',
    'InventoryItem',
    'InventoryHistory',
    'InventoryGroup',
    'InventoryGroupCapacity',
    'TicketInventoryItem',
    'TicketCollaborator',
]
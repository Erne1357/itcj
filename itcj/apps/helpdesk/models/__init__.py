"""
Modelos del sistema de Helpdesk
"""
from itcj.apps.helpdesk.models.ticket import Ticket
from itcj.apps.helpdesk.models.category import Category
from itcj.apps.helpdesk.models.assignment import Assignment
from itcj.apps.helpdesk.models.comment import Comment
from itcj.apps.helpdesk.models.attachment import Attachment
from itcj.apps.helpdesk.models.status_log import StatusLog

# NUEVOS MODELOS DE INVENTARIO
from itcj.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj.apps.helpdesk.models.inventory_item import InventoryItem
from itcj.apps.helpdesk.models.inventory_history import InventoryHistory

__all__ = [
    'Ticket',
    'Category',
    'Assignment',
    'Comment',
    'Attachment',
    'StatusLog',
    # Inventario
    'InventoryCategory',
    'InventoryItem',
    'InventoryHistory',
]
from flask import Blueprint

# Crear blueprints de API
tickets_api_bp = Blueprint('tickets_api', __name__)
assignments_api_bp = Blueprint('assignments_api', __name__)
comments_api_bp = Blueprint('comments_api', __name__)
attachments_api_bp = Blueprint('attachments_api', __name__)
categories_api_bp = Blueprint('categories_api', __name__)
inventory_api_bp = Blueprint('inventory_api', __name__)
# Importar rutas para registrarlas
from . import tickets
from . import assignments
from . import comments
from . import attachments
from . import categories
import inventory

__all__ = [
    'tickets_api_bp',
    'assignments_api_bp',
    'comments_api_bp',
    'attachments_api_bp',
    'categories_api_bp',
    'inventory_api_bp',
]
# itcj/apps/helpdesk/routes/pages/__init__.py
from flask import Blueprint

user_pages_bp = Blueprint('user_pages', __name__)
secretary_pages_bp = Blueprint('secretary_pages', __name__)
technician_pages_bp = Blueprint('technician_pages', __name__)
department_pages_bp = Blueprint('department_pages', __name__)

# Importar rutas
from . import department_head, user, secretary, technician

__all__ = ['user_pages_bp', 'secretary_pages_bp', 'technician_pages_bp', 'department_pages_bp']
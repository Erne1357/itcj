from flask import Blueprint

# Blueprints de páginas
student_pages_bp = Blueprint('student_pages', __name__)
volunteer_pages_bp = Blueprint('volunteer_pages', __name__)
admin_pages_bp = Blueprint('admin_pages', __name__)

# Importar rutas para registrarlas
from . import student
from . import volunteer
from . import admin

__all__ = [
    'student_pages_bp',
    'volunteer_pages_bp',
    'admin_pages_bp',
]

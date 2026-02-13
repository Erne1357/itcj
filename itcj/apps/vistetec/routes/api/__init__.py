from flask import Blueprint

# Blueprints de API
catalog_api_bp = Blueprint('catalog_api', __name__)
appointments_api_bp = Blueprint('appointments_api', __name__)
garments_api_bp = Blueprint('garments_api', __name__)
donations_api_bp = Blueprint('donations_api', __name__)
pantry_api_bp = Blueprint('pantry_api', __name__)
slots_api_bp = Blueprint('slots_api', __name__)
reports_api_bp = Blueprint('reports_api', __name__)

# Importar rutas para registrarlas en los blueprints
from . import catalog
from . import garments
from . import time_slots
from . import appointments
from . import donations
from . import pantry
from . import reports

__all__ = [
    'catalog_api_bp',
    'appointments_api_bp',
    'garments_api_bp',
    'donations_api_bp',
    'pantry_api_bp',
    'slots_api_bp',
    'reports_api_bp',
]

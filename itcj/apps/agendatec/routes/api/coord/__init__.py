# routes/api/coord/__init__.py
"""
Módulo de API de coordinadores para AgendaTec.

Este paquete contiene los endpoints de coordinadores organizados por funcionalidad:
- dashboard: Dashboard y coordinadores compartidos
- day_config: Configuración de días y slots
- appointments: Gestión de citas
- drops: Gestión de bajas
- password: Cambio de contraseña

Uso:
    from itcj.apps.agendatec.routes.api.coord import api_coord_bp
"""
from flask import Blueprint

from .appointments import coord_appointments_bp
from .dashboard import coord_dashboard_bp
from .day_config import coord_day_config_bp
from .drops import coord_drops_bp
from .helpers import (
    DEFAULT_NIP,
    get_coord_program_ids,
    get_current_coordinator_id,
    get_current_user,
    split_or_delete_windows,
)
from .password import coord_password_bp

# Blueprint principal que agrupa todos los sub-blueprints
api_coord_bp = Blueprint("api_coord", __name__)

# Registrar sub-blueprints
api_coord_bp.register_blueprint(coord_dashboard_bp)
api_coord_bp.register_blueprint(coord_day_config_bp)
api_coord_bp.register_blueprint(coord_appointments_bp)
api_coord_bp.register_blueprint(coord_drops_bp)
api_coord_bp.register_blueprint(coord_password_bp)

# Exportar helpers para uso externo si es necesario
__all__ = [
    "api_coord_bp",
    # Helpers
    "get_current_user",
    "get_current_coordinator_id",
    "get_coord_program_ids",
    "split_or_delete_windows",
    "DEFAULT_NIP",
]

"""
Módulo de tickets API con sub-rutas organizadas.
"""
from flask import Blueprint

# Blueprint principal de tickets
from itcj.apps.helpdesk.routes.api import tickets_api_bp
# Importar y registrar sub-módulos
from .base import tickets_base_bp
from .collaborators import tickets_collaborators_bp
from .comments import tickets_comments_bp
from .equipment import tickets_equipment_bp

# Registrar sub-blueprints
tickets_api_bp.register_blueprint(tickets_base_bp)
tickets_api_bp.register_blueprint(tickets_collaborators_bp)
tickets_api_bp.register_blueprint(tickets_comments_bp)
tickets_api_bp.register_blueprint(tickets_equipment_bp)

__all__ = ['tickets_api_bp']
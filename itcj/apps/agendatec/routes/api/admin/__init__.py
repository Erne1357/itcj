# routes/api/admin/__init__.py
"""
Módulo de API de administración para AgendaTec.

Este paquete contiene los endpoints de administración organizados por funcionalidad:
- stats: Estadísticas del dashboard
- requests: Gestión de solicitudes
- users: Gestión de coordinadores y estudiantes
- reports: Generación de reportes
- surveys: Envío de encuestas

Uso:
    from itcj.apps.agendatec.routes.api.admin import api_admin_bp
"""
from flask import Blueprint

from .helpers import (
    add_query_params,
    find_recipients,
    get_dialect_name,
    paginate,
    parse_dt,
    range_from_query,
    student_email_from_user,
    student_identifier,
)
from .reports import admin_reports_bp
from .requests import admin_requests_bp
from .stats import admin_stats_bp
from .surveys import admin_surveys_bp
from .users import admin_users_bp

# Blueprint principal que agrupa todos los sub-blueprints
api_admin_bp = Blueprint("api_admin", __name__)

# Registrar sub-blueprints
api_admin_bp.register_blueprint(admin_stats_bp)
api_admin_bp.register_blueprint(admin_requests_bp)
api_admin_bp.register_blueprint(admin_users_bp)
api_admin_bp.register_blueprint(admin_reports_bp)
api_admin_bp.register_blueprint(admin_surveys_bp)

# Exportar helpers para uso externo si es necesario
__all__ = [
    "api_admin_bp",
    # Helpers
    "parse_dt",
    "range_from_query",
    "paginate",
    "add_query_params",
    "student_email_from_user",
    "student_identifier",
    "find_recipients",
    "get_dialect_name",
]

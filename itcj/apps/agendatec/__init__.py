# itcj/apps/agendatec/__init__.py
from flask import Blueprint, redirect, url_for, g, current_app, request
from itcj.core.utils.decorators import login_required, guard_blueprint
from itcj.core.services.authz_service import get_user_permissions_for_app, user_roles_in_app
from itcj.apps.agendatec.utils.utils import get_role_agenda, get_permissions_agenda
import logging

# Blueprints de AgendaTec
agendatec_api_bp = Blueprint('agendatec_api', __name__)
agendatec_pages_bp = Blueprint('agendatec_pages', __name__, template_folder='templates', static_folder='static')

# Proteger TODO agendatec con el nuevo sistema
guard_blueprint(agendatec_api_bp, "agendatec")
guard_blueprint(agendatec_pages_bp, "agendatec")

# Registrar APIs
from .routes.api.programs_academic import api_programs_bp
from .routes.api.availability import api_avail_bp
from .routes.api.requests import api_req_bp
from .routes.api.slots import api_slots_bp
from .routes.api.coord import api_coord_bp
from .routes.api.social import api_social_bp
from .routes.api.admin import api_admin_bp
from .routes.api.notifications import api_notifications_bp
from .routes.api.periods import api_periods_bp

agendatec_api_bp.register_blueprint(api_programs_bp, url_prefix="/programs")
agendatec_api_bp.register_blueprint(api_avail_bp, url_prefix="/availability")
agendatec_api_bp.register_blueprint(api_req_bp, url_prefix="/requests")
agendatec_api_bp.register_blueprint(api_slots_bp, url_prefix="/slots")
agendatec_api_bp.register_blueprint(api_coord_bp, url_prefix="/coord")
agendatec_api_bp.register_blueprint(api_social_bp, url_prefix="/social")
agendatec_api_bp.register_blueprint(api_admin_bp, url_prefix="/admin")
agendatec_api_bp.register_blueprint(api_notifications_bp, url_prefix="/notifications")
agendatec_api_bp.register_blueprint(api_periods_bp, url_prefix="/periods")

# Registrar páginas
from .routes.pages.student import student_pages_bp
from .routes.pages.coord import coord_pages_bp
from .routes.pages.social import social_pages_bp
from .routes.pages.admin import admin_pages_bp
from .routes.pages.admin_surveys import admin_surveys_pages

agendatec_pages_bp.register_blueprint(student_pages_bp, url_prefix="/student")
agendatec_pages_bp.register_blueprint(coord_pages_bp, url_prefix="/coord")
agendatec_pages_bp.register_blueprint(social_pages_bp, url_prefix="/social")
agendatec_pages_bp.register_blueprint(admin_pages_bp, url_prefix="/admin")
agendatec_pages_bp.register_blueprint(admin_surveys_pages, url_prefix="/surveys")

# Error handlers específicos para AgendaTec
def register_agendatec_error_handlers():
    """Registra error handlers específicos para AgendaTec usando su propio template"""
    from flask import request, jsonify, render_template
    from werkzeug.exceptions import HTTPException
    
    def wants_json():
        return request.path.startswith("/api/")
    
    def render_agendatec_error_page(status_code, message):
        # Marcar que estamos en un error handler para evitar loops en context processor
        request.is_error_handler = True
        return render_template("agendatec/errors/error_page.html",
                             code=status_code,
                             message=message), status_code
    
    @agendatec_pages_bp.errorhandler(HTTPException)
    def handle_agendatec_http_exception(e: HTTPException):
        code = e.code or 500
        message = e.description or f"Error {code}"
        
        if wants_json():
            payload = {"error": getattr(e, "name", "error"), "status": code}
            if getattr(e, "description", None):
                payload["detail"] = e.description
            return jsonify(payload), code
        
        return render_agendatec_error_page(code, message)
    
    @agendatec_pages_bp.errorhandler(Exception)
    def handle_agendatec_unexpected(e: Exception):
        current_app.logger.exception("Unhandled exception in AgendaTec")
        if wants_json():
            return jsonify({"error": "internal_error", "status": 500}), 500
        return render_agendatec_error_page(500, "Error interno del servidor")
    
    # Error handlers específicos
    @agendatec_pages_bp.errorhandler(404)
    def handle_agendatec_404(e):
        if wants_json():
            return jsonify({"error": "not_found", "status": 404}), 404
        return render_agendatec_error_page(404, "La página que buscas no existe en AgendaTec")
    
    @agendatec_pages_bp.errorhandler(403)
    def handle_agendatec_403(e):
        if wants_json():
            return jsonify({"error": "forbidden", "status": 403}), 403
        return render_agendatec_error_page(403, "No tienes permisos para acceder a este recurso de AgendaTec")

# Función para determinar el home según el rol (ESPECÍFICA DE AGENDATEC)
def agendatec_role_home(role: str) -> str:
    """Devuelve la ruta home específica de AgendaTec según el rol"""
    return {
        "student": "/agendatec/student/home",
        "coordinator": "/agendatec/coord/home", 
        "social_service": "/agendatec/social/home",
        "admin": "/agendatec/admin/home"
    }.get(role, "/agendatec/student/home")

# Función para obtener navegación de AgendaTec
def get_agendatec_navigation(user_permissions: set[str], student_window_open: bool = True):
    """Devuelve la navegación específica de AgendaTec basada en los permisos del usuario."""

    # Define la estructura completa de navegación con el permiso requerido para cada item
    full_nav_structure = [
        # Coordinador
        {"label": "Dashboard", "endpoint": "agendatec_pages.coord_pages.coord_home_page", "permission": "agendatec.coord_dashboard.page.view", "icon": "bi-speedometer2"},
        {"label": "Horario", "endpoint": "agendatec_pages.coord_pages.coord_slots_page", "permission": "agendatec.slots.page.list", "icon": "bi-calendar-week"},
        {"label": "Citas del día", "endpoint": "agendatec_pages.coord_pages.coord_appointments_page", "permission": "agendatec.appointments.page.list", "icon": "bi-calendar-event"},
        {"label": "Bajas", "endpoint": "agendatec_pages.coord_pages.coord_drops_page", "permission": "agendatec.drops.page.list", "icon": "bi-person-dash"},
        # Admin
        {"label": "Dashboard Admin", "endpoint": "agendatec_pages.admin_pages.admin_home", "permission": "agendatec.admin_dashboard.page.view", "icon": "bi-bar-chart-fill"},
        {"label": "Usuarios", "endpoint": "agendatec_pages.admin_pages.admin_users", "permission": "agendatec.users.page.list", "icon": "bi-people"},
        {"label": "Solicitudes", "endpoint": "agendatec_pages.admin_pages.admin_requests", "permission": "agendatec.requests.page.list", "icon": "bi-clipboard-data"},
        {"label": "Crear Solicitud", "endpoint": "agendatec_pages.admin_pages.admin_create_request", "permission": "agendatec.requests.page.create", "icon": "bi-plus-circle"},
        {"label": "Reportes", "endpoint": "agendatec_pages.admin_pages.admin_reports", "permission": "agendatec.reports.page.view", "icon": "bi-graph-up"},
        {"label": "Encuestas", "endpoint": "agendatec_pages.admin_surveys_pages.admin_surveys", "permission": "agendatec.surveys.page.list", "icon": "bi-list-check"},
        {"label": "Períodos", "endpoint": "agendatec_pages.admin_pages.admin_periods", "permission": "agendatec.periods.page.list", "icon": "bi-calendar-check"},
        # Servicio Social
        {"label": "Citas", "endpoint": "agendatec_pages.social_pages.social_home", "permission": "agendatec.social.page.home", "icon": "bi-calendar-heart"}
    ]

    # Filtra la lista: incluye un item solo si el usuario tiene el permiso requerido
    return [item for item in full_nav_structure if item["permission"] in user_permissions]


@agendatec_pages_bp.context_processor
def inject_agendatec_nav():
    """Inyecta navegación específica de AgendaTec en todas las páginas"""
    from itcj.apps.agendatec.utils.period_utils import is_student_window_open
    
    nav_items = []
    
    # CRÍTICO: No ejecutar lógica compleja en páginas de error para evitar loops
    if g.get("current_user") and not getattr(request, 'is_error_handler', False):
        try:
            user_id = g.current_user["sub"]
            student_open = is_student_window_open()
            
            # 1. Obtener los roles del usuario DENTRO de agendatec de forma segura
            agendatec_roles = user_roles_in_app(user_id, "agendatec")

            # 2. Si tiene el rol de estudiante en la app, mostrar la navegación de estudiante
            if "student" in agendatec_roles and student_open:
                nav_items = [
                    {"label": "Inicio", "endpoint": "agendatec_pages.student_pages.student_home", "icon": "bi-house"},
                    {"label": "Mis solicitudes", "endpoint": "agendatec_pages.student_pages.student_requests", "icon": "bi-journal-text"},
                ]
            # Si no es estudiante, construir la navegación basada en permisos
            else:
                user_perms = get_user_permissions_for_app(user_id, "agendatec")
                nav_items = get_agendatec_navigation(user_perms, student_open)

            # Añade la URL a cada item para usarla en el template
            for item in nav_items:
                item['url'] = url_for(item['endpoint'])
                
        except Exception as e:
            # Si hay error, no fallar - simplemente no mostrar navegación
            current_app.logger.warning(f"Error en context processor de AgendaTec: {e}")
            nav_items = []

    return {"agendatec_nav_items": nav_items}

@agendatec_pages_bp.get("/")
@login_required  
def home():
    if g.current_user:
        role = get_role_agenda(g.current_user["sub"])
        current_app.logger.warning(f"Redirigiendo a home de {role if role else 'sin rol'} en AgendaTec")
        return redirect(agendatec_role_home(role))
    return redirect(url_for("pages_core.pages_auth.login_page"))

# Registrar los error handlers específicos de AgendaTec
register_agendatec_error_handlers()
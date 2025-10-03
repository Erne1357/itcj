# itcj/apps/agendatec/__init__.py
from flask import Blueprint, redirect, url_for, g, current_app
from itcj.core.utils.decorators import login_required, guard_blueprint
from itcj.core.services.authz_service import get_user_permissions_for_app, user_roles_in_app

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

agendatec_api_bp.register_blueprint(api_programs_bp, url_prefix="/programs")
agendatec_api_bp.register_blueprint(api_avail_bp, url_prefix="/availability")
agendatec_api_bp.register_blueprint(api_req_bp, url_prefix="/requests")
agendatec_api_bp.register_blueprint(api_slots_bp, url_prefix="/slots")
agendatec_api_bp.register_blueprint(api_coord_bp, url_prefix="/coord")
agendatec_api_bp.register_blueprint(api_social_bp, url_prefix="/social")
agendatec_api_bp.register_blueprint(api_admin_bp, url_prefix="/admin")
agendatec_api_bp.register_blueprint(api_notifications_bp, url_prefix="/notifications")

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
        {"label": "Dashboard", "endpoint": "agendatec_pages.coord_pages.coord_home_page", "permission": "agendatec.coord_dashboard.view"},
        {"label": "Horario", "endpoint": "agendatec_pages.coord_pages.coord_slots_page", "permission": "agendatec.slots.view"},
        {"label": "Citas del día", "endpoint": "agendatec_pages.coord_pages.coord_appointments_page", "permission": "agendatec.appointments.view"},
        {"label": "Bajas", "endpoint": "agendatec_pages.coord_pages.coord_drops_page", "permission": "agendatec.drops.view"},
        # Admin
        {"label": "Dashboard Admin", "endpoint": "agendatec_pages.admin_pages.admin_home", "permission": "agendatec.admin_dashboard.view"},
        {"label": "Usuarios", "endpoint": "agendatec_pages.admin_pages.admin_users", "permission": "agendatec.users.view"},
        {"label": "Solicitudes", "endpoint": "agendatec_pages.admin_pages.admin_requests", "permission": "agendatec.requests_all.view"},
        {"label": "Reportes", "endpoint": "agendatec_pages.admin_pages.admin_reports", "permission": "agendatec.reports.view"},
        {"label": "Encuestas", "endpoint": "agendatec_pages.admin_surveys_pages.admin_surveys", "permission": "agendatec.surveys.view"},
        # Servicio Social
        {"label": "Citas", "endpoint": "agendatec_pages.social_pages.social_home", "permission": "agendatec.social_home.view"}
    ]
    
    # Filtra la lista: incluye un item solo si el usuario tiene el permiso requerido
    return [item for item in full_nav_structure if item["permission"] in user_permissions]


@agendatec_pages_bp.context_processor
def inject_agendatec_nav():
    from itcj.core.utils.admit_window import is_student_window_open
    
    nav_items = []
    if g.get("current_user"):
        user_id = g.current_user["sub"]
        student_open = is_student_window_open()
        
        # 1. Obtener los roles del usuario DENTRO de agendatec
        agendatec_roles = user_roles_in_app(user_id, "agendatec")

        # 2. Si tiene el rol de estudiante en la app, mostrar la navegación de estudiante
        if "student" in agendatec_roles and student_open:
            nav_items = [
                {"label": "Inicio", "endpoint": "agendatec_pages.student_pages.student_home"},
                {"label": "Mis solicitudes", "endpoint": "agendatec_pages.student_pages.student_requests"},
            ]
        # Si no es estudiante, construir la navegación basada en permisos
        else:
            user_perms = get_user_permissions_for_app(user_id, "agendatec")
            nav_items = get_agendatec_navigation(user_perms, student_open)

    # Añade la URL a cada item para usarla en el template
    for item in nav_items:
        item['url'] = url_for(item['endpoint'])

    return {"agendatec_nav_items": nav_items}

@agendatec_pages_bp.get("/")
@login_required  
def home():
    current_app.logger.info(f"Redirigiendo a home de {g.current_user.get('role') if g.current_user else 'anónimo'}")
    if g.current_user:
        role = g.current_user.get("role")
        return redirect(agendatec_role_home(role))
    return redirect(url_for("pages_core.pages_auth.login_page"))
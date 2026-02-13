# itcj/apps/vistetec/__init__.py
from flask import Blueprint, g, request, url_for, render_template, current_app
from itcj.core.utils.decorators import login_required, guard_blueprint
from itcj.core.services.authz_service import user_roles_in_app, get_user_permissions_for_app
from itcj.apps.vistetec import models
import logging

logger = logging.getLogger(__name__)

# Blueprints principales
vistetec_api_bp = Blueprint('vistetec_api', __name__)
vistetec_pages_bp = Blueprint('vistetec_pages', __name__,
                              template_folder='templates',
                              static_folder='static')

guard_blueprint(vistetec_api_bp, "vistetec")
guard_blueprint(vistetec_pages_bp, "vistetec")

# Registro de blueprints de API
from itcj.apps.vistetec.routes.api import (
    catalog_api_bp,
    appointments_api_bp,
    garments_api_bp,
    donations_api_bp,
    pantry_api_bp,
    slots_api_bp,
    reports_api_bp,
)

vistetec_api_bp.register_blueprint(catalog_api_bp, url_prefix='/catalog')
vistetec_api_bp.register_blueprint(appointments_api_bp, url_prefix='/appointments')
vistetec_api_bp.register_blueprint(garments_api_bp, url_prefix='/garments')
vistetec_api_bp.register_blueprint(donations_api_bp, url_prefix='/donations')
vistetec_api_bp.register_blueprint(pantry_api_bp, url_prefix='/pantry')
vistetec_api_bp.register_blueprint(slots_api_bp, url_prefix='/slots')
vistetec_api_bp.register_blueprint(reports_api_bp, url_prefix='/reports')

# Registro de blueprints de páginas
from itcj.apps.vistetec.routes.pages import (
    student_pages_bp,
    volunteer_pages_bp,
    admin_pages_bp,
)

vistetec_pages_bp.register_blueprint(student_pages_bp, url_prefix='/student')
vistetec_pages_bp.register_blueprint(volunteer_pages_bp, url_prefix='/volunteer')
vistetec_pages_bp.register_blueprint(admin_pages_bp, url_prefix='/admin')


@vistetec_pages_bp.context_processor
def inject_vistetec_nav():
    """Inyecta navegación dinámica de VisteTec en todas las páginas."""
    nav_items = []
    user_roles = set()

    if g.get("current_user") and not getattr(request, 'is_error_handler', False):
        try:
            user_id = g.current_user["sub"]
            user_roles = set(user_roles_in_app(user_id, "vistetec"))
            user_perms = get_user_permissions_for_app(user_id, "vistetec")

            # Navegación para estudiantes
            if 'student' in user_roles:
                nav_items.extend([
                    {
                        'label': 'Catálogo',
                        'endpoint': 'vistetec_pages.student_pages.catalog',
                        'icon': 'bi-grid-3x3-gap',
                    },
                    {
                        'label': 'Mis Apartados',
                        'endpoint': 'vistetec_pages.student_pages.my_appointments',
                        'icon': 'bi-calendar-check',
                    },
                    {
                        'label': 'Mis Donaciones',
                        'endpoint': 'vistetec_pages.student_pages.my_donations',
                        'icon': 'bi-heart',
                    },
                ])

            # Navegación para voluntarios
            if 'volunteer' in user_roles:
                nav_items.extend([
                    {
                        'label': 'Dashboard',
                        'endpoint': 'vistetec_pages.volunteer_pages.dashboard',
                        'icon': 'bi-speedometer2',
                    },
                    {
                        'label': 'Citas',
                        'endpoint': 'vistetec_pages.volunteer_pages.appointments',
                        'icon': 'bi-calendar2-week',
                    },
                    {
                        'label': 'Registrar Prenda',
                        'endpoint': 'vistetec_pages.volunteer_pages.garment_form',
                        'icon': 'bi-plus-circle',
                    },
                    {
                        'label': 'Registrar Donación',
                        'endpoint': 'vistetec_pages.volunteer_pages.register_donation',
                        'icon': 'bi-gift',
                    },
                ])

            # Navegación para admin
            if 'admin' in user_roles:
                nav_items.extend([
                    {
                        'label': 'Dashboard Admin',
                        'endpoint': 'vistetec_pages.admin_pages.dashboard',
                        'icon': 'bi-speedometer',
                    },
                    {
                        'label': 'Prendas',
                        'endpoint': 'vistetec_pages.admin_pages.garments',
                        'icon': 'bi-tag',
                    },
                    {
                        'label': 'Despensa',
                        'endpoint': 'vistetec_pages.admin_pages.pantry',
                        'icon': 'bi-box-seam',
                    },
                    {
                        'label': 'Campañas',
                        'endpoint': 'vistetec_pages.admin_pages.campaigns',
                        'icon': 'bi-megaphone',
                    },
                    {
                        'label': 'Reportes',
                        'endpoint': 'vistetec_pages.admin_pages.reports',
                        'icon': 'bi-graph-up',
                    },
                ])

            # Agregar URL a cada item
            for item in nav_items:
                if item.get('endpoint') and item['endpoint'] != '#':
                    try:
                        item['url'] = url_for(item['endpoint'])
                    except Exception:
                        item['url'] = '#'

        except Exception as e:
            current_app.logger.warning(f"Error en context processor de VisteTec: {e}")
            nav_items = []
            user_roles = set()

    return {
        "vistetec_nav_items": nav_items,
        "current_route": request.endpoint,
        "user_roles": user_roles,
    }


# ==================== RUTA PRINCIPAL ====================
@vistetec_pages_bp.get("/")
@login_required
def home():
    """Landing page de VisteTec."""
    return render_template("vistetec/home.html", title="VisteTec")

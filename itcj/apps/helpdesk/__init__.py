# itcj/apps/helpdesk/__init__.py
from flask import Blueprint, redirect, url_for, g, render_template, request, jsonify, current_app
from itcj.core.utils.decorators import login_required, guard_blueprint
from itcj.core.services.authz_service import user_roles_in_app, get_user_permissions_for_app
from itcj.apps.helpdesk import models
from itcj.apps.helpdesk.utils.navigation import get_helpdesk_navigation, get_helpdesk_role_groups
import logging

logger = logging.getLogger(__name__)

# Blueprints principales
helpdesk_api_bp = Blueprint('helpdesk_api', __name__)
helpdesk_pages_bp = Blueprint('helpdesk_pages', __name__, 
                              template_folder='templates', 
                              static_folder='static')

guard_blueprint(helpdesk_api_bp, "helpdesk")
guard_blueprint(helpdesk_pages_bp, "helpdesk")

# Registro de blueprints de API
from itcj.apps.helpdesk.routes.api import (
    tickets_api_bp,
    assignments_api_bp,
    comments_api_bp,
    attachments_api_bp,
    categories_api_bp,
    inventory_api_bp,
)

helpdesk_api_bp.register_blueprint(tickets_api_bp, url_prefix='/tickets')
helpdesk_api_bp.register_blueprint(assignments_api_bp, url_prefix='/assignments')
helpdesk_api_bp.register_blueprint(comments_api_bp, url_prefix='/comments')
helpdesk_api_bp.register_blueprint(attachments_api_bp, url_prefix='/attachments')
helpdesk_api_bp.register_blueprint(categories_api_bp, url_prefix='/categories')
helpdesk_api_bp.register_blueprint(inventory_api_bp, url_prefix='/inventory')
# Registro de blueprints de pages
from itcj.apps.helpdesk.routes.pages import (
    user_pages_bp,
    secretary_pages_bp,
    technician_pages_bp,
    department_pages_bp,
    inventory_pages_bp,
    admin_pages_bp
)

helpdesk_pages_bp.register_blueprint(user_pages_bp, url_prefix='/user')
helpdesk_pages_bp.register_blueprint(secretary_pages_bp, url_prefix='/secretary')
helpdesk_pages_bp.register_blueprint(technician_pages_bp, url_prefix='/technician')
helpdesk_pages_bp.register_blueprint(department_pages_bp, url_prefix='/department')
helpdesk_pages_bp.register_blueprint(inventory_pages_bp, url_prefix='/inventory')
helpdesk_pages_bp.register_blueprint(admin_pages_bp, url_prefix='/admin')


@helpdesk_pages_bp.context_processor
def inject_helpdesk_nav():
    """
    Inyecta navegación dinámica de Help-Desk en todas las páginas.
    Similar al context processor de AgendaTec.
    """
    nav_items = []
    
    # CRÍTICO: No ejecutar en páginas de error
    if g.get("current_user") and not getattr(request, 'is_error_handler', False):
        try:
            user_id = g.current_user["sub"]
            
            # Obtener roles y permisos del usuario en helpdesk
            user_roles = set(user_roles_in_app(user_id, "helpdesk"))
            user_perms = get_user_permissions_for_app(user_id, "helpdesk")
            
            # Generar navegación
            nav_items = get_helpdesk_navigation(user_perms, user_roles)
            
            # Añadir URL a cada item
            for item in nav_items:
                if item.get('endpoint') and item['endpoint'] != '#':
                    item['url'] = url_for(item['endpoint'])
                    # Añadir fragment si existe
                    if 'fragment' in item:
                        item['url'] += item['fragment']
                
                # Procesar dropdown
                if 'dropdown' in item:
                    for sub_item in item['dropdown']:
                        if sub_item.get('endpoint') and sub_item['endpoint'] != '#':
                            sub_item['url'] = url_for(sub_item['endpoint'])
                            if 'fragment' in sub_item:
                                sub_item['url'] += sub_item['fragment']
                        
        except Exception as e:
            current_app.logger.warning(f"Error en context processor de Help-Desk: {e}")
            nav_items = []
    return {
        "helpdesk_nav_items": nav_items,
        "current_route": request.endpoint
    }



# ==================== RUTA PRINCIPAL (LANDING) ====================
@helpdesk_pages_bp.get("/")
@login_required
def home():
    """Landing page - entry point para todos los usuarios"""
    return render_template("helpdesk/home_landing.html", title="Help-Desk")


# ==================== REDIRECCIÓN POR ROL ====================
@helpdesk_pages_bp.post("/")
@login_required
def redirect_by_role():
    """
    Redirige al dashboard apropiado según el rol del usuario.
    El botón "Pedir Ayuda" del landing hace POST aquí.
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    current_app.logger.warning(f"Usuario {user_id} solicitando redirección. Roles: {user_roles}")
    
    # Prioridad de roles (de más específico a más general)
    if 'admin' in user_roles:
        return jsonify({'redirect': url_for('helpdesk_pages.admin_pages.home')}), 200

    elif 'secretary' in user_roles:
        return jsonify({'redirect': url_for('helpdesk_pages.secretary_pages.dashboard')}), 200

    elif 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        return jsonify({'redirect': url_for('helpdesk_pages.technician_pages.dashboard')}), 200
    
    elif 'department_head' in user_roles:
        return jsonify({'redirect': url_for('helpdesk_pages.department_pages.tickets')}), 200
    
    elif 'staff' in user_roles:
        return jsonify({'redirect': url_for('helpdesk_pages.user_pages.create_ticket')}), 200
    else:
        current_app.logger.error(f"Usuario {user_id} no tiene roles asignados en Help-Desk.")
        return jsonify({'error': 'no_roles'}), 403

# ==================== FUNCIÓN DE ROL HOME ====================
def role_home(role: str) -> str:
    """
    Retorna la URL home apropiada según el rol.
    Usado por el core para redireccionar después del login.
    """
    role_map = {
        "staff": "/help-desk/user/create",
        "secretary": "/help-desk/secretary",
        "tech_desarrollo": "/help-desk/technician",
        "tech_soporte": "/help-desk/technician",
        "department_head": "/help-desk/department",
        "admin": "/help-desk/admin/home"
    }
    
    return role_map.get(role, "/")
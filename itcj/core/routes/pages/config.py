# itcj/core/routes/pages/config.py
from flask import Blueprint, render_template, request, redirect, url_for, g
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.user import User
from itcj.core.utils.decorators import login_required
from itcj.core.extensions import db

# Blueprint de configuración
pages_config_bp = Blueprint('pages_config', __name__, template_folder='templates', static_folder='static')

# Página principal de configuración
@pages_config_bp.route("/config")
@login_required
# Decorador comentado para que cualquiera pueda acceder mientras configuramos
# @role_required_page(["admin", "super_admin"])  
def settings():
    """Panel principal de configuración del sistema"""
    apps = App.query.order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    users_count = User.query.count()
    permissions_count = Permission.query.count()
    
    return render_template("config/index.html", 
                         apps=apps, 
                         roles=roles,
                         users_count=users_count,
                         permissions_count=permissions_count)

# Gestión de Apps
@pages_config_bp.route("/config/apps")
@login_required
def apps_management():
    """Página de gestión de aplicaciones"""
    apps = App.query.order_by(App.key.asc()).all()
    return render_template("config/apps.html", apps=apps)

# Gestión de Roles
@pages_config_bp.route("/config/roles")
@login_required
def roles_management():
    """Página de gestión de roles globales"""
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("config/roles.html", roles=roles)

# Gestión de Permisos por App
@pages_config_bp.route("/config/apps/<string:app_key>/permissions")
@login_required
def app_permissions(app_key):
    """Página de gestión de permisos de una app específica"""
    app = App.query.filter_by(key=app_key).first_or_404()
    permissions = Permission.query.filter_by(app_id=app.id).order_by(Permission.code.asc()).all()
    return render_template("config/permissions.html", app=app, permissions=permissions)

# Gestión de Usuarios
@pages_config_bp.route("/config/users")
@login_required
def users_management():
    """Página de gestión de usuarios y sus asignaciones"""
    users = User.query.order_by(User.full_name.asc()).all()
    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("config/users.html", users=users, apps=apps, roles=roles)

# Detalle de usuario específico
@pages_config_bp.route("/config/users/<int:user_id>")
@login_required
def user_detail(user_id):
    """Página de detalle de un usuario específico con sus asignaciones"""
    user = User.query.get_or_404(user_id)
    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("config/user_detail.html", user=user, apps=apps, roles=roles)
# itcj/core/routes/pages/config.py
from flask import Blueprint, render_template, request, redirect, url_for, g
from itcj.core.models.app import App
from itcj.core.models.department import Department
from itcj.core.models.position import Position
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.user import User
from itcj.core.utils.decorators import login_required
from itcj.core.extensions import db
from sqlalchemy import or_

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
    departments_count = Department.query.filter_by(is_active=True).count()

    context = {
        "apps": apps,
        "roles": roles,
        "users_count": users_count,
        "permissions_count": permissions_count,
        "departments_count": departments_count
    }
    return render_template("config/index.html", **context)
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

#
#  Gestión de Usuarios
@pages_config_bp.route("/config/users")
@login_required
def users_management():
    """Página de gestión de usuarios con paginación Y BÚSQUEDA"""
    page = request.args.get('page', 1, type=int)
    # 1. Obtener el término de búsqueda de los argumentos de la URL
    query_string = request.args.get('q', '', type=str)
    per_page = 20

    # 2. Construir la consulta base
    users_query = User.query

    # 3. Si hay un término de búsqueda, aplicar filtros
    if query_string:
        search_term = f"%{query_string}%"
        users_query = users_query.filter(
            or_(
                User.full_name.ilike(search_term),
                User.username.ilike(search_term),
                User.control_number.ilike(search_term),
                User.email.ilike(search_term)
            )
        )

    # 4. Ordenar y paginar sobre la consulta (ya sea la original o la filtrada)
    pagination = users_query.order_by(User.full_name.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    users = pagination.items

    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    
    return render_template(
        "config/users.html", 
        users=users, 
        apps=apps, 
        roles=roles, 
        pagination=pagination,
        # 5. Pasar el término de búsqueda de vuelta a la plantilla
        current_query=query_string
    )


# Detalle de usuario específico
@pages_config_bp.route("/config/users/<int:user_id>")
@login_required
def user_detail(user_id):
    """Página de detalle de un usuario específico con sus asignaciones"""
    user = User.query.get_or_404(user_id)
    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("config/user_detail.html", user=user, apps=apps, roles=roles)


@pages_config_bp.get("/config/departments")
@login_required
def positions_management():  # Mantener el nombre para no romper URLs existentes
    """Vista principal de departamentos (era positions_management)"""
    return render_template("config/departments.html")

@pages_config_bp.get("/config/departments/<int:department_id>")
@login_required
def department_detail(department_id):
    """Vista de detalle de un departamento con sus puestos"""
    dept = Department.query.get_or_404(department_id)
    return render_template("config/department_detail.html", department_id=department_id, department=dept)

@pages_config_bp.get("/config/positions/<int:position_id>")
@login_required
def position_detail(position_id):
    """Vista de detalle/edición de un puesto"""
    from itcj.core.models.position import Position
    from itcj.core.models.role import Role
    position = Position.query.get_or_404(position_id)
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("config/position_detail.html", position_id=position_id, position=position, roles=roles)
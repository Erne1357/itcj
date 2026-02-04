# itcj/core/routes/pages/config.py
from flask import Blueprint, render_template, request, redirect, url_for, g
from itcj.core.models.app import App
from itcj.core.models.department import Department
from itcj.core.models.position import Position
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.user import User
from itcj.core.utils.decorators import login_required, app_required
from itcj.core.extensions import db
from sqlalchemy import or_

# Blueprint de configuración
pages_config_bp = Blueprint('pages_config', __name__, template_folder='templates', static_folder='static')

# Página principal de configuración
@pages_config_bp.route("/config")
@login_required
@app_required('itcj', roles=['admin'])
def settings():
    """Panel principal de configuración del sistema"""
    apps = App.query.order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    users_count = User.query.count()
    permissions_count = Permission.query.count()
    departments_count = Department.query.filter_by(is_active=True).count()

    # Obtener info de tematicas para el panel
    themes_count = 0
    active_theme_name = None
    try:
        from itcj.core.models.theme import Theme
        themes_count = Theme.query.filter_by(is_enabled=True).count()
        from itcj.core.services import themes_service
        active = themes_service.get_active_theme()
        if active:
            active_theme_name = active.name
    except Exception:
        pass

    context = {
        "apps": apps,
        "roles": roles,
        "users_count": users_count,
        "permissions_count": permissions_count,
        "departments_count": departments_count,
        "themes_count": themes_count,
        "active_theme_name": active_theme_name,
    }
    return render_template("core/config/index.html", **context)

# === Sistema ===

@pages_config_bp.route("/config/apps")
@login_required
@app_required('itcj', roles=['admin'])
def apps_management():
    """Página de gestión de aplicaciones"""
    apps = App.query.order_by(App.key.asc()).all()
    return render_template("core/config/system/apps.html", apps=apps)

@pages_config_bp.route("/config/roles")
@login_required
@app_required('itcj', roles=['admin'])
def roles_management():
    """Página de gestión de roles globales"""
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("core/config/system/roles.html", roles=roles)

@pages_config_bp.route("/config/apps/<string:app_key>/permissions")
@login_required
@app_required('itcj', roles=['admin'])
def app_permissions(app_key):
    """Página de gestión de permisos de una app específica"""
    app = App.query.filter_by(key=app_key).first_or_404()
    permissions = Permission.query.filter_by(app_id=app.id).order_by(Permission.code.asc()).all()
    return render_template("core/config/system/permissions.html", app=app, permissions=permissions)

@pages_config_bp.route("/config/themes")
@login_required
@app_required('itcj', roles=['admin'])
def themes_management():
    """Pagina de gestion de tematicas del sistema"""
    return render_template("core/config/system/themes.html")

# === Usuarios ===

@pages_config_bp.route("/config/users")
@login_required
@app_required('itcj', roles=['admin'])
def users_management():
    """Página de gestión de usuarios con paginación Y BÚSQUEDA"""
    page = request.args.get('page', 1, type=int)
    query_string = request.args.get('q', '', type=str)
    per_page = 20

    users_query = User.query

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

    pagination = users_query.order_by(User.full_name.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    users = pagination.items

    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()

    return render_template(
        "core/config/users/users.html",
        users=users,
        apps=apps,
        roles=roles,
        pagination=pagination,
        current_query=query_string
    )

@pages_config_bp.route("/config/users/<int:user_id>")
@login_required
@app_required('itcj', roles=['admin'])
def user_detail(user_id):
    """Página de detalle de un usuario específico con sus asignaciones"""
    user = User.query.get_or_404(user_id)
    apps = App.query.filter_by(is_active=True).order_by(App.key.asc()).all()
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("core/config/users/user_detail.html", user=user, apps=apps, roles=roles)

# === Organizacion ===

@pages_config_bp.get("/config/departments")
@login_required
@app_required('itcj', roles=['admin'])
def positions_management():
    """Vista principal de departamentos"""
    return render_template("core/config/organization/departments.html")

@pages_config_bp.get("/config/departments/<int:department_id>")
@login_required
@app_required('itcj', roles=['admin'])
def department_detail(department_id):
    """Vista de detalle de un departamento con sus puestos"""
    dept = Department.query.get_or_404(department_id)
    return render_template("core/config/organization/department_detail.html", department_id=department_id, department=dept)

@pages_config_bp.get("/config/positions/<int:position_id>")
@login_required
@app_required('itcj', roles=['admin'])
def position_detail(position_id):
    """Vista de detalle/edición de un puesto"""
    from itcj.core.models.position import Position
    from itcj.core.models.role import Role
    position = Position.query.get_or_404(position_id)
    roles = Role.query.order_by(Role.name.asc()).all()
    return render_template("core/config/organization/position_detail.html", position_id=position_id, position=position, roles=roles)

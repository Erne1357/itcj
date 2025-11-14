# itcj/apps/helpdesk/routes/pages/secretary.py
from flask import render_template, g, abort
from itcj.core.utils.decorators import app_required
from itcj.core.models.user import User
from itcj.core.models.department import Department
from . import secretary_pages_bp

@secretary_pages_bp.get('/')
@app_required('helpdesk', perms=['helpdesk.dashboard.secretary'])
def dashboard():
    """
    Dashboard simple para secretarías
    
    Muestra:
    - KPIs básicos del departamento
    - Lista de tickets del departamento
    - Opción de crear tickets
    - Vista de inventario (solo lectura)
    
    NO permite:
    - Asignar tickets (eso ahora es /admin/assign-tickets)
    - Generar reportes avanzados
    - Editar inventario
    """
    user_id = int(g.current_user['sub'])
    
    # Obtener usuario y su departamento a través de su puesto activo
    user = User.query.get(user_id)
    if not user:
        abort(404, description="Usuario no encontrado")
    
    department = user.get_current_department()
    if not department:
        abort(403, description="Usuario sin departamento asignado")
    
    return render_template(
        'secretary/dashboard.html',
        title="Secretaría - Dashboard",
        department=department,
        department_name=department.name
    )
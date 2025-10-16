# itcj/apps/helpdesk/routes/pages/department_head.py
from flask import render_template, g, abort
from itcj.core.utils.decorators import app_required
from itcj.core.services import positions_service
from . import department_pages_bp

@department_pages_bp.get('/')
@app_required('helpdesk', positions=['department_head'])
def tickets():
    """Vista de tickets del departamento"""
    # Obtener el departamento del cual el usuario es jefe
    user_id = int(g.current_user['sub'])
    
    # Usar el servicio para obtener el departamento que maneja
    managed_department = positions_service.get_user_primary_managed_department(user_id)
    
    if not managed_department:
        abort(403, "No tienes un departamento asignado como jefe")
    
    department = managed_department['department']
    position = managed_department['position']
    
    return render_template('department_head/dashboard.html', 
                         title=f"Departamento - {department['name']}", 
                         department=department,
                         position=position,
                         assignment=managed_department['assignment'])
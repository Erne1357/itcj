# itcj/apps/helpdesk/routes/pages/department.py
from flask import render_template
from itcj.core.utils.decorators import app_required
from . import department_pages_bp

@department_pages_bp.get('/')
@app_required('helpdesk', positions=['jefe_depto'])
def tickets():
    """Vista de tickets del departamento"""
    return render_template('department_head/dashboard.html', title="Departamento - Tickets")
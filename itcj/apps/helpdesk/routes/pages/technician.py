# itcj/apps/helpdesk/routes/pages/technician.py
from flask import render_template
from itcj.core.utils.decorators import app_required
from . import technician_pages_bp

@technician_pages_bp.get('/')
@app_required('helpdesk', roles=['tech_desarrollo', 'tech_soporte', 'admin'])
def dashboard():
    """Dashboard de técnicos"""
    return render_template('technician/dashboard.html', title="Técnico - Dashboard")
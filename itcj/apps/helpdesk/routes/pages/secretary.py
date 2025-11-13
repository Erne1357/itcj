# itcj/apps/helpdesk/routes/pages/secretary.py
from flask import render_template
from itcj.core.utils.decorators import app_required
from . import secretary_pages_bp

@secretary_pages_bp.get('/')
@app_required('helpdesk', perms=['helpdesk.dashboard.secretary'])
def dashboard():
    """Dashboard principal de secretaría"""
    return render_template('secretary/dashboard.html', title="Secretaría - Dashboard")
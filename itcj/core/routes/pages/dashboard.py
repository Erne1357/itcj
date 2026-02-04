# routes/pages/dashboard.py
from flask import Blueprint, render_template, g, redirect, request, url_for
from itcj.core.utils.decorators import login_required, app_required
from itcj.core.utils import role_home

pages_dashboard_bp = Blueprint("pages_dashboard", __name__)

@pages_dashboard_bp.get("/dashboard")
@login_required
@app_required('itcj', roles=['coordinator', 'social_service', 'admin', 'staff'])
def dashboard():
    # Staff en movil sin preferencia desktop: redirigir a mobile
    from itcj.core.services.mobile_service import is_mobile_user_agent
    prefer_desktop = request.cookies.get('prefer_desktop')
    if not prefer_desktop and is_mobile_user_agent(request.headers.get('User-Agent', '')):
        return redirect(url_for('pages_core.pages_mobile.mobile_dashboard'))

    return render_template("core/dashboard/dashboard.html")

# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from itcj.core.utils.decorators import login_required, app_required
from itcj.core.utils import role_home

pages_dashboard_bp = Blueprint("pages_dashboard", __name__)

@pages_dashboard_bp.get("/dashboard")
@login_required
@app_required('itcj', roles=['coordinator', 'social_service', 'admin', 'staff'])
def dashboard():
    #if g.current_user:
    #    return redirect(role_home(g.current_user.get("role")))
    return render_template("core/dashboard/dashboard.html")

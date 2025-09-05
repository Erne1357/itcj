# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from ....core.utils.decorators import login_required, role_required_page
from .... import role_home

pages_dashboard_bp = Blueprint("pages_dashboard", __name__,template_folder='../../templates', static_folder='../../static')

@pages_dashboard_bp.get("/dashboard")
@login_required
@role_required_page(["coordinator","social_service","admin"])
def login_page():
    #if g.current_user:
    #    return redirect(role_home(g.current_user.get("role")))
    return render_template("dashboard/dashboard.html")

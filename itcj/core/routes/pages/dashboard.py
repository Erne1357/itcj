# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from itcj.core.utils.decorators import login_required, role_required_page, pw_changed_required
from itcj.core.utils import role_home

pages_dashboard_bp = Blueprint("pages_dashboard", __name__)

@pages_dashboard_bp.get("/dashboard")
@login_required
@role_required_page(["coordinator","social_service","admin","staff"])
def dashboard():
    #if g.current_user:
    #    return redirect(role_home(g.current_user.get("role")))
    return render_template("dashboard/dashboard.html")

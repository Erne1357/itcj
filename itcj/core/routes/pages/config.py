# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from itcj.core.utils.decorators import login_required, role_required_page
from itcj.core.utils import role_home

pages_settings_bp = Blueprint("pages_settings", __name__)

@pages_settings_bp.get("/config")
@login_required
@role_required_page(["coordinator","social_service","admin"])
def settings():
    #if g.current_user:
    #    return redirect(role_home(g.current_user.get("role")))
    return render_template("dashboard/dashboard.html")
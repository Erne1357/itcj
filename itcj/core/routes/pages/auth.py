# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from itcj import role_home

pages_auth_bp = Blueprint("pages_auth", __name__,template_folder='../../templates', static_folder='../../static')

@pages_auth_bp.get("/login")
def login_page():
    if g.current_user:
        return redirect(role_home(g.current_user.get("role")))
    return render_template("auth/login.html")

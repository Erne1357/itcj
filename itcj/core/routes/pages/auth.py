# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect,current_app
from itcj.core.utils.role_home import role_home
import logging,json

pages_auth_bp = Blueprint("pages_auth", __name__)

@pages_auth_bp.get("/login")
def login_page():
    if g.current_user:
        current_app.logger.warning(f"Usuario : {g.current_user}")
        return redirect(role_home(g.current_user.get('role')))
    return render_template("auth/login.html")

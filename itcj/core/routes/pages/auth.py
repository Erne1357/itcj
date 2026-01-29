# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect,current_app
from itcj.core.utils.role_home import role_home
from itcj.core.services.authz_service import user_roles_in_app
import logging,json

pages_auth_bp = Blueprint("pages_auth", __name__)

@pages_auth_bp.get("/login")
def login_page():
    if g.current_user:
        current_app.logger.warning(f"Usuario : {g.current_user}")
        user_id = int(g.current_user['sub'])
        return redirect(role_home(user_roles_in_app(user_id, 'itcj')))
    return render_template("core/auth/login.html")

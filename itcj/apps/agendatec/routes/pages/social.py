# routes/pages/social.py
"""
Páginas de servicio social para AgendaTec.

Incluye: vista de citas del día.
"""
from flask import Blueprint, render_template

from itcj.core.utils.decorators import app_required, login_required

social_pages_bp = Blueprint("social_pages", __name__)

@social_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.social.page.home"])
def social_home():
    return render_template("agendatec/social/home.html", title="Servicio Social - Citas del día")

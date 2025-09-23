# routes/templates/social.py
from flask import Blueprint, render_template
from itcj.core.utils.decorators import login_required, role_required_page,app_required

social_pages_bp = Blueprint("social_pages", __name__)

@social_pages_bp.get("/home")
@login_required
@app_required(app_key="agendatec", perms=["agendatec.social_home.view"])
def social_home():
    return render_template("social/home.html", title="Servicio Social - Citas del día")

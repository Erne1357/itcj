# routes/templates/social.py
from flask import Blueprint, render_template
from itcj.core.utils.decorators import login_required, role_required_page

social_pages_bp = Blueprint("social_pages", __name__)

@social_pages_bp.get("/home")
@login_required
@role_required_page(["social_service","coordinator","admin"])
def social_home():
    return render_template("social/home.html", title="Servicio Social - Citas del día")

# routes/pages/auth.py
from flask import Blueprint, render_template, g, redirect
from itcj.core.utils.decorators import login_required, app_required, pw_changed_required
from itcj.core.utils import role_home
from itcj.core.services.profile_service import get_user_profile_data

pages_profile_bp = Blueprint("pages_profile", __name__)

@pages_profile_bp.get("/profile")
@login_required
@app_required('itcj', roles=['coordinator', 'social_service', 'admin', 'staff'])
def profile():
    user_id = int(g.current_user['sub'])
    
    # Obtener datos iniciales del perfil
    profile = get_user_profile_data(user_id)
    
    if not profile:
        return "Usuario no encontrado", 404
    return render_template("profile/profile.html", profile=profile)

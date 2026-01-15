# routes/api/coord/password.py
"""
Endpoints para gestión de contraseña del coordinador.

Incluye:
- coord_password_state: Verificar si debe cambiar contraseña
- change_password: Cambiar contraseña
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.core.models.coordinator import Coordinator
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.security import hash_nip, verify_nip

from .helpers import DEFAULT_NIP, get_current_user

coord_password_bp = Blueprint("coord_password", __name__)


@coord_password_bp.get("/password-state")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["coordinator"])
def coord_password_state():
    """
    Verifica si el coordinador debe cambiar su contraseña.

    Returns:
        JSON con must_change: True/False
    """
    u = get_current_user()
    if not u:
        return jsonify({"error": "user_not_found"}), 404

    must_change = verify_nip(DEFAULT_NIP, u.password_hash)
    return jsonify({"must_change": must_change})


@coord_password_bp.post("/change_password")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["coordinator"])
def change_password():
    """
    Cambia la contraseña del coordinador.

    Body JSON:
        new_password: Nueva contraseña (mínimo 4 caracteres)

    Returns:
        JSON con ok: True
    """
    u = get_current_user()
    if not u:
        return jsonify({"error": "user_not_found"}), 404

    data = request.get_json(silent=True) or {}
    new_password = (data.get("new_password") or "").strip()

    # Validar que la contraseña tenga al menos 4 caracteres
    if len(new_password) < 4:
        return jsonify({"error": "invalid_new_password"}), 400

    # Guardar hash nuevo
    coord = db.session.query(Coordinator).filter_by(user_id=u.id).first()
    if coord:
        coord.must_change_pw = False
    u.password_hash = hash_nip(new_password)
    db.session.commit()

    return jsonify({"ok": True})

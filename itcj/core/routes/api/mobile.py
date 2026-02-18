# itcj/core/routes/api/mobile.py
"""
API REST para el dashboard movil.
"""
from flask import Blueprint, jsonify, g
from itcj.core.utils.decorators import api_auth_required
from itcj.core.services import mobile_service as svc


api_mobile_bp = Blueprint("api_mobile_bp", __name__)


# ---------------------------
# Helpers
# ---------------------------

def _ok(data=None, status=200):
    if data is not None:
        return jsonify({"status": "ok", "data": data}), status
    return "", 204


def _bad(msg="bad_request", status=400):
    return jsonify({"status": "error", "error": msg}), status


# ---------------------------
# Endpoints
# ---------------------------

@api_mobile_bp.get("/apps")
@api_auth_required
def get_mobile_apps():
    """Retorna las apps habilitadas para movil segun permisos del usuario."""
    user_id = int(g.current_user["sub"])
    apps = svc.get_mobile_apps_for_user(user_id)
    user_type = svc.get_user_type(user_id)
    return _ok({"apps": apps, "user_type": user_type})


@api_mobile_bp.get("/user-type")
@api_auth_required
def get_user_type():
    """Retorna si el usuario es 'student' o 'staff'."""
    user_id = int(g.current_user["sub"])
    return _ok({"user_type": svc.get_user_type(user_id)})

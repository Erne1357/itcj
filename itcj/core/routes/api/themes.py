# itcj/core/routes/api/themes.py
"""
API REST para gestión de temáticas del sistema.
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_auth_required, api_app_required
from itcj.core.services import themes_service as svc


api_themes_bp = Blueprint("api_themes_bp", __name__)


# ---------------------------
# Helpers
# ---------------------------

def _ok(data=None, status=200):
    if data is not None:
        return jsonify({"status": "ok", "data": data}), status
    else:
        return "", 204


def _bad(msg="bad_request", status=400):
    return jsonify({"status": "error", "error": msg}), status


# ---------------------------
# Endpoints públicos
# ---------------------------

@api_themes_bp.get("/active")
def get_active_theme():
    """
    Obtiene la temática actualmente activa (endpoint público).
    No requiere autenticación para permitir aplicar temas sin login.
    """
    theme = svc.get_active_theme()
    if not theme:
        return _ok(None)
    return _ok(theme.to_dict(include_full=True))


# ---------------------------
# Endpoints protegidos (CRUD)
# ---------------------------

@api_themes_bp.get("")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def list_themes():
    """Lista todas las temáticas."""
    themes = svc.list_themes()
    return _ok([t.to_dict() for t in themes])


@api_themes_bp.get("/<int:theme_id>")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def get_theme(theme_id):
    """Obtiene el detalle de una temática."""
    theme = svc.get_theme(theme_id)
    if not theme:
        return _bad("theme_not_found", 404)
    return _ok(theme.to_dict(include_full=True))


@api_themes_bp.post("")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def create_theme():
    """Crea una nueva temática."""
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    if not name:
        return _bad("name_required")

    try:
        # Obtener user_id del contexto de autenticación
        user_id = getattr(g, 'user_id', None)
        theme = svc.create_theme(payload, created_by_id=user_id)
        return _ok(theme.to_dict(include_full=True), 201)
    except ValueError as e:
        return _bad(str(e), 409)
    except Exception as e:
        return _bad(f"error_creating_theme: {str(e)}", 500)


@api_themes_bp.patch("/<int:theme_id>")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def update_theme(theme_id):
    """Actualiza una temática existente."""
    payload = request.get_json(silent=True) or {}

    try:
        theme = svc.update_theme(theme_id, **payload)
        return _ok(theme.to_dict(include_full=True))
    except ValueError as e:
        error_msg = str(e)
        if "no encontrada" in error_msg.lower() or "not found" in error_msg.lower():
            return _bad(error_msg, 404)
        return _bad(error_msg, 409)
    except Exception as e:
        return _bad(f"error_updating_theme: {str(e)}", 500)


@api_themes_bp.post("/<int:theme_id>/toggle")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def toggle_theme(theme_id):
    """Activa o desactiva manualmente una temática."""
    payload = request.get_json(silent=True) or {}
    active = payload.get("active", False)

    try:
        theme = svc.toggle_theme_manual(theme_id, active)
        return _ok(theme.to_dict())
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        return _bad(f"error_toggling_theme: {str(e)}", 500)


@api_themes_bp.post("/<int:theme_id>/enable")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def toggle_theme_enabled(theme_id):
    """Habilita o deshabilita una temática."""
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled", True)

    try:
        theme = svc.toggle_theme_enabled(theme_id, enabled)
        return _ok(theme.to_dict())
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        return _bad(f"error_enabling_theme: {str(e)}", 500)


@api_themes_bp.delete("/<int:theme_id>")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def delete_theme(theme_id):
    """Elimina una temática."""
    try:
        svc.delete_theme(theme_id)
        return _ok({"deleted": True})
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        return _bad(f"error_deleting_theme: {str(e)}", 500)


# ---------------------------
# Endpoints de estadísticas
# ---------------------------

@api_themes_bp.get("/stats")
@api_auth_required
@api_app_required("itcj", roles=["admin"])
def get_themes_stats():
    """Obtiene estadísticas de temáticas."""
    return _ok({
        "total": svc.get_themes_count(),
        "active": svc.get_active_themes_count()
    })

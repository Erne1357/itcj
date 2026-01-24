"""
API REST para notificaciones del sistema ITCJ.

Endpoints:
- GET /notifications - Listar notificaciones con filtros
- GET /notifications/unread-counts - Conteos de no leídas por app
- PATCH /notifications/:id/read - Marcar individual como leída
- PATCH /notifications/mark-all-read - Marcar todas como leídas
- DELETE /notifications/:id - Eliminar notificación

Nota: Las notificaciones en tiempo real se envían via WebSocket (Socket.IO /notify namespace)
"""
from flask import Blueprint, jsonify, request, g, current_app
from itcj.core.utils.decorators import api_auth_required
from itcj.core.services.notification_service import NotificationService
from itcj.core.extensions import db


api_notifications_bp = Blueprint("api_notifications", __name__)


def _get_current_user_id():
    """Helper para obtener el ID del usuario actual desde g.current_user"""
    try:
        return int(g.current_user["sub"])
    except (KeyError, ValueError, TypeError):
        return None


@api_notifications_bp.get("")
@api_notifications_bp.get("/")
@api_auth_required
def list_notifications():
    """
    Lista notificaciones del usuario con filtros y paginación.

    Query params:
        - app: str - Filtrar por aplicación ('agendatec', 'helpdesk')
        - unread: str - '1' o 'true' para solo no leídas
        - limit: int - Máximo de resultados (default: 20, max: 100)
        - offset: int - Offset para paginación (default: 0)
        - before_id: int - Cursor-based pagination (ID de notificación)

    Returns:
        200: {
            "status": "ok",
            "data": {
                "items": [...],
                "total": int,
                "unread": int,
                "has_more": bool
            }
        }
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    # Extraer parámetros
    app_name = request.args.get('app')
    unread_only = request.args.get('unread', '').lower() in ['1', 'true']
    limit = min(int(request.args.get('limit', 20)), 100)
    offset = int(request.args.get('offset', 0))
    before_id = request.args.get('before_id', type=int)

    try:
        result = NotificationService.get_notifications(
            user_id=user_id,
            app_name=app_name,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
            before_id=before_id
        )

        return jsonify({
            "status": "ok",
            "data": result
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error listing notifications: {e}", exc_info=True)
        return jsonify({"error": "internal_error"}), 500


@api_notifications_bp.get("/unread-counts")
@api_auth_required
def get_unread_counts():
    """
    Obtiene conteos de notificaciones no leídas agrupadas por app.

    Returns:
        200: {
            "status": "ok",
            "data": {
                "counts": {"agendatec": 5, "helpdesk": 2},
                "total": 7
            }
        }
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    try:
        counts = NotificationService.get_unread_counts_by_app(user_id)
        total = sum(counts.values())

        return jsonify({
            "status": "ok",
            "data": {
                "counts": counts,
                "total": total
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error getting unread counts: {e}", exc_info=True)
        return jsonify({"error": "internal_error"}), 500


@api_notifications_bp.patch("/<int:notification_id>/read")
@api_auth_required
def mark_notification_read(notification_id):
    """
    Marca una notificación específica como leída.

    Args:
        notification_id: ID de la notificación

    Returns:
        200: {"status": "ok"}
        404: {"error": "not_found"}
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    try:
        success = NotificationService.mark_read(notification_id, user_id)

        if not success:
            return jsonify({"error": "not_found"}), 404

        db.session.commit()

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking notification as read: {e}", exc_info=True)
        return jsonify({"error": "internal_error"}), 500


@api_notifications_bp.patch("/mark-all-read")
@api_auth_required
def mark_all_notifications_read():
    """
    Marca todas las notificaciones no leídas como leídas.

    Query params:
        - app: str - Opcional, filtrar por aplicación específica

    Returns:
        200: {"status": "ok", "count": int}
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    app_name = request.args.get('app')

    try:
        count = NotificationService.mark_all_read(user_id, app_name)
        db.session.commit()

        return jsonify({
            "status": "ok",
            "count": count
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking all as read: {e}", exc_info=True)
        return jsonify({"error": "internal_error"}), 500


@api_notifications_bp.delete("/<int:notification_id>")
@api_auth_required
def delete_notification(notification_id):
    """
    Elimina una notificación.

    Args:
        notification_id: ID de la notificación

    Returns:
        200: {"status": "ok"}
        404: {"error": "not_found"}
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    try:
        success = NotificationService.delete_notification(notification_id, user_id)

        if not success:
            return jsonify({"error": "not_found"}), 404

        db.session.commit()

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting notification: {e}", exc_info=True)
        return jsonify({"error": "internal_error"}), 500

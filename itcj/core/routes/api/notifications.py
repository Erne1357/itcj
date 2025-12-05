"""
API REST + SSE para notificaciones del sistema ITCJ.

Endpoints:
- GET /notifications - Listar notificaciones con filtros
- GET /notifications/stream - SSE endpoint para notificaciones en tiempo real
- GET /notifications/unread-counts - Conteos de no leídas por app
- PATCH /notifications/:id/read - Marcar individual como leída
- PATCH /notifications/mark-all-read - Marcar todas como leídas
- DELETE /notifications/:id - Eliminar notificación
"""
import json
from datetime import datetime
from flask import Blueprint, jsonify, request, g, Response, current_app
from itcj.core.utils.decorators import api_auth_required
from itcj.core.services.notification_service import NotificationService
from itcj.core.extensions import db
from itcj.core.utils.redis_conn import get_redis


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


@api_notifications_bp.get("/stream")
@api_auth_required
def notification_stream():
    """
    SSE endpoint para recibir notificaciones en tiempo real.

    Headers:
        Authorization: Bearer <jwt_token> (o cookie itcj_token)

    SSE Events:
        - connected: {"type": "connected", "user_id": int, "counts": {...}}
        - notification: {...notification_data...}
        - heartbeat: {"type": "heartbeat", "timestamp": iso_string}

    Returns:
        200: text/event-stream
    """
    user_id = _get_current_user_id()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    # Capturar referencia al app ANTES de crear el generador
    app = current_app._get_current_object()

    def event_stream():
        """Generador compatible con Eventlet para streaming SSE"""
        redis_client = None
        pubsub = None

        try:
            with app.app_context():
                redis_client = get_redis()
                channel = f"notify:user:{user_id}"
                pubsub = redis_client.pubsub()
                pubsub.subscribe(channel)

                # Enviar evento de conexión con conteos iniciales
                counts = NotificationService.get_unread_counts_by_app(user_id)
                total_unread = sum(counts.values())

                connection_data = {
                    'type': 'connected',
                    'user_id': user_id,
                    'counts': counts,
                    'total_unread': total_unread,
                    'timestamp': datetime.now().isoformat()
                }
                yield f"data: {json.dumps(connection_data)}\n\n"

            # Heartbeat counter
            message_count = 0

            # Escuchar mensajes desde Redis (ya no necesita DB, solo Redis)
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        # Nueva notificación - verificar que sea JSON válido
                        data = message['data']
                        if isinstance(data, bytes):
                            data = data.decode('utf-8')
                        
                        # Validar que sea JSON válido antes de enviarlo
                        json.loads(data)  # Solo para validar
                        yield f"data: {data}\n\n"
                        message_count += 1
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        with app.app_context():
                            app.logger.error(f"Invalid message data in SSE for user {user_id}: {e}")
                        # Enviar un mensaje de error genérico al cliente
                        error_notification = {
                            'type': 'error',
                            'title': 'Error de notificación',
                            'body': 'Se recibió una notificación inválida',
                            'timestamp': datetime.now().isoformat()
                        }
                        yield f"data: {json.dumps(error_notification)}\n\n"

                # Heartbeat cada 30 mensajes o si es subscribe/psubscribe
                if message_count % 30 == 0 or message['type'] in ['subscribe', 'psubscribe']:
                    heartbeat = {
                        'type': 'heartbeat',
                        'timestamp': datetime.now().isoformat()
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"

        except GeneratorExit:
            # Cliente desconectó
            with app.app_context():
                app.logger.info(f"SSE client disconnected: user {user_id}")

        except Exception as e:
            # Usar el logger capturado con contexto
            with app.app_context():
                app.logger.error(f"Error in SSE stream for user {user_id}: {e}", exc_info=True)
            
            error_data = {
                'type': 'error',
                'message': 'Stream error occurred',
                'timestamp': datetime.now().isoformat()
            }
            yield f"data: {json.dumps(error_data)}\n\n"

        finally:
            # Cleanup
            if pubsub:
                try:
                    pubsub.unsubscribe()
                    pubsub.close()
                except Exception:
                    pass

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Nginx support
            'Connection': 'keep-alive'
        }
    )


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

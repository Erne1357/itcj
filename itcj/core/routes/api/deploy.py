# itcj/core/routes/api/deploy.py
"""
Endpoint para recibir notificaciones de deploy y emitir eventos WebSocket
a los clientes conectados.

Este endpoint es llamado por el script de deploy cuando hay cambios en
archivos estaticos, permitiendo notificar solo a los usuarios afectados.
"""
from flask import Blueprint, request, jsonify, current_app

api_deploy_bp = Blueprint('api_deploy', __name__)


@api_deploy_bp.post('/static-update')
def notify_static_update():
    """Recibe la lista de archivos estaticos que cambiaron y emite
    un evento SocketIO a todos los clientes conectados.

    Request body:
        {
            "changed": ["app/ruta/archivo.js", ...],
            "removed": ["app/ruta/viejo.css", ...],  # opcional
            "deploy_key": "secreto"  # opcional, para autenticacion
        }

    Response:
        {"ok": true, "notified": N}  # N = cantidad de archivos notificados

    El evento WebSocket emitido es:
        namespace: /notify
        event: static_update
        data: {"changed": [...], "removed": [...]}
    """
    # Validar que viene del deploy script (no de un usuario random)
    deploy_key = current_app.config.get('DEPLOY_SECRET', '')
    if deploy_key:
        provided_key = request.json.get('deploy_key', '') if request.json else ''
        if provided_key != deploy_key:
            return jsonify({'error': 'unauthorized', 'message': 'Invalid deploy key'}), 403

    data = request.json or {}
    changed = data.get('changed', [])
    removed = data.get('removed', [])

    if not changed and not removed:
        return jsonify({'ok': True, 'notified': 0, 'message': 'No changes to notify'})

    # Emitir via SocketIO al namespace /notify
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit('static_update', {
            'changed': changed,
            'removed': removed
        }, namespace='/notify')

        current_app.logger.info(
            f"Deploy notification sent: {len(changed)} changed, {len(removed)} removed"
        )

        return jsonify({
            'ok': True,
            'notified': len(changed) + len(removed),
            'changed': len(changed),
            'removed': len(removed)
        })

    current_app.logger.warning("SocketIO not available, notification not sent")
    return jsonify({
        'ok': False,
        'error': 'socketio_unavailable',
        'message': 'WebSocket server not available'
    }), 503

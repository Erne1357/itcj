# sockets/notifications.py
from flask import g, request
from flask_socketio import emit, join_room
from ..utils.socket_auth import current_user_from_environ
from ...apps.agendatec.models import db

NAMESPACE = "/notify"

def _user_room(uid: int) -> str:
    return f"user:{uid}:notify"

def register_notification_events(socketio):
    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        user = current_user_from_environ(request.environ)
        if not user:
            return False
        g.current_user = user
        uid = int(user["sub"])
        join_room(_user_room(uid))
        emit("hello", {"msg": "WS /notify conectado", "uid": uid})

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect(*args, **kwargs):
        try:
            db.session.remove()
        except Exception:
            pass

# Emisor
def push_notification(socketio, user_id: int, payload: dict):
    socketio.emit("notify", payload, to=_user_room(int(user_id)), namespace=NAMESPACE)

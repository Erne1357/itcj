# sockets/system.py
"""
Namespace /system — rastreo de usuarios activos en tiempo real.

Estrategia:
- Redis SET  `ws:uids:student`  → user_ids de estudiantes con al menos 1 SID activo
- Redis SET  `ws:uids:admin`    → user_ids de staff/admin con al menos 1 SID activo
- Redis HASH `ws:sid_map`       → SID → "user_id:type" (para saber qué limpiar en disconnect)
- Redis HASH `ws:uid_refcount`  → user_id → cantidad de SIDs activos (para saber cuándo sacar del SET)

Los conteos se obtienen con SCARD (O(1)), no hay que iterar ni parsear JSON.
"""
from flask import g, request, current_app
from flask_socketio import emit, join_room
from itcj.core.utils.socket_auth import current_user_from_environ
from itcj.core.utils.redis_conn import get_redis

NAMESPACE = "/system"
ADMIN_ROOM = "system:admins"

# Redis keys
SID_MAP_KEY = "ws:sid_map"          # Hash: SID -> "uid:type"
UID_REFCOUNT_KEY = "ws:uid_refcount"  # Hash: uid -> ref count (str)
STUDENTS_KEY = "ws:uids:student"    # Set of user_ids
ADMINS_KEY = "ws:uids:admin"        # Set of user_ids


def _user_type(user_data):
    """Devuelve 'student' si tiene control_number, sino 'admin'."""
    return "student" if user_data.get("cn") else "admin"


def _set_key_for(utype):
    return STUDENTS_KEY if utype == "student" else ADMINS_KEY


def _get_counts():
    """Conteos O(1) con SCARD."""
    r = get_redis()
    pipe = r.pipeline(transaction=False)
    pipe.scard(STUDENTS_KEY)
    pipe.scard(ADMINS_KEY)
    students, admins = pipe.execute()
    return {"total": students + admins, "students": students, "admins": admins}


def _broadcast_counts(socketio):
    """Emite conteos actualizados a todos los admins en /system."""
    counts = _get_counts()
    socketio.emit("active_users", counts, to=ADMIN_ROOM, namespace=NAMESPACE)


# ---------- Llamados desde connect/disconnect de TODOS los namespaces ----------

def track_connect(socketio, sid, user_data):
    """Registra una sesión activa en Redis."""
    try:
        r = get_redis()
        uid = str(user_data.get("sub"))
        utype = _user_type(user_data)

        # Guardar mapeo SID -> uid:type
        r.hset(SID_MAP_KEY, sid, f"{uid}:{utype}")

        # Incrementar refcount; si es 1, es un usuario nuevo → agregar al SET
        new_count = r.hincrby(UID_REFCOUNT_KEY, uid, 1)
        if new_count == 1:
            r.sadd(_set_key_for(utype), uid)
            _broadcast_counts(socketio)
    except Exception as e:
        current_app.logger.error(f"system.track_connect error: {e}")


def track_disconnect(socketio, sid):
    """Elimina una sesión activa de Redis."""
    try:
        r = get_redis()

        # Leer y eliminar el mapeo del SID
        mapping = r.hget(SID_MAP_KEY, sid)
        if not mapping:
            return
        r.hdel(SID_MAP_KEY, sid)

        uid, utype = mapping.rsplit(":", 1)

        # Decrementar refcount; si llega a 0, el usuario ya no tiene SIDs → sacar del SET
        new_count = r.hincrby(UID_REFCOUNT_KEY, uid, -1)
        if new_count <= 0:
            r.hdel(UID_REFCOUNT_KEY, uid)
            r.srem(_set_key_for(utype), uid)
            _broadcast_counts(socketio)
    except Exception as e:
        current_app.logger.error(f"system.track_disconnect error: {e}")


# ---------- Namespace /system (solo admins) ----------

def register_system_events(socketio):

    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        user = current_user_from_environ(request.environ)
        if not user:
            return False
        # Solo admins pueden suscribirse a este namespace
        role = user.get("role")
        is_admin = (role == "admin") if isinstance(role, str) else ("admin" in (role or []))
        if not is_admin:
            return False
        g.current_user = user
        join_room(ADMIN_ROOM)
        # Registrar al admin como usuario activo
        track_connect(socketio, request.sid, user)
        # Enviar conteos actuales al admin que se conecta
        emit("active_users", _get_counts())

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect(*args, **kwargs):
        try:
            track_disconnect(socketio, request.sid)
        except Exception:
            pass

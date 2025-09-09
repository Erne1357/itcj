# sockets/slots.py
from datetime import timedelta
from flask import g, request, current_app
from flask_socketio import emit, join_room, leave_room
from itcj.apps.agendatec.models import db, TimeSlot
from itcj.core.utils.redis_conn import get_redis, get_hold_ttl
from itcj.core.utils.socket_auth import current_user_from_environ

NAMESPACE = "/slots"

def _room_for_day(day_str: str) -> str:
    return f"day:{day_str}"

def _slot_hold_key(slot_id: int) -> str:
    return f"slot:{slot_id}:hold"

def _sid_hold_key(sid : str) -> str:
    return f"sid:{sid}:hold"

def _get_slot_day(slot_id: int) -> str | None:
    s = db.session.query(TimeSlot).get(int(slot_id))
    return None if not s else str(s.day)

def _slots_snapshot_for_day(day_str: str):
    r = get_redis()
    rows = (db.session.query(TimeSlot.id, TimeSlot.is_booked)
            .filter(TimeSlot.day == day_str).all())
    booked = [sid for sid, b in rows if b]

    held = []
    pipe = r.pipeline()
    for sid, _ in rows:
        pipe.ttl(_slot_hold_key(sid))
    ttls = pipe.execute()
    for (sid, _), ttl in zip(rows, ttls):
        if isinstance(ttl, int) and ttl > 0:
            held.append({"slot_id": sid, "ttl": ttl})

    return {"booked": booked, "held": held}

def register_slot_events(socketio):
    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        user = current_user_from_environ(request.environ)
        if not user:
            return False  # rechazar
        g.current_user = user  # disponible en este contexto
        emit("hello", {"msg": f"Conectado como {user.get('name') or user.get('cn')}"})

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect(*args, **kwargs):
        try:
            # ... tu limpieza, por ejemplo:
            db.session.remove()
        except Exception:
            pass

    @socketio.on("join_day", namespace=NAMESPACE)
    def on_join_day(data):
        day = (data or {}).get("day")
        if not day:
            emit("error", {"error": "invalid_day"})
            return
        join_room(_room_for_day(day))
        snap = _slots_snapshot_for_day(day)
        emit("joined_day", {"day": day})
        emit("slots_snapshot", {"day": day, **snap})

    @socketio.on("leave_day", namespace=NAMESPACE)
    def on_leave_day(data):
        day = (data or {}).get("day")
        if not day:
            emit("error", {"error": "invalid_day"})
            return
        leave_room(_room_for_day(day))
        emit("left_day", {"day": day})

    @socketio.on("hold_slot", namespace=NAMESPACE)
    def on_hold_slot(data):
        r = get_redis()
        slot_id = int((data or {}).get("slot_id") or 0)
        if slot_id <= 0:
            emit("hold_slot_ack", {"ok": False, "error": "invalid_slot"})
            return

        day = _get_slot_day(slot_id)
        if not day:
            emit("hold_slot_ack", {"ok": False, "error": "slot_not_found"})
            return

        ttl = get_hold_ttl()
        key = _slot_hold_key(slot_id)
        sid = request.sid
        sid_key = _sid_hold_key(sid)

        # 1) Si este socket ya sostiene OTRO slot, libéralo primero (lado servidor)
        prev = r.get(sid_key)
        if prev and str(prev) != str(slot_id):
            prev_key = _slot_hold_key(int(prev))
            # libera solo si ese hold lo tiene este mismo SID
            if r.get(prev_key) == sid:
                r.delete(prev_key)
                emit("slot_released", {"slot_id": int(prev), "day": _get_slot_day(int(prev))},
                    to=_room_for_day(_get_slot_day(int(prev)) or ""), namespace=NAMESPACE)

        # 2) Intento atómico: crear hold si no existe
        created = r.set(key, sid, ex=ttl, nx=True)
        if created:
            r.set(sid_key, slot_id, ex=ttl)
            emit("hold_slot_ack", {"ok": True, "slot_id": slot_id, "ttl": ttl})
            emit("slot_held", {"slot_id": slot_id, "day": day, "ttl": ttl},
                to=_room_for_day(day), namespace=NAMESPACE, include_self=True)
            return

        # 3) Ya existe: ¿es mío? -> renovar TTL; si no, error
        current = r.get(key)
        if current == sid:
            r.expire(key, ttl)
            r.set(sid_key, slot_id, ex=ttl)
            emit("hold_slot_ack", {"ok": True, "slot_id": slot_id, "ttl": ttl, "renewed": True})
            emit("slot_held", {"slot_id": slot_id, "day": day, "ttl": ttl},
                to=_room_for_day(day), namespace=NAMESPACE)
        else:
            emit("hold_slot_ack", {"ok": False, "error": "already_held"})

    @socketio.on("release_hold", namespace=NAMESPACE)
    def on_release_hold(data):
        r = get_redis()
        slot_id = int((data or {}).get("slot_id") or 0)
        if slot_id <= 0:
            emit("release_hold_ack", {"ok": False, "error": "invalid_slot"})
            return

        day = _get_slot_day(slot_id)
        if not day:
            emit("release_hold_ack", {"ok": False, "error": "slot_not_found"})
            return

        key = _slot_hold_key(slot_id)
        sid = request.sid
        sid_key = _sid_hold_key(sid)

        if r.get(key) == sid:
            r.delete(key)
            # si el índice de este SID apunta a este slot, bórralo también
            if r.get(sid_key) == str(slot_id):
                r.delete(sid_key)
            emit("release_hold_ack", {"ok": True, "slot_id": slot_id})
            emit("slot_released", {"slot_id": slot_id, "day": day},
                to=_room_for_day(day), namespace=NAMESPACE)
        else:
            emit("release_hold_ack", {"ok": False, "error": "not_holder"})
    socketio
"""
WebSocket namespace /slots para reserva de horarios en AgendaTec.

Migración de itcj/core/sockets/slots.py (Flask-SocketIO sync)
a python-socketio ASGI (async nativo).

Todas las operaciones de DB (SQLAlchemy) y Redis síncronas
se ejecutan con asyncio.to_thread() para no bloquear el event loop.
"""
import asyncio
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.slots")

NAMESPACE = "/slots"


# ==================== Room / Key Helpers ====================

def _room_for_day(day_str: str) -> str:
    return f"day:{day_str}"


def _slot_hold_key(slot_id: int) -> str:
    return f"slot:{slot_id}:hold"


def _sid_hold_key(sid: str) -> str:
    return f"sid:{sid}:hold"


# ==================== Sync DB/Redis Helpers (para thread pool) ====================

def _get_slot_day(slot_id: int):
    """Obtiene el día de un TimeSlot (sync, corre en thread pool)."""
    from itcj2.apps.agendatec.models import TimeSlot
    from itcj2.database import SessionLocal

    with SessionLocal() as s:
        row = s.get(TimeSlot, int(slot_id))
        return None if not row else str(row.day)


def _slots_snapshot_for_day(day_str: str) -> dict:
    """
    Genera snapshot de estado de slots para un día dado (sync, thread pool).
    Retorna {booked: [...], held: [{slot_id, ttl}, ...]}.
    """
    from itcj2.apps.agendatec.models import TimeSlot
    from itcj2.core.utils.redis_conn import get_redis
    from itcj2.database import SessionLocal

    r = get_redis()
    with SessionLocal() as s:
        rows = (
            s.query(TimeSlot.id, TimeSlot.is_booked)
            .filter(TimeSlot.day == day_str)
            .all()
        )

    booked = [slot_id for slot_id, is_booked in rows if is_booked]

    pipe = r.pipeline()
    for slot_id, _ in rows:
        pipe.ttl(_slot_hold_key(slot_id))
    ttls = pipe.execute()

    held = []
    for (slot_id, _), ttl in zip(rows, ttls):
        if isinstance(ttl, int) and ttl > 0:
            held.append({"slot_id": slot_id, "ttl": ttl})

    return {"booked": booked, "held": held}


def _try_hold_slot(slot_id: int, sid: str) -> dict:
    """
    Intenta crear/renovar un hold en Redis para el slot (sync, thread pool).

    Returns dict:
        ok=True  → {ok, slot_id, ttl, day, renewed, released_slot, released_day}
        ok=False → {ok, error}
    """
    from itcj2.core.utils.redis_conn import get_redis, get_hold_ttl

    r = get_redis()
    day = _get_slot_day(slot_id)
    if not day:
        return {"ok": False, "error": "slot_not_found"}

    ttl = get_hold_ttl()
    key = _slot_hold_key(slot_id)
    sid_key = _sid_hold_key(sid)

    released_slot = None
    released_day = None

    # Si este socket ya sostiene OTRO slot, liberarlo primero
    prev = r.get(sid_key)
    if prev and prev != str(slot_id):
        prev_id = int(prev)
        prev_key = _slot_hold_key(prev_id)
        if r.get(prev_key) == sid:
            r.delete(prev_key)
            released_slot = prev_id
            released_day = _get_slot_day(prev_id)

    # Intento atómico: crear hold si no existe
    created = r.set(key, sid, ex=ttl, nx=True)
    if created:
        r.set(sid_key, str(slot_id), ex=ttl)
        return {
            "ok": True,
            "slot_id": slot_id,
            "ttl": ttl,
            "day": day,
            "renewed": False,
            "released_slot": released_slot,
            "released_day": released_day,
        }

    # ¿Es mío? → renovar TTL
    current = r.get(key)
    if current == sid:
        r.expire(key, ttl)
        r.set(sid_key, str(slot_id), ex=ttl)
        return {
            "ok": True,
            "slot_id": slot_id,
            "ttl": ttl,
            "day": day,
            "renewed": True,
            "released_slot": released_slot,
            "released_day": released_day,
        }

    return {"ok": False, "error": "already_held"}


def _release_hold(slot_id: int, sid: str) -> dict:
    """Libera un hold en Redis (sync, corre en thread pool)."""
    from itcj2.core.utils.redis_conn import get_redis

    r = get_redis()
    day = _get_slot_day(slot_id)
    if not day:
        return {"ok": False, "error": "slot_not_found"}

    key = _slot_hold_key(slot_id)
    sid_key = _sid_hold_key(sid)

    if r.get(key) == sid:
        r.delete(key)
        if r.get(sid_key) == str(slot_id):
            r.delete(sid_key)
        return {"ok": True, "slot_id": slot_id, "day": day}

    return {"ok": False, "error": "not_holder"}


# ==================== Event Registration ====================

def register_slot_namespace(sio_server):
    """Registra los event handlers del namespace /slots."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)
        name = user.get("name") or user.get("cn")
        await sio_server.emit(
            "hello", {"msg": f"Conectado como {name}"}, to=sid, namespace=NAMESPACE
        )

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        pass

    @sio_server.on("join_day", namespace=NAMESPACE)
    async def on_join_day(sid, data):
        day = (data or {}).get("day")
        if not day:
            await sio_server.emit("error", {"error": "invalid_day"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _room_for_day(day), namespace=NAMESPACE)
        snap = await asyncio.to_thread(_slots_snapshot_for_day, day)
        await sio_server.emit("joined_day", {"day": day}, to=sid, namespace=NAMESPACE)
        await sio_server.emit("slots_snapshot", {"day": day, **snap}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_day", namespace=NAMESPACE)
    async def on_leave_day(sid, data):
        day = (data or {}).get("day")
        if not day:
            await sio_server.emit("error", {"error": "invalid_day"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.leave_room(sid, _room_for_day(day), namespace=NAMESPACE)
        await sio_server.emit("left_day", {"day": day}, to=sid, namespace=NAMESPACE)

    @sio_server.on("hold_slot", namespace=NAMESPACE)
    async def on_hold_slot(sid, data):
        try:
            slot_id = int((data or {}).get("slot_id") or 0)
        except (TypeError, ValueError):
            await sio_server.emit(
                "hold_slot_ack", {"ok": False, "error": "invalid_slot"}, to=sid, namespace=NAMESPACE
            )
            return

        if slot_id <= 0:
            await sio_server.emit(
                "hold_slot_ack", {"ok": False, "error": "invalid_slot"}, to=sid, namespace=NAMESPACE
            )
            return

        result = await asyncio.to_thread(_try_hold_slot, slot_id, sid)

        if not result["ok"]:
            await sio_server.emit("hold_slot_ack", result, to=sid, namespace=NAMESPACE)
            return

        day = result["day"]
        ttl = result["ttl"]

        # Notificar slot previo liberado (si hubo sustitución)
        if result.get("released_slot") and result.get("released_day"):
            await sio_server.emit(
                "slot_released",
                {"slot_id": result["released_slot"], "day": result["released_day"]},
                to=_room_for_day(result["released_day"]),
                namespace=NAMESPACE,
            )

        await sio_server.emit(
            "hold_slot_ack",
            {"ok": True, "slot_id": slot_id, "ttl": ttl, "renewed": result.get("renewed", False)},
            to=sid,
            namespace=NAMESPACE,
        )
        await sio_server.emit(
            "slot_held",
            {"slot_id": slot_id, "day": day, "ttl": ttl},
            to=_room_for_day(day),
            namespace=NAMESPACE,
        )

    @sio_server.on("release_hold", namespace=NAMESPACE)
    async def on_release_hold(sid, data):
        try:
            slot_id = int((data or {}).get("slot_id") or 0)
        except (TypeError, ValueError):
            await sio_server.emit(
                "release_hold_ack", {"ok": False, "error": "invalid_slot"}, to=sid, namespace=NAMESPACE
            )
            return

        if slot_id <= 0:
            await sio_server.emit(
                "release_hold_ack", {"ok": False, "error": "invalid_slot"}, to=sid, namespace=NAMESPACE
            )
            return

        result = await asyncio.to_thread(_release_hold, slot_id, sid)

        if not result["ok"]:
            await sio_server.emit("release_hold_ack", result, to=sid, namespace=NAMESPACE)
            return

        day = result["day"]
        await sio_server.emit(
            "release_hold_ack", {"ok": True, "slot_id": slot_id}, to=sid, namespace=NAMESPACE
        )
        await sio_server.emit(
            "slot_released",
            {"slot_id": slot_id, "day": day},
            to=_room_for_day(day),
            namespace=NAMESPACE,
        )

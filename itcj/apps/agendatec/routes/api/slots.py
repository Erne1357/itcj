# routes/api/slots.py
from datetime import date
import json
from flask import Blueprint, request, jsonify, g
from sqlalchemy import and_
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
from itcj.core.utils.redis_conn import get_redis, get_hold_ttl
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.services import period_service

api_slots_bp = Blueprint("api_slots", __name__)

# NOTA: ALLOWED_DAYS eliminado - ahora se obtiene dinámicamente del período activo

# Convención de claves en Redis
def k_slot_hold(slot_id: int) -> str:
    return f"slot_hold:{slot_id}"

def k_user_hold(user_id: int) -> str:
    # Si prefieres permitir múltiples holds por usuario, suprime esta llave y solo usa la de slot.
    return f"user_hold:{user_id}"

# Por ahora: 1 hold por usuario a la vez (simple y práctico)
ENFORCE_SINGLE_HOLD_PER_USER = True

# --------------------------------------------------------------------
# POST /slots/hold  -> crea un hold temporal (TTL) sobre un slot libre
# --------------------------------------------------------------------
@api_slots_bp.post("/hold")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def hold_slot():
    rds = get_redis()
    ttl = get_hold_ttl()
    uid = int(g.current_user["sub"])

    data = request.get_json(silent=True) or {}
    try:
        slot_id = int(data.get("slot_id"))
    except Exception:
        return jsonify({"error": "invalid_payload"}), 400

    # Validar slot en DB
    slot = db.session.query(TimeSlot).get(slot_id)
    if not slot:
        return jsonify({"error":"slot_not_found"}), 404
    if slot.is_booked:
        return jsonify({"error":"slot_unavailable"}), 409

    # Validar que el día esté habilitado en el período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))
    if slot.day not in enabled_days:
        return jsonify({
            "error": "day_not_enabled",
            "enabled_days": [d.isoformat() for d in sorted(enabled_days)]
        }), 400

    skey = k_slot_hold(slot_id)
    ukey = k_user_hold(uid)

    pipe = rds.pipeline()
    while True:
        try:
            # Observa ambas llaves para control optimista
            watch_keys = [skey]
            if ENFORCE_SINGLE_HOLD_PER_USER:
                watch_keys.append(ukey)
            pipe.watch(*watch_keys)

            slot_val = pipe.get(skey)
            if slot_val:
                # Ya está en hold por alguien
                try:
                    info = json.loads(slot_val)
                except Exception:
                    info = {"user_id": None}
                owner = info.get("user_id")
                ttl_left = rds.ttl(skey)
                if owner == uid:
                    # Es mío: re-extiende el TTL
                    pipe.multi()
                    pipe.set(skey, slot_val, ex=ttl)
                    if ENFORCE_SINGLE_HOLD_PER_USER:
                        pipe.set(ukey, str(slot_id), ex=ttl)
                    pipe.execute()
                    return jsonify({"ok": True, "slot_id": slot_id, "owner": uid, "ttl": ttl})
                else:
                    pipe.reset()
                    return jsonify({"error":"slot_on_hold", "held_by": owner, "ttl": ttl_left}), 409

            # Opcional: un solo hold por usuario
            if ENFORCE_SINGLE_HOLD_PER_USER:
                current_user_hold = pipe.get(ukey)
                if current_user_hold and int(current_user_hold) != slot_id:
                    ttl_left = rds.ttl(ukey)
                    pipe.reset()
                    return jsonify({"error":"user_has_other_hold","slot_id": int(current_user_hold), "ttl": ttl_left}), 409

            # Crear hold
            payload = json.dumps({
                "user_id": uid,
                "slot_id": slot_id,
                "day": str(slot.day),
                "coordinator_id": slot.coordinator_id
            })

            pipe.multi()
            pipe.set(skey, payload, ex=ttl)
            if ENFORCE_SINGLE_HOLD_PER_USER:
                pipe.set(ukey, str(slot_id), ex=ttl)
            pipe.execute()

            return jsonify({"ok": True, "slot_id": slot_id, "owner": uid, "ttl": ttl})

        except redis.WatchError:  # type: ignore[name-defined]
            # Alguien cambió llaves; reintentamos
            continue
        finally:
            pipe.reset()

# --------------------------------------------------------------------
# POST /slots/release -> libera el hold del usuario sobre un slot
# --------------------------------------------------------------------
@api_slots_bp.post("/release")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def release_slot():
    rds = get_redis()
    uid = int(g.current_user["sub"])

    data = request.get_json(silent=True) or {}
    try:
        slot_id = int(data.get("slot_id"))
    except Exception:
        return jsonify({"error": "invalid_payload"}), 400

    skey = k_slot_hold(slot_id)
    ukey = k_user_hold(uid)

    val = rds.get(skey)
    if not val:
        # No hay hold en ese slot; idempotente
        # También limpia el user_hold si apunta al slot
        cur = rds.get(ukey)
        if cur and cur == str(slot_id):
            rds.delete(ukey)
        return jsonify({"ok": True, "released": False, "reason": "no_hold_found"})

    try:
        info = json.loads(val)
    except Exception:
        info = {"user_id": None}

    if info.get("user_id") != uid:
        return jsonify({"error": "not_owner"}), 403

    # Borra hold de slot y user
    pipe = rds.pipeline()
    pipe.delete(skey)
    pipe.delete(ukey)
    pipe.execute()

    return jsonify({"ok": True, "released": True})

# --------------------------------------------------------------------
# GET /slots/<slot_id>/status  -> estado puntual de un slot
# --------------------------------------------------------------------
@api_slots_bp.get("/<int:slot_id>/status")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.slots.api.read"])
def slot_status(slot_id: int):
    rds = get_redis()
    slot = db.session.query(TimeSlot).get(slot_id)
    if not slot:
        return jsonify({"error":"slot_not_found"}), 404

    skey = k_slot_hold(slot_id)
    val = rds.get(skey)
    if slot.is_booked:
        return jsonify({"slot_id": slot_id, "status": "BOOKED"})
    if val:
        try:
            info = json.loads(val)
        except Exception:
            info = {"user_id": None}
        ttl_left = rds.ttl(skey)
        return jsonify({
            "slot_id": slot_id,
            "status": "HOLD",
            "owner": info.get("user_id"),
            "ttl": ttl_left
        })
    return jsonify({"slot_id": slot_id, "status": "FREE"})

# --------------------------------------------------------------------
# (Opcional admin/coord) listar holds activos actuales
# GET /slots/holds
# --------------------------------------------------------------------
@api_slots_bp.get("/holds")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.slots.api.read"])
def list_holds():
    """
    Devuelve lista de holds actuales (solo claves activas).
    Tip: útil para tablero del coordinador o para debug.
    """
    rds = get_redis()
    # SCAN para no bloquear Redis (en ambientes grandes)
    cursor = 0
    keys = []
    pattern = "slot_hold:*"
    while True:
        cursor, chunk = rds.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(chunk)
        if cursor == 0:
            break

    items = []
    for k in keys:
        v = rds.get(k)
        if not v: 
            continue
        try:
            info = json.loads(v)
        except Exception:
            continue
        ttl = rds.ttl(k)
        items.append({
            "slot_id": info.get("slot_id"),
            "user_id": info.get("user_id"),
            "coordinator_id": info.get("coordinator_id"),
            "day": info.get("day"),
            "ttl": ttl
        })
    return jsonify({"items": items})

"""
Slots API v2 — Holds temporales sobre slots con Redis.
Fuente: itcj/apps/agendatec/routes/api/slots.py
"""
import json
import logging

from fastapi import APIRouter, HTTPException

import redis as _redis

from itcj2.apps.agendatec.schemas.slots import HoldSlotBody, ReleaseSlotBody
from itcj2.dependencies import DbSession, require_perms, require_roles, CurrentUser

from itcj2.apps.agendatec.config.constants import (
    ENFORCE_SINGLE_HOLD_PER_USER,
    REDIS_SLOT_HOLD_PREFIX,
    REDIS_USER_HOLD_PREFIX,
)
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.services import period_service
from itcj2.core.utils.redis_conn import get_hold_ttl, get_redis

router = APIRouter(tags=["agendatec-slots"])
logger = logging.getLogger(__name__)


def _k_slot(slot_id: int) -> str:
    return f"{REDIS_SLOT_HOLD_PREFIX}{slot_id}"


def _k_user(user_id: int) -> str:
    return f"{REDIS_USER_HOLD_PREFIX}{user_id}"


# ==================== POST /hold ====================

@router.post("/hold")
def hold_slot(
    body: HoldSlotBody,
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """Crea un hold temporal (TTL) sobre un slot libre."""
    rds = get_redis()
    ttl = get_hold_ttl()
    uid = int(user["sub"])
    slot_id = body.slot_id

    slot = db.query(TimeSlot).get(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="slot_not_found")
    if slot.is_booked:
        raise HTTPException(status_code=409, detail="slot_unavailable")

    active_period = period_service.get_active_period()
    if not active_period:
        raise HTTPException(status_code=503, detail="no_active_period")

    enabled_days = set(period_service.get_enabled_days(active_period.id))
    if slot.day not in enabled_days:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "day_not_enabled",
                "enabled_days": [d.isoformat() for d in sorted(enabled_days)],
            },
        )

    skey = _k_slot(slot_id)
    ukey = _k_user(uid)

    pipe = rds.pipeline()
    while True:
        try:
            watch_keys = [skey]
            if ENFORCE_SINGLE_HOLD_PER_USER:
                watch_keys.append(ukey)
            pipe.watch(*watch_keys)

            slot_val = pipe.get(skey)
            if slot_val:
                try:
                    info = json.loads(slot_val)
                except Exception:
                    info = {"user_id": None}
                owner = info.get("user_id")
                ttl_left = rds.ttl(skey)
                if owner == uid:
                    pipe.multi()
                    pipe.set(skey, slot_val, ex=ttl)
                    if ENFORCE_SINGLE_HOLD_PER_USER:
                        pipe.set(ukey, str(slot_id), ex=ttl)
                    pipe.execute()
                    return {"ok": True, "slot_id": slot_id, "owner": uid, "ttl": ttl}
                else:
                    pipe.reset()
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "slot_on_hold", "held_by": owner, "ttl": ttl_left},
                    )

            if ENFORCE_SINGLE_HOLD_PER_USER:
                current_user_hold = pipe.get(ukey)
                if current_user_hold and int(current_user_hold) != slot_id:
                    ttl_left = rds.ttl(ukey)
                    pipe.reset()
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "user_has_other_hold",
                            "slot_id": int(current_user_hold),
                            "ttl": ttl_left,
                        },
                    )

            payload = json.dumps({
                "user_id": uid,
                "slot_id": slot_id,
                "day": str(slot.day),
                "coordinator_id": slot.coordinator_id,
            })

            pipe.multi()
            pipe.set(skey, payload, ex=ttl)
            if ENFORCE_SINGLE_HOLD_PER_USER:
                pipe.set(ukey, str(slot_id), ex=ttl)
            pipe.execute()

            return {"ok": True, "slot_id": slot_id, "owner": uid, "ttl": ttl}

        except _redis.WatchError:
            continue
        finally:
            pipe.reset()


# ==================== POST /release ====================

@router.post("/release")
def release_slot(
    body: ReleaseSlotBody,
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """Libera el hold del usuario sobre un slot."""
    rds = get_redis()
    uid = int(user["sub"])
    slot_id = body.slot_id

    skey = _k_slot(slot_id)
    ukey = _k_user(uid)

    val = rds.get(skey)
    if not val:
        cur = rds.get(ukey)
        if cur and cur == str(slot_id):
            rds.delete(ukey)
        return {"ok": True, "released": False, "reason": "no_hold_found"}

    try:
        info = json.loads(val)
    except Exception:
        info = {"user_id": None}

    if info.get("user_id") != uid:
        raise HTTPException(status_code=403, detail="not_owner")

    pipe = rds.pipeline()
    pipe.delete(skey)
    pipe.delete(ukey)
    pipe.execute()

    return {"ok": True, "released": True}


# ==================== GET /<slot_id>/status ====================

@router.get("/{slot_id}/status")
def slot_status(
    slot_id: int,
    user: dict = require_perms("agendatec", ["agendatec.slots.api.read"]),
    db: DbSession = None,
):
    """Consulta el estado puntual de un slot (FREE, HOLD, BOOKED)."""
    rds = get_redis()
    slot = db.query(TimeSlot).get(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="slot_not_found")

    skey = _k_slot(slot_id)
    val = rds.get(skey)

    if slot.is_booked:
        return {"slot_id": slot_id, "status": "BOOKED"}
    if val:
        try:
            info = json.loads(val)
        except Exception:
            info = {"user_id": None}
        ttl_left = rds.ttl(skey)
        return {
            "slot_id": slot_id,
            "status": "HOLD",
            "owner": info.get("user_id"),
            "ttl": ttl_left,
        }
    return {"slot_id": slot_id, "status": "FREE"}


# ==================== GET /holds ====================

@router.get("/holds")
def list_holds(
    user: dict = require_perms("agendatec", ["agendatec.slots.api.read"]),
    db: DbSession = None,
):
    """Lista holds activos (para coordinadores/debug)."""
    rds = get_redis()
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
            "ttl": ttl,
        })
    return {"items": items}

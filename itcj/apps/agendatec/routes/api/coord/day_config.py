# routes/api/coord/day_config.py
"""
Endpoints para configuración de días y slots.

Incluye:
- get_day_config: Obtener configuración de un día
- set_day_config: Configurar ventana de disponibilidad
- delete_day_range: Eliminar rango de slots
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.services import period_service
from itcj.core.utils.decorators import api_app_required, api_auth_required

from .helpers import get_current_coordinator_id, split_or_delete_windows

coord_day_config_bp = Blueprint("coord_day_config", __name__)


@coord_day_config_bp.get("/day-config")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.slots.api.read"])
def get_day_config():
    """
    Obtiene la configuración de ventanas de disponibilidad para un día.

    Query params:
        day: Fecha en formato YYYY-MM-DD

    Returns:
        JSON con day e items (lista de ventanas)
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    day_s = (request.args.get("day") or "").strip()
    try:
        d = datetime.strptime(day_s, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid_day_format"}), 400

    # Validar que el día esté habilitado en el período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))
    if d not in enabled_days:
        return jsonify({"error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled_days)]}), 400

    wins = (
        db.session.query(AvailabilityWindow)
        .filter(AvailabilityWindow.coordinator_id == coord_id,
                AvailabilityWindow.day == d)
        .order_by(AvailabilityWindow.start_time.asc())
        .all()
    )
    items = [{
        "id": w.id,
        "day": str(w.day),
        "start": w.start_time.strftime("%H:%M"),
        "end": w.end_time.strftime("%H:%M"),
        "slot_minutes": w.slot_minutes
    } for w in wins]

    return jsonify({"day": str(d), "items": items})


@coord_day_config_bp.post("/day-config")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.slots.api.create"])
def set_day_config():
    """
    Agrega/actualiza una ventana de disponibilidad para un día.

    Body JSON:
        day: Fecha en formato YYYY-MM-DD
        start: Hora de inicio (HH:MM)
        end: Hora de fin (HH:MM)
        slot_minutes: Duración de cada slot (5,10,15,20,30,60)

    Returns:
        JSON con ok, windows_deleted, slots_deleted y slots_created
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    data = request.get_json(silent=True) or {}
    day_s = (data.get("day") or "").strip()
    start_s = (data.get("start") or "").strip()
    end_s = (data.get("end") or "").strip()
    slot_minutes = int(data.get("slot_minutes", 10))
    socketio = current_app.extensions.get('socketio')

    # Validaciones de fecha/hora
    try:
        d = datetime.strptime(day_s, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid_day_format"}), 400

    # Validar que el día esté habilitado en el período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))
    if d not in enabled_days:
        return jsonify({"error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled_days)]}), 400

    now = datetime.now()
    try:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        start_t = datetime.strptime(f"{sh:02d}:{sm:02d}", "%H:%M").time()
        end_t = datetime.strptime(f"{eh:02d}:{em:02d}", "%H:%M").time()
    except Exception:
        return jsonify({"error": "invalid_time_format"}), 400

    slot_datetime = datetime.combine(d, start_t)
    if now > slot_datetime:
        return jsonify({"error": "slot_time_passed"}), 400

    if (end_t <= start_t) or (slot_minutes not in (5, 10, 15, 20, 30, 60)):
        return jsonify({"error": "invalid_time_range_or_slot_size"}), 400

    time_ge = start_t
    time_lt = end_t

    # Ver si hay RESERVAS en el rango
    overlap_booked_cnt = (
        db.session.query(TimeSlot.id)
        .filter(TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == d,
                TimeSlot.start_time >= time_ge,
                TimeSlot.start_time < time_lt,
                TimeSlot.is_booked == True)
        .count()
    )
    if overlap_booked_cnt > 0:
        return jsonify({
            "error": "overlap_booked_slots_exist",
            "booked_count": overlap_booked_cnt
        }), 409

    # Identificar ventanas que se SOLAPAN con la nueva
    overlapping_windows = (
        db.session.query(AvailabilityWindow)
        .filter(AvailabilityWindow.coordinator_id == coord_id,
                AvailabilityWindow.day == d,
                ~(
                    (AvailabilityWindow.end_time <= time_ge) |
                    (AvailabilityWindow.start_time >= time_lt)
                ))
        .all()
    )

    # Borrar SOLO slots no reservados dentro del rango nuevo
    slots_deleted = (
        db.session.query(TimeSlot)
        .filter(TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == d,
                TimeSlot.start_time >= time_ge,
                TimeSlot.start_time < time_lt,
                TimeSlot.is_booked == False)
        .delete(synchronize_session=False)
    )

    # Borrar ventanas que solapan
    wins_deleted = 0
    for w in overlapping_windows:
        db.session.delete(w)
        wins_deleted += 1

    # Crear la nueva ventana
    av = AvailabilityWindow(
        coordinator_id=coord_id,
        day=d,
        start_time=start_t,
        end_time=end_t,
        slot_minutes=slot_minutes
    )
    db.session.add(av)
    db.session.flush()

    # Generar slots
    created = 0
    step = timedelta(minutes=slot_minutes)
    cur_dt = datetime.combine(d, start_t)
    end_dt = datetime.combine(d, end_t)
    while (cur_dt + step) <= end_dt:
        db.session.add(TimeSlot(
            coordinator_id=coord_id,
            day=d,
            start_time=cur_dt.time(),
            end_time=(cur_dt + step).time(),
            is_booked=False
        ))
        created += 1
        cur_dt += step
    db.session.commit()

    try:
        socketio.emit("slots_window_changed", {"day": str(d)},
                      to=f"day:{str(d)}", namespace="/slots")
    except Exception:
        current_app.logger.exception("Failed to emit slots_window_changed")

    return jsonify({
        "ok": True,
        "windows_deleted": wins_deleted,
        "slots_deleted": slots_deleted,
        "slots_created": created
    })


@coord_day_config_bp.delete("/day-config")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.slots.api.delete"])
def delete_day_range():
    """
    Borra el rango [start, end) de un día.

    Body JSON:
        day: Fecha en formato YYYY-MM-DD
        start: Hora de inicio (HH:MM)
        end: Hora de fin (HH:MM)

    Returns:
        JSON con ok, day, slots_deleted, windows_deleted y windows_created
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    data = request.get_json(silent=True) or {}
    day_s = (data.get("day") or "").strip()
    start_s = (data.get("start") or "").strip()
    end_s = (data.get("end") or "").strip()
    socketio = current_app.extensions.get('socketio')

    # Validaciones de fecha/hora
    try:
        d = datetime.strptime(day_s, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid_day_format"}), 400

    # Validar que el día esté habilitado en el período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))
    if d not in enabled_days:
        return jsonify({"error": "day_not_allowed"}), 400

    today = date.today()
    if today >= d:
        return jsonify({"error": "cannot_modify_today_or_past"}), 400

    try:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        start_t = datetime.strptime(f"{sh:02d}:{sm:02d}", "%H:%M").time()
        end_t = datetime.strptime(f"{eh:02d}:{em:02d}", "%H:%M").time()
    except Exception:
        return jsonify({"error": "invalid_time_format"}), 400

    if end_t <= start_t:
        return jsonify({"error": "invalid_time_range"}), 400

    # ¿Hay reservados en el rango?
    overlap_booked_cnt = (
        db.session.query(TimeSlot.id)
        .filter(TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == d,
                TimeSlot.start_time >= start_t,
                TimeSlot.start_time < end_t,
                TimeSlot.is_booked == True)
        .count()
    )
    if overlap_booked_cnt > 0:
        return jsonify({"error": "overlap_booked_slots_exist", "booked_count": overlap_booked_cnt}), 409

    # Borrar slots NO reservados del rango
    slots_deleted = (
        db.session.query(TimeSlot)
        .filter(TimeSlot.coordinator_id == coord_id,
                TimeSlot.day == d,
                TimeSlot.start_time >= start_t,
                TimeSlot.start_time < end_t,
                TimeSlot.is_booked == False)
        .delete(synchronize_session=False)
    )

    # Recortar ventanas de disponibilidad solapadas
    win_stats = split_or_delete_windows(coord_id, d, start_t, end_t)

    db.session.commit()

    # Broadcast
    try:
        socketio.emit("slots_window_changed", {"day": str(d)},
                      to=f"day:{str(d)}", namespace="/slots")
    except Exception:
        current_app.logger.exception("Failed to emit slots_window_changed")

    return jsonify({
        "ok": True,
        "day": str(d),
        "slots_deleted": slots_deleted,
        **win_stats
    })

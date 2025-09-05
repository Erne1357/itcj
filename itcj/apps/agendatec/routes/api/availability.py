# routes/api/availability.py
from datetime import datetime, timedelta, date
from flask import Blueprint, request, jsonify, g
from sqlalchemy import and_
from .....core.utils.decorators import api_auth_required, api_role_required
from ...models import db
from ...models.program import Program
from ...models.user import User
from ...models.coordinator import Coordinator
from ...models.program_coordinator import ProgramCoordinator
from ...models.time_slot import TimeSlot            # id, coordinator_id, day (DATE), start_time (TIME), end_time (TIME), is_booked
from ...models.availability_window import AvailabilityWindow  # id, coordinator_id, day (DATE), start_time (TIME), end_time (TIME), slot_minutes

api_avail_bp = Blueprint("api_avail", __name__)

# Días permitidos (según alcance)
ALLOWED_DAYS = {date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)}

# ---------- Helpers ----------
def _parse_day_query():
    s = (request.args.get("day") or "").strip()
    if not s:
        # Si no envían ?day, toma el día de hoy del servidor (date naive)
        return date.today()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None

def _parse_day_body(x: str):
    return datetime.strptime(x, "%Y-%m-%d").date()

def _require_allowed_day(d: date):
    return d in ALLOWED_DAYS

def _current_coordinator_id(fallback_id: int | None = None):
    """
    Si el usuario autenticado es 'coordinator', resuelve su coordinator_id por user_id.
    Si es admin y manda coordinator_id en body/query, úsalo.
    """
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        uid = None
    if uid:
        u = db.session.query(User).get(uid)
        if u and getattr(u, "id", None):
            c = db.session.query(Coordinator).filter_by(user_id=u.id).first()
            if c:
                return c.id
    return fallback_id

# =========================================================
#            API ALUMNO: LISTAR SLOTS POR DÍA
# =========================================================
@api_avail_bp.get("/availability/program/<int:program_id>/slots")
@api_auth_required
def list_slots_for_program_day(program_id: int):
    """
    Une coordinadores asignados al programa y devuelve slots LIBRES (is_booked=false) para un día.
    Respuesta: { day, program_id, items: [ {slot_id, coordinator_id, day, start_time, end_time}, ... ] }
    """
    d = _parse_day_query()
    if not d:
        return jsonify({"error": "invalid_day_format"}), 400

    prog = db.session.query(Program).get(program_id)
    if not prog:
        return jsonify({"error":"program_not_found"}), 404

    # coordinadores del programa
    coor_ids = [pc.coordinator_id for pc in db.session.query(ProgramCoordinator)
                .filter(ProgramCoordinator.program_id == program_id).all()]
    if not coor_ids:
        return jsonify({"day": str(d), "program_id": program_id, "items": []})

    # slots libres de esos coordinadores ese día
    slots = (db.session.query(TimeSlot)
             .filter(TimeSlot.coordinator_id.in_(coor_ids))
             .filter(TimeSlot.day == d)
             .filter(TimeSlot.is_booked == False)
             .order_by(TimeSlot.start_time.asc())
             .all())

    items = [{
        "slot_id": s.id,
        "coordinator_id": s.coordinator_id,
        "day": str(s.day),
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M")
    } for s in slots]

    return jsonify({"day": str(d), "program_id": program_id, "items": items})

# =========================================================
#     API COORD/ADMIN: CREAR VENTANA DE DISPONIBILIDAD
# =========================================================
@api_avail_bp.post("/availability/windows")
@api_auth_required
@api_role_required(["coordinator","admin"])
def create_availability_window():
    """
    Crea una ventana para UNO de los 3 días permitidos (25,26,27 Ago 2025).
    Body JSON: {
      "coordinator_id": 10,    // opcional si el que llama es coordinator (se infiere)
      "day": "2025-08-25",
      "start": "09:00",         // HH:MM (24h)
      "end": "13:00",           // HH:MM (24h)
      "slot_minutes": 10
    }
    *NOTA*: Este endpoint SOLO guarda la ventana; los slots se generan con /availability/generate-slots
    """
    data = request.get_json(silent=True) or {}
    day_s = (data.get("day") or "").strip()
    start_s = (data.get("start") or "").strip()
    end_s   = (data.get("end") or "").strip()
    slot_minutes = int(data.get("slot_minutes", 10))

    # resolver coordinator_id
    body_coor_id = data.get("coordinator_id")
    coord_id = None
    if body_coor_id is not None:
        try:
            coord_id = int(body_coor_id)
        except Exception:
            return jsonify({"error":"invalid_coordinator_id"}), 400
    coord_id = _current_coordinator_id(coord_id)
    if not coord_id:
        return jsonify({"error":"coordinator_not_found"}), 404

    # validar día permitido
    try:
        d = _parse_day_body(day_s)
    except Exception:
        return jsonify({"error":"invalid_day_format"}), 400
    if not _require_allowed_day(d):
        return jsonify({"error":"day_not_allowed","allowed":[str(x) for x in sorted(ALLOWED_DAYS)]}), 400

    # validar horas HH:MM
    try:
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        start_t = datetime.strptime(f"{sh:02d}:{sm:02d}", "%H:%M").time()
        end_t   = datetime.strptime(f"{eh:02d}:{em:02d}", "%H:%M").time()
    except Exception:
        return jsonify({"error":"invalid_time_format"}), 400

    if (end_t <= start_t) or (slot_minutes not in (5, 10, 15, 20, 30, 60)):
        return jsonify({"error":"invalid_time_range_or_slot_size"}), 400

    av = AvailabilityWindow(
        coordinator_id = coord_id,
        day            = d,
        start_time     = start_t,
        end_time       = end_t,
        slot_minutes   = slot_minutes
    )
    db.session.add(av)
    db.session.commit()
    return jsonify({"ok": True, "id": av.id})

# =========================================================
#     API COORD/ADMIN: GENERAR SLOTS A PARTIR DE VENTANAS
# =========================================================
@api_avail_bp.post("/availability/generate-slots")
@api_auth_required
@api_role_required(["coordinator","admin"])
def api_generate_slots():
    """
    Genera 'time_slots' a partir de 'availability_windows' del/los día(s) indicados.
    Body:
      { "day": "2025-08-25" }
      o
      { "days": ["2025-08-25","2025-08-26","2025-08-27"] }

    Evita duplicados si existe índice único (coordinator_id, day, start_time) en time_slots.
    """
    data = request.get_json(silent=True) or {}
    days = data.get("days")
    day  = data.get("day")
    if day and not days:
        days = [day]
    if not days or not isinstance(days, list):
        return jsonify({"error":"invalid_payload_days"}), 400

    # Parse + validar días
    parsed_days: list[date] = []
    try:
        for s in days:
            d = _parse_day_body(str(s))
            if not _require_allowed_day(d):
                return jsonify({"error":"day_not_allowed","day":str(d),"allowed":[str(x) for x in sorted(ALLOWED_DAYS)]}), 400
            parsed_days.append(d)
    except Exception:
        return jsonify({"error":"invalid_day_format"}), 400

    created = 0
    for d in parsed_days:
        wins = (db.session.query(AvailabilityWindow)
                .filter(AvailabilityWindow.day == d)
                .all())
        for w in wins:
            # iterar en saltos de w.slot_minutes entre start_time y end_time
            step = timedelta(minutes=w.slot_minutes)
            cur_dt = datetime.combine(w.day, w.start_time)
            end_dt = datetime.combine(w.day, w.end_time)

            while (cur_dt + step) <= end_dt:
                start_t = cur_dt.time()
                end_t   = (cur_dt + step).time()

                exists = (db.session.query(TimeSlot.id)
                          .filter(TimeSlot.coordinator_id == w.coordinator_id,
                                  TimeSlot.day == w.day,
                                  TimeSlot.start_time == start_t)
                          .first())
                if not exists:
                    db.session.add(TimeSlot(
                        coordinator_id = w.coordinator_id,
                        day            = w.day,
                        start_time     = start_t,
                        end_time       = end_t,
                        is_booked      = False
                    ))
                    created += 1

                cur_dt += step

    db.session.commit()
    return jsonify({"ok": True, "slots_created": created, "days": [str(d) for d in parsed_days]})

# =========================================================
#  (Opcional) Listar ventanas del día para el coordinador
# =========================================================
@api_avail_bp.get("/availability/windows")
@api_auth_required
@api_role_required(["coordinator","admin"])
def list_my_windows():
    """
    Lista las ventanas del día ?day=YYYY-MM-DD para:
      - el coordinador autenticado, o
      - un coordinator_id pasado por query (solo admin)
    """
    d = _parse_day_query()
    if not d:
        return jsonify({"error":"invalid_day_format"}), 400
    if not _require_allowed_day(d):
        return jsonify({"error":"day_not_allowed","allowed":[str(x) for x in sorted(ALLOWED_DAYS)]}), 400

    coord_id_q = request.args.get("coordinator_id")
    cid = None
    if coord_id_q:
        try:
            cid = int(coord_id_q)
        except Exception:
            return jsonify({"error":"invalid_coordinator_id"}), 400
    cid = _current_coordinator_id(cid)
    if not cid:
        return jsonify({"error":"coordinator_not_found"}), 404

    wins = (db.session.query(AvailabilityWindow)
            .filter(AvailabilityWindow.coordinator_id == cid,
                    AvailabilityWindow.day == d)
            .order_by(AvailabilityWindow.start_time.asc())
            .all())

    items = [{
        "id": w.id,
        "coordinator_id": w.coordinator_id,
        "day": str(w.day),
        "start_time": w.start_time.strftime("%H:%M"),
        "end_time": w.end_time.strftime("%H:%M"),
        "slot_minutes": w.slot_minutes
    } for w in wins]
    return jsonify({"day": str(d), "coordinator_id": cid, "items": items})

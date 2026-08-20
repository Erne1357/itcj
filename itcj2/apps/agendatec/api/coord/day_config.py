"""Coord Day Config API v2 — Configuración de días, slots y su scope por carrera.

`POST /day-config` dejó de ser "borra y regenera": ahora reconcilia. Si hay
citas reservadas dentro del rango las acorta conservando su hora de inicio y
notifica al alumno, en vez de rechazar con 409.

Toda la mecánica del split vive en `SlotService`; aquí solo se valida la
entrada, se toma el lock y se ejecutan los efectos post-commit.
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, text

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import (
    now_app, parse_time_str, require_coordinator, split_or_delete_windows,
)
from itcj2.apps.agendatec.config.constants import (
    SPLIT_GRACE_MINUTES, STUDENT_REQUESTS_URL, VALID_SLOT_MINUTES,
)
from itcj2.apps.agendatec.schemas.coord import (
    DeleteDayRangeBody, PreviewDayConfigBody, SetDayConfigBody,
)
from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.apps.agendatec.services.slot_service import SlotService
from itcj2.core.services import period_service
from itcj2.utils import async_broadcast as _async_broadcast

router = APIRouter(tags=["agendatec-coord-day-config"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.slots.api.read"])
CreatePerm = require_perms("agendatec", ["agendatec.slots.api.create"])
DeletePerm = require_perms("agendatec", ["agendatec.slots.api.delete"])


def _get_active_period_and_days(db):
    """Retorna (period, enabled_days_set) o lanza 503."""
    period = period_service.get_active_period(db)
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")
    enabled = set(period_service.get_enabled_days(db, period.id))
    return period, enabled


def _parse_day(day_s: str) -> date:
    from datetime import datetime
    try:
        return datetime.strptime(day_s.strip(), "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_day_format")


def _parse_and_validate(body, user, db):
    """Resuelve coordinador, día y horas. Lanza HTTPException si algo no cuadra."""
    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(body.day)

    _, enabled = _get_active_period_and_days(db)
    if d not in enabled:
        raise HTTPException(status_code=400, detail={
            "error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled)],
        })

    start_t = parse_time_str(body.start)
    end_t = parse_time_str(body.end)
    if not start_t or not end_t:
        raise HTTPException(status_code=400, detail="invalid_time_format")
    if end_t <= start_t or body.slot_minutes not in VALID_SLOT_MINUTES:
        raise HTTPException(status_code=400, detail="invalid_time_range_or_slot_size")

    return coord_id, d, start_t, end_t


def _offenders_payload(plan):
    return [
        {"slot_id": o.slot_id, "start": o.start.strftime("%H:%M"),
         "end": o.end.strftime("%H:%M"), "reason": o.reason}
        for o in plan.offenders
    ]


def _create_window_with_scope(db, coord_id, d, start_t, end_t, slot_minutes, program_ids):
    from itcj2.apps.agendatec.models import AvailabilityWindowProgram

    av = AvailabilityWindow(
        coordinator_id=coord_id, day=d,
        start_time=start_t, end_time=end_t, slot_minutes=slot_minutes,
    )
    db.add(av)
    db.flush()
    for pid in program_ids:
        db.add(AvailabilityWindowProgram(window_id=av.id, program_id=pid))
    return av


def _post_commit_effects(db, d, plan, result):
    """Redis, sockets y notificaciones. TODO fuera de la transacción.

    Nada de esto puede correr dentro del advisory lock: inmovilizaría un backend
    de PgBouncer durante round-trips a Redis y al bus de sockets.
    """
    from itcj2.core.services.notification_service import NotificationService
    from itcj2.core.utils.redis_conn import get_redis
    from itcj2.sockets.notifications import push_notification
    from itcj2.sockets.slots import broadcast_slots_window_changed

    # Los slots borrados pueden tener un hold vivo; sin barrerlo, el alumno
    # recibe slot_not_found al confirmar.
    try:
        r = get_redis()
        for sid in plan.to_delete_ids:
            owner = r.get(f"slot:{sid}:hold")
            if owner:
                owner_sid = owner.decode() if isinstance(owner, bytes) else owner
                r.delete(f"sid:{owner_sid}:hold")
            r.delete(f"slot:{sid}:hold")
    except Exception:
        logger.exception("No se pudieron limpiar los holds de los slots borrados")

    try:
        _async_broadcast(broadcast_slots_window_changed(str(d)))
    except Exception:
        logger.exception("Failed to emit slots_window_changed")

    for aff in result.affected:
        try:
            n = NotificationService.create(
                db=db,
                user_id=aff.student_id,
                app_name="agendatec",
                type="APPOINTMENT_RESCHEDULED",
                title="Tu cita cambió de horario",
                body=(f"Tu cita del {d:%d/%m} cambió de "
                      f"{aff.old_start:%H:%M}–{aff.old_end:%H:%M} a "
                      f"{aff.new_start:%H:%M}–{aff.new_end:%H:%M}."),
                data={
                    "url": STUDENT_REQUESTS_URL,
                    "request_id": aff.request_id,
                    "appointment_id": aff.appointment_id,
                    "day": str(d),
                    "old_start": aff.old_start.strftime("%H:%M"),
                    "old_end": aff.old_end.strftime("%H:%M"),
                    "new_start": aff.new_start.strftime("%H:%M"),
                    "new_end": aff.new_end.strftime("%H:%M"),
                },
                source_request_id=aff.request_id,
                source_appointment_id=aff.appointment_id,
            )
            db.commit()
            # Endpoint sync: el broadcast interno del service no encuentra loop.
            _async_broadcast(push_notification(aff.student_id, n.to_dict()))
        except Exception:
            db.rollback()   # no dejar la sesión abortada para el siguiente alumno
            logger.exception("No se pudo notificar la reagenda al alumno %s", aff.student_id)


# ==================== GET /day-config ====================

@router.get("/day-config")
def get_day_config(
    day: str = Query(..., description="Fecha YYYY-MM-DD"),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Ventanas de disponibilidad del día, con su scope de carreras."""
    from itcj2.apps.agendatec.models import AvailabilityWindowProgram
    from itcj2.core.models.program import Program

    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(day)

    _, enabled = _get_active_period_and_days(db)
    if d not in enabled:
        raise HTTPException(status_code=400, detail={
            "error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled)],
        })

    wins = (
        db.query(AvailabilityWindow)
        .filter(AvailabilityWindow.coordinator_id == coord_id, AvailabilityWindow.day == d)
        .order_by(AvailabilityWindow.start_time.asc())
        .all()
    )

    win_ids = [w.id for w in wins]
    by_window = {}
    if win_ids:
        rows = (
            db.query(AvailabilityWindowProgram.window_id, Program.id, Program.name)
            .join(Program, Program.id == AvailabilityWindowProgram.program_id)
            .filter(AvailabilityWindowProgram.window_id.in_(win_ids))
            .all()
        )
        for wid, pid, pname in rows:
            by_window.setdefault(wid, []).append({"id": pid, "name": pname})

    return {
        "day": str(d),
        "items": [
            {
                "id": w.id,
                "day": str(w.day),
                "start": w.start_time.strftime("%H:%M"),
                "end": w.end_time.strftime("%H:%M"),
                "slot_minutes": w.slot_minutes,
                "programs": by_window.get(w.id, []),
            }
            for w in wins
        ],
    }


# ==================== POST /day-config/preview ====================

@router.post("/day-config/preview")
def preview_day_config(body: PreviewDayConfigBody, user: dict = CreatePerm, db: DbSession = None):
    """Qué haría POST /day-config, sin hacerlo.

    ADVERTENCIA: es informativo, no una reserva. Entre el preview y el POST un
    alumno puede reservar un slot y el POST devolver 409 aunque aquí saliera
    `blocked: false`. La UI debe manejar ese 409 tardío.
    """
    coord_id, d, start_t, end_t = _parse_and_validate(body, user, db)
    program_ids = SlotService.resolve_programs(db, coord_id, body.programs)
    plan = SlotService.plan_split(db, coord_id, d, start_t, end_t, body.slot_minutes, program_ids)
    # Sin rollback explícito: `plan_split` no muta nada, y `get_db` ya hace
    # rollback en su teardown (database.py:47). Un rollback aquí solo serviría
    # para tirar trabajo ajeno si alguien reutiliza la sesión.

    def _fmt(a):
        return {
            "student_name": a.student_name,
            "program": a.program_name,
            "old": f"{a.old_start:%H:%M}–{a.old_end:%H:%M}",
            "new": f"{a.new_start:%H:%M}–{a.new_end:%H:%M}",
        }

    return {
        "start_efectivo": plan.start_efectivo.strftime("%H:%M"),
        "slots_to_delete": len(plan.to_delete_ids),
        "slots_to_create": len(plan.to_create),
        "slots_preserved_with_history": len(plan.preserved_with_history),
        "appointments_affected": [_fmt(a) for a in plan.to_notify],
        "out_of_scope_appointments": [_fmt(a) for a in plan.out_of_scope],
        "blocked": plan.blocked,
        "offenders": _offenders_payload(plan),
        "advisory": "El resultado puede cambiar si un alumno reserva antes de confirmar.",
    }


# ==================== POST /day-config ====================

@router.post("/day-config")
def set_day_config(body: SetDayConfigBody, user: dict = CreatePerm, db: DbSession = None):
    """Configura (o re-divide) un rango de horarios del día."""
    coord_id, d, start_t, end_t = _parse_and_validate(body, user, db)

    # Lock de intención. SELECT ... FOR UPDATE sobre CERO filas no excluye nada,
    # y configurar un rango vacío por primera vez es justo ese caso: dos
    # pestañas insertarían la grilla completa dos veces, y uq_time_slot no
    # existe en la BD para atraparlo.
    # xact_lock (no session lock): se libera en COMMIT y en ROLLBACK, y es
    # seguro bajo PgBouncer en pool_mode = transaction.
    db.execute(text("SELECT pg_advisory_xact_lock(:c, :d)"),
               {"c": coord_id, "d": d.toordinal()})

    program_ids = SlotService.resolve_programs(db, coord_id, body.programs)

    # ORDEN CRÍTICO: bloquear ANTES de planear. El advisory lock solo excluye a
    # otros coordinadores; el alumno NO lo toma (request_service hace
    # UPDATE ... WHERE is_booked=false sin pedirlo). Si planeáramos primero, un
    # alumno podría reservar entre el plan y el lock, y el borrado por id se
    # llevaría por CASCADE la cita recién creada.
    (db.query(TimeSlot)
       .filter(TimeSlot.coordinator_id == coord_id, TimeSlot.day == d,
               and_(TimeSlot.end_time > start_t, TimeSlot.start_time < end_t))
       .order_by(TimeSlot.id)          # orden determinista: evita deadlocks
       .with_for_update()
       .all())

    plan = SlotService.plan_split(db, coord_id, d, start_t, end_t, body.slot_minutes, program_ids)

    if plan.blocked:
        # No hace falta rollback explícito: nada se mutó (plan_split es puro), y
        # `get_db` cierra la transacción en su teardown, que es lo que libera el
        # pg_advisory_xact_lock y el FOR UPDATE.
        return JSONResponse(status_code=409, content={
            "error": "misaligned_booked_slots",
            "offenders": _offenders_payload(plan),
        })

    result = SlotService.apply_split(db, coord_id, d, plan, program_ids)

    win_stats = split_or_delete_windows(coord_id, d, plan.start_efectivo, end_t, db)
    _create_window_with_scope(db, coord_id, d, plan.start_efectivo, end_t,
                              body.slot_minutes, program_ids)
    db.commit()   # libera el advisory lock

    _post_commit_effects(db, d, plan, result)

    return {
        "ok": True,
        "start_efectivo": plan.start_efectivo.strftime("%H:%M"),
        "slots_created": result.slots_created,
        "slots_deleted": result.slots_deleted,
        "slots_shortened": result.slots_shortened,
        "slots_preserved_with_history": len(plan.preserved_with_history),
        "appointments_notified": len(result.affected),
        **win_stats,
    }


# ==================== DELETE /day-config ====================

@router.delete("/day-config")
def delete_day_range(body: DeleteDayRangeBody, user: dict = DeletePerm, db: DbSession = None):
    """Borra el rango [start, end) de slots libres de un día.

    A diferencia del POST, ante slots reservados sigue devolviendo 409: borrar
    un rango con citas vivas es destructivo, no una re-división.
    """
    from itcj2.apps.agendatec.models import Appointment
    from itcj2.sockets.slots import broadcast_slots_window_changed

    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(body.day)

    _, enabled = _get_active_period_and_days(db)
    if d not in enabled:
        raise HTTPException(status_code=400, detail="day_not_allowed")

    start_t = parse_time_str(body.start)
    end_t = parse_time_str(body.end)
    if not start_t or not end_t:
        raise HTTPException(status_code=400, detail="invalid_time_format")
    if end_t <= start_t:
        raise HTTPException(status_code=400, detail="invalid_time_range")

    # Alineado con el POST: el día en curso se permite de ahora en adelante.
    # Antes lo rechazaba entero, mientras el POST sí dejaba agregar ventanas
    # ese mismo día — una asimetría que no tenía justificación.
    now_local = now_app()
    if d < now_local.date():
        raise HTTPException(status_code=400, detail="day_in_past")
    if d == now_local.date():
        cutoff_dt = now_local + timedelta(minutes=SPLIT_GRACE_MINUTES)
        if cutoff_dt.date() == d:
            start_t = max(start_t, cutoff_dt.time())
        if start_t >= end_t:
            raise HTTPException(status_code=400, detail="range_fully_in_past")

    # Mismo predicado de solape que el split: con `start_time >=` el borrado
    # dejaba a caballo los slots que cruzan la frontera.
    overlaps = and_(TimeSlot.end_time > start_t, TimeSlot.start_time < end_t)

    booked_cnt = (
        db.query(TimeSlot.id)
        .filter(TimeSlot.coordinator_id == coord_id, TimeSlot.day == d,
                overlaps, TimeSlot.is_booked.is_(True))
        .count()
    )
    if booked_cnt > 0:
        return JSONResponse(status_code=409, content={
            "error": "overlap_booked_slots_exist", "booked_count": booked_cnt,
        })

    # No borrar slots con historial de citas: el ON DELETE CASCADE las destruye.
    slots_deleted = (
        db.query(TimeSlot)
        .filter(TimeSlot.coordinator_id == coord_id, TimeSlot.day == d,
                overlaps, TimeSlot.is_booked.is_(False),
                ~TimeSlot.id.in_(db.query(Appointment.slot_id)))
        .delete(synchronize_session=False)
    )

    win_stats = split_or_delete_windows(coord_id, d, start_t, end_t, db)
    db.commit()

    try:
        _async_broadcast(broadcast_slots_window_changed(str(d)))
    except Exception:
        logger.exception("Failed to emit slots_window_changed")

    return {"ok": True, "day": str(d), "slots_deleted": slots_deleted, **win_stats}

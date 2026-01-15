# routes/api/admin/stats.py
"""
Endpoints de estadísticas para administración de AgendaTec.

Incluye:
- stats_overview: Resumen general del dashboard
- stats_coordinators: Estadísticas por coordinador
- stats_activity: Histograma de actividad por hora
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, case, cast, Date, func
from sqlalchemy.sql import extract

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request as Req
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_app_required, api_auth_required

from .helpers import range_from_query, get_dialect_name

admin_stats_bp = Blueprint("admin_stats", __name__)


@admin_stats_bp.get("/stats/overview")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_overview():
    """
    Resumen de estadísticas del dashboard administrativo.

    Query params:
        from: Fecha de inicio (YYYY-MM-DD)
        to: Fecha de fin (YYYY-MM-DD)

    Returns:
        JSON con totales, series temporales, tasa de no-show y pendientes por coordinador
    """
    start, end = range_from_query()

    # Totales por estado (Requests)
    totals_q = (
        db.session.query(Req.status, func.count(Req.id))
        .filter(Req.created_at >= start, Req.created_at <= end)
        .group_by(Req.status)
    )
    totals = [{"status": s, "total": t} for (s, t) in totals_q.all()]

    is_pg = get_dialect_name().startswith("postgres")

    if is_pg:
        hour_bucket = func.date_trunc("hour", Req.created_at).label("hour")
    else:
        hour_bucket = func.strftime("%Y-%m-%d %H:00:00", Req.created_at).label("hour")

    hourly_q = (
        db.session.query(hour_bucket, func.count(Req.id))
        .filter(Req.created_at >= start, Req.created_at <= end)
        .group_by(hour_bucket)
        .order_by(hour_bucket)
    )

    series = []
    for h, n in hourly_q.all():
        series.append({"hour": h.isoformat() if hasattr(h, "isoformat") else str(h), "total": n})

    # No-show rate (Appointments): NO_SHOW / (DONE + NO_SHOW)
    denom_q = (
        db.session.query(func.count(Appointment.id))
        .join(Req, Req.id == Appointment.request_id)
        .filter(
            Req.type == "APPOINTMENT",
            Req.created_at >= start,
            Req.created_at <= end,
            Appointment.status.in_(["DONE", "NO_SHOW"]),
        )
    )
    denom = denom_q.scalar() or 0
    noshow_q = (
        db.session.query(func.count(Appointment.id))
        .join(Req, Req.id == Appointment.request_id)
        .filter(
            Req.type == "APPOINTMENT",
            Req.created_at >= start,
            Req.created_at <= end,
            Appointment.status == "NO_SHOW",
        )
    )
    noshows = noshow_q.scalar() or 0
    no_show_rate = (noshows / denom) if denom else 0.0

    pending_appointment_q = (
        db.session.query(
            Coordinator.id.label("coordinator_id"),
            User.full_name.label("coordinator_name"),
            func.count(Req.id).label("pending"),
        )
        .join(User, User.id == Coordinator.user_id)
        .join(Appointment, Appointment.coordinator_id == Coordinator.id)
        .join(Req, Req.id == Appointment.request_id)
        .filter(
            Req.status == "PENDING",
            Req.type == "APPOINTMENT",
            Req.created_at >= start,
            Req.created_at <= end
        )
        .group_by(Coordinator.id, User.full_name)
        .order_by(func.count(Req.id).desc())
    )
    pending_appointment = [
        dict(coordinator_id=i, coordinator_name=n, pending=p)
        for (i, n, p) in pending_appointment_q.all()
    ]

    # Pendientes por coordinador: DROP
    pending_drop_q = (
        db.session.query(
            Coordinator.id.label("coordinator_id"),
            User.full_name.label("coordinator_name"),
            func.count(Req.id).label("pending"),
        )
        .join(User, User.id == Coordinator.user_id)
        .join(ProgramCoordinator, ProgramCoordinator.coordinator_id == Coordinator.id)
        .join(Req, Req.program_id == ProgramCoordinator.program_id)
        .filter(
            Req.status == "PENDING",
            Req.type == "DROP",
            Req.created_at >= start,
            Req.created_at <= end
        )
        .group_by(Coordinator.id, User.full_name)
        .order_by(func.count(Req.id).desc())
    )
    pending_drop = [
        dict(coordinator_id=i, coordinator_name=n, pending=p)
        for (i, n, p) in pending_drop_q.all()
    ]

    return jsonify(
        {
            "totals": totals,
            "series": series,
            "no_show_rate": no_show_rate,
            "pending_appointment": pending_appointment,
            "pending_drop": pending_drop,
        }
    )


@admin_stats_bp.get("/stats/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_coordinators():
    """
    Estadística por coordinador con TODAS las solicitudes.

    Query params:
        from, to: Rango de fechas
        rtype: ALL|APPOINTMENT|DROP (default: ALL)
        by_day: 1 → desglose por día
        states: 1 → agrega campos por estado individual

    Returns:
        JSON con overall, coordinators y opcionalmente overall_by_day
    """
    start, end = range_from_query()
    start_date, end_date = start.date(), end.date()

    by_day = (request.args.get("by_day", "0").lower() in ("1", "true", "yes"))
    want_states = (request.args.get("states", "1").lower() in ("1", "true", "yes"))
    rtype = (request.args.get("rtype", "ALL") or "ALL").upper()
    if rtype not in ("ALL", "APPOINTMENT", "DROP"):
        rtype = "ALL"

    # Columnas de agregación comunes
    is_pending = case((Req.status == "PENDING", 1), else_=0)
    is_attended = case(
        (Req.status.in_(("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT")), 1),
        else_=0
    )
    is_unattended = case((Req.status.in_(("NO_SHOW", "CANCELED")), 1), else_=0)

    s_ok = case((Req.status == "RESOLVED_SUCCESS", 1), else_=0)
    s_nok = case((Req.status == "RESOLVED_NOT_COMPLETED", 1), else_=0)
    s_other = case((Req.status == "ATTENDED_OTHER_SLOT", 1), else_=0)
    s_nshow = case((Req.status == "NO_SHOW", 1), else_=0)
    s_canc = case((Req.status == "CANCELED", 1), else_=0)
    s_pend = case((Req.status == "PENDING", 1), else_=0)

    def _select_cols(day_col=None):
        cols = [
            Coordinator.id.label("coord_id"),
            User.full_name.label("coord_name"),
            func.count(Req.id).label("total"),
            func.sum(is_pending).label("pending"),
            func.sum(is_attended).label("attended"),
            func.sum(is_unattended).label("unattended"),
        ]
        if want_states:
            cols += [
                func.sum(s_ok).label("resolved_success"),
                func.sum(s_nok).label("resolved_not_completed"),
                func.sum(s_other).label("attended_other_slot"),
                func.sum(s_nshow).label("no_show"),
                func.sum(s_canc).label("canceled"),
                func.sum(s_pend).label("pending"),
            ]
        if by_day and day_col is not None:
            cols.insert(2, day_col.label("day"))
        return cols

    rows_all = []

    # Subconsulta: APPOINTMENT (por TimeSlot.day)
    if rtype in ("ALL", "APPOINTMENT"):
        day_col_ap = TimeSlot.day
        q_ap = (
            db.session.query(*_select_cols(day_col_ap if by_day else None))
            .join(Appointment, Appointment.request_id == Req.id)
            .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
            .join(Coordinator, Coordinator.id == Appointment.coordinator_id)
            .join(User, User.id == Coordinator.user_id)
            .filter(
                Req.type == "APPOINTMENT",
                day_col_ap >= start_date,
                day_col_ap <= end_date,
            )
        )
        grp_ap = [Coordinator.id, User.full_name]
        if by_day:
            grp_ap.append(day_col_ap)
        q_ap = q_ap.group_by(*grp_ap).order_by(User.full_name.asc(), *([day_col_ap.asc()] if by_day else []))
        rows_all.extend(q_ap.all())

    # Subconsulta: DROP (por Program → ProgramCoordinator)
    if rtype in ("ALL", "DROP"):
        drop_day_col = cast(Req.updated_at, Date)
        q_drop = (
            db.session.query(*_select_cols(drop_day_col if by_day else None))
            .join(Program, Program.id == Req.program_id)
            .join(ProgramCoordinator, ProgramCoordinator.program_id == Program.id)
            .join(Coordinator, Coordinator.id == ProgramCoordinator.coordinator_id)
            .join(User, User.id == Coordinator.user_id)
            .filter(
                Req.type == "DROP",
                drop_day_col >= start_date,
                drop_day_col <= end_date,
            )
        )
        grp_drop = [Coordinator.id, User.full_name]
        if by_day:
            grp_drop.append(drop_day_col)
        q_drop = q_drop.group_by(*grp_drop).order_by(User.full_name.asc(), *([drop_day_col.asc()] if by_day else []))
        rows_all.extend(q_drop.all())

    # Reducir / combinar ambas listas de filas
    overall = defaultdict(int)
    overall_by_day = defaultdict(lambda: defaultdict(int))
    per_coord = {}
    per_coord_days = defaultdict(lambda: defaultdict(int))

    def add_to_bucket(bucket: dict, r):
        bucket["total"] = int(bucket.get("total", 0)) + int(r.total or 0)
        bucket["pending"] = int(bucket.get("pending", 0)) + int(r.pending or 0)
        bucket["attended"] = int(bucket.get("attended", 0)) + int(r.attended or 0)
        bucket["unattended"] = int(bucket.get("unattended", 0)) + int(r.unattended or 0)
        if want_states:
            st = bucket.setdefault("states", defaultdict(int))
            st["RESOLVED_SUCCESS"] += int(getattr(r, "resolved_success", 0) or 0)
            st["RESOLVED_NOT_COMPLETED"] += int(getattr(r, "resolved_not_completed", 0) or 0)
            st["ATTENDED_OTHER_SLOT"] += int(getattr(r, "attended_other_slot", 0) or 0)
            st["NO_SHOW"] += int(getattr(r, "no_show", 0) or 0)
            st["CANCELED"] += int(getattr(r, "canceled", 0) or 0)
            st["PENDING"] += int(getattr(r, "pending", 0) or 0)

    for r in rows_all:
        cid = int(r.coord_id)

        if cid not in per_coord:
            per_coord[cid] = {
                "coordinator_id": cid,
                "coordinator_name": r.coord_name,
                "totals": {"total": 0, "pending": 0, "attended": 0, "unattended": 0}
            }
            if want_states:
                per_coord[cid]["totals"]["states"] = {
                    "RESOLVED_SUCCESS": 0,
                    "RESOLVED_NOT_COMPLETED": 0,
                    "ATTENDED_OTHER_SLOT": 0,
                    "NO_SHOW": 0,
                    "CANCELED": 0,
                    "PENDING": 0,
                }

        add_to_bucket(per_coord[cid]["totals"], r)
        add_to_bucket(overall, r)

        if by_day:
            d_iso = (r.day.isoformat() if r.day else None)
            if d_iso:
                day_bucket = per_coord_days[cid].setdefault(
                    d_iso, {"day": d_iso, "total": 0, "pending": 0, "attended": 0, "unattended": 0}
                )
                if want_states and "states" not in day_bucket:
                    day_bucket["states"] = {
                        "RESOLVED_SUCCESS": 0,
                        "RESOLVED_NOT_COMPLETED": 0,
                        "ATTENDED_OTHER_SLOT": 0,
                        "NO_SHOW": 0,
                        "CANCELED": 0,
                        "PENDING": 0,
                    }
                add_to_bucket(day_bucket, r)
                add_to_bucket(overall_by_day[d_iso], r)

    # Serializar coordinadores
    coord_list = []
    for cid, obj in sorted(per_coord.items(), key=lambda kv: kv[1]["coordinator_name"] or ""):
        if by_day:
            days_map = per_coord_days.get(cid, {})
            obj["days"] = [days_map[k] for k in sorted(days_map.keys())]
        if want_states:
            st = obj["totals"].get("states")
            if st and isinstance(st, defaultdict):
                obj["totals"]["states"] = dict(st)
        coord_list.append(obj)

    overall_out = dict(overall)
    if want_states and "states" in overall_out and isinstance(overall_out["states"], defaultdict):
        overall_out["states"] = dict(overall_out["states"])

    resp = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "filter": {"rtype": rtype, "by_day": by_day, "states": want_states},
        "overall": overall_out,
        "coordinators": coord_list,
    }

    if by_day:
        ob = []
        for d in sorted(overall_by_day.keys()):
            vals = overall_by_day[d]
            row = {"day": d}
            row.update({k: v for k, v in vals.items() if k != "states"})
            if want_states and "states" in vals:
                st = vals["states"]
                row["states"] = dict(st) if isinstance(st, defaultdict) else st
            ob.append(row)
        resp["overall_by_day"] = ob

    return jsonify(resp)


@admin_stats_bp.get("/stats/activity")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_activity():
    """
    Histograma por hora (0..23) de UPDATED_AT.

    Query params:
        from, to: Rango de fechas
        rtype: ALL|APPOINTMENT|DROP (default ALL)

    Returns:
        JSON con overall (array de 24), coordinators y labels
    """
    start, end = range_from_query()
    rtype = (request.args.get("rtype", "ALL") or "ALL").upper()
    if rtype not in ("ALL", "APPOINTMENT", "DROP"):
        rtype = "ALL"

    def _zeros24():
        return [0] * 24

    overall = _zeros24()
    by_coord = {}

    # APPOINTMENT (join Appointment->Coordinator)
    if rtype in ("ALL", "APPOINTMENT"):
        q_ap = (
            db.session.query(
                Coordinator.id.label("cid"),
                User.full_name.label("cname"),
                extract("hour", Req.updated_at).cast(db.Integer).label("h"),
                func.count(Req.id)
            )
            .join(Appointment, Appointment.request_id == Req.id)
            .join(Coordinator, Coordinator.id == Appointment.coordinator_id)
            .join(User, User.id == Coordinator.user_id)
            .filter(
                Req.type == "APPOINTMENT",
                Req.updated_at >= start,
                Req.updated_at <= end,
            )
            .group_by("cid", "cname", "h")
        )
        for cid, cname, h, n in q_ap.all():
            h = int(h or 0)
            overall[h] += int(n)
            arr = by_coord.setdefault(int(cid), {"id": int(cid), "name": cname, "hours": _zeros24()})["hours"]
            arr[h] += int(n)

    # DROP (join Program->ProgramCoordinator->Coordinator)
    if rtype in ("ALL", "DROP"):
        q_dr = (
            db.session.query(
                Coordinator.id.label("cid"),
                User.full_name.label("cname"),
                extract("hour", Req.updated_at).cast(db.Integer).label("h"),
                func.count(Req.id)
            )
            .join(Program, Program.id == Req.program_id)
            .join(ProgramCoordinator, ProgramCoordinator.program_id == Program.id)
            .join(Coordinator, Coordinator.id == ProgramCoordinator.coordinator_id)
            .join(User, User.id == Coordinator.user_id)
            .filter(
                Req.type == "DROP",
                Req.updated_at >= start,
                Req.updated_at <= end,
            )
            .group_by("cid", "cname", "h")
        )
        for cid, cname, h, n in q_dr.all():
            h = int(h or 0)
            overall[h] += int(n)
            arr = by_coord.setdefault(int(cid), {"id": int(cid), "name": cname, "hours": _zeros24()})["hours"]
            arr[h] += int(n)

    resp = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "overall": overall,
        "coordinators": sorted(by_coord.values(), key=lambda x: x["name"] or ""),
        "labels": [f"{h:02d}:00" for h in range(24)],
    }
    return jsonify(resp)

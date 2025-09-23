# backend/routes/api/admin.py
from __future__ import annotations
from datetime import datetime, timedelta, date
from typing import Optional, Iterable

from flask import Blueprint, request, jsonify, send_file, g, current_app
from sqlalchemy import func, case, and_, or_, cast, Date
from sqlalchemy.orm import joinedload, contains_eager
from sqlalchemy.sql import extract

from itcj.apps.agendatec.models import db
from itcj.core.models.user import User
from itcj.core.models.role import Role
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.apps.agendatec.models.request import Request as Req
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.apps.agendatec.models.notification import Notification
from itcj.apps.agendatec.models.audit_log import AuditLog
from itcj.apps.agendatec.models.survey_dispatches import SurveyDispatch

from itcj.core.utils.decorators import api_auth_required, api_role_required,api_app_required
from itcj.core.utils.jwt_tools import encode_jwt
from itcj.core.utils.security import hash_nip  # si ya tienes util p/ NIP hash (ajusta si difiere)
from itcj.core.utils.notify import create_notification as notify_user  # si ya tienes un helper (ajusta si difiere)
import logging,os
from xlsxwriter import Workbook
from itcj.core.utils.msgraph_mail import acquire_token_silent, graph_send_mail
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from itcj.core.utils.email_tools import student_email

# XLSX
from io import BytesIO

import pandas as pd

api_admin_bp = Blueprint("api_admin", __name__)
ATTENDED_STATES = ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT")
EXCLUDE_STATES  = ("CANCELED", "NO_SHOW","PENDING")
# ---------- Helpers ----------

def _parse_dt(s: Optional[str], default: Optional[datetime] = None) -> datetime:
    if s:
        # admite 'YYYY-MM-DD' o ISO completo
        try:
            if len(s) == 10:
                return datetime.fromisoformat(s)
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    return default or datetime.utcnow()

def _range_from_query() -> tuple[datetime, datetime]:
    qf = request.args.get("from")
    qt = request.args.get("to")
    end = _parse_dt(qt, datetime.utcnow())
    start = _parse_dt(qf, end - timedelta(days=7))
    # normaliza para incluir el día 'to' completo si vino solo fecha
    if qf and len(qf) == 10:
        start = datetime.combine(start.date(), datetime.min.time())
    if qt and len(qt) == 10:
        end = datetime.combine(end.date(), datetime.max.time())
    return start, end

def _paginate(query, default_limit=20, max_limit=100):
    try:
        limit = min(int(request.args.get("limit", default_limit)), max_limit)
    except ValueError:
        limit = default_limit
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    total = query.order_by(None).count()
    items = query.limit(limit).offset(offset).all()
    return items, total

def _ensure_admin():
    # por si necesitas usar fuera de decoradores
    u = getattr(g, "current_user", None)
    if not u or u.get("role") != "admin":
        from flask import abort
        abort(403)
def _add_query_params(url: str, **params) -> str:
    """
    Agrega/mezcla query params a una URL (p.ej. SURVEY_FORMS_URL?cn=...).
    """
    pr = urlparse(url)
    q = dict(parse_qsl(pr.query))
    q.update({k: v for k, v in params.items() if v is not None})
    new_q = urlencode(q)
    return urlunparse((pr.scheme, pr.netloc, pr.path, pr.params, new_q, pr.fragment))

def _student_email_from_user(u: User) -> Optional[str]:
    """
    Regla pedida:
    - Si username ya es un correo (contiene @) -> úsalo.
    - Si username existe (sin arroba) -> username@EMAIL_DOMAIN
    - Si no hay username, pero hay control_number -> L{control_number}@EMAIL_DOMAIN
    """
    domain = os.getenv("EMAIL_DOMAIN", "").strip()
    # Si no hay dominio y SENDER_UPN existe, usar el dominio del remitente
    if not domain:
        sender = os.getenv("MAIL_SENDER_UPN", "")
        if "@" in sender:
            domain = sender.split("@", 1)[1].strip().lower()

    if u.username:
        un = u.username.strip()
        if "@" in un:
            return un.lower()
        if domain:
            return f"{un.lower()}@{domain}"
    if u.control_number and domain:
        cn = u.control_number.strip().upper()
        if not cn.startswith("L"):
            cn = "L" + cn
        return f"{cn.lower()}@{domain}"
    return None

def _student_identifier(u: User) -> str:
    """
    Identificador para pasar al Forms (param 'cn'): usa control_number si existe;
    si no, usa username.
    """
    return (getattr(u, "control_number", None) or getattr(u, "username", "") or "").strip()
def find_recipients(start, end, campaign_code: str, skip_already_sent: bool = True, limit=500, offset=0):
    """
    Retorna [(user, request, email)] para enviar encuesta.
    Regla: cualquier Req cuyo estado NO esté en CANCELED/NO_SHOW y que pertenezca a un coordinador (ligado a programa),
    usando updated_at para bajas y slot.day para citas (si tu SQL ya arma eso, perfecto).
    """

    # Base: requests atendidas (no cancel/no_show) en rango por su "evento" (tu ya lo definiste).
    q = (
        db.session.query(User, Req)
        .join(User, User.id == Req.user_id)
        .filter(Req.status.notin_(EXCLUDE_STATES))
        .filter(and_(Req.updated_at >= start, Req.updated_at <= end))   # Para bajas y también sirve como fallback general
        # si tienes tipo "APPOINTMENT" y deseas usar slot.day, arma un UNION o un OR con subquery; para mantenerlo simple:
        # .filter(or_(Req.type == "DROP", … condición APPOINTMENT …))
    )

    if skip_already_sent:
        q = q.outerjoin(
            SurveyDispatch,
            and_(
                SurveyDispatch.campaign_code == campaign_code,
                SurveyDispatch.user_id == User.id,
            ),
        ).filter(SurveyDispatch.id.is_(None))

    q = q.order_by(User.full_name.asc()).limit(limit).offset(offset)

    rows = q.all()
    out = []
    for u, r in rows:
        em = student_email(u)
        if not em:
            continue
        out.append((u, r, em))
    return out
# ---------- Stats Overview ----------

@api_admin_bp.get("/stats/overview")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_overview():
    start, end = _range_from_query()

    # Totales por estado (Requests)
    totals_q = (
        db.session.query(Req.status, func.count(Req.id))
        .filter(Req.created_at >= start, Req.created_at <= end)
        .group_by(Req.status)
    )
    totals = [{"status": s, "total": t} for (s, t) in totals_q.all()]
    def _dialect_name():
        try:
            bind = db.session.get_bind()  # devuelve el engine activo para esta sesión
        except Exception:
            bind = None
        try:
            eng = bind or db.engine        # respaldo: engine principal
        except Exception:
            eng = None
        return (eng and eng.dialect and eng.dialect.name) or ""

    is_pg = _dialect_name().startswith("postgres")

    if is_pg:
        hour_bucket = func.date_trunc("hour", Req.created_at).label("hour")
    else:
        # SQLite: usa strftime; en otros, ajusta según backend
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
        .filter(Req.status == "PENDING", Req.type == "APPOINTMENT")
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
        .filter(Req.status == "PENDING", Req.type == "DROP")
        .group_by(Coordinator.id, User.full_name)
        .order_by(func.count(Req.id).desc())
    )
    pending_drop = [
        dict(coordinator_id=i, coordinator_name=n, pending=p)
        for (i, n, p) in pending_drop_q.all()
    ]
    # En tu respuesta JSON:
    return jsonify(
        {
            "totals": totals,
            "series": series,
            "no_show_rate": no_show_rate,
            "pending_appointment": pending_appointment,
            "pending_drop": pending_drop,
        }
    )

# ---------- Listado y edición de solicitudes ----------

@api_admin_bp.get("/requests")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests_all.read"])
def admin_list_requests():
    start, end = _range_from_query()
    status = request.args.get("status")
    program_id = request.args.get("program_id", type=int)
    coordinator_id = request.args.get("coordinator_id", type=int)
    q = request.args.get("q", "").strip()

    qry = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.program),
            joinedload(Req.student),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
    )
    if status:
        qry = qry.filter(Req.status == status)
    if program_id:
        qry = qry.filter(Req.program_id == program_id)
    if coordinator_id:
        # a través de Appointment
        qry = qry.join(Appointment, Appointment.request_id == Req.id).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if q:
        # busca por no. de control o nombre del alumno
        qry = qry.join(User, User.id == Req.student_id).filter(
            or_(User.control_number.ilike(f"%{q}%"),User.username.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )

    items, total = _paginate(qry.order_by(Req.created_at.desc()))

    def _to_dict(r: Req):
        a: Optional[Appointment] = r.appointment
        coord_name = a.coordinator.user.full_name if a and a.coordinator and a.coordinator.user else None
        return {
            "id": r.id,
            "type": r.type,
            "status": r.status,
            "program": r.program.name if r.program else None,
            "student": r.student.full_name if r.student else None,
            "student_control_number": r.student.control_number if r.student.control_number else r.student.username,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "appointment": {
                "id": a.id,
                "status": a.status,
                "coordinator_id": a.coordinator_id,
                "coordinator_name": coord_name,
                "time_slot_id": a.slot_id,
            } if a else None,
        }

    return jsonify({"items": [_to_dict(x) for x in items], "total": total})

@api_admin_bp.patch("/requests/<int:req_id>/status")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests_all.edit"])
def admin_change_request_status(req_id: int):
    data = request.get_json(silent=True) or {}
    new_status: str = data.get("status")
    reason: str = data.get("reason", "")
    actor_id = int((g.current_user or {}).get("sub")) if getattr(g,"current_user",None) else None
    resp, code = admin_change_request_status(actor_user_id=actor_id, req_id=req_id, new_status=new_status, reason=reason)
    return jsonify(resp), code

# ---------- Coordinadores: crear/actualizar ----------

@api_admin_bp.post("/users/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.create"])
def create_coordinator():
    data = request.get_json(silent=True) or {}
    name: str = data.get("name", "").strip()
    email: str = data.get("email", "").strip()
    control_number: Optional[str] = data.get("control_number")
    username: str = data.get("username","").strip() # opcional para staff
    program_ids: list[int] = data.get("program_ids", [])
    nip: str = data.get("nip", "1234")  # NIP temporal

    if not name:
        return jsonify({"error": "missing_name"}), 400

    # Rol coordinator
    role = db.session.query(Role).filter_by(name="coordinator").first()
    if not role:
        return jsonify({"error": "role_not_found"}), 500

    # User
    u = User(full_name=name, email=email or None, control_number=control_number, username = username, role_id=role.id, nip_hash=hash_nip(nip))
    db.session.add(u)
    db.session.flush()

    # Coordinator
    c = Coordinator(user_id=u.id, contact_email=email or None)
    db.session.add(c)
    db.session.flush()

    # Asignaciones
    if program_ids:
        # valida que existan
        valid_programs = db.session.query(Program.id).filter(Program.id.in_(program_ids)).all()
        valid_ids = [pid for (pid,) in valid_programs]
        for pid in valid_ids:
            db.session.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    # Audit
    actor_id = g.current_user.get("sub") if getattr(g, "current_user", None) else None
    db.session.add(
        AuditLog(
            actor_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="create",
            payload_json=None,
        )
    )
    db.session.commit()

    return jsonify({"id": c.id, "user_id": u.id})

@api_admin_bp.patch("/users/coordinators/<int:coord_id>")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.edit"])
def update_coordinator(coord_id: int):
    data = request.get_json(silent=True) or {}
    name: Optional[str] = data.get("name")
    email: Optional[str] = data.get("email")
    program_ids: Optional[list[int]] = data.get("program_ids")

    c = db.session.query(Coordinator).options(joinedload(Coordinator.user)).filter(Coordinator.id == coord_id).first()
    if not c:
        return jsonify({"error": "not_found"}), 404

    before = {"name": c.user.full_name, "email": c.contact_email}

    if name is not None:
        c.user.full_name = name.strip() or c.user.full_name
    if email is not None:
        c.contact_email = email.strip() or None

    if program_ids is not None:
        # reemplaza asignaciones
        db.session.query(ProgramCoordinator).filter(ProgramCoordinator.coordinator_id == c.id).delete()
        if program_ids:
            valid_programs = db.session.query(Program.id).filter(Program.id.in_(program_ids)).all()
            valid_ids = [pid for (pid,) in valid_programs]
            for pid in valid_ids:
                db.session.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))

    after = {"name": c.user.full_name, "email": c.contact_email, "program_ids": program_ids}
    actor_id = g.current_user.get("sub") if getattr(g, "current_user", None) else None
    db.session.add(
        AuditLog(
            actor_user_id=actor_id,
            entity="coordinator",
            entity_id=c.id,
            action="update",
            from_json=before,
            to_json=after,
        )
    )
    db.session.commit()
    return jsonify({"ok": True})


# backend/routes/api/admin.py (agrega esto)

@api_admin_bp.get("/users/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.users.read"])
def list_coordinators():
    """
    Lista coordinadores con sus programas (para usar en Admin · Usuarios y combos).
    Filtros opcionales: q (texto), program_id (int).
    """
    from sqlalchemy.orm import joinedload
    from itcj.core.models.coordinator import Coordinator
    from itcj.core.models.program_coordinator import ProgramCoordinator
    from itcj.core.models.program import Program
    from itcj.core.models.user import User

    q = (request.args.get("q") or "").strip().lower()
    program_id = request.args.get("program_id", type=int)

    base = (
        db.session.query(Coordinator)
        .options(joinedload(Coordinator.user))
    )
    if q:
        base = base.join(User).filter(
            (User.full_name.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%"))
        )
    rows = base.all()

    # programas por coord
    prog_map = {}
    if rows:
        coord_ids = [c.id for c in rows]
        links = (db.session.query(ProgramCoordinator.coordinator_id, Program.id, Program.name)
                 .join(Program, Program.id == ProgramCoordinator.program_id)
                 .filter(ProgramCoordinator.coordinator_id.in_(coord_ids))
                 .all())
        for cid, pid, pname in links:
            prog_map.setdefault(cid, []).append({"id": pid, "name": pname})

    items = []
    for c in rows:
        progs = prog_map.get(c.id, [])
        if program_id and all(p["id"] != program_id for p in progs):
            continue
        items.append({
            "id": c.id,
            "user_id": c.user_id,
            "name": c.user.full_name,
            "email": c.contact_email,
            "programs": progs,
        })

    return jsonify({"items": items})

# ---------- Reporte XLSX ----------

@api_admin_bp.post("/reports/requests.xlsx")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.reports.generate"])
def export_requests_xlsx():
    start, end = _range_from_query()
    status = request.args.get("status")
    program_id = request.args.get("program_id", type=int)
    coordinator_id = request.args.get("coordinator_id", type=int)
    q = request.args.get("q", "").strip()

    qry = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.program),
            joinedload(Req.student),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
        .order_by(Req.created_at.desc())
    )
    if status:
        qry = qry.filter(Req.status == status)
    if program_id:
        qry = qry.filter(Req.program_id == program_id)
    if coordinator_id:
        qry = qry.join(Appointment, Appointment.request_id == Req.id).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if q:
        qry = qry.join(User, User.id == Req.student_id).filter(
            or_(User.control_number.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )

    rows = []
    for r in qry.all():
        a = r.appointment
        rows.append(
            {
                "ID": r.id,
                "Tipo": r.type,
                "Estado": r.status,
                "Programa": r.program.name if r.program else None,
                "Alumno": r.student.full_name if r.student else None,
                "NoControl": r.student.control_number if r.student else None,
                "Coord": (a.coordinator.user.full_name if a and a.coordinator and a.coordinator.user else None),
                "CitaID": a.id if a else None,
                "CitaStatus": a.status if a else None,
                "Creado": r.created_at.isoformat() if r.created_at else None,
                "Actualizado": r.updated_at.isoformat() if r.updated_at else None,
            }
        )

    df = pd.DataFrame(rows)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Solicitudes")
    buf.seek(0)
    filename = f"solicitudes_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )

# --- NUEVO: Stats por coordinador (pasteles) ---
@api_admin_bp.get("/stats/coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_coordinators():
    """
    Estadística por coordinador con TODAS las solicitudes.
    - ?from=YYYY-MM-DD&to=YYYY-MM-DD
    - ?rtype=ALL|APPOINTMENT|DROP   (default: ALL)
    - by_day=1   → desglose por día
        * APPOINTMENT: usa TimeSlot.day
        * DROP (u otras sin cita): usa DATE(Request.updated_at)
    - states=1   → agrega campos por estado individual
    """
    start, end = _range_from_query()
    start_date, end_date = start.date(), end.date()

    by_day = (request.args.get("by_day", "0").lower() in ("1", "true", "yes"))
    want_states = (request.args.get("states", "1").lower() in ("1", "true", "yes"))
    rtype = (request.args.get("rtype", "ALL") or "ALL").upper()
    if rtype not in ("ALL", "APPOINTMENT", "DROP"):
        rtype = "ALL"

    # ---- Columnas de agregación comunes (sobre Req.status) ----
    is_pending     = case((Req.status == "PENDING", 1), else_=0)
    is_attended    = case(
        (Req.status.in_(("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT")), 1),
        else_=0
    )
    is_unattended  = case((Req.status.in_(("NO_SHOW", "CANCELED")), 1), else_=0)

    s_ok    = case((Req.status == "RESOLVED_SUCCESS", 1), else_=0)
    s_nok   = case((Req.status == "RESOLVED_NOT_COMPLETED", 1), else_=0)
    s_other = case((Req.status == "ATTENDED_OTHER_SLOT", 1), else_=0)  # será 0 para DROP
    s_nshow = case((Req.status == "NO_SHOW", 1), else_=0)              # será 0 para DROP
    s_canc  = case((Req.status == "CANCELED", 1), else_=0)
    s_pend  = case((Req.status == "PENDING" , 1), else_=0)

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
            cols.insert(2, day_col.label("day"))  # después de coord_name
        return cols

    rows_all = []

    # ---- Subconsulta: APPOINTMENT (por TimeSlot.day) ----
    if rtype in ("ALL", "APPOINTMENT"):
        day_col_ap = TimeSlot.day  # tipo Date
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
        q_ap = q_ap.group_by(*grp_ap).order_by(User.full_name.asc(), *( [day_col_ap.asc()] if by_day else [] ))
        rows_all.extend(q_ap.all())

    # ---- Subconsulta: DROP (u otras sin cita) por Program → ProgramCoordinator ----
    # Día = DATE(updated_at) → "cuando se revisaron"
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
        q_drop = q_drop.group_by(*grp_drop).order_by(User.full_name.asc(), *( [drop_day_col.asc()] if by_day else [] ))
        rows_all.extend(q_drop.all())

    # ---- Reducir / combinar ambas listas de filas ----
    from collections import defaultdict

    overall = defaultdict(int)
    overall_by_day = defaultdict(lambda: defaultdict(int))
    per_coord = {}
    per_coord_days = defaultdict(lambda: defaultdict(int))  # acumular por día y coord

    def add_to_bucket(bucket: dict, r):
        bucket["total"]      = int(bucket.get("total", 0))      + int(r.total or 0)
        bucket["pending"]    = int(bucket.get("pending", 0))    + int(r.pending or 0)
        bucket["attended"]   = int(bucket.get("attended", 0))   + int(r.attended or 0)
        bucket["unattended"] = int(bucket.get("unattended", 0)) + int(r.unattended or 0)
        if want_states:
            st = bucket.setdefault("states", defaultdict(int))
            st["RESOLVED_SUCCESS"]       += int(getattr(r, "resolved_success", 0) or 0)
            st["RESOLVED_NOT_COMPLETED"] += int(getattr(r, "resolved_not_completed", 0) or 0)
            st["ATTENDED_OTHER_SLOT"]    += int(getattr(r, "attended_other_slot", 0) or 0)
            st["NO_SHOW"]                += int(getattr(r, "no_show", 0) or 0)
            st["CANCELED"]               += int(getattr(r, "canceled", 0) or 0)
            st["PENDING"]                += int(getattr(r, "pending", 0) or 0)

    for r in rows_all:
        cid = int(r.coord_id)

        # Crear entrada del coordinador si no existe
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

        # Acumular totales por coordinador y global
        add_to_bucket(per_coord[cid]["totals"], r)
        add_to_bucket(overall, r)

        # Acumular por día (si aplica)
        if by_day:
            # r.day puede ser date o datetime; normalizamos a ISO (YYYY-MM-DD)
            d_iso = (r.day.isoformat() if r.day else None)
            if d_iso:
                # coord + day
                day_bucket = per_coord_days[cid].setdefault(d_iso, {"day": d_iso, "total": 0, "pending": 0, "attended": 0, "unattended": 0})
                if want_states and "states" not in day_bucket:
                    day_bucket["states"] = {
                        "RESOLVED_SUCCESS": 0,
                        "RESOLVED_NOT_COMPLETED": 0,
                        "ATTENDED_OTHER_SLOT": 0,
                        "NO_SHOW": 0,
                        "CANCELED": 0,
                        "PENDING" : 0,
                    }
                add_to_bucket(day_bucket, r)

                # overall by day
                add_to_bucket(overall_by_day[d_iso], r)

    # Serializar coordinadores (orden por nombre)
    coord_list = []
    for cid, obj in sorted(per_coord.items(), key=lambda kv: kv[1]["coordinator_name"] or ""):
        if by_day:
            # pasar map→lista ordenada
            days_map = per_coord_days.get(cid, {})
            obj["days"] = [days_map[k] for k in sorted(days_map.keys())]
        if want_states:
            # a dict plano
            st = obj["totals"].get("states")
            if st and isinstance(st, defaultdict):
                obj["totals"]["states"] = dict(st)
        coord_list.append(obj)

    # Global
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
        # overall_by_day map → lista ordenada
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

#-----------------Email ---------------------
@api_admin_bp.post("/surveys/send")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.surveys.manage"])
def send_surveys():
    """
    Envía correos de encuesta:
      - test=1 → SIEMPRE manda a l21111182@cdjuarez.tecnm.mx (sin importar query)
      - test=0/omitido → usa tu query de alumnos atendidos
    Requiere sesión MSAL delegada activa (pestaña “Conexión Outlook”).
    """
    # 1) token
    token = acquire_token_silent()
    if not token:
        return jsonify({"error": "no_ms_session", "message": "Inicia sesión en la pestaña 'Conexión Outlook'."}), 401

    # 2) filtros
    start, end = _range_from_query()
    limit = request.args.get("limit", type=int) or 200
    offset = request.args.get("offset", type=int) or 0
    is_test = request.args.get("test", "0") in ("1","true","yes")

    # 3) destinatarios
    targets = []
    if is_test:
        targets = ["jefatura_cc@cdjuarez.tecnm.mx"]
    else:
        # EJEMPLO: obtén correos a partir de tus modelos
        from itcj.core.models.user import User
        from itcj.apps.agendatec.models.request import Request as Req
        q = (
            db.session.query(User)
            .join(Req, Req.student_id == User.id)
            .filter(
                Req.status.notin_(["PENDING", "CANCELED", "NO_SHOW"]),
                Req.updated_at >= start,
                Req.updated_at <= end,
            )
            .order_by(Req.updated_at.desc())
            .limit(limit).offset(offset)
        )
        rows = [student_email(e) for (e) in q.all() if e]
        targets = rows

    if not targets:
        return jsonify({"ok": True, "sent": 0, "detail": "Sin destinatarios"}), 200
    # 4) contenido (pon tu Microsoft Forms URL, etc.)
    forms_url = os.getenv("SURVEY_FORMS_URL", "https://forms.office.com/r/xxxxx")
    subject = "Encuesta de satisfacción AgendaTec"
    html = f"""
      <p>¡Hola! 👋</p>
      <p>Si recientemente realizaste un trámite en AgendaTec, para nosotros es muy importante tu opinión en la mejora de nuestros servicios, apóyanos respondiendo está breve encuesta..</p>
      <p>Por favor, responde esta encuesta rápida (menos de 1 minuto):<br>
      <a href="{forms_url}">{forms_url}</a></p>
      <p>¡Gracias!</p>
    """
    # 5) enviar en lotes pequeños (Graph permite varios por minuto, manténlo conservador)
    sent, errors = 0, []
    for addr in targets:
        r = graph_send_mail(token, subject, html, [addr])
        if r.status_code in (202, 200):
            sent += 1
        else:
            errors.append({"to": addr, "status": r.status_code, "body": r.text})

    return jsonify({"ok": True, "sent": sent, "errors": errors, "total_targets": len(targets)})

@api_admin_bp.get("/stats/activity")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.admin_dashboard.read"])
def stats_activity():
    """
    Histograma por hora (0..23) de UPDATED_AT.
    - ?from=YYYY-MM-DD&to=YYYY-MM-DD
    - ?rtype=ALL|APPOINTMENT|DROP (default ALL)
    Devuelve:
      { range, overall: [24], coordinators: [{id,name,hours:[24]}] }
    """
    start, end = _range_from_query()
    rtype = (request.args.get("rtype", "ALL") or "ALL").upper()
    if rtype not in ("ALL", "APPOINTMENT", "DROP"):
        rtype = "ALL"

    # Helpers para acumular
    def _zeros24(): return [0]*24
    overall = _zeros24()
    by_coord = {}

    # ---- APPOINTMENT (join Appointment->Coordinator) ----
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

    # ---- DROP (join Program->ProgramCoordinator->Coordinator) ----
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
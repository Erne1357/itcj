"""
Servicio de Dashboard Departamental para la app de Mantenimiento.

Provee dos niveles de información:
  - summary: KPIs básicos + listas cortas (para dispatcher/secretary).
  - full: KPIs completos + breakdowns por estado/categoría/técnico + SLA (para admin/department_head).

Lógica de alcance:
  - Admin global (JWT role=="admin"): puede consultar cualquier depto o todos.
  - Usuario normal: limitado a los departamentos de sus puestos activos.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local, ensure_local_timezone

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS")
RESOLVED_STATUSES = ("RESOLVED_SUCCESS", "RESOLVED_FAILED")
ALL_STATUSES = (
    "PENDING", "ASSIGNED", "IN_PROGRESS",
    "RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _apply_dept_filter(query, dept_ids: list[int] | None):
    """
    Aplica filtro de departamento a un query sobre MaintTicket.
    Si dept_ids es None o lista vacía → sin filtro (todos los deptos del ITCJ).
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    if dept_ids:
        return query.filter(MaintTicket.requester_department_id.in_(dept_ids))
    return query


def _resolve_user_departments(db: Session, user_id: int) -> list[dict]:
    """
    Retorna [{id, code, name}] de los departamentos de los puestos activos del usuario.
    Puede haber duplicados de departamento si el usuario tiene >1 puesto en el mismo;
    se deduplican por dept_id.
    """
    from itcj2.core.models.position import UserPosition, Position
    from itcj2.core.models.department import Department

    rows = (
        db.query(Department.id, Department.code, Department.name)
        .join(Position, Position.department_id == Department.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active.is_(True),
            Department.is_active.is_(True),
        )
        .distinct()
        .all()
    )
    return [{"id": r.id, "code": r.code, "name": r.name} for r in rows]


def _dept_ids_for_query(
    db: Session,
    user_id: int,
    is_admin_global: bool,
    dept_filter: int | None,
    user_departments: list[dict],
) -> list[int] | None:
    """
    Calcula la lista de dept_ids a usar en el filtro SQL.

    Retorna None si NO debe aplicarse filtro de departamento (= todos).
    Retorna lista (posiblemente con 1 elemento) si debe filtrarse.

    Raises ValueError si dept_filter no pertenece al usuario (y no es admin global).
    """
    if is_admin_global:
        if dept_filter is not None:
            return [dept_filter]
        return None  # Admin global sin filtro → todos los deptos del ITCJ

    # Usuario normal
    user_dept_ids = [d["id"] for d in user_departments]

    if dept_filter is not None:
        if dept_filter not in user_dept_ids:
            raise ValueError(
                f"El departamento {dept_filter} no pertenece a tus puestos activos."
            )
        return [dept_filter]

    # Sin filtro → unión de todos sus deptos
    if not user_dept_ids:
        # El usuario no tiene ningún puesto → devolver lista vacía que producirá 0 resultados
        return [-1]  # ID imposible → 0 resultados
    return user_dept_ids


def _serialize_ticket_summary(ticket, now: datetime) -> dict:
    """Serializa un MaintTicket a dict ligero para las listas del dashboard."""
    due_at = ensure_local_timezone(ticket.due_at) if ticket.due_at else None
    is_overdue = bool(due_at and ticket.status in OPEN_STATUSES and due_at < now)

    # Nombre de la categoría — puede estar lazy-loaded
    try:
        category_name = ticket.category.name if ticket.category else None
    except Exception:
        category_name = None

    # Nombre del solicitante
    try:
        requester_name = ticket.requester.full_name if ticket.requester else None
    except Exception:
        requester_name = None

    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "category_name": category_name,
        "requester_name": requester_name,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "due_at": due_at.isoformat() if due_at else None,
        "is_overdue": is_overdue,
    }


# ─────────────────────────────────────────────────────────────────────────────
# API pública del módulo
# ─────────────────────────────────────────────────────────────────────────────

def get_user_departments(db: Session, user_id: int) -> list[dict]:
    """
    Retorna [{id, code, name}] de los departamentos activos del user vía UserPosition.
    Si el user es admin global (verificar en el endpoint vía JWT), el endpoint
    devuelve lista vacía (= "todos los deptos").
    """
    return _resolve_user_departments(db, user_id)


def get_summary(
    db: Session,
    user_id: int,
    is_admin_global: bool,
    dept_filter: int | None,
) -> dict:
    """
    Resumen para dispatcher/secretary.

    Retorna:
      {
        "kpis": {
          "open_total": int,
          "unassigned": int,
          "in_progress": int,
          "overdue": int,
          "resolved_this_week": int,
        },
        "unassigned_tickets": [...max 10],
        "recent_open": [...max 5],
      }

    Raises ValueError si dept_filter no pertenece al usuario.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician

    now = now_local()
    week_start = now - timedelta(days=now.weekday())  # Lunes de esta semana
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    user_departments = _resolve_user_departments(db, user_id)
    dept_ids = _dept_ids_for_query(db, user_id, is_admin_global, dept_filter, user_departments)

    base_q = _apply_dept_filter(db.query(MaintTicket), dept_ids)

    # KPI: open_total (PENDING + ASSIGNED + IN_PROGRESS)
    open_total = (
        base_q.filter(MaintTicket.status.in_(OPEN_STATUSES))
        .count()
    )

    # KPI: in_progress
    in_progress = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(MaintTicket.status == "IN_PROGRESS")
        .count()
    )

    # KPI: overdue (open AND due_at < now)
    overdue = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(OPEN_STATUSES),
            MaintTicket.due_at < now,
        )
        .count()
    )

    # KPI: resolved_this_week
    resolved_this_week = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.resolved_at >= week_start,
        )
        .count()
    )

    # KPI: unassigned (PENDING sin técnicos activos)
    # Subconsulta: ticket_ids que tienen al menos un técnico activo
    assigned_ticket_ids_sq = (
        db.query(MaintTicketTechnician.ticket_id)
        .filter(MaintTicketTechnician.unassigned_at.is_(None))
        .subquery()
    )
    unassigned = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status == "PENDING",
            MaintTicket.id.not_in(
                db.query(assigned_ticket_ids_sq.c.ticket_id)
            ),
        )
        .count()
    )

    # Lista: unassigned_tickets (máx 10, por priority desc + created_at asc)
    from sqlalchemy import case as sa_case

    priority_order = sa_case(
        (MaintTicket.priority == "URGENTE", 0),
        (MaintTicket.priority == "ALTA", 1),
        (MaintTicket.priority == "MEDIA", 2),
        (MaintTicket.priority == "BAJA", 3),
        else_=99,
    )

    unassigned_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status == "PENDING",
            MaintTicket.id.not_in(
                db.query(assigned_ticket_ids_sq.c.ticket_id)
            ),
        )
        .order_by(priority_order.asc(), MaintTicket.created_at.asc())
        .limit(10)
        .all()
    )

    # Lista: recent_open (últimos 5 abiertos por created_at desc)
    recent_open_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(MaintTicket.status.in_(OPEN_STATUSES))
        .order_by(MaintTicket.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "kpis": {
            "open_total": open_total,
            "unassigned": unassigned,
            "in_progress": in_progress,
            "overdue": overdue,
            "resolved_this_week": resolved_this_week,
        },
        "unassigned_tickets": [_serialize_ticket_summary(t, now) for t in unassigned_rows],
        "recent_open": [_serialize_ticket_summary(t, now) for t in recent_open_rows],
    }


def get_full(
    db: Session,
    user_id: int,
    is_admin_global: bool,
    dept_filter: int | None,
) -> dict:
    """
    Dashboard completo para admin/department_head.

    Retorna:
      {
        "kpis": { ...summary kpis + avg_resolution_hours, rated_count, rated_pct },
        "by_status": { "PENDING": N, ... },
        "by_category": [{"code", "name", "count"}, ...],
        "by_technician": [{"user_id", "name", "active_count", "resolved_count"}, ...max 10],
        "sla_breakdown": { "on_time": int, "overdue_open": int, "overdue_resolved": int },
        "recent_open": [...max 10],
        "overdue_tickets": [...max 10],
      }

    Raises ValueError si dept_filter no pertenece al usuario.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician
    from itcj2.apps.maint.models.category import MaintCategory
    from itcj2.core.models.user import User

    now = now_local()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    user_departments = _resolve_user_departments(db, user_id)
    dept_ids = _dept_ids_for_query(db, user_id, is_admin_global, dept_filter, user_departments)

    base_q = _apply_dept_filter(db.query(MaintTicket), dept_ids)

    # ── by_status ────────────────────────────────────────────────────────────
    status_rows = (
        base_q.with_entities(MaintTicket.status, func.count(MaintTicket.id))
        .group_by(MaintTicket.status)
        .all()
    )
    by_status = {s: 0 for s in ALL_STATUSES}
    for status, count in status_rows:
        if status in by_status:
            by_status[status] = count

    # ── KPIs básicos ─────────────────────────────────────────────────────────
    open_total = sum(by_status[s] for s in OPEN_STATUSES)
    in_progress = by_status.get("IN_PROGRESS", 0)

    overdue = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(OPEN_STATUSES),
            MaintTicket.due_at < now,
        )
        .count()
    )

    resolved_this_week = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.resolved_at >= week_start,
        )
        .count()
    )

    # ── KPI: unassigned ──────────────────────────────────────────────────────
    assigned_ticket_ids_sq = (
        db.query(MaintTicketTechnician.ticket_id)
        .filter(MaintTicketTechnician.unassigned_at.is_(None))
        .subquery()
    )
    unassigned = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status == "PENDING",
            MaintTicket.id.not_in(
                db.query(assigned_ticket_ids_sq.c.ticket_id)
            ),
        )
        .count()
    )

    # ── KPI: avg_resolution_hours ─────────────────────────────────────────────
    avg_row = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .with_entities(func.avg(MaintTicket.time_invested_minutes))
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.time_invested_minutes.isnot(None),
        )
        .scalar()
    )
    avg_resolution_hours = round(float(avg_row) / 60, 2) if avg_row is not None else None

    # ── KPI: rated_count, rated_pct ──────────────────────────────────────────
    resolved_total = sum(by_status[s] for s in RESOLVED_STATUSES) + by_status.get("CLOSED", 0)
    rated_count = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.rating_attention.isnot(None),
        )
        .count()
    )
    rated_pct = round((rated_count / resolved_total) * 100, 1) if resolved_total > 0 else 0.0

    # ── by_category ───────────────────────────────────────────────────────────
    cat_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(MaintTicket.status.in_(OPEN_STATUSES))
        .with_entities(MaintTicket.category_id, func.count(MaintTicket.id))
        .group_by(MaintTicket.category_id)
        .all()
    )
    open_by_cat = {cat_id: cnt for cat_id, cnt in cat_rows}

    categories = (
        db.query(MaintCategory)
        .filter_by(is_active=True)
        .order_by(MaintCategory.display_order)
        .all()
    )
    by_category = [
        {
            "code": cat.code,
            "name": cat.name,
            "count": open_by_cat.get(cat.id, 0),
        }
        for cat in categories
        if open_by_cat.get(cat.id, 0) > 0
    ]

    # ── by_technician (top 10 por tickets activos) ────────────────────────────
    # Tickets activos por técnico en el scope de departamentos
    active_tech_rows = (
        db.query(MaintTicketTechnician.user_id, func.count(MaintTicketTechnician.id).label("active_count"))
        .join(MaintTicket, MaintTicketTechnician.ticket_id == MaintTicket.id)
        .filter(
            MaintTicketTechnician.unassigned_at.is_(None),
            MaintTicket.status.in_(OPEN_STATUSES),
        )
    )
    if dept_ids:
        active_tech_rows = active_tech_rows.filter(
            MaintTicket.requester_department_id.in_(dept_ids)
        )
    active_tech_rows = (
        active_tech_rows
        .group_by(MaintTicketTechnician.user_id)
        .order_by(func.count(MaintTicketTechnician.id).desc())
        .limit(10)
        .all()
    )

    # Tickets resueltos por técnico (resolved_by_id en el scope)
    resolved_tech_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.resolved_by_id.isnot(None),
        )
        .with_entities(MaintTicket.resolved_by_id, func.count(MaintTicket.id))
        .group_by(MaintTicket.resolved_by_id)
        .all()
    )
    resolved_by_tech = {uid: cnt for uid, cnt in resolved_tech_rows}

    # Cargar nombres de usuarios
    tech_ids = {row.user_id for row in active_tech_rows} | set(resolved_by_tech.keys())
    if tech_ids:
        users = db.query(User).filter(User.id.in_(tech_ids)).all()
        users_map = {u.id: u.full_name for u in users}
    else:
        users_map = {}

    by_technician = [
        {
            "user_id": row.user_id,
            "name": users_map.get(row.user_id, f"Usuario {row.user_id}"),
            "active_count": row.active_count,
            "resolved_count": resolved_by_tech.get(row.user_id, 0),
        }
        for row in active_tech_rows
    ]

    # ── SLA breakdown ─────────────────────────────────────────────────────────
    # on_time: tickets resueltos con resolved_at <= due_at (o sin due_at)
    on_time = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            (MaintTicket.due_at.is_(None)) | (MaintTicket.resolved_at <= MaintTicket.due_at),
        )
        .count()
    )
    # overdue_open: abiertos vencidos
    overdue_open = overdue
    # overdue_resolved: resueltos que se pasaron del SLA
    overdue_resolved = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES + ("CLOSED",)),
            MaintTicket.due_at.isnot(None),
            MaintTicket.resolved_at > MaintTicket.due_at,
        )
        .count()
    )

    # ── recent_open (últimos 10 abiertos) ────────────────────────────────────
    recent_open_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(MaintTicket.status.in_(OPEN_STATUSES))
        .order_by(MaintTicket.created_at.desc())
        .limit(10)
        .all()
    )

    # ── overdue_tickets (máx 10, más antiguos primero) ───────────────────────
    overdue_rows = (
        _apply_dept_filter(db.query(MaintTicket), dept_ids)
        .filter(
            MaintTicket.status.in_(OPEN_STATUSES),
            MaintTicket.due_at < now,
        )
        .order_by(MaintTicket.due_at.asc())
        .limit(10)
        .all()
    )

    return {
        "kpis": {
            "open_total": open_total,
            "unassigned": unassigned,
            "in_progress": in_progress,
            "overdue": overdue,
            "resolved_this_week": resolved_this_week,
            "avg_resolution_hours": avg_resolution_hours,
            "rated_count": rated_count,
            "rated_pct": rated_pct,
        },
        "by_status": by_status,
        "by_category": by_category,
        "by_technician": by_technician,
        "sla_breakdown": {
            "on_time": on_time,
            "overdue_open": overdue_open,
            "overdue_resolved": overdue_resolved,
        },
        "recent_open": [_serialize_ticket_summary(t, now) for t in recent_open_rows],
        "overdue_tickets": [_serialize_ticket_summary(t, now) for t in overdue_rows],
    }

"""
Servicio de reportes de alto nivel para mantenimiento.

Genera series de tiempo y agregados por período para consumo
de gráficas en el módulo de reportes.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

RESOLVED_STATUSES = ("RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _date_range(from_date: date, to_date: date) -> list[date]:
    """Genera lista de dates [from_date, …, to_date] inclusive."""
    days = []
    cur = from_date
    while cur <= to_date:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _to_datetime_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0)


def _to_datetime_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59)


# ─────────────────────────────────────────────────────────────────────────────
# Tickets time series
# ─────────────────────────────────────────────────────────────────────────────

def get_tickets_time_series(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
) -> dict:
    """Serie de tiempo de tickets creados vs resueltos por día."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    dt_start = _to_datetime_start(from_date)
    dt_end = _to_datetime_end(to_date)

    base_filter = []
    if category_id:
        base_filter.append(MaintTicket.category_id == category_id)

    # Creados por día
    created_rows = (
        db.query(
            func.date(MaintTicket.created_at).label("day"),
            func.count(MaintTicket.id).label("count"),
        )
        .filter(
            MaintTicket.created_at >= dt_start,
            MaintTicket.created_at <= dt_end,
            *base_filter,
        )
        .group_by(func.date(MaintTicket.created_at))
        .all()
    )
    created_map = {str(row.day): row.count for row in created_rows}

    # Resueltos por día (fecha de resolved_at)
    resolved_rows = (
        db.query(
            func.date(MaintTicket.resolved_at).label("day"),
            func.count(MaintTicket.id).label("count"),
        )
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES),
            MaintTicket.resolved_at >= dt_start,
            MaintTicket.resolved_at <= dt_end,
            *base_filter,
        )
        .group_by(func.date(MaintTicket.resolved_at))
        .all()
    )
    resolved_map = {str(row.day): row.count for row in resolved_rows}

    days = _date_range(from_date, to_date)
    data = [
        {
            "date": str(d),
            "created": created_map.get(str(d), 0),
            "resolved": resolved_map.get(str(d), 0),
        }
        for d in days
    ]

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# Technician aggregates
# ─────────────────────────────────────────────────────────────────────────────

def get_technician_report(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
) -> dict:
    """Agregados por técnico: resueltos, tiempo promedio, ratings, SLA."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.core.models.user import User

    dt_start = _to_datetime_start(from_date)
    dt_end = _to_datetime_end(to_date)

    filters = [
        MaintTicket.status.in_(RESOLVED_STATUSES),
        MaintTicket.resolved_at >= dt_start,
        MaintTicket.resolved_at <= dt_end,
        MaintTicket.resolved_by_id.isnot(None),
    ]
    if category_id:
        filters.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            MaintTicket.resolved_by_id,
            func.count(MaintTicket.id).label("resolved_count"),
            func.avg(MaintTicket.time_invested_minutes).label("avg_time_invested"),
            func.avg(MaintTicket.rating_attention).label("avg_rating_attention"),
            func.avg(MaintTicket.rating_speed).label("avg_rating_speed"),
            func.sum(
                case((MaintTicket.rating_efficiency == True, 1), else_=0)
            ).label("efficient_count"),
            func.sum(
                case(
                    (
                        and_(
                            MaintTicket.due_at.isnot(None),
                            MaintTicket.resolved_at <= MaintTicket.due_at,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sla_ok_count"),
            func.sum(
                case((MaintTicket.rating_efficiency.isnot(None), 1), else_=0)
            ).label("rated_efficiency_count"),
            func.sum(
                case((MaintTicket.due_at.isnot(None), 1), else_=0)
            ).label("with_due_at_count"),
        )
        .filter(*filters)
        .group_by(MaintTicket.resolved_by_id)
        .order_by(func.count(MaintTicket.id).desc())
        .all()
    )

    tech_ids = [r.resolved_by_id for r in rows]
    users_map: dict[int, str] = {}
    if tech_ids:
        users = db.query(User).filter(User.id.in_(tech_ids)).all()
        users_map = {u.id: u.full_name for u in users}

    data = []
    for r in rows:
        resolved = r.resolved_count or 0
        rated_eff = r.rated_efficiency_count or 0
        with_due = r.with_due_at_count or 0
        data.append(
            {
                "user_id": r.resolved_by_id,
                "name": users_map.get(r.resolved_by_id, f"Usuario {r.resolved_by_id}"),
                "resolved_count": resolved,
                "avg_time_invested_minutes": round(float(r.avg_time_invested), 1) if r.avg_time_invested else None,
                "avg_rating_attention": round(float(r.avg_rating_attention), 2) if r.avg_rating_attention else None,
                "avg_rating_speed": round(float(r.avg_rating_speed), 2) if r.avg_rating_speed else None,
                "pct_efficient": round(r.efficient_count / rated_eff * 100, 1) if rated_eff else None,
                "pct_sla_cumplido": round(r.sla_ok_count / with_due * 100, 1) if with_due else None,
            }
        )

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# Category aggregates
# ─────────────────────────────────────────────────────────────────────────────

def get_category_report(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
) -> dict:
    """Agregados por categoría: total, abiertos, resueltos, tiempo promedio."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.category import MaintCategory

    OPEN_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS")

    dt_start = _to_datetime_start(from_date)
    dt_end = _to_datetime_end(to_date)

    base_filters = [
        MaintTicket.created_at >= dt_start,
        MaintTicket.created_at <= dt_end,
    ]
    if category_id:
        base_filters.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            MaintTicket.category_id,
            func.count(MaintTicket.id).label("total"),
            func.sum(
                case((MaintTicket.status.in_(OPEN_STATUSES), 1), else_=0)
            ).label("open_count"),
            func.sum(
                case((MaintTicket.status.in_(RESOLVED_STATUSES), 1), else_=0)
            ).label("resolved_count"),
            func.avg(
                case(
                    (MaintTicket.status.in_(RESOLVED_STATUSES), MaintTicket.time_invested_minutes),
                    else_=None,
                )
            ).label("avg_resolution_minutes"),
        )
        .filter(*base_filters)
        .group_by(MaintTicket.category_id)
        .all()
    )

    cat_ids = [r.category_id for r in rows]
    cats_map: dict[int, MaintCategory] = {}
    if cat_ids:
        cats = db.query(MaintCategory).filter(MaintCategory.id.in_(cat_ids)).all()
        cats_map = {c.id: c for c in cats}

    data = [
        {
            "category_id": r.category_id,
            "category_code": cats_map[r.category_id].code if r.category_id in cats_map else None,
            "category_name": cats_map[r.category_id].name if r.category_id in cats_map else f"Cat {r.category_id}",
            "total": r.total,
            "open": r.open_count or 0,
            "resolved": r.resolved_count or 0,
            "avg_resolution_minutes": round(float(r.avg_resolution_minutes), 1) if r.avg_resolution_minutes else None,
        }
        for r in rows
    ]

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# SLA report
# ─────────────────────────────────────────────────────────────────────────────

def get_sla_report(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
) -> dict:
    """Resumen de cumplimiento SLA para tickets resueltos en el rango."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    dt_start = _to_datetime_start(from_date)
    dt_end = _to_datetime_end(to_date)

    filters = [
        MaintTicket.status.in_(RESOLVED_STATUSES),
        MaintTicket.resolved_at >= dt_start,
        MaintTicket.resolved_at <= dt_end,
    ]
    if category_id:
        filters.append(MaintTicket.category_id == category_id)

    row = (
        db.query(
            func.count(MaintTicket.id).label("total_resolved"),
            func.sum(
                case((MaintTicket.due_at.isnot(None), 1), else_=0)
            ).label("with_due_at"),
            func.sum(
                case(
                    (
                        and_(
                            MaintTicket.due_at.isnot(None),
                            MaintTicket.resolved_at <= MaintTicket.due_at,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("on_time"),
            func.sum(
                case(
                    (
                        and_(
                            MaintTicket.due_at.isnot(None),
                            MaintTicket.resolved_at > MaintTicket.due_at,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("overdue"),
            func.avg(
                case(
                    (
                        and_(
                            MaintTicket.due_at.isnot(None),
                            MaintTicket.resolved_at > MaintTicket.due_at,
                        ),
                        func.extract(
                            "epoch",
                            MaintTicket.resolved_at - MaintTicket.due_at,
                        ) / 3600.0,
                    ),
                    else_=None,
                )
            ).label("avg_overrun_hours"),
        )
        .filter(*filters)
        .one()
    )

    total = row.total_resolved or 0
    with_due = row.with_due_at or 0
    on_time = row.on_time or 0
    overdue = row.overdue or 0

    data = {
        "total_resolved": total,
        "with_due_at": with_due,
        "on_time": on_time,
        "overdue": overdue,
        "pct_on_time": round(on_time / with_due * 100, 1) if with_due else None,
        "pct_overdue": round(overdue / with_due * 100, 1) if with_due else None,
        "avg_overrun_hours": round(float(row.avg_overrun_hours), 2) if row.avg_overrun_hours else None,
    }

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}

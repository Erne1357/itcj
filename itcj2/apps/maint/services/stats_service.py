"""
Servicio de estadísticas analíticas para mantenimiento.

Provee breakdowns globales, por técnico, por categoría,
tiempos de transición, distribución de ratings y heatmaps.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, case, and_, text
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

RESOLVED_STATUSES = ("RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED")
OPEN_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS")
ALL_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS", "RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED", "CANCELED")


def _dt_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0)


def _dt_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59)


# ─────────────────────────────────────────────────────────────────────────────
# Global stats
# ─────────────────────────────────────────────────────────────────────────────

def get_global_stats(db: Session, from_date: date, to_date: date, category_id: int | None = None) -> dict:
    """Totales y breakdowns por estado, categoría y prioridad en el rango."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.category import MaintCategory

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    base = [
        MaintTicket.created_at >= dt_start,
        MaintTicket.created_at <= dt_end,
    ]
    if category_id:
        base.append(MaintTicket.category_id == category_id)

    total = db.query(func.count(MaintTicket.id)).filter(*base).scalar() or 0

    # by_status
    status_rows = (
        db.query(MaintTicket.status, func.count(MaintTicket.id))
        .filter(*base)
        .group_by(MaintTicket.status)
        .all()
    )
    by_status = {s: 0 for s in ALL_STATUSES}
    for status, cnt in status_rows:
        if status in by_status:
            by_status[status] = cnt

    # by_priority
    priority_rows = (
        db.query(MaintTicket.priority, func.count(MaintTicket.id))
        .filter(*base)
        .group_by(MaintTicket.priority)
        .all()
    )
    by_priority = {"BAJA": 0, "MEDIA": 0, "ALTA": 0, "URGENTE": 0}
    for priority, cnt in priority_rows:
        if priority in by_priority:
            by_priority[priority] = cnt

    # by_category
    cat_rows = (
        db.query(MaintTicket.category_id, func.count(MaintTicket.id))
        .filter(*base)
        .group_by(MaintTicket.category_id)
        .all()
    )
    cat_ids = [r[0] for r in cat_rows]
    cats_map: dict[int, MaintCategory] = {}
    if cat_ids:
        cats = db.query(MaintCategory).filter(MaintCategory.id.in_(cat_ids)).all()
        cats_map = {c.id: c for c in cats}
    by_category = [
        {
            "category_id": cat_id,
            "category_name": cats_map[cat_id].name if cat_id in cats_map else f"Cat {cat_id}",
            "count": cnt,
        }
        for cat_id, cnt in cat_rows
    ]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "data": {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# By technician
# ─────────────────────────────────────────────────────────────────────────────

def get_by_technician(db: Session, from_date: date, to_date: date, category_id: int | None = None) -> dict:
    """Stats por técnico: asignados, resueltos, tiempo promedio, rating, SLA."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.ticket_technician import MaintTicketTechnician
    from itcj2.core.models.user import User

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    cat_filter = []
    if category_id:
        cat_filter.append(MaintTicket.category_id == category_id)

    # Cantidad asignada (por MaintTicketTechnician, ticket creado en rango)
    assigned_rows = (
        db.query(
            MaintTicketTechnician.user_id,
            func.count(MaintTicketTechnician.id).label("assigned_count"),
        )
        .join(MaintTicket, MaintTicketTechnician.ticket_id == MaintTicket.id)
        .filter(
            MaintTicket.created_at >= dt_start,
            MaintTicket.created_at <= dt_end,
            *cat_filter,
        )
        .group_by(MaintTicketTechnician.user_id)
        .all()
    )
    assigned_map = {r.user_id: r.assigned_count for r in assigned_rows}

    # Resueltos (por resolved_by_id)
    resolved_rows = (
        db.query(
            MaintTicket.resolved_by_id,
            func.count(MaintTicket.id).label("resolved_count"),
            func.avg(MaintTicket.time_invested_minutes).label("avg_time"),
            func.avg(MaintTicket.rating_attention).label("avg_rating_attention"),
            func.avg(MaintTicket.rating_speed).label("avg_rating_speed"),
            func.sum(
                case((MaintTicket.due_at.isnot(None), 1), else_=0)
            ).label("with_due"),
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
            ).label("sla_ok"),
        )
        .filter(
            MaintTicket.status.in_(RESOLVED_STATUSES),
            MaintTicket.resolved_at >= dt_start,
            MaintTicket.resolved_at <= dt_end,
            MaintTicket.resolved_by_id.isnot(None),
            *cat_filter,
        )
        .group_by(MaintTicket.resolved_by_id)
        .all()
    )
    resolved_map = {r.resolved_by_id: r for r in resolved_rows}

    # resolved_map keyed by resolved_by_id
    all_tech_ids = set(assigned_map) | {r.resolved_by_id for r in resolved_rows}
    users_map: dict[int, str] = {}
    if all_tech_ids:
        users = db.query(User).filter(User.id.in_(all_tech_ids)).all()
        users_map = {u.id: u.full_name for u in users}

    data = []
    for tech_id in sorted(all_tech_ids):
        r = resolved_map.get(tech_id)
        with_due = (r.with_due or 0) if r else 0
        data.append(
            {
                "user_id": tech_id,
                "name": users_map.get(tech_id, f"Usuario {tech_id}"),
                "assigned_count": assigned_map.get(tech_id, 0),
                "resolved_count": r.resolved_count if r else 0,
                "avg_time_invested_minutes": round(float(r.avg_time), 1) if r and r.avg_time else None,
                "avg_rating_attention": round(float(r.avg_rating_attention), 2) if r and r.avg_rating_attention else None,
                "avg_rating_speed": round(float(r.avg_rating_speed), 2) if r and r.avg_rating_speed else None,
                "pct_sla_cumplido": round(r.sla_ok / with_due * 100, 1) if r and with_due else None,
            }
        )

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# By category
# ─────────────────────────────────────────────────────────────────────────────

def get_by_category(db: Session, from_date: date, to_date: date, category_id: int | None = None) -> dict:
    """Cantidad, abiertos, cerrados y tasa de cancelación por categoría."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.category import MaintCategory

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    base = [
        MaintTicket.created_at >= dt_start,
        MaintTicket.created_at <= dt_end,
    ]
    if category_id:
        base.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            MaintTicket.category_id,
            func.count(MaintTicket.id).label("total"),
            func.sum(case((MaintTicket.status.in_(OPEN_STATUSES), 1), else_=0)).label("open_count"),
            func.sum(case((MaintTicket.status.in_(RESOLVED_STATUSES), 1), else_=0)).label("resolved_count"),
            func.sum(case((MaintTicket.status == "CANCELED", 1), else_=0)).label("canceled_count"),
        )
        .filter(*base)
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
            "canceled": r.canceled_count or 0,
            "cancellation_rate": round((r.canceled_count or 0) / r.total * 100, 1) if r.total else 0.0,
        }
        for r in rows
    ]

    return {"range": {"from": str(from_date), "to": str(to_date)}, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# Time breakdown (via status_logs)
# ─────────────────────────────────────────────────────────────────────────────

def get_time_breakdown(db: Session, from_date: date, to_date: date, category_id: int | None = None) -> dict:
    """Tiempo promedio (minutos) en cada transición de estado usando status_logs."""
    from itcj2.apps.maint.models.status_log import MaintStatusLog
    from itcj2.apps.maint.models.ticket import MaintTicket

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    # Para cada transición A→B calculamos: avg(tiempo entre log A y log B para el mismo ticket)
    # Usamos SQL directo (self-join sobre status_logs) para eficiencia.
    # La tabla maint_status_logs tiene: ticket_id, from_status, to_status, created_at

    transitions = [
        ("PENDING", "ASSIGNED", "pending_to_assigned_minutes"),
        ("ASSIGNED", "IN_PROGRESS", "assigned_to_in_progress_minutes"),
        ("IN_PROGRESS", "RESOLVED_SUCCESS", "in_progress_to_resolved_minutes"),
    ]

    cat_join = ""
    cat_param: dict = {}
    if category_id:
        cat_join = "JOIN maint_tickets t ON sl.ticket_id = t.id"
        cat_param["category_id"] = category_id

    result: dict[str, float | None] = {}

    for from_s, to_s, key in transitions:
        # Find pairs: same ticket, log that arrived at from_s, then log that arrived at to_s
        # We use the to_status column: a row with to_status='ASSIGNED' means transition → ASSIGNED
        q = text(f"""
            SELECT AVG(
                EXTRACT(EPOCH FROM (sl2.created_at - sl1.created_at)) / 60.0
            )
            FROM maint_status_logs sl1
            JOIN maint_status_logs sl2
                ON sl1.ticket_id = sl2.ticket_id
                AND sl2.created_at > sl1.created_at
            {cat_join}
            WHERE sl1.to_status = :from_s
              AND sl2.to_status = :to_s
              AND sl1.created_at >= :dt_start
              AND sl1.created_at <= :dt_end
              {"AND t.category_id = :category_id" if category_id else ""}
        """)
        params = {"from_s": from_s, "to_s": to_s, "dt_start": dt_start, "dt_end": dt_end, **cat_param}
        val = db.execute(q, params).scalar()
        result[key] = round(float(val), 1) if val is not None else None

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "data": result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ratings detail
# ─────────────────────────────────────────────────────────────────────────────

def get_ratings_detail(db: Session, from_date: date, to_date: date, category_id: int | None = None) -> dict:
    """Distribución de ratings 1-5, % rating_efficiency, rated vs unrated."""
    from itcj2.apps.maint.models.ticket import MaintTicket

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    base = [
        MaintTicket.status.in_(RESOLVED_STATUSES),
        MaintTicket.resolved_at >= dt_start,
        MaintTicket.resolved_at <= dt_end,
    ]
    if category_id:
        base.append(MaintTicket.category_id == category_id)

    total_resolved = db.query(func.count(MaintTicket.id)).filter(*base).scalar() or 0
    total_rated = (
        db.query(func.count(MaintTicket.id))
        .filter(*base, MaintTicket.rating_attention.isnot(None))
        .scalar() or 0
    )
    total_unrated = total_resolved - total_rated

    # Distribution by rating value (1-5)
    def _dist(col):
        rows = (
            db.query(col, func.count(MaintTicket.id))
            .filter(*base, col.isnot(None))
            .group_by(col)
            .all()
        )
        dist = {i: 0 for i in range(1, 6)}
        for val, cnt in rows:
            if val in dist:
                dist[val] = cnt
        return dist

    rating_attention_dist = _dist(MaintTicket.rating_attention)
    rating_speed_dist = _dist(MaintTicket.rating_speed)

    # % efficiency
    efficient_count = (
        db.query(func.count(MaintTicket.id))
        .filter(*base, MaintTicket.rating_efficiency == True)
        .scalar() or 0
    )
    with_efficiency = (
        db.query(func.count(MaintTicket.id))
        .filter(*base, MaintTicket.rating_efficiency.isnot(None))
        .scalar() or 0
    )

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "data": {
            "total_resolved": total_resolved,
            "total_rated": total_rated,
            "total_unrated": total_unrated,
            "rating_attention_distribution": rating_attention_dist,
            "rating_speed_distribution": rating_speed_dist,
            "pct_rating_efficiency_true": round(efficient_count / with_efficiency * 100, 1) if with_efficiency else None,
            "efficient_count": efficient_count,
            "with_efficiency_count": with_efficiency,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Heatmap
# ─────────────────────────────────────────────────────────────────────────────

def get_heatmap_by_location(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
    top_n: int = 30,
) -> dict:
    """Heatmap location × category_id con top N ubicaciones."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.category import MaintCategory

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    base = [
        MaintTicket.created_at >= dt_start,
        MaintTicket.created_at <= dt_end,
        MaintTicket.location.isnot(None),
    ]
    if category_id:
        base.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            func.lower(func.trim(MaintTicket.location)).label("loc"),
            MaintTicket.category_id,
            func.count(MaintTicket.id).label("cnt"),
        )
        .filter(*base)
        .group_by(func.lower(func.trim(MaintTicket.location)), MaintTicket.category_id)
        .all()
    )

    # Top N locations by total count
    loc_totals: dict[str, int] = {}
    for r in rows:
        loc_totals[r.loc] = loc_totals.get(r.loc, 0) + r.cnt
    top_locs = sorted(loc_totals, key=lambda l: loc_totals[l], reverse=True)[:top_n]
    top_locs_set = set(top_locs)

    # Categories in data
    cat_ids_in = sorted({r.category_id for r in rows if r.loc in top_locs_set})
    cats_map: dict[int, MaintCategory] = {}
    if cat_ids_in:
        cats = db.query(MaintCategory).filter(MaintCategory.id.in_(cat_ids_in)).all()
        cats_map = {c.id: c for c in cats}

    # Build cell map
    cell: dict[tuple[str, int], int] = {}
    for r in rows:
        if r.loc in top_locs_set:
            cell[(r.loc, r.category_id)] = r.cnt

    x_labels = [cats_map[c].name if c in cats_map else f"Cat {c}" for c in cat_ids_in]
    y_labels = top_locs  # already sorted by count desc

    matrix = [
        [cell.get((loc, cat_id), 0) for cat_id in cat_ids_in]
        for loc in top_locs
    ]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "group_by": "location",
        "axes": {"x": x_labels, "y": y_labels},
        "matrix": matrix,
    }


def get_heatmap_by_building(
    db: Session,
    from_date: date,
    to_date: date,
    category_id: int | None = None,
) -> dict:
    """Heatmap building × month-of-created_at."""
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.utils.location_parser import parse_building

    dt_start = _dt_start(from_date)
    dt_end = _dt_end(to_date)

    base = [
        MaintTicket.created_at >= dt_start,
        MaintTicket.created_at <= dt_end,
    ]
    if category_id:
        base.append(MaintTicket.category_id == category_id)

    rows = (
        db.query(
            MaintTicket.location,
            func.to_char(MaintTicket.created_at, "YYYY-MM").label("month"),
            func.count(MaintTicket.id).label("cnt"),
        )
        .filter(*base)
        .group_by(MaintTicket.location, func.to_char(MaintTicket.created_at, "YYYY-MM"))
        .all()
    )

    # Aggregate into building → month → count
    cell: dict[tuple[str, str], int] = {}
    months_set: set[str] = set()
    buildings_set: set[str] = set()

    for r in rows:
        building = parse_building(r.location)
        month = r.month
        months_set.add(month)
        buildings_set.add(building)
        key = (building, month)
        cell[key] = cell.get(key, 0) + r.cnt

    x_labels = sorted(months_set)
    y_labels = sorted(buildings_set, key=lambda b: (b == "Sin clasificar", b))

    matrix = [
        [cell.get((building, month), 0) for month in x_labels]
        for building in y_labels
    ]

    return {
        "range": {"from": str(from_date), "to": str(to_date)},
        "group_by": "building",
        "axes": {"x": x_labels, "y": y_labels},
        "matrix": matrix,
    }

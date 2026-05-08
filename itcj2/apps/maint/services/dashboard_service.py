"""
Dashboard service para la app de Mantenimiento.

Calcula los KPIs del dashboard filtrando por el scope de visibilidad
del usuario (mismo criterio que ticket_service.list_tickets).

NOTA: El bloque de visibilidad se duplica aquí intencionalmente en lugar de
extraerlo a un helper, para no modificar ticket_service.py.
Mantener sincronizado con la lógica en ticket_service.list_tickets.
"""
import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

FULL_ACCESS_ROLES = frozenset({'admin', 'dispatcher', 'tech_maint'})
DEPT_ACCESS_ROLES = frozenset({'department_head', 'secretary'})
OPEN_STATUSES = ('PENDING', 'ASSIGNED', 'IN_PROGRESS')
ALL_STATUSES = ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de visibilidad  (keep in sync with ticket_service.list_tickets)
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_dept_id(db: Session, user_id: int) -> int | None:
    """Devuelve el department_id activo del usuario, o None si no se puede determinar."""
    try:
        from itcj2.core.models.position import UserPosition
        up = db.query(UserPosition).filter_by(user_id=user_id, is_active=True).first()
        if up and up.position:
            return up.position.department_id
    except Exception:
        pass
    return None


def _apply_visibility(query, user_id: int, user_roles: list, db: Session):
    """
    Aplica el filtro de visibilidad a un query sobre MaintTicket.
    Devuelve el query modificado.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    roles = set(user_roles)

    if FULL_ACCESS_ROLES & roles:
        return query  # Sin restricción

    if DEPT_ACCESS_ROLES & roles:
        dept_id = _resolve_dept_id(db, user_id)
        if dept_id:
            return query.filter(MaintTicket.requester_department_id == dept_id)
        # Sin departamento resuelto → retornar nada (seguro)
        return query.filter(MaintTicket.id == -1)

    # staff / resto → solo propios
    return query.filter(MaintTicket.requester_id == user_id)


# ──────────────────────────────────────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────────────────────────────────────

def get_dashboard(db: Session, user_id: int, user_roles: list) -> dict:
    """
    Devuelve todos los KPIs del dashboard para el usuario dado.
    El scope de datos respeta la misma lógica de visibilidad que list_tickets.
    """
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models.category import MaintCategory
    from itcj2.apps.maint.models.action_log import MaintTicketActionLog
    from itcj2.core.models.user import User

    roles = set(user_roles)
    now = now_local()
    cutoff_30d = now - timedelta(days=30)
    cutoff_24h = now - timedelta(hours=24)

    # ── Base query con visibilidad ─────────────────────────────────────────
    base_q = _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)

    # ── by_status ─────────────────────────────────────────────────────────
    status_rows = (
        base_q.with_entities(MaintTicket.status, func.count(MaintTicket.id))
        .group_by(MaintTicket.status)
        .all()
    )
    by_status = {s: 0 for s in ALL_STATUSES}
    for status, count in status_rows:
        if status in by_status:
            by_status[status] = count

    # ── open_total ────────────────────────────────────────────────────────
    open_total = sum(by_status[s] for s in OPEN_STATUSES)

    # ── overdue: open AND due_at < now ─────────────────────────────────────
    overdue = (
        _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)
        .filter(
            MaintTicket.status.in_(OPEN_STATUSES),
            MaintTicket.due_at < now,
        )
        .count()
    )

    # ── unrated_resolved: tickets del usuario como solicitante sin calificar
    # (siempre global — el banner afecta solo las acciones del propio usuario)
    unrated_resolved = (
        db.query(MaintTicket)
        .filter(
            MaintTicket.requester_id == user_id,
            MaintTicket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED']),
            MaintTicket.rating_attention.is_(None),
        )
        .count()
    )

    # ── by_category ───────────────────────────────────────────────────────
    # open count por categoría dentro del scope
    open_by_cat_rows = (
        _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)
        .with_entities(MaintTicket.category_id, func.count(MaintTicket.id))
        .filter(MaintTicket.status.in_(OPEN_STATUSES))
        .group_by(MaintTicket.category_id)
        .all()
    )
    open_by_cat = {cat_id: cnt for cat_id, cnt in open_by_cat_rows}

    total_by_cat_rows = (
        _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)
        .with_entities(MaintTicket.category_id, func.count(MaintTicket.id))
        .group_by(MaintTicket.category_id)
        .all()
    )
    total_by_cat = {cat_id: cnt for cat_id, cnt in total_by_cat_rows}

    categories = db.query(MaintCategory).filter_by(is_active=True).order_by(MaintCategory.display_order).all()
    by_category = [
        {
            "id": cat.id,
            "code": cat.code,
            "name": cat.name,
            "icon": cat.icon,
            "open": open_by_cat.get(cat.id, 0),
            "total": total_by_cat.get(cat.id, 0),
        }
        for cat in categories
        if total_by_cat.get(cat.id, 0) > 0 or open_by_cat.get(cat.id, 0) > 0
    ]

    # ── by_priority: solo tickets abiertos en scope ────────────────────────
    priority_rows = (
        _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)
        .with_entities(MaintTicket.priority, func.count(MaintTicket.id))
        .filter(MaintTicket.status.in_(OPEN_STATUSES))
        .group_by(MaintTicket.priority)
        .all()
    )
    by_priority = {"BAJA": 0, "MEDIA": 0, "ALTA": 0, "URGENTE": 0}
    for priority, count in priority_rows:
        if priority in by_priority:
            by_priority[priority] = count

    # ── avg_resolution_minutes_30d ─────────────────────────────────────────
    avg_row = (
        _apply_visibility(db.query(MaintTicket), user_id, user_roles, db)
        .with_entities(func.avg(MaintTicket.time_invested_minutes))
        .filter(
            MaintTicket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']),
            MaintTicket.resolved_at >= cutoff_30d,
            MaintTicket.time_invested_minutes.isnot(None),
        )
        .scalar()
    )
    avg_resolution_minutes_30d = round(float(avg_row)) if avg_row is not None else None

    # ── top_technicians_30d: solo para admin/dispatcher ────────────────────
    top_technicians_30d = []
    is_privileged = bool(roles & {'admin', 'dispatcher'})
    if is_privileged:
        top_rows = (
            db.query(
                MaintTicket.resolved_by_id,
                func.count(MaintTicket.id).label('resolved_count'),
                func.avg(MaintTicket.rating_attention).label('avg_rating'),
            )
            .filter(
                MaintTicket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']),
                MaintTicket.resolved_at >= cutoff_30d,
                MaintTicket.resolved_by_id.isnot(None),
            )
            .group_by(MaintTicket.resolved_by_id)
            .order_by(func.count(MaintTicket.id).desc())
            .limit(5)
            .all()
        )
        tech_ids = [row.resolved_by_id for row in top_rows]
        if tech_ids:
            users = db.query(User).filter(User.id.in_(tech_ids)).all()
            users_map = {u.id: u.full_name for u in users}
            top_technicians_30d = [
                {
                    "user_id": row.resolved_by_id,
                    "name": users_map.get(row.resolved_by_id, f"Usuario {row.resolved_by_id}"),
                    "resolved_count": row.resolved_count,
                    "avg_rating_attention": round(float(row.avg_rating), 2) if row.avg_rating else None,
                }
                for row in top_rows
            ]

    # ── recent_activity: últimas 10 acciones dentro del scope ─────────────
    log_q = (
        db.query(MaintTicketActionLog)
        .join(MaintTicket, MaintTicketActionLog.ticket_id == MaintTicket.id)
    )
    # Aplicar visibilidad al join (re-filtrar sobre MaintTicket)
    log_q = _apply_visibility_to_join(log_q, user_id, user_roles, db)
    activity_rows = (
        log_q
        .order_by(MaintTicketActionLog.performed_at.desc())
        .limit(10)
        .all()
    )
    recent_activity = []
    for log in activity_rows:
        try:
            performer_name = log.performed_by.full_name if log.performed_by else str(log.performed_by_id)
            ticket_number = log.ticket.ticket_number if log.ticket else str(log.ticket_id)
            recent_activity.append({
                "ticket_id": log.ticket_id,
                "ticket_number": ticket_number,
                "action": log.action,
                "performed_at": log.performed_at.isoformat() if log.performed_at else None,
                "performed_by": performer_name,
            })
        except Exception as e:
            logger.warning("Error serializando action_log %s: %s", log.id, e)

    # ── count 24h para roles técnicos/admin ────────────────────────────────
    activity_24h = None
    if roles & FULL_ACCESS_ROLES:
        activity_24h = (
            db.query(MaintTicketActionLog)
            .filter(MaintTicketActionLog.performed_at >= cutoff_24h)
            .count()
        )

    # ── last_ticket del usuario como solicitante (para staff) ──────────────
    last_ticket = None
    if not (roles & (FULL_ACCESS_ROLES | DEPT_ACCESS_ROLES)):
        lt = (
            db.query(MaintTicket)
            .filter(MaintTicket.requester_id == user_id)
            .order_by(MaintTicket.created_at.desc())
            .first()
        )
        if lt:
            last_ticket = {"ticket_number": lt.ticket_number, "status": lt.status}

    return {
        "by_status": by_status,
        "open_total": open_total,
        "overdue": overdue,
        "unrated_resolved": unrated_resolved,
        "by_category": by_category,
        "by_priority": by_priority,
        "avg_resolution_minutes_30d": avg_resolution_minutes_30d,
        "top_technicians_30d": top_technicians_30d,
        "recent_activity": recent_activity,
        # extras para la UI de la landing
        "activity_24h": activity_24h,
        "last_ticket": last_ticket,
    }


def _apply_visibility_to_join(query, user_id: int, user_roles: list, db: Session):
    """
    Versión de _apply_visibility para queries que ya hacen join con MaintTicket.
    Filtra sobre MaintTicket directamente (el join ya está hecho).
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    roles = set(user_roles)

    if FULL_ACCESS_ROLES & roles:
        return query

    if DEPT_ACCESS_ROLES & roles:
        dept_id = _resolve_dept_id(db, user_id)
        if dept_id:
            return query.filter(MaintTicket.requester_department_id == dept_id)
        return query.filter(MaintTicket.id == -1)

    return query.filter(MaintTicket.requester_id == user_id)

"""
Dashboard service para la app de Mantenimiento.

Calcula los KPIs del dashboard filtrando por el scope de visibilidad
del usuario (mismo criterio que ticket_service.list_tickets).

NOTA: El bloque de visibilidad se duplica aquí intencionalmente en lugar de
extraerlo a un helper en ticket_service.py, para no modificar ese archivo.
Mantener sincronizado con la lógica en ticket_service.list_tickets. Dentro de
ESTE módulo, en cambio, la condición vive en UN solo sitio (`_visibility_cond`)
compartido por `_apply_visibility` y `_apply_visibility_to_join` — antes tenían
lógicas ligeramente distintas entre sí y ambas divergían de list_tickets.
"""
import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

# tech_maint YA NO es FULL_ACCESS (D-G/H3): ve solo asignados/propios/de su área.
# maint_area_coordinator TAMPOCO: ve solo SU(s) área(s) + ruteados/asignados/propios.
# Solo admin, dispatcher y coordinador GENERAL tienen read.all. Igual que
# ticket_service.list_tickets.
FULL_ACCESS_ROLES = frozenset({'admin', 'dispatcher', 'maint_general_coordinator'})
DEPT_ACCESS_ROLES = frozenset({'department_head', 'secretary'})
OPEN_STATUSES = ('PENDING', 'ASSIGNED', 'IN_PROGRESS')
ALL_STATUSES = ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED')


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de visibilidad  (keep in sync with ticket_service.list_tickets)
# ──────────────────────────────────────────────────────────────────────────────

def _visibility_cond(db: Session, user_id: int, user_roles: list):
    """Condición SQL de visibilidad ÚNICA y ADITIVA (no excluyente): propio ∨
    asignado ∨ ruteado a mí (coordinador de área) ∨ categoría de mis áreas
    (técnico/coordinador de área) ∨ departamento/subárbol (jefe/secretaria +
    procedencia). Espejo EXACTO de la disyunción de
    ``ticket_service.list_tickets`` (no se importa de ahí para no acoplar este
    fix a un archivo fuera de scope; se comparte AQUÍ entre ``_apply_visibility``
    y ``_apply_visibility_to_join`` para que dejen de divergir entre sí — antes
    ninguna incluía la propiedad y cada una ramificaba distinto, así que los
    KPIs no contaban los tickets propios de un departamento anterior mientras
    ``unrated_resolved`` sí, y ``recent_activity`` terminaba siendo un
    subconjunto distinto del resto del mismo dashboard).
    """
    from sqlalchemy import or_
    from itcj2.apps.maint.models.ticket import MaintTicket
    from itcj2.apps.maint.models import MaintTicketTechnician
    from itcj2.apps.maint.models.category import MaintCategory
    from itcj2.apps.maint.services.ticket_service import _get_tech_maint_area_codes

    roles = set(user_roles)

    assigned_subq = db.query(MaintTicketTechnician.ticket_id).filter(
        MaintTicketTechnician.user_id == user_id,
        MaintTicketTechnician.unassigned_at.is_(None),
    )
    conds = [
        MaintTicket.requester_id == user_id,
        MaintTicket.id.in_(assigned_subq),
    ]

    area_codes: set[str] = set()
    if 'maint_area_coordinator' in roles:
        from itcj2.apps.maint.services.coordinator_service import CoordinatorService
        conds.append(MaintTicket.coordinator_id == user_id)
        area_codes |= set(CoordinatorService.get_coordinator_areas(db, user_id) or ())
    if 'tech_maint' in roles:
        area_codes |= set(_get_tech_maint_area_codes(db, user_id) or ())
    if area_codes:
        cat_subq = db.query(MaintCategory.id).filter(MaintCategory.code.in_(area_codes))
        conds.append(MaintTicket.category_id.in_(cat_subq))

    # H5: multi-depto (antes un resolver mono-depto elegía uno al azar) + subárbol
    # por procedencia (en sync con ticket_service.list_tickets).
    from itcj2.core.services.scope_service import subtree_scope_for
    dept_ids = set(subtree_scope_for(db, user_id, "maint", "maint.tickets.api.read.subtree"))
    if DEPT_ACCESS_ROLES & roles:
        from itcj2.apps.maint.services.department_dashboard_service import _resolve_user_departments
        dept_ids |= {d["id"] for d in _resolve_user_departments(db, user_id)}
    if dept_ids:
        conds.append(MaintTicket.requester_department_id.in_(dept_ids))

    return or_(*conds)


def _apply_visibility(query, user_id: int, user_roles: list, db: Session):
    """
    Aplica el filtro de visibilidad a un query sobre MaintTicket.
    Devuelve el query modificado.
    """
    roles = set(user_roles)

    if FULL_ACCESS_ROLES & roles:
        return query  # Sin restricción

    return query.filter(_visibility_cond(db, user_id, roles))


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

    Antes tenía su propia lógica, más pobre que `_apply_visibility` (sin rama de
    `maint_area_coordinator` ni subárbol, y tampoco incluía la propiedad) — por
    eso `recent_activity` era un subconjunto distinto del resto del dashboard.
    Ahora comparte `_visibility_cond` con `_apply_visibility`: misma condición,
    una sola vez.
    """
    roles = set(user_roles)

    if FULL_ACCESS_ROLES & roles:
        return query

    return query.filter(_visibility_cond(db, user_id, roles))

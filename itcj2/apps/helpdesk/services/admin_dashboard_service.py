"""
Servicio que compone `/help-desk/admin/home` — el panel de administrador de
Help-Desk (KPIs, banda "Requiere atención" y actividad reciente).

Reusa los MISMOS resolvers de scope que el resto del app, para que el
dashboard nunca muestre un número que el usuario no vería si navega a la
vista real que lo explica:
  - Tickets: `_resolve_stats_scope` (`api/stats.py`) — igual que `/stats/*`.
  - Inventario: `visible_department_ids` (`utils/inventory_access.py`) — igual
    que los widgets de `api/inventory/dashboard.py`.

Fail-closed: sin departamento resoluble, cada bloque cae a 0 (nunca "todos"),
heredado directamente de esos dos resolvers.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

# Estados "vivos" de un ticket — los que cuentan para "sin actualizar".
_ACTIVE_TICKET_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS")

# Estados de una solicitud de baja que siguen esperando alguna firma/revisión
# (excluye DRAFT —aún no se envió— y los estados terminales).
_RETIREMENT_PENDING_STATUSES = (
    "PENDING",
    "AWAITING_RECURSOS_MATERIALES",
    "AWAITING_SUBDIRECTOR",
    "AWAITING_DIRECTOR",
    "AWAITING_COMP_CENTER",
)

# Un ticket activo sin tocar en este umbral entra a la banda de atención.
_STALE_DAYS = 3

# Mismo umbral "critical" que `api/inventory/verification.py::_verification_status`
# (30/90 días). Se repite aquí en vez de importarlo: ese módulo está fuera del
# alcance de este cambio y el valor es un contrato ya documentado, no un detalle
# de implementación que vaya a cambiar en silencio.
_VERIFICATION_CRITICAL_DAYS = 90

# Mismo horizonte que la alerta de garantías de `api/inventory/dashboard.py::get_alerts`.
_WARRANTY_ALERT_DAYS = 30

# Ancla de subárbol propia de bajas (igual que `api/inventory/retirement_requests.py::_retirement_scope`).
_RETIREMENT_SUBTREE_PERM = "helpdesk.inventory.retirement.api.read.subtree"


class AdminDashboardService:
    """Compone el resumen de `/help-desk/admin/home`."""

    @staticmethod
    def get_overview(db: Session, user: dict) -> dict:
        kpis, ticket_attention, recent_tickets = AdminDashboardService._ticket_block(db, user)
        inventory_attention, recent_inventory = AdminDashboardService._inventory_block(db, user)

        return {
            "kpis": kpis,
            "attention": ticket_attention + inventory_attention,
            "recent_tickets": recent_tickets,
            "recent_inventory_events": recent_inventory,
        }

    # ------------------------------------------------------------------
    # Tickets — mismo scope que `/stats/*` (`_resolve_stats_scope`).
    # ------------------------------------------------------------------
    @staticmethod
    def _ticket_block(db: Session, user: dict) -> tuple[dict, list, list]:
        from itcj2.apps.helpdesk.api.stats import (
            _build_base_query,
            _resolution_hours,
            _resolve_stats_scope,
            _safe_avg,
            _within_sla,
        )
        from itcj2.apps.helpdesk.models.ticket import Ticket

        has_full_access, dept_ids = _resolve_stats_scope(db, user)
        scoped_dept_ids = None if has_full_access else dept_ids

        base_query = _build_base_query(db, None, None, None, None, None, dept_ids=scoped_dept_ids)

        total = base_query.count()
        pending = base_query.filter(Ticket.status == "PENDING").count()

        today_start = datetime.combine(datetime.now().date(), datetime.min.time())
        created_today = base_query.filter(Ticket.created_at >= today_start).count()

        stale_cutoff = datetime.now() - timedelta(days=_STALE_DAYS)
        stale_count = base_query.filter(
            Ticket.status.in_(_ACTIVE_TICKET_STATUSES),
            Ticket.updated_at < stale_cutoff,
        ).count()

        resolved_tickets = base_query.filter(Ticket.resolved_at.isnot(None)).all()
        res_hours = [_resolution_hours(t) for t in resolved_tickets if _resolution_hours(t) is not None]
        avg_resolution_hours = _safe_avg(res_hours)
        sla_ok = sum(1 for t in resolved_tickets if _within_sla(t))
        sla_rate = round(sla_ok / len(resolved_tickets) * 100, 1) if resolved_tickets else 0
        rated = [t.rating_attention for t in resolved_tickets if t.rating_attention is not None]
        avg_rating_attention = _safe_avg(rated)

        kpis = {
            "total": total,
            "pending": pending,
            "created_today": created_today,
            "avg_rating_attention": avg_rating_attention,
            "avg_resolution_hours": avg_resolution_hours,
            "sla_compliance_rate": sla_rate,
        }

        # "Sin asignar" = la misma cuenta que "Pendientes": un ticket entra a
        # ASSIGNED precisamente cuando se le pone técnico o cola de equipo, así
        # que PENDING es, por construcción, "sin asignar todavía". Única fuente
        # para ambos números — nunca pueden desalinearse entre sí.
        attention = [
            {
                "key": "unassigned",
                "icon": "fa-user-slash",
                "label": "tickets sin asignar",
                "count": pending,
                "url": "/help-desk/admin/assign-tickets",
                "action_label": "Asignar",
            },
            {
                "key": "stale",
                "icon": "fa-hourglass-half",
                "label": f"tickets sin actualizar hace más de {_STALE_DAYS} días",
                "count": stale_count,
                "url": "/help-desk/admin/tickets-list?sort=stale",
                "action_label": "Revisar",
            },
        ]

        recent = base_query.order_by(Ticket.created_at.desc()).limit(8).all()
        recent_tickets = [t.to_dict(include_relations=True) for t in recent]

        return kpis, attention, recent_tickets

    # ------------------------------------------------------------------
    # Inventario — mismo scope que los widgets de `api/inventory/dashboard.py`
    # (`visible_department_ids`).
    # ------------------------------------------------------------------
    @staticmethod
    def _inventory_block(db: Session, user: dict) -> tuple[list, list]:
        from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
        from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
        from itcj2.apps.helpdesk.models.inventory_retirement_request import (
            InventoryRetirementRequest,
            InventoryRetirementRequestItem,
        )
        from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

        user_id = int(user["sub"])
        visible = visible_department_ids(db, user)

        def _scope(query, column):
            # `visible is None` -> acceso completo, sin filtro. `visible` set
            # (posiblemente vacío) -> fail-closed vía el sentinel -1.
            if visible is None:
                return query
            return query.filter(column.in_(visible or {-1}))

        verif_cutoff = datetime.now() - timedelta(days=_VERIFICATION_CRITICAL_DAYS)
        critical_q = db.query(InventoryItem).filter(
            InventoryItem.is_active.is_(True),
            InventoryItem.last_verified_at.isnot(None),
            InventoryItem.last_verified_at < verif_cutoff,
        )
        critical_count = _scope(critical_q, InventoryItem.department_id).count()

        today = datetime.now().date()
        warranty_q = db.query(InventoryItem).filter(
            InventoryItem.is_active.is_(True),
            InventoryItem.warranty_expiration.isnot(None),
            InventoryItem.warranty_expiration >= today,
            InventoryItem.warranty_expiration <= today + timedelta(days=_WARRANTY_ALERT_DAYS),
        )
        warranty_count = _scope(warranty_q, InventoryItem.department_id).count()

        # Ancla propia de bajas (procedencia distinta a la de items/verificación):
        # mismo criterio que `api/inventory/retirement_requests.py::_retirement_scope`.
        visible_retirement = visible_department_ids(db, user, extra_subtree_perms={_RETIREMENT_SUBTREE_PERM})
        retirement_q = db.query(InventoryRetirementRequest.id).filter(
            InventoryRetirementRequest.status.in_(_RETIREMENT_PENDING_STATUSES)
        )
        if visible_retirement is not None:
            # La propiedad siempre suma (como en `InventoryRetirementService.get_requests`):
            # la solicitud propia cuenta aunque sus equipos ya no estén en el subárbol.
            conds = [InventoryRetirementRequest.requested_by_id == user_id]
            if visible_retirement:
                conds.append(
                    db.query(InventoryRetirementRequestItem.id)
                    .join(InventoryItem, InventoryItem.id == InventoryRetirementRequestItem.item_id)
                    .filter(
                        InventoryRetirementRequestItem.request_id == InventoryRetirementRequest.id,
                        InventoryItem.department_id.in_(visible_retirement),
                    )
                    .exists()
                )
            retirement_q = retirement_q.filter(or_(*conds))
        retirement_count = retirement_q.count()

        attention = [
            {
                "key": "verification_critical",
                "icon": "fa-clipboard-check",
                "label": f"equipos sin verificar hace más de {_VERIFICATION_CRITICAL_DAYS} días",
                "count": critical_count,
                "url": "/help-desk/inventory/verification?status_filter=critical",
                "action_label": "Verificar",
            },
            {
                "key": "warranty_expiring",
                "icon": "fa-shield-halved",
                "label": f"garantías que vencen en los próximos {_WARRANTY_ALERT_DAYS} días",
                "count": warranty_count,
                "url": "/help-desk/inventory/reports/warranty",
                "action_label": "Ver",
            },
            {
                "key": "retirement_pending",
                "icon": "fa-box-archive",
                "label": "solicitudes de baja pendientes",
                "count": retirement_count,
                "url": "/help-desk/inventory/retirement-requests",
                "action_label": "Revisar",
            },
        ]

        events_q = db.query(InventoryHistory).join(
            InventoryItem, InventoryHistory.item_id == InventoryItem.id
        )
        if visible is not None:
            events_q = events_q.filter(InventoryItem.department_id.in_(visible or {-1}))
        events = events_q.order_by(InventoryHistory.timestamp.desc()).limit(8).all()

        recent_inventory = [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "event_description": InventoryHistory.get_event_description(ev.event_type),
                "item": {
                    "id": ev.item.id,
                    "inventory_number": ev.item.inventory_number,
                    "display_name": ev.item.display_name,
                } if ev.item else None,
                "performed_by": {
                    "id": ev.performed_by.id,
                    "full_name": ev.performed_by.full_name,
                } if ev.performed_by else None,
                "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
            }
            for ev in events
        ]

        return attention, recent_inventory

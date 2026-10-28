"""Motor de asignación automática de tickets nuevos por reglas.

Corre inline al crear un ticket (después del commit de la creación). Número de
consultas constante: no depende de cuántas reglas, técnicos o tickets activos
haya. La fila de la regla elegida se lee con `FOR UPDATE` y el lock se libera
en el mismo commit de `assignment_service.assign_ticket`, que además guarda el
puntero de turnos: dos tickets simultáneos de la misma regla no caen al mismo
técnico.
"""
import logging

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, joinedload

from itcj2.apps.helpdesk.models.assignment_rule import AssignmentRule
from itcj2.apps.helpdesk.models.ticket import Ticket

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("ASSIGNED", "IN_PROGRESS")


class AutoAssignService:
    """Elige regla y técnico, y asigna. Ver spec §3."""

    @staticmethod
    def match_rule(db: Session, ticket, *, lock: bool = False):
        """Regla activa más específica para el ticket (categoría+prioridad >
        categoría > prioridad > solo área), o None. Una sola consulta."""
        q = (
            db.query(AssignmentRule)
            .options(joinedload(AssignmentRule.category))  # el motivo lleva su nombre
            .filter(
                AssignmentRule.is_active.is_(True),
                AssignmentRule.area == ticket.area,
                or_(AssignmentRule.category_id.is_(None),
                    AssignmentRule.category_id == ticket.category_id),
                or_(AssignmentRule.priority.is_(None),
                    AssignmentRule.priority == ticket.priority),
            )
            .order_by(
                AssignmentRule.category_id.isnot(None).desc(),
                AssignmentRule.priority.isnot(None).desc(),
                AssignmentRule.id,
            )
            .limit(1)
        )
        if lock:
            # OF: Postgres no bloquea el lado nulable del LEFT JOIN de categoría.
            # populate_existing: el puntero debe leerse tras obtener el lock.
            q = q.with_for_update(of=AssignmentRule).populate_existing()
        return q.first()

    @staticmethod
    def pick_technician(db: Session, rule) -> int | None:
        """Técnico que le toca según la estrategia de la regla. No muta nada."""
        from itcj2.apps.helpdesk.services.assignment_service import get_technicians_by_area

        ids = list(rule.technician_ids or [])
        # Turnos: rotar la lista para empezar después del último asignado; si
        # el puntero ya no está en la lista, desde el primero.
        if rule.last_assigned_user_id in ids:
            i = ids.index(rule.last_assigned_user_id) + 1
            ids = ids[i:] + ids[:i]
        active = {u.id for u in get_technicians_by_area(db, rule.area)}
        order = [uid for uid in ids if uid in active]
        if not order:
            return None
        if rule.strategy != "least_loaded":
            return order[0]

        load = dict(
            db.query(Ticket.assigned_to_user_id, func.count(Ticket.id))
            .filter(Ticket.assigned_to_user_id.in_(order),
                    Ticket.status.in_(_ACTIVE_STATUSES))
            .group_by(Ticket.assigned_to_user_id)
            .all()
        )
        # min() devuelve el primero de los empatados → orden de turnos
        return min(order, key=lambda uid: load.get(uid, 0))

    @staticmethod
    def try_auto_assign(db: Session, ticket):
        """Asigna el ticket según las reglas. Devuelve la `Assignment` o None.

        Nunca lanza: ante cualquier fallo hace rollback, lo loguea y el ticket
        queda PENDING. Espera la sesión sin cambios pendientes (se llama tras
        el commit de la creación).
        """
        from itcj2.apps.helpdesk.services import assignment_service
        from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings

        try:
            if not get_settings(db).auto_assign_enabled:
                return None
            # Corre dentro de un endpoint async: una fila retenida por otra
            # transacción no debe colgar el event loop (SET LOCAL muere en el commit).
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            # Releer el ticket bloqueado: una asignación manual que se haya
            # colado desde el broadcast de ticket_created ya se ve aquí.
            ticket = (
                db.query(Ticket).filter(Ticket.id == ticket.id)
                .with_for_update().populate_existing().one()
            )
            if ticket.status != "PENDING" or ticket.assigned_to_user_id or ticket.assigned_to_team:
                db.rollback()  # suelta el lock del ticket
                return None

            rule = AutoAssignService.match_rule(db, ticket, lock=True)
            pick = AutoAssignService.pick_technician(db, rule) if rule else None
            if pick is None:
                db.rollback()  # suelta los locks del ticket y la regla
                return None

            rule.last_assigned_user_id = pick
            reason = (
                f"Asignación automática (regla: {rule.area} · "
                f"{rule.category.name if rule.category_id else 'toda el área'} · "
                f"{rule.priority or 'cualquier prioridad'})"
            )
            # Su commit guarda el puntero y libera el lock de la regla
            return assignment_service.assign_ticket(
                db,
                ticket.id,
                assigned_by_id=rule.updated_by_id or rule.created_by_id,
                assigned_to_user_id=pick,
                reason=reason,
            )
        except Exception:
            db.rollback()
            logger.exception("Asignación automática falló; el ticket queda PENDING")
            return None

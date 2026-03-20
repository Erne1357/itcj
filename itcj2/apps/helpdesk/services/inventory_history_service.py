"""
Servicio para consultas de historial de inventario
"""
from datetime import datetime, timedelta

from sqlalchemy import desc, and_, or_, BigInteger
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.apps.helpdesk.models.inventory_item import InventoryItem


class InventoryHistoryService:
    """Consultas y análisis del historial de equipos"""

    @staticmethod
    def get_item_history(db: Session, item_id, limit=None, event_types=None):
        """
        Obtiene el historial de un equipo
        """
        query = db.query(InventoryHistory).filter(
            InventoryHistory.item_id == item_id
        ).order_by(desc(InventoryHistory.timestamp))

        if event_types:
            query = query.filter(InventoryHistory.event_type.in_(event_types))

        if limit:
            query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_recent_events(db: Session, department_id=None, days=7, limit=50):
        """
        Obtiene eventos recientes del inventario
        """
        since_date = datetime.now() - timedelta(days=days)

        query = db.query(InventoryHistory).join(
            InventoryItem, InventoryHistory.item_id == InventoryItem.id
        ).filter(
            InventoryHistory.timestamp >= since_date
        )

        if department_id:
            query = query.filter(InventoryItem.department_id == department_id)

        query = query.order_by(desc(InventoryHistory.timestamp)).limit(limit)

        return query.all()

    @staticmethod
    def get_assignment_history(db: Session, user_id):
        """
        Obtiene historial de asignaciones de un usuario
        """
        events = db.query(InventoryHistory).filter(
            or_(
                InventoryHistory.event_type == 'ASSIGNED_TO_USER',
                InventoryHistory.event_type == 'REASSIGNED',
                InventoryHistory.event_type == 'UNASSIGNED'
            ),
            or_(
                InventoryHistory.new_value['assigned_to_user_id'].astext.cast(BigInteger) == user_id,
                InventoryHistory.old_value['assigned_to_user_id'].astext.cast(BigInteger) == user_id
            )
        ).order_by(desc(InventoryHistory.timestamp)).all()

        return events

    @staticmethod
    def get_transfers_between_departments(db: Session, days=30):
        """
        Obtiene transferencias entre departamentos
        """
        since_date = datetime.now() - timedelta(days=days)

        transfers = db.query(InventoryHistory).filter(
            InventoryHistory.event_type == 'TRANSFERRED',
            InventoryHistory.timestamp >= since_date
        ).order_by(desc(InventoryHistory.timestamp)).all()

        return transfers

    @staticmethod
    def log_event(
        db: Session,
        item_id,
        event_type,
        performed_by_id,
        old_value=None,
        new_value=None,
        notes=None,
        related_ticket_id=None,
        ip_address=None,
    ):
        """
        Registra un evento en el historial
        """
        history = InventoryHistory(
            item_id=item_id,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            notes=notes,
            related_ticket_id=related_ticket_id,
            performed_by_id=performed_by_id,
            ip_address=ip_address
        )

        db.add(history)
        db.flush()

        return history

    @staticmethod
    def get_maintenance_history(db: Session, item_id):
        """
        Obtiene historial de mantenimientos de un equipo
        """
        maintenance_events = db.query(InventoryHistory).filter(
            InventoryHistory.item_id == item_id,
            or_(
                InventoryHistory.event_type == 'MAINTENANCE_SCHEDULED',
                InventoryHistory.event_type == 'MAINTENANCE_COMPLETED',
                and_(
                    InventoryHistory.event_type == 'STATUS_CHANGED',
                    or_(
                        InventoryHistory.new_value['status'].astext == 'MAINTENANCE',
                        InventoryHistory.old_value['status'].astext == 'MAINTENANCE'
                    )
                )
            )
        ).order_by(desc(InventoryHistory.timestamp)).all()

        return maintenance_events

    @staticmethod
    def get_events_by_user(db: Session, user_id, days=30, limit=100):
        """
        Obtiene todas las acciones realizadas por un usuario
        """
        since_date = datetime.now() - timedelta(days=days)

        events = db.query(InventoryHistory).filter(
            InventoryHistory.performed_by_id == user_id,
            InventoryHistory.timestamp >= since_date
        ).order_by(desc(InventoryHistory.timestamp)).limit(limit).all()

        return events

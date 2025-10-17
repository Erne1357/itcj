"""
Servicio para consultas de historial de inventario
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryHistory, InventoryItem
from datetime import datetime, timedelta
from sqlalchemy import desc, and_, or_


class InventoryHistoryService:
    """Consultas y análisis del historial de equipos"""
    
    @staticmethod
    def get_item_history(item_id, limit=None, event_types=None):
        """
        Obtiene el historial de un equipo
        
        Args:
            item_id: ID del equipo
            limit: Límite de registros (opcional)
            event_types: Lista de tipos de eventos a filtrar (opcional)
        
        Returns:
            Lista de InventoryHistory ordenada por fecha descendente
        """
        query = InventoryHistory.query.filter(
            InventoryHistory.item_id == item_id
        ).order_by(desc(InventoryHistory.timestamp))
        
        if event_types:
            query = query.filter(InventoryHistory.event_type.in_(event_types))
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    @staticmethod
    def get_recent_events(department_id=None, days=7, limit=50):
        """
        Obtiene eventos recientes del inventario
        
        Args:
            department_id: Filtrar por departamento (opcional)
            days: Días hacia atrás (default: 7)
            limit: Máximo de registros (default: 50)
        
        Returns:
            Lista de eventos recientes
        """
        since_date = datetime.utcnow() - timedelta(days=days)
        
        query = db.session.query(InventoryHistory).join(
            InventoryItem, InventoryHistory.item_id == InventoryItem.id
        ).filter(
            InventoryHistory.timestamp >= since_date
        )
        
        if department_id:
            query = query.filter(InventoryItem.department_id == department_id)
        
        query = query.order_by(desc(InventoryHistory.timestamp)).limit(limit)
        
        return query.all()
    
    @staticmethod
    def get_assignment_history(user_id):
        """
        Obtiene historial de asignaciones de un usuario
        
        Args:
            user_id: ID del usuario
        
        Returns:
            Lista de equipos que han estado asignados al usuario
        """
        events = InventoryHistory.query.filter(
            or_(
                InventoryHistory.event_type == 'ASSIGNED_TO_USER',
                InventoryHistory.event_type == 'REASSIGNED',
                InventoryHistory.event_type == 'UNASSIGNED'
            ),
            or_(
                InventoryHistory.new_value['assigned_to_user_id'].astext.cast(db.BigInteger) == user_id,
                InventoryHistory.old_value['assigned_to_user_id'].astext.cast(db.BigInteger) == user_id
            )
        ).order_by(desc(InventoryHistory.timestamp)).all()
        
        return events
    
    @staticmethod
    def get_transfers_between_departments(days=30):
        """
        Obtiene transferencias entre departamentos
        
        Args:
            days: Días hacia atrás (default: 30)
        
        Returns:
            Lista de transferencias
        """
        since_date = datetime.utcnow() - timedelta(days=days)
        
        transfers = InventoryHistory.query.filter(
            InventoryHistory.event_type == 'TRANSFERRED',
            InventoryHistory.timestamp >= since_date
        ).order_by(desc(InventoryHistory.timestamp)).all()
        
        return transfers
    
    @staticmethod
    def log_event(item_id, event_type, performed_by_id, old_value=None, 
                  new_value=None, notes=None, related_ticket_id=None, ip_address=None):
        """
        Registra un evento en el historial
        
        Args:
            item_id: ID del equipo
            event_type: Tipo de evento
            performed_by_id: ID de quien realiza la acción
            old_value: Estado anterior (dict)
            new_value: Estado nuevo (dict)
            notes: Observaciones
            related_ticket_id: ID de ticket relacionado (opcional)
            ip_address: IP del usuario
        
        Returns:
            InventoryHistory creado
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
        
        db.session.add(history)
        db.session.flush()
        
        return history
    
    @staticmethod
    def get_maintenance_history(item_id):
        """
        Obtiene historial de mantenimientos de un equipo
        
        Args:
            item_id: ID del equipo
        
        Returns:
            Lista de eventos de mantenimiento
        """
        maintenance_events = InventoryHistory.query.filter(
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
    def get_events_by_user(user_id, days=30, limit=100):
        """
        Obtiene todas las acciones realizadas por un usuario
        
        Args:
            user_id: ID del usuario
            days: Días hacia atrás
            limit: Máximo de registros
        
        Returns:
            Lista de eventos
        """
        since_date = datetime.utcnow() - timedelta(days=days)
        
        events = InventoryHistory.query.filter(
            InventoryHistory.performed_by_id == user_id,
            InventoryHistory.timestamp >= since_date
        ).order_by(desc(InventoryHistory.timestamp)).limit(limit).all()
        
        return events
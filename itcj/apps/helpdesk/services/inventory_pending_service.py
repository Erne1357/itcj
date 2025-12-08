"""
Servicio para gestión de equipos pendientes de asignación
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryItem, InventoryHistory
from itcj.core.models.department import Department
from sqlalchemy import and_
import logging

logger = logging.getLogger(__name__)


class InventoryPendingService:
    """Servicio para equipos en espera de asignación"""
    
    @staticmethod
    def get_pending_items(category_id=None):
        """
        Obtiene todos los equipos pendientes de asignación.
        
        Args:
            category_id: Filtrar por categoría (opcional)
        """
        cc_department = Department.query.filter_by(code='comp_center').first()
        
        if not cc_department:
            return []
        
        query = InventoryItem.query.filter(
            InventoryItem.status == 'PENDING_ASSIGNMENT',
            InventoryItem.department_id == cc_department.id,
            InventoryItem.is_active == True
        )
        
        if category_id:
            query = query.filter_by(category_id=category_id)
        
        return query.order_by(InventoryItem.created_at.desc()).all()
    
    @staticmethod
    def get_pending_stats():
        """
        Obtiene estadísticas de equipos pendientes.
        
        Returns:
            {
                'total': int,
                'by_category': [
                    {'category_id': int, 'category_name': str, 'count': int},
                    ...
                ]
            }
        """
        from sqlalchemy import func
        from itcj.apps.helpdesk.models import InventoryCategory
        
        cc_department = Department.query.filter_by(code='comp_center').first()
        
        if not cc_department:
            return {'total': 0, 'by_category': []}
        
        # Total
        total = InventoryItem.query.filter(
            InventoryItem.status == 'PENDING_ASSIGNMENT',
            InventoryItem.department_id == cc_department.id,
            InventoryItem.is_active == True
        ).count()
        
        # Por categoría
        by_category = db.session.query(
            InventoryItem.category_id,
            InventoryCategory.name,
            func.count(InventoryItem.id).label('count')
        ).join(
            InventoryCategory, InventoryItem.category_id == InventoryCategory.id
        ).filter(
            InventoryItem.status == 'PENDING_ASSIGNMENT',
            InventoryItem.department_id == cc_department.id,
            InventoryItem.is_active == True
        ).group_by(
            InventoryItem.category_id,
            InventoryCategory.name
        ).all()
        
        return {
            'total': total,
            'by_category': [
                {
                    'category_id': cat_id,
                    'category_name': cat_name,
                    'count': count
                }
                for cat_id, cat_name, count in by_category
            ]
        }
    
    @staticmethod
    def assign_to_department(item_ids: list, department_id: int, assigned_by_id: int,
                            location_detail: str = None, notes: str = None) -> list:
        """
        Asigna equipos pendientes a un departamento.
        
        Args:
            item_ids: Lista de IDs de equipos a asignar
            department_id: ID del departamento destino
            assigned_by_id: ID del usuario que asigna
            location_detail: Ubicación específica (opcional)
            notes: Notas adicionales (opcional)
        """
        try:
            # Validar departamento
            department = Department.query.get(department_id)
            if not department:
                raise ValueError(f"Departamento {department_id} no encontrado")
            
            cc_department = Department.query.filter_by(code='comp_center').first()
            
            assigned_items = []
            
            for item_id in item_ids:
                item = InventoryItem.query.get(item_id)
                
                if not item:
                    logger.warning(f"Equipo {item_id} no encontrado, omitiendo")
                    continue
                
                # Validar que esté pendiente
                if item.status != 'PENDING_ASSIGNMENT':
                    logger.warning(f"Equipo {item.inventory_number} no está pendiente, omitiendo")
                    continue
                
                # Guardar valores antiguos
                old_dept_id = item.department_id
                old_status = item.status
                
                # Asignar al departamento
                item.department_id = department_id
                item.status = 'ACTIVE'
                item.assigned_by_id = assigned_by_id
                item.assigned_at = db.func.now()
                
                if location_detail:
                    item.location_detail = location_detail
                
                if notes:
                    item.notes = notes
                
                # Registrar en historial
                history = InventoryHistory(
                    item_id=item.id,
                    event_type='ASSIGNED_TO_DEPT',
                    old_value={
                        'department_id': old_dept_id,
                        'department_name': cc_department.name if cc_department else None,
                        'status': old_status
                    },
                    new_value={
                        'department_id': department_id,
                        'department_name': department.name,
                        'status': 'ACTIVE'
                    },
                    notes=notes or f"Equipo asignado desde limbo a {department.name}",
                    performed_by_id=assigned_by_id
                )
                db.session.add(history)
                
                assigned_items.append(item)
            
            db.session.commit()
            logger.info(f"{len(assigned_items)} equipos asignados a departamento {department.name}")
            
            return assigned_items
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al asignar equipos pendientes: {str(e)}")
            raise
"""
Servicio para gestión de equipos pendientes de asignación
"""
import logging

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.core.models.department import Department

logger = logging.getLogger(__name__)


class InventoryPendingService:
    """Servicio para equipos en espera de asignación"""

    @staticmethod
    def get_pending_items(db: Session, category_id=None):
        """
        Obtiene todos los equipos pendientes de asignación.
        """
        cc_department = db.query(Department).filter_by(code='comp_center').first()

        if not cc_department:
            return []

        query = db.query(InventoryItem).filter(
            InventoryItem.status == 'PENDING_ASSIGNMENT',
            InventoryItem.department_id == cc_department.id,
            InventoryItem.is_active == True
        )

        if category_id:
            query = query.filter_by(category_id=category_id)

        return query.order_by(InventoryItem.created_at.desc()).all()

    @staticmethod
    def get_pending_stats(db: Session):
        """
        Obtiene estadísticas de equipos pendientes.
        """
        from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory

        cc_department = db.query(Department).filter_by(code='comp_center').first()

        if not cc_department:
            return {'total': 0, 'by_category': []}

        total = db.query(InventoryItem).filter(
            InventoryItem.status == 'PENDING_ASSIGNMENT',
            InventoryItem.department_id == cc_department.id,
            InventoryItem.is_active == True
        ).count()

        by_category = db.query(
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
    def assign_to_department(
        db: Session,
        item_ids: list,
        department_id: int,
        assigned_by_id: int,
        location_detail: str = None,
        notes: str = None,
    ) -> list:
        """
        Asigna equipos pendientes a un departamento.
        """
        try:
            department = db.get(Department, department_id)
            if not department:
                raise ValueError(f"Departamento {department_id} no encontrado")

            cc_department = db.query(Department).filter_by(code='comp_center').first()

            assigned_items = []

            for item_id in item_ids:
                item = db.get(InventoryItem, item_id)

                if not item:
                    logger.warning(f"Equipo {item_id} no encontrado, omitiendo")
                    continue

                if item.status != 'PENDING_ASSIGNMENT':
                    logger.warning(f"Equipo {item.inventory_number} no está pendiente, omitiendo")
                    continue

                old_dept_id = item.department_id
                old_status = item.status

                item.department_id = department_id
                item.status = 'ACTIVE'
                item.assigned_by_id = assigned_by_id
                item.assigned_at = func.now()

                if location_detail:
                    item.location_detail = location_detail

                if notes:
                    item.notes = notes

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
                db.add(history)

                assigned_items.append(item)

            db.commit()
            logger.info(f"{len(assigned_items)} equipos asignados a departamento {department.name}")

            return assigned_items

        except Exception as e:
            db.rollback()
            logger.error(f"Error al asignar equipos pendientes: {str(e)}")
            raise

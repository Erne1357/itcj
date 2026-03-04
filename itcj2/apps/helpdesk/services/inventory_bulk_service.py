"""
Servicio para registro masivo de equipos de inventario
"""
from datetime import datetime, date, timedelta
import logging

from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.core.models.department import Department

logger = logging.getLogger(__name__)


class InventoryBulkService:
    """Servicio para operaciones de registro masivo"""

    @staticmethod
    def get_next_inventory_number(db: Session, category_id: int, year: int = None) -> str:
        """
        Genera el siguiente número de inventario para una categoría.
        Formato: PREFIX-YYYY-NNNN
        """
        if year is None:
            year = datetime.now().year

        category = db.get(InventoryCategory, category_id)
        if not category:
            raise ValueError(f"Categoría {category_id} no encontrada")

        prefix = category.inventory_prefix
        year_str = str(year)

        last_item = db.query(InventoryItem).filter(
            InventoryItem.category_id == category_id,
            InventoryItem.inventory_number.like(f"{prefix}-{year_str}-%")
        ).order_by(InventoryItem.inventory_number.desc()).first()

        if last_item:
            parts = last_item.inventory_number.split('-')
            if len(parts) == 3:
                last_num = int(parts[2])
                next_num = last_num + 1
            else:
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}-{year_str}-{next_num:04d}"

    @staticmethod
    def bulk_create_items(db: Session, data: dict, registered_by_id: int) -> list:
        """
        Crea múltiples equipos con las mismas especificaciones.
        Solo varía el número de serie.
        """
        try:
            created_items = []
            cc_department = db.query(Department).filter_by(code='comp_center').first()

            if not cc_department:
                raise ValueError("Departamento del Centro de Cómputo (comp_center) no encontrado")

            category = db.get(InventoryCategory, data['category_id'])
            if not category:
                raise ValueError(f"Categoría {data['category_id']} no encontrada")

            acquisition_date = None
            if data.get('acquisition_date'):
                acquisition_date = date.fromisoformat(data['acquisition_date'])

            warranty_expiration = None
            if data.get('warranty_expiration'):
                warranty_expiration = date.fromisoformat(data['warranty_expiration'])

            next_maintenance_date = None
            if data.get('maintenance_frequency_days') and acquisition_date:
                next_maintenance_date = acquisition_date + timedelta(days=data['maintenance_frequency_days'])

            for item_data in data['items']:
                inventory_number = InventoryBulkService.get_next_inventory_number(db, data['category_id'])

                department_id = item_data.get('department_id')
                status = 'ACTIVE'

                if not department_id:
                    department_id = cc_department.id
                    status = 'PENDING_ASSIGNMENT'

                item = InventoryItem(
                    inventory_number=inventory_number,
                    category_id=data['category_id'],
                    brand=data.get('brand'),
                    model=data.get('model'),
                    serial_number=item_data['serial_number'],
                    specifications=data.get('specifications'),
                    department_id=department_id,
                    assigned_to_user_id=item_data.get('assigned_to_user_id'),
                    group_id=item_data.get('group_id'),
                    location_detail=item_data.get('location_detail'),
                    status=status,
                    acquisition_date=acquisition_date,
                    warranty_expiration=warranty_expiration,
                    maintenance_frequency_days=data.get('maintenance_frequency_days'),
                    next_maintenance_date=next_maintenance_date,
                    notes=data.get('notes'),
                    registered_by_id=registered_by_id,
                    is_active=True
                )

                db.add(item)
                db.flush()

                history = InventoryHistory(
                    item_id=item.id,
                    event_type='REGISTERED',
                    old_value=None,
                    new_value={
                        'inventory_number': item.inventory_number,
                        'category_id': item.category_id,
                        'status': item.status,
                        'department_id': item.department_id
                    },
                    notes='Equipo registrado mediante registro masivo',
                    performed_by_id=registered_by_id
                )
                db.add(history)

                created_items.append(item)

            db.commit()
            logger.info(f"Registro masivo: {len(created_items)} equipos creados por usuario {registered_by_id}")

            return created_items

        except Exception as e:
            db.rollback()
            logger.error(f"Error en registro masivo: {str(e)}")
            raise

    @staticmethod
    def validate_serial_numbers(db: Session, serial_numbers: list) -> dict:
        """
        Valida que los números de serie no estén duplicados.
        """
        result = {
            'valid': True,
            'duplicates_in_list': [],
            'duplicates_in_db': []
        }

        seen = set()
        for sn in serial_numbers:
            if sn in seen:
                result['duplicates_in_list'].append(sn)
                result['valid'] = False
            seen.add(sn)

        existing = db.query(InventoryItem).filter(
            InventoryItem.serial_number.in_(serial_numbers)
        ).all()

        if existing:
            result['duplicates_in_db'] = [item.serial_number for item in existing]
            result['valid'] = False

        return result

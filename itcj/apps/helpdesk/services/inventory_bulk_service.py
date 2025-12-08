"""
Servicio para registro masivo de equipos de inventario
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryItem, InventoryCategory, InventoryHistory
from itcj.core.models.department import Department
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class InventoryBulkService:
    """Servicio para operaciones de registro masivo"""
    
    @staticmethod
    def get_next_inventory_number(category_id: int, year: int = None) -> str:
        """
        Genera el siguiente número de inventario para una categoría.
        Formato: PREFIX-YYYY-NNNN
        Ejemplo: COMP-2025-0001
        """
        if year is None:
            year = datetime.now().year
        
        category = InventoryCategory.query.get(category_id)
        if not category:
            raise ValueError(f"Categoría {category_id} no encontrada")
        
        prefix = category.inventory_prefix
        year_str = str(year)
        
        # Buscar el último número para esta categoría y año
        last_item = InventoryItem.query.filter(
            InventoryItem.category_id == category_id,
            InventoryItem.inventory_number.like(f"{prefix}-{year_str}-%")
        ).order_by(InventoryItem.inventory_number.desc()).first()
        
        if last_item:
            # Extraer el número secuencial
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
    def bulk_create_items(data: dict, registered_by_id: int) -> list:
        """
        Crea múltiples equipos con las mismas especificaciones.
        Solo varía el número de serie.
        
        Args:
            data: {
                'category_id': int,
                'brand': str,
                'model': str,
                'specifications': dict,
                'acquisition_date': str (ISO),
                'warranty_expiration': str (ISO),
                'maintenance_frequency_days': int,
                'notes': str,
                'items': [
                    {
                        'serial_number': str,
                        'department_id': int (opcional),
                        'assigned_to_user_id': int (opcional),
                        'group_id': int (opcional),
                        'location_detail': str (opcional)
                    },
                    ...
                ]
            }
            registered_by_id: ID del usuario que registra
        """
        try:
            created_items = []
            cc_department = Department.query.filter_by(code='comp_center').first()
            
            if not cc_department:
                raise ValueError("Departamento del Centro de Cómputo (comp_center) no encontrado")
            
            # Validar categoría
            category = InventoryCategory.query.get(data['category_id'])
            if not category:
                raise ValueError(f"Categoría {data['category_id']} no encontrada")
            
            # Procesar fechas
            acquisition_date = None
            if data.get('acquisition_date'):
                acquisition_date = date.fromisoformat(data['acquisition_date'])
            
            warranty_expiration = None
            if data.get('warranty_expiration'):
                warranty_expiration = date.fromisoformat(data['warranty_expiration'])
            
            # Calcular next_maintenance_date si se especifica frecuencia
            next_maintenance_date = None
            if data.get('maintenance_frequency_days') and acquisition_date:
                from datetime import timedelta
                next_maintenance_date = acquisition_date + timedelta(days=data['maintenance_frequency_days'])
            
            # Crear cada equipo
            for item_data in data['items']:
                # Generar número de inventario secuencial
                inventory_number = InventoryBulkService.get_next_inventory_number(data['category_id'])
                
                # Determinar departamento y status
                department_id = item_data.get('department_id')
                status = 'ACTIVE'
                
                # Si no se especifica departamento, va al limbo del CC
                if not department_id:
                    department_id = cc_department.id
                    status = 'PENDING_ASSIGNMENT'
                
                # Crear el equipo
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
                
                db.session.add(item)
                db.session.flush()  # Para obtener el ID
                
                # Registrar en historial
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
                db.session.add(history)
                
                created_items.append(item)
            
            db.session.commit()
            logger.info(f"Registro masivo: {len(created_items)} equipos creados por usuario {registered_by_id}")
            
            return created_items
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error en registro masivo: {str(e)}")
            raise
    
    @staticmethod
    def validate_serial_numbers(serial_numbers: list) -> dict:
        """
        Valida que los números de serie no estén duplicados.
        
        Returns:
            {
                'valid': bool,
                'duplicates_in_list': [str],
                'duplicates_in_db': [str]
            }
        """
        result = {
            'valid': True,
            'duplicates_in_list': [],
            'duplicates_in_db': []
        }
        
        # Verificar duplicados en la lista
        seen = set()
        for sn in serial_numbers:
            if sn in seen:
                result['duplicates_in_list'].append(sn)
                result['valid'] = False
            seen.add(sn)
        
        # Verificar duplicados en BD
        existing = InventoryItem.query.filter(
            InventoryItem.serial_number.in_(serial_numbers)
        ).all()
        
        if existing:
            result['duplicates_in_db'] = [item.serial_number for item in existing]
            result['valid'] = False
        
        return result
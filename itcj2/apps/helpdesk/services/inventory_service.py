"""
Servicio para gestión de inventario
"""
from datetime import datetime, date, timedelta

from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
from itcj2.core.models.department import Department


class InventoryService:
    """Lógica de negocio para el sistema de inventario"""

    @staticmethod
    def generate_inventory_number(db: Session, category_id):
        """
        Genera número de inventario único.
        Formato: [PREFIX]-[YEAR]-[SEQUENCE]
        """
        category = db.get(InventoryCategory, category_id)
        if not category:
            raise ValueError("Categoría no encontrada")

        prefix = category.inventory_prefix
        year = datetime.now().year

        last_item = db.query(InventoryItem).filter(
            InventoryItem.category_id == category_id,
            InventoryItem.inventory_number.like(f"{prefix}-{year}-%")
        ).order_by(InventoryItem.id.desc()).first()

        if last_item:
            try:
                last_sequence = int(last_item.inventory_number.split('-')[-1])
                next_sequence = last_sequence + 1
            except Exception:
                next_sequence = 1
        else:
            next_sequence = 1

        return f"{prefix}-{year}-{next_sequence:04d}"

    @staticmethod
    def create_item(db: Session, data, registered_by_id, ip_address=None):
        """
        Registra un nuevo equipo en el inventario.
        """
        if not data.get('category_id'):
            raise ValueError("Categoría requerida")
        if not data.get('department_id'):
            cc_department = db.query(Department).filter_by(code='comp_center').first()
            if not cc_department:
                raise ValueError("Departamento del Centro de Cómputo (comp_center) no encontrado")
            data['department_id'] = cc_department.id
            if not data.get('status'):
                data['status'] = 'PENDING_ASSIGNMENT'

        if not data.get('inventory_number'):
            data['inventory_number'] = InventoryService.generate_inventory_number(
                db, data['category_id']
            )

        existing = db.query(InventoryItem).filter_by(
            inventory_number=data['inventory_number']
        ).first()
        if existing:
            raise ValueError(f"El número de inventario {data['inventory_number']} ya existe")

        if data.get('supplier_serial'):
            existing = db.query(InventoryItem).filter_by(supplier_serial=data['supplier_serial']).first()
            if existing:
                raise ValueError(f"El serial de proveedor '{data['supplier_serial']}' ya existe en {existing.inventory_number}")

        if data.get('itcj_serial'):
            existing = db.query(InventoryItem).filter_by(itcj_serial=data['itcj_serial']).first()
            if existing:
                raise ValueError(f"El serial ITCJ '{data['itcj_serial']}' ya existe en {existing.inventory_number}")

        if data.get('id_tecnm'):
            existing = db.query(InventoryItem).filter_by(id_tecnm=data['id_tecnm']).first()
            if existing:
                raise ValueError(f"El ID TecNM '{data['id_tecnm']}' ya existe en {existing.inventory_number}")

        if data.get('maintenance_frequency_days'):
            base_date = data.get('last_maintenance_date') or data.get('acquisition_date') or date.today()
            data['next_maintenance_date'] = base_date + timedelta(days=data['maintenance_frequency_days'])

        item = InventoryItem(
            inventory_number=data['inventory_number'],
            category_id=data['category_id'],
            brand=data.get('brand'),
            model=data.get('model'),
            supplier_serial=data.get('supplier_serial'),
            itcj_serial=data.get('itcj_serial'),
            id_tecnm=data.get('id_tecnm'),
            specifications=data.get('specifications'),
            department_id=data['department_id'],
            assigned_to_user_id=data.get('assigned_to_user_id'),
            location_detail=data.get('location_detail'),
            status=data.get('status', 'ACTIVE'),
            acquisition_date=data.get('acquisition_date'),
            warranty_expiration=data.get('warranty_expiration'),
            last_maintenance_date=data.get('last_maintenance_date'),
            maintenance_frequency_days=data.get('maintenance_frequency_days'),
            next_maintenance_date=data.get('next_maintenance_date'),
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
                'category': item.category.name if item.category else None,
                'department': item.department.name if item.department else None,
                'status': item.status
            },
            notes=data.get('registration_notes', 'Equipo registrado en el sistema'),
            performed_by_id=registered_by_id,
            ip_address=ip_address
        )
        db.add(history)

        db.commit()
        return item

    @staticmethod
    def update_item(db: Session, item_id, data, updated_by_id, ip_address=None):
        """
        Actualiza información de un equipo.
        """
        item = db.get(InventoryItem, item_id)
        if not item:
            raise ValueError("Equipo no encontrado")

        if not item.is_active:
            raise ValueError("No se puede editar un equipo dado de baja")

        updatable_fields = [
            'brand', 'model', 'supplier_serial', 'itcj_serial', 'id_tecnm',
            'specifications', 'location_detail',
            'warranty_expiration', 'maintenance_frequency_days', 'notes'
        ]

        serial_uniqueness = [
            ('supplier_serial', 'serial de proveedor'),
            ('itcj_serial', 'serial ITCJ'),
            ('id_tecnm', 'ID TecNM'),
        ]
        for field, label in serial_uniqueness:
            value = data.get(field)
            if value and value != getattr(item, field):
                existing = db.query(InventoryItem).filter(
                    getattr(InventoryItem, field) == value,
                    InventoryItem.id != item_id,
                ).first()
                if existing:
                    raise ValueError(f"El {label} '{value}' ya existe en {existing.inventory_number}")

        changes = {}
        for field in updatable_fields:
            if field in data:
                old_value = getattr(item, field)
                new_value = data[field]
                if old_value != new_value:
                    changes[field] = {'old': old_value, 'new': new_value}
                    setattr(item, field, new_value)

        if 'maintenance_frequency_days' in changes and item.maintenance_frequency_days:
            base_date = item.last_maintenance_date or item.acquisition_date or date.today()
            item.next_maintenance_date = base_date + timedelta(days=item.maintenance_frequency_days)

        if changes:
            history = InventoryHistory(
                item_id=item.id,
                event_type='SPECS_UPDATED',
                old_value={'changes': {k: v['old'] for k, v in changes.items()}},
                new_value={'changes': {k: v['new'] for k, v in changes.items()}},
                notes=data.get('update_notes', 'Información actualizada'),
                performed_by_id=updated_by_id,
                ip_address=ip_address
            )
            db.add(history)

        db.commit()
        return item

    @staticmethod
    def assign_to_user(db: Session, item_id, user_id, assigned_by_id, location=None, notes=None, ip_address=None):
        """
        Asigna equipo a un usuario específico.
        """
        from itcj2.core.models.user import User

        item = db.get(InventoryItem, item_id)
        if not item:
            raise ValueError("Equipo no encontrado")

        if not item.is_active:
            raise ValueError("No se puede asignar un equipo dado de baja")

        if item.status != 'ACTIVE':
            raise ValueError(f"No se puede asignar un equipo en estado {item.status}")

        user = db.get(User, user_id)
        if not user:
            raise ValueError("Usuario no encontrado")

        old_assigned_to = item.assigned_to_user_id
        old_location = item.location_detail

        item.assigned_to_user_id = user_id
        item.assigned_by_id = assigned_by_id
        item.assigned_at = datetime.now()

        if location:
            item.location_detail = location

        history = InventoryHistory(
            item_id=item.id,
            event_type='ASSIGNED_TO_USER' if old_assigned_to is None else 'REASSIGNED',
            old_value={
                'assigned_to_user_id': old_assigned_to,
                'location': old_location
            },
            new_value={
                'assigned_to_user_id': user_id,
                'assigned_to_user_name': user.full_name,
                'location': location or old_location
            },
            notes=notes or f'Asignado a {user.full_name}',
            performed_by_id=assigned_by_id,
            ip_address=ip_address
        )
        db.add(history)

        db.commit()
        return item

    @staticmethod
    def unassign_from_user(db: Session, item_id, unassigned_by_id, notes=None, ip_address=None):
        """
        Libera equipo de usuario (lo vuelve global del departamento).
        """
        item = db.get(InventoryItem, item_id)
        if not item:
            raise ValueError("Equipo no encontrado")

        if not item.is_assigned_to_user:
            raise ValueError("El equipo no está asignado a ningún usuario")

        old_user_id = item.assigned_to_user_id
        old_user_name = item.assigned_to_user.full_name if item.assigned_to_user else None

        item.assigned_to_user_id = None
        item.assigned_by_id = None
        item.assigned_at = None

        history = InventoryHistory(
            item_id=item.id,
            event_type='UNASSIGNED',
            old_value={
                'assigned_to_user_id': old_user_id,
                'assigned_to_user_name': old_user_name
            },
            new_value={
                'assigned_to_user_id': None,
                'status': 'Global del departamento'
            },
            notes=notes or 'Equipo liberado y disponible para el departamento',
            performed_by_id=unassigned_by_id,
            ip_address=ip_address
        )
        db.add(history)

        db.commit()
        return item

    @staticmethod
    def change_status(db: Session, item_id, new_status, changed_by_id, notes=None, ip_address=None):
        """
        Cambia el estado de un equipo.
        """
        valid_statuses = ['ACTIVE', 'MAINTENANCE', 'DAMAGED', 'RETIRED', 'LOST']
        if new_status not in valid_statuses:
            raise ValueError(f"Estado inválido. Debe ser uno de: {', '.join(valid_statuses)}")

        item = db.get(InventoryItem, item_id)
        if not item:
            raise ValueError("Equipo no encontrado")

        old_status = item.status
        if old_status == new_status:
            raise ValueError(f"El equipo ya está en estado {new_status}")

        item.status = new_status

        if new_status == 'ACTIVE' and old_status == 'MAINTENANCE':
            item.last_maintenance_date = date.today()
            if item.maintenance_frequency_days:
                item.next_maintenance_date = date.today() + timedelta(days=item.maintenance_frequency_days)

        history = InventoryHistory(
            item_id=item.id,
            event_type='STATUS_CHANGED',
            old_value={'status': old_status},
            new_value={'status': new_status},
            notes=notes or f'Estado cambiado de {old_status} a {new_status}',
            performed_by_id=changed_by_id,
            ip_address=ip_address
        )
        db.add(history)

        db.commit()
        return item

    @staticmethod
    def deactivate_item(db: Session, item_id, deactivated_by_id, reason, ip_address=None):
        """
        Da de baja un equipo (soft delete).
        """
        if not reason or len(reason.strip()) < 10:
            raise ValueError("La razón de baja debe tener al menos 10 caracteres")

        item = db.get(InventoryItem, item_id)
        if not item:
            raise ValueError("Equipo no encontrado")

        if not item.is_active:
            raise ValueError("El equipo ya está dado de baja")

        active_tickets = item.active_tickets_count
        if active_tickets > 0:
            raise ValueError(f"No se puede dar de baja: tiene {active_tickets} ticket(s) activo(s)")

        item.is_active = False
        item.deactivated_at = datetime.now()
        item.deactivated_by_id = deactivated_by_id
        item.deactivation_reason = reason
        item.status = 'RETIRED'

        old_user = None
        if item.assigned_to_user_id:
            old_user = item.assigned_to_user.full_name if item.assigned_to_user else None
            item.assigned_to_user_id = None

        history = InventoryHistory(
            item_id=item.id,
            event_type='DEACTIVATED',
            old_value={
                'is_active': True,
                'status': item.status,
                'assigned_to_user': old_user
            },
            new_value={
                'is_active': False,
                'status': 'RETIRED',
                'deactivation_reason': reason
            },
            notes=reason,
            performed_by_id=deactivated_by_id,
            ip_address=ip_address
        )
        db.add(history)

        db.commit()
        return item

    @staticmethod
    def get_items_for_user(db: Session, user_id, category_id=None):
        """
        Obtiene equipos asignados a un usuario específico.
        """
        query = db.query(InventoryItem).filter(
            InventoryItem.assigned_to_user_id == user_id,
            InventoryItem.is_active == True,
            InventoryItem.status == 'ACTIVE'
        )

        if category_id:
            query = query.filter(InventoryItem.category_id == category_id)

        return query.all()

    @staticmethod
    def get_items_for_department(db: Session, department_id, include_assigned=True):
        """
        Obtiene equipos de un departamento.
        """
        query = db.query(InventoryItem).filter(
            InventoryItem.department_id == department_id,
            InventoryItem.is_active == True
        )

        if not include_assigned:
            query = query.filter(InventoryItem.assigned_to_user_id == None)

        return query.all()

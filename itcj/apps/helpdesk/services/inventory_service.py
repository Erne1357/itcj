"""
Servicio para gestión de inventario
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryItem, InventoryCategory, InventoryHistory
from datetime import datetime, date, timedelta
from flask import g
from sqlalchemy import or_, and_, func


class InventoryService:
    """Lógica de negocio para el sistema de inventario"""
    
    @staticmethod
    def generate_inventory_number(category_id):
        """
        Genera número de inventario único
        Formato: [PREFIX]-[YEAR]-[SEQUENCE]
        Ejemplo: COMP-2025-001
        """
        category = InventoryCategory.query.get(category_id)
        if not category:
            raise ValueError("Categoría no encontrada")
        
        prefix = category.inventory_prefix
        year = datetime.now().year
        
        # Buscar el último número de la categoría en el año actual
        last_item = db.session.query(InventoryItem).filter(
            InventoryItem.category_id == category_id,
            InventoryItem.inventory_number.like(f"{prefix}-{year}-%")
        ).order_by(InventoryItem.id.desc()).first()
        
        if last_item:
            # Extraer el número de secuencia
            try:
                last_sequence = int(last_item.inventory_number.split('-')[-1])
                next_sequence = last_sequence + 1
            except:
                next_sequence = 1
        else:
            next_sequence = 1
        
        # Formato: PREFIX-YYYY-NNNN (4 dígitos con ceros a la izquierda)
        inventory_number = f"{prefix}-{year}-{next_sequence:04d}"
        
        return inventory_number
    
    @staticmethod
    def create_item(data, registered_by_id, ip_address=None):
        """
        Registra un nuevo equipo en el inventario
        
        Args:
            data: dict con los datos del equipo
            registered_by_id: ID del usuario que registra
            ip_address: IP del usuario (opcional)
        
        Returns:
            InventoryItem creado
        """
        # Validaciones
        if not data.get('category_id'):
            raise ValueError("Categoría requerida")
        if not data.get('department_id'):
            raise ValueError("Departamento requerido")
        
        # Generar número de inventario si no viene
        if not data.get('inventory_number'):
            data['inventory_number'] = InventoryService.generate_inventory_number(
                data['category_id']
            )
        
        # Validar que el número no exista
        existing = InventoryItem.query.filter_by(
            inventory_number=data['inventory_number']
        ).first()
        if existing:
            raise ValueError(f"El número de inventario {data['inventory_number']} ya existe")
        
        # Validar serie única (si viene)
        if data.get('serial_number'):
            existing_serial = InventoryItem.query.filter_by(
                serial_number=data['serial_number']
            ).first()
            if existing_serial:
                raise ValueError(f"El número de serie {data['serial_number']} ya existe")
        
        # Calcular next_maintenance_date si tiene frequency
        if data.get('maintenance_frequency_days'):
            base_date = data.get('last_maintenance_date') or data.get('acquisition_date') or date.today()
            data['next_maintenance_date'] = base_date + timedelta(days=data['maintenance_frequency_days'])
        
        # Crear item
        item = InventoryItem(
            inventory_number=data['inventory_number'],
            category_id=data['category_id'],
            brand=data.get('brand'),
            model=data.get('model'),
            serial_number=data.get('serial_number'),
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
        
        db.session.add(item)
        db.session.flush()  # Para obtener el ID
        
        # Registrar en historial
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
        db.session.add(history)
        
        db.session.commit()
        
        return item
    
    @staticmethod
    def update_item(item_id, data, updated_by_id, ip_address=None):
        """
        Actualiza información de un equipo
        
        Args:
            item_id: ID del equipo
            data: dict con campos a actualizar
            updated_by_id: ID del usuario que actualiza
            ip_address: IP del usuario
        
        Returns:
            InventoryItem actualizado
        """
        item = InventoryItem.query.get(item_id)
        if not item:
            raise ValueError("Equipo no encontrado")
        
        if not item.is_active:
            raise ValueError("No se puede editar un equipo dado de baja")
        
        # Campos permitidos para actualizar
        updatable_fields = [
            'brand', 'model', 'specifications', 'location_detail',
            'warranty_expiration', 'maintenance_frequency_days', 'notes'
        ]
        
        changes = {}
        for field in updatable_fields:
            if field in data:
                old_value = getattr(item, field)
                new_value = data[field]
                if old_value != new_value:
                    changes[field] = {'old': old_value, 'new': new_value}
                    setattr(item, field, new_value)
        
        # Recalcular next_maintenance_date si cambió frequency
        if 'maintenance_frequency_days' in changes and item.maintenance_frequency_days:
            base_date = item.last_maintenance_date or item.acquisition_date or date.today()
            item.next_maintenance_date = base_date + timedelta(days=item.maintenance_frequency_days)
        
        if changes:
            # Registrar en historial
            history = InventoryHistory(
                item_id=item.id,
                event_type='SPECS_UPDATED',
                old_value={'changes': {k: v['old'] for k, v in changes.items()}},
                new_value={'changes': {k: v['new'] for k, v in changes.items()}},
                notes=data.get('update_notes', 'Información actualizada'),
                performed_by_id=updated_by_id,
                ip_address=ip_address
            )
            db.session.add(history)
        
        db.session.commit()
        return item
    
    @staticmethod
    def assign_to_user(item_id, user_id, assigned_by_id, location=None, notes=None, ip_address=None):
        """
        Asigna equipo a un usuario específico
        
        Args:
            item_id: ID del equipo
            user_id: ID del usuario destino
            assigned_by_id: ID de quien asigna (jefe o admin)
            location: Ubicación específica (opcional)
            notes: Observaciones (opcional)
            ip_address: IP de quien asigna
        
        Returns:
            InventoryItem actualizado
        """
        from itcj.core.models.user import User
        
        item = InventoryItem.query.get(item_id)
        if not item:
            raise ValueError("Equipo no encontrado")
        
        if not item.is_active:
            raise ValueError("No se puede asignar un equipo dado de baja")
        
        if item.status != 'ACTIVE':
            raise ValueError(f"No se puede asignar un equipo en estado {item.status}")
        
        # Validar que el usuario exista y pertenezca al departamento
        user = User.query.get(user_id)
        if not user:
            raise ValueError("Usuario no encontrado")
        
        # Aquí podrías validar que el usuario pertenezca al departamento del equipo
        # (depende de cómo tengas estructurado users-departments)
        
        # Guardar estado anterior
        old_assigned_to = item.assigned_to_user_id
        old_location = item.location_detail
        
        # Actualizar
        item.assigned_to_user_id = user_id
        item.assigned_by_id = assigned_by_id
        item.assigned_at = datetime.now()
        
        if location:
            item.location_detail = location
        
        # Registrar en historial
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
        db.session.add(history)
        
        db.session.commit()
        return item
    
    @staticmethod
    def unassign_from_user(item_id, unassigned_by_id, notes=None, ip_address=None):
        """
        Libera equipo de usuario (lo vuelve global del departamento)
        
        Args:
            item_id: ID del equipo
            unassigned_by_id: ID de quien libera
            notes: Razón de la liberación
            ip_address: IP de quien libera
        
        Returns:
            InventoryItem actualizado
        """
        item = InventoryItem.query.get(item_id)
        if not item:
            raise ValueError("Equipo no encontrado")
        
        if not item.is_assigned_to_user:
            raise ValueError("El equipo no está asignado a ningún usuario")
        
        # Guardar estado anterior
        old_user_id = item.assigned_to_user_id
        old_user_name = item.assigned_to_user.full_name if item.assigned_to_user else None
        
        # Liberar
        item.assigned_to_user_id = None
        item.assigned_by_id = None
        item.assigned_at = None
        
        # Registrar en historial
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
        db.session.add(history)
        
        db.session.commit()
        return item
    
    @staticmethod
    def change_status(item_id, new_status, changed_by_id, notes=None, ip_address=None):
        """
        Cambia el estado de un equipo
        
        Args:
            item_id: ID del equipo
            new_status: Nuevo estado (ACTIVE, MAINTENANCE, DAMAGED, RETIRED, LOST)
            changed_by_id: ID de quien cambia el estado
            notes: Observaciones
            ip_address: IP de quien cambia
        
        Returns:
            InventoryItem actualizado
        """
        valid_statuses = ['ACTIVE', 'MAINTENANCE', 'DAMAGED', 'RETIRED', 'LOST']
        if new_status not in valid_statuses:
            raise ValueError(f"Estado inválido. Debe ser uno de: {', '.join(valid_statuses)}")
        
        item = InventoryItem.query.get(item_id)
        if not item:
            raise ValueError("Equipo no encontrado")
        
        old_status = item.status
        if old_status == new_status:
            raise ValueError(f"El equipo ya está en estado {new_status}")
        
        # Actualizar
        item.status = new_status
        
        # Si cambia a MAINTENANCE, registrar fecha
        if new_status == 'MAINTENANCE':
            # Se podría agregar un campo maintenance_start_date
            pass
        
        # Si vuelve a ACTIVE desde MAINTENANCE, actualizar last_maintenance
        if new_status == 'ACTIVE' and old_status == 'MAINTENANCE':
            item.last_maintenance_date = date.today()
            if item.maintenance_frequency_days:
                item.next_maintenance_date = date.today() + timedelta(days=item.maintenance_frequency_days)
        
        # Registrar en historial
        history = InventoryHistory(
            item_id=item.id,
            event_type='STATUS_CHANGED',
            old_value={'status': old_status},
            new_value={'status': new_status},
            notes=notes or f'Estado cambiado de {old_status} a {new_status}',
            performed_by_id=changed_by_id,
            ip_address=ip_address
        )
        db.session.add(history)
        
        db.session.commit()
        return item
    
    @staticmethod
    def deactivate_item(item_id, deactivated_by_id, reason, ip_address=None):
        """
        Da de baja un equipo (soft delete)
        
        Args:
            item_id: ID del equipo
            deactivated_by_id: ID de quien da de baja
            reason: Razón de la baja (obligatorio)
            ip_address: IP de quien da de baja
        
        Returns:
            InventoryItem dado de baja
        """
        if not reason or len(reason.strip()) < 10:
            raise ValueError("La razón de baja debe tener al menos 10 caracteres")
        
        item = InventoryItem.query.get(item_id)
        if not item:
            raise ValueError("Equipo no encontrado")
        
        if not item.is_active:
            raise ValueError("El equipo ya está dado de baja")
        
        # Verificar que no tenga tickets activos
        active_tickets = item.active_tickets_count
        if active_tickets > 0:
            raise ValueError(f"No se puede dar de baja: tiene {active_tickets} ticket(s) activo(s)")
        
        # Dar de baja
        item.is_active = False
        item.deactivated_at = datetime.now()
        item.deactivated_by_id = deactivated_by_id
        item.deactivation_reason = reason
        item.status = 'RETIRED'
        
        # Si estaba asignado, liberar
        old_user = None
        if item.assigned_to_user_id:
            old_user = item.assigned_to_user.full_name if item.assigned_to_user else None
            item.assigned_to_user_id = None
        
        # Registrar en historial
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
        db.session.add(history)
        
        db.session.commit()
        return item
    
    @staticmethod
    def get_items_for_user(user_id, category_id=None):
        """
        Obtiene equipos asignados a un usuario específico
        
        Args:
            user_id: ID del usuario
            category_id: Filtrar por categoría (opcional)
        
        Returns:
            Lista de InventoryItem
        """
        query = InventoryItem.query.filter(
            InventoryItem.assigned_to_user_id == user_id,
            InventoryItem.is_active == True,
            InventoryItem.status == 'ACTIVE'
        )
        
        if category_id:
            query = query.filter(InventoryItem.category_id == category_id)
        
        return query.all()
    
    @staticmethod
    def get_items_for_department(department_id, include_assigned=True):
        """
        Obtiene equipos de un departamento
        
        Args:
            department_id: ID del departamento
            include_assigned: Si incluir equipos asignados a usuarios (default: True)
        
        Returns:
            Lista de InventoryItem
        """
        query = InventoryItem.query.filter(
            InventoryItem.department_id == department_id,
            InventoryItem.is_active == True
        )
        
        if not include_assigned:
            query = query.filter(InventoryItem.assigned_to_user_id == None)
        
        return query.all()
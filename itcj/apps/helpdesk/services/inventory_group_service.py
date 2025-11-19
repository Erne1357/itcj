"""
Servicio para gestión de grupos de inventario (salones, laboratorios, etc.)
"""
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import InventoryGroup, InventoryGroupCapacity, InventoryItem, InventoryHistory
from itcj.core.models.department import Department
from sqlalchemy import and_, or_
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class InventoryGroupService:
    """Servicio para operaciones CRUD de grupos de inventario"""
    
    @staticmethod
    def generate_group_code(department_code: str, group_name: str) -> str:
        """
        Genera un código único para el grupo.
        Formato: DEPT_CODE-TYPE-NAME
        Ejemplo: IND-SALON-203, CC-LAB-ELECT
        """
        # Limpiar nombre: solo alfanuméricos y guiones
        clean_name = ''.join(c if c.isalnum() else '-' for c in group_name.upper())
        clean_name = clean_name[:20]  # Limitar longitud
        
        base_code = f"{department_code.upper()}-{clean_name}"
        
        # Verificar si ya existe
        counter = 1
        code = base_code
        while InventoryGroup.query.filter_by(code=code).first():
            code = f"{base_code}-{counter}"
            counter += 1
        
        return code
    
    @staticmethod
    def create_group(data: dict, created_by_id: int) -> InventoryGroup:
        """
        Crea un nuevo grupo de inventario.
        
        Args:
            data: {
                'name': str,
                'department_id': int,
                'group_type': str (opcional),
                'description': str (opcional),
                'building': str (opcional),
                'floor': str (opcional),
                'location_notes': str (opcional),
                'capacities': [
                    {'category_id': int, 'max_capacity': int},
                    ...
                ]
            }
            created_by_id: ID del usuario que crea el grupo
        """
        try:
            # Validar departamento
            department = Department.query.get(data['department_id'])
            if not department:
                raise ValueError(f"Departamento {data['department_id']} no encontrado")
            
            # Generar código único
            code = InventoryGroupService.generate_group_code(
                department.code,
                data['name']
            )
            
            # Crear grupo
            group = InventoryGroup(
                name=data['name'],
                code=code,
                department_id=data['department_id'],
                group_type=data.get('group_type', 'CLASSROOM'),
                description=data.get('description'),
                building=data.get('building'),
                floor=data.get('floor'),
                location_notes=data.get('location_notes'),
                created_by_id=created_by_id,
                is_active=True
            )
            
            db.session.add(group)
            db.session.flush()  # Para obtener el ID
            
            # Crear capacidades
            if 'capacities' in data and data['capacities']:
                for cap_data in data['capacities']:
                    if cap_data['max_capacity'] > 0:
                        capacity = InventoryGroupCapacity(
                            group_id=group.id,
                            category_id=cap_data['category_id'],
                            max_capacity=cap_data['max_capacity']
                        )
                        db.session.add(capacity)
            
            db.session.commit()
            logger.info(f"Grupo creado: {group.code} por usuario {created_by_id}")
            
            return group
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al crear grupo: {str(e)}")
            raise
    
    @staticmethod
    def update_group(group_id: int, data: dict) -> InventoryGroup:
        """Actualiza información de un grupo"""
        try:
            group = InventoryGroup.query.get(group_id)
            if not group:
                raise ValueError(f"Grupo {group_id} no encontrado")
            
            # Actualizar campos básicos
            if 'name' in data:
                group.name = data['name']
            if 'group_type' in data:
                group.group_type = data['group_type']
            if 'description' in data:
                group.description = data['description']
            if 'building' in data:
                group.building = data['building']
            if 'floor' in data:
                group.floor = data['floor']
            if 'location_notes' in data:
                group.location_notes = data['location_notes']
            if 'is_active' in data:
                group.is_active = data['is_active']
            
            db.session.commit()
            logger.info(f"Grupo actualizado: {group.code}")
            
            return group
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al actualizar grupo: {str(e)}")
            raise
    
    @staticmethod
    def update_capacities(group_id: int, capacities: list) -> InventoryGroup:
        """
        Actualiza las capacidades de un grupo.
        
        Args:
            group_id: ID del grupo
            capacities: [{'category_id': int, 'max_capacity': int}, ...]
        """
        try:
            group = InventoryGroup.query.get(group_id)
            if not group:
                raise ValueError(f"Grupo {group_id} no encontrado")
            
            # Validar que no se reduzca la capacidad por debajo de equipos asignados
            for cap_data in capacities:
                category_id = cap_data['category_id']
                new_capacity = cap_data['max_capacity']
                
                current_count = group.get_assigned_count_for_category(category_id)
                if new_capacity < current_count:
                    raise ValueError(
                        f"No se puede reducir capacidad a {new_capacity}. "
                        f"Hay {current_count} equipos asignados de esta categoría."
                    )
            
            # Eliminar capacidades existentes
            InventoryGroupCapacity.query.filter_by(group_id=group_id).delete()
            
            # Crear nuevas capacidades
            for cap_data in capacities:
                if cap_data['max_capacity'] > 0:
                    capacity = InventoryGroupCapacity(
                        group_id=group_id,
                        category_id=cap_data['category_id'],
                        max_capacity=cap_data['max_capacity']
                    )
                    db.session.add(capacity)
            
            db.session.commit()
            logger.info(f"Capacidades actualizadas para grupo: {group.code}")
            
            return group
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al actualizar capacidades: {str(e)}")
            raise
    
    @staticmethod
    def delete_group(group_id: int) -> bool:
        """
        Elimina un grupo (solo si está vacío).
        """
        try:
            group = InventoryGroup.query.get(group_id)
            if not group:
                raise ValueError(f"Grupo {group_id} no encontrado")
            
            # Verificar que no tenga equipos asignados
            items_count = group.items.filter_by(is_active=True).count()
            if items_count > 0:
                raise ValueError(
                    f"No se puede eliminar. El grupo tiene {items_count} equipos asignados."
                )
            
            db.session.delete(group)
            db.session.commit()
            logger.info(f"Grupo eliminado: {group.code}")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al eliminar grupo: {str(e)}")
            raise
    
    @staticmethod
    def get_groups_by_department(department_id: int, include_inactive=False):
        """Obtiene todos los grupos de un departamento"""
        query = InventoryGroup.query.filter_by(department_id=department_id)
        
        if not include_inactive:
            query = query.filter_by(is_active=True)
        
        return query.order_by(InventoryGroup.name).all()
    
    @staticmethod
    def get_group_items(group_id: int, category_id=None):
        """
        Obtiene los equipos asignados a un grupo.
        Opcionalmente filtra por categoría.
        """
        query = InventoryItem.query.filter(
            InventoryItem.group_id == group_id,
            InventoryItem.is_active == True
        )
        
        if category_id:
            query = query.filter_by(category_id=category_id)
        
        return query.order_by(InventoryItem.inventory_number).all()
    
    @staticmethod
    def assign_item_to_group(item_id: int, group_id: int, performed_by_id: int) -> InventoryItem:
        """
        Asigna un equipo a un grupo.
        Valida capacidad disponible.
        """
        try:
            item = InventoryItem.query.get(item_id)
            if not item:
                raise ValueError(f"Equipo {item_id} no encontrado")
            
            group = InventoryGroup.query.get(group_id)
            if not group:
                raise ValueError(f"Grupo {group_id} no encontrado")
            
            # Validar que el equipo pertenezca al mismo departamento
            if item.department_id != group.department_id:
                raise ValueError(
                    f"El equipo pertenece al departamento {item.department_id} "
                    f"y el grupo al departamento {group.department_id}"
                )
            
            # Validar capacidad disponible
            available = group.get_available_slots_for_category(item.category_id)
            if available <= 0:
                raise ValueError(
                    f"No hay espacio disponible para esta categoría en el grupo. "
                    f"Capacidad: {group.get_capacity_for_category(item.category_id)}, "
                    f"Asignados: {group.get_assigned_count_for_category(item.category_id)}"
                )
            
            # Guardar valores anteriores para historial
            old_group_id = item.group_id
            
            # Asignar al grupo
            item.group_id = group_id
            
            # Si el equipo estaba PENDING_ASSIGNMENT, cambiar a ACTIVE
            if item.status == 'PENDING_ASSIGNMENT':
                item.status = 'ACTIVE'
            
            # Registrar en historial
            history = InventoryHistory(
                item_id=item.id,
                event_type='ASSIGNED_TO_GROUP',
                old_value={'group_id': old_group_id, 'group_name': None},
                new_value={'group_id': group.id, 'group_name': group.name},
                notes=f"Equipo asignado al grupo {group.name}",
                performed_by_id=performed_by_id
            )
            db.session.add(history)
            
            db.session.commit()
            logger.info(f"Equipo {item.inventory_number} asignado a grupo {group.code}")
            
            return item
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al asignar equipo a grupo: {str(e)}")
            raise
    
    @staticmethod
    def unassign_item_from_group(item_id: int, performed_by_id: int) -> InventoryItem:
        """Remueve un equipo de un grupo"""
        try:
            item = InventoryItem.query.get(item_id)
            if not item:
                raise ValueError(f"Equipo {item_id} no encontrado")
            
            if not item.group_id:
                raise ValueError("El equipo no está asignado a ningún grupo")
            
            # Guardar para historial
            old_group = InventoryGroup.query.get(item.group_id)
            
            # Remover del grupo
            item.group_id = None
            
            # Registrar en historial
            history = InventoryHistory(
                item_id=item.id,
                event_type='UNASSIGNED_FROM_GROUP',
                old_value={'group_id': old_group.id, 'group_name': old_group.name},
                new_value={'group_id': None, 'group_name': None},
                notes=f"Equipo removido del grupo {old_group.name}",
                performed_by_id=performed_by_id
            )
            db.session.add(history)
            
            db.session.commit()
            logger.info(f"Equipo {item.inventory_number} removido de grupo {old_group.code}")
            
            return item
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error al desasignar equipo de grupo: {str(e)}")
            raise
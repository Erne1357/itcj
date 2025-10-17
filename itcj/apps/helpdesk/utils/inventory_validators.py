"""
Validadores para el sistema de inventario
"""
from itcj.apps.helpdesk.models import InventoryItem, InventoryCategory
from itcj.core.models.department import Department
from itcj.core.models.user import User


class InventoryValidators:
    """Validaciones para inventario"""
    
    @staticmethod
    def validate_inventory_number(inventory_number, exclude_id=None):
        """
        Valida que el número de inventario sea único
        
        Args:
            inventory_number: Número a validar
            exclude_id: ID de item a excluir (para edición)
        
        Returns:
            tuple (is_valid: bool, message: str)
        """
        if not inventory_number:
            return False, "Número de inventario requerido"
        
        if len(inventory_number) < 5:
            return False, "Número de inventario muy corto"
        
        query = InventoryItem.query.filter_by(inventory_number=inventory_number)
        
        if exclude_id:
            query = query.filter(InventoryItem.id != exclude_id)
        
        existing = query.first()
        
        if existing:
            return False, f"El número {inventory_number} ya existe"
        
        return True, "OK"
    
    @staticmethod
    def validate_serial_number(serial_number, exclude_id=None):
        """
        Valida que el número de serie sea único
        
        Args:
            serial_number: Serie a validar
            exclude_id: ID de item a excluir (para edición)
        
        Returns:
            tuple (is_valid: bool, message: str)
        """
        if not serial_number:
            # Serie es opcional
            return True, "OK"
        
        query = InventoryItem.query.filter_by(serial_number=serial_number)
        
        if exclude_id:
            query = query.filter(InventoryItem.id != exclude_id)
        
        existing = query.first()
        
        if existing:
            return False, f"El número de serie {serial_number} ya existe en {existing.inventory_number}"
        
        return True, "OK"
    
    @staticmethod
    def validate_category(category_id):
        """
        Valida que la categoría exista y esté activa
        
        Args:
            category_id: ID de la categoría
        
        Returns:
            tuple (is_valid: bool, message: str, category: InventoryCategory)
        """
        if not category_id:
            return False, "Categoría requerida", None
        
        category = InventoryCategory.query.get(category_id)
        
        if not category:
            return False, "Categoría no encontrada", None
        
        if not category.is_active:
            return False, f"La categoría {category.name} está inactiva", None
        
        return True, "OK", category
    
    @staticmethod
    def validate_department(department_id):
        """
        Valida que el departamento exista
        
        Args:
            department_id: ID del departamento
        
        Returns:
            tuple (is_valid: bool, message: str, department: Department)
        """
        if not department_id:
            return False, "Departamento requerido", None
        
        department = Department.query.get(department_id)
        
        if not department:
            return False, "Departamento no encontrado", None
        
        return True, "OK", department
    
    @staticmethod
    def validate_user_for_assignment(user_id, department_id):
        """
        Valida que el usuario exista y pertenezca al departamento
        
        Args:
            user_id: ID del usuario
            department_id: ID del departamento del equipo
        
        Returns:
            tuple (is_valid: bool, message: str, user: User)
        """
        if not user_id:
            return False, "Usuario requerido", None
        
        user = User.query.get(user_id)
        
        if not user:
            return False, "Usuario no encontrado", None
        
        # Aquí podrías validar que el usuario pertenezca al departamento
        # Depende de cómo tengas estructurada la relación users-departments
        # Por ahora solo verificamos que exista
        
        return True, "OK", user
    
    @staticmethod
    def validate_status_transition(current_status, new_status):
        """
        Valida que la transición de estado sea permitida
        
        Args:
            current_status: Estado actual
            new_status: Estado nuevo
        
        Returns:
            tuple (is_valid: bool, message: str)
        """
        valid_statuses = ['ACTIVE', 'MAINTENANCE', 'DAMAGED', 'RETIRED', 'LOST']
        
        if new_status not in valid_statuses:
            return False, f"Estado inválido: {new_status}"
        
        if current_status == new_status:
            return False, f"El equipo ya está en estado {new_status}"
        
        # Definir transiciones permitidas
        allowed_transitions = {
            'ACTIVE': ['MAINTENANCE', 'DAMAGED', 'LOST', 'RETIRED'],
            'MAINTENANCE': ['ACTIVE', 'DAMAGED', 'RETIRED'],
            'DAMAGED': ['MAINTENANCE', 'RETIRED', 'ACTIVE'],
            'LOST': ['ACTIVE', 'RETIRED'],
            'RETIRED': [],  # No se puede cambiar desde RETIRED
        }
        
        if current_status == 'RETIRED':
            return False, "No se puede cambiar el estado de un equipo dado de baja. Use reactivación."
        
        if new_status not in allowed_transitions.get(current_status, []):
            return False, f"No se puede cambiar de {current_status} a {new_status}"
        
        return True, "OK"
    
    @staticmethod
    def validate_specifications(specifications, category):
        """
        Valida especificaciones técnicas según template de categoría
        
        Args:
            specifications: dict con especificaciones
            category: InventoryCategory
        
        Returns:
            tuple (is_valid: bool, message: str, errors: list)
        """
        if not category.requires_specs:
            # No requiere specs
            return True, "OK", []
        
        if not category.spec_template:
            # No hay template definido, cualquier cosa es válida
            return True, "OK", []
        
        errors = []
        
        # Validar campos requeridos del template
        for field_name, field_config in category.spec_template.items():
            if field_config.get('required', False):
                if not specifications or field_name not in specifications:
                    errors.append(f"Campo requerido: {field_config.get('label', field_name)}")
                elif not specifications[field_name]:
                    errors.append(f"Campo requerido: {field_config.get('label', field_name)}")
        
        if errors:
            return False, "Especificaciones incompletas", errors
        
        return True, "OK", []
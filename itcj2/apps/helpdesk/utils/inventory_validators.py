"""
Validadores para el sistema de inventario.
Migrado de itcj/apps/helpdesk/utils/inventory_validators.py (Flask) a SQLAlchemy puro.
"""
from itcj2.apps.helpdesk.models import InventoryItem, InventoryCategory
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.database import SessionLocal


def _get_db():
    """Obtiene una sesión de DB para validaciones standalone."""
    return SessionLocal()


class InventoryValidators:
    """Validaciones para inventario"""

    @staticmethod
    def validate_inventory_number(inventory_number, exclude_id=None, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not inventory_number:
                return False, "Número de inventario requerido"

            if len(inventory_number) < 5:
                return False, "Número de inventario muy corto"

            query = db.query(InventoryItem).filter_by(inventory_number=inventory_number)
            if exclude_id:
                query = query.filter(InventoryItem.id != exclude_id)

            if query.first():
                return False, f"El número {inventory_number} ya existe"

            return True, "OK"
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_supplier_serial(supplier_serial, exclude_id=None, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not supplier_serial:
                return True, "OK"

            query = db.query(InventoryItem).filter_by(supplier_serial=supplier_serial)
            if exclude_id:
                query = query.filter(InventoryItem.id != exclude_id)

            existing = query.first()
            if existing:
                return False, f"El serial de proveedor '{supplier_serial}' ya existe en {existing.inventory_number}"

            return True, "OK"
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_itcj_serial(itcj_serial, exclude_id=None, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not itcj_serial:
                return True, "OK"

            query = db.query(InventoryItem).filter_by(itcj_serial=itcj_serial)
            if exclude_id:
                query = query.filter(InventoryItem.id != exclude_id)

            existing = query.first()
            if existing:
                return False, f"El serial ITCJ '{itcj_serial}' ya existe en {existing.inventory_number}"

            return True, "OK"
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_id_tecnm(id_tecnm, exclude_id=None, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not id_tecnm:
                return True, "OK"

            query = db.query(InventoryItem).filter_by(id_tecnm=id_tecnm)
            if exclude_id:
                query = query.filter(InventoryItem.id != exclude_id)

            existing = query.first()
            if existing:
                return False, f"El ID TecNM '{id_tecnm}' ya existe en {existing.inventory_number}"

            return True, "OK"
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_category(category_id, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not category_id:
                return False, "Categoría requerida", None

            category = db.get(InventoryCategory, category_id)
            if not category:
                return False, "Categoría no encontrada", None

            if not category.is_active:
                return False, f"La categoría {category.name} está inactiva", None

            return True, "OK", category
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_department(department_id, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not department_id:
                return False, "Departamento requerido", None

            department = db.get(Department, department_id)
            if not department:
                return False, "Departamento no encontrado", None

            return True, "OK", department
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_user_for_assignment(user_id, department_id, db=None):
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            if not user_id:
                return False, "Usuario requerido", None

            user = db.get(User, user_id)
            if not user:
                return False, "Usuario no encontrado", None

            return True, "OK", user
        finally:
            if own_session:
                db.close()

    @staticmethod
    def validate_status_transition(current_status, new_status):
        valid_statuses = ['ACTIVE', 'MAINTENANCE', 'DAMAGED', 'RETIRED', 'LOST']

        if new_status not in valid_statuses:
            return False, f"Estado inválido: {new_status}"

        if current_status == new_status:
            return False, f"El equipo ya está en estado {new_status}"

        allowed_transitions = {
            'ACTIVE': ['MAINTENANCE', 'DAMAGED', 'LOST', 'RETIRED'],
            'MAINTENANCE': ['ACTIVE', 'DAMAGED', 'RETIRED'],
            'DAMAGED': ['MAINTENANCE', 'RETIRED', 'ACTIVE'],
            'LOST': ['ACTIVE', 'RETIRED'],
            'RETIRED': [],
        }

        if current_status == 'RETIRED':
            return False, "No se puede cambiar el estado de un equipo dado de baja. Use reactivación."

        if new_status not in allowed_transitions.get(current_status, []):
            return False, f"No se puede cambiar de {current_status} a {new_status}"

        return True, "OK"

    @staticmethod
    def validate_specifications(specifications, category):
        if not category.requires_specs:
            return True, "OK", []

        if not category.spec_template:
            return True, "OK", []

        errors = []

        for field_name, field_config in category.spec_template.items():
            if field_config.get('required', False):
                if not specifications or field_name not in specifications:
                    errors.append(f"Campo requerido: {field_config.get('label', field_name)}")
                else:
                    value = specifications[field_name]
                    # Permitir False (boolean) y 0 (number) como valores válidos
                    if value is None or (isinstance(value, str) and not value.strip()):
                         errors.append(f"Campo requerido: {field_config.get('label', field_name)}")

        if errors:
            return False, "Especificaciones incompletas", errors

        return True, "OK", []

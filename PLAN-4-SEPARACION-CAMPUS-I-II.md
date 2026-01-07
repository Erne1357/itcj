# PLAN DE IMPLEMENTACIÓN #4: SEPARACIÓN CAMPUS I Y CAMPUS II

**Proyecto:** Sistema Helpdesk - ITCJ
**Fecha:** 2026-01-06
**Autor:** Análisis de sistema actual + propuesta técnica
**Prioridad:** Alta
**Complejidad:** Media-Alta

---

## 📋 RESUMEN EJECUTIVO

Implementar **separación completa** de operaciones entre Campus I y Campus II en el sistema de helpdesk, permitiendo que cada campus funcione de manera independiente con sus propios técnicos, departamentos y flujos de trabajo, mientras mantiene una arquitectura unificada.

**Situación actual:**
- Todo el sistema está diseñado para Campus I (Centro de Cómputo único)
- No hay distinción entre campus en la base de datos
- Técnicos de Campus I reciben tickets de todos los usuarios
- No hay forma de separar inventario, departamentos ni reportes por campus

**Contexto organizacional del Campus II:**
- **Completamente independiente:** Tiene su propio Centro de Cómputo, jefe, staff técnico
- **Estructura simplificada:** Todo Campus II es un solo departamento grande, sin subdivisión interna por carreras
- **No cruzan tickets:** Las solicitudes de Campus II deben ir SOLO a técnicos de Campus II
- **Diferentes procesos:** Pueden tener sus propias categorías, políticas, horarios

**Solución propuesta:**
- Agregar campo `campus` a nivel de `Department` (CAMPUS_I, CAMPUS_II)
- Usuarios heredan campus de su departamento
- Filtrado automático de tickets por campus
- Roles de técnicos específicos por campus
- Inventario segregado por campus
- Dashboard y reportes por campus
- Administración centralizada con visibilidad global (super admin)

---

## 🎯 OBJETIVOS

### Objetivos principales:
1. **Separación total de operaciones** entre Campus I y Campus II
2. **Prevenir cruces** de tickets entre campus
3. **Autonomía operativa** para cada campus
4. **Arquitectura escalable** para futuros campus (III, IV, etc.)
5. **Mantener sistema unificado** (una sola aplicación, una BD)

### Objetivos secundarios:
- Reportes comparativos entre campus
- Flexibilidad para compartir categorías o tenerlas propias
- Posibilidad de transferir tickets entre campus (casos excepcionales)
- Visibilidad global para directivos

---

## 🏗️ ARQUITECTURA DE LA SOLUCIÓN

### Opción Seleccionada: **Campus a nivel de Department**

Basándonos en que:
- Campus II es organizacionalmente "un departamento" del Tec
- Pero internamente opera de forma independiente
- La jerarquía debe ser flexible

**Estructura propuesta:**

```
Dirección (parent_id = NULL, campus = NULL)  [Nivel institucional]
│
├── Campus I (parent_id = Dirección, campus = CAMPUS_I)
│   ├── Centro de Cómputo - Campus I
│   ├── Sistemas - Campus I
│   ├── Industrial - Campus I
│   ├── Electrónica - Campus I
│   └── ... [todos los departamentos académicos]
│
└── Campus II (parent_id = Dirección, campus = CAMPUS_II)
    ├── Centro de Cómputo - Campus II
    ├── Edificio A - Campus II [opcional, subdivisión interna]
    ├── Edificio B - Campus II [opcional]
    └── ... [estructura flexible]
```

### Componentes a modificar:

```
itcj/core/
└── models/
    └── department.py                   [MODIFICAR] Agregar campo campus

apps/helpdesk/
├── models/
│   ├── ticket.py                       [MODIFICAR] Heredar campus
│   └── inventory_item.py               [MODIFICAR] Campus en inventario
│
├── services/
│   ├── ticket_service.py               [MODIFICAR] Filtrado por campus
│   ├── assignment_service.py           [MODIFICAR] Asignación por campus
│   ├── inventory_service.py            [MODIFICAR] Inventario por campus
│   └── campus_service.py               [NUEVO] Lógica de campus
│
├── routes/
│   ├── api/
│   │   └── tickets/
│   │       └── base.py                 [MODIFICAR] Filtros por campus
│   └── pages/
│       ├── technician.py               [MODIFICAR] Vista por campus
│       ├── admin.py                    [MODIFICAR] Selección de campus
│       └── campus_admin.py             [NUEVO] Admin específico de campus
│
├── templates/helpdesk/
│   ├── technician/
│   │   └── home.html                   [MODIFICAR] Filtro campus
│   ├── admin/
│   │   └── campus_selector.html       [NUEVO] Selector de campus
│   └── shared/
│       └── campus_badge.html           [NUEVO] Badge de campus
│
└── utils/
    ├── campus_filter.py                [NUEVO] Decorador de filtrado
    └── navigation.py                   [MODIFICAR] Menú por campus
```

---

## 💾 MODIFICACIONES A BASE DE DATOS

### 1. Modificar Department (core)

**Tabla:** `core_departments`

```python
class Department(db.Model):
    # ... campos existentes ...

    # NUEVO CAMPO
    campus = db.Column(db.String(20), nullable=True, default='CAMPUS_I')
    # Valores permitidos:
    #   - NULL: Nivel institucional (Dirección)
    #   - 'CAMPUS_I': Campus I
    #   - 'CAMPUS_II': Campus II
    #   - 'CAMPUS_III': Campus III (futuro)

    # NUEVOS MÉTODOS
    @property
    def campus_display_name(self):
        """Nombre legible del campus"""
        campus_names = {
            'CAMPUS_I': 'Campus I',
            'CAMPUS_II': 'Campus II',
            'CAMPUS_III': 'Campus III',
        }
        return campus_names.get(self.campus, 'Sin Campus')

    @property
    def is_campus_root(self):
        """Indica si este departamento es raíz de un campus"""
        # Ej: "Campus II" con parent_id = Dirección
        return self.campus is not None and self.parent and self.parent.is_direction()

    def get_campus_root(self):
        """Obtiene el departamento raíz del campus"""
        if self.is_campus_root:
            return self
        if self.parent:
            return self.parent.get_campus_root()
        return None

    @staticmethod
    def get_all_campus():
        """Retorna lista de campus existentes"""
        campus_list = db.session.query(Department.campus).distinct().filter(
            Department.campus.isnot(None)
        ).all()
        return [c[0] for c in campus_list]
```

**Migración SQL:**
```sql
-- Agregar columna campus
ALTER TABLE core_departments
ADD COLUMN campus VARCHAR(20);

-- Crear índice
CREATE INDEX idx_departments_campus ON core_departments(campus);

-- Migrar datos existentes (todos los departamentos actuales son Campus I)
UPDATE core_departments
SET campus = 'CAMPUS_I'
WHERE campus IS NULL AND parent_id IS NOT NULL;
-- Dejar NULL solo para la Dirección

-- Crear departamento raíz de Campus II
INSERT INTO core_departments (code, name, description, parent_id, campus, is_active)
VALUES (
    'campus_ii',
    'Campus II',
    'Campus II del Tecnológico',
    (SELECT id FROM core_departments WHERE code = 'direccion'),
    'CAMPUS_II',
    true
);

-- Crear Centro de Cómputo - Campus II
INSERT INTO core_departments (code, name, description, parent_id, campus, is_active)
VALUES (
    'cc_campus_ii',
    'Centro de Cómputo - Campus II',
    'Centro de Cómputo del Campus II',
    (SELECT id FROM core_departments WHERE code = 'campus_ii'),
    'CAMPUS_II',
    true
);
```

### 2. Modificar Ticket

**Tabla:** `helpdesk_tickets`

```python
class Ticket(db.Model):
    # ... campos existentes ...

    # NUEVO CAMPO (desnormalizado para performance)
    campus = db.Column(db.String(20), nullable=True, index=True)
    # Se llena automáticamente del department del requester

    # MODIFICAR método create
    @staticmethod
    def create_ticket(**kwargs):
        # ... lógica existente ...

        # Determinar campus automáticamente
        if requester_department:
            ticket.campus = requester_department.campus

        # ... resto de la lógica ...

    # NUEVOS MÉTODOS
    @property
    def campus_display_name(self):
        campus_names = {
            'CAMPUS_I': 'Campus I',
            'CAMPUS_II': 'Campus II',
        }
        return campus_names.get(self.campus, 'Sin Campus')

    @property
    def campus_badge_class(self):
        """Clase CSS para badge de campus"""
        campus_colors = {
            'CAMPUS_I': 'primary',
            'CAMPUS_II': 'success',
            'CAMPUS_III': 'info',
        }
        return campus_colors.get(self.campus, 'secondary')
```

**Migración SQL:**
```sql
-- Agregar columna campus
ALTER TABLE helpdesk_tickets
ADD COLUMN campus VARCHAR(20);

-- Crear índice
CREATE INDEX idx_tickets_campus ON helpdesk_tickets(campus);

-- Migrar datos existentes (heredar de departamento)
UPDATE helpdesk_tickets t
SET campus = d.campus
FROM core_departments d
WHERE t.requester_department_id = d.id;

-- Tickets sin departamento → Campus I por defecto
UPDATE helpdesk_tickets
SET campus = 'CAMPUS_I'
WHERE campus IS NULL;
```

### 3. Modificar InventoryItem

**Tabla:** `helpdesk_inventory_items`

```python
class InventoryItem(db.Model):
    # ... campos existentes ...

    # NUEVO CAMPO
    campus = db.Column(db.String(20), nullable=True, index=True)
    # Heredado del department

    # MODIFICAR métodos de creación
    @staticmethod
    def register_item(**kwargs):
        # ... lógica existente ...

        # Determinar campus del departamento
        if department_id:
            dept = Department.query.get(department_id)
            item.campus = dept.campus

        # ... resto de la lógica ...

    # MODIFICAR inventory_number para incluir campus
    @staticmethod
    def generate_inventory_number(category, campus=None):
        """
        Genera número de inventario con prefijo de campus.

        Ejemplos:
            - C1-COMP-2026-001 (Campus I)
            - C2-COMP-2026-001 (Campus II)
        """
        year = datetime.now().year
        prefix = category.inventory_prefix  # COMP, IMP, etc.

        # Prefijo de campus
        campus_prefix = ''
        if campus == 'CAMPUS_I':
            campus_prefix = 'C1-'
        elif campus == 'CAMPUS_II':
            campus_prefix = 'C2-'
        elif campus == 'CAMPUS_III':
            campus_prefix = 'C3-'

        # Contar items existentes en este campus
        count = InventoryItem.query.filter_by(
            category_id=category.id,
            campus=campus
        ).filter(
            InventoryItem.inventory_number.like(f'{campus_prefix}{prefix}-{year}-%')
        ).count()

        number = count + 1
        return f"{campus_prefix}{prefix}-{year}-{number:03d}"
```

**Migración SQL:**
```sql
-- Agregar columna campus
ALTER TABLE helpdesk_inventory_items
ADD COLUMN campus VARCHAR(20);

-- Crear índice
CREATE INDEX idx_inventory_items_campus ON helpdesk_inventory_items(campus);

-- Migrar datos existentes (heredar de departamento)
UPDATE helpdesk_inventory_items i
SET campus = d.campus
FROM core_departments d
WHERE i.department_id = d.id;

-- Items sin departamento → Campus I por defecto
UPDATE helpdesk_inventory_items
SET campus = 'CAMPUS_I'
WHERE campus IS NULL;
```

### 4. Modificar Roles y Permisos

**Nuevos roles por campus:**

```sql
-- Roles actuales (Campus I):
-- - tech_desarrollo (ya existe)
-- - tech_soporte (ya existe)

-- Nuevos roles para Campus II:
-- - tech_desarrollo_c2
-- - tech_soporte_c2
-- - admin_campus_ii

-- Crear nuevos roles (vía código de inicialización)
```

```python
# En seed/initialization script
CAMPUS_II_ROLES = [
    {
        'code': 'tech_desarrollo_c2',
        'name': 'Técnico de Desarrollo - Campus II',
        'description': 'Técnico del área de desarrollo en Campus II',
        'app': 'helpdesk'
    },
    {
        'code': 'tech_soporte_c2',
        'name': 'Técnico de Soporte - Campus II',
        'description': 'Técnico del área de soporte en Campus II',
        'app': 'helpdesk'
    },
    {
        'code': 'admin_campus_ii',
        'name': 'Administrador Campus II',
        'description': 'Administrador del helpdesk para Campus II',
        'app': 'helpdesk'
    },
]
```

---

## 🔧 SERVICIOS (Lógica de negocio)

### 1. CampusService (Nuevo)

**Archivo:** `apps/helpdesk/services/campus_service.py`

```python
class CampusService:
    """Servicio para gestionar lógica relacionada con campus"""

    CAMPUS_I = 'CAMPUS_I'
    CAMPUS_II = 'CAMPUS_II'
    CAMPUS_III = 'CAMPUS_III'

    CAMPUS_NAMES = {
        CAMPUS_I: 'Campus I',
        CAMPUS_II: 'Campus II',
        CAMPUS_III: 'Campus III',
    }

    CAMPUS_TECH_ROLES = {
        CAMPUS_I: ['tech_desarrollo', 'tech_soporte'],
        CAMPUS_II: ['tech_desarrollo_c2', 'tech_soporte_c2'],
    }

    @staticmethod
    def get_user_campus(user_id):
        """
        Determina el campus de un usuario basado en su departamento.

        Returns:
            str: 'CAMPUS_I', 'CAMPUS_II', etc., o None
        """
        user = User.query.get(user_id)
        if not user:
            return None

        department = user.get_current_department()
        if not department:
            return CampusService.CAMPUS_I  # Default Campus I

        dept = Department.query.get(department)
        return dept.campus if dept else CampusService.CAMPUS_I

    @staticmethod
    def get_user_campus_from_department(department_id):
        """
        Obtiene campus desde un department_id.

        Returns:
            str: 'CAMPUS_I', 'CAMPUS_II', etc.
        """
        dept = Department.query.get(department_id)
        return dept.campus if dept else CampusService.CAMPUS_I

    @staticmethod
    def can_user_access_campus(user_id, campus, user_roles):
        """
        Verifica si un usuario puede acceder a recursos de un campus específico.

        Args:
            user_id: ID del usuario
            campus: Campus a verificar
            user_roles: Roles del usuario

        Returns:
            bool: True si puede acceder
        """
        # Super admin puede todo
        if 'admin' in user_roles:
            return True

        # Admins de campus específico
        if campus == CampusService.CAMPUS_I and 'admin_campus_i' in user_roles:
            return True
        if campus == CampusService.CAMPUS_II and 'admin_campus_ii' in user_roles:
            return True

        # Técnicos solo acceden a su campus
        user_campus = CampusService.get_user_campus(user_id)
        tech_roles = CampusService.CAMPUS_TECH_ROLES.get(campus, [])

        for role in user_roles:
            if role in tech_roles and user_campus == campus:
                return True

        # Usuarios normales solo acceden a su campus
        return user_campus == campus

    @staticmethod
    def get_technicians_for_campus(campus, area=None):
        """
        Obtiene técnicos disponibles para un campus y área.

        Args:
            campus: 'CAMPUS_I', 'CAMPUS_II'
            area: 'DESARROLLO', 'SOPORTE' (opcional)

        Returns:
            [
                {
                    'user_id': int,
                    'full_name': str,
                    'area': str,
                    'campus': str
                },
                ...
            ]
        """
        tech_roles = CampusService.CAMPUS_TECH_ROLES.get(campus, [])

        if area == 'DESARROLLO':
            tech_roles = [r for r in tech_roles if 'desarrollo' in r]
        elif area == 'SOPORTE':
            tech_roles = [r for r in tech_roles if 'soporte' in r]

        # Query usuarios con esos roles
        # (Implementación depende del sistema de roles actual)
        technicians = []
        for role_code in tech_roles:
            users = _get_users_with_role(role_code)
            for user in users:
                technicians.append({
                    'user_id': user.id,
                    'full_name': user.full_name,
                    'area': 'DESARROLLO' if 'desarrollo' in role_code else 'SOPORTE',
                    'campus': campus
                })

        return technicians

    @staticmethod
    def get_campus_statistics(campus, start_date=None, end_date=None):
        """
        Obtiene estadísticas de un campus.

        Returns:
            {
                'total_tickets': int,
                'pending': int,
                'in_progress': int,
                'resolved': int,
                'avg_resolution_time': float,
                'technicians_count': int,
                'departments_count': int,
                'inventory_items_count': int
            }
        """
        query = Ticket.query.filter_by(campus=campus)

        if start_date:
            query = query.filter(Ticket.created_at >= start_date)
        if end_date:
            query = query.filter(Ticket.created_at <= end_date)

        tickets = query.all()

        return {
            'total_tickets': len(tickets),
            'pending': sum(1 for t in tickets if t.status == 'PENDING'),
            'in_progress': sum(1 for t in tickets if t.status == 'IN_PROGRESS'),
            'resolved': sum(1 for t in tickets if t.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED']),
            'technicians_count': len(CampusService.get_technicians_for_campus(campus)),
            'departments_count': Department.query.filter_by(campus=campus).count(),
            'inventory_items_count': InventoryItem.query.filter_by(campus=campus).count()
        }

    @staticmethod
    def transfer_ticket_to_campus(ticket_id, target_campus, transferred_by_id, reason):
        """
        Transfiere un ticket a otro campus (caso excepcional).

        Args:
            ticket_id: ID del ticket
            target_campus: Campus destino
            transferred_by_id: Admin que autoriza
            reason: Razón de la transferencia

        Returns:
            Ticket actualizado

        Raises:
            ValueError si no está autorizado
        """
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            raise ValueError("Ticket no encontrado")

        # Solo admins pueden transferir
        user = User.query.get(transferred_by_id)
        user_roles = get_user_roles(user)  # Función existente
        if 'admin' not in user_roles:
            raise ValueError("Solo administradores pueden transferir tickets entre campus")

        # Validar que el campus destino existe
        if target_campus not in CampusService.CAMPUS_NAMES:
            raise ValueError(f"Campus '{target_campus}' no existe")

        old_campus = ticket.campus
        ticket.campus = target_campus

        # Desasignar técnico actual (probablemente de otro campus)
        if ticket.assigned_to_user_id:
            ticket.assigned_to_user_id = None
            ticket.assigned_to_team = None
            ticket.status = 'PENDING'

        # Registrar en StatusLog
        StatusLogService.log_event(
            ticket_id=ticket_id,
            event_type='TRANSFERRED_CAMPUS',
            notes=f"Transferido de {old_campus} a {target_campus}. Razón: {reason}",
            changed_by_id=transferred_by_id
        )

        db.session.commit()

        # Notificar a admins del campus destino
        _notify_campus_transfer(ticket, old_campus, target_campus)

        return ticket

    @staticmethod
    def get_all_campus_list():
        """
        Retorna lista de todos los campus activos en el sistema.

        Returns:
            [
                {'code': 'CAMPUS_I', 'name': 'Campus I'},
                {'code': 'CAMPUS_II', 'name': 'Campus II'},
            ]
        """
        campus_codes = Department.get_all_campus()
        return [
            {'code': code, 'name': CampusService.CAMPUS_NAMES.get(code, code)}
            for code in campus_codes
        ]
```

### 2. Modificar TicketService

**Archivo:** `apps/helpdesk/services/ticket_service.py`

```python
class TicketService:
    # ... métodos existentes ...

    @staticmethod
    def list_tickets(user_id, filters=None):
        """
        Lista tickets con filtrado automático por campus.

        MODIFICACIÓN: Agregar filtro de campus automático según el usuario.
        """
        filters = filters or {}
        user_roles = get_user_roles_for_user(user_id)
        user = User.query.get(user_id)

        query = Ticket.query

        # NUEVO: Filtrado automático por campus
        if 'admin' not in user_roles:  # Super admin ve todos
            user_campus = CampusService.get_user_campus(user_id)

            # Técnicos solo ven tickets de su campus
            if any(role.startswith('tech_') for role in user_roles):
                query = query.filter(Ticket.campus == user_campus)

            # Admin de campus específico solo ve su campus
            elif 'admin_campus_i' in user_roles:
                query = query.filter(Ticket.campus == CampusService.CAMPUS_I)
            elif 'admin_campus_ii' in user_roles:
                query = query.filter(Ticket.campus == CampusService.CAMPUS_II)

            # Usuarios normales solo ven sus propios tickets (ya filtrado antes)
            # pero asegurar que sean de su campus
            elif 'staff' in user_roles:
                query = query.filter(
                    Ticket.requester_id == user_id,
                    Ticket.campus == user_campus
                )

        # Filtro manual de campus (para super admin)
        if filters.get('campus'):
            query = query.filter(Ticket.campus == filters['campus'])

        # ... resto de filtros existentes ...

        return query.all()

    @staticmethod
    def create_ticket(**kwargs):
        """
        Crea un ticket con campus automático.

        MODIFICACIÓN: Determinar campus del requester automáticamente.
        """
        requester_id = kwargs.get('requester_id')

        # Determinar campus del usuario
        user_campus = CampusService.get_user_campus(requester_id)

        # Determinar campus del departamento (puede ser diferente si crea para otro)
        dept_id = kwargs.get('requester_department_id')
        if dept_id:
            dept_campus = CampusService.get_user_campus_from_department(dept_id)
            campus = dept_campus
        else:
            campus = user_campus

        kwargs['campus'] = campus

        # ... resto de la lógica existente ...

        ticket = Ticket(**kwargs)
        db.session.add(ticket)
        db.session.commit()

        # NUEVO: Notificar solo a admins/secretarias del mismo campus
        _notify_ticket_created_campus_specific(ticket, campus)

        return ticket
```

### 3. Modificar AssignmentService

**Archivo:** `apps/helpdesk/services/assignment_service.py`

```python
class AssignmentService:
    # ... métodos existentes ...

    @staticmethod
    def get_available_technicians(area, ticket_id=None):
        """
        Obtiene técnicos disponibles para asignar.

        MODIFICACIÓN: Filtrar solo técnicos del mismo campus del ticket.
        """
        if ticket_id:
            ticket = Ticket.query.get(ticket_id)
            campus = ticket.campus
        else:
            # Si no hay ticket, asumir Campus I (no debería pasar)
            campus = CampusService.CAMPUS_I

        # Obtener técnicos del campus específico
        technicians = CampusService.get_technicians_for_campus(campus, area)

        return technicians

    @staticmethod
    def assign_ticket(ticket_id, assigned_by_id, assigned_to_user_id=None, assigned_to_team=None, reason=None):
        """
        Asigna un ticket a un técnico o equipo.

        MODIFICACIÓN: Validar que el técnico sea del mismo campus.
        """
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            raise ValueError("Ticket no encontrado")

        # NUEVA VALIDACIÓN: Técnico debe ser del mismo campus
        if assigned_to_user_id:
            tech_campus = CampusService.get_user_campus(assigned_to_user_id)
            if tech_campus != ticket.campus:
                raise ValueError(
                    f"No se puede asignar técnico de {tech_campus} a ticket de {ticket.campus}. "
                    f"Si necesitas transferir, usa la función de transferencia de campus."
                )

        # ... resto de la lógica existente ...

        assignment = Assignment(
            ticket_id=ticket_id,
            assigned_by_id=assigned_by_id,
            assigned_to_user_id=assigned_to_user_id,
            assigned_to_team=assigned_to_team,
            reason=reason
        )

        db.session.add(assignment)
        db.session.commit()

        return assignment
```

---

## 🌐 RUTAS Y API

### API Endpoints - Campus

**Archivo:** `apps/helpdesk/routes/api/campus.py` (NUEVO)

```python
from flask import Blueprint, jsonify, request, session
from apps.helpdesk.services.campus_service import CampusService
from core.decorators import api_app_required

campus_bp = Blueprint('campus_api', __name__)

# GET /api/help-desk/v1/campus/list
@campus_bp.route('/list', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.campus.api.read'])
def get_campus_list():
    """Lista todos los campus activos"""
    campus_list = CampusService.get_all_campus_list()
    return jsonify(campus_list), 200

# GET /api/help-desk/v1/campus/:campus_code/statistics
@campus_bp.route('/<campus_code>/statistics', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.campus.api.read'])
def get_campus_statistics(campus_code):
    """Obtiene estadísticas de un campus"""
    user_id = session.get('user_id')
    user_roles = get_user_roles_for_user(user_id)

    # Validar acceso al campus
    if not CampusService.can_user_access_campus(user_id, campus_code, user_roles):
        return jsonify({'error': 'No autorizado para acceder a este campus'}), 403

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    stats = CampusService.get_campus_statistics(campus_code, start_date, end_date)
    return jsonify(stats), 200

# GET /api/help-desk/v1/campus/:campus_code/technicians
@campus_bp.route('/<campus_code>/technicians', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.assignments.api.read'])
def get_campus_technicians(campus_code):
    """Obtiene técnicos de un campus"""
    area = request.args.get('area')  # DESARROLLO, SOPORTE
    technicians = CampusService.get_technicians_for_campus(campus_code, area)
    return jsonify(technicians), 200

# POST /api/help-desk/v1/campus/transfer-ticket
@campus_bp.route('/transfer-ticket', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.manage'])
def transfer_ticket_campus():
    """
    Transfiere un ticket a otro campus (solo admin).

    Body:
    {
        "ticket_id": 123,
        "target_campus": "CAMPUS_II",
        "reason": "Usuario fue transferido al Campus II"
    }
    """
    admin_id = session.get('user_id')
    data = request.get_json()

    try:
        ticket = CampusService.transfer_ticket_to_campus(
            ticket_id=data['ticket_id'],
            target_campus=data['target_campus'],
            transferred_by_id=admin_id,
            reason=data['reason']
        )

        return jsonify({
            'success': True,
            'ticket': {
                'id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'campus': ticket.campus
            }
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

# GET /api/help-desk/v1/campus/my-campus
@campus_bp.route('/my-campus', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.campus.api.read'])
def get_my_campus():
    """Obtiene el campus del usuario actual"""
    user_id = session.get('user_id')
    campus = CampusService.get_user_campus(user_id)

    return jsonify({
        'campus': campus,
        'campus_name': CampusService.CAMPUS_NAMES.get(campus, 'Desconocido')
    }), 200
```

### Modificar Endpoints Existentes

**Tickets API - Agregar filtro de campus:**

```python
# En apps/helpdesk/routes/api/tickets/base.py

# GET /api/help-desk/v1/tickets
@tickets_bp.route('/', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def list_tickets():
    """
    Lista tickets con filtrado automático por campus.

    Query params:
        - campus: (opcional) Filtrar por campus específico (solo super admin)
        - status: ...
        - ... (otros filtros existentes)
    """
    user_id = session.get('user_id')
    filters = {
        'campus': request.args.get('campus'),
        'status': request.args.getlist('status'),
        # ... otros filtros ...
    }

    tickets = TicketService.list_tickets(user_id, filters)
    # Ya incluye filtrado automático por campus

    return jsonify([serialize_ticket(t) for t in tickets]), 200
```

---

## 🎨 TEMPLATES Y UI

### 1. campus_badge.html (Componente reutilizable)

**Archivo:** `templates/helpdesk/shared/campus_badge.html`

```html
<!-- Badge de campus para mostrar en tickets, inventario, etc. -->
<span class="badge bg-{{ campus_badge_class }} campus-badge">
    <i class="fas fa-building"></i>
    {{ campus_display_name }}
</span>

<style>
.campus-badge {
    font-size: 0.85em;
    padding: 0.35em 0.65em;
    border-radius: 0.25rem;
}
</style>
```

### 2. Modificar ticket_detail.html

Mostrar campus del ticket:

```html
<!-- En la sección de información del ticket -->
<div class="card mb-3">
    <div class="card-header">
        <i class="fas fa-ticket-alt"></i> Información del Ticket
    </div>
    <div class="card-body">
        <div class="row">
            <div class="col-md-6">
                <p><strong>Número:</strong> {{ ticket.ticket_number }}</p>
                <p><strong>Estado:</strong> <span class="badge bg-{{ ticket.status_badge }}">{{ ticket.status }}</span></p>

                <!-- NUEVO: Campus -->
                <p>
                    <strong>Campus:</strong>
                    {% include 'helpdesk/shared/campus_badge.html' with campus_badge_class=ticket.campus_badge_class, campus_display_name=ticket.campus_display_name %}
                </p>
            </div>
            <!-- ... resto de la información ... -->
        </div>
    </div>
</div>
```

### 3. Modificar technician/home.html

Dashboard de técnico con indicador de campus:

```html
<!-- Banner de campus del técnico -->
<div class="alert alert-info mb-4">
    <div class="d-flex align-items-center">
        <i class="fas fa-building fa-2x me-3"></i>
        <div>
            <h5 class="mb-0">{{ user_campus_name }}</h5>
            <small>Estás viendo tickets de tu campus. No verás tickets de otros campus.</small>
        </div>
    </div>
</div>

<!-- Dashboard existente -->
<div class="row">
    <!-- Cards de estadísticas con datos del campus -->
</div>
```

### 4. admin/campus_selector.html (NUEVO)

Selector de campus para super admin:

```html
<!-- Selector de campus para admin -->
<div class="card mb-4">
    <div class="card-body">
        <div class="row align-items-center">
            <div class="col-md-8">
                <h5 class="mb-0">
                    <i class="fas fa-building"></i>
                    Seleccionar Campus
                </h5>
                <small class="text-muted">Filtra los datos por campus específico o ve todos</small>
            </div>
            <div class="col-md-4">
                <select id="campus-selector" class="form-select" onchange="changeCampus()">
                    <option value="">Todos los Campus</option>
                    {% for campus in campus_list %}
                    <option value="{{ campus.code }}" {% if selected_campus == campus.code %}selected{% endif %}>
                        {{ campus.name }}
                    </option>
                    {% endfor %}
                </select>
            </div>
        </div>
    </div>
</div>

<script>
function changeCampus() {
    const selector = document.getElementById('campus-selector');
    const campus = selector.value;

    // Agregar parámetro a URL
    const url = new URL(window.location);
    if (campus) {
        url.searchParams.set('campus', campus);
    } else {
        url.searchParams.delete('campus');
    }
    window.location.href = url.toString();
}
</script>
```

### 5. Modificar my_tickets.html

Mostrar campus en lista de tickets:

```html
<!-- Tabla de tickets -->
<table class="table">
    <thead>
        <tr>
            <th>Número</th>
            <th>Campus</th> <!-- NUEVA COLUMNA -->
            <th>Título</th>
            <th>Estado</th>
            <th>Fecha</th>
            <th>Acciones</th>
        </tr>
    </thead>
    <tbody>
        {% for ticket in tickets %}
        <tr>
            <td>{{ ticket.ticket_number }}</td>
            <td>
                <!-- NUEVO -->
                {% include 'helpdesk/shared/campus_badge.html' with campus_badge_class=ticket.campus_badge_class, campus_display_name=ticket.campus_display_name %}
            </td>
            <td>{{ ticket.title }}</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

---

## 🔐 CONTROL DE ACCESO Y PERMISOS

### Matriz de permisos por rol y campus:

| Rol | Campus | Acceso a Tickets | Asignación | Inventario | Admin |
|-----|--------|------------------|------------|------------|-------|
| **admin** | Todos | ✅ Todos | ✅ Todos | ✅ Todos | ✅ Global |
| **admin_campus_i** | Campus I | ✅ Campus I | ✅ Campus I | ✅ Campus I | ✅ Campus I |
| **admin_campus_ii** | Campus II | ✅ Campus II | ✅ Campus II | ✅ Campus II | ✅ Campus II |
| **tech_desarrollo** | Campus I | ✅ Campus I | ❌ No | 👁️ Ver | ❌ No |
| **tech_soporte** | Campus I | ✅ Campus I | ❌ No | 👁️ Ver | ❌ No |
| **tech_desarrollo_c2** | Campus II | ✅ Campus II | ❌ No | 👁️ Ver | ❌ No |
| **tech_soporte_c2** | Campus II | ✅ Campus II | ❌ No | 👁️ Ver | ❌ No |
| **staff** | Su campus | ✅ Propios | ❌ No | 👁️ Propios | ❌ No |
| **secretary** | Su campus | ✅ Su dpto | ❌ No | 👁️ Su dpto | ❌ No |

### Decorador de filtrado por campus:

**Archivo:** `apps/helpdesk/utils/campus_filter.py` (NUEVO)

```python
from functools import wraps
from flask import session, abort
from apps.helpdesk.services.campus_service import CampusService

def campus_access_required(campus_param='campus'):
    """
    Decorador que verifica acceso a un campus específico.

    Args:
        campus_param: Nombre del parámetro de ruta que contiene el código del campus

    Usage:
        @campus_access_required('campus_code')
        def view_campus_tickets(campus_code):
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            campus = kwargs.get(campus_param)
            user_roles = get_user_roles_for_user(user_id)

            if not CampusService.can_user_access_campus(user_id, campus, user_roles):
                abort(403)  # Forbidden

            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Uso:
@app.route('/help-desk/campus/<campus_code>/dashboard')
@campus_access_required('campus_code')
def campus_dashboard(campus_code):
    # Usuario ya validado que puede acceder a este campus
    stats = CampusService.get_campus_statistics(campus_code)
    return render_template('campus_dashboard.html', stats=stats)
```

---

## 📊 REPORTES Y DASHBOARDS

### 1. Dashboard Comparativo de Campus (Super Admin)

**Ubicación:** `/help-desk/admin/campus/comparison`

**Métricas lado a lado:**

| Métrica | Campus I | Campus II | Diferencia |
|---------|----------|-----------|------------|
| Tickets Totales | 1,245 | 387 | +858 (69%) |
| Tickets Pendientes | 45 | 12 | +33 |
| Tiempo Promedio Resolución | 2.3 horas | 1.8 horas | -0.5h ⬇️ |
| Técnicos Activos | 8 | 3 | +5 |
| Tasa de Éxito | 94% | 97% | +3% ⬆️ |
| Equipos Registrados | 450 | 120 | +330 |

**Gráficas:**
- Timeline de tickets por campus
- Distribución de categorías por campus
- Comparación de SLA compliance

### 2. Dashboard Individual de Campus

**Ubicación:** `/help-desk/campus/<campus_code>/dashboard`

**Similar al dashboard de técnico pero con:**
- Estadísticas solo del campus
- Lista de técnicos del campus
- Tickets activos del campus
- Inventario del campus

---

## 🔄 FLUJOS DE USUARIO

### Escenario 1: Usuario de Campus II crea ticket

1. **Usuario de Campus II** (María González, Ing. Industrial - Campus II)
2. Entra a helpdesk, clic en "Pedir Ayuda"
3. Selecciona categoría "Problema con Internet"
4. Llena formulario y crea ticket
5. **Sistema automáticamente:**
   - Detecta que María pertenece al departamento "Industrial - Campus II"
   - `campus = 'CAMPUS_II'`
   - Ticket número: `TK-2026-0050`
6. **Notificación enviada a:**
   - Secretaria Centro de Cómputo - Campus II ✅
   - Admin Campus II ✅
   - ❌ NO se notifica a técnicos de Campus I
7. Ticket aparece en dashboard de Campus II
8. **Técnico de Campus II** lo ve y se auto-asigna
9. Resuelve el problema

### Escenario 2: Técnico de Campus I no ve tickets de Campus II

1. **Técnico de Campus I** (Juan Pérez, rol: `tech_soporte`)
2. Entra a dashboard de técnico
3. **Banner muestra:** "Campus I - Viendo tickets de tu campus"
4. Lista de tickets:
   - ✅ TK-2026-0048 [Campus I] - Problema impresora
   - ✅ TK-2026-0049 [Campus I] - Internet lento
   - ❌ TK-2026-0050 [Campus II] - NO VISIBLE
5. Filtros de búsqueda **NO incluyen** opción de seleccionar campus
   (Automáticamente filtrado a Campus I)

### Escenario 3: Super Admin ve todos los campus

1. **Super Admin** entra a dashboard
2. **Selector de campus** visible:
   ```
   [ Todos los Campus ▼ ]
   ```
3. Ve tickets de AMBOS campus en la lista
4. Cada ticket tiene badge de campus:
   - TK-2026-0048 🔵 Campus I
   - TK-2026-0049 🔵 Campus I
   - TK-2026-0050 🟢 Campus II
5. Puede filtrar por campus específico
6. Puede acceder a dashboard comparativo

### Escenario 4: Transferencia excepcional entre campus

1. **Usuario reporta** ticket en Campus I
2. Ticket `TK-2026-0051` creado en Campus I
3. Durante investigación, descubren que el usuario fue transferido al Campus II
4. **Super Admin** decide transferir el ticket:
   - Entra al ticket
   - Clic en "Transferir a otro Campus"
   - Selecciona "Campus II"
   - Escribe razón: "Usuario transferido al Campus II"
   - Confirma
5. **Sistema:**
   - Cambia `campus = 'CAMPUS_II'`
   - Desasigna técnico de Campus I
   - Status → PENDING
   - Registra en StatusLog
   - Notifica a admins de Campus II
6. Ticket ahora aparece en Campus II

### Escenario 5: Admin de Campus II no puede acceder a Campus I

1. **Admin Campus II** (Pedro Martínez, rol: `admin_campus_ii`)
2. Intenta acceder a `/help-desk/campus/CAMPUS_I/dashboard`
3. **Sistema verifica:**
   - `can_user_access_campus(user_id, 'CAMPUS_I', ['admin_campus_ii'])`
   - Retorna `False`
4. **Respuesta:** `403 Forbidden`
5. Mensaje: "No tienes permiso para acceder a Campus I"

---

## 🧪 CASOS DE PRUEBA

### Casos de Filtrado:

1. ✅ Usuario de Campus I solo ve sus tickets de Campus I
2. ✅ Técnico de Campus II solo ve tickets de Campus II
3. ✅ Admin de Campus I no ve tickets de Campus II
4. ✅ Super admin ve todos los tickets
5. ✅ Búsqueda de tickets respeta filtro de campus
6. ✅ Notificaciones solo a personal del campus correspondiente

### Casos de Asignación:

1. ✅ Ticket de Campus I solo se puede asignar a técnico de Campus I
2. ❌ Intentar asignar técnico de Campus II a ticket de Campus I → Error
3. ✅ Lista de técnicos disponibles solo muestra del campus correcto
4. ✅ Auto-asignación solo funciona si técnico es del mismo campus

### Casos de Inventario:

1. ✅ Equipos de Campus I tienen prefijo `C1-`
2. ✅ Equipos de Campus II tienen prefijo `C2-`
3. ✅ Numeración es independiente por campus (C1-COMP-2026-001, C2-COMP-2026-001)
4. ✅ Dashboard de inventario filtra por campus

### Casos de Transferencia:

1. ✅ Solo super admin puede transferir entre campus
2. ✅ Transferencia desasigna técnico automáticamente
3. ✅ Se registra en auditoría
4. ❌ Técnico no puede transferir → Error 403

---

## 📅 PLAN DE IMPLEMENTACIÓN POR FASES

### Fase 1: Migraciones de Base de Datos (2 días)
- [ ] Agregar campo `campus` a `Department`
- [ ] Agregar campo `campus` a `Ticket`
- [ ] Agregar campo `campus` a `InventoryItem`
- [ ] Crear índices
- [ ] Migrar datos existentes (todo → Campus I)
- [ ] Crear departamento raíz Campus II
- [ ] Crear Centro de Cómputo Campus II

### Fase 2: Modelos y Servicios (3 días)
- [ ] Crear `CampusService`
- [ ] Modificar `TicketService` con filtrado
- [ ] Modificar `AssignmentService` con validación
- [ ] Modificar `InventoryService`
- [ ] Tests unitarios

### Fase 3: Roles y Permisos (2 días)
- [ ] Crear roles Campus II (`tech_desarrollo_c2`, `tech_soporte_c2`, `admin_campus_ii`)
- [ ] Configurar permisos por campus
- [ ] Decorador `campus_access_required`
- [ ] Migración de roles a usuarios de prueba

### Fase 4: API REST (2 días)
- [ ] Endpoints de campus (list, statistics, technicians)
- [ ] Modificar endpoints existentes con filtrado
- [ ] Endpoint de transferencia
- [ ] Validaciones y tests

### Fase 5: Templates - Componentes Básicos (2 días)
- [ ] Badge de campus (componente reutilizable)
- [ ] Modificar ticket_detail.html
- [ ] Modificar my_tickets.html
- [ ] Banner de campus en dashboards

### Fase 6: Templates - Dashboards por Campus (3 días)
- [ ] Dashboard de técnico con filtro
- [ ] Dashboard de admin con selector de campus
- [ ] Dashboard comparativo de campus
- [ ] Estadísticas por campus

### Fase 7: Inventario por Campus (2 días)
- [ ] Modificar vistas de inventario
- [ ] Generación de números con prefijo de campus
- [ ] Filtrado en asignación de equipos
- [ ] Reportes de inventario por campus

### Fase 8: Funcionalidad de Transferencia (1 día)
- [ ] UI de transferencia de ticket
- [ ] Modal de confirmación
- [ ] Validaciones
- [ ] Notificaciones

### Fase 9: Testing Integral (3 días)
- [ ] Testing E2E de flujos por campus
- [ ] Testing de permisos
- [ ] Testing de transferencias
- [ ] Pruebas de performance con filtros
- [ ] Corrección de bugs

### Fase 10: Migración de Datos Reales (1 día)
- [ ] Identificar departamentos del Campus II real
- [ ] Migrar usuarios al Campus II
- [ ] Migrar inventario existente
- [ ] Verificar datos migrados

### Fase 11: Capacitación y Documentación (2 días)
- [ ] Manual de usuario por campus
- [ ] Capacitación a técnicos de Campus II
- [ ] Documentación de API
- [ ] Guía de troubleshooting

**Total estimado:** 23-28 días de desarrollo

---

## ⚠️ RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Migración de datos incorrecta | Media | Crítico | Backup completo, migración en staging primero, validación manual |
| Tickets asignados a campus incorrecto | Media | Alto | Validación en múltiples niveles, alertas automáticas |
| Usuarios no entienden separación | Alta | Medio | Banners claros, capacitación, documentación |
| Performance degradado por filtros | Baja | Medio | Índices en BD, caching, optimización de queries |
| Confusión en transferencias | Media | Medio | Proceso claro, solo admins, confirmación obligatoria |
| Roles mal asignados | Media | Alto | Revisión manual, script de validación |

---

## 🎯 CRITERIOS DE ÉXITO

- ✅ 0 tickets cruzados entre campus en producción
- ✅ 100% de usuarios correctamente asignados a su campus
- ✅ 100% de inventario correctamente segregado
- ✅ Técnicos de Campus II operan independientemente sin interferencia de Campus I
- ✅ Reportes por campus funcionan correctamente
- ✅ Performance de queries no se degrada > 10%
- ✅ 0 errores de permisos en producción
- ✅ Satisfacción de usuarios de Campus II > 8/10

---

## 💡 EXTENSIONES FUTURAS

### 1. Campus III, IV, V...
- Arquitectura ya preparada para N campus
- Solo agregar en `CampusService.CAMPUS_NAMES`
- Crear departamentos y roles

### 2. Compartir Recursos entre Campus
- Categorías compartidas vs específicas de campus
- Pool de técnicos "flotantes" que atienden ambos campus
- Inventario compartido (equipos móviles)

### 3. Replicación de Configuración
- Copiar categorías de Campus I a Campus II
- Copiar checklists de primeros auxilios
- Plantillas de configuración

### 4. Analytics Multi-Campus
- Benchmarking entre campus
- Identificar mejores prácticas
- KPIs comparativos en tiempo real

### 5. Campus Virtual
- Campus "VIRTUAL" para usuarios remotos
- Campus "EXTERNO" para proveedores/externos

---

## 📝 CHECKLIST DE MIGRACIÓN A PRODUCCIÓN

### Pre-Deploy:
- [ ] Backup completo de base de datos
- [ ] Validar migración en staging
- [ ] Identificar todos los departamentos de Campus II
- [ ] Listar usuarios que deben ser Campus II
- [ ] Listar inventario que debe ser Campus II
- [ ] Crear roles de Campus II
- [ ] Asignar roles a usuarios de Campus II

### Deploy:
- [ ] Modo mantenimiento
- [ ] Ejecutar migraciones de BD
- [ ] Ejecutar scripts de migración de datos
- [ ] Validar integridad de datos
- [ ] Deploy de código
- [ ] Restart de servicios
- [ ] Smoke tests

### Post-Deploy:
- [ ] Validar que técnicos de Campus I solo ven Campus I
- [ ] Validar que técnicos de Campus II solo ven Campus II
- [ ] Crear ticket de prueba en cada campus
- [ ] Verificar notificaciones
- [ ] Revisar dashboard de cada campus
- [ ] Monitorear logs por 24 horas
- [ ] Capacitación a equipo de Campus II

---

## 🔍 MONITOREO Y MÉTRICAS

### Métricas a monitorear post-implementación:

1. **Separación correcta:**
   - Query diario: Tickets con técnico de campus diferente → debe ser 0
   - Alertar si se encuentra alguno

2. **Performance:**
   - Tiempo de respuesta de queries con filtro de campus
   - Debe ser < 200ms

3. **Uso:**
   - % de tickets por campus
   - Distribución esperada: 70% Campus I, 30% Campus II

4. **Errores:**
   - Intentos bloqueados de acceso cross-campus
   - Debe ser < 5 por semana (después de capacitación)

### Dashboard de monitoreo:

```
┌─────────────────────────────────────────┐
│  MONITOREO MULTI-CAMPUS                 │
├─────────────────────────────────────────┤
│  ✅ Separación correcta: 100%           │
│  ✅ Tickets cross-campus: 0             │
│  ✅ Performance queries: 145ms avg      │
│  ⚠️  Accesos bloqueados: 3 hoy          │
│                                         │
│  Campus I:  245 tickets  (68%)          │
│  Campus II: 115 tickets  (32%)          │
└─────────────────────────────────────────┘
```

---

**Fin del documento de planificación #4**

---

## 📚 RESUMEN DE LOS 4 PLANES

Con la implementación de estos 4 planes, el sistema de helpdesk tendrá:

1. ✅ **Verificación de Equipos:** Control estricto del inventario con validación obligatoria
2. ✅ **Duplicación de Tickets:** Eficiencia en problemas recurrentes
3. ✅ **Calificación + Primeros Auxilios:** Reducción de tickets triviales y scoring de usuarios
4. ✅ **Separación de Campus:** Operación independiente de Campus I y Campus II

**Tiempo total estimado:** 70-86 días de desarrollo (14-17 semanas)

**Recomendación de orden de implementación:**
1. **Campus (Plan 4):** Base estructural, afecta todo lo demás
2. **Duplicación (Plan 2):** Más simple, valor inmediato
3. **Primeros Auxilios (Plan 3):** Mayor complejidad, gran impacto
4. **Verificación de Equipos (Plan 1):** Complementa el sistema completo

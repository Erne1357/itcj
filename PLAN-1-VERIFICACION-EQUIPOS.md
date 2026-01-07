# PLAN DE IMPLEMENTACIÓN #1: VERIFICACIÓN OBLIGATORIA DE EQUIPOS DE INVENTARIO

**Proyecto:** Sistema Helpdesk - ITCJ
**Fecha:** 2026-01-06
**Autor:** Análisis de sistema actual + propuesta técnica
**Prioridad:** Alta
**Complejidad:** Media-Alta

---

## 📋 RESUMEN EJECUTIVO

Implementar un sistema obligatorio de verificación de equipos donde los usuarios deben confirmar periódicamente que los equipos asignados a ellos son correctos. El sistema debe ser "molesto" intencionalmente para forzar la atención del usuario y garantizar que el inventario institucional esté actualizado.

**Problema actual:**
- Inventario con muchas discrepancias (equipos mal asignados, usuarios sin equipos que figuran tenerlos)
- Falta de control sobre equipos en todo el plantel
- No hay proceso formal para que usuarios reporten errores de inventario

**Solución propuesta:**
- Nueva sección "Mi Equipo" en el portal del usuario
- Solicitudes de corrección de inventario (separadas de tickets normales)
- Recordatorios periódicos obligatorios de verificación
- Sistema de aprobación para cambios (jefe de departamento/admin)
- Posibilidad de bloquear creación de tickets si no ha verificado su equipo

---

## 🎯 OBJETIVOS

### Objetivos principales:
1. **Tener un inventario confiable y actualizado** al 100%
2. **Transferir responsabilidad** a los usuarios de mantener su inventario correcto
3. **Detectar pérdidas, robos o daños** más rápidamente
4. **Reducir fricción** para reportar discrepancias sin crear tickets formales

### Objetivos secundarios:
- Crear historial de verificaciones por usuario (auditoría)
- Métricas de cumplimiento de verificación por departamento
- Alertas automáticas para equipos no verificados en X meses

---

## 🏗️ ARQUITECTURA DE LA SOLUCIÓN

### Componentes nuevos a crear:

```
apps/helpdesk/
├── models/
│   ├── equipment_verification.py          [NUEVO] Registro de verificaciones
│   ├── equipment_correction_request.py    [NUEVO] Solicitudes de corrección
│   └── verification_reminder.py           [NUEVO] Recordatorios periódicos
│
├── services/
│   ├── equipment_verification_service.py  [NUEVO] Lógica de verificación
│   ├── correction_request_service.py      [NUEVO] Lógica de solicitudes
│   └── verification_reminder_service.py   [NUEVO] Envío de recordatorios
│
├── routes/
│   ├── api/
│   │   └── equipment_verification.py      [NUEVO] API REST
│   └── pages/
│       └── user_equipment.py              [NUEVO] Páginas HTML
│
├── templates/helpdesk/user/
│   ├── my_equipment.html                  [NUEVO] Listado de equipos
│   ├── verify_equipment.html              [NUEVO] Modal de verificación
│   └── correction_request.html            [NUEVO] Formulario de corrección
│
└── static/
    ├── js/
    │   └── equipment_verification.js      [NUEVO]
    └── css/
        └── equipment_verification.css     [NUEVO]
```

---

## 💾 MODELOS DE BASE DE DATOS

### 1. EquipmentVerification (Registro de verificaciones)

**Tabla:** `helpdesk_equipment_verifications`

```python
class EquipmentVerification(db.Model):
    """
    Registro de cada vez que un usuario verifica sus equipos.
    Permite auditoría completa de quién verificó qué y cuándo.
    """
    __tablename__ = 'helpdesk_equipment_verifications'

    # Identificación
    id = db.Column(db.BigInteger, primary_key=True)

    # Usuario que verifica
    user_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)

    # Equipo verificado
    equipment_id = db.Column(db.BigInteger, db.ForeignKey('helpdesk_inventory_items.id'), nullable=False)

    # Resultado de la verificación
    status = db.Column(db.String(20), nullable=False)
    # Valores:
    #   - CONFIRMED: "Sí, este equipo es mío y lo tengo"
    #   - NOT_MINE: "Este equipo NO es mío / nunca lo tuve"
    #   - NO_LONGER_HAVE: "Era mío pero ya no lo tengo"
    #   - WRONG_DETAILS: "Es mío pero la info (marca/modelo/serial) es incorrecta"

    # Detalles adicionales
    notes = db.Column(db.Text, nullable=True)  # Comentarios del usuario

    # Ubicación reportada (si CONFIRMED)
    current_location = db.Column(db.String(255), nullable=True)

    # Timestamps
    verified_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Si marcó problema, se crea una correction request
    correction_request_id = db.Column(db.BigInteger,
                                      db.ForeignKey('helpdesk_equipment_correction_requests.id'),
                                      nullable=True)

    # Relaciones
    user = db.relationship('User', backref='equipment_verifications')
    equipment = db.relationship('InventoryItem', backref='verifications')
    correction_request = db.relationship('EquipmentCorrectionRequest',
                                         backref='verification')

    # Índices
    __table_args__ = (
        db.Index('idx_equipment_verifications_user', 'user_id'),
        db.Index('idx_equipment_verifications_equipment', 'equipment_id'),
        db.Index('idx_equipment_verifications_status', 'status'),
        db.Index('idx_equipment_verifications_date', 'verified_at'),
    )

    # Métodos útiles
    @property
    def is_problematic(self):
        """Indica si la verificación reveló un problema"""
        return self.status in ['NOT_MINE', 'NO_LONGER_HAVE', 'WRONG_DETAILS']

    @property
    def needs_action(self):
        """Indica si requiere acción administrativa"""
        return self.is_problematic and self.correction_request_id is None
```

### 2. EquipmentCorrectionRequest (Solicitudes de corrección)

**Tabla:** `helpdesk_equipment_correction_requests`

```python
class EquipmentCorrectionRequest(db.Model):
    """
    Solicitud de corrección de inventario creada por un usuario.
    Requiere aprobación de jefe de departamento o administrador.
    """
    __tablename__ = 'helpdesk_equipment_correction_requests'

    # Identificación
    id = db.Column(db.BigInteger, primary_key=True)
    request_number = db.Column(db.String(20), unique=True, nullable=False)
    # Formato: CR-2026-0001 (Correction Request)

    # Solicitante
    requester_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)
    requester_department_id = db.Column(db.Integer, db.ForeignKey('core_departments.id'), nullable=True)

    # Equipo en cuestión
    equipment_id = db.Column(db.BigInteger, db.ForeignKey('helpdesk_inventory_items.id'), nullable=False)

    # Tipo de corrección solicitada
    correction_type = db.Column(db.String(30), nullable=False)
    # Valores:
    #   - REMOVE_ASSIGNMENT: "Este equipo no es mío, eliminar asignación"
    #   - CHANGE_ASSIGNMENT: "Asignar a otro usuario"
    #   - REPORT_LOST: "Reportar como extraviado"
    #   - REPORT_DAMAGED: "Reportar como dañado"
    #   - UPDATE_INFO: "Actualizar información (marca/modelo/serial)"
    #   - CHANGE_LOCATION: "Cambiar ubicación"

    # Descripción del problema
    description = db.Column(db.Text, nullable=False)  # Min 20 caracteres

    # Si pide cambio de asignación, a quién
    requested_new_assignee_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)

    # Si pide actualización de info, nuevos datos propuestos
    proposed_changes = db.Column(db.JSON, nullable=True)
    # Ejemplo: {"brand": "HP", "model": "EliteBook 840 G8", "serial_number": "ABC123"}

    # Estado de la solicitud
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    # Valores: PENDING, APPROVED, REJECTED, CANCELLED

    # Revisión
    reviewed_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    # Ejecución
    executed_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    executed_at = db.Column(db.DateTime, nullable=True)

    # Prioridad (automática según tipo)
    priority = db.Column(db.String(10), default='MEDIA', nullable=False)
    # URGENTE: REPORT_LOST, REPORT_DAMAGED
    # ALTA: REMOVE_ASSIGNMENT
    # MEDIA: resto

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    requester = db.relationship('User', foreign_keys=[requester_id], backref='correction_requests')
    requester_department = db.relationship('Department', backref='correction_requests')
    equipment = db.relationship('InventoryItem', backref='correction_requests')
    requested_new_assignee = db.relationship('User', foreign_keys=[requested_new_assignee_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])
    executed_by = db.relationship('User', foreign_keys=[executed_by_id])

    # Índices
    __table_args__ = (
        db.Index('idx_correction_requests_requester', 'requester_id'),
        db.Index('idx_correction_requests_equipment', 'equipment_id'),
        db.Index('idx_correction_requests_status', 'status'),
        db.Index('idx_correction_requests_priority', 'priority'),
        db.Index('idx_correction_requests_department', 'requester_department_id'),
    )

    # Métodos
    @property
    def is_pending(self):
        return self.status == 'PENDING'

    @property
    def is_resolved(self):
        return self.status in ['APPROVED', 'REJECTED', 'CANCELLED']

    def can_approve(self, user_id, user_roles):
        """Verifica si un usuario puede aprobar esta solicitud"""
        # Admins pueden todo
        if 'admin' in user_roles:
            return True

        # Jefe del departamento puede aprobar
        if 'department_head' in user_roles:
            user_position = UserPosition.query.filter_by(
                user_id=user_id,
                is_active=True
            ).first()
            if user_position and user_position.position.department_id == self.requester_department_id:
                return True

        return False
```

### 3. VerificationReminder (Recordatorios periódicos)

**Tabla:** `helpdesk_verification_reminders`

```python
class VerificationReminder(db.Model):
    """
    Recordatorios enviados a usuarios para verificar sus equipos.
    Permite trackear quién ha sido notificado y cuándo.
    """
    __tablename__ = 'helpdesk_verification_reminders'

    id = db.Column(db.BigInteger, primary_key=True)

    # Usuario notificado
    user_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)

    # Tipo de recordatorio
    reminder_type = db.Column(db.String(20), nullable=False)
    # Valores:
    #   - PERIODIC: Recordatorio periódico mensual
    #   - OVERDUE: Usuario nunca ha verificado
    #   - BLOCKING: Usuario bloqueado de crear tickets

    # Estado
    status = db.Column(db.String(20), default='SENT', nullable=False)
    # Valores: SENT, VIEWED, DISMISSED, COMPLETED

    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    viewed_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)  # Cuando verificó

    # Relaciones
    user = db.relationship('User', backref='verification_reminders')

    # Índices
    __table_args__ = (
        db.Index('idx_verification_reminders_user', 'user_id'),
        db.Index('idx_verification_reminders_status', 'status'),
        db.Index('idx_verification_reminders_type', 'reminder_type'),
    )
```

### 4. Modificaciones a InventoryItem (modelo existente)

Agregar campos para tracking de verificación:

```python
class InventoryItem(db.Model):
    # ... campos existentes ...

    # NUEVOS CAMPOS
    last_verified_at = db.Column(db.DateTime, nullable=True)
    last_verified_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    verification_status = db.Column(db.String(20), default='NEVER_VERIFIED', nullable=False)
    # Valores: NEVER_VERIFIED, VERIFIED_OK, NEEDS_REVIEW, DISPUTED

    requires_verification = db.Column(db.Boolean, default=True, nullable=False)
    # False para equipos globales o de grupos (solo individuales requieren verificación)

    # Relaciones nuevas
    last_verified_by = db.relationship('User', foreign_keys=[last_verified_by_id])

    # NUEVOS MÉTODOS
    @property
    def days_since_last_verification(self):
        """Días desde última verificación"""
        if not self.last_verified_at:
            # Si nunca se verificó, contar desde la asignación
            if self.assigned_at:
                return (datetime.utcnow() - self.assigned_at).days
            return None
        return (datetime.utcnow() - self.last_verified_at).days

    @property
    def verification_overdue(self):
        """Indica si la verificación está vencida (más de 90 días)"""
        days = self.days_since_last_verification
        return days is not None and days > 90

    @property
    def can_be_verified(self):
        """Indica si puede ser verificado (solo equipos asignados a usuarios)"""
        return (self.requires_verification and
                self.is_assigned_to_user and
                self.status == 'ACTIVE')
```

---

## 🔧 SERVICIOS (Lógica de negocio)

### 1. EquipmentVerificationService

**Archivo:** `apps/helpdesk/services/equipment_verification_service.py`

```python
class EquipmentVerificationService:
    """Servicio para gestionar verificaciones de equipos"""

    @staticmethod
    def get_user_equipment_to_verify(user_id):
        """
        Obtiene todos los equipos asignados a un usuario que requieren verificación.

        Returns:
            {
                'total': int,
                'verified': int,
                'pending': int,
                'overdue': int,
                'equipment': [
                    {
                        'id': int,
                        'inventory_number': str,
                        'category': str,
                        'brand': str,
                        'model': str,
                        'location_detail': str,
                        'assigned_at': datetime,
                        'last_verified_at': datetime,
                        'days_since_verification': int,
                        'is_overdue': bool,
                        'verification_status': str
                    },
                    ...
                ]
            }
        """
        equipment_list = InventoryItem.query.filter_by(
            assigned_to_user_id=user_id,
            is_active=True,
            requires_verification=True
        ).filter(
            InventoryItem.status.in_(['ACTIVE', 'MAINTENANCE'])
        ).all()

        total = len(equipment_list)
        verified = sum(1 for e in equipment_list if e.verification_status == 'VERIFIED_OK')
        overdue = sum(1 for e in equipment_list if e.verification_overdue)
        pending = total - verified

        return {
            'total': total,
            'verified': verified,
            'pending': pending,
            'overdue': overdue,
            'equipment': [
                {
                    'id': eq.id,
                    'inventory_number': eq.inventory_number,
                    'category': eq.category.name,
                    'brand': eq.brand,
                    'model': eq.model,
                    'serial_number': eq.serial_number,
                    'location_detail': eq.location_detail,
                    'assigned_at': eq.assigned_at,
                    'last_verified_at': eq.last_verified_at,
                    'days_since_verification': eq.days_since_last_verification,
                    'is_overdue': eq.verification_overdue,
                    'verification_status': eq.verification_status
                }
                for eq in equipment_list
            ]
        }

    @staticmethod
    def verify_equipment(user_id, equipment_id, status, notes=None, current_location=None):
        """
        Registra la verificación de un equipo por parte del usuario.

        Args:
            user_id: ID del usuario que verifica
            equipment_id: ID del equipo
            status: CONFIRMED | NOT_MINE | NO_LONGER_HAVE | WRONG_DETAILS
            notes: Notas del usuario
            current_location: Ubicación actual si CONFIRMED

        Returns:
            {
                'verification': EquipmentVerification,
                'correction_request': EquipmentCorrectionRequest | None
            }

        Raises:
            ValueError si el equipo no está asignado al usuario
        """
        # Validar que el equipo esté asignado al usuario
        equipment = InventoryItem.query.get(equipment_id)
        if not equipment:
            raise ValueError("Equipo no encontrado")

        if equipment.assigned_to_user_id != user_id:
            raise ValueError("Este equipo no está asignado a ti")

        # Crear registro de verificación
        verification = EquipmentVerification(
            user_id=user_id,
            equipment_id=equipment_id,
            status=status,
            notes=notes,
            current_location=current_location
        )
        db.session.add(verification)

        # Actualizar equipo
        equipment.last_verified_at = datetime.utcnow()
        equipment.last_verified_by_id = user_id

        correction_request = None

        if status == 'CONFIRMED':
            # Todo OK
            equipment.verification_status = 'VERIFIED_OK'
            if current_location and current_location != equipment.location_detail:
                equipment.location_detail = current_location
                # Registrar en history
                InventoryHistoryService.log_event(
                    equipment_id=equipment_id,
                    event_type='LOCATION_CHANGED',
                    old_value={'location_detail': equipment.location_detail},
                    new_value={'location_detail': current_location},
                    performed_by_id=user_id,
                    notes=f"Actualizado durante verificación: {notes}"
                )

        else:
            # Hay un problema, crear correction request
            equipment.verification_status = 'DISPUTED'

            # Mapear status a correction_type
            correction_type_map = {
                'NOT_MINE': 'REMOVE_ASSIGNMENT',
                'NO_LONGER_HAVE': 'REPORT_LOST',
                'WRONG_DETAILS': 'UPDATE_INFO'
            }

            correction_request = CorrectionRequestService.create_request(
                requester_id=user_id,
                equipment_id=equipment_id,
                correction_type=correction_type_map[status],
                description=notes or f"Verificación marcada como: {status}",
                auto_created=True
            )

            verification.correction_request_id = correction_request.id

        db.session.commit()

        # Registrar en history
        InventoryHistoryService.log_event(
            equipment_id=equipment_id,
            event_type='VERIFICATION_COMPLETED',
            new_value={
                'status': status,
                'notes': notes,
                'verification_id': verification.id
            },
            performed_by_id=user_id
        )

        return {
            'verification': verification,
            'correction_request': correction_request
        }

    @staticmethod
    def verify_all_ok(user_id):
        """
        Marca todos los equipos del usuario como verificados OK.
        Útil para usuarios con muchos equipos.

        Returns:
            {
                'verified_count': int,
                'verifications': [EquipmentVerification, ...]
            }
        """
        equipment_list = InventoryItem.query.filter_by(
            assigned_to_user_id=user_id,
            is_active=True,
            requires_verification=True,
            status='ACTIVE'
        ).all()

        verifications = []
        for equipment in equipment_list:
            verification = EquipmentVerification(
                user_id=user_id,
                equipment_id=equipment.id,
                status='CONFIRMED',
                notes='Verificación masiva: todo correcto'
            )
            db.session.add(verification)

            equipment.last_verified_at = datetime.utcnow()
            equipment.last_verified_by_id = user_id
            equipment.verification_status = 'VERIFIED_OK'

            verifications.append(verification)

        db.session.commit()

        return {
            'verified_count': len(verifications),
            'verifications': verifications
        }

    @staticmethod
    def get_overdue_users(days_threshold=90):
        """
        Obtiene usuarios con equipos vencidos para verificación.

        Returns:
            [
                {
                    'user': User,
                    'equipment_count': int,
                    'oldest_verification_days': int,
                    'never_verified_count': int
                },
                ...
            ]
        """
        # Query complejo para obtener usuarios con equipos vencidos
        # Se usaría para job de recordatorios automáticos
        pass
```

### 2. CorrectionRequestService

**Archivo:** `apps/helpdesk/services/correction_request_service.py`

```python
class CorrectionRequestService:
    """Servicio para gestionar solicitudes de corrección de inventario"""

    @staticmethod
    def create_request(requester_id, equipment_id, correction_type, description,
                       proposed_changes=None, requested_new_assignee_id=None,
                       auto_created=False):
        """
        Crea una nueva solicitud de corrección.

        Returns:
            EquipmentCorrectionRequest
        """
        # Validaciones
        if len(description) < 20:
            raise ValueError("La descripción debe tener al menos 20 caracteres")

        equipment = InventoryItem.query.get(equipment_id)
        if not equipment:
            raise ValueError("Equipo no encontrado")

        user = User.query.get(requester_id)
        user_department_id = user.get_current_department()

        # Generar número de solicitud
        request_number = _generate_request_number()

        # Determinar prioridad automática
        priority_map = {
            'REPORT_LOST': 'URGENTE',
            'REPORT_DAMAGED': 'URGENTE',
            'REMOVE_ASSIGNMENT': 'ALTA',
            'CHANGE_ASSIGNMENT': 'MEDIA',
            'UPDATE_INFO': 'MEDIA',
            'CHANGE_LOCATION': 'BAJA'
        }

        request = EquipmentCorrectionRequest(
            request_number=request_number,
            requester_id=requester_id,
            requester_department_id=user_department_id,
            equipment_id=equipment_id,
            correction_type=correction_type,
            description=description,
            proposed_changes=proposed_changes,
            requested_new_assignee_id=requested_new_assignee_id,
            priority=priority_map.get(correction_type, 'MEDIA')
        )

        db.session.add(request)
        db.session.commit()

        # Enviar notificación a jefe de departamento y admins
        _notify_correction_request_created(request)

        return request

    @staticmethod
    def approve_request(request_id, reviewer_id, review_notes=None, execute_now=True):
        """
        Aprueba y opcionalmente ejecuta una solicitud de corrección.

        Args:
            execute_now: Si True, ejecuta el cambio inmediatamente
        """
        request = EquipmentCorrectionRequest.query.get(request_id)
        if not request:
            raise ValueError("Solicitud no encontrada")

        if not request.is_pending:
            raise ValueError("Solo se pueden aprobar solicitudes pendientes")

        request.status = 'APPROVED'
        request.reviewed_by_id = reviewer_id
        request.reviewed_at = datetime.utcnow()
        request.review_notes = review_notes

        if execute_now:
            CorrectionRequestService.execute_request(request_id, reviewer_id)

        db.session.commit()

        # Notificar al solicitante
        _notify_correction_request_approved(request)

        return request

    @staticmethod
    def execute_request(request_id, executor_id):
        """
        Ejecuta los cambios de una solicitud aprobada.
        """
        request = EquipmentCorrectionRequest.query.get(request_id)
        if request.status != 'APPROVED':
            raise ValueError("Solo se pueden ejecutar solicitudes aprobadas")

        equipment = request.equipment

        # Ejecutar según tipo
        if request.correction_type == 'REMOVE_ASSIGNMENT':
            InventoryService.unassign_from_user(
                equipment.id,
                reason=f"Corrección {request.request_number}: {request.description}",
                performed_by_id=executor_id
            )

        elif request.correction_type == 'CHANGE_ASSIGNMENT':
            InventoryService.assign_to_user(
                equipment.id,
                request.requested_new_assignee_id,
                assigned_by_id=executor_id,
                notes=f"Corrección {request.request_number}"
            )

        elif request.correction_type == 'REPORT_LOST':
            equipment.status = 'LOST'
            equipment.assigned_to_user_id = None
            InventoryHistoryService.log_event(
                equipment_id=equipment.id,
                event_type='STATUS_CHANGED',
                old_value={'status': 'ACTIVE'},
                new_value={'status': 'LOST'},
                notes=f"Corrección {request.request_number}: {request.description}",
                performed_by_id=executor_id
            )

        elif request.correction_type == 'REPORT_DAMAGED':
            equipment.status = 'DAMAGED'
            InventoryHistoryService.log_event(
                equipment_id=equipment.id,
                event_type='STATUS_CHANGED',
                old_value={'status': 'ACTIVE'},
                new_value={'status': 'DAMAGED'},
                notes=f"Corrección {request.request_number}",
                performed_by_id=executor_id
            )

        elif request.correction_type == 'UPDATE_INFO':
            if request.proposed_changes:
                old_values = {}
                for key, value in request.proposed_changes.items():
                    if hasattr(equipment, key):
                        old_values[key] = getattr(equipment, key)
                        setattr(equipment, key, value)

                InventoryHistoryService.log_event(
                    equipment_id=equipment.id,
                    event_type='SPECS_UPDATED',
                    old_value=old_values,
                    new_value=request.proposed_changes,
                    notes=f"Corrección {request.request_number}",
                    performed_by_id=executor_id
                )

        request.executed_by_id = executor_id
        request.executed_at = datetime.utcnow()
        db.session.commit()

        return request
```

---

## 🌐 RUTAS Y API

### API Endpoints

**Archivo:** `apps/helpdesk/routes/api/equipment_verification.py`

```python
# GET /api/help-desk/v1/equipment/my-equipment
# Obtiene equipos del usuario actual para verificar
@equipment_verification_bp.route('/my-equipment', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.equipment.api.view_own'])
def get_my_equipment():
    """Retorna equipos asignados al usuario actual"""
    user_id = session.get('user_id')
    data = EquipmentVerificationService.get_user_equipment_to_verify(user_id)
    return jsonify(data), 200

# POST /api/help-desk/v1/equipment/verify
# Verifica un equipo específico
@equipment_verification_bp.route('/verify', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.equipment.api.verify'])
def verify_equipment():
    """
    Body:
    {
        "equipment_id": 123,
        "status": "CONFIRMED" | "NOT_MINE" | "NO_LONGER_HAVE" | "WRONG_DETAILS",
        "notes": "Comentarios opcionales",
        "current_location": "Oficina 201"  # Si CONFIRMED
    }
    """
    pass

# POST /api/help-desk/v1/equipment/verify-all
# Marca todos como OK
@equipment_verification_bp.route('/verify-all', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.equipment.api.verify'])
def verify_all_ok():
    """Marca todos los equipos del usuario como verificados OK"""
    pass

# POST /api/help-desk/v1/corrections/create
# Crea solicitud de corrección
@equipment_verification_bp.route('/corrections/create', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.corrections.api.create'])
def create_correction_request():
    """
    Body:
    {
        "equipment_id": 123,
        "correction_type": "REMOVE_ASSIGNMENT",
        "description": "Descripción detallada...",
        "proposed_changes": {...},  # Opcional
        "requested_new_assignee_id": 456  # Opcional
    }
    """
    pass

# GET /api/help-desk/v1/corrections/my-requests
# Mis solicitudes de corrección
@equipment_verification_bp.route('/corrections/my-requests', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.corrections.api.read.own'])
def get_my_correction_requests():
    """Retorna solicitudes del usuario con paginación"""
    pass

# GET /api/help-desk/v1/corrections/pending
# Solicitudes pendientes de aprobación (para jefes/admins)
@equipment_verification_bp.route('/corrections/pending', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.corrections.api.read.department'])
def get_pending_corrections():
    """
    Retorna solicitudes pendientes del departamento del usuario.
    Solo para department_head y admin.
    """
    pass

# POST /api/help-desk/v1/corrections/:id/approve
# Aprobar solicitud
@equipment_verification_bp.route('/corrections/<int:request_id>/approve', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.corrections.api.approve'])
def approve_correction(request_id):
    """
    Body:
    {
        "review_notes": "Aprobado",
        "execute_now": true
    }
    """
    pass

# POST /api/help-desk/v1/corrections/:id/reject
# Rechazar solicitud
@equipment_verification_bp.route('/corrections/<int:request_id>/reject', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.corrections.api.approve'])
def reject_correction(request_id):
    """Body: {"review_notes": "Razón del rechazo"}"""
    pass
```

### Páginas HTML

**Archivo:** `apps/helpdesk/routes/pages/user_equipment.py`

```python
# GET /help-desk/user/my-equipment
@user_equipment_bp.route('/user/my-equipment', methods=['GET'])
@page_app_required('helpdesk', perms=['helpdesk.equipment.page.my_equipment'])
def my_equipment_page():
    """Página principal de 'Mi Equipo'"""
    return render_template('helpdesk/user/my_equipment.html')

# GET /help-desk/user/corrections
@user_equipment_bp.route('/user/corrections', methods=['GET'])
@page_app_required('helpdesk', perms=['helpdesk.corrections.page.my_requests'])
def my_corrections_page():
    """Página de mis solicitudes de corrección"""
    return render_template('helpdesk/user/my_corrections.html')
```

---

## 🎨 TEMPLATES Y UI

### 1. my_equipment.html

Página principal donde el usuario ve todos sus equipos.

**Elementos clave:**
- **Banner de alerta** si tiene equipos vencidos (>90 días sin verificar)
- **Estadísticas en cards**: Total, Verificados, Pendientes, Vencidos
- **Tabla de equipos** con:
  - Número de inventario
  - Categoría, Marca, Modelo
  - Ubicación
  - Fecha de asignación
  - Última verificación
  - Estado de verificación
  - **Badge** rojo si está vencido
  - **Botón "Verificar"** por equipo
- **Botón "Todo está correcto"** para verificar todo en masa
- **Botón "Reportar problema"** para crear correction request

### 2. verify_equipment_modal.html

Modal que aparece al hacer clic en "Verificar" de un equipo.

**Estructura:**
```html
<div class="modal">
  <h3>Verificar Equipo: COMP-2025-001</h3>

  <!-- Resumen del equipo -->
  <div class="equipment-summary">
    <p><strong>Categoría:</strong> Computadora de Escritorio</p>
    <p><strong>Marca:</strong> HP</p>
    <p><strong>Modelo:</strong> EliteDesk 800 G6</p>
    <p><strong>Serial:</strong> ABC123456</p>
    <p><strong>Ubicación:</strong> Oficina 201</p>
  </div>

  <!-- Opciones de verificación -->
  <form id="verify-form">
    <div class="radio-group">
      <label>
        <input type="radio" name="status" value="CONFIRMED" checked>
        ✅ Sí, este equipo es mío y lo tengo
      </label>

      <label>
        <input type="radio" name="status" value="NOT_MINE">
        ❌ Este equipo NO es mío (nunca lo tuve o me lo cambiaron)
      </label>

      <label>
        <input type="radio" name="status" value="NO_LONGER_HAVE">
        ⚠️ Era mío pero ya no lo tengo (lo regresé, se dañó, etc.)
      </label>

      <label>
        <input type="radio" name="status" value="WRONG_DETAILS">
        ℹ️ Es mío pero la información (marca/modelo/serial) es incorrecta
      </label>
    </div>

    <!-- Campo de ubicación (solo si CONFIRMED) -->
    <div id="location-field" class="form-group">
      <label>Confirma o actualiza la ubicación:</label>
      <input type="text" name="current_location" value="Oficina 201">
    </div>

    <!-- Notas (obligatorio si NO es CONFIRMED) -->
    <div class="form-group">
      <label>Comentarios adicionales:</label>
      <textarea name="notes" rows="3" placeholder="Explica la situación..."></textarea>
    </div>

    <div class="modal-footer">
      <button type="button" class="btn-secondary">Cancelar</button>
      <button type="submit" class="btn-primary">Guardar Verificación</button>
    </div>
  </form>
</div>
```

**Comportamiento:**
- Si selecciona algo diferente a CONFIRMED, el campo de notas se vuelve obligatorio
- Al enviar, si hay problema, automáticamente crea una correction request
- Muestra mensaje de confirmación y actualiza la tabla sin reload

### 3. correction_request_form.html

Formulario completo para crear una solicitud de corrección manualmente.

**Casos de uso:**
- Usuario quiere reportar equipo perdido sin verificar primero
- Usuario quiere solicitar cambio de asignación
- Usuario quiere actualizar información detallada

---

## 👤 FLUJO DE USUARIO

### Escenario 1: Verificación simple (todo OK)

1. Usuario entra a `/help-desk/user/my-equipment`
2. Ve su lista de equipos con badges de "Vencido" en rojo
3. Hace clic en "Verificar" en COMP-2025-001
4. Modal se abre, selecciona "✅ Sí, este equipo es mío"
5. Confirma la ubicación "Oficina 201"
6. Clic en "Guardar Verificación"
7. Toast: "✅ Equipo verificado correctamente"
8. Badge cambia a "Verificado ✓" en verde
9. Contador de "Pendientes" disminuye

### Escenario 2: Reportar equipo que no es suyo

1. Usuario entra a `/help-desk/user/my-equipment`
2. Ve equipo IMP-2025-050 que nunca le han dado
3. Clic en "Verificar"
4. Selecciona "❌ Este equipo NO es mío"
5. Campo de notas se vuelve obligatorio (borde rojo)
6. Escribe: "Nunca he tenido esta impresora, debe ser un error de registro"
7. Clic en "Guardar Verificación"
8. Sistema automáticamente:
   - Crea verificación con status=NOT_MINE
   - Crea CorrectionRequest #CR-2026-0001 tipo REMOVE_ASSIGNMENT
   - Envía notificación a jefe de departamento
9. Toast: "⚠️ Verificación guardada. Se creó la solicitud CR-2026-0001 para revisar este equipo"
10. Usuario puede ir a "Mis Solicitudes" para ver el estatus

### Escenario 3: Verificación masiva

1. Usuario tiene 5 equipos asignados, todos correctos
2. En vez de verificar uno por uno, clic en botón "✅ Todo está correcto"
3. Modal de confirmación: "¿Confirmas que TODOS los equipos listados son correctos y los tienes en tu poder?"
4. Acepta
5. Sistema crea 5 verificaciones con status=CONFIRMED
6. Toast: "✅ 5 equipos verificados exitosamente"
7. Todos los badges cambian a verde

### Escenario 4: Jefe de departamento aprueba corrección

1. Jefe entra a `/help-desk/department/corrections`
2. Ve solicitud pendiente CR-2026-0001
3. Lee: "Usuario reporta que nunca tuvo la impresora IMP-2025-050"
4. Revisa historial del equipo
5. Confirma que fue error de asignación
6. Clic en "Aprobar y Ejecutar"
7. Escribe nota: "Error confirmado, nunca se le asignó físicamente"
8. Sistema:
   - Marca request como APPROVED
   - Ejecuta: `equipment.assigned_to_user_id = NULL`
   - Registra en InventoryHistory
   - Notifica al usuario: "Tu solicitud CR-2026-0001 fue aprobada"
9. Equipo queda en estado PENDING_ASSIGNMENT para reasignar

---

## 🔒 SEGURIDAD Y VALIDACIONES

### Validaciones de backend:

1. **Verificación solo de equipos propios:**
   - Usuario solo puede verificar equipos con `assigned_to_user_id == user_id`
   - Retornar 403 Forbidden si intenta verificar equipo ajeno

2. **Correction requests:**
   - Descripción mínimo 20 caracteres
   - No permitir duplicados (misma combinación user + equipment + tipo en status PENDING)

3. **Aprobación de requests:**
   - Solo admin o jefe del departamento del solicitante
   - No aprobar si status != PENDING
   - Ejecutar cambios con transaction para atomicidad

4. **Rate limiting:**
   - Máximo 50 verificaciones por usuario por día (prevenir spam)
   - Máximo 10 correction requests por usuario por día

### Auditoría:

- Todas las acciones se registran en `InventoryHistory`
- Tracking de IP en `EquipmentCorrectionRequest`
- Timestamps en todas las tablas

---

## 📊 MÉTRICAS Y REPORTES

### Dashboard para Admin/Jefe de Departamento:

**Métricas clave:**
- % de equipos verificados en los últimos 90 días
- Usuarios con equipos vencidos (nunca verificados)
- Solicitudes de corrección pendientes por tipo
- Top 10 usuarios con más equipos sin verificar
- Evolución de verificaciones en el tiempo (gráfica)

**Reportes exportables:**
- CSV de equipos no verificados por departamento
- Reporte de integridad de inventario

---

## 📅 PLAN DE IMPLEMENTACIÓN POR FASES

### Fase 1: Base de datos y modelos (1-2 días)
- [ ] Crear migraciones para 3 nuevas tablas
- [ ] Agregar campos a `InventoryItem`
- [ ] Crear modelos en Python
- [ ] Generar datos de prueba (seeds)

### Fase 2: Servicios y lógica de negocio (2-3 días)
- [ ] `EquipmentVerificationService`
- [ ] `CorrectionRequestService`
- [ ] `VerificationReminderService` (solo estructura, cronjob después)
- [ ] Tests unitarios de servicios

### Fase 3: API REST (2 días)
- [ ] Endpoints de verificación
- [ ] Endpoints de correction requests
- [ ] Validaciones y manejo de errores
- [ ] Documentación de API

### Fase 4: Frontend - Páginas de usuario (3-4 días)
- [ ] Template `my_equipment.html`
- [ ] Modal de verificación
- [ ] JavaScript para interacciones
- [ ] CSS y diseño responsivo
- [ ] Página de "Mis Solicitudes"

### Fase 5: Frontend - Panel de aprobación (2 días)
- [ ] Vista para jefe de departamento
- [ ] Flujo de aprobación/rechazo
- [ ] Ejecución automática de cambios

### Fase 6: Integraciones (2 días)
- [ ] Modificar navegación para agregar "Mi Equipo"
- [ ] Sistema de notificaciones
- [ ] Integración con permisos existentes
- [ ] Envío de emails

### Fase 7: Features avanzados (3 días)
- [ ] Recordatorios automáticos (cronjob)
- [ ] Bloqueo de creación de tickets si no ha verificado (opcional)
- [ ] Dashboard de métricas
- [ ] Exportación de reportes

### Fase 8: Testing y refinamiento (2 días)
- [ ] Testing E2E con Selenium/Playwright
- [ ] Pruebas de carga
- [ ] Corrección de bugs
- [ ] Optimización de queries

**Total estimado:** 17-21 días de desarrollo

---

## ⚠️ RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Usuarios ignoran recordatorios | Alta | Alto | Implementar bloqueo opcional de tickets |
| Falsas reportes de pérdida | Media | Alto | Requerir aprobación de jefe, historial de usuario |
| Sobrecarga de solicitudes al inicio | Alta | Medio | Implementación gradual por departamento |
| Performance con muchos equipos | Media | Medio | Índices en BD, paginación, lazy loading |
| Resistencia al cambio | Alta | Medio | Capacitación, comunicación de beneficios |

---

## 🎯 CRITERIOS DE ÉXITO

- ✅ 90% de equipos asignados verificados en primeros 30 días
- ✅ <5% de solicitudes de corrección rechazadas (indica buena UX)
- ✅ 100% de correction requests atendidas en <48 horas
- ✅ 0 errores críticos en producción
- ✅ Reducción de 50% en tickets mal clasificados por inventario
- ✅ Feedback positivo de usuarios (>7/10 en encuesta)

---

## 📝 NOTAS ADICIONALES

### Consideraciones UX:
- El sistema debe ser "molesto pero no insoportable"
- Usar gamificación: badges de "Verificador Confiable" para usuarios que siempre verifican a tiempo
- Mostrar estadísticas del departamento para crear competencia sana

### Extensiones futuras:
- App móvil para escanear QR de equipos y verificar
- Verificación con foto (subir foto del equipo durante verificación)
- Geolocalización para verificar ubicación física
- Integración con sistema de bajas automáticas

---

**Fin del documento de planificación #1**

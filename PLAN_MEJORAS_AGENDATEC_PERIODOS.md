# Plan de Mejoras AgendaTec - Sistema de Periodos Académicos

## Documento de Planificación
**Fecha:** 2026-01-07
**Objetivo:** Implementar sistema de periodos académicos y configuración dinámica de días habilitados para que la aplicación AgendaTec pueda reutilizarse semestre tras semestre.

---

## Tabla de Contenidos
1. [Análisis de Situación Actual](#1-análisis-de-situación-actual)
2. [Arquitectura Propuesta](#2-arquitectura-propuesta)
3. [Fases de Implementación](#3-fases-de-implementación)
4. [Sugerencias de Mejoras Adicionales](#4-sugerencias-de-mejoras-adicionales)
5. [Consideraciones Técnicas](#5-consideraciones-técnicas)

---

## 1. Análisis de Situación Actual

### 1.1 Problemas Identificados

#### **Fechas Hardcodeadas (11 archivos)**

Las fechas 25, 26, 27 de Agosto de 2025 están hardcodeadas en:

**Backend (Python):**
1. `itcj/apps/agendatec/routes/api/requests.py:22` - Variable `ALLOWED_DAYS`
2. `itcj/apps/agendatec/routes/api/slots.py:14` - Variable `ALLOWED_DAYS`
3. `itcj/apps/agendatec/routes/api/availability.py:17` - Variable `ALLOWED_DAYS`
4. `itcj/apps/agendatec/routes/api/coord.py:23` - Variable `ALLOWED_DAYS`

**Frontend (JavaScript):**
5. `itcj/apps/agendatec/static/js/student/request.js:5` - Array `ALLOWED_DAYS`
6. `itcj/apps/agendatec/static/js/admin/home.js:21` - Fecha hardcodeada en filtro

**Templates (HTML):**
7. `itcj/apps/agendatec/templates/agendatec/student/new_request.html:126-128` - Botones de días
8. `itcj/apps/agendatec/templates/agendatec/coord/slots.html:17-19, 118-120` - Options de días
9. `itcj/apps/agendatec/templates/agendatec/coord/appointments.html:15-17` - Options de días
10. `itcj/apps/agendatec/templates/agendatec/social/home.html:11-13` - Options de días

#### **Restricciones de Solicitudes Sin Concepto de Periodo**

Actualmente:
- Un estudiante solo puede tener UNA solicitud PENDING a la vez
- No hay concepto de periodo, por lo que si un estudiante usó el sistema en Ago 2025, no podrá crear una nueva solicitud en Ene 2026
- La validación actual en `routes/api/requests.py:78-83`:
  ```python
  exists = db.session.query(Request).filter(
      Request.student_id == u.id).first()
  if exists and exists.status != "CANCELED":
      return jsonify({"error": "already_has_petition"}), 409
  ```

**PROBLEMA:** No considera que cada periodo es independiente.

#### **Falta de Validaciones Temporales para Cancelación**

Actualmente se puede cancelar una solicitud PENDING sin validar:
- Si la fecha/hora de la cita ya pasó
- Si el periodo académico ya cerró

#### **Variable de Entorno Estática**

`LAST_TIME_STUDENT_ADMIT='2025-08-27 18:00:00'` en `.env` debe cambiarse manualmente cada semestre.

---

### 1.2 Requisitos del Usuario

Según conversación, se necesita:

1. **Modelo de Periodo Académico** que contenga:
   - Nombre del periodo (ej: "Ago-Dic 2025")
   - Fecha de inicio y fin del periodo
   - Hora límite de admisión para estudiantes
   - Estado: activo/inactivo/archivado
   - **Solo UN periodo puede estar activo a la vez**

2. **Pantalla Administrativa Separada** para configurar:
   - Los días específicos habilitados para que estudiantes creen solicitudes
   - Esta configuración debe estar vinculada al periodo académico

3. **Validaciones mejoradas para cancelación**:
   - No permitir cancelar si ya pasó la fecha/hora de la cita
   - No permitir cancelar si el periodo ya cerró

4. **Restricción de solicitudes por periodo**:
   - Un estudiante puede tener una solicitud PENDING por periodo
   - Si usó el sistema en Ago-Dic 2025, puede volver a usarlo en Ene-Jun 2026

---

## 2. Arquitectura Propuesta

### 2.1 Nuevos Modelos

#### **AcademicPeriod** (`itcj/core/models/academic_period.py`)

```python
class AcademicPeriod(db.Model):
    __tablename__ = "core_academic_periods"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    # Ej: "Ago-Dic 2025", "Ene-Jun 2026"

    # Rango completo del semestre
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Ventana de admisión para estudiantes
    student_admission_deadline = db.Column(db.DateTime(timezone=True), nullable=False)
    # Ej: "2025-08-27 18:00:00-07:00"

    # Estado del periodo
    status = db.Column(
        db.Enum("ACTIVE", "INACTIVE", "ARCHIVED", name="period_status"),
        nullable=False,
        default="INACTIVE"
    )

    # Solo un periodo puede estar ACTIVE a la vez
    # (constraint a nivel de aplicación)

    # Auditoría
    created_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    enabled_days = db.relationship("PeriodEnabledDay", back_populates="period", cascade="all, delete-orphan")
    requests = db.relationship("Request", back_populates="period")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # Constraints
    __table_args__ = (
        db.CheckConstraint('end_date >= start_date', name='check_period_dates'),
        db.CheckConstraint(
            "student_admission_deadline <= (end_date + interval '1 day')",
            name='check_admission_within_period'
        ),
        db.Index('idx_period_status', 'status'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "student_admission_deadline": self.student_admission_deadline.isoformat(),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @staticmethod
    def get_active():
        """Obtiene el periodo activo actual."""
        return AcademicPeriod.query.filter_by(status="ACTIVE").first()

    def is_student_window_open(self):
        """Verifica si la ventana de admisión para estudiantes está abierta."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Ciudad_Juarez")
        now = datetime.now(tz)

        return (
            self.status == "ACTIVE" and
            now <= self.student_admission_deadline
        )
```

#### **PeriodEnabledDay** (`itcj/apps/agendatec/models/period_enabled_day.py`)

```python
class PeriodEnabledDay(db.Model):
    """
    Días habilitados para que estudiantes creen solicitudes en un periodo académico.
    Configurable desde pantalla administrativa.
    """
    __tablename__ = "agendatec_period_enabled_days"

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey("core_academic_periods.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)

    # Auditoría
    created_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = db.relationship("AcademicPeriod", back_populates="enabled_days")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # Constraints
    __table_args__ = (
        db.UniqueConstraint('period_id', 'day', name='uq_period_day'),
        db.CheckConstraint(
            "day >= (SELECT start_date FROM core_academic_periods WHERE id = period_id)",
            name='check_day_after_period_start'
        ),
        db.CheckConstraint(
            "day <= (SELECT end_date FROM core_academic_periods WHERE id = period_id)",
            name='check_day_before_period_end'
        ),
        db.Index('idx_period_enabled_days', 'period_id', 'day'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "period_id": self.period_id,
            "day": self.day.isoformat(),
            "created_at": self.created_at.isoformat()
        }
```

#### **Modificación al Modelo Request**

Agregar campo `period_id`:

```python
# En itcj/apps/agendatec/models/request.py

class Request(db.Model):
    __tablename__ = "agendatec_requests"

    id = db.Column(db.BigInteger, primary_key=True)
    student_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("core_programs.id"), nullable=False)

    # NUEVO CAMPO
    period_id = db.Column(
        db.Integer,
        db.ForeignKey("core_academic_periods.id"),
        nullable=False,
        index=True
    )

    type = db.Column(
        db.Enum("DROP", "APPOINTMENT", name="request_type"),
        nullable=False
    )
    description = db.Column(db.Text)
    status = db.Column(
        db.Enum(
            "PENDING",
            "RESOLVED_SUCCESS",
            "RESOLVED_NOT_COMPLETED",
            "NO_SHOW",
            "ATTENDED_OTHER_SLOT",
            "CANCELED",
            name="request_status"
        ),
        nullable=False,
        default="PENDING"
    )
    coordinator_comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"), nullable=False)

    # Relaciones
    student = db.relationship("User", foreign_keys=[student_id], backref="agendatec_requests")
    program = db.relationship("Program", backref="agendatec_requests")
    period = db.relationship("AcademicPeriod", back_populates="requests")  # NUEVA
    appointment = db.relationship("Appointment", uselist=False, back_populates="request")

    # Índice compuesto para la restricción "una solicitud PENDING por estudiante por periodo"
    __table_args__ = (
        db.Index('idx_student_period_status', 'student_id', 'period_id', 'status'),
    )
```

---

### 2.2 Diagrama de Relaciones

```
core_academic_periods (NUEVO)
├── id (PK)
├── name
├── start_date, end_date
├── student_admission_deadline
├── status (ACTIVE/INACTIVE/ARCHIVED)
└── [timestamps]

agendatec_period_enabled_days (NUEVO)
├── id (PK)
├── period_id (FK → core_academic_periods.id)
├── day
└── [timestamps]

agendatec_requests (MODIFICADO)
├── id (PK)
├── student_id (FK → core_users.id)
├── program_id (FK → core_programs.id)
├── period_id (FK → core_academic_periods.id) ← NUEVO
├── type, status, description
└── [timestamps]
```

---

### 2.3 Pantallas Administrativas

#### **Pantalla 1: Gestión de Periodos Académicos**

Ubicación: `/agendatec/admin/periods`

**Funcionalidades:**
- Listar todos los periodos (tabla con columnas: nombre, fechas, estado, acciones)
- Crear nuevo periodo
- Editar periodo existente
- Activar/Desactivar/Archivar periodo
- Validación: Solo un periodo puede estar ACTIVE a la vez
- Al activar un periodo, se desactiva automáticamente el anterior

**Campos del formulario:**
- Nombre del periodo (texto)
- Fecha de inicio (date picker)
- Fecha de fin (date picker)
- Hora límite de admisión (datetime picker)
- Estado (select: INACTIVE/ACTIVE/ARCHIVED)

#### **Pantalla 2: Configuración de Días Habilitados**

Ubicación: `/agendatec/admin/periods/<period_id>/days`

**Funcionalidades:**
- Calendario visual mostrando el rango del periodo
- Selección múltiple de días habilitados
- Guardar configuración de días
- Validación: Los días deben estar dentro del rango start_date - end_date
- Vista previa de días seleccionados

**Flujo:**
1. Admin selecciona un periodo desde la tabla de periodos
2. Click en "Configurar días habilitados"
3. Se muestra calendario con rango del periodo
4. Admin selecciona días (ej: 25, 26, 27 de Agosto)
5. Guardar → inserta registros en `agendatec_period_enabled_days`

---

## 3. Fases de Implementación

### **FASE 1: Preparación de Base de Datos**

#### Tareas:
1. Crear migración para `core_academic_periods`
2. Crear migración para `agendatec_period_enabled_days`
3. Crear migración para agregar `period_id` a `agendatec_requests`
4. Ejecutar migraciones en desarrollo

#### Archivos a crear/modificar:
- `itcj/core/models/academic_period.py` (nuevo)
- `itcj/core/models/__init__.py` (importar AcademicPeriod)
- `itcj/apps/agendatec/models/period_enabled_day.py` (nuevo)
- `itcj/apps/agendatec/models/__init__.py` (importar PeriodEnabledDay)
- `itcj/apps/agendatec/models/request.py` (agregar period_id)
- Archivos de migración en `migrations/`

#### Comandos:
```bash
flask db migrate -m "Add AcademicPeriod and PeriodEnabledDay models"
flask db upgrade
```

#### Datos iniciales:
Crear script para insertar periodo actual basado en fechas hardcodeadas:
```python
# Script: itcj/apps/agendatec/scripts/seed_initial_period.py

from itcj.core.models import AcademicPeriod
from itcj.apps.agendatec.models import PeriodEnabledDay
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Crear periodo Ago-Dic 2025
period = AcademicPeriod(
    name="Ago-Dic 2025",
    start_date=date(2025, 8, 1),
    end_date=date(2025, 12, 31),
    student_admission_deadline=datetime(2025, 8, 27, 18, 0, 0, tzinfo=ZoneInfo("America/Ciudad_Juarez")),
    status="ACTIVE"
)
db.session.add(period)
db.session.flush()

# Agregar días habilitados
for day in [date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)]:
    enabled_day = PeriodEnabledDay(period_id=period.id, day=day)
    db.session.add(enabled_day)

db.session.commit()
```

#### Migración de datos:
Actualizar todas las solicitudes existentes para vincularlas al periodo "Ago-Dic 2025":
```sql
UPDATE agendatec_requests
SET period_id = (SELECT id FROM core_academic_periods WHERE name = 'Ago-Dic 2025' LIMIT 1)
WHERE period_id IS NULL;
```

---

### **FASE 2: Servicios y Utilidades Backend**

#### Tareas:
1. Crear servicio para gestión de periodos
2. Crear servicio para días habilitados
3. Actualizar decorador `@api_closed` para usar periodo activo
4. Crear funciones helper para validaciones

#### Archivos a crear/modificar:

**1. Servicio de Periodos** (`itcj/core/services/period_service.py`)
```python
from itcj.core.models import AcademicPeriod
from itcj.core.extensions import db

class PeriodService:
    @staticmethod
    def get_active_period():
        """Retorna el periodo activo actual."""
        return AcademicPeriod.query.filter_by(status="ACTIVE").first()

    @staticmethod
    def is_student_window_open():
        """Verifica si la ventana de admisión está abierta."""
        period = PeriodService.get_active_period()
        if not period:
            return False
        return period.is_student_window_open()

    @staticmethod
    def activate_period(period_id, user_id):
        """
        Activa un periodo y desactiva todos los demás.
        """
        # Desactivar todos
        AcademicPeriod.query.update({"status": "INACTIVE"})

        # Activar el seleccionado
        period = AcademicPeriod.query.get(period_id)
        if not period:
            raise ValueError("Period not found")

        period.status = "ACTIVE"
        db.session.commit()

        return period

    @staticmethod
    def get_enabled_days(period_id=None):
        """
        Retorna los días habilitados del periodo activo o del periodo especificado.
        """
        from itcj.apps.agendatec.models import PeriodEnabledDay

        if period_id is None:
            period = PeriodService.get_active_period()
            if not period:
                return []
            period_id = period.id

        enabled_days = PeriodEnabledDay.query.filter_by(period_id=period_id).all()
        return [ed.day for ed in enabled_days]
```

**2. Actualizar decorador de ventana** (`itcj/apps/agendatec/utils/decorators.py` - nuevo)
```python
from functools import wraps
from flask import jsonify
from itcj.core.services.period_service import PeriodService

def api_closed(f):
    """
    Decorador que verifica si la ventana de admisión para estudiantes está abierta.
    Reemplaza el decorador @api_closed anterior que usaba LAST_TIME_STUDENT_ADMIT.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not PeriodService.is_student_window_open():
            return jsonify({
                "error": "student_window_closed",
                "message": "La ventana de admisión para estudiantes ha cerrado."
            }), 423  # Locked
        return f(*args, **kwargs)
    return decorated
```

**3. Actualizar imports** en archivos que usan `@api_closed`:
- `itcj/apps/agendatec/routes/api/requests.py`
- `itcj/apps/agendatec/routes/api/slots.py`

---

### **FASE 3: APIs Backend para Admin**

#### Tareas:
1. Crear endpoints para gestión de periodos
2. Crear endpoints para configuración de días habilitados
3. Agregar validaciones y permisos

#### Archivos a crear/modificar:

**1. APIs de Periodos** (`itcj/apps/agendatec/routes/api/periods.py` - nuevo)
```python
from flask import Blueprint, jsonify, request
from itcj.core.extensions import db
from itcj.core.models import AcademicPeriod
from itcj.apps.agendatec.models import PeriodEnabledDay
from itcj.core.services.period_service import PeriodService
from itcj.core.utils.jwt_auth import jwt_required
from datetime import datetime
from zoneinfo import ZoneInfo

bp = Blueprint("periods", __name__, url_prefix="/api/agendatec/v1/admin/periods")

@bp.route("", methods=["GET"])
@jwt_required
def list_periods():
    """Listar todos los periodos académicos."""
    # TODO: Verificar rol admin

    periods = AcademicPeriod.query.order_by(AcademicPeriod.start_date.desc()).all()
    return jsonify([p.to_dict() for p in periods]), 200

@bp.route("", methods=["POST"])
@jwt_required
def create_period():
    """Crear nuevo periodo académico."""
    # TODO: Verificar rol admin

    data = request.json
    u = request.current_user

    # Validaciones
    required = ["name", "start_date", "end_date", "student_admission_deadline"]
    if not all(k in data for k in required):
        return jsonify({"error": "missing_fields"}), 400

    # Parse dates
    try:
        start_date = datetime.fromisoformat(data["start_date"]).date()
        end_date = datetime.fromisoformat(data["end_date"]).date()
        admission_deadline = datetime.fromisoformat(data["student_admission_deadline"])

        # Asegurar timezone
        if admission_deadline.tzinfo is None:
            admission_deadline = admission_deadline.replace(tzinfo=ZoneInfo("America/Ciudad_Juarez"))
    except ValueError as e:
        return jsonify({"error": "invalid_date_format", "details": str(e)}), 400

    # Validar rango de fechas
    if end_date < start_date:
        return jsonify({"error": "end_date_before_start_date"}), 400

    # Crear periodo
    period = AcademicPeriod(
        name=data["name"],
        start_date=start_date,
        end_date=end_date,
        student_admission_deadline=admission_deadline,
        status=data.get("status", "INACTIVE"),
        created_by_id=u.id
    )

    # Si se marca como ACTIVE, desactivar los demás
    if period.status == "ACTIVE":
        AcademicPeriod.query.update({"status": "INACTIVE"})

    db.session.add(period)
    db.session.commit()

    return jsonify(period.to_dict()), 201

@bp.route("/<int:period_id>", methods=["PATCH"])
@jwt_required
def update_period(period_id):
    """Actualizar periodo académico."""
    # TODO: Verificar rol admin

    period = AcademicPeriod.query.get_or_404(period_id)
    data = request.json

    # Actualizar campos permitidos
    if "name" in data:
        period.name = data["name"]
    if "start_date" in data:
        period.start_date = datetime.fromisoformat(data["start_date"]).date()
    if "end_date" in data:
        period.end_date = datetime.fromisoformat(data["end_date"]).date()
    if "student_admission_deadline" in data:
        deadline = datetime.fromisoformat(data["student_admission_deadline"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=ZoneInfo("America/Ciudad_Juarez"))
        period.student_admission_deadline = deadline

    # Si se cambia status a ACTIVE
    if "status" in data and data["status"] == "ACTIVE":
        AcademicPeriod.query.filter(AcademicPeriod.id != period_id).update({"status": "INACTIVE"})
        period.status = "ACTIVE"
    elif "status" in data:
        period.status = data["status"]

    period.updated_at = datetime.now()
    db.session.commit()

    return jsonify(period.to_dict()), 200

@bp.route("/<int:period_id>/enabled-days", methods=["GET"])
@jwt_required
def get_enabled_days(period_id):
    """Obtener días habilitados de un periodo."""
    # TODO: Verificar rol admin

    enabled_days = PeriodEnabledDay.query.filter_by(period_id=period_id).all()
    return jsonify([ed.to_dict() for ed in enabled_days]), 200

@bp.route("/<int:period_id>/enabled-days", methods=["POST"])
@jwt_required
def set_enabled_days(period_id):
    """
    Configurar días habilitados para un periodo.
    Body: { "days": ["2025-08-25", "2025-08-26", "2025-08-27"] }
    """
    # TODO: Verificar rol admin

    period = AcademicPeriod.query.get_or_404(period_id)
    data = request.json
    u = request.current_user

    if "days" not in data or not isinstance(data["days"], list):
        return jsonify({"error": "invalid_payload"}), 400

    # Parse días
    try:
        days = [datetime.fromisoformat(d).date() for d in data["days"]]
    except ValueError as e:
        return jsonify({"error": "invalid_date_format", "details": str(e)}), 400

    # Validar que los días estén dentro del rango del periodo
    for day in days:
        if not (period.start_date <= day <= period.end_date):
            return jsonify({
                "error": "day_out_of_period_range",
                "day": day.isoformat()
            }), 400

    # Eliminar días existentes
    PeriodEnabledDay.query.filter_by(period_id=period_id).delete()

    # Insertar nuevos días
    for day in days:
        enabled_day = PeriodEnabledDay(
            period_id=period_id,
            day=day,
            created_by_id=u.id
        )
        db.session.add(enabled_day)

    db.session.commit()

    return jsonify({"message": "enabled_days_updated", "count": len(days)}), 200

@bp.route("/active", methods=["GET"])
def get_active_period():
    """Obtener periodo activo (público, para estudiantes)."""
    period = PeriodService.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 404

    # Incluir días habilitados
    enabled_days = PeriodService.get_enabled_days(period.id)

    result = period.to_dict()
    result["enabled_days"] = [d.isoformat() for d in enabled_days]
    result["is_window_open"] = period.is_student_window_open()

    return jsonify(result), 200
```

**2. Registrar blueprint** en `itcj/apps/agendatec/__init__.py`:
```python
from .routes.api import periods as api_periods
app.register_blueprint(api_periods.bp)
```

---

### **FASE 4: Actualizar Validaciones Backend**

#### Tareas:
1. Reemplazar `ALLOWED_DAYS` hardcodeadas por consultas dinámicas
2. Actualizar validación "una solicitud por estudiante" para incluir periodo
3. Agregar validaciones de cancelación

#### Archivos a modificar:

**1. `itcj/apps/agendatec/routes/api/requests.py`**

Cambios principales:
```python
# ANTES:
ALLOWED_DAYS = {date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)}

# DESPUÉS:
from itcj.core.services.period_service import PeriodService

@bp.route("", methods=["POST"])
@jwt_required
@api_closed  # Ya usa PeriodService internamente
def create_request():
    u = request.current_user
    data = request.json

    # Obtener periodo activo
    period = PeriodService.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    # Validar una solicitud PENDING por periodo
    exists = db.session.query(Request).filter(
        Request.student_id == u.id,
        Request.period_id == period.id  # NUEVO: filtrar por periodo
    ).first()

    if exists and exists.status != "CANCELED":
        return jsonify({"error": "already_has_petition_this_period"}), 409

    # Para APPOINTMENT: validar día habilitado
    if data.get("type") == "APPOINTMENT":
        slot_id = data.get("slot_id")
        slot = TimeSlot.query.get(slot_id)

        # Obtener días habilitados del periodo
        enabled_days = set(PeriodService.get_enabled_days(period.id))

        if slot.day not in enabled_days:
            return jsonify({"error": "day_not_enabled"}), 400

        # ... resto de validaciones de slot ...

    # Crear solicitud con period_id
    r = Request(
        student_id=u.id,
        program_id=data["program_id"],
        period_id=period.id,  # NUEVO
        type=data["type"],
        description=data.get("description", ""),
        status="PENDING"
    )
    # ... resto de la lógica ...

@bp.route("/<int:req_id>/cancel", methods=["PATCH"])
@jwt_required
@api_closed
def cancel_request(req_id):
    u = request.current_user

    r = Request.query.filter_by(
        id=req_id,
        student_id=u.id
    ).first()

    if not r:
        return jsonify({"error": "not_found"}), 404

    if r.status != "PENDING":
        return jsonify({"error": "not_pending"}), 400

    # NUEVA VALIDACIÓN: Verificar si el periodo cerró
    period = AcademicPeriod.query.get(r.period_id)
    if period.status != "ACTIVE":
        return jsonify({
            "error": "period_closed",
            "message": "No se puede cancelar porque el periodo académico ha cerrado."
        }), 403

    # NUEVA VALIDACIÓN: Si es APPOINTMENT, verificar que la cita no haya pasado
    if r.type == "APPOINTMENT" and r.appointment:
        slot = r.appointment.slot
        now = datetime.now()
        slot_datetime = datetime.combine(slot.day, slot.start_time)

        if now >= slot_datetime:
            return jsonify({
                "error": "appointment_time_passed",
                "message": "No se puede cancelar porque la cita ya pasó."
            }), 403

    # Proceder con cancelación
    r.status = "CANCELED"

    if r.type == "APPOINTMENT" and r.appointment:
        r.appointment.status = "CANCELED"
        slot = r.appointment.slot
        slot.is_booked = False

    db.session.commit()

    # Emitir eventos WebSocket...

    return jsonify({"message": "request_canceled"}), 200
```

**2. `itcj/apps/agendatec/routes/api/slots.py`**

Reemplazar `ALLOWED_DAYS`:
```python
# ANTES:
ALLOWED_DAYS = {date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)}

@bp.route("/hold", methods=["POST"])
@jwt_required
@api_closed
def hold_slot():
    # ...
    if slot.day not in ALLOWED_DAYS:
        return jsonify({"error": "day_not_allowed"}), 400

# DESPUÉS:
from itcj.core.services.period_service import PeriodService

@bp.route("/hold", methods=["POST"])
@jwt_required
@api_closed
def hold_slot():
    # ...
    period = PeriodService.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(PeriodService.get_enabled_days(period.id))
    if slot.day not in enabled_days:
        return jsonify({"error": "day_not_enabled"}), 400
    # ...
```

**3. `itcj/apps/agendatec/routes/api/availability.py`**

Similar al anterior, reemplazar `ALLOWED_DAYS`.

**4. `itcj/apps/agendatec/routes/api/coord.py`**

Actualizar dashboard y day-config para usar días dinámicos.

---

### **FASE 5: Frontend - Pantallas Administrativas**

#### Tareas:
1. Crear página de gestión de periodos
2. Crear página de configuración de días habilitados
3. Integrar con APIs

#### Archivos a crear:

**1. Template: Gestión de Periodos** (`itcj/apps/agendatec/templates/agendatec/admin/periods.html`)

```html
{% extends "agendatec/base.html" %}

{% block title %}Gestión de Periodos Académicos{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2>Periodos Académicos</h2>
        <button class="btn btn-primary" id="btnNewPeriod">
            <i class="fas fa-plus"></i> Nuevo Periodo
        </button>
    </div>

    <!-- Tabla de periodos -->
    <table class="table table-striped" id="periodsTable">
        <thead>
            <tr>
                <th>Nombre</th>
                <th>Fecha Inicio</th>
                <th>Fecha Fin</th>
                <th>Límite Admisión</th>
                <th>Estado</th>
                <th>Acciones</th>
            </tr>
        </thead>
        <tbody>
            <!-- Llenado dinámicamente con JS -->
        </tbody>
    </table>
</div>

<!-- Modal: Crear/Editar Periodo -->
<div class="modal fade" id="periodModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="periodModalTitle">Nuevo Periodo</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <form id="periodForm">
                    <input type="hidden" id="periodId">

                    <div class="mb-3">
                        <label for="periodName" class="form-label">Nombre del Periodo</label>
                        <input type="text" class="form-control" id="periodName"
                               placeholder="Ej: Ago-Dic 2025" required>
                    </div>

                    <div class="mb-3">
                        <label for="startDate" class="form-label">Fecha de Inicio</label>
                        <input type="date" class="form-control" id="startDate" required>
                    </div>

                    <div class="mb-3">
                        <label for="endDate" class="form-label">Fecha de Fin</label>
                        <input type="date" class="form-control" id="endDate" required>
                    </div>

                    <div class="mb-3">
                        <label for="admissionDeadline" class="form-label">Límite de Admisión Estudiantes</label>
                        <input type="datetime-local" class="form-control" id="admissionDeadline" required>
                    </div>

                    <div class="mb-3">
                        <label for="periodStatus" class="form-label">Estado</label>
                        <select class="form-select" id="periodStatus">
                            <option value="INACTIVE">Inactivo</option>
                            <option value="ACTIVE">Activo</option>
                            <option value="ARCHIVED">Archivado</option>
                        </select>
                        <small class="text-muted">Solo un periodo puede estar activo a la vez.</small>
                    </div>
                </form>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                <button type="button" class="btn btn-primary" id="btnSavePeriod">Guardar</button>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('agendatec.static', filename='js/admin/periods.js') }}"></script>
{% endblock %}
```

**2. JavaScript: Gestión de Periodos** (`itcj/apps/agendatec/static/js/admin/periods.js`)

```javascript
document.addEventListener("DOMContentLoaded", async () => {
    await loadPeriods();

    document.getElementById("btnNewPeriod").addEventListener("click", () => {
        openPeriodModal();
    });

    document.getElementById("btnSavePeriod").addEventListener("click", async () => {
        await savePeriod();
    });
});

async function loadPeriods() {
    try {
        const response = await fetch("/api/agendatec/v1/admin/periods", {
            headers: { "Authorization": `Bearer ${getToken()}` }
        });

        if (!response.ok) throw new Error("Failed to load periods");

        const periods = await response.json();
        renderPeriodsTable(periods);
    } catch (error) {
        console.error(error);
        alert("Error al cargar periodos");
    }
}

function renderPeriodsTable(periods) {
    const tbody = document.querySelector("#periodsTable tbody");
    tbody.innerHTML = "";

    periods.forEach(period => {
        const tr = document.createElement("tr");

        const statusBadge = {
            "ACTIVE": '<span class="badge bg-success">Activo</span>',
            "INACTIVE": '<span class="badge bg-secondary">Inactivo</span>',
            "ARCHIVED": '<span class="badge bg-warning">Archivado</span>'
        }[period.status];

        tr.innerHTML = `
            <td>${period.name}</td>
            <td>${formatDate(period.start_date)}</td>
            <td>${formatDate(period.end_date)}</td>
            <td>${formatDateTime(period.student_admission_deadline)}</td>
            <td>${statusBadge}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="editPeriod(${period.id})">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn btn-sm btn-outline-info" onclick="configureDays(${period.id})">
                    <i class="fas fa-calendar-day"></i> Días
                </button>
            </td>
        `;

        tbody.appendChild(tr);
    });
}

function openPeriodModal(period = null) {
    const modal = new bootstrap.Modal(document.getElementById("periodModal"));
    const title = document.getElementById("periodModalTitle");
    const form = document.getElementById("periodForm");

    form.reset();

    if (period) {
        title.textContent = "Editar Periodo";
        document.getElementById("periodId").value = period.id;
        document.getElementById("periodName").value = period.name;
        document.getElementById("startDate").value = period.start_date;
        document.getElementById("endDate").value = period.end_date;
        document.getElementById("admissionDeadline").value = period.student_admission_deadline.slice(0, 16);
        document.getElementById("periodStatus").value = period.status;
    } else {
        title.textContent = "Nuevo Periodo";
        document.getElementById("periodId").value = "";
    }

    modal.show();
}

async function savePeriod() {
    const periodId = document.getElementById("periodId").value;
    const data = {
        name: document.getElementById("periodName").value,
        start_date: document.getElementById("startDate").value,
        end_date: document.getElementById("endDate").value,
        student_admission_deadline: document.getElementById("admissionDeadline").value,
        status: document.getElementById("periodStatus").value
    };

    const url = periodId
        ? `/api/agendatec/v1/admin/periods/${periodId}`
        : "/api/agendatec/v1/admin/periods";

    const method = periodId ? "PATCH" : "POST";

    try {
        const response = await fetch(url, {
            method,
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${getToken()}`
            },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || "Failed to save period");
        }

        alert("Periodo guardado exitosamente");
        bootstrap.Modal.getInstance(document.getElementById("periodModal")).hide();
        await loadPeriods();
    } catch (error) {
        console.error(error);
        alert(`Error: ${error.message}`);
    }
}

async function editPeriod(periodId) {
    try {
        const response = await fetch(`/api/agendatec/v1/admin/periods`, {
            headers: { "Authorization": `Bearer ${getToken()}` }
        });
        const periods = await response.json();
        const period = periods.find(p => p.id === periodId);

        if (period) {
            openPeriodModal(period);
        }
    } catch (error) {
        console.error(error);
    }
}

function configureDays(periodId) {
    window.location.href = `/agendatec/admin/periods/${periodId}/days`;
}

function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString("es-MX");
}

function formatDateTime(dateTimeStr) {
    return new Date(dateTimeStr).toLocaleString("es-MX");
}

function getToken() {
    return localStorage.getItem("jwt_token");
}
```

**3. Template: Configuración de Días** (`itcj/apps/agendatec/templates/agendatec/admin/period_days.html`)

```html
{% extends "agendatec/base.html" %}

{% block title %}Configurar Días Habilitados{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="mb-4">
        <a href="{{ url_for('agendatec_admin_pages.periods') }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver a Periodos
        </a>
    </div>

    <h2>Configurar Días Habilitados</h2>
    <p class="text-muted">Periodo: <strong id="periodName"></strong></p>

    <div class="card mb-4">
        <div class="card-body">
            <h5>Selecciona los días en que los estudiantes pueden crear solicitudes:</h5>
            <div id="calendar"></div>
        </div>
    </div>

    <div class="mb-3">
        <h6>Días seleccionados:</h6>
        <div id="selectedDays" class="d-flex flex-wrap gap-2"></div>
    </div>

    <button class="btn btn-primary btn-lg" id="btnSaveDays">
        <i class="fas fa-save"></i> Guardar Configuración
    </button>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<script src="{{ url_for('agendatec.static', filename='js/admin/period_days.js') }}"></script>
{% endblock %}
```

**4. JavaScript: Configuración de Días** (`itcj/apps/agendatec/static/js/admin/period_days.js`)

```javascript
let selectedDays = [];
let period = null;
const periodId = window.location.pathname.split("/").slice(-2)[0];

document.addEventListener("DOMContentLoaded", async () => {
    await loadPeriod();
    await loadEnabledDays();
    initCalendar();

    document.getElementById("btnSaveDays").addEventListener("click", saveDays);
});

async function loadPeriod() {
    try {
        const response = await fetch("/api/agendatec/v1/admin/periods", {
            headers: { "Authorization": `Bearer ${getToken()}` }
        });
        const periods = await response.json();
        period = periods.find(p => p.id == periodId);

        if (period) {
            document.getElementById("periodName").textContent = period.name;
        }
    } catch (error) {
        console.error(error);
    }
}

async function loadEnabledDays() {
    try {
        const response = await fetch(`/api/agendatec/v1/admin/periods/${periodId}/enabled-days`, {
            headers: { "Authorization": `Bearer ${getToken()}` }
        });

        const enabledDays = await response.json();
        selectedDays = enabledDays.map(ed => ed.day);
        renderSelectedDays();
    } catch (error) {
        console.error(error);
    }
}

function initCalendar() {
    const calendar = flatpickr("#calendar", {
        inline: true,
        mode: "multiple",
        dateFormat: "Y-m-d",
        minDate: period.start_date,
        maxDate: period.end_date,
        defaultDate: selectedDays,
        onChange: (selectedDates) => {
            selectedDays = selectedDates.map(d => d.toISOString().split("T")[0]);
            renderSelectedDays();
        }
    });
}

function renderSelectedDays() {
    const container = document.getElementById("selectedDays");
    container.innerHTML = "";

    if (selectedDays.length === 0) {
        container.innerHTML = '<span class="text-muted">Ningún día seleccionado</span>';
        return;
    }

    selectedDays.sort().forEach(day => {
        const badge = document.createElement("span");
        badge.className = "badge bg-primary";
        badge.textContent = formatDate(day);
        container.appendChild(badge);
    });
}

async function saveDays() {
    try {
        const response = await fetch(`/api/agendatec/v1/admin/periods/${periodId}/enabled-days`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${getToken()}`
            },
            body: JSON.stringify({ days: selectedDays })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error);
        }

        alert("Días habilitados guardados exitosamente");
    } catch (error) {
        console.error(error);
        alert(`Error: ${error.message}`);
    }
}

function formatDate(dateStr) {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("es-MX", {
        weekday: "short",
        day: "numeric",
        month: "short"
    });
}

function getToken() {
    return localStorage.getItem("jwt_token");
}
```

**5. Ruta de página** (`itcj/apps/agendatec/routes/pages/admin.py`)

Agregar rutas:
```python
@bp.route("/periods")
@jwt_required
def periods():
    # TODO: Verificar rol admin
    return render_template("agendatec/admin/periods.html")

@bp.route("/periods/<int:period_id>/days")
@jwt_required
def period_days(period_id):
    # TODO: Verificar rol admin
    return render_template("agendatec/admin/period_days.html")
```

**6. Actualizar navegación** en templates base para incluir link a Periodos.

---

### **FASE 6: Frontend - Actualizar Vista de Estudiantes**

#### Tareas:
1. Modificar `request.js` para obtener días habilitados dinámicamente
2. Actualizar templates para renderizar días dinámicamente
3. Manejar caso donde no hay periodo activo

#### Archivos a modificar:

**1. `itcj/apps/agendatec/static/js/student/request.js`**

```javascript
// ANTES:
const ALLOWED_DAYS = ["2025-08-25", "2025-08-26", "2025-08-27"];

// DESPUÉS:
let ALLOWED_DAYS = [];
let activePeriod = null;

document.addEventListener("DOMContentLoaded", async () => {
    // Cargar periodo activo y días habilitados
    await loadActivePeriod();

    if (!activePeriod || !activePeriod.is_window_open) {
        // Redirigir a página de "período cerrado"
        window.location.href = "/agendatec/student/close";
        return;
    }

    ALLOWED_DAYS = activePeriod.enabled_days;

    // Renderizar días dinámicamente
    renderAvailableDays();

    // Resto de la inicialización...
});

async function loadActivePeriod() {
    try {
        const response = await fetch("/api/agendatec/v1/admin/periods/active");

        if (!response.ok) {
            throw new Error("No active period");
        }

        activePeriod = await response.json();
    } catch (error) {
        console.error("Error loading active period:", error);
        activePeriod = null;
    }
}

function renderAvailableDays() {
    const container = document.querySelector(".day-buttons-container");
    container.innerHTML = "";

    ALLOWED_DAYS.forEach(dayStr => {
        const date = new Date(dayStr + "T00:00:00");
        const dayName = date.toLocaleDateString("es-MX", { day: "numeric", month: "short" });

        const button = document.createElement("button");
        button.className = "btn btn-outline-primary day-btn";
        button.dataset.day = dayStr;
        button.textContent = dayName;
        button.addEventListener("click", () => selectDay(dayStr));

        container.appendChild(button);
    });
}
```

**2. `itcj/apps/agendatec/templates/agendatec/student/new_request.html`**

Reemplazar botones hardcodeados:
```html
<!-- ANTES: -->
<div class="day-selection mb-4">
    <button class="btn btn-outline-primary day-btn" data-day="2025-08-25">25 Ago</button>
    <button class="btn btn-outline-primary day-btn" data-day="2025-08-26">26 Ago</button>
    <button class="btn btn-outline-primary day-btn" data-day="2025-08-27">27 Ago</button>
</div>

<!-- DESPUÉS: -->
<div class="day-selection mb-4">
    <div class="day-buttons-container">
        <!-- Renderizado dinámicamente con JS -->
    </div>
</div>
```

**3. Templates de Coordinador y Servicio Social**

Aplicar el mismo patrón en:
- `templates/agendatec/coord/slots.html`
- `templates/agendatec/coord/appointments.html`
- `templates/agendatec/social/home.html`

---

### **FASE 7: Migración y Limpieza**

#### Tareas:
1. Migrar datos existentes al nuevo sistema
2. Eliminar variables de entorno obsoletas
3. Actualizar documentación

#### Script de migración:

**`itcj/apps/agendatec/scripts/migrate_to_periods.py`**

```python
"""
Script para migrar solicitudes existentes al sistema de periodos.
"""
from itcj.core.extensions import db
from itcj.core.models import AcademicPeriod
from itcj.apps.agendatec.models import Request, PeriodEnabledDay
from datetime import date, datetime
from zoneinfo import ZoneInfo

def migrate():
    print("Iniciando migración a sistema de periodos...")

    # 1. Crear periodo Ago-Dic 2025 si no existe
    period = AcademicPeriod.query.filter_by(name="Ago-Dic 2025").first()

    if not period:
        print("Creando periodo 'Ago-Dic 2025'...")
        period = AcademicPeriod(
            name="Ago-Dic 2025",
            start_date=date(2025, 8, 1),
            end_date=date(2025, 12, 31),
            student_admission_deadline=datetime(
                2025, 8, 27, 18, 0, 0,
                tzinfo=ZoneInfo("America/Ciudad_Juarez")
            ),
            status="ACTIVE"
        )
        db.session.add(period)
        db.session.flush()

        # Agregar días habilitados
        for day in [date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)]:
            enabled_day = PeriodEnabledDay(period_id=period.id, day=day)
            db.session.add(enabled_day)

        db.session.commit()
        print(f"Periodo creado con ID: {period.id}")
    else:
        print(f"Periodo 'Ago-Dic 2025' ya existe (ID: {period.id})")

    # 2. Migrar solicitudes sin period_id
    requests_without_period = Request.query.filter(Request.period_id.is_(None)).all()

    if requests_without_period:
        print(f"Migrando {len(requests_without_period)} solicitudes...")

        for req in requests_without_period:
            req.period_id = period.id

        db.session.commit()
        print("Solicitudes migradas exitosamente")
    else:
        print("No hay solicitudes por migrar")

    print("Migración completada.")

if __name__ == "__main__":
    from itcj import create_app
    app = create_app()

    with app.app_context():
        migrate()
```

#### Limpieza de código:

Eliminar o comentar variables obsoletas:
1. En `.env`: `LAST_TIME_STUDENT_ADMIT` (mantener comentada para referencia)
2. En archivos Python: todas las líneas `ALLOWED_DAYS = {date(...)}` (reemplazadas por llamadas a servicio)

---

### **FASE 8: Testing y Validación**

#### Tareas:
1. Crear tests unitarios para servicios
2. Crear tests de integración para APIs
3. Testing manual de flujos completos

#### Tests a crear:

**1. `tests/unit/test_period_service.py`**
```python
import pytest
from itcj.core.services.period_service import PeriodService
from itcj.core.models import AcademicPeriod

def test_get_active_period(db_session):
    # Crear periodo activo
    period = AcademicPeriod(name="Test", status="ACTIVE", ...)
    db_session.add(period)
    db_session.commit()

    active = PeriodService.get_active_period()
    assert active.id == period.id

def test_only_one_active_period(db_session):
    # Crear dos periodos activos
    period1 = AcademicPeriod(name="Test 1", status="ACTIVE", ...)
    period2 = AcademicPeriod(name="Test 2", status="ACTIVE", ...)

    # activate_period debe desactivar el anterior
    PeriodService.activate_period(period2.id, user_id=1)

    db_session.refresh(period1)
    assert period1.status == "INACTIVE"
    assert period2.status == "ACTIVE"
```

**2. `tests/integration/test_periods_api.py`**
```python
def test_create_period(client, admin_token):
    response = client.post(
        "/api/agendatec/v1/admin/periods",
        json={
            "name": "Ene-Jun 2026",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "student_admission_deadline": "2026-01-15T18:00:00",
            "status": "INACTIVE"
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 201
    data = response.json
    assert data["name"] == "Ene-Jun 2026"
```

#### Checklist de testing manual:

- [ ] Crear nuevo periodo desde admin
- [ ] Activar periodo (verificar que desactiva el anterior)
- [ ] Configurar días habilitados
- [ ] Verificar que estudiantes ven los días correctos
- [ ] Crear solicitud en nuevo periodo
- [ ] Verificar restricción "una por periodo"
- [ ] Intentar cancelar después de cierre de periodo (debe fallar)
- [ ] Intentar cancelar después de fecha de cita (debe fallar)
- [ ] Cambiar a nuevo periodo y verificar que se puede crear nueva solicitud

---

## 4. Sugerencias de Mejoras Adicionales

### 4.1 Sistema de Notificaciones Mejorado

**Problema identificado:** Las notificaciones solo funcionan en tiempo real vía WebSocket. Si un usuario no está conectado, no recibe la notificación.

**Propuesta:**
1. Persistir notificaciones en base de datos (tabla ya existe: `core_notifications`)
2. Mostrar badge con contador de notificaciones sin leer
3. Pantalla de historial de notificaciones
4. Enviar emails para eventos críticos (cita agendada, cancelada, etc.)

**Impacto:** Alta - Mejora significativa en la experiencia del usuario

---

### 4.2 Reportes y Analíticas por Periodo

**Problema identificado:** Los reportes actuales no filtran por periodo académico.

**Propuesta:**
1. Agregar filtro de periodo en todas las estadísticas
2. Reporte comparativo entre periodos:
   - Total de solicitudes por tipo
   - Tasa de asistencia (DONE vs NO_SHOW)
   - Coordinadores más solicitados
   - Programas con más demanda
3. Exportar reportes históricos por periodo

**Impacto:** Media - Útil para toma de decisiones

---

### 4.3 Validación de Horarios Realistas

**Problema identificado:** No hay validación de que los slots sean en horarios laborales.

**Propuesta:**
1. Agregar configuración de "horario laboral" (ej: 8:00 - 18:00)
2. Validar que los coordinadores no creen slots fuera de este rango
3. Validar que no haya traslapes de slots del mismo coordinador

**Impacto:** Baja - Mejora la calidad de datos

---

### 4.4 Sistema de Recordatorios

**Problema identificado:** Los estudiantes pueden olvidar su cita.

**Propuesta:**
1. Enviar email recordatorio 24 horas antes de la cita
2. Enviar email recordatorio 1 hora antes de la cita
3. Notificación in-app el día de la cita

**Impacto:** Alta - Reduce NO_SHOW

---

### 4.5 Historial de Solicitudes del Estudiante

**Problema identificado:** Los estudiantes solo ven su solicitud actual.

**Propuesta:**
1. Pantalla "Mis solicitudes históricas"
2. Filtrar por periodo
3. Ver detalles completos (comentarios del coordinador, fecha de resolución, etc.)
4. Descargar comprobante de asistencia (PDF)

**Impacto:** Media - Mejor experiencia y transparencia

---

### 4.6 Logs de Auditoría Completos

**Problema identificado:** `audit_log` existe pero no se usa consistentemente.

**Propuesta:**
1. Registrar TODOS los cambios de estado en `audit_log`
2. Pantalla de auditoría para admins con filtros avanzados
3. Trazabilidad completa: quién, qué, cuándo, por qué

**Impacto:** Media - Importante para compliance y debugging

---

### 4.7 Encuestas de Satisfacción Automáticas

**Problema identificado:** Las encuestas se envían manualmente por campaña.

**Propuesta:**
1. Enviar encuesta automáticamente 24 horas después de una cita completada (status=DONE)
2. Trackear tasa de respuesta
3. Dashboard de resultados de encuestas por coordinador/programa

**Impacto:** Media - Feedback continuo para mejora

---

### 4.8 Configuración de Duración de Slots por Coordinador

**Problema identificado:** Todos los slots duran 10 minutos (hardcodeado en `AvailabilityWindow.slot_minutes`).

**Propuesta:**
1. Permitir que cada coordinador configure su duración preferida (5, 10, 15, 20 minutos)
2. Aplicar al crear ventanas de disponibilidad
3. Validar que la duración sea divisor del rango de tiempo

**Impacto:** Baja - Flexibilidad para diferentes tipos de citas

---

### 4.9 Límite de Cancelaciones

**Problema identificado:** Un estudiante podría abusar cancelando/reagendando múltiples veces.

**Propuesta:**
1. Agregar campo `cancellation_count` a `Request`
2. Configurar límite máximo de cancelaciones por periodo (ej: 2)
3. Después del límite, el estudiante no puede cancelar (debe contactar a admin)

**Impacto:** Baja - Prevención de abuso

---

### 4.10 Dashboard de Coordinador Mejorado

**Problema identificado:** El dashboard actual es básico.

**Propuesta:**
1. Gráfico de citas por día (últimos 7 días)
2. Lista de próximas citas con countdown
3. Alertas de slots sin usar (días con baja ocupación)
4. Estadísticas personales (total atendido, promedio diario, etc.)

**Impacto:** Media - Mejor visibilidad para coordinadores

---

## 5. Consideraciones Técnicas

### 5.1 Migraciones de Base de Datos

**Estrategia:**
1. Aplicar migraciones en desarrollo primero
2. Crear backup completo de producción antes de migrar
3. Ejecutar script de migración de datos (`migrate_to_periods.py`)
4. Validar integridad de datos post-migración
5. Solo entonces aplicar en producción

**Rollback plan:**
- Mantener backup de BD
- Documentar queries para revertir cambios si es necesario

---

### 5.2 Timezone Awareness

**Importante:** La aplicación usa `America/Ciudad_Juarez` (UTC-7).

Todas las fechas/horas con timezone deben:
- Almacenarse en BD con timezone (`DateTime(timezone=True)`)
- Parsearse en Python con `zoneinfo.ZoneInfo`
- Mostrarse en frontend con conversión a hora local

**Ejemplo:**
```python
from zoneinfo import ZoneInfo
from datetime import datetime

tz = ZoneInfo("America/Ciudad_Juarez")
now = datetime.now(tz)
```

---

### 5.3 Índices de Base de Datos

Crear índices para consultas frecuentes:
```sql
CREATE INDEX idx_request_period_student ON agendatec_requests(period_id, student_id);
CREATE INDEX idx_request_period_status ON agendatec_requests(period_id, status);
CREATE INDEX idx_period_status ON core_academic_periods(status);
CREATE INDEX idx_enabled_days_period ON agendatec_period_enabled_days(period_id);
```

---

### 5.4 Testing en Desarrollo

Crear fixture de periodos para testing:
```python
# tests/fixtures/periods.py

@pytest.fixture
def active_period(db_session):
    period = AcademicPeriod(
        name="Test Period",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=90),
        student_admission_deadline=datetime.now(tz) + timedelta(days=7),
        status="ACTIVE"
    )
    db_session.add(period)
    db_session.commit()
    return period
```

---

### 5.5 Variables de Entorno

Mantener `.env` limpio, pero documentar:
```env
# DEPRECATED - Ahora controlado por AcademicPeriod
# LAST_TIME_STUDENT_ADMIT='2025-08-27 18:00:00'

# Redis para holds de slots
REDIS_URL=redis://redis:6379/0
SLOT_HOLD_SECONDS=60

# Timezone de la aplicación
TZ=America/Ciudad_Juarez
```

---

### 5.6 Documentación

Actualizar `README.md` de agendatec con:
1. Nuevo flujo de configuración de periodos
2. Guía de uso para administradores
3. FAQ sobre periodos académicos
4. Diagramas de flujo actualizados

---

## Resumen de Archivos a Crear/Modificar

### Archivos a CREAR (31):

**Modelos:**
1. `itcj/core/models/academic_period.py`
2. `itcj/apps/agendatec/models/period_enabled_day.py`

**Servicios:**
3. `itcj/core/services/period_service.py`
4. `itcj/apps/agendatec/utils/decorators.py`

**APIs:**
5. `itcj/apps/agendatec/routes/api/periods.py`

**Templates:**
6. `itcj/apps/agendatec/templates/agendatec/admin/periods.html`
7. `itcj/apps/agendatec/templates/agendatec/admin/period_days.html`

**JavaScript:**
8. `itcj/apps/agendatec/static/js/admin/periods.js`
9. `itcj/apps/agendatec/static/js/admin/period_days.js`

**Scripts:**
10. `itcj/apps/agendatec/scripts/seed_initial_period.py`
11. `itcj/apps/agendatec/scripts/migrate_to_periods.py`

**Tests:**
12. `tests/unit/test_period_service.py`
13. `tests/unit/test_academic_period_model.py`
14. `tests/integration/test_periods_api.py`
15. `tests/integration/test_request_with_periods.py`
16. `tests/fixtures/periods.py`

**Migraciones:**
17-19. Archivos de migración Alembic (generados)

### Archivos a MODIFICAR (20):

**Modelos:**
1. `itcj/core/models/__init__.py` - Importar AcademicPeriod
2. `itcj/apps/agendatec/models/__init__.py` - Importar PeriodEnabledDay
3. `itcj/apps/agendatec/models/request.py` - Agregar period_id

**APIs:**
4. `itcj/apps/agendatec/routes/api/requests.py` - Usar PeriodService
5. `itcj/apps/agendatec/routes/api/slots.py` - Usar PeriodService
6. `itcj/apps/agendatec/routes/api/availability.py` - Usar PeriodService
7. `itcj/apps/agendatec/routes/api/coord.py` - Usar PeriodService

**Rutas de Páginas:**
8. `itcj/apps/agendatec/routes/pages/admin.py` - Agregar rutas de periodos

**JavaScript:**
9. `itcj/apps/agendatec/static/js/student/request.js` - Días dinámicos
10. `itcj/apps/agendatec/static/js/admin/home.js` - Remover fecha hardcodeada

**Templates:**
11. `itcj/apps/agendatec/templates/agendatec/student/new_request.html` - Días dinámicos
12. `itcj/apps/agendatec/templates/agendatec/coord/slots.html` - Días dinámicos
13. `itcj/apps/agendatec/templates/agendatec/coord/appointments.html` - Días dinámicos
14. `itcj/apps/agendatec/templates/agendatec/social/home.html` - Días dinámicos
15. `itcj/apps/agendatec/templates/agendatec/base.html` - Agregar link a Periodos en nav

**Configuración:**
16. `itcj/apps/agendatec/__init__.py` - Registrar blueprint de periods
17. `.env` - Documentar variable obsoleta

**Documentación:**
18. `itcj/apps/agendatec/README.md` - Actualizar con nuevo flujo
19. `CHANGELOG.md` - Documentar cambios mayores

---

## Cronograma Estimado

| Fase | Descripción | Archivos | Complejidad |
|------|-------------|----------|-------------|
| 1 | Preparación de BD | 6 | Alta |
| 2 | Servicios Backend | 3 | Media |
| 3 | APIs Admin | 2 | Media |
| 4 | Validaciones Backend | 4 | Alta |
| 5 | Frontend Admin | 5 | Media |
| 6 | Frontend Estudiante | 6 | Media |
| 7 | Migración y Limpieza | 3 | Media |
| 8 | Testing y Validación | 7 | Alta |

---

## Próximos Pasos Recomendados

1. **Revisar y aprobar este plan** con el equipo
2. **Crear backup de la base de datos** antes de comenzar
3. **Implementar Fase 1** (modelos y migraciones) en desarrollo
4. **Validar** que las migraciones funcionan correctamente
5. **Proceder con Fases 2-4** (backend completo)
 7. **Implementar Fases 5-6** (frontend)
8. **Testing manual** de flujos completos
9. **Aplicar en producción** con plan de rollback listo

---

## Notas Finales

Este plan cubre:
- ✅ Sistema de periodos académicos con un periodo activo a la vez
- ✅ Configuración dinámica de días habilitados por periodo
- ✅ Restricción de "una solicitud por estudiante por periodo"
- ✅ Validaciones de cancelación mejoradas
- ✅ Eliminación de todas las fechas hardcodeadas
- ✅ Pantallas administrativas completas
- ✅ Sugerencias de mejoras adicionales

**Puntos críticos de atención:**
1. Migración de datos existentes sin pérdida de información
2. Manejo correcto de timezones
3. Validación estricta de "solo un periodo activo"
4. Testing exhaustivo antes de producción

**Contacto para dudas:**
- Revisar documentación en `itcj/apps/agendatec/README.md`
- Consultar modelos en `itcj/core/models/` y `itcj/apps/agendatec/models/`

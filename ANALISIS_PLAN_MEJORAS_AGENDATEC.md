# Análisis y Plan de Mejoras - AgendaTec

> **Fecha de análisis:** 15 de enero de 2026  
> **Objetivo:** Preparar la aplicación AgendaTec para producción con código optimizado, mantenible y siguiendo mejores prácticas.

---

## 📊 Resumen del Análisis

### Estructura Actual
```
itcj/apps/agendatec/
├── __init__.py           (184 líneas) - Blueprint principal y navegación
├── addStudents.py        (223 líneas) - Script de importación de alumnos
├── commands.py           (221 líneas) - Comandos CLI de Flask
├── config/               - Configuración (vacía excepto __init__.py)
├── models/               - 8 modelos SQLAlchemy
├── routes/
│   ├── api/              - 10 blueprints de API
│   └── pages/            - 5 blueprints de páginas
├── services/             - Lógica de negocio
├── static/               - Archivos estáticos
├── templates/            - Templates Jinja2
└── utils/                - Utilidades
```

### Métricas de Código
| Archivo | Líneas | Observación |
|---------|--------|-------------|
| `routes/api/admin.py` | **1,402** | ⚠️ Muy grande - debe dividirse |
| `routes/api/coord.py` | **972** | ⚠️ Grande - candidato a refactorizar |
| `routes/api/periods.py` | **598** | ⚠️ Moderado - evaluar división |
| `routes/api/requests.py` | **474** | Aceptable pero con oportunidades |
| `routes/api/availability.py` | **301** | Aceptable |
| `routes/api/slots.py` | **241** | ✅ Tamaño adecuado |

---

## 🎯 Plan de Mejoras

### Leyenda de Complejidad
- 🟢 **Fácil** (1-2 horas): Cambios de nomenclatura, documentación, pequeños refactors
- 🟡 **Media** (2-8 horas): División de archivos, extracción de funciones, nuevos módulos
- 🔴 **Alta** (8+ horas): Cambios arquitectónicos, refactorización profunda

---

## 🟢 Mejoras de Complejidad FÁCIL

### 1. Añadir Docstrings y Tipado Consistente
**Archivos afectados:** Todos los módulos  
**Impacto:** Mantenibilidad, documentación automática

**Problema actual:**
```python
# Función sin documentación ni tipos
def _current_coordinator_id():
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        return None
```

**Mejora propuesta:**
```python
def _current_coordinator_id() -> Optional[int]:
    """
    Obtiene el ID del coordinador asociado al usuario autenticado actual.
    
    Returns:
        El coordinator_id si el usuario es coordinador, None en caso contrario.
    """
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        return None
```

**Archivos prioritarios:**
- [ ] `routes/api/coord.py` - Funciones helper
- [ ] `routes/api/admin.py` - Todas las funciones helper
- [ ] `utils/utils.py` - Funciones de utilidad
- [ ] `utils/period_utils.py` - Ya tiene docstrings, verificar completitud

---

### 2. Eliminar Imports No Utilizados
**Archivos afectados:** Varios  
**Impacto:** Limpieza de código, reducción de dependencias innecesarias

**Ejemplos detectados:**
```python
# En routes/api/coord.py
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
# api_role_required no parece usarse

# En routes/api/admin.py  
import logging, os  # Formato no PEP8
from xlsxwriter import Workbook  # Se importa pero se usa pandas ExcelWriter
```

**Acciones:**
- [ ] Revisar y limpiar imports en `admin.py`
- [ ] Revisar y limpiar imports en `coord.py`
- [ ] Revisar y limpiar imports en `requests.py`
- [ ] Usar herramienta como `autoflake` o `isort` para automatizar

---

### 3. Estandarizar Formato de Imports (PEP8)
**Archivos afectados:** Todos  
**Impacto:** Consistencia, legibilidad

**Problema:**
```python
# Mezcla de estilos
import logging,os  # Sin espacios
from io import BytesIO

import pandas as pd  # Línea en blanco inconsistente
```

**Estándar a seguir:**
```python
# Librerías estándar
import logging
import os
from datetime import datetime, date
from io import BytesIO
from typing import Optional, Tuple

# Librerías de terceros
import pandas as pd
from flask import Blueprint, request, jsonify
from sqlalchemy import func, and_, or_

# Imports del proyecto
from itcj.apps.agendatec.models import db
from itcj.core.utils.decorators import api_auth_required
```

---

### 4. Constantes Mágicas a Archivo de Configuración
**Archivos afectados:** `routes/api/admin.py`, `routes/api/coord.py`  
**Impacto:** Mantenibilidad, configurabilidad

**Problema actual:**
```python
# En admin.py - Constantes dispersas
DEFAULT_PASSWORD = "tecno#2K"
ATTENDED_STATES = ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT")
EXCLUDE_STATES = ("CANCELED", "NO_SHOW", "PENDING")

# En coord.py - Duplicado
DEFAULT_NIP = "tecno#2K"
```

**Mejora propuesta:**  
Crear `config/constants.py`:
```python
"""Constantes de AgendaTec"""

# Estados de solicitudes
REQUEST_ATTENDED_STATES = frozenset({
    "RESOLVED_SUCCESS", 
    "RESOLVED_NOT_COMPLETED", 
    "ATTENDED_OTHER_SLOT"
})

REQUEST_EXCLUDE_STATES = frozenset({
    "CANCELED", 
    "NO_SHOW", 
    "PENDING"
})

# Configuración de usuarios
DEFAULT_STAFF_PASSWORD = "tecno#2K"

# Paginación
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Slots
VALID_SLOT_MINUTES = frozenset({5, 10, 15, 20, 30, 60})
```

---

### 5. Remover Código Comentado y TODOs Obsoletos
**Archivos afectados:** Varios  
**Impacto:** Limpieza

**Ejemplos:**
```python
# En routes/api/requests.py
# NOTA: ALLOWED_DAYS eliminado - ahora se obtiene dinámicamente del período activo
```

**Acción:** Revisar y eliminar comentarios obsoletos que ya no aportan contexto.

---

### 6. Estandarizar Nombres de Blueprints
**Archivos afectados:** `routes/pages/`, `routes/api/`  
**Impacto:** Consistencia

**Problema:**
```python
# Inconsistencia en naming
api_admin_bp = Blueprint("api_admin", __name__)  # Usa "api_" prefix
api_coord_bp = Blueprint("api_coord", __name__)  # Usa "api_" prefix
student_pages_bp = Blueprint("student_pages", __name__)  # Usa "_pages" suffix
admin_surveys_pages = Blueprint("admin_surveys_pages", __name__)  # Sin _bp
```

**Mejora:** Estandarizar a `{módulo}_{tipo}_bp`:
```python
admin_api_bp = Blueprint("admin_api", __name__)
admin_pages_bp = Blueprint("admin_pages", __name__)
admin_surveys_pages_bp = Blueprint("admin_surveys_pages", __name__)
```

---

### 7. Mejorar Manejo de Errores Consistente
**Archivos afectados:** Todos los endpoints API  
**Impacto:** UX, debugging

**Problema actual:** Inconsistencia en estructura de errores
```python
# Algunas veces
return jsonify({"error": "not_found"}), 404

# Otras veces
return jsonify({"error": "not_found", "message": "Usuario no encontrado"}), 404

# Otras veces
return jsonify({"error": "missing_fields", "required": required}), 400
```

**Mejora propuesta:** Crear helper en `utils/`:
```python
# utils/responses.py
def api_error(code: str, message: str = None, status: int = 400, **extra) -> tuple:
    """Genera respuesta de error estandarizada"""
    payload = {"error": code, "status": status}
    if message:
        payload["message"] = message
    payload.update(extra)
    return jsonify(payload), status

# Uso:
return api_error("not_found", "Usuario no encontrado", 404)
return api_error("missing_fields", "Campos requeridos faltantes", 400, required=["name", "email"])
```

---

## 🟡 Mejoras de Complejidad MEDIA

### 8. Dividir `routes/api/admin.py` (1,402 líneas)
**Impacto:** Mantenibilidad, testing, responsabilidad única

**División propuesta:**
```
routes/api/admin/
├── __init__.py              # Exporta blueprint consolidado
├── stats.py                 # stats_overview, stats_coordinators, stats_activity (~300 líneas)
├── requests.py              # CRUD de solicitudes (~200 líneas)
├── coordinators.py          # CRUD de coordinadores (~250 líneas)
├── students.py              # Listado de estudiantes (~100 líneas)
├── reports.py               # Generación de reportes XLSX (~200 líneas)
├── surveys.py               # Envío de encuestas (~150 líneas)
└── helpers.py               # Funciones auxiliares compartidas (~100 líneas)
```

**Pasos:**
1. [ ] Crear estructura de carpeta `routes/api/admin/`
2. [ ] Extraer helpers comunes a `helpers.py`
3. [ ] Mover endpoints de stats a `stats.py`
4. [ ] Mover endpoints de coordinadores a `coordinators.py`
5. [ ] Mover endpoints de reportes a `reports.py`
6. [ ] Mover endpoints de surveys a `surveys.py`
7. [ ] Actualizar imports en `__init__.py` principal

---

### 9. Dividir `routes/api/coord.py` (972 líneas)
**Impacto:** Mantenibilidad, testing

**División propuesta:**
```
routes/api/coord/
├── __init__.py              # Exporta blueprint consolidado
├── dashboard.py             # Dashboard y resumen (~100 líneas)
├── day_config.py            # Configuración de días (~200 líneas)
├── appointments.py          # Gestión de citas (~300 líneas)
├── drops.py                 # Gestión de bajas (~150 líneas)
├── password.py              # Cambio de contraseña (~50 líneas)
└── helpers.py               # _current_coordinator_id, _coord_program_ids, etc.
```

---

### 10. Extraer Lógica de Negocio a Services
**Archivos afectados:** `routes/api/requests.py`, `routes/api/coord.py`  
**Impacto:** Testabilidad, reutilización, separación de responsabilidades

**Problema actual:** Lógica de negocio mezclada con handlers de rutas
```python
# En requests.py - Lógica compleja dentro del endpoint
@api_req_bp.post("")
def create_request():
    # 100+ líneas de lógica de negocio
    ...
```

**Mejora propuesta:**  
Crear `services/request_service.py`:
```python
class RequestService:
    """Servicio para gestión de solicitudes"""
    
    def create_drop_request(self, student_id: int, program_id: int, 
                           period_id: int, description: str) -> Request:
        """Crea una solicitud de baja"""
        ...
    
    def create_appointment_request(self, student_id: int, program_id: int,
                                   period_id: int, slot_id: int, 
                                   description: str) -> tuple[Request, Appointment]:
        """Crea una solicitud de cita"""
        ...
    
    def cancel_request(self, request_id: int, user_id: int) -> bool:
        """Cancela una solicitud del usuario"""
        ...
    
    def validate_can_create_request(self, student_id: int, period_id: int) -> tuple[bool, str]:
        """Valida si un estudiante puede crear solicitud en el período"""
        ...
```

**Rutas simplificadas:**
```python
@api_req_bp.post("")
def create_request():
    service = RequestService()
    
    # Validación
    can_create, error_msg = service.validate_can_create_request(student_id, period_id)
    if not can_create:
        return api_error("validation_failed", error_msg, 409)
    
    # Creación delegada al servicio
    if req_type == "DROP":
        request = service.create_drop_request(...)
        return jsonify({"ok": True, "request_id": request.id})
```

---

### 11. Crear Schemas de Validación con Pydantic/Marshmallow
**Archivos afectados:** Todos los endpoints que reciben JSON  
**Impacto:** Validación robusta, documentación automática

**Problema actual:**
```python
# Validación manual dispersa y propensa a errores
data = request.get_json(silent=True) or {}
req_type = (data.get("type") or "").upper()
if req_type not in ("APPOINTMENT", "DROP"):
    return jsonify({"error": "invalid_type"}), 400
```

**Mejora propuesta:**  
Crear `schemas/requests.py`:
```python
from pydantic import BaseModel, Field, validator
from enum import Enum

class RequestType(str, Enum):
    DROP = "DROP"
    APPOINTMENT = "APPOINTMENT"

class CreateRequestSchema(BaseModel):
    type: RequestType
    program_id: int = Field(gt=0)
    description: str = Field(max_length=500)
    slot_id: int | None = None
    
    @validator('slot_id')
    def slot_required_for_appointment(cls, v, values):
        if values.get('type') == RequestType.APPOINTMENT and not v:
            raise ValueError('slot_id es requerido para citas')
        return v
```

---

### 12. Refactorizar Funciones Helper Duplicadas
**Archivos afectados:** `admin.py`, `coord.py`, `availability.py`  
**Impacto:** DRY, mantenibilidad

**Duplicaciones detectadas:**

| Función | Archivos | Acción |
|---------|----------|--------|
| `_current_coordinator_id()` | coord.py, availability.py | Mover a utils/auth.py |
| `_parse_dt()`, `_range_from_query()` | admin.py | Mover a utils/dates.py |
| `_paginate()` | admin.py | Mover a utils/pagination.py |
| `_coord_program_ids()` | coord.py | Mover a services/coordinator_service.py |

**Estructura propuesta:**
```
utils/
├── __init__.py
├── auth.py          # get_current_user_id, get_current_coordinator_id
├── dates.py         # parse_date, parse_datetime, get_date_range
├── pagination.py    # paginate_query, PaginationParams
├── responses.py     # api_error, api_success
└── period_utils.py  # (existente)
```

---

### 13. Mejorar `addStudents.py` - Script de Importación
**Impacto:** Mantenibilidad, robustez

**Problemas actuales:**
- Imports rotos (usa rutas absolutas incorrectas)
- No usa el contexto de Flask correctamente
- Debería ser un comando CLI de Flask

**Mejora propuesta:**  
Convertir a comando Flask en `commands.py`:
```python
@click.command('import-students')
@click.argument('csv_path', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Simular sin guardar')
@with_appcontext
def import_students_command(csv_path: str, dry_run: bool):
    """Importa estudiantes desde un archivo CSV"""
    ...
```

---

### 14. Añadir Logging Estructurado
**Archivos afectados:** Todos  
**Impacto:** Debugging, monitoreo en producción

**Problema actual:**
```python
current_app.logger.exception("Failed to broadcast slot_booked")
# Solo se loguea el error, sin contexto
```

**Mejora propuesta:**
```python
import structlog

logger = structlog.get_logger(__name__)

# En el código
logger.info("request_created", 
    request_id=r.id, 
    student_id=u.id, 
    type=req_type,
    period_id=period.id
)

logger.error("broadcast_failed", 
    event="slot_booked",
    slot_id=slot_id,
    exc_info=True
)
```

---

### 15. Tests Unitarios para Services
**Impacto:** Confiabilidad, facilitar refactorizaciones futuras

**Crear estructura de tests:**
```
tests/
└── apps/
    └── agendatec/
        ├── __init__.py
        ├── conftest.py           # Fixtures comunes
        ├── test_request_service.py
        ├── test_period_utils.py
        └── test_api/
            ├── test_requests.py
            ├── test_coord.py
            └── test_admin.py
```

**Prioridad:** Empezar con `period_utils.py` y validaciones de solicitudes.

---

## 🔴 Mejoras de Complejidad ALTA (Solo Documentar)

### 16. Migrar a API RESTful con Versionado
**Estado:** Solo documentar - No implementar ahora

**Descripción:**  
Implementar versionado de API (`/api/v1/agendatec/...`) con OpenAPI/Swagger para documentación automática.

**Beneficios:**
- Evolución de API sin romper clientes
- Documentación interactiva
- Generación automática de SDKs

**Estimación:** 40+ horas

---

### 17. Implementar CQRS para Reportes
**Estado:** Solo documentar - No implementar ahora

**Descripción:**  
Separar operaciones de lectura (queries) de escritura (commands) para mejorar rendimiento en reportes pesados.

**Beneficios:**
- Mejora de rendimiento en queries analíticas
- Mejor escalabilidad
- Posibilidad de usar bases de datos optimizadas para lectura

**Estimación:** 60+ horas

---

### 18. Cache Distribuido para Slots y Períodos
**Estado:** Solo documentar - No implementar ahora

**Descripción:**  
Implementar capa de cache con Redis para:
- Configuración de períodos activos
- Días habilitados
- Información de coordinadores por programa

**Beneficios:**
- Reducción de queries a base de datos
- Mejor tiempo de respuesta
- Menor carga en base de datos

**Estimación:** 20+ horas

---

### 19. Event Sourcing para Auditoría
**Estado:** Solo documentar - No implementar ahora

**Descripción:**  
Implementar event sourcing completo en lugar del AuditLog actual para tener historial completo y reproducible de todas las operaciones.

**Beneficios:**
- Historial completo de cambios
- Capacidad de "replay" de eventos
- Debugging avanzado

**Estimación:** 80+ horas

---

### 20. Migrar a Async (Flask-ASGI o FastAPI)
**Estado:** Solo documentar - No implementar ahora

**Descripción:**  
Migrar endpoints con I/O intensivo (notificaciones, emails) a procesamiento asíncrono.

**Beneficios:**
- Mejor manejo de concurrencia
- Tiempos de respuesta más rápidos
- Mejor uso de recursos

**Estimación:** 100+ horas (migración completa)

---

## 📋 Checklist de Implementación

### Fase 1: Limpieza Básica (Semana 1)

#### Subfase 1.1: Nuevos Módulos Base
- [x] **M4**: Crear `config/constants.py` ✅
- [x] **M7**: Crear `utils/responses.py` con helpers de error ✅

#### Subfase 1.2: Limpieza de Imports
- [x] **M2**: Limpiar imports no utilizados ✅
- [x] **M3**: Estandarizar formato de imports (PEP8) ✅

#### Subfase 1.3: Documentación
- [x] **M1**: Docstrings y tipado en helpers principales ✅
  - `routes/api/admin.py`: `_parse_dt`, `_range_from_query`, `_paginate`, `_add_query_params`, `_student_email_from_user`
  - `routes/api/coord.py`: `_current_user`, `_current_coordinator_id`, `_coord_program_ids`, `_split_or_delete_windows`
  - `routes/api/availability.py`: `_parse_day_query`, `_parse_day_body`, `_require_allowed_day`, `_current_coordinator_id`
  - `routes/api/requests.py`: `_get_current_student`

#### Subfase 1.4: Limpieza de Código
- [x] **M5**: Revisado - Comentarios NOTA son útiles para documentación, no obsoletos ✅

#### Subfase 1.5: Estandarización
- [x] **M6**: Estandarizar nombres de blueprints ✅
  - `admin_surveys_pages` → `admin_surveys_pages_bp`
  - Todos los demás ya usaban convención `*_bp`

### Fase 2: División de Archivos (Semana 2-3)
- [x] **M8**: Dividir `admin.py` en módulos ✅
  - Creado paquete `routes/api/admin/` con:
    - `__init__.py` - Blueprint principal
    - `helpers.py` - Funciones helper compartidas
    - `stats.py` - Endpoints de estadísticas
    - `requests.py` - Gestión de solicitudes
    - `users.py` - Coordinadores y estudiantes
    - `reports.py` - Generación de reportes XLSX
    - `surveys.py` - Envío de encuestas
- [x] **M9**: Dividir `coord.py` en módulos ✅
  - Creado paquete `routes/api/coord/` con:
    - `__init__.py` - Blueprint principal
    - `helpers.py` - Funciones helper compartidas
    - `dashboard.py` - Dashboard y coordinadores compartidos
    - `day_config.py` - Configuración de días y slots
    - `appointments.py` - Gestión de citas
    - `drops.py` - Gestión de bajas y estado de solicitudes
    - `password.py` - Cambio de contraseña
- [x] **M12**: Refactorizar helpers duplicados ✅
  - Helpers organizados en `admin/helpers.py` y `coord/helpers.py`
  - Funciones con nombres limpios (sin prefijo `_`) y docstrings completos

### Fase 3: Arquitectura (Semana 3-4)
- [ ] **M10**: Extraer lógica a `RequestService`
- [ ] **M11**: Implementar schemas con Pydantic
- [ ] **M13**: Refactorizar `addStudents.py`
- [ ] **M14**: Añadir logging estructurado

### Fase 4: Testing (Semana 4-5)
- [ ] **M15**: Tests unitarios para servicios críticos

---

## 📝 Notas Adicionales

### Archivos que NO Requieren Cambios Significativos
Los siguientes archivos están bien estructurados y solo requieren mejoras menores:
- `models/` - Modelos SQLAlchemy bien definidos
- `utils/period_utils.py` - Bien documentado y con tipos
- `routes/pages/` - Simples y con buena separación

### Dependencias a Considerar
Para implementar algunas mejoras se sugiere añadir:
```txt
# requirements.txt (adicionales)
pydantic>=2.0
structlog>=23.0
isort>=5.0
black>=23.0
```

### Comandos Útiles de Calidad de Código
```bash
# Ordenar imports
isort itcj/apps/agendatec/

# Formatear código
black itcj/apps/agendatec/

# Limpiar imports no usados
autoflake --in-place --remove-all-unused-imports -r itcj/apps/agendatec/

# Type checking
mypy itcj/apps/agendatec/
```

---

## 🎯 Prioridades Recomendadas para Producción

1. **CRÍTICO antes de producción:**
   - M4 (Constantes) - Evita hardcoding de contraseñas
   - M7 (Manejo de errores) - UX consistente

2. **IMPORTANTE para mantenibilidad:**
   - M8-M9 (División de archivos) - Facilita colaboración
   - M12 (Refactorizar helpers) - Reduce bugs por duplicación

3. **RECOMENDADO a corto plazo:**
   - M10 (Services) - Mejor testabilidad
   - M14 (Logging) - Debugging en producción

---

*Documento generado el 15 de enero de 2026*

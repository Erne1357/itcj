# Help-Desk - Sistema de Gestión de Tickets de Soporte

## Descripción General

**Help-Desk** es un sistema integral de soporte técnico y de desarrollo diseñado para el Instituto Tecnológico de Ciudad Juárez que permite gestionar solicitudes de asistencia técnica mediante un flujo estructurado de tickets. El sistema cubre tanto el área de **Desarrollo de Software** (mantenimiento de sistemas institucionales) como **Soporte Técnico** (hardware, red, infraestructura).

### Características Principales

- 🎫 **Gestión de Tickets**: Sistema completo con flujo de estados y asignaciones
- 👥 **Múltiples Roles**: Staff, Secretarias, Técnicos (Desarrollo/Soporte), Jefes de Departamento, Administradores
- 📊 **Métricas de SLA**: Seguimiento de Service Level Agreement con alertas de vencimiento
- 💻 **Inventario de Equipos**: Registro y gestión de activos tecnológicos institucionales
- ⭐ **Sistema de Calificaciones**: Encuestas de satisfacción con múltiples criterios
- 📎 **Adjuntos y Comentarios**: Comunicación interna y externa con historial completo
- 🔔 **Notificaciones en Tiempo Real**: WebSockets para actualizaciones instantáneas
- 👥 **Colaboradores**: Asignación de múltiples técnicos a un mismo ticket
- 📈 **Dashboard de Métricas**: Análisis de rendimiento, carga de trabajo y calidad del servicio

---

## Stack Tecnológico

### Backend
- **Framework**: Flask 3.1.1
- **Base de Datos**: PostgreSQL con SQLAlchemy 2.0
- **Migraciones**: Alembic 1.16.5

### Frontend
- **Templates**: Jinja2 con Bootstrap 5
- **JavaScript**: Vanilla JS con componentes modulares
- **Estilos**: CSS personalizado + Bootstrap utilities

### Tiempo Real
- **WebSockets**: Flask-SocketIO
- **Broker**: Redis (para escalabilidad)

### Almacenamiento de Archivos
- **Adjuntos**: Sistema local en `instance/apps/helpdesk/attachments/`
- **Límite de tamaño**: 3MB por archivo
- **Formatos permitidos**: jpg, jpeg, png, gif, webp

---

## Arquitectura de Help-Desk

### Estructura de Archivos

```
itcj/apps/helpdesk/
├── __init__.py                    # Blueprints principales y configuración
├── README.md                      # Este archivo
│
├── models/                        # Modelos de datos
│   ├── __init__.py
│   ├── ticket.py                  # Modelo principal de tickets
│   ├── category.py                # Categorías de clasificación
│   ├── assignment.py              # Asignaciones a técnicos
│   ├── comment.py                 # Comentarios en tickets
│   ├── attachment.py              # Archivos adjuntos
│   ├── status_log.py              # Historial de cambios de estado
│   ├── collaborator.py            # Colaboradores en tickets
│   ├── inventory_item.py          # Equipos institucionales
│   ├── inventory_category.py      # Categorías de equipos
│   ├── inventory_group.py         # Grupos (salones, labs)
│   ├── inventory_history.py       # Historial de cambios de inventario
│   └── ticket_inventory_item.py   # Relación tickets-equipos
│
├── routes/                        # Endpoints
│   ├── api/                       # API REST
│   │   ├── tickets/               # CRUD de tickets
│   │   │   ├── base.py
│   │   │   ├── collaborators.py
│   │   │   ├── comments.py
│   │   │   └── equipment.py
│   │   ├── assignments.py         # Gestión de asignaciones
│   │   ├── comments.py            # Comentarios
│   │   ├── attachments.py         # Subida de archivos
│   │   ├── categories.py          # Categorías
│   │   └── inventory/             # Gestión de inventario
│   │       ├── inventory_items.py
│   │       ├── inventory_categories.py
│   │       ├── inventory_groups.py
│   │       ├── inventory_assignments.py
│   │       ├── inventory_history.py
│   │       └── inventory_stats.py
│   │
│   └── pages/                     # Vistas HTML
│       ├── user.py                # Panel de usuario/staff
│       ├── secretary.py           # Panel de secretaria
│       ├── technician.py          # Panel de técnico
│       ├── department_head.py     # Panel de jefe de departamento
│       ├── inventory.py           # Gestión de inventario
│       └── admin.py               # Panel de administrador
│
├── services/                      # Lógica de negocio
│   ├── assignment_service.py      # Asignación inteligente
│   ├── attachment_cleanup.py      # Limpieza de archivos
│   ├── collaborator_service.py    # Gestión de colaboradores
│   ├── inventory_bulk_service.py  # Importación masiva
│   ├── inventory_group_service.py # Gestión de grupos
│   └── inventory_history_service.py # Auditoría de inventario
│
├── utils/                         # Utilidades
│   ├── navigation.py              # Menús dinámicos por rol
│   ├── time_calculator.py         # Cálculo de horas laborales
│   └── timezone_utils.py          # Manejo de zonas horarias
│
├── templates/helpdesk/            # Templates HTML
│   ├── home_landing.html          # Landing page
│   ├── user/                      # Vistas de usuario
│   ├── secretary/                 # Vistas de secretaria
│   ├── technician/                # Vistas de técnico
│   ├── department/                # Vistas de jefe de dpto
│   ├── inventory/                 # Vistas de inventario
│   ├── admin/                     # Vistas de admin
│   └── components/                # Componentes reutilizables
│
├── static/                        # Assets estáticos
│   ├── css/helpdesk/              # Estilos
│   ├── js/helpdesk/               # JavaScript
│   └── images/helpdesk/           # Imágenes
│
└── commands.py                    # Comandos Flask personalizados
```

---

## Sistema de Roles y Permisos

### Roles Disponibles

#### 1. **Staff** (Personal General)
**Permisos**:
- ✅ Crear tickets para sí mismo
- ✅ Ver sus propios tickets
- ✅ Agregar comentarios a sus tickets
- ✅ Subir adjuntos (evidencias)
- ✅ Calificar tickets resueltos
- ✅ Cancelar sus propios tickets (solo si están en PENDING)

**Flujo típico**:
```
1. Acceder a /help-desk/user/create
2. Llenar formulario (área, categoría, prioridad, descripción)
3. Esperar asignación de técnico
4. Seguimiento del ticket
5. Calificar cuando esté resuelto
```

---

#### 2. **Secretary** (Secretaria)
**Permisos**:
- ✅ Crear tickets en nombre de otros usuarios
- ✅ Seleccionar el solicitante real del ticket
- ✅ Ver tickets del departamento
- ✅ Agregar comentarios
- ❌ No puede asignar o cambiar estados

**Casos de uso**:
- Usuario sin acceso al sistema solicita soporte presencialmente
- Reportar problemas de manera centralizada por departamento

**Flujo típico**:
```
1. Acceder a /help-desk/user/create
2. Seleccionar usuario solicitante (autocomplete)
3. Llenar formulario en nombre del usuario
4. El ticket aparece como creado por la secretaria pero solicitado por el usuario
```

---

#### 3. **Tech_Desarrollo** (Técnico de Desarrollo)
**Permisos**:
- ✅ Ver todos los tickets de área DESARROLLO
- ✅ Aceptar asignaciones
- ✅ Cambiar estado de tickets asignados (IN_PROGRESS, RESOLVED)
- ✅ Agregar comentarios internos y externos
- ✅ Registrar tiempo invertido
- ✅ Agregar colaboradores
- ✅ Vincular equipos de inventario

**Responsabilidades**:
- Mantenimiento de sistemas: SII, SIILE, SIISAE, AgendaTec, Help-Desk, Moodle
- Desarrollo de nuevas funcionalidades
- Corrección de bugs
- Soporte de bases de datos

**Flujo típico**:
```
1. Acceder a /help-desk/technician
2. Ver dashboard con tickets pendientes (ASSIGNED)
3. Iniciar trabajo (cambiar a IN_PROGRESS)
4. Documentar solución en comentarios
5. Registrar tiempo invertido
6. Resolver (RESOLVED_SUCCESS o RESOLVED_FAILED)
```

---

#### 4. **Tech_Soporte** (Técnico de Soporte)
**Permisos**:
- ✅ Ver todos los tickets de área SOPORTE
- ✅ Aceptar asignaciones
- ✅ Cambiar estado de tickets asignados
- ✅ Gestión de inventario (ver equipos asignados)
- ✅ Vincular equipos a tickets
- ✅ Registrar mantenimientos

**Responsabilidades**:
- Soporte de hardware (computadoras, impresoras)
- Problemas de red y cableado
- Instalación de software
- Mantenimiento preventivo y correctivo
- Proyectores y equipos audiovisuales

**Flujo típico**:
```
1. Recibir asignación de ticket de soporte
2. Revisar equipo vinculado (si aplica)
3. Realizar diagnóstico y solución
4. Actualizar estado del equipo en inventario (si está dañado)
5. Documentar solución
6. Registrar tiempo y resolver
```

---

#### 5. **Department_Head** (Jefe de Departamento)
**Permisos**:
- ✅ Ver todos los tickets de su departamento
- ✅ Crear tickets para su departamento
- ✅ **Gestión de inventario**:
  - Ver equipos del departamento
  - Asignar equipos a usuarios
  - Crear grupos (salones, laboratorios)
  - Asignar equipos a grupos
  - Ver reportes de inventario
- ✅ Ver métricas y estadísticas del departamento

**Responsabilidades**:
- Supervisión de tickets del departamento
- Asignación estratégica de equipos
- Planificación de mantenimientos
- Reportes de satisfacción

**Flujo típico**:
```
1. Acceder a /help-desk/department
2. Ver dashboard de tickets del departamento
3. Gestionar inventario:
   - Ver equipos pendientes de asignación
   - Asignar computadoras a empleados
   - Crear grupo "Lab-Computo-1" y asignar 30 PCs
4. Monitorear métricas de SLA
```

---

#### 6. **Admin** (Administrador)
**Permisos**:
- ✅ Acceso completo a todos los tickets
- ✅ Asignar tickets manualmente a cualquier técnico
- ✅ Cambiar cualquier estado
- ✅ **Gestión de categorías**:
  - Crear/editar/eliminar categorías
  - Configurar orden de visualización
- ✅ **Gestión de inventario global**:
  - Registrar nuevos equipos
  - Ver inventario completo institucional
  - Gestionar categorías de inventario
  - Ver historial completo de cambios
- ✅ Ver métricas globales y reportes
- ✅ Configuración del sistema

**Responsabilidades**:
- Administración de usuarios y roles
- Configuración de categorías de tickets
- Registro de equipos nuevos
- Análisis de métricas institucionales
- Soporte de segundo nivel

---

### Matriz de Permisos

| Permiso | Staff | Secretary | Tech_Des | Tech_Sop | Dept_Head | Admin |
|---------|-------|-----------|----------|----------|-----------|-------|
| Crear ticket (propio) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Crear ticket (otros) | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Ver todos los tickets | ❌ | ❌ | ⚠️ Área | ⚠️ Área | ⚠️ Dpto | ✅ |
| Asignar tickets | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Cambiar estado | ❌ | ❌ | ⚠️ Propios | ⚠️ Propios | ❌ | ✅ |
| Comentarios externos | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Comentarios internos | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Ver inventario | ❌ | ❌ | ⚠️ Necesario | ⚠️ Necesario | ⚠️ Dpto | ✅ |
| Asignar inventario | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Registrar inventario | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Gestionar categorías | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Ver métricas globales | ❌ | ❌ | ⚠️ Propias | ⚠️ Propias | ⚠️ Dpto | ✅ |

**Leyenda**:
- ✅ Permitido completamente
- ❌ No permitido
- ⚠️ Permitido con restricciones

---

## Flujo de Estados de Tickets

### Diagrama de Estados

```
┌──────────┐
│ PENDING  │ ← Ticket recién creado
└────┬─────┘
     │
     │ Admin/Sistema asigna a técnico
     ↓
┌──────────┐
│ ASSIGNED │ ← Asignado a técnico/equipo
└────┬─────┘
     │
     │ Técnico acepta y comienza trabajo
     ↓
┌──────────────┐
│ IN_PROGRESS  │ ← Técnico trabajando activamente
└────┬─────────┘
     │
     │ Técnico completa trabajo
     ↓
┌─────────────────────┐
│ RESOLVED_SUCCESS    │ ← Resuelto exitosamente
│ o                   │
│ RESOLVED_FAILED     │ ← Atendido pero no resuelto
└────┬────────────────┘
     │
     │ Usuario califica (opcional)
     ↓
┌──────────┐
│ CLOSED   │ ← Ticket cerrado
└──────────┘

     En cualquier momento:
┌──────────┐
│ CANCELED │ ← Usuario cancela (solo en PENDING)
└──────────┘
```

### Descripción de Estados

#### 1. **PENDING** (Pendiente)
- **Descripción**: Ticket recién creado, esperando asignación
- **Quién lo activa**: Sistema automáticamente al crear el ticket
- **Acciones permitidas**:
  - Admin puede asignar manualmente
  - Usuario puede cancelar
  - Se pueden agregar comentarios
- **SLA**: Comienza a contar desde este momento

#### 2. **ASSIGNED** (Asignado)
- **Descripción**: Ticket asignado a un técnico o equipo específico
- **Quién lo activa**: Admin o sistema de asignación automática
- **Acciones permitidas**:
  - Técnico puede iniciar trabajo (cambiar a IN_PROGRESS)
  - Técnico puede rechazar asignación
  - Admin puede reasignar
- **Notificación**: Se notifica al técnico asignado

#### 3. **IN_PROGRESS** (En Progreso)
- **Descripción**: Técnico trabajando activamente en la solución
- **Quién lo activa**: Técnico asignado
- **Acciones permitidas**:
  - Técnico agrega comentarios de progreso
  - Técnico puede agregar colaboradores
  - Técnico puede vincular equipos
  - Técnico registra tiempo invertido
  - Técnico puede resolver
- **Visibilidad**: Usuario puede ver actualizaciones en tiempo real

#### 4. **RESOLVED_SUCCESS** (Resuelto Exitosamente)
- **Descripción**: Problema solucionado satisfactoriamente
- **Quién lo activa**: Técnico al completar el trabajo
- **Campos requeridos**:
  - `resolution_notes`: Descripción de la solución
  - `time_invested_minutes`: Tiempo real invertido
- **Acciones siguientes**:
  - Sistema solicita calificación al usuario
  - Ticket queda disponible para cerrar
- **SLA**: Se detiene el contador

#### 5. **RESOLVED_FAILED** (Atendido pero No Resuelto)
- **Descripción**: Se intentó solucionar pero no fue posible
- **Quién lo activa**: Técnico
- **Casos de uso**:
  - Requiere autorización externa
  - Problema fuera del alcance
  - Necesita repuesto no disponible
  - Requiere proveedor externo
- **Campos requeridos**:
  - `resolution_notes`: Explicación detallada del motivo
- **SLA**: Se marca como resuelto en SLA pero con flag de no exitoso

#### 6. **CLOSED** (Cerrado)
- **Descripción**: Ticket completamente cerrado
- **Quién lo activa**: Sistema automáticamente o Admin
- **Condiciones**:
  - Debe estar en RESOLVED_SUCCESS o RESOLVED_FAILED
  - Usuario idealmente ya calificó (opcional)
- **Acciones**: No se pueden hacer más cambios (solo Admin puede reabrir)

#### 7. **CANCELED** (Cancelado)
- **Descripción**: Usuario cancela la solicitud
- **Quién lo activa**: Usuario solicitante o Admin
- **Restricciones**: Solo permitido si el ticket está en PENDING
- **No cuenta para métricas**: No afecta SLA ni estadísticas de técnicos

---

### Transiciones de Estado Válidas

| Estado Actual | Puede cambiar a | Quién puede |
|---------------|-----------------|-------------|
| PENDING | ASSIGNED | Admin, Sistema |
| PENDING | CANCELED | Usuario, Admin |
| ASSIGNED | IN_PROGRESS | Técnico |
| ASSIGNED | PENDING | Admin (reasignar) |
| IN_PROGRESS | RESOLVED_SUCCESS | Técnico |
| IN_PROGRESS | RESOLVED_FAILED | Técnico |
| RESOLVED_* | CLOSED | Sistema, Admin |
| CLOSED | IN_PROGRESS | Admin (reabrir) |

---

## Gestión de Inventario

### Conceptos Principales

El módulo de inventario gestiona los activos tecnológicos institucionales (computadoras, impresoras, proyectores, etc.) y su relación con tickets de soporte.

#### Entidades Principales

1. **InventoryItem** (Equipo individual)
2. **InventoryCategory** (Categoría de equipo)
3. **InventoryGroup** (Grupo/Salón/Laboratorio)
4. **InventoryHistory** (Historial de cambios)

---

### Categorías de Inventario

Ejemplos de categorías predefinidas:

| Código | Nombre | Icono | Descripción |
|--------|--------|-------|-------------|
| `comp` | Computadora | 💻 | Desktop, laptop, all-in-one |
| `imp` | Impresora | 🖨️ | Láser, inyección, multifuncional |
| `proy` | Proyector | 📽️ | Proyectores multimedia |
| `red` | Equipo de Red | 🌐 | Switches, routers, APs |
| `tel` | Teléfono | 📞 | Teléfonos IP, analógicos |
| `ups` | UPS/No-Break | 🔋 | Respaldo de energía |
| `esc` | Escáner | 🖨️ | Escáneres documentales |
| `otro` | Otro | 📦 | Otros equipos |

---

### Estados de Equipos

```
┌──────────────────────┐
│ PENDING_ASSIGNMENT   │ ← Recién registrado por Admin
└──────────┬───────────┘
           │
           │ Jefe Dpto asigna a usuario/grupo
           ↓
┌──────────────────────┐
│ ACTIVE               │ ← Equipo en uso
└──────────┬───────────┘
           │
           ├─→ MAINTENANCE     (Mantenimiento preventivo/correctivo)
           │   └─→ ACTIVE      (Regresa después de mantenimiento)
           │
           ├─→ DAMAGED         (Dañado, requiere reparación)
           │   ├─→ ACTIVE      (Reparado)
           │   └─→ RETIRED     (No reparable)
           │
           ├─→ LOST            (Extraviado)
           │
           └─→ RETIRED         (Dado de baja por obsolescencia)
```

---

### Tipos de Asignación

#### 1. **Asignación Individual**
**Descripción**: Equipo asignado a un usuario específico

**Ejemplo**:
```
Computadora COMP-2025-045
├─ Asignado a: Dr. Juan Pérez (Docente)
├─ Departamento: Sistemas y Computación
├─ Ubicación: Oficina B-201
└─ Responsable: Dr. Juan Pérez
```

**Casos de uso**:
- Computadoras personales de docentes/administrativos
- Laptops institucionales
- Impresoras de oficina

**Gestión**:
- Solo el Jefe de Departamento puede asignar
- Usuario es responsable del equipo
- Tickets de ese equipo se relacionan con el usuario

---

#### 2. **Asignación a Grupo** (Salón/Laboratorio)
**Descripción**: Múltiples equipos agrupados en una ubicación física

**Ejemplo**:
```
Grupo: Lab-Computo-2
├─ Tipo: Laboratorio
├─ Departamento: Sistemas y Computación
├─ Capacidad: 30 equipos
├─ Responsable: Ing. María García
└─ Equipos asignados:
    ├─ COMP-2025-100 (Estación 1)
    ├─ COMP-2025-101 (Estación 2)
    ├─ ...
    └─ COMP-2025-129 (Estación 30)
```

**Casos de uso**:
- Laboratorios de cómputo
- Salas de maestros
- Centros de copiado
- Aulas con equipos fijos

**Gestión**:
- Jefe de Departamento crea el grupo
- Especifica capacidad esperada
- Asigna equipos al grupo
- Puede designar un responsable del grupo

---

#### 3. **Asignación Global** (Departamento)
**Descripción**: Equipo asignado al departamento sin usuario/grupo específico

**Ejemplo**:
```
Proyector PROY-2025-015
├─ Asignado a: Departamento de Sistemas (global)
├─ Ubicación: Almacén CC, Estante 3
└─ Uso: Préstamo temporal a docentes
```

**Casos de uso**:
- Equipos en stock/almacén
- Equipos rotatorios (proyectores, laptops de préstamo)
- Repuestos en espera

**Gestión**:
- Disponible para préstamos temporales
- No tiene responsable individual
- Requiere proceso de préstamo/devolución

---

### Flujo de Registro y Asignación de Equipos

#### Fase 1: Registro (Admin)

```
1. Admin accede a /help-desk/inventory/items/new
2. Completa formulario:
   ├─ Categoría (Computadora, Impresora, etc.)
   ├─ Número de inventario (auto-generado: COMP-2025-XXX)
   ├─ Marca, Modelo, Número de Serie
   ├─ Especificaciones técnicas (JSON):
   │  ├─ processor: "Intel Core i5-11500"
   │  ├─ ram: "16 GB"
   │  ├─ storage: "512 GB SSD"
   │  └─ os: "Windows 11 Pro"
   ├─ Departamento destino
   ├─ Fecha de adquisición
   ├─ Fecha de vencimiento de garantía
   └─ Notas adicionales
3. Equipo queda en estado PENDING_ASSIGNMENT
4. Notificación enviada al Jefe del Departamento
```

---

#### Fase 2: Asignación (Jefe de Departamento)

**Opción A: Asignación a Usuario Individual**
```
1. Jefe accede a /help-desk/inventory
2. Ve equipos pendientes de su departamento
3. Selecciona equipo COMP-2025-045
4. Click en "Asignar a Usuario"
5. Busca y selecciona usuario (Dr. Juan Pérez)
6. Especifica ubicación (Oficina B-201)
7. Confirma asignación
8. Estado cambia a ACTIVE
9. Usuario es notificado
```

**Opción B: Asignación a Grupo**
```
1. Jefe crea grupo "Lab-Computo-1":
   ├─ Tipo: Laboratorio
   ├─ Código: LAB-COMP-1
   ├─ Capacidad: 30 estaciones
   └─ Responsable: Ing. María García

2. Selección masiva de equipos:
   ├─ Filtrar: PENDING_ASSIGNMENT, Categoría: Computadora
   ├─ Seleccionar 30 equipos (COMP-2025-100 a COMP-2025-129)
   └─ Acción masiva: "Asignar a Grupo"

3. Asignar al grupo Lab-Computo-1
4. Especificar ubicación base: "Edificio A, Piso 2"
5. Opcionalmente asignar ubicaciones específicas:
   ├─ COMP-2025-100 → Estación 1
   ├─ COMP-2025-101 → Estación 2
   └─ ...

6. Confirmar
7. Todos los equipos pasan a ACTIVE
8. Responsable del grupo es notificado
```

**Opción C: Mantener como Global**
```
1. No hacer nada (equipo queda en PENDING_ASSIGNMENT)
2. O explícitamente marcar como "Global del Departamento"
3. Útil para equipos en almacén o préstamo rotatorio
```

---

### Vinculación de Equipos con Tickets

#### Caso 1: Ticket con Equipo Específico

**Flujo desde creación de ticket**:
```
1. Usuario crea ticket de soporte
2. En formulario, puede buscar y seleccionar equipo:
   - Buscar por número de inventario (COMP-2025-045)
   - Buscar por ubicación (Oficina B-201)
   - O seleccionar de equipos asignados a él
3. Ticket queda vinculado al equipo
4. Técnico puede ver historial del equipo al atender ticket
```

**Flujo desde técnico**:
```
1. Técnico recibe ticket genérico
2. Durante atención, identifica equipo específico
3. Click en "Vincular Equipo"
4. Busca y selecciona equipo
5. Equipo queda relacionado con el ticket
```

---

#### Caso 2: Múltiples Equipos en un Ticket

**Ejemplo**: "Laboratorio completo sin internet"

```
1. Usuario crea ticket reportando problema en Lab-Computo-1
2. Técnico atiende y detecta que es problema del switch
3. Técnico vincula:
   ├─ Switch principal (RED-2025-012)
   └─ Afecta a todo el grupo Lab-Computo-1 (30 computadoras)
4. Al resolver, actualiza estado del switch (MAINTENANCE → ACTIVE)
```

---

### Historial y Auditoría de Inventario

Cada cambio significativo en un equipo queda registrado en `InventoryHistory`:

#### Eventos Registrados

| Evento | Descripción | Datos Guardados |
|--------|-------------|-----------------|
| `created` | Equipo registrado | Usuario que registró |
| `assigned_to_user` | Asignado a usuario | Usuario anterior, Usuario nuevo |
| `assigned_to_group` | Asignado a grupo | Grupo nuevo |
| `status_changed` | Cambio de estado | Estado anterior, Estado nuevo |
| `location_changed` | Cambio de ubicación | Ubicación anterior, Ubicación nueva |
| `specifications_updated` | Specs actualizadas | JSON diff |
| `maintenance_scheduled` | Mantenimiento programado | Fecha programada |
| `maintenance_completed` | Mantenimiento realizado | Técnico, Notas |
| `warranty_expired` | Garantía vencida | Fecha de vencimiento |
| `linked_to_ticket` | Vinculado a ticket | Ticket ID |
| `retired` | Dado de baja | Motivo, Usuario |

---

### Métricas de Inventario

#### Dashboard de Jefe de Departamento

```
📊 Resumen de Inventario - Departamento de Sistemas

Total de Equipos: 150
├─ Activos: 135 (90%)
├─ Mantenimiento: 8 (5%)
├─ Dañados: 5 (3%)
└─ Pendientes Asignación: 2 (1%)

Por Categoría:
├─ Computadoras: 95 (63%)
├─ Impresoras: 25 (17%)
├─ Proyectores: 15 (10%)
└─ Otros: 15 (10%)

Asignación:
├─ Usuarios Individuales: 45 equipos
├─ Grupos/Labs: 85 equipos (3 grupos)
└─ Global/Almacén: 5 equipos

Alertas:
⚠️ 3 equipos requieren mantenimiento preventivo
⚠️ 5 garantías por vencer en 30 días
⚠️ 2 equipos sin asignar por más de 15 días
```

---

## Métricas y Reportes

### Service Level Agreement (SLA)

El sistema calcula automáticamente el cumplimiento de SLA basado en la prioridad del ticket.

#### Tiempos Objetivo por Prioridad

| Prioridad | Tiempo SLA | Color | Ejemplos |
|-----------|-----------|-------|----------|
| URGENTE | 4 horas | 🔴 Rojo | Sistema caído, seguridad crítica |
| ALTA | 24 horas | 🟠 Naranja | Servicio degradado, múltiples usuarios afectados |
| MEDIA | 72 horas (3 días) | 🟡 Amarillo | Problemas individuales, funcionalidad reducida |
| BAJA | 168 horas (7 días) | 🟢 Verde | Mejoras, optimizaciones, consultas |

#### Cálculo de SLA

```python
# Tiempo transcurrido
if ticket.resolved_at:
    elapsed = ticket.resolved_at - ticket.created_at
else:
    elapsed = now() - ticket.created_at

# Porcentaje de SLA consumido
sla_percentage = (elapsed_hours / sla_target_hours) * 100

# Estado de SLA
if sla_percentage <= 100:
    sla_status = "on_time"     # ✅ A tiempo
else:
    sla_status = "overdue"     # ❌ Vencido
```

#### Tipos de Tiempo Medido

1. **Tiempo calendario** (`total_elapsed_hours`)
   - Tiempo real transcurrido desde creación hasta resolución
   - Incluye noches, fines de semana, y feriados
   - Usado para SLA principal

2. **Horas laborales** (`business_hours_elapsed`)
   - Solo cuenta Lunes-Viernes, 8:00 AM - 6:00 PM
   - Excluye noches, fines de semana
   - Útil para métricas internas de productividad

3. **Tiempo invertido** (`time_invested_minutes`)
   - Tiempo real que el técnico trabajó en el ticket
   - Registrado manualmente por el técnico
   - Útil para medir eficiencia y carga de trabajo

**Ejemplo**:
```
Ticket creado: Lunes 10:00 AM
Ticket resuelto: Martes 11:00 AM

Tiempo calendario: 25 horas (SLA)
Horas laborales: 8 horas (Lun 10AM-6PM) + 3 horas (Mar 8AM-11AM) = 11 horas
Tiempo invertido: 2 horas (técnico reporta)
```

---

### Métricas por Técnico

#### Dashboard Individual

```
👤 Ing. Carlos Rodríguez - Técnico de Desarrollo

📊 Resumen del Mes
├─ Tickets Resueltos: 45
├─ Tiempo Promedio Resolución: 18.5 horas
├─ Tasa de Éxito: 93% (42 exitosos, 3 no resueltos)
└─ Calificación Promedio: 4.7/5 ⭐

⏱️ Productividad
├─ Tiempo Total Invertido: 95 horas
├─ Tiempo Promedio por Ticket: 2.1 horas
└─ Tickets/Día: 2.25

🎯 Cumplimiento SLA
├─ A tiempo: 40 tickets (89%)
├─ Vencidos: 5 tickets (11%)
└─ Promedio % SLA: 75% (dentro del target)

📈 Tendencias
├─ Tickets Pendientes: 3 (ASSIGNED)
├─ En Progreso: 2 (IN_PROGRESS)
└─ Carga Actual: Media
```

---

### Sistema de Calificaciones

#### Encuesta de Satisfacción

Cuando un ticket se resuelve, el usuario puede calificar en 3 dimensiones:

**1. Calidad de Atención** (`rating_attention`)
- Escala: 1 a 5 estrellas ⭐
- Pregunta: "¿Cómo calificas la atención recibida?"
- Evalúa: Amabilidad, profesionalismo, comunicación

**2. Rapidez del Servicio** (`rating_speed`)
- Escala: 1 a 5 estrellas ⭐
- Pregunta: "¿Qué tan rápido fue el servicio?"
- Evalúa: Tiempo de respuesta, cumplimiento de SLA

**3. Eficiencia del Servicio** (`rating_efficiency`)
- Escala: Sí / No (Boolean)
- Pregunta: "¿Se resolvió tu problema de manera efectiva?"
- Evalúa: Si la solución fue adecuada y completa

**4. Comentarios Adicionales** (`rating_comment`)
- Campo de texto libre (opcional)
- Pregunta: "¿Tienes alguna sugerencia o comentario adicional?"

#### Cálculo de Calificación General

```python
# Promedio de estrellas
avg_stars = (rating_attention + rating_speed) / 2

# Penalización si no fue eficiente
if not rating_efficiency:
    avg_stars = avg_stars * 0.7  # Reducir 30%

# Calificación final (1-5)
final_rating = round(avg_stars, 1)
```

---

### Reportes Disponibles

#### 1. Reporte de Tickets por Período
**Ruta**: `/api/help-desk/v1/reports/tickets`

**Parámetros**:
- `start_date`: Fecha inicio
- `end_date`: Fecha fin
- `area`: DESARROLLO o SOPORTE (opcional)
- `status`: Filtro por estado (opcional)

**Datos incluidos**:
- Total de tickets creados
- Tickets resueltos vs pendientes
- Tiempo promedio de resolución
- Distribución por categoría
- Distribución por prioridad
- Cumplimiento de SLA

---

#### 2. Reporte de Rendimiento de Técnicos
**Ruta**: `/api/help-desk/v1/reports/technicians`

**Parámetros**:
- `period`: `week`, `month`, `quarter`, `year`
- `team`: `desarrollo` o `soporte`

**Datos incluidos**:
- Tickets por técnico
- Tiempo promedio de resolución
- Tasa de éxito (RESOLVED_SUCCESS / Total)
- Calificaciones promedio
- Cumplimiento de SLA
- Carga actual de trabajo

---

#### 3. Reporte de Satisfacción
**Ruta**: `/api/help-desk/v1/reports/satisfaction`

**Datos incluidos**:
- Calificación promedio global
- Calificación por técnico
- Calificación por área (Desarrollo vs Soporte)
- Calificación por categoría
- Tendencias mensuales
- Comentarios destacados

---

#### 4. Reporte de Inventario
**Ruta**: `/api/help-desk/v1/reports/inventory`

**Datos incluidos**:
- Total de equipos por categoría
- Distribución por estado
- Equipos por departamento
- Equipos sin asignar
- Equipos próximos a vencer garantía
- Equipos que requieren mantenimiento
- Historial de cambios del período

---

## Documentación de API

### Autenticación

Todas las rutas API requieren autenticación mediante JWT almacenado en cookies.

**Headers requeridos**:
```
Cookie: itcj_token=<jwt_token>
```

---

### Endpoints de Tickets

#### GET `/api/help-desk/v1/tickets`
**Descripción**: Lista tickets con filtros y paginación

**Query Parameters**:
```
?status=PENDING              # Filtrar por estado
&priority=ALTA               # Filtrar por prioridad
&area=DESARROLLO             # Filtrar por área
&assigned_to_me=true         # Solo mis tickets asignados
&created_by_me=true          # Solo mis tickets creados
&department_id=5             # Tickets del departamento
&category_id=3               # Filtrar por categoría
&page=1                      # Página (default: 1)
&per_page=20                 # Resultados por página (default: 20)
&sort_by=created_at          # Ordenar por campo
&sort_order=desc             # asc o desc
```

**Response**:
```json
{
  "tickets": [
    {
      "id": 123,
      "ticket_number": "TK-2025-0123",
      "title": "Error en sistema de calificaciones",
      "description": "Al intentar capturar calificaciones aparece error 500",
      "area": "DESARROLLO",
      "priority": "ALTA",
      "status": "IN_PROGRESS",
      "location": "Edificio A, Oficina 201",
      "office_document_folio": "OF-2025-045",
      "created_at": "2025-12-02T10:30:00",
      "updated_at": "2025-12-02T14:15:00",
      "resolved_at": null,
      "requester": {
        "id": 25,
        "name": "Dr. Juan Pérez",
        "username": "jperez"
      },
      "category": {
        "id": 3,
        "code": "dev_sii",
        "name": "SII",
        "area": "DESARROLLO"
      },
      "assigned_to": {
        "id": 8,
        "name": "Ing. Carlos Rodríguez",
        "username": "crodriguez"
      },
      "assigned_to_team": "desarrollo",
      "department": {
        "id": 5,
        "name": "Sistemas y Computación"
      },
      "collaborators": [
        {
          "id": 45,
          "user": {
            "id": 10,
            "name": "Ing. María García"
          },
          "added_at": "2025-12-02T12:00:00"
        }
      ],
      "collaborators_count": 1,
      "inventory_items": [
        {
          "id": 67,
          "inventory_number": "COMP-2025-045",
          "display_name": "COMP-2025-045 - Dell - OptiPlex 7090",
          "brand": "Dell",
          "model": "OptiPlex 7090",
          "location_detail": "Oficina A-201"
        }
      ],
      "inventory_items_count": 1
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 156,
    "pages": 8,
    "has_next": true,
    "has_prev": false
  }
}
```

---

#### POST `/api/help-desk/v1/tickets`
**Descripción**: Crear nuevo ticket

**Body**:
```json
{
  "title": "No puedo acceder al sistema",
  "description": "Al intentar iniciar sesión en SII aparece error 500",
  "area": "DESARROLLO",
  "category_id": 3,
  "priority": "ALTA",
  "location": "Edificio A, Oficina 201",
  "office_document_folio": "OF-2025-050",
  "requester_id": 25,  // Opcional, solo para secretarias
  "inventory_item_ids": [67, 68]  // Opcional, equipos relacionados
}
```

**Response**:
```json
{
  "ok": true,
  "ticket": {
    "id": 124,
    "ticket_number": "TK-2025-0124",
    "status": "PENDING",
    ...
  }
}
```

---

#### PATCH `/api/help-desk/v1/tickets/{id}`
**Descripción**: Actualizar ticket

**Body**:
```json
{
  "priority": "URGENTE",
  "title": "Título actualizado",
  "description": "Descripción actualizada"
}
```

---

#### PATCH `/api/help-desk/v1/tickets/{id}/assign`
**Descripción**: Asignar ticket a técnico

**Body**:
```json
{
  "assigned_to_user_id": 8,
  "assigned_to_team": "desarrollo"
}
```

---

#### PATCH `/api/help-desk/v1/tickets/{id}/status`
**Descripción**: Cambiar estado del ticket

**Body**:
```json
{
  "status": "IN_PROGRESS"
}
```

Para resolver:
```json
{
  "status": "RESOLVED_SUCCESS",
  "resolution_notes": "Se corrigió el error en la base de datos y se actualizó el código",
  "time_invested_minutes": 120
}
```

---

#### POST `/api/help-desk/v1/tickets/{id}/comments`
**Descripción**: Agregar comentario

**Body**:
```json
{
  "content": "He revisado el ticket y el problema es en la base de datos",
  "is_internal": true  // true = solo técnicos, false = visible para usuario
}
```

---

#### POST `/api/help-desk/v1/tickets/{id}/attachments`
**Descripción**: Subir archivo adjunto

**Content-Type**: `multipart/form-data`

**Body**:
```
file: <archivo>
description: "Captura de pantalla del error"
```

---

#### POST `/api/help-desk/v1/tickets/{id}/collaborators`
**Descripción**: Agregar colaborador

**Body**:
```json
{
  "user_id": 10
}
```

---

#### POST `/api/help-desk/v1/tickets/{id}/rate`
**Descripción**: Calificar ticket (solo usuario solicitante)

**Body**:
```json
{
  "rating_attention": 5,
  "rating_speed": 4,
  "rating_efficiency": true,
  "rating_comment": "Excelente servicio, muy rápido"
}
```

---

### Endpoints de Inventario

#### GET `/api/help-desk/v1/inventory/items`
**Descripción**: Lista equipos de inventario

**Query Parameters**:
```
?department_id=5             # Filtrar por departamento
&category_id=1               # Filtrar por categoría
&status=ACTIVE               # Filtrar por estado
&assigned_to_user_id=25      # Equipos de un usuario
&group_id=3                  # Equipos de un grupo
&is_pending_assignment=true  # Solo pendientes de asignación
&search=COMP-2025            # Buscar por número, marca, modelo
&page=1
&per_page=50
```

---

#### POST `/api/help-desk/v1/inventory/items`
**Descripción**: Registrar nuevo equipo (Admin)

**Body**:
```json
{
  "inventory_number": "COMP-2025-150",  // Opcional, se auto-genera
  "category_id": 1,
  "brand": "Dell",
  "model": "OptiPlex 7090",
  "serial_number": "SN123456789",
  "specifications": {
    "processor": "Intel Core i5-11500",
    "ram": "16",
    "ram_unit": "GB",
    "storage": "512",
    "storage_unit": "GB",
    "storage_type": "SSD",
    "os": "Windows 11 Pro",
    "has_monitor": true,
    "monitor_size": "24"
  },
  "department_id": 5,
  "acquisition_date": "2025-01-15",
  "warranty_expiration": "2028-01-15",
  "notes": "Equipo nuevo para laboratorio"
}
```

---

#### PATCH `/api/help-desk/v1/inventory/items/{id}/assign`
**Descripción**: Asignar equipo (Jefe Dpto / Admin)

**Body para usuario individual**:
```json
{
  "assigned_to_user_id": 25,
  "location_detail": "Oficina A-201"
}
```

**Body para grupo**:
```json
{
  "group_id": 3,
  "location_detail": "Lab Computo 1, Estación 5"
}
```

---

#### POST `/api/help-desk/v1/inventory/groups`
**Descripción**: Crear grupo de equipos

**Body**:
```json
{
  "name": "Laboratorio de Cómputo 1",
  "code": "LAB-COMP-1",
  "department_id": 5,
  "group_type": "laboratory",  // laboratory, classroom, office, storage
  "location": "Edificio A, Piso 2",
  "responsible_user_id": 15,
  "capacity": 30,
  "description": "Laboratorio principal de programación"
}
```

---

## Comandos Flask Personalizados

### Comandos de Help-Desk

```bash
# Limpiar adjuntos huérfanos (archivos sin ticket asociado)
flask helpdesk-cleanup-attachments

# Generar reporte de tickets del mes
flask helpdesk-ticket-report --month=12 --year=2024

# Actualizar métricas de SLA (ejecutar diariamente con cron)
flask helpdesk-update-sla

# Notificar tickets próximos a vencer SLA
flask helpdesk-notify-sla-warnings

# Cerrar automáticamente tickets resueltos hace más de 7 días
flask helpdesk-auto-close-tickets --days=7

# Importar equipos desde CSV
flask helpdesk-import-inventory --file=equipos.csv

# Generar números de inventario faltantes
flask helpdesk-generate-inventory-numbers --category=comp --start=100 --count=50
```

---

## Mejores Prácticas

### Para Usuarios (Staff)

1. **Título descriptivo**: "Error al guardar calificaciones en SII" vs "No funciona"
2. **Descripción detallada**: Incluir pasos para reproducir, mensajes de error, capturas
3. **Prioridad correcta**: No marcar todo como URGENTE, usar criterios reales
4. **Vincular equipos**: Si el problema es de un equipo específico, vincularlo
5. **Seguimiento**: Revisar notificaciones y responder preguntas de técnicos
6. **Calificar**: Siempre calificar el servicio para mejorar el sistema

---

### Para Técnicos

1. **Aceptar rápido**: Cambiar a IN_PROGRESS al comenzar el trabajo
2. **Comentar progreso**: Mantener al usuario informado con actualizaciones
3. **Comentarios internos**: Usar para comunicación técnica sin confundir al usuario
4. **Documentar solución**: Escribir resolution_notes detalladas para futura referencia
5. **Tiempo invertido**: Registrar el tiempo real trabajado para métricas precisas
6. **Vincular equipos**: Siempre vincular equipos afectados para historial
7. **Agregar colaboradores**: Si necesitas ayuda, agrega al técnico colaborador
8. **Cerrar proactivamente**: Resolver tickets de manera oportuna para cumplir SLA

---

### Para Jefes de Departamento

1. **Asignar rápido**: Equipos en PENDING_ASSIGNMENT generan alertas
2. **Grupos eficientes**: Crear grupos para laboratorios facilita gestión masiva
3. **Responsables claros**: Designar responsables de grupos/salones
4. **Revisar métricas**: Monitorear tickets del departamento semanalmente
5. **Mantenimientos preventivos**: Agendar mantenimientos antes de que equipos fallen

---

### Para Administradores

1. **Categorías claras**: Mantener categorías bien definidas y actualizadas
2. **Roles apropiados**: Asignar roles según funciones reales
3. **Monitorear SLA**: Revisar tickets vencidos y tomar acciones
4. **Capacitar**: Entrenar a usuarios en el uso correcto del sistema
5. **Analizar métricas**: Usar reportes para tomar decisiones informadas
6. **Respaldo**: Mantener backups regulares de la base de datos

---

## Solución de Problemas Comunes

### Usuario no puede crear tickets
**Problema**: Error "No autorizado" al intentar crear ticket

**Soluciones**:
1. Verificar que el usuario tiene el rol `staff` en Help-Desk
2. Verificar que la sesión no ha expirado (relogin)
3. Verificar que el departamento del usuario está activo

```bash
# Asignar rol staff a usuario
flask assign-role <user_id> staff --app helpdesk
```

---

### Técnico no ve tickets asignados
**Problema**: Dashboard vacío para técnico

**Soluciones**:
1. Verificar que tiene el rol correcto (`tech_desarrollo` o `tech_soporte`)
2. Verificar que hay tickets asignados en su área
3. Verificar filtros del dashboard

```bash
# Verificar roles del usuario
flask list-user-roles <user_id>
```

---

### Archivos adjuntos no se suben
**Problema**: Error al subir imágenes

**Soluciones**:
1. Verificar que el archivo no excede 3MB
2. Verificar que el formato es permitido (jpg, jpeg, png, gif, webp)
3. Verificar permisos de escritura en `instance/apps/helpdesk/attachments/`

```bash
# Verificar permisos
ls -la instance/apps/helpdesk/attachments/

# Ajustar permisos si es necesario
chmod 755 instance/apps/helpdesk/attachments/
```

---

### WebSockets no funcionan
**Problema**: Notificaciones en tiempo real no aparecen

**Soluciones**:
1. Verificar que Redis está corriendo
2. Verificar configuración de SocketIO en `.env`
3. Verificar firewall/proxy no bloquea WebSockets

```bash
# Verificar Redis
redis-cli ping
# Debe responder: PONG

# Verificar logs de SocketIO
docker-compose logs backend | grep socketio
```

---

## Roadmap y Futuras Mejoras

### Versión 1.1 (Q1 2025)
- [ ] Asignación automática inteligente basada en carga de trabajo
- [ ] Plantillas de respuesta rápida para técnicos
- [ ] Notificaciones por email además de in-app
- [ ] Exportación de reportes a PDF/Excel
- [ ] Dashboard público de estadísticas

### Versión 1.2 (Q2 2025)
- [ ] Sistema de priorización automática con IA
- [ ] Chat en vivo entre usuario y técnico
- [ ] Base de conocimiento (KB) con soluciones frecuentes
- [ ] Integración con sistema de activos institucional
- [ ] API pública documentada (OpenAPI/Swagger)

### Versión 2.0 (Q3 2025)
- [ ] App móvil (iOS/Android) para técnicos
- [ ] Sistema de préstamo de equipos rotatorios
- [ ] Gamificación para técnicos (badges, ranking)
- [ ] Análisis predictivo de fallas de equipos
- [ ] Integración con proveedores externos

---

## Contacto y Soporte

### Reportar Bugs
- **GitHub Issues**: [Crear issue](link-to-repo/issues)
- **Email**: soporte-helpdesk@itcj.edu.mx

### Solicitar Funcionalidades
- **GitHub Discussions**: [Abrir discusión](link-to-repo/discussions)
- **Formulario**: [Link a formulario interno]

### Documentación Adicional
- **README Principal**: [`/README.md`](../../README.md)
- **Guía de Base de Datos**: [`/database/VERIFICATION_GUIDE.md`](../../../database/VERIFICATION_GUIDE.md)
- **AgendaTec README**: [`/itcj/apps/agendatec/README.md`](../agendatec/README.md)

---

## Licencia

Este proyecto es de uso interno del Instituto Tecnológico de Ciudad Juárez.

---

**Desarrollado con ❤️ por el equipo de Centros de Cómputo del ITCJ**

**Última actualización**: Diciembre 2024

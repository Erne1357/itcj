# Plan: Aplicación de Mantenimiento (Help Desk de Mantenimiento)

> **Rama objetivo:** `feature/maintenance-app`
> **Fecha de planeación:** 2026-03-09
> **Departamento:** `equipment_maint`
> **Contexto:** App paralela a Help Desk CC, con la misma filosofía de tickets pero orientada al departamento de mantenimiento. Visualmente similar a Help Desk, pero con diferencias clave en asignación múltiple, auditoría reforzada y categorías propias.

---

## Tabla de Contenidos

1. [Diferencias clave vs Help Desk CC](#1-diferencias-clave-vs-help-desk-cc)
2. [Arquitectura de Datos](#2-arquitectura-de-datos)
3. [Sistema de Permisos y Roles](#3-sistema-de-permisos-y-roles)
4. [Lógica de Negocio](#4-lógica-de-negocio)
5. [API Endpoints](#5-api-endpoints)
6. [Páginas Frontend](#6-páginas-frontend)
7. [Integración con Almacén Global](#7-integración-con-almacén-global)
8. [Fases de Implementación](#8-fases-de-implementación)
9. [Estructura de Archivos](#9-estructura-de-archivos)
10. [Convenciones y Estándares](#10-convenciones-y-estándares)

---

## 1. Diferencias clave vs Help Desk CC

| Aspecto | Help Desk CC | Mantenimiento |
|---|---|---|
| Prefijo BD | `helpdesk_*` | `maint_*` |
| Áreas | DESARROLLO / SOPORTE | N/A (área es informativa por técnico) |
| Asignación | 1 técnico o equipo | 1..N técnicos simultáneos |
| ¿Quién asigna? | Secretaria / Admin | 1..N dispatchers |
| ¿Quién resuelve? | Solo el asignado | Asignado **O** cualquier dispatcher |
| Categorías | Por área (Desarrollo/Soporte) | Transporte, Mant. General, Eléctrico, Carpintería, A/C, Jardinería |
| Campos dinámicos | `field_template` por categoría | Igual (ej: campos extra para Transporte) |
| Auditoría | StatusLog + EditLog | StatusLog + **ActionLog reforzado** |
| Inventario | Equipos individuales (activos) | No aplica |
| Almacén | Helpdesk Warehouse | Almacén Global compartido |
| Tipo mantenimiento | PREVENTIVO / CORRECTIVO | Igual |
| Origen servicio | INTERNO / EXTERNO | Igual |
| Rating y cierre | Rating → CLOSED | Igual |
| Límite tickets sin calificar | 3 | Igual |

---

## 2. Arquitectura de Datos

> **Convención de prefijo:** `maint_*`
> **DDL:** Vía migraciones Alembic (nunca SQL directo para DDL)

### 2.1 Modelos SQLAlchemy

---

#### Modelo 1: `MaintCategory` → `maint_categories`

```
id              INTEGER PK
code            VARCHAR(50) UNIQUE NOT NULL
                Valores iniciales: TRANSPORT, GENERAL, ELECTRICAL, CARPENTRY, AC, GARDENING
name            VARCHAR(100) NOT NULL
                Nombres: Transporte, Mantenimiento General, Taller Eléctrico,
                         Carpintería, Aire Acondicionado, Jardinería
description     TEXT
icon            VARCHAR(50) DEFAULT 'bi-tools'
field_template  JSON NULLABLE      -- Campos extra (ej: Transporte: destino, horario, pasajeros)
is_active       BOOLEAN DEFAULT TRUE
display_order   INTEGER DEFAULT 0
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP DEFAULT NOW()

INDEX(is_active, display_order)
```

**field_template para Transporte (ejemplo):**
```json
[
  {"key": "destination",      "label": "Destino",                  "type": "text",   "required": true},
  {"key": "departure_date",   "label": "Fecha de salida",          "type": "date",   "required": true},
  {"key": "departure_time",   "label": "Hora de salida estimada",  "type": "time",   "required": true},
  {"key": "return_time",      "label": "Hora de regreso estimada", "type": "time",   "required": false},
  {"key": "passenger_count",  "label": "Número de pasajeros",      "type": "number", "required": true},
  {"key": "vehicle_type",     "label": "Tipo de vehículo",         "type": "select", "required": false,
   "options": ["Camioneta", "Autobús", "Automóvil", "Sin preferencia"]}
]
```

Relaciones:
- `tickets` → List[MaintTicket]

---

#### Modelo 2: `MaintTicket` → `maint_tickets`

```
id                          INTEGER PK
ticket_number               VARCHAR(20) UNIQUE NOT NULL   -- MANT-2026-000001
requester_id                FK → core_users NOT NULL
requester_department_id     FK → core_departments NOT NULL
category_id                 FK → maint_categories NOT NULL
priority                    VARCHAR(20) DEFAULT 'MEDIA'
                            Valores: BAJA | MEDIA | ALTA | URGENTE
title                       VARCHAR(200) NOT NULL
description                 TEXT NOT NULL
location                    VARCHAR(300)
custom_fields               JSON NULLABLE

-- Estado
status                      VARCHAR(30) NOT NULL DEFAULT 'PENDING'
                            Valores: PENDING | ASSIGNED | IN_PROGRESS |
                                     RESOLVED_SUCCESS | RESOLVED_FAILED | CLOSED | CANCELED

-- Resolución
maintenance_type            VARCHAR(20) NULLABLE          -- PREVENTIVO | CORRECTIVO
service_origin              VARCHAR(20) NULLABLE          -- INTERNO | EXTERNO
resolution_notes            TEXT NULLABLE
time_invested_minutes       INTEGER NULLABLE
observations                TEXT NULLABLE
resolved_at                 TIMESTAMP NULLABLE
resolved_by_id              FK → core_users NULLABLE

-- Rating
rating_attention            INTEGER NULLABLE              -- 1–5
rating_speed                INTEGER NULLABLE              -- 1–5
rating_efficiency           BOOLEAN NULLABLE
rating_comment              TEXT NULLABLE
rated_at                    TIMESTAMP NULLABLE

-- Auditoría
created_at                  TIMESTAMP DEFAULT NOW()
created_by_id               FK → core_users NOT NULL
updated_at                  TIMESTAMP ON UPDATE NOW()
updated_by_id               FK → core_users NULLABLE
closed_at                   TIMESTAMP NULLABLE
canceled_at                 TIMESTAMP NULLABLE
canceled_by_id              FK → core_users NULLABLE
cancel_reason               TEXT NULLABLE

INDEX(status, created_at)
INDEX(requester_id, status)
INDEX(ticket_number)
INDEX(category_id, status)
INDEX(resolved_by_id)
```

Propiedades calculadas:
- `is_open` = status NOT IN (CLOSED, CANCELED)
- `is_resolved` = status IN (RESOLVED_SUCCESS, RESOLVED_FAILED, CLOSED)
- `can_be_rated` = is_resolved AND rating_attention IS NULL
- `active_technicians` = lista de usuarios en `maint_ticket_technicians` con `unassigned_at IS NULL`

Relaciones:
- `requester` (User)
- `requester_department` (Department)
- `category` (MaintCategory)
- `resolved_by` (User)
- `created_by_user`, `updated_by_user`, `canceled_by_user` (User)
- `technicians` (MaintTicketTechnician) → cascade delete
- `status_logs` (MaintStatusLog) → cascade delete
- `action_logs` (MaintTicketActionLog) → cascade delete
- `comments` (MaintComment) → cascade delete
- `attachments` (MaintAttachment) → cascade delete

---

#### Modelo 3: `MaintTicketTechnician` → `maint_ticket_technicians`

*(Asignaciones múltiples de técnicos por ticket — historial completo)*

```
id                  INTEGER PK
ticket_id           FK → maint_tickets NOT NULL
user_id             FK → core_users NOT NULL
assigned_by_id      FK → core_users NOT NULL
assigned_at         TIMESTAMP DEFAULT NOW()
unassigned_at       TIMESTAMP NULLABLE
unassigned_by_id    FK → core_users NULLABLE
unassigned_reason   VARCHAR(500) NULLABLE
notes               TEXT NULLABLE

-- Sin UNIQUE(ticket_id, user_id) porque el mismo técnico
-- puede ser asignado, removido y vuelto a asignar en diferentes momentos.
-- La asignación activa se obtiene filtrando: unassigned_at IS NULL

INDEX(ticket_id, unassigned_at)    -- Asignaciones activas por ticket
INDEX(user_id, unassigned_at)      -- Tickets activos de un técnico
INDEX(ticket_id, assigned_at)      -- Historia de asignaciones
```

Relaciones:
- `ticket` (MaintTicket)
- `user` (User) — el técnico asignado
- `assigned_by` (User) — el dispatcher que asignó
- `unassigned_by` (User)

---

#### Modelo 4: `MaintTechnicianArea` → `maint_technician_areas`

*(Áreas de especialidad de cada técnico — informativo, NO restringe asignación)*

```
id              INTEGER PK
user_id         FK → core_users NOT NULL
area_code       VARCHAR(50) NOT NULL
                Valores: TRANSPORT | ELECTRICAL | CARPENTRY | AC | GARDENING | GENERAL | PAINTING
is_primary      BOOLEAN DEFAULT FALSE   -- Área principal del técnico
created_at      TIMESTAMP DEFAULT NOW()
updated_by_id   FK → core_users NULLABLE
updated_at      TIMESTAMP

UNIQUE(user_id, area_code)
INDEX(user_id)
INDEX(area_code)
```

> **Nota:** No restringe qué tickets puede recibir el técnico. Es solo referencial para
> que el dispatcher sepa quién tiene experiencia en qué.

---

#### Modelo 5: `MaintStatusLog` → `maint_status_logs`

*(Auditoría de cambios de estado del ticket)*

```
id              INTEGER PK
ticket_id       FK → maint_tickets NOT NULL
from_status     VARCHAR(30) NULLABLE      -- NULL en el primer registro
to_status       VARCHAR(30) NOT NULL
changed_by_id   FK → core_users NOT NULL
notes           TEXT NULLABLE
created_at      TIMESTAMP DEFAULT NOW()

INDEX(ticket_id, created_at)
INDEX(changed_by_id, created_at)
```

---

#### Modelo 6: `MaintTicketActionLog` → `maint_ticket_action_logs`

*(Auditoría reforzada: registra TODA acción sobre el ticket, incluyendo resoluciones por dispatcher)*

```
id              INTEGER PK
ticket_id       FK → maint_tickets NOT NULL
action          VARCHAR(60) NOT NULL
                Valores:
                  CREATED                  -- Ticket creado
                  TECHNICIAN_ASSIGNED      -- Técnico asignado al ticket
                  TECHNICIAN_UNASSIGNED    -- Técnico removido del ticket
                  STATUS_CHANGED           -- Cambio de estado (complementa StatusLog)
                  RESOLVED_BY_ASSIGNED     -- Resuelto por un técnico formalmente asignado
                  RESOLVED_BY_DISPATCHER   -- Resuelto por un dispatcher NO asignado al ticket
                  RATED                    -- Calificado por el solicitante
                  COMMENTED                -- Comentario agregado
                  ATTACHMENT_ADDED         -- Archivo adjunto
                  EDITED                   -- Campo editado (antes de asignación)
                  CANCELED                 -- Cancelado
                  WAREHOUSE_MATERIAL_ADDED -- Material del almacén registrado
                  WAREHOUSE_MATERIAL_REMOVED -- Material del almacén revertido
performed_by_id FK → core_users NOT NULL
performed_at    TIMESTAMP DEFAULT NOW()
detail          JSON NULLABLE
                -- Contexto adicional según la acción:
                -- Para TECHNICIAN_ASSIGNED: {user_id, user_name, assigned_by}
                -- Para RESOLVED_BY_DISPATCHER: {resolver_id, resolver_name, had_active_technicians: bool}
                -- Para EDITED: {field, old_value, new_value}
                -- Para STATUS_CHANGED: {from_status, to_status}

INDEX(ticket_id, performed_at)
INDEX(performed_by_id, performed_at)
INDEX(action, performed_at)
```

> **Por qué este modelo es crítico:** Si un dispatcher resuelve un ticket donde no estaba
> asignado, queda registrado con `RESOLVED_BY_DISPATCHER` en `detail.had_active_technicians`.
> Permite auditar si se resolvió algo que no les correspondía o si fue necesario por falta
> de técnico con equipo disponible.

---

#### Modelo 7: `MaintComment` → `maint_comments`

```
id              INTEGER PK
ticket_id       FK → maint_tickets NOT NULL
author_id       FK → core_users NOT NULL
content         TEXT NOT NULL
is_internal     BOOLEAN DEFAULT FALSE
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP

INDEX(ticket_id, created_at)
```

Relaciones:
- `ticket` (MaintTicket)
- `author` (User)
- `attachments` (MaintAttachment)

---

#### Modelo 8: `MaintAttachment` → `maint_attachments`

```
id                  INTEGER PK
ticket_id           FK → maint_tickets NOT NULL
uploaded_by_id      FK → core_users NOT NULL
attachment_type     VARCHAR(30) NOT NULL          -- ticket | resolution | comment
comment_id          FK → maint_comments NULLABLE
filename            VARCHAR(255) NOT NULL
original_filename   VARCHAR(255) NOT NULL
filepath            VARCHAR(500) NOT NULL
mime_type           VARCHAR(100)
file_size           INTEGER
uploaded_at         TIMESTAMP DEFAULT NOW()
auto_delete_at      TIMESTAMP NULLABLE

INDEX(auto_delete_at)
INDEX(ticket_id, attachment_type)
```

---

### 2.2 Diagrama de Relaciones

```
MaintCategory
    └── MaintTicket (N)
            ├── MaintTicketTechnician (N)    ← historial de asignaciones
            ├── MaintStatusLog (N)           ← historial de estados
            ├── MaintTicketActionLog (N)     ← auditoría completa
            ├── MaintComment (N)
            │       └── MaintAttachment (N) [comment_id]
            └── MaintAttachment (N)

MaintTechnicianArea                          ← áreas por técnico (independiente de tickets)
    └── core_users (via user_id)

-- Relación con Almacén Global (ver PLAN_WAREHOUSE_GLOBAL.md):
WarehouseTicketMaterial
    source_app = 'maint'
    source_ticket_id = maint_tickets.id
```

---

## 3. Sistema de Permisos y Roles

### 3.1 Roles de la App

Se reutilizan roles globales del sistema para no proliferar roles innecesarios.

| Rol (global) | Tipo | Descripción en maint |
|---|---|---|
| `admin` | Existente | Acceso total: categorías, reportes, asignaciones, todo |
| `dispatcher` | **Nuevo global** | Asigna/reasigna técnicos; puede resolver cualquier ticket (incluso sin estar asignado) |
| `tech_maint` | **Nuevo global** | Técnico de campo de mantenimiento: ve sus tickets asignados, resuelve |
| `department_head` | Existente | Jefe de depto: ve tickets de su departamento, crea solicitudes, califica |
| `secretary` | Existente | Secretaría de depto: misma visibilidad que `department_head` |
| `staff` | Existente | Empleado genérico: crea sus propios tickets, ve solo los suyos, califica |

> `dispatcher` y `tech_maint` NO son excluyentes (ej: jefe de cuadrilla que también trabaja y asigna).
>
> `department_head` y `secretary` se asignan automáticamente a las posiciones via `core_position_app_roles`.
>
> `staff` se asigna manualmente a empleados que requieran acceso básico.

### 3.2 Permisos

```
-- PÁGINAS
maint.tickets.page.list             → Ver lista de tickets (vista ajustada por rol)
maint.tickets.page.detail           → Ver detalle de un ticket
maint.tickets.page.create           → Crear ticket
maint.admin.page.categories         → Gestión de categorías y field_templates
maint.admin.page.areas              → Gestión de áreas de técnicos
maint.admin.page.reports            → Reportes de la app

-- API - TICKETS
maint.tickets.api.create            → Crear ticket
maint.tickets.api.read.own          → Leer sus propios tickets
maint.tickets.api.read.department   → Leer tickets del departamento del solicitante
maint.tickets.api.read.all          → Leer todos los tickets
maint.tickets.api.edit              → Editar ticket (antes de asignación; solo propios para dept_head/secretary/staff)
maint.tickets.api.cancel            → Cancelar ticket (solo propios en PENDING para dept_head/secretary/staff)
maint.tickets.api.resolve           → Resolver ticket (dispatcher y tech_maint)
maint.tickets.api.rate              → Calificar ticket (solicitante: dept_head / secretary / staff)

-- API - ASIGNACIONES
maint.assignments.api.assign        → Asignar técnico a ticket
maint.assignments.api.unassign      → Remover técnico de ticket

-- API - COMENTARIOS
maint.comments.api.create           → Agregar comentario público
maint.comments.api.internal         → Ver/crear comentarios internos (solo staff operativo)

-- API - ADMIN
maint.admin.api.categories          → Crear/editar/desactivar categorías
maint.admin.api.areas               → Gestionar áreas de especialidad de técnicos
maint.admin.api.reports             → Consultar reportes y estadísticas
```

**Total: 21 permisos**

### 3.3 Asignación a Roles

| Permiso | admin | dispatcher | tech_maint | department_head | secretary | staff |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| page.list | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| page.detail | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| page.create | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| admin.page.categories | ✅ | — | — | — | — | — |
| admin.page.areas | ✅ | ✅ | — | — | — | — |
| admin.page.reports | ✅ | ✅ | — | — | — | — |
| tickets.api.create | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| tickets.api.read.own | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| tickets.api.read.department | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| tickets.api.read.all | ✅ | ✅ | ✅ | — | — | — |
| tickets.api.edit | ✅ | ✅ | — | ✅ (propios) | ✅ (propios) | ✅ (propios) |
| tickets.api.cancel | ✅ | ✅ | — | ✅ (propios) | ✅ (propios) | ✅ (propios) |
| tickets.api.resolve | ✅ | ✅ | ✅ | — | — | — |
| tickets.api.rate | — | — | — | ✅ | ✅ | ✅ |
| assignments.api.assign | ✅ | ✅ | — | — | — | — |
| assignments.api.unassign | ✅ | ✅ | — | — | — | — |
| comments.api.create | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| comments.api.internal | ✅ | ✅ | ✅ | — | — | — |
| admin.api.categories | ✅ | — | — | — | — | — |
| admin.api.areas | ✅ | ✅ | — | — | — | — |
| admin.api.reports | ✅ | ✅ | — | — | — | — |

> Las restricciones "(propios)" y "(PENDING)" se aplican en la capa de servicio, no en los permisos.

### 3.4 Archivos DML

```
database/DML/maint/
  00_insert_app.sql
  01_add_maint_permissions.sql
  02_assign_maint_permissions_to_roles.sql   ← Crea dispatcher y tech_maint; asigna todo
  03_seed_maint_categories.sql               ← Las 6 categorías con sus field_templates
```

---

## 4. Lógica de Negocio

### 4.1 Flujo de Estados

```
PENDING (ticket creado)
  ↓  [assign_ticket — dispatcher asigna 1+ técnicos]
ASSIGNED
  ↓  [start_progress — técnico asignado o dispatcher cambia estado]
IN_PROGRESS
  ↓  [resolve — técnico asignado O dispatcher]
RESOLVED_SUCCESS | RESOLVED_FAILED
  ↓  [rate — solicitante califica]
CLOSED  ← estado final

En cualquier momento antes de RESOLVED:
  → CANCELED  [cancel — solicitante si es PENDING, dispatcher/admin en cualquier estado]
```

**Progreso visual (porcentaje para UI):**
- PENDING → 10% — "Solicitud creada, pendiente de asignación"
- ASSIGNED → 30% — "Asignada a técnico(s)"
- IN_PROGRESS → 60% — "En proceso"
- RESOLVED_SUCCESS → 90% — "Resuelta exitosamente"
- RESOLVED_FAILED → 85% — "Atendida, sin resolución completa"
- CLOSED → 100% — "Cerrada"
- CANCELED → 0% — "Cancelada"

---

### 4.2 Asignación Múltiple de Técnicos

```
assign_technician(ticket_id, user_id, assigned_by_id, notes):

1. Verificar ticket.status IN (PENDING, ASSIGNED, IN_PROGRESS)
2. Verificar que user_id tiene rol maint_technician (o maint_dispatcher/admin)
3. Verificar si user_id ya tiene asignación activa en este ticket:
   - MaintTicketTechnician WHERE ticket_id=X AND user_id=Y AND unassigned_at IS NULL
   - Si existe → raise ValueError("El técnico ya está asignado a este ticket")
4. Crear MaintTicketTechnician(ticket_id, user_id, assigned_by_id, assigned_at=now())
5. Si ticket.status == PENDING → cambiar a ASSIGNED
   - Crear MaintStatusLog(PENDING → ASSIGNED)
6. Crear MaintTicketActionLog(action=TECHNICIAN_ASSIGNED,
   detail={user_id, user_name, assigned_by_id})
7. Enviar notificación al técnico asignado
```

```
unassign_technician(ticket_id, user_id, unassigned_by_id, reason):

1. Buscar asignación activa: MaintTicketTechnician WHERE ticket_id=X AND user_id=Y
   AND unassigned_at IS NULL
2. Si no existe → raise 404
3. Actualizar: unassigned_at=now(), unassigned_by_id, unassigned_reason=reason
4. Contar asignaciones activas restantes:
   - Si 0 activas y ticket.status == ASSIGNED → cambiar status a PENDING
5. Crear MaintTicketActionLog(action=TECHNICIAN_UNASSIGNED, detail={...})
```

---

### 4.3 Resolución por Dispatcher (sin ser técnico asignado)

```
resolve_ticket(ticket_id, resolver_id, resolution_data):

1. Verificar ticket.status IN (ASSIGNED, IN_PROGRESS)
2. Verificar que resolver tiene permiso maint.tickets.api.resolve
3. Determinar tipo de resolución:
   - is_assigned = ¿resolver_id tiene asignación activa en el ticket?
   - action = RESOLVED_BY_ASSIGNED si is_assigned, sino RESOLVED_BY_DISPATCHER
4. Actualizar MaintTicket:
   - status = RESOLVED_SUCCESS o RESOLVED_FAILED (según resolution_data.outcome)
   - resolution_notes, maintenance_type, service_origin, time_invested_minutes
   - resolved_at = now(), resolved_by_id = resolver_id
5. Crear MaintStatusLog(from=IN_PROGRESS|ASSIGNED, to=RESOLVED_*)
6. Crear MaintTicketActionLog(
     action = <action calculado>,
     performed_by_id = resolver_id,
     detail = {
       outcome: "SUCCESS|FAILED",
       resolved_by_role: "dispatcher|technician",
       had_active_technicians: bool,
       active_technician_ids: [...]  ← si aplica
     }
   )
7. Procesar material del almacén si se registró
8. Programar auto-delete de adjuntos (2 días)
9. Notificar al solicitante
```

---

### 4.4 Restricción de 3 Tickets sin Calificar

```
create_ticket(requester_id, ...):

1. Contar tickets del requester:
   WHERE requester_id = X
   AND status IN (RESOLVED_SUCCESS, RESOLVED_FAILED)
   AND rating_attention IS NULL

2. Si count >= 3:
   raise HTTPException(400,
     "Tienes 3 o más solicitudes resueltas sin calificar. "
     "Por favor califica tus solicitudes anteriores antes de crear una nueva."
   )

3. Continuar con creación normal
```

---

### 4.5 Cierre por Rating

```
rate_ticket(ticket_id, requester_id, rating_data):

1. Verificar ticket.requester_id == requester_id (solo el solicitante califica)
2. Verificar ticket.status IN (RESOLVED_SUCCESS, RESOLVED_FAILED)
3. Verificar ticket.rating_attention IS NULL (no calificado aún)
4. Actualizar MaintTicket:
   - rating_attention, rating_speed, rating_efficiency, rating_comment
   - rated_at = now()
   - status = CLOSED
   - closed_at = now()
5. Crear MaintStatusLog(from=RESOLVED_*, to=CLOSED)
6. Crear MaintTicketActionLog(action=RATED, detail={ratings})
```

---

### 4.6 Número de Ticket

**Formato:** `MANT-{YEAR}-{SEQ:06d}`
**Ejemplo:** `MANT-2026-000001`

- Secuencial por año (reinicia en 000001 cada 1 de enero)
- Generado en un servicio atómico similar a `ticket_number_generator.py` de helpdesk
- Prefijo `MANT-` para diferenciar claramente de `TICK-` de helpdesk

---

## 5. API Endpoints

### Base URL: `/api/maint/v2`

#### 5.1 Tickets

```
POST   /tickets                          → Crear ticket (con adjuntos vía multipart)
GET    /tickets                          → Listar tickets (filtros: status, category_id,
                                           priority, requester_id, technician_id, fecha)
GET    /tickets/{ticket_id}              → Detalle de ticket (con técnicos, logs, comentarios)
PUT    /tickets/{ticket_id}              → Editar ticket (solo antes de ASSIGNED)
POST   /tickets/{ticket_id}/cancel       → Cancelar ticket
POST   /tickets/{ticket_id}/start        → Cambiar a IN_PROGRESS
POST   /tickets/{ticket_id}/resolve      → Resolver ticket (+ material almacén opcional)
POST   /tickets/{ticket_id}/rate         → Calificar ticket
```

#### 5.2 Asignaciones

```
POST   /tickets/{ticket_id}/technicians              → Asignar técnico
DELETE /tickets/{ticket_id}/technicians/{user_id}    → Remover técnico
GET    /tickets/{ticket_id}/technicians              → Ver técnicos asignados (activos + histórico)
```

#### 5.3 Comentarios y Adjuntos

```
GET    /tickets/{ticket_id}/comments                 → Listar comentarios
POST   /tickets/{ticket_id}/comments                 → Agregar comentario
POST   /tickets/{ticket_id}/attachments              → Subir adjunto al ticket
```

#### 5.4 Categorías (Admin)

```
GET    /categories                       → Listar categorías
POST   /categories                       → Crear categoría
PUT    /categories/{id}                  → Editar categoría + field_template
DELETE /categories/{id}                  → Desactivar categoría
```

#### 5.5 Áreas de Técnicos (Admin/Dispatcher)

```
GET    /technicians                      → Listar técnicos con sus áreas
GET    /technicians/{user_id}/areas      → Áreas de un técnico
POST   /technicians/{user_id}/areas      → Asignar área a técnico
DELETE /technicians/{user_id}/areas/{area_code} → Remover área de técnico
```

#### 5.6 Dashboard y Reportes

```
GET    /dashboard                        → Stats: tickets por estado, por categoría,
                                           tiempo promedio de resolución, últimas actividades
GET    /reports/tickets                  → Reporte de tickets por período
GET    /reports/technicians              → Reporte de productividad por técnico
GET    /reports/categories               → Reporte por categoría
```

---

## 6. Páginas Frontend

### Base URL de páginas: `/mantenimiento/`

| Ruta | Descripción | Rol |
|---|---|---|
| `/` | Dashboard: mis tickets (requester) o todos los tickets (staff) | Todos |
| `/tickets/crear` | Formulario de creación | Todos |
| `/tickets/{id}` | Detalle del ticket | Todos |
| `/admin/categorias` | Gestión de categorías y field_templates | Admin |
| `/admin/tecniucos` | Gestión de áreas de técnicos | Admin / Dispatcher |
| `/admin/reportes` | Reportes y estadísticas | Admin / Dispatcher |

### 6.1 Vistas diferenciadas por rol en `/`

- **Requester:** Mis solicitudes (puede filtrar por estado, buscar)
- **Technician:** Mis tickets asignados activos + historial
- **Dispatcher:** Todos los tickets con vista de gestión (asignar, reasignar)
- **Admin:** Vista total con estadísticas en cabecera

---

## 7. Integración con Almacén Global

> Ver `PLAN_WAREHOUSE_GLOBAL.md` para la arquitectura completa del almacén.

La integración en la app de mantenimiento es análoga a la de helpdesk:

1. **Al resolver un ticket**, en la tab de resolución se puede registrar material utilizado.
2. El endpoint `POST /api/maint/v2/tickets/{id}/resolve` acepta opcionalmente:
   ```json
   {
     "outcome": "SUCCESS",
     "resolution_notes": "...",
     "maintenance_type": "CORRECTIVO",
     "service_origin": "INTERNO",
     "materials_used": [
       {"product_id": 5, "quantity": 2, "notes": "Pintura blanca para pared norte"}
     ]
   }
   ```
3. El servicio llama a `WarehouseFifoService.consume(...)` con `source_app='maint'` y `source_ticket_id=ticket_id`.
4. Se crea `MaintTicketActionLog(action=WAREHOUSE_MATERIAL_ADDED, ...)`.
5. Si hay error de stock, la resolución **no se bloquea** — se muestra advertencia al usuario pero puede continuar.

### 7.1 Permisos de Almacén para técnicos de Mantenimiento

Los roles `maint_dispatcher` y `maint_technician` necesitan el permiso global:
- `warehouse.api.read` — Ver stock disponible
- `warehouse.api.consume` — Registrar material usado en resolución

Estos permisos se asignan en el DML del almacén global filtrando por departamento `equipment_maint`.

---

## 8. Fases de Implementación

---

### Fase 1 — Modelos de Datos y Migración Alembic ✅

**Objetivo:** Crear todas las tablas en la base de datos.

- [x] Crear `itcj2/apps/maint/` con estructura base
- [x] Crear `itcj2/apps/maint/models/category.py` → `MaintCategory`
- [x] Crear `itcj2/apps/maint/models/ticket.py` → `MaintTicket`
- [x] Crear `itcj2/apps/maint/models/ticket_technician.py` → `MaintTicketTechnician`
- [x] Crear `itcj2/apps/maint/models/technician_area.py` → `MaintTechnicianArea`
- [x] Crear `itcj2/apps/maint/models/status_log.py` → `MaintStatusLog`
- [x] Crear `itcj2/apps/maint/models/action_log.py` → `MaintTicketActionLog`
- [x] Crear `itcj2/apps/maint/models/comment.py` → `MaintComment`
- [x] Crear `itcj2/apps/maint/models/attachment.py` → `MaintAttachment`
- [x] Crear `itcj2/apps/maint/models/__init__.py` con todos los imports
- [ ] Generar migración: `alembic revision --autogenerate -m "add_maintenance_app"`
- [ ] Revisar y ajustar el script generado
- [ ] Ejecutar: `alembic upgrade head`

---

### Fase 2 — DML: Permisos, Roles y Datos Iniciales

**Objetivo:** Registrar la app, permisos, roles y categorías en la BD.

- [ ] Crear `database/DML/maint/01_add_maint_permissions.sql`
  - Registrar app `maint` en `core_apps` (si aplica)
  - 21 permisos con `ON CONFLICT DO NOTHING`
- [ ] Crear `database/DML/maint/02_assign_maint_permissions_to_roles.sql`
  - Crear roles globales: `dispatcher`, `tech_maint`
  - Asignar permisos a cada rol (ver tabla §3.3)
- [ ] Crear `database/DML/maint/03_seed_maint_categories.sql`
  - Insertar las 6 categorías con sus íconos y `field_template` (especialmente Transporte)
- [ ] Ejecutar los scripts en la BD

---

### Fase 3 — Schemas Pydantic ✅

**Objetivo:** Validación de requests y serialización de respuestas.

- [x] Crear `itcj2/apps/maint/schemas/tickets.py`:
  - `MaintTicketCreate` (title, description, category_id, location, custom_fields, attachments)
  - `MaintTicketUpdate` (campos editables antes de asignación)
  - `MaintTicketOut` (respuesta pública + técnicos activos)
  - `MaintTicketDetailOut` (incluye logs, comentarios, materiales usados)
  - `MaintResolveRequest` (outcome, resolution_notes, maintenance_type, service_origin, materials_used?)
  - `MaintRatingRequest` (rating_attention, rating_speed, rating_efficiency, rating_comment)
  - `MaintCancelRequest` (cancel_reason)
- [x] Crear `itcj2/apps/maint/schemas/assignments.py`:
  - `AssignTechnicianRequest` (user_id, notes)
  - `UnassignTechnicianRequest` (reason)
  - `MaintTicketTechnicianOut`
- [x] Crear `itcj2/apps/maint/schemas/categories.py`:
  - `CreateCategoryRequest`, `UpdateCategoryRequest`, `ToggleCategoryRequest`, `UpdateFieldTemplateRequest`
- [x] Crear `itcj2/apps/maint/schemas/comments.py`:
  - `CreateCommentRequest`
- [x] Crear `itcj2/apps/maint/schemas/technician_areas.py`:
  - `TechnicianAreaAssign`, `TechnicianAreaOut`, `TechnicianWithAreasOut`

---

### Fase 4 — Services (Lógica de Negocio) ✅

**Objetivo:** Implementar toda la lógica de negocio sin dependencias de FastAPI context.

- [x] Crear `itcj2/apps/maint/utils/ticket_number_generator.py`
  - `generate_maint_ticket_number(db)` → `MANT-{YEAR}-{SEQ:06d}`
- [x] Crear `itcj2/apps/maint/services/ticket_service.py`
  - `create_ticket`, `get_ticket`, `list_tickets`, `update_ticket`, `cancel_ticket`
  - `start_progress`, `resolve_ticket`, `rate_ticket`, `add_comment`
  - `_save_attachment` — Con compresión de imágenes
- [x] Crear `itcj2/apps/maint/services/assignment_service.py`
  - `assign_technician`, `unassign_technician`, `get_active_technicians`, `get_assignment_history`
- [x] Crear `itcj2/apps/maint/services/category_service.py`
  - CRUD de categorías y validación de `field_template`
- [x] Crear `itcj2/apps/maint/services/technician_service.py`
  - `list_technicians_with_areas`, `assign_area`, `remove_area`
- [ ] Crear `itcj2/apps/maint/services/notification_helper.py`
  - `notify_ticket_created`, `notify_technician_assigned`, `notify_ticket_resolved`
- [ ] Crear `itcj2/apps/maint/utils/custom_fields_validator.py`
  - Reutilizar la lógica de helpdesk adaptada (validar custom_fields contra field_template)

---

### Fase 5 — API Routes ✅ (parcial)

**Objetivo:** Exponer los endpoints REST.

- [x] Crear `itcj2/apps/maint/api/tickets.py` — CRUD + flujo de estados
- [x] Crear `itcj2/apps/maint/api/assignments.py` — Asignar/remover técnicos
- [x] Crear `itcj2/apps/maint/api/comments.py` — Comentarios
- [x] Crear `itcj2/apps/maint/api/categories.py` — Categorías (admin)
- [x] Crear `itcj2/apps/maint/api/technicians.py` — Gestión de áreas
- [ ] Crear `itcj2/apps/maint/api/dashboard.py` — Stats y dashboard
- [ ] Crear `itcj2/apps/maint/api/reports.py` — Reportes
- [x] Crear `itcj2/apps/maint/router.py` — Ensamblar todos los routers bajo `/api/maint/v2`
- [ ] Registrar `maint_router` en el router principal de la app ITCJ

---

### Fase 6 — Pages (Rutas de Páginas) ✅

**Objetivo:** Rutas FastAPI nativas con instancia propia de `Jinja2Templates` (sin tocar `itcj2/templates.py`).

- [x] Crear `itcj2/apps/maint/pages/router.py`
- [x] Crear `itcj2/apps/maint/pages/landing.py` — Landing `/mantenimiento/` con CTA por rol
- [x] Crear `itcj2/apps/maint/pages/tickets.py` — Lista, crear y detalle (stubs)
- [x] Crear `itcj2/apps/maint/pages/admin.py` — Categorías, áreas, reportes (stubs)
- [x] Crear `itcj2/apps/maint/pages/nav.py` — Instancia Jinja2Templates + `sv()` + nav por rol
- [ ] Registrar pages router en el router principal

---

### Fase 7 — Frontend: Templates ✅ (stubs completos)

**Objetivo:** Vistas HTML con Jinja2 + Bootstrap. Todas usan `sv()` / `sv_core()` para versioning.

- [x] Crear `itcj2/apps/maint/templates/maint/base_maint.html` — Layout base (topbar, sidebar, FAB, `{% block modals %}`)
- [x] Crear `itcj2/apps/maint/templates/maint/home_landing.html` — Hero + CTA por rol + tarjetas de servicio
- [x] Crear `itcj2/apps/maint/templates/maint/tickets/list.html` — stub
- [x] Crear `itcj2/apps/maint/templates/maint/tickets/create.html` — stub
- [x] Crear `itcj2/apps/maint/templates/maint/tickets/detail.html` — stub (pendiente tabs completos)
  - [ ] Tab: Información general
  - [ ] Tab: Técnicos asignados (dispatcher puede agregar/remover aquí)
  - [ ] Tab: Comentarios
  - [ ] Tab: Resolución + Material de almacén
  - [ ] Tab: Historial (StatusLog + ActionLog resumido)
- [x] Crear `itcj2/apps/maint/templates/maint/admin/categories.html` — stub
- [ ] Crear `itcj2/apps/maint/templates/maint/admin/areas.html` — stub ✅ / implementación pendiente
- [x] Crear `itcj2/apps/maint/templates/maint/admin/reports.html` — stub

---

### Fase 8 — Frontend: JavaScript y CSS ✅ (base completa)

**Objetivo:** Interactividad y estilos visuales.
**Paleta definida:** Steel Blue-Gray — `#546E7A` (primary), `#37474F` (dark), `#263238` (darker), `#ECEFF1` (light). Prefijo CSS: `.mn-`

- [x] Crear `itcj2/apps/maint/static/css/maint.css` — Variables, topbar, sidebar, badges de estado/prioridad, tarjetas de ticket, SLA, skeleton
- [x] Crear `itcj2/apps/maint/static/css/home_landing.css` — Hero, CTA card, service cards
- [x] Crear `itcj2/apps/maint/static/js/maint-utils.js`
  - `window.MaintUtils = { toast, confirm, alert, loading, api }`
  - Sin `alert()` / `confirm()` nativos — todo en modales Bootstrap inyectados programáticamente
- [x] Crear `itcj2/apps/maint/static/js/shared/base.js`
  - Logout (POST API + postMessage al iframe padre)
  - Init FAB con colores de marca (`#546E7A` / `#37474F`)
- [ ] Crear `itcj2/apps/maint/static/js/tickets-list.js`
- [ ] Crear `itcj2/apps/maint/static/js/ticket-create.js`
- [ ] Crear `itcj2/apps/maint/static/js/ticket-detail.js`
- [ ] Crear `itcj2/apps/maint/static/js/ticket-assignment.js`
- [ ] Crear `itcj2/apps/maint/static/js/ticket-resolution.js`
- [ ] Crear `itcj2/apps/maint/static/js/admin/admin-categories.js`

---

### Fase 9 — Integración de Almacén Global

**Objetivo:** Conectar la resolución de tickets con el almacén global.

> Requiere que `PLAN_WAREHOUSE_GLOBAL.md` Fases 1–4 estén completadas primero.

- [ ] Actualizar `MaintResolveRequest` schema para incluir `materials_used?: List[MaterialUseRequest]`
- [ ] En `ticket_service.resolve_ticket()`: llamar a `WarehouseFifoService.consume()` para cada material
- [ ] Crear endpoint: `GET /api/maint/v1/tickets/{id}/materials` → materiales usados en el ticket
- [ ] Implementar tab "Resolución" en `ticket-detail.js` con autocomplete de productos del almacén
- [ ] Ejecutar DML: asignar permisos `warehouse.api.read` y `warehouse.api.consume` a roles `maint_dispatcher` y `maint_technician`

---

### Fase 10 — Notificaciones y Navegación ✅ (parcial)

**Objetivo:** Integrar en el sistema de navegación global y notificaciones.

- [x] `itcj2/apps/maint/pages/nav.py` — navegación por rol (`_build_maint_nav`)
- [x] Ícono de Mantenimiento en `core/templates/core/dashboard/dashboard.html` (`bi-tools`, `#546E7A`)
- [x] Ícono pinned en taskbar del dashboard (`wrench` Lucide)
- [x] Registrado en `dashboard.js` — `desktopItems` + `getAppConfig` con `iframeSrc: "/mantenimiento/"`
- [x] FAB de notificaciones con colores de marca (filtra solo notificaciones `app_name='maint'`)
- [ ] Conectar `notification_helper.py` con el sistema de notificaciones/email existente
- [ ] Registrar pages router en el router principal de itcj2

---

## 9. Estructura de Archivos

```
itcj2/apps/maint/
├── __init__.py
├── router.py                           (API router assembly)
├── models/
│   ├── __init__.py
│   ├── category.py                     (MaintCategory)
│   ├── ticket.py                       (MaintTicket)
│   ├── ticket_technician.py            (MaintTicketTechnician)
│   ├── technician_area.py              (MaintTechnicianArea)
│   ├── status_log.py                   (MaintStatusLog)
│   ├── action_log.py                   (MaintTicketActionLog)
│   ├── comment.py                      (MaintComment)
│   └── attachment.py                   (MaintAttachment)
├── schemas/
│   ├── tickets.py
│   ├── assignments.py
│   ├── categories.py
│   ├── comments.py
│   └── technician_areas.py
├── services/
│   ├── ticket_service.py
│   ├── assignment_service.py
│   ├── category_service.py
│   ├── technician_service.py
│   └── notification_helper.py
├── api/
│   ├── __init__.py
│   ├── tickets.py
│   ├── assignments.py
│   ├── comments.py
│   ├── categories.py
│   ├── technicians.py
│   ├── dashboard.py
│   └── reports.py
├── pages/
│   ├── router.py
│   ├── landing.py
│   ├── tickets.py
│   ├── admin.py
│   └── nav.py
├── utils/
│   ├── ticket_number_generator.py      (MANT-YEAR-SEQ)
│   └── custom_fields_validator.py
├── static/
│   ├── css/
│   │   ├── maint.css                   ✅ (variables, topbar, sidebar, badges, skeleton)
│   │   └── home_landing.css            ✅
│   └── js/
│       ├── maint-utils.js              ✅ (toast, confirm, alert, loading, apiFetch)
│       ├── shared/
│       │   └── base.js                 ✅ (logout + FAB init con colores de marca)
│       ├── tickets-list.js             (pendiente)
│       ├── ticket-create.js            (pendiente)
│       ├── ticket-detail.js            (pendiente)
│       ├── ticket-assignment.js        (pendiente)
│       ├── ticket-resolution.js        (pendiente)
│       └── admin/
│           └── admin-categories.js     (pendiente)
└── templates/maint/
    ├── base_maint.html                 ✅
    ├── home_landing.html               ✅
    ├── tickets/
    │   ├── list.html                   ✅ (stub)
    │   ├── create.html                 ✅ (stub)
    │   └── detail.html                 ✅ (stub)
    └── admin/
        ├── categories.html             ✅ (stub)
        ├── areas.html                  ✅ (stub)
        └── reports.html                ✅ (stub)

database/DML/maint/
    ├── 01_add_maint_permissions.sql
    ├── 02_assign_maint_permissions_to_roles.sql
    └── 03_seed_maint_categories.sql

migrations/versions/
    └── <hash>_add_maintenance_app.py   (via alembic)
```

**Archivos del proyecto a modificar:**
- `itcj2/router.py` (o equivalente global) — Registrar `maint_router`
- `itcj2/pages/router.py` (o equivalente global) — Registrar pages de maint
- `itcj2/models/__init__.py` (o equivalente) — Importar modelos de maint para Alembic

---

## 10. Convenciones y Estándares

### SQL (DML)
- Usar `DO $$ DECLARE ... BEGIN ... END $$;` con lookup de `app_id`
- `ON CONFLICT ... DO NOTHING` para idempotencia
- `RAISE NOTICE` para feedback durante ejecución
- Nomenclatura: `maint.modulo.tipo.accion`

### SQLAlchemy (Modelos)
- Prefijo de tabla: `maint_`
- FKs referenciadas por nombre de tabla string (no clase) para evitar imports circulares
- `created_at` con `server_default=func.now()`; `updated_at` con `onupdate=func.now()`
- Índices nombrados explícitamente: `ix_maint_tickets_status_created`
- Relaciones con `back_populates` (no `backref`)

### Python (Services y API)
- Services sin dependencia de request context (reciben `db: Session` como parámetro)
- Un service por dominio (ticket, assignment, category, technician)
- Errores con `HTTPException` y códigos apropiados
- Tipos de retorno con schemas Pydantic en todas las rutas (`response_model=`)
- Dependencias de autenticación/permisos inyectadas vía `Depends()`

### JavaScript
- Patrón IIFE con `'use strict'`
- Namespace global: `window.MaintUtils` para funciones compartidas
- Variables Jinja solo para IDs/datos del servidor; resto en archivos externos
- Sin `alert()` / `confirm()` nativos — usar `MaintUtils.alert()` / `MaintUtils.confirm()`
- Rutas de estáticos directas: `/static/maint/...?v={{ sv('...') }}` (no `url_for`)

### CSS
- Variables de Bootstrap 5.3.0 donde sea posible
- Prefijo `.mn-` para clases propias del módulo
- **Paleta definida:** `#546E7A` primary · `#37474F` dark · `#263238` darker · `#ECEFF1` light

---

*Fin del documento — PLAN_MAINTENANCE_APP.md*

# Plan de Mejoras al Módulo de Inventario (Helpdesk)

**Fecha:** 2026-03-06
**Rama:** `feature/refactor-fastapi` → nueva rama `feature/inventory-improvements`
**Scope:** `itcj2/apps/helpdesk` + `database/DML/helpdesk/inventory/`

---

## Resumen de cambios

| # | Cambio | Impacto |
|---|--------|---------|
| 1 | Nuevos campos de identificación en equipos (supplier_serial, itcj_serial, id_tecnm) | Modelo + migración + API + UI |
| 2 | Registro masivo con listas de números de serie | API bulk + template |
| 3 | Transferencia masiva de departamento | Nuevo endpoint + UI en 2 páginas |
| 4 | Sistema de solicitudes de baja (retirement requests) | 2 nuevos modelos + endpoints + UI completa |

---

## Fase 1 — Nuevos campos de identificación en equipos

### 1.1 Cambios en el modelo `InventoryItem`

**Archivo:** `itcj2/apps/helpdesk/models/inventory_item.py`

| Campo actual | Cambio | Nuevo campo | Tipo | Restricciones |
|---|---|---|---|---|
| `serial_number` | Renombrar | `supplier_serial` | `String(150)` | `unique=True, nullable=True, index=True` |
| — | Agregar | `itcj_serial` | `String(150)` | `unique=True, nullable=True, index=True` |
| — | Agregar | `id_tecnm` | `String(100)` | `unique=True, nullable=True, index=True` |

**Descripción de cada campo:**
- `supplier_serial`: Número de serie del fabricante/proveedor (el que viene grabado en el equipo o en la caja). Renombrado desde `serial_number` existente.
- `itcj_serial`: Número de serie / número de activo asignado por el Departamento de Compras del ITCJ. Se ingresa manualmente.
- `id_tecnm`: Identificador con el que el equipo está registrado en el sistema nacional del TecNM. Permite reportar al TecNM el estado del equipo.

### 1.2 Migración de base de datos (Alembic)

Los cambios de esquema se hacen con Alembic, **no con archivos SQL**.

**Comando para generar la migración:**
```bash
alembic revision --autogenerate -m "rename_serial_number_add_itcj_serial_id_tecnm"
```

**Contenido esperado del script Alembic generado (`upgrade`):**
- `op.alter_column('helpdesk_inventory_items', 'serial_number', new_column_name='supplier_serial')`
- `op.add_column('helpdesk_inventory_items', sa.Column('itcj_serial', sa.String(150), unique=True, nullable=True))`
- `op.add_column('helpdesk_inventory_items', sa.Column('id_tecnm', sa.String(100), unique=True, nullable=True))`
- `op.create_index('ix_helpdesk_inventory_items_itcj_serial', 'helpdesk_inventory_items', ['itcj_serial'])`
- `op.create_index('ix_helpdesk_inventory_items_id_tecnm', 'helpdesk_inventory_items', ['id_tecnm'])`

Para los nuevos modelos `InventoryRetirementRequest` e `InventoryRetirementRequestItem` también se genera su migración con autogenerate después de crear los modelos.

### 1.3 Cambios en validadores

**Archivo:** `itcj2/apps/helpdesk/utils/inventory_validators.py`

- Renombrar `validate_serial_number()` → `validate_supplier_serial()`
- Agregar `validate_itcj_serial()` — unicidad en tabla
- Agregar `validate_id_tecnm()` — unicidad en tabla
- Los 3 son opcionales (nullable), pero si se proporcionan deben ser únicos

### 1.4 Cambios en el servicio

**Archivo:** `itcj2/apps/helpdesk/services/inventory_service.py`

- `create_item()`: aceptar `supplier_serial`, `itcj_serial`, `id_tecnm` en lugar de `serial_number`
- `update_item()`: incluir los 3 nuevos campos como actualizables
- En el historial (`SPECS_UPDATED`): registrar cambios en cualquiera de los 3 campos

### 1.5 Cambios en los endpoints

**Archivo:** `itcj2/apps/helpdesk/api/inventory/items.py`

- Actualizar schemas de request/response: reemplazar `serial_number` por `supplier_serial`, agregar `itcj_serial` e `id_tecnm`
- Actualizar filtros de búsqueda: permitir buscar por cualquiera de los 3

### 1.6 Cambios en templates

**Archivos afectados:**
- `item_create.html`: Agregar 3 campos en el formulario de creación individual
- `item_detail.html`: Mostrar los 3 campos en la sección de información del equipo
- `items_list.html`: Actualizar columna "Número de Serie" para mostrar los campos disponibles (tooltip con los 3)
- `verification.html`: Mostrar y permitir editar los 3 campos durante verificación

---

## Fase 2 — Registro masivo con listas de números de serie

### 2.1 Descripción del flujo

En la página de registro masivo (`/inventory/bulk-register`), además de los campos actuales, se añade una sección opcional "Asignar identificadores" con 3 textareas donde el usuario puede pegar listas de números de serie. El sistema mapea posicionalmente: equipo #1 recibe serial[0], equipo #2 recibe serial[1], etc.

Si una lista tiene menos entradas que equipos, los equipos restantes quedan sin ese identificador.
Si una lista tiene más entradas que equipos, las entradas sobrantes se ignoran (con advertencia).

### 2.2 Separadores soportados

El usuario selecciona el separador de su lista:
- **Coma** (`,`) — ej: `SN001,SN002,SN003`
- **Punto y coma** (`;`)
- **Espacio** — ej: `SN001 SN002 SN003`
- **Enter / salto de línea** (uno por renglón) — ej:
  ```
  SN001
  SN002
  SN003
  ```
- **Automático** — detecta el separador más común en el texto pegado

### 2.3 Cambios en el servicio de bulk

**Archivo:** `itcj2/apps/helpdesk/services/inventory_bulk_service.py`

Agregar método `parse_serial_list(raw_text: str, separator: str) -> list[str]`:
- Limpia espacios en blanco al inicio/fin de cada entrada
- Elimina entradas vacías
- Retorna lista ordenada de strings

Modificar `create_bulk_items()`:
- Aceptar `supplier_serial_list`, `itcj_serial_list`, `id_tecnm_list` (opcionales)
- Validar unicidad de cada serial antes de comenzar el insert (para fallar rápido si hay duplicados)
- Asignar posicionalmente durante la creación de cada equipo

### 2.4 Cambios en el endpoint bulk

**Archivo:** `itcj2/apps/helpdesk/api/inventory/bulk.py`

- `POST /bulk/validate`: Incluir validación de listas de seriales (unicidad, tamaño vs cantidad de equipos)
- `POST /bulk/create`: Aceptar los 3 campos de listas
- Respuesta de validación incluye advertencias si listas tienen longitud distinta a la cantidad de equipos

### 2.5 Cambios en template

**Archivo:** `itcj2/apps/helpdesk/templates/helpdesk/inventory/item_create.html` (sección bulk)

Agregar sección colapsable "Identificadores de serie (opcional)":
- Selector de separador (radio buttons o dropdown)
- Textarea: Lista de seriales proveedor
- Textarea: Lista de seriales ITCJ/Compras
- Textarea: Lista de IDs TecNM
- Contador en tiempo real: "X de Y equipos tendrán serial proveedor asignado"

---

## Fase 3 — Transferencia masiva entre departamentos

### 3.1 Nuevo endpoint

**Archivo a crear:** `itcj2/apps/helpdesk/api/inventory/bulk_transfer.py`

**Endpoint:** `POST /api/help-desk/v2/inventory/items/bulk-transfer`

**Permiso:** `helpdesk.inventory.api.transfer` (ya existe)

**Request body:**
```json
{
  "item_ids": [1, 2, 3, ...],
  "target_department_id": 5,
  "notes": "Texto opcional explicando la razón del traslado"
}
```

**Lógica:**
1. Validar que el usuario tenga permiso `helpdesk.inventory.api.transfer`
2. Validar que todos los `item_ids` existan y estén activos
3. Validar que `target_department_id` exista
4. Por cada equipo:
   - Guardar `old_department_id`
   - Actualizar `department_id` → `target_department_id`
   - Si el equipo tiene `group_id` y el grupo pertenece al departamento origen, desvincular (`group_id = None`)
   - Crear entrada en `InventoryHistory` con:
     - `event_type = 'TRANSFERRED'`
     - `old_value = { "department_id": old_id, "department_name": old_name }`
     - `new_value = { "department_id": new_id, "department_name": new_name }`
     - `notes = [notas del usuario]`
5. Respuesta: lista de equipos transferidos con éxito + lista de errores (si alguno falló)

### 3.2 Cambios en templates

#### Lista de inventarios (`items_list.html`)
- Agregar checkbox en cada fila de equipo (visible para usuarios con permiso `helpdesk.inventory.api.transfer`)
- Agregar barra de acciones masivas (aparece al seleccionar ≥1 equipo):
  - Botón "Transferir a departamento" → abre modal con selector de departamento destino + campo de notas
  - Contador: "X equipos seleccionados"
- El modal confirma la acción y muestra departamento origen → destino

#### Verificación (`verification.html`)
- Agregar checkbox en cada fila de equipo (misma lógica de permisos)
- Agregar barra de acciones masivas con botón "Transferir seleccionados"
- Mismo modal que en la lista

---

## Fase 4 — Sistema de solicitudes de baja (Retirement Requests)

### 4.1 Nuevos modelos

#### Modelo: `InventoryRetirementRequest`

**Archivo a crear:** `itcj2/apps/helpdesk/models/inventory_retirement_request.py`
**Tabla:** `helpdesk_inventory_retirement_requests`

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | Integer PK | |
| `folio` | String(20), unique | Auto-generado: `BAJA-{YEAR}-{SEQUENCE}`, ej: `BAJA-2026-001` |
| `status` | String(20) | `DRAFT`, `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED` |
| `reason` | Text, required | Justificación de la baja |
| `requested_by_id` | FK → User | Usuario que creó la solicitud |
| `reviewed_by_id` | FK → User, nullable | Admin que aprobó/rechazó |
| `reviewed_at` | DateTime, nullable | Fecha de revisión |
| `review_notes` | Text, nullable | Comentarios del revisor |
| `document_path` | String(500), nullable | Ruta del archivo adjunto subido |
| `document_original_name` | String(255), nullable | Nombre original del archivo adjunto |
| `format_generated_at` | DateTime, nullable | Cuándo se generó el formato PDF interno |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

**Estados del flujo:**
```
DRAFT → PENDING → APPROVED → (equipos dados de baja)
                ↘ REJECTED
DRAFT/PENDING → CANCELLED (por el solicitante)
```

#### Modelo: `InventoryRetirementRequestItem`

**Archivo a crear:** `itcj2/apps/helpdesk/models/inventory_retirement_request_item.py`
**Tabla:** `helpdesk_inventory_retirement_request_items`

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | Integer PK | |
| `request_id` | FK → InventoryRetirementRequest | |
| `item_id` | FK → InventoryItem | |
| `item_notes` | Text, nullable | Nota específica de por qué este equipo en particular se da de baja |
| UniqueConstraint | `(request_id, item_id)` | Un equipo no puede aparecer dos veces en la misma solicitud |

**Restricción adicional de negocio:** Un equipo activo solo puede estar en una solicitud en estado `DRAFT` o `PENDING` a la vez. No puede ser incluido en 2 solicitudes simultáneas.

### 4.2 Nuevo servicio

**Archivo a crear:** `itcj2/apps/helpdesk/services/inventory_retirement_service.py`

| Método | Descripción |
|---|---|
| `generate_folio(db)` | Genera `BAJA-{YEAR}-{SEQ}` con secuencia del año actual |
| `create_request(db, data, requested_by_id, ip)` | Crea solicitud en estado `DRAFT` |
| `add_item(db, request_id, item_id, notes, user_id)` | Agrega equipo a solicitud en DRAFT |
| `remove_item(db, request_id, item_id, user_id)` | Quita equipo de solicitud en DRAFT |
| `submit_request(db, request_id, user_id, ip)` | Cambia estado DRAFT → PENDING |
| `approve_request(db, request_id, admin_id, notes, ip)` | Aprueba y ejecuta bajas masivas |
| `reject_request(db, request_id, admin_id, notes, ip)` | Rechaza la solicitud |
| `cancel_request(db, request_id, user_id, ip)` | Cancela (solo DRAFT o PENDING propios) |
| `attach_document(db, request_id, file, user_id)` | Adjunta PDF/documento a la solicitud |
| `generate_format(db, request_id)` | Genera PDF del formato oficial de baja (**PLACEHOLDER** hasta tener el formato) |
| `validate_items_not_in_pending(db, item_ids)` | Verifica que los equipos no estén en otra solicitud activa |

**Lógica de `approve_request()`:**
1. Cambiar estado → `APPROVED`, registrar `reviewed_by_id`, `reviewed_at`, `review_notes`
2. Para cada equipo en la solicitud, llamar a `inventory_service.deactivate_item()` con:
   - `reason = f"Solicitud de baja aprobada. Folio: {folio}. {review_notes}"`
   - `ip_address` del admin
3. El historial `DEACTIVATED` de cada equipo referenciará el folio de la solicitud

### 4.3 Nuevos endpoints

**Archivo a crear:** `itcj2/apps/helpdesk/api/inventory/retirement_requests.py`

**Prefijo:** `/api/help-desk/v2/inventory/retirement-requests`

| Método | Ruta | Permiso | Descripción |
|---|---|---|---|
| GET | `/` | `helpdesk.inventory.retirement.api.read` | Listar solicitudes (admin ve todas, otros solo las propias) |
| POST | `/` | `helpdesk.inventory.retirement.api.create` | Crear nueva solicitud (DRAFT) |
| GET | `/{request_id}` | `helpdesk.inventory.retirement.api.read` | Detalle de solicitud |
| POST | `/{request_id}/items` | `helpdesk.inventory.retirement.api.create` | Agregar equipo(s) a solicitud |
| DELETE | `/{request_id}/items/{item_id}` | `helpdesk.inventory.retirement.api.create` | Quitar equipo de solicitud |
| POST | `/{request_id}/submit` | `helpdesk.inventory.retirement.api.create` | Enviar solicitud (DRAFT → PENDING) |
| POST | `/{request_id}/approve` | `helpdesk.inventory.retirement.api.approve` | Aprobar solicitud (admin) |
| POST | `/{request_id}/reject` | `helpdesk.inventory.retirement.api.approve` | Rechazar solicitud (admin) |
| POST | `/{request_id}/cancel` | `helpdesk.inventory.retirement.api.create` | Cancelar solicitud propia |
| POST | `/{request_id}/attach` | `helpdesk.inventory.retirement.api.create` | Subir documento adjunto |
| GET | `/{request_id}/generate-format` | `helpdesk.inventory.retirement.api.create` | Generar PDF del formato (**PLACEHOLDER**) |

### 4.4 Nuevas rutas de página

**Archivo:** `itcj2/apps/helpdesk/pages/inventory.py`

| Ruta | Permiso | Descripción |
|---|---|---|
| `/inventory/retirement-requests` | `helpdesk.inventory.retirement.page.list` | Lista de solicitudes de baja |
| `/inventory/retirement-requests/create` | `helpdesk.inventory.retirement.page.create` | Crear nueva solicitud |
| `/inventory/retirement-requests/{id}` | `helpdesk.inventory.retirement.page.detail` | Detalle + gestión de solicitud |

### 4.5 Nuevos templates

| Template | Descripción |
|---|---|
| `inventory/retirement_requests_list.html` | Lista de solicitudes con filtros por estado, fecha, solicitante |
| `inventory/retirement_request_create.html` | Formulario: razón + buscar/agregar equipos |
| `inventory/retirement_request_detail.html` | Detalle: lista de equipos, documentos, historial de estado, acciones (aprobar/rechazar/cancelar) |

### 4.6 Cambios en flujo de baja existente

**Impacto en `item_detail.html` y `items_list.html`:**
- El botón "Dar de baja" ya no llama directamente al endpoint `deactivate`. En su lugar abre un modal que permite:
  1. **Crear nueva solicitud de baja** con ese equipo pre-cargado
  2. **Agregar a solicitud existente en DRAFT** (si el usuario tiene una abierta)
- El endpoint `POST /items/{item_id}/deactivate` **se mantiene** pero solo es accesible con un nuevo permiso de bypass `helpdesk.inventory.api.delete.direct` (para emergencias o migraciones). El flujo normal será siempre vía solicitud.

**Impacto en `verification.html`:**
- El botón de baja en verificación también redirige al flujo de solicitud

---

## Fase 5 — Permisos nuevos (DML SQL)

### 5.1 Permisos nuevos a crear

**Archivo a crear:** `database/DML/helpdesk/inventory/04_add_retirement_request_permissions.sql`

```
Nomenclatura: helpdesk.inventory.retirement.{tipo}.{accion}

Nuevos permisos:
  helpdesk.inventory.retirement.page.list    → Ver lista de solicitudes de baja
  helpdesk.inventory.retirement.page.create  → Ver página crear solicitud
  helpdesk.inventory.retirement.page.detail  → Ver detalle de solicitud
  helpdesk.inventory.retirement.api.read     → Leer solicitudes vía API
  helpdesk.inventory.retirement.api.create   → Crear/editar solicitudes propias vía API
  helpdesk.inventory.retirement.api.approve  → Aprobar o rechazar solicitudes (admin)
  helpdesk.inventory.retirement.api.cancel   → Cancelar solicitudes propias
  helpdesk.inventory.inventory.api.delete.direct → Dar de baja directa sin solicitud (bypass, solo admin emergencias)
```

### 5.2 Asignación de permisos a roles

**Archivo a crear:** `database/DML/helpdesk/inventory/05_assign_retirement_permissions_to_roles.sql`

| Permiso | admin | tech_desarrollo | tech_soporte | secretary | department_head | staff |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `retirement.page.list` | ✅ | ✅ | ✅ | — | — | — |
| `retirement.page.create` | ✅ | ✅ | ✅ | — | — | — |
| `retirement.page.detail` | ✅ | ✅ | ✅ | — | — | — |
| `retirement.api.read` | ✅ | ✅ | ✅ | — | — | — |
| `retirement.api.create` | ✅ | ✅ | ✅ | — | — | — |
| `retirement.api.approve` | ✅ | — | — | — | — | — |
| `retirement.api.cancel` | ✅ | ✅ | ✅ | — | — | — |
| `api.delete.direct` | ✅ | — | — | — | — | — |

> **Nota:** Los permisos se asignan a roles como base. Para usuarios de servicio social se les asignará el permiso `retirement.api.create` y `retirement.page.*` directamente a su usuario o mediante un rol específico de "servicio_social" si se crea en el futuro.

---

## Fase 6 — Generación de formato de baja (PLACEHOLDER)

> ⚠️ **Esta fase es un PLACEHOLDER** hasta que se comparta el formato oficial del ITCJ/TecNM.

### 6.1 Lo que se implementará cuando se tenga el formato

- Librería: `reportlab` o `WeasyPrint` para generación de PDF
- El endpoint `GET /retirement-requests/{id}/generate-format` retornará el PDF como descarga
- El formato incluirá (campos a confirmar con el documento oficial):
  - Encabezado institucional (logo ITCJ + TecNM)
  - Folio de la solicitud
  - Fecha de solicitud
  - Solicitante (nombre, puesto, departamento)
  - Tabla de equipos: Número de inventario, categoría, marca/modelo, supplier_serial, itcj_serial, id_tecnm, razón de baja
  - Motivo general de baja
  - Espacios para firmas: Solicitante, Jefe de Departamento, Responsable de Inventario, Dirección
- Una vez aprobada la solicitud se guardará el PDF generado en el servidor junto al folio

### 6.2 Por ahora

El endpoint existe pero retorna `501 Not Implemented` con mensaje:
```json
{ "message": "Generación de formato pendiente. Adjunta el documento manualmente." }
```

---

## Orden de implementación recomendado

```
Fase 1 → Fase 1.x (validadores + service + API) → Tests básicos
    ↓
Fase 2 → Bulk serial lists → Tests
    ↓
Fase 3 → Bulk transfer endpoint + UI
    ↓
Fase 5 → SQL permisos (antes de Fase 4 porque Fase 4 los requiere)
    ↓
Fase 4.1-4.2 → Modelos + servicio de retirement requests
    ↓
Fase 4.3 → Endpoints API
    ↓
Fase 4.4-4.5 → Rutas de página + templates
    ↓
Fase 4.6 → Modificar flujo de baja existente
    ↓
Fase 6 → Cuando se comparta el formato oficial
```

---

## Archivos a crear (resumen)

### Modelos nuevos
- `itcj2/apps/helpdesk/models/inventory_retirement_request.py`
- `itcj2/apps/helpdesk/models/inventory_retirement_request_item.py`

### Servicios nuevos
- `itcj2/apps/helpdesk/services/inventory_retirement_service.py`

### API nuevos
- `itcj2/apps/helpdesk/api/inventory/bulk_transfer.py`
- `itcj2/apps/helpdesk/api/inventory/retirement_requests.py`

### Templates nuevos
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/retirement_requests_list.html`
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/retirement_request_create.html`
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/retirement_request_detail.html`

### Migraciones Alembic (DDL)
- `alembic revision --autogenerate` tras modificar `inventory_item.py` → rename + 2 columnas nuevas
- `alembic revision --autogenerate` tras crear los modelos `InventoryRetirementRequest` e `InventoryRetirementRequestItem`

### DML/SQL nuevos (solo datos, no DDL)
- `database/DML/helpdesk/inventory/04_add_retirement_request_permissions.sql`
- `database/DML/helpdesk/inventory/05_assign_retirement_permissions_to_roles.sql`

### Archivos modificados (principales)
- `itcj2/apps/helpdesk/models/inventory_item.py` — renombrar + 2 campos nuevos
- `itcj2/apps/helpdesk/utils/inventory_validators.py` — validadores nuevos seriales
- `itcj2/apps/helpdesk/services/inventory_service.py` — soportar 3 seriales
- `itcj2/apps/helpdesk/services/inventory_bulk_service.py` — listas de seriales
- `itcj2/apps/helpdesk/api/inventory/items.py` — schemas actualizados
- `itcj2/apps/helpdesk/api/inventory/bulk.py` — listas de seriales
- `itcj2/apps/helpdesk/api/inventory/__init__.py` — registrar nuevos routers
- `itcj2/apps/helpdesk/pages/inventory.py` — rutas retirement requests
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/item_create.html`
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/item_detail.html`
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/items_list.html`
- `itcj2/apps/helpdesk/templates/helpdesk/inventory/verification.html`

---

## Notas y consideraciones

1. **Migración sin pérdida de datos:** El rename de `serial_number` → `supplier_serial` preserva todos los datos existentes. Solo es un `ALTER TABLE ... RENAME COLUMN`.

2. **Unicidad de los 3 seriales:** Los 3 son `UNIQUE` en BD, pero `nullable`. Dos equipos pueden no tener `id_tecnm` (ambos NULL), ya que `UNIQUE` en SQL permite múltiples NULLs en PostgreSQL.

3. **Búsqueda en lista:** Los 3 campos deben incluirse en el buscador global de inventario (el campo `search` del endpoint `GET /items`).

4. **Formato oficial de baja:** Cuando se comparta el documento, determinar si se usa `reportlab` (más control sobre diseño exacto) o `WeasyPrint` (renderiza HTML→PDF, más fácil de maquetar). Se recomienda `WeasyPrint` para replicar fielmente un formato con logotipos y tablas.

5. **Almacenamiento de archivos adjuntos:** Los documentos adjuntos a las solicitudes de baja se guardan en el sistema de archivos del servidor en una carpeta `uploads/helpdesk/retirement_requests/{folio}/`. El `document_path` en la BD guarda la ruta relativa.

6. **Equipo en múltiples solicitudes:** Un equipo ACTIVO no puede estar en 2 solicitudes simultáneas en estado DRAFT/PENDING. Sí puede aparecer en solicitudes históricas (APPROVED/REJECTED/CANCELLED). Esta validación va en `validate_items_not_in_pending()` del servicio.

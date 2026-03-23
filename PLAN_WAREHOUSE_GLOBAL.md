# Plan: Módulo de Almacén Global (Shared Warehouse)

> **Rama objetivo:** `feature/warehouse-global`
> **Fecha de planeación:** 2026-03-09
> **Supersede:** `PLAN_WAREHOUSE_MODULE.md` (plan original solo para helpdesk, ahora descartado)
> **Decisión arquitectónica:** Almacén compartido entre múltiples apps (helpdesk, maint, y cualquier futura).

---

## Tabla de Contenidos

1. [Decisión Arquitectónica y Razonamiento](#1-decisión-arquitectónica-y-razonamiento)
2. [Arquitectura de Datos](#2-arquitectura-de-datos)
3. [Sistema de Permisos](#3-sistema-de-permisos)
4. [Lógica de Negocio](#4-lógica-de-negocio)
5. [API Endpoints](#5-api-endpoints)
6. [Páginas Frontend (Admin)](#6-páginas-frontend-admin)
7. [Integración por App Consumidora](#7-integración-por-app-consumidora)
8. [Fases de Implementación](#8-fases-de-implementación)
9. [Estructura de Archivos](#9-estructura-de-archivos)
10. [Convenciones y Estándares](#10-convenciones-y-estándares)

---

## 1. Decisión Arquitectónica y Razonamiento

### 1.1 ¿Por qué Global?

| Criterio | Almacén por App | **Almacén Global (elegido)** |
|---|---|---|
| Lógica FIFO | Duplicada en cada app | Una sola implementación |
| Reportes de stock | Silos separados, imposible ver total | Vista consolidada de todo el stock |
| Productos compartidos | No posible (ej: un cable que usa CC y Mant) | Posible, separado por departamento |
| Mantenimiento de código | 2× archivos de modelos, services, schemas | 1× centralizado |
| Nuevas apps futuras | Requiere duplicar todo otra vez | Solo agregar integración |
| Separación lógica | Física (tablas distintas) | Por `department_code` + permisos |

### 1.2 Separación por Departamento

Los productos del almacén están asociados a un departamento vía `department_code`. Esto permite:
- Filtrar stock visible según el rol/departamento del usuario
- Un admin de helpdesk solo ve stock de `comp_center`
- Un admin de mantenimiento solo ve stock de `equipment_maint`
- Un superadmin puede ver todo

### 1.3 Relación Polimórfica para Tickets

El almacén necesita registrar qué ticket consumió qué material, pero los tickets viven en
tablas de diferentes apps (`helpdesk_ticket`, `maint_tickets`). Se usa un patrón polimórfico
con `source_app` + `source_ticket_id` en lugar de múltiples FKs nullable:

```
-- En lugar de:
helpdesk_ticket_id FK → helpdesk_ticket NULLABLE
maint_ticket_id    FK → maint_tickets NULLABLE

-- Se usa:
source_app         VARCHAR(30)   -- 'helpdesk' | 'maint'
source_ticket_id   INTEGER       -- ID en la tabla correspondiente
```

La integridad referencial se mantiene a nivel de aplicación (el service valida que
el `source_ticket_id` exista antes de crear el registro).

---

## 2. Arquitectura de Datos

> **Convención de prefijo:** `warehouse_*`
> **DDL:** Vía migraciones Alembic (nunca SQL directo para DDL)

### 2.1 Modelos SQLAlchemy

---

#### Modelo 1: `WarehouseCategory` → `warehouse_categories`

```
id              INTEGER PK
name            VARCHAR(100) NOT NULL
description     TEXT
icon            VARCHAR(50) DEFAULT 'bi-box-seam'
department_code VARCHAR(50) NOT NULL      -- 'comp_center' | 'equipment_maint' | null para global
                                          -- NULL = categoría visible para todos los admins
is_active       BOOLEAN DEFAULT TRUE
display_order   INTEGER DEFAULT 0
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP DEFAULT NOW()

INDEX(department_code, is_active)
```

Relaciones:
- `subcategories` → List[WarehouseSubcategory] (cascade delete)

---

#### Modelo 2: `WarehouseSubcategory` → `warehouse_subcategories`

```
id              INTEGER PK
category_id     FK → warehouse_categories NOT NULL
name            VARCHAR(100) NOT NULL
description     TEXT
is_active       BOOLEAN DEFAULT TRUE
display_order   INTEGER DEFAULT 0
created_at      TIMESTAMP DEFAULT NOW()

UNIQUE(category_id, name)
INDEX(category_id, is_active)
```

Relaciones:
- `category` → WarehouseCategory
- `products` → List[WarehouseProduct]

---

#### Modelo 3: `WarehouseProduct` → `warehouse_products`

```
id                      INTEGER PK
code                    VARCHAR(20) UNIQUE NOT NULL       -- auto-gen: WAR-001
name                    VARCHAR(150) NOT NULL
description             TEXT
subcategory_id          FK → warehouse_subcategories NOT NULL
department_code         VARCHAR(50) NOT NULL              -- Dpto dueño del producto
unit_of_measure         VARCHAR(30) NOT NULL              -- pieza, metro, rollo, kit, par...
icon                    VARCHAR(50) DEFAULT 'bi-box'
is_active               BOOLEAN DEFAULT TRUE

-- Restock
restock_point_auto      NUMERIC(10,2) DEFAULT 0
restock_point_override  NUMERIC(10,2) NULLABLE
restock_lead_time_days  INTEGER DEFAULT 7
last_restock_calc_at    TIMESTAMP NULLABLE
restock_alert_sent_at   TIMESTAMP NULLABLE

-- Auditoría
created_by_id           FK → core_users NOT NULL
created_at              TIMESTAMP DEFAULT NOW()
updated_at              TIMESTAMP DEFAULT NOW()

INDEX(subcategory_id, is_active)
INDEX(department_code, is_active)
INDEX(code)
```

Propiedades calculadas:
- `restock_point` = override si está seteado, sino auto
- `total_stock` = suma de `quantity_remaining` de lotes activos
- `is_below_restock` = `total_stock <= restock_point`
- `total_stock_value` = suma de `quantity_remaining * unit_cost` por lote

Relaciones:
- `subcategory` → WarehouseSubcategory
- `stock_entries` → List[WarehouseStockEntry]
- `movements` → List[WarehouseMovement]
- `ticket_materials` → List[WarehouseTicketMaterial]

---

#### Modelo 4: `WarehouseStockEntry` → `warehouse_stock_entries`

*(Lote/compra — base del sistema FIFO)*

```
id                  INTEGER PK
product_id          FK → warehouse_products NOT NULL
quantity_original   NUMERIC(10,2) NOT NULL
quantity_remaining  NUMERIC(10,2) NOT NULL
purchase_date       DATE NOT NULL                 -- ← FIFO se ordena por este campo
purchase_folio      VARCHAR(100) NOT NULL
unit_cost           NUMERIC(10,4) NOT NULL
supplier            VARCHAR(200) NULLABLE
registered_by_id    FK → core_users NOT NULL
registered_at       TIMESTAMP DEFAULT NOW()
notes               TEXT
is_exhausted        BOOLEAN DEFAULT FALSE
voided              BOOLEAN DEFAULT FALSE
voided_by_id        FK → core_users NULLABLE
voided_at           TIMESTAMP NULLABLE
void_reason         TEXT NULLABLE

INDEX(product_id, purchase_date)              -- clave para FIFO
INDEX(product_id, is_exhausted, voided)       -- stock disponible
```

Propiedades:
- `is_available` = NOT is_exhausted AND NOT voided
- `quantity_consumed` = quantity_original - quantity_remaining

---

#### Modelo 5: `WarehouseMovement` → `warehouse_movements`

*(Registro de cada operación — trazabilidad completa)*

```
id                  INTEGER PK
product_id          FK → warehouse_products NOT NULL
entry_id            FK → warehouse_stock_entries NULLABLE
movement_type       VARCHAR(30) NOT NULL
                    Valores: ENTRY | CONSUMED | ADJUSTED_IN | ADJUSTED_OUT | RETURNED | VOIDED
quantity            NUMERIC(10,2) NOT NULL

-- Relación polimórfica con tickets (nullable — solo si el movimiento es de un ticket)
source_app          VARCHAR(30) NULLABLE      -- 'helpdesk' | 'maint'
source_ticket_id    INTEGER NULLABLE          -- ID del ticket en su app

performed_by_id     FK → core_users NOT NULL
performed_at        TIMESTAMP DEFAULT NOW()
notes               TEXT

INDEX(product_id, performed_at)
INDEX(source_app, source_ticket_id)           -- Para consultas por ticket
INDEX(movement_type, performed_at)
```

---

#### Modelo 6: `WarehouseTicketMaterial` → `warehouse_ticket_materials`

*(Resumen de material usado por ticket — para mostrar en resolución del ticket)*

```
id                  INTEGER PK
source_app          VARCHAR(30) NOT NULL      -- 'helpdesk' | 'maint'
source_ticket_id    INTEGER NOT NULL          -- ID del ticket en la app origen
product_id          FK → warehouse_products NOT NULL
quantity_used       NUMERIC(10,2) NOT NULL
added_by_id         FK → core_users NOT NULL
added_at            TIMESTAMP DEFAULT NOW()
notes               TEXT NULLABLE

UNIQUE(source_app, source_ticket_id, product_id)
INDEX(source_app, source_ticket_id)           -- Todos los materiales de un ticket
INDEX(product_id)
```

---

### 2.2 Diagrama de Relaciones

```
WarehouseCategory (dept: comp_center | equipment_maint)
    └── WarehouseSubcategory (N)
            └── WarehouseProduct (N) [dept: comp_center | equipment_maint]
                    ├── WarehouseStockEntry (N)  ← FIFO por purchase_date
                    │       └── WarehouseMovement (N) [entry_id]
                    ├── WarehouseMovement (N) [product_id]
                    └── WarehouseTicketMaterial (N)
                                ├── source_app='helpdesk', source_ticket_id → helpdesk_ticket.id
                                └── source_app='maint',    source_ticket_id → maint_tickets.id
```

---

## 3. Sistema de Permisos

### 3.1 Permisos Globales del Almacén

Los permisos del almacén son propios de la app `warehouse`, no de helpdesk ni maint:

```
-- PÁGINAS (gestión administrativa)
warehouse.page.dashboard         → Dashboard general de almacén
warehouse.page.products          → Ver catálogo de productos
warehouse.page.categories        → Gestión de categorías/subcategorías
warehouse.page.entries           → Ver entradas de stock
warehouse.page.movements         → Ver historial de movimientos
warehouse.page.reports           → Ver reportes

-- API - LECTURA
warehouse.api.read               → Consultar productos y stock (para autocomplete en tickets)

-- API - PRODUCTOS
warehouse.api.products.create    → Crear productos
warehouse.api.products.update    → Editar productos
warehouse.api.products.delete    → Desactivar productos

-- API - CATEGORÍAS
warehouse.api.categories.manage  → CRUD de categorías y subcategorías

-- API - STOCK
warehouse.api.entries.create     → Registrar nueva entrada/lote
warehouse.api.entries.void       → Anular una entrada
warehouse.api.adjust             → Ajuste manual de stock (corrección)

-- API - CONSUMO (usado por las apps consumidoras)
warehouse.api.consume            → Registrar consumo de material en un ticket (FIFO)

-- API - REPORTES
warehouse.api.reports.read       → Generar reportes
```

**Total: 15 permisos**

### 3.2 Asignación por Departamento

La asignación de permisos a roles combina el permiso global con el `department_code` que el
usuario tiene en el sistema. El filtrado por departamento es responsabilidad del service:

| Permiso | helpdesk admin | helpdesk secretary | tech_soporte | maint_admin | maint_dispatcher | maint_technician |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| page.dashboard | ✅ (CC) | ✅ (CC) | ✅ (CC) | ✅ (EM) | ✅ (EM) | — |
| page.products | ✅ (CC) | ✅ (CC) | ✅ (CC) | ✅ (EM) | ✅ (EM) | — |
| page.categories | ✅ (CC) | ✅ (CC) | — | ✅ (EM) | — | — |
| page.entries | ✅ (CC) | ✅ (CC) | — | ✅ (EM) | ✅ (EM) | — |
| page.movements | ✅ (CC) | ✅ (CC) | — | ✅ (EM) | ✅ (EM) | — |
| page.reports | ✅ (CC) | ✅ (CC) | — | ✅ (EM) | ✅ (EM) | — |
| api.read | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| api.products.create | ✅ | ✅ | — | ✅ | ✅ | — |
| api.products.update | ✅ | ✅ | — | ✅ | ✅ | — |
| api.products.delete | ✅ | — | — | ✅ | — | — |
| api.categories.manage | ✅ | ✅ | — | ✅ | — | — |
| api.entries.create | ✅ | ✅ | — | ✅ | ✅ | — |
| api.entries.void | ✅ | — | — | ✅ | — | — |
| api.adjust | ✅ | ✅ | — | ✅ | ✅ | — |
| api.consume | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| api.reports.read | ✅ | ✅ | — | ✅ | ✅ | — |

> CC = comp_center | EM = equipment_maint
> El sistema filtra automáticamente los datos por `department_code` del usuario.

### 3.3 Archivos DML

```
database/DML/warehouse/
  01_add_warehouse_permissions.sql
  02_assign_warehouse_permissions_to_helpdesk_roles.sql
  03_assign_warehouse_permissions_to_maint_roles.sql
```

---

## 4. Lógica de Negocio

### 4.1 FIFO — Consumo de Stock

Cuando se registra uso de un producto (cantidad N) desde cualquier app:

```
consume(product_id, quantity, source_app, source_ticket_id, performed_by_id, notes, db):

1. Verificar que el producto pertenece al departamento correcto según el usuario
2. Buscar lotes disponibles:
   WHERE product_id = X
   AND is_exhausted = FALSE
   AND voided = FALSE
   AND quantity_remaining > 0
   ORDER BY purchase_date ASC  ← FIFO

3. Verificar stock total suficiente:
   Si SUM(quantity_remaining) < quantity:
     raise ValueError(f"Stock insuficiente. Disponible: {total}, requerido: {quantity}")

4. Iterar lotes en orden FIFO:
   a. Si lote.quantity_remaining >= restante:
      - Descontar del lote
      - Crear WarehouseMovement(CONSUMED, entry_id=lote.id, qty=consumido,
                                source_app, source_ticket_id)
      - Si quantity_remaining == 0: lote.is_exhausted = TRUE
      - Break
   b. Si lote.quantity_remaining < restante:
      - Consumir todo el lote
      - Crear WarehouseMovement para este lote
      - lote.is_exhausted = TRUE
      - restante -= lote.quantity_remaining
      - Continuar con siguiente lote

5. Upsert WarehouseTicketMaterial:
   INSERT (source_app, source_ticket_id, product_id, quantity_used, added_by_id)
   ON CONFLICT (source_app, source_ticket_id, product_id)
   DO UPDATE SET quantity_used = quantity_used + EXCLUDED.quantity_used

6. Trigger: check_and_alert(product_id, db)
7. Trigger: recalculate_restock_point(product_id, db)  ← async si es posible
```

### 4.2 Reversión de Consumo

```
revert_consumption(source_app, source_ticket_id, product_id, performed_by_id, db):

1. Buscar WarehouseTicketMaterial(source_app, source_ticket_id, product_id)
   - Si no existe: raise 404

2. quantity_to_return = ticket_material.quantity_used
3. Revertir FIFO inverso (reponer al lote más reciente):
   - Crear WarehouseMovement(RETURNED, entry_id=lote_mas_reciente.id,
                              qty=quantity_to_return, source_app, source_ticket_id)
   - Incrementar quantity_remaining del lote
   - Si lote estaba exhausted: lote.is_exhausted = FALSE

4. Eliminar WarehouseTicketMaterial
5. Recalcular restock point
```

### 4.3 Cálculo del Punto de Restock

*(Idéntico al plan original — rolling 90 días)*

```
calculate_restock_point(product_id, db):

avg_daily = SUM(quantity) / 90
    WHERE product_id = X
    AND movement_type IN ('CONSUMED', 'ADJUSTED_OUT')
    AND performed_at >= NOW() - INTERVAL '90 days'

restock_point_auto = CEILING(avg_daily * (lead_time_days + 3))
-- Mínimo 1 si hay consumo; 0 si no hay consumo en 90 días
-- Actualiza product.restock_point_auto y product.last_restock_calc_at
```

### 4.4 Alertas de Restock

```
check_and_alert(product_id, db):

Si product.is_below_restock == True:
  Y (restock_alert_sent_at IS NULL
     OR restock_alert_sent_at < NOW() - INTERVAL '24 hours'):

  1. Crear notificación en sistema para admins del departamento del producto
  2. Enviar email a usuarios con permiso warehouse.page.dashboard
     filtrando por department_code del producto
  3. product.restock_alert_sent_at = NOW()
```

### 4.5 Ajustes de Stock

- **ADJUSTED_IN:** Corrección positiva (sin folio de compra formal)
  - Crea `WarehouseMovement(ADJUSTED_IN)` + optionalmente `WarehouseStockEntry` si se quiere FIFO sobre el ajuste
- **ADJUSTED_OUT:** Corrección negativa (producto dañado, desecho)
  - Aplica lógica FIFO igual que consumo normal, pero `movement_type = ADJUSTED_OUT` y `source_ticket_id = NULL`

---

## 5. API Endpoints

### Base URL: `/api/warehouse/v1`

#### 5.1 Categorías y Subcategorías

```
GET    /categories                          → Listar categorías (filtro por dept del usuario)
POST   /categories                          → Crear categoría
PUT    /categories/{id}                     → Editar categoría
DELETE /categories/{id}                     → Desactivar

GET    /categories/{id}/subcategories       → Subcategorías de una categoría
POST   /categories/{id}/subcategories       → Crear subcategoría
PUT    /subcategories/{id}                  → Editar subcategoría
DELETE /subcategories/{id}                  → Desactivar
```

#### 5.2 Productos

```
GET    /products                            → Listar (con stock, filtro por dept)
POST   /products                            → Crear producto
GET    /products/{id}                       → Detalle + lotes + movimientos recientes
PUT    /products/{id}                       → Editar producto
DELETE /products/{id}                       → Desactivar
GET    /products/available                  → Para autocomplete en tickets (stock > 0)
POST   /products/{id}/recalculate-restock   → Recalcular punto de restock
PUT    /products/{id}/restock-override      → Setear/quitar override manual
```

#### 5.3 Entradas de Stock

```
GET    /stock-entries                       → Listar entradas (filtros: product_id, fecha)
POST   /stock-entries                       → Nueva entrada/lote (folio + costo obligatorios)
GET    /stock-entries/{id}                  → Detalle de entrada
POST   /stock-entries/{id}/void             → Anular entrada (razón obligatoria)
```

#### 5.4 Movimientos

```
GET    /movements                           → Historial (filtros: product_id, tipo, fecha,
                                              source_app, source_ticket_id)
POST   /adjust                              → Ajuste manual (IN o OUT + justificación)
```

#### 5.5 Consumo (llamado internamente por las apps consumidoras)

```
POST   /consume                             → Consumir material para un ticket (FIFO)
        Body: { product_id, quantity, source_app, source_ticket_id, notes }

DELETE /ticket-materials/{source_app}/{source_ticket_id}/{product_id}
        → Revertir consumo de un producto en un ticket
          (solo si el ticket no está CLOSED, crea movimiento RETURNED)
```

#### 5.6 Consulta de Materiales por Ticket (para las apps consumidoras)

```
GET    /ticket-materials/{source_app}/{source_ticket_id}
        → Todos los materiales registrados para un ticket específico
          (usado por helpdesk y maint para mostrar en detalle del ticket)
```

#### 5.7 Dashboard y Reportes

```
GET    /dashboard                           → Stats del almacén (filtrado por dept del usuario)
GET    /low-stock                           → Productos bajo restock point
GET    /reports/movements                   → Reporte de movimientos por período
GET    /reports/consumption                 → Consumo por producto/categoría
GET    /reports/stock-valuation             → Valor del inventario (FIFO)
```

---

## 6. Páginas Frontend (Admin)

### Base URL de páginas: `/almacen/`

> Las páginas del almacén son administrativas. Los técnicos interactúan con el almacén
> desde el detalle del ticket (tab de Resolución) en sus respectivas apps.

| Ruta | Descripción | Permiso |
|---|---|---|
| `/almacen/` | Dashboard con alertas de restock, KPIs | `warehouse.page.dashboard` |
| `/almacen/productos` | Catálogo con stock visual | `warehouse.page.products` |
| `/almacen/productos/{id}` | Detalle: lotes, historial, gráfica de consumo | `warehouse.page.products` |
| `/almacen/categorias` | CRUD de categorías/subcategorías | `warehouse.page.categories` |
| `/almacen/entradas` | Registro de entradas de stock | `warehouse.page.entries` |
| `/almacen/movimientos` | Historial completo con filtros | `warehouse.page.movements` |
| `/almacen/reportes` | Reportes del almacén | `warehouse.page.reports` |

> El dashboard y las páginas filtran automáticamente por el `department_code` del usuario.
> Un superadmin puede cambiar el filtro para ver el almacén de cualquier departamento.

---

## 7. Integración por App Consumidora

### 7.1 Integración en Help Desk CC

**¿Qué cambia vs el plan original (PLAN_WAREHOUSE_MODULE.md)?**
- La API que se consume es `/api/warehouse/v1/` (no `/api/helpdesk/warehouse/`)
- Los permisos son `warehouse.*` (no `helpdesk.warehouse.*`)
- El `WarehouseTicketMaterial` usa `source_app='helpdesk'`
- El resto del flujo (tab de resolución, autocomplete, consumo FIFO) es igual

**Cambios en HelpDesk:**
- `services/ticket_service.py`: importar y llamar `WarehouseFifoService.consume(source_app='helpdesk', ...)`
- `api/tickets.py`: el endpoint de resolución acepta `materials_used?` opcional
- `templates/helpdesk/technician/ticket_detail.html`: tab "Resolución" con sección de materiales
- `static/js/helpdesk/technician/warehouse-materials.js`: autocomplete + lista de materiales

> Los permisos `warehouse.api.read` y `warehouse.api.consume` deben asignarse a los roles
> `tech_soporte` y `secretary_comp_center` vía DML.

### 7.2 Integración en App de Mantenimiento

- La API es la misma: `/api/warehouse/v1/`
- El `WarehouseTicketMaterial` usa `source_app='maint'`
- Los permisos `warehouse.api.read` y `warehouse.api.consume` se asignan a `maint_dispatcher` y `maint_technician`
- En el detalle del ticket de maint (tab "Resolución"), misma UX que helpdesk
- El filtrado de productos es automático por `department_code='equipment_maint'`

### 7.3 Cómo una App Llama al Almacén

```python
# Ejemplo en ticket_service.py de maint o helpdesk:
from itcj2.apps.warehouse.services.fifo_service import WarehouseFifoService

def resolve_ticket(db, ticket_id, resolver_id, data):
    # ... lógica de resolución ...

    # Consumir materiales si se proporcionaron
    if data.materials_used:
        for material in data.materials_used:
            try:
                WarehouseFifoService.consume(
                    db=db,
                    product_id=material.product_id,
                    quantity=material.quantity,
                    source_app='maint',  # o 'helpdesk'
                    source_ticket_id=ticket.id,
                    performed_by_id=resolver_id,
                    notes=material.notes
                )
            except ValueError as e:
                # Stock insuficiente: no bloqueamos la resolución, solo registramos advertencia
                warnings.append(str(e))

    # ... resto de la resolución ...
```

---

## 8. Fases de Implementación

---

### Fase 1 — Modelos y Migración Alembic

**Objetivo:** Crear las tablas del almacén global.

- [ ] Crear `itcj2/apps/warehouse/` con estructura base
- [ ] Crear `itcj2/apps/warehouse/models/category.py` → `WarehouseCategory`
- [ ] Crear `itcj2/apps/warehouse/models/subcategory.py` → `WarehouseSubcategory`
- [ ] Crear `itcj2/apps/warehouse/models/product.py` → `WarehouseProduct`
- [ ] Crear `itcj2/apps/warehouse/models/stock_entry.py` → `WarehouseStockEntry`
- [ ] Crear `itcj2/apps/warehouse/models/movement.py` → `WarehouseMovement`
- [ ] Crear `itcj2/apps/warehouse/models/ticket_material.py` → `WarehouseTicketMaterial`
- [ ] Crear `itcj2/apps/warehouse/models/__init__.py`
- [ ] Generar migración: `alembic revision --autogenerate -m "add_global_warehouse_module"`
- [ ] Revisar y ajustar el script generado (especialmente los índices)
- [ ] Ejecutar: `alembic upgrade head`

---

### Fase 2 — DML: Permisos y Asignación a Roles

- [ ] Crear `database/DML/warehouse/01_add_warehouse_permissions.sql`
  - 15 permisos con prefijo `warehouse.*`
  - `ON CONFLICT DO NOTHING` para idempotencia
- [ ] Crear `database/DML/warehouse/02_assign_warehouse_permissions_to_helpdesk_roles.sql`
  - Asignar a: `admin`, `secretary_comp_center`, `tech_soporte`
  - Solo permisos apropiados por rol (ver tabla en §3.2)
- [ ] Crear `database/DML/warehouse/03_assign_warehouse_permissions_to_maint_roles.sql`
  - Asignar a: `maint_admin`, `maint_dispatcher`, `maint_technician`
  - Solo permisos apropiados por rol
- [ ] Ejecutar los scripts en la BD

---

### Fase 3 — Schemas Pydantic

- [ ] Crear `itcj2/apps/warehouse/schemas/categories.py`
  - `WarehouseCategoryCreate`, `WarehouseCategoryOut`
  - `WarehouseSubcategoryCreate`, `WarehouseSubcategoryOut`
- [ ] Crear `itcj2/apps/warehouse/schemas/products.py`
  - `WarehouseProductCreate`, `WarehouseProductUpdate`, `WarehouseProductOut`
  - `WarehouseProductWithStockOut` (incluye `total_stock`, `is_below_restock`, `restock_point`)
  - `WarehouseProductAvailableOut` (para autocomplete: id, name, unit, stock_available)
- [ ] Crear `itcj2/apps/warehouse/schemas/stock.py`
  - `StockEntryCreate`, `StockEntryOut`
  - `StockEntryVoidRequest`
  - `AdjustRequest` (product_id, quantity, type: IN|OUT, notes, justification)
- [ ] Crear `itcj2/apps/warehouse/schemas/consume.py`
  - `ConsumeRequest` (product_id, quantity, source_app, source_ticket_id, notes)
  - `MaterialUseRequest` (usado por las apps: product_id, quantity, notes)
  - `WarehouseTicketMaterialOut`
- [ ] Crear `itcj2/apps/warehouse/schemas/movements.py`
  - `MovementOut` (con info de producto, lote, usuario, ticket referenciado)
- [ ] Crear `itcj2/apps/warehouse/schemas/dashboard.py`
  - `WarehouseDashboardOut`

---

### Fase 4 — Services (Lógica de Negocio)

- [ ] Crear `itcj2/apps/warehouse/services/category_service.py`
  - CRUD de categorías y subcategorías (filtrando por `department_code`)
- [ ] Crear `itcj2/apps/warehouse/services/product_service.py`
  - CRUD de productos
  - `get_available_for_autocomplete(db, department_code, search_term)` → para los tickets
  - `get_products_below_restock(db, department_code)` → para badge de nav
- [ ] Crear `itcj2/apps/warehouse/services/stock_service.py`
  - `register_entry(db, product_id, data, user_id)` → Crea StockEntry + Movement(ENTRY)
  - `void_entry(db, entry_id, reason, user_id)` → Anular lote
  - `get_available_entries(db, product_id)` → Lotes FIFO ordenados
- [ ] Crear `itcj2/apps/warehouse/services/fifo_service.py`
  - `consume(db, product_id, quantity, source_app, source_ticket_id, performed_by_id, notes)`
  - `revert_consumption(db, source_app, source_ticket_id, product_id, performed_by_id)`
  - `adjust_stock(db, product_id, quantity, type, notes, user_id)`
- [ ] Crear `itcj2/apps/warehouse/services/restock_service.py`
  - `calculate_restock_point(db, product_id)`
  - `recalculate_all(db, department_code?)` → Para tarea programada o bajo demanda
- [ ] Crear `itcj2/apps/warehouse/services/alert_service.py`
  - `check_and_alert(db, product_id)`
  - `get_nav_badge_count(db, department_code)` → Query eficiente para el badge del menú
  - `send_system_notification(db, product)` → Usa sistema de notificaciones existente

---

### Fase 5 — API Routes

- [ ] Crear `itcj2/apps/warehouse/api/categories.py`
- [ ] Crear `itcj2/apps/warehouse/api/products.py`
- [ ] Crear `itcj2/apps/warehouse/api/entries.py`
- [ ] Crear `itcj2/apps/warehouse/api/movements.py`
- [ ] Crear `itcj2/apps/warehouse/api/consume.py` — Consumo FIFO + reversión + materiales por ticket
- [ ] Crear `itcj2/apps/warehouse/api/dashboard.py`
- [ ] Crear `itcj2/apps/warehouse/api/reports.py`
- [ ] Crear `itcj2/apps/warehouse/router.py` → Ensamblar bajo `/api/warehouse/v1`
- [ ] Registrar `warehouse_router` en el router principal de ITCJ

---

### Fase 6 — Pages (Admin)

- [ ] Crear `itcj2/apps/warehouse/pages/router.py`
- [ ] Crear `itcj2/apps/warehouse/pages/main.py` — Dashboard, productos, categorías, etc.
- [ ] Registrar en router principal de páginas ITCJ

---

### Fase 7 — Frontend: Templates y JS/CSS

- [ ] Crear `itcj2/apps/warehouse/templates/warehouse/base.html`
- [ ] Crear `warehouse/dashboard.html` — KPIs, alertas, movimientos recientes
- [ ] Crear `warehouse/products/list.html` — Catálogo con barra de nivel de stock
- [ ] Crear `warehouse/products/detail.html` — Lotes, historial, gráfica de consumo
- [ ] Crear `warehouse/categories.html` — CRUD inline de categorías/subcategorías
- [ ] Crear `warehouse/entries/list.html` + `entries/create.html`
- [ ] Crear `warehouse/movements/list.html` — Historial con filtros (incluye filtro por source_app)
- [ ] Crear `warehouse/reports.html`

**JavaScript:**
- [ ] `static/js/warehouse/warehouse-utils.js` — `window.WarehouseUtils` (showToast, helpers)
- [ ] `static/js/warehouse/dashboard.js`
- [ ] `static/js/warehouse/products.js`
- [ ] `static/js/warehouse/product-detail.js`
- [ ] `static/js/warehouse/entries.js`
- [ ] `static/js/warehouse/categories.js`
- [ ] `static/js/warehouse/movements.js`
- [ ] `static/js/warehouse/materials-ticket.js` — **Componente compartido** para autocomplete
  de materiales en la tab de resolución de tickets. Importado por helpdesk Y maint.

**CSS:**
- [ ] `static/css/warehouse/warehouse.css` — Barras de nivel de stock (`.wh-stock-bar`), tarjetas de alerta

---

### Fase 8 — Integración con Help Desk

> Prerequisito: Fases 1–5 de este plan completadas.

- [ ] Actualizar `helpdesk/schemas/tickets.py`: agregar `materials_used?: List[MaterialUseRequest]`
- [ ] Actualizar `helpdesk/services/ticket_service.py`: llamar a `WarehouseFifoService.consume()`
- [ ] Crear endpoint: `GET /api/help-desk/v2/tickets/{id}/materials` (proxy a warehouse)
- [ ] Crear `helpdesk/templates/technician/partials/resolution_tab.html` — Tab de resolución con sección de material
- [ ] Actualizar template de detalle de ticket SOPORTE para agregar la nueva tab
- [ ] Crear `helpdesk/static/js/technician/ticket-resolution.js` — Usa `warehouse-materials.js`
- [ ] Ejecutar `database/DML/warehouse/02_assign_warehouse_permissions_to_helpdesk_roles.sql`

---

### Fase 9 — Integración con Mantenimiento

> Prerequisito: Fases 1–5 de este plan + PLAN_MAINTENANCE_APP.md Fases 1–6 completadas.

- [ ] Actualizar `maint/schemas/tickets.py`: agregar `materials_used?: List[MaterialUseRequest]`
- [ ] Actualizar `maint/services/ticket_service.py`: llamar a `WarehouseFifoService.consume(source_app='maint', ...)`
- [ ] Actualizar `maint/templates/tickets/detail.html`: tab "Resolución" con sección de material
- [ ] Usar `warehouse-materials.js` en `maint/static/js/maint/ticket-resolution.js`
- [ ] Ejecutar `database/DML/warehouse/03_assign_warehouse_permissions_to_maint_roles.sql`

---

### Fase 10 — Alertas, Notificaciones y Navegación

- [ ] Integrar `alert_service.py` con el sistema de notificaciones global de ITCJ
- [ ] Agregar el badge de stock bajo en el menú de navegación:
  - Para usuarios con permiso `warehouse.page.dashboard`
  - Query eficiente: `count WHERE is_below_restock AND department_code = user.dept`
- [ ] Configurar template de email para alerta de restock (por departamento)
- [ ] Documentar cómo programar recálculo automático semanal (`restock_service.recalculate_all()`)

---

## 9. Estructura de Archivos

```
itcj2/apps/warehouse/
├── __init__.py
├── router.py                             (API router assembly → /api/warehouse/v1)
├── models/
│   ├── __init__.py
│   ├── category.py                       (WarehouseCategory)
│   ├── subcategory.py                    (WarehouseSubcategory)
│   ├── product.py                        (WarehouseProduct)
│   ├── stock_entry.py                    (WarehouseStockEntry)
│   ├── movement.py                       (WarehouseMovement)
│   └── ticket_material.py                (WarehouseTicketMaterial)
├── schemas/
│   ├── categories.py
│   ├── products.py
│   ├── stock.py
│   ├── consume.py
│   ├── movements.py
│   └── dashboard.py
├── services/
│   ├── category_service.py
│   ├── product_service.py
│   ├── stock_service.py
│   ├── fifo_service.py                   ← importado por helpdesk y maint
│   ├── restock_service.py
│   └── alert_service.py
├── api/
│   ├── __init__.py
│   ├── categories.py
│   ├── products.py
│   ├── entries.py
│   ├── movements.py
│   ├── consume.py
│   ├── dashboard.py
│   └── reports.py
├── pages/
│   ├── router.py
│   └── main.py
├── static/
│   ├── js/warehouse/
│   │   ├── warehouse-utils.js
│   │   ├── dashboard.js
│   │   ├── products.js
│   │   ├── product-detail.js
│   │   ├── entries.js
│   │   ├── categories.js
│   │   ├── movements.js
│   │   └── materials-ticket.js           ← compartido por helpdesk y maint
│   └── css/warehouse/
│       └── warehouse.css
└── templates/warehouse/
    ├── base.html
    ├── dashboard.html
    ├── products/
    │   ├── list.html
    │   └── detail.html
    ├── categories.html
    ├── entries/
    │   ├── list.html
    │   └── create.html
    ├── movements/
    │   └── list.html
    └── reports.html

database/DML/warehouse/
    ├── 01_add_warehouse_permissions.sql
    ├── 02_assign_warehouse_permissions_to_helpdesk_roles.sql
    └── 03_assign_warehouse_permissions_to_maint_roles.sql

migrations/versions/
    └── <hash>_add_global_warehouse_module.py   (via alembic)
```

**Archivos a modificar en apps consumidoras:**
- `helpdesk/services/ticket_service.py` — Integrar FIFO consume
- `helpdesk/schemas/tickets.py` — Agregar `materials_used`
- `helpdesk/templates/.../ticket_detail.html` — Tab de Resolución
- `maint/services/ticket_service.py` — Integrar FIFO consume
- `maint/schemas/tickets.py` — Agregar `materials_used`
- `maint/templates/tickets/detail.html` — Tab de Resolución
- Router principal de ITCJ — Registrar `warehouse_router` y pages

---

## 10. Convenciones y Estándares

### SQL (DML)
- Lookup de `app_id` con validación: `IF v_app_id IS NULL THEN RAISE EXCEPTION ...`
- `ON CONFLICT ... DO NOTHING` para idempotencia
- `RAISE NOTICE` para feedback durante ejecución
- Nomenclatura de permisos: `warehouse.tipo.accion[.scope]`

### SQLAlchemy (Modelos)
- Prefijo de tabla: `warehouse_`
- FKs por nombre de tabla string para evitar imports circulares
- `server_default=func.now()` para `created_at`; `onupdate=func.now()` para `updated_at`
- Índices nombrados: `ix_warehouse_products_dept_active`, etc.
- `back_populates` en todas las relaciones (no `backref`)

### Python (Services)
- `fifo_service.py` es el contrato público para apps consumidoras — no exponer detalles internos
- Todos los services reciben `db: Session` como parámetro — sin dependencia de request context
- `source_app` como literal string: validar que sea `'helpdesk'` o `'maint'` (o usar Enum)
- Usar transacciones explícitas en FIFO para garantizar atomicidad

### JavaScript
- `window.WarehouseUtils` como namespace global del módulo
- `materials-ticket.js` debe ser importable desde cualquier app sin modificaciones
  - Recibe configuración via atributo `data-department-code` en el elemento contenedor

### CSS
- Variables de Bootstrap 5.3.0
- Prefijo `.wh-` para clases del módulo
- Niveles de stock: verde ≥ 75%, amarillo 25–74%, rojo < 25% del restock_point

---

*Fin del documento — PLAN_WAREHOUSE_GLOBAL.md*

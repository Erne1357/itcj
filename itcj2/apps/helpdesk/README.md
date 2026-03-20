# Help-Desk — Soporte Tecnico e Inventario Institucional

## Descripcion

**Help-Desk** es el sistema de soporte tecnico del ITCJ. Gestiona tickets de soporte para los departamentos de Desarrollo de Software y Soporte Tecnico, con seguimiento de estados, asignaciones, SLA, calificaciones y un modulo completo de inventario de equipos institucionales.

---

## Roles

| Rol | Descripcion |
|---|---|
| `staff` | Personal institucional: crea tickets y consulta los suyos |
| `secretary` | Crea tickets en nombre de otros usuarios |
| `tech_desarrollo` | Tecnico del area de Desarrollo de Software |
| `tech_soporte` | Tecnico del area de Soporte Tecnico |
| `department_head` | Jefe de departamento: acceso a inventario de su departamento |
| `admin` | Acceso completo: tickets, inventario, estadisticas y configuracion |

---

## Caracteristicas Principales

### Modulo de Tickets

- Flujo de estados configurable con historial completo
- Clasificacion por area (DESARROLLO / SOPORTE) y prioridad (BAJA, MEDIA, ALTA, URGENTE)
- Asignacion a tecnicos individuales o equipos
- Colaboradores adicionales en tickets
- Comentarios internos y publicos con adjuntos (imagenes y documentos)
- Sistema de calificaciones y encuestas de satisfaccion al cerrar
- Metricas de SLA: tiempo de primera respuesta, tiempo de resolucion

### Modulo de Inventario

- Registro de equipos institucionales con numero de inventario y numero de serie
- Organizacion por categorias, grupos (salones, laboratorios, oficinas) y departamentos
- Historial de cambios en cada equipo
- Relacion de equipos con tickets de soporte
- Transferencias individuales y masivas entre departamentos/grupos
- Solicitudes de baja de equipos

### Modulo de Estadisticas y Analisis

- Dashboard con 5 pestanas: global, por departamento, por tecnico, desglose de tiempos, calificaciones
- Modulo de analisis: outliers (IQR), clustering K-means, distribucion, tendencias
- Filtros por periodo academico, area y rango de fechas libre

---

## URLs

| Tipo | Prefijo |
|---|---|
| API REST | `/api/help-desk/v2/` |
| Paginas HTML | `/help-desk/` |

### Modulos API

| Sub-ruta | Descripcion |
|---|---|
| `/tickets` | CRUD de tickets, estados, colaboradores, equipos asociados |
| `/assignments` | Asignacion y reasignacion de tickets |
| `/comments` | Comentarios generales |
| `/attachments` | Carga y descarga de archivos adjuntos |
| `/documents` | Documentos de resolucion |
| `/categories` | Categorias de tickets |
| `/stats` | Estadisticas y analisis |
| `/inventory/...` | Modulo completo de inventario |

### Paginas HTML

| Ruta | Descripcion |
|---|---|
| `/help-desk/` | Landing / acceso segun rol |
| `/help-desk/user/` | Dashboard del usuario (staff/secretary) |
| `/help-desk/technician/` | Panel del tecnico |
| `/help-desk/department/` | Vista del jefe de departamento |
| `/help-desk/admin/` | Panel de administracion |
| `/help-desk/inventory/` | Gestion de inventario |
| `/help-desk/warehouse/` | Integracion con almacen global |

---

## Estructura de Directorios

```
helpdesk/
├── router.py                  # APIRouter principal (/api/help-desk/v2)
├── models/                    # Modelos SQLAlchemy
│   ├── ticket.py              # Ticket principal
│   ├── category.py            # Categorias de tickets
│   ├── assignment.py          # Asignaciones
│   ├── comment.py             # Comentarios
│   ├── attachment.py          # Archivos adjuntos
│   ├── status_log.py          # Historial de estados
│   ├── collaborator.py        # Colaboradores
│   ├── inventory_item.py      # Equipos institucionales
│   ├── inventory_category.py  # Categorias de equipos
│   ├── inventory_group.py     # Grupos de equipos
│   └── inventory_history.py   # Historial de equipos
├── api/
│   ├── tickets.py             # CRUD de tickets
│   ├── assignments.py         # Asignaciones
│   ├── comments.py            # Comentarios
│   ├── attachments.py         # Adjuntos
│   ├── documents.py           # Documentos de resolucion
│   ├── categories.py          # Categorias
│   ├── stats.py               # Estadisticas
│   ├── ticket_collaborators.py
│   ├── ticket_comments.py
│   ├── ticket_equipment.py    # Equipos asociados a un ticket
│   └── inventory/             # Sub-modulo de inventario
│       ├── __init__.py        # inventory_router
│       ├── items.py           # CRUD de equipos
│       ├── groups.py          # Grupos de equipos
│       ├── categories.py      # Categorias de inventario
│       ├── transfer.py        # Transferencias individuales
│       └── bulk_transfer.py   # Transferencias masivas
├── pages/
│   ├── router.py              # APIRouter de paginas HTML
│   ├── nav.py                 # Navegacion y menus
│   ├── user.py                # Paginas del usuario
│   ├── technician.py          # Paginas del tecnico
│   ├── department.py          # Paginas del jefe de departamento
│   ├── admin.py               # Paginas de administracion
│   └── warehouse.py           # Paginas de integracion con almacen
├── schemas/                   # Pydantic validators
├── services/                  # Logica de negocio
├── utils/
│   ├── navigation.py          # Helpers de navegacion
│   └── warehouse_auth.py      # Permisos del almacen
├── templates/helpdesk/        # Templates Jinja2
└── static/                    # CSS, JS (servidos por Nginx)
```

---

## Modelos de Base de Datos

Todas las tablas usan el prefijo `helpdesk_`.

### Tickets

| Tabla | Descripcion |
|---|---|
| `helpdesk_ticket` | Ticket de soporte principal |
| `helpdesk_category` | Categorias y subcategorias |
| `helpdesk_assignment` | Asignaciones a tecnicos |
| `helpdesk_comment` | Comentarios en tickets |
| `helpdesk_attachment` | Archivos adjuntos (imagenes, documentos) |
| `helpdesk_status_log` | Historial de cambios de estado |
| `helpdesk_collaborator` | Colaboradores adicionales en un ticket |
| `helpdesk_ticket_inventory_item` | Relacion tickets ↔ equipos |

### Inventario

| Tabla | Descripcion |
|---|---|
| `helpdesk_inventory_categories` | Categorias de equipos (computadora, impresora, etc.) |
| `helpdesk_inventory_items` | Equipos institucionales |
| `helpdesk_inventory_groups` | Grupos de equipos (salones, labs, oficinas) |
| `helpdesk_inventory_group_capacity` | Capacidad maxima por categoria en un grupo |
| `helpdesk_inventory_history` | Historial de cambios en equipos |

---

## Flujo de un Ticket

```
PENDING
   │
   └─→ ASSIGNED
           │
           └─→ IN_PROGRESS
                    │
                    ├─→ RESOLVED_SUCCESS
                    │        └─→ CLOSED
                    │
                    ├─→ RESOLVED_FAILED
                    │        └─→ CLOSED
                    │
                    └─→ CANCELED
```

Cada cambio de estado queda registrado en `helpdesk_status_log` con usuario y timestamp.

---

## Inventario — Conceptos Clave

### Numeros de Identificacion

Cada equipo tiene dos identificadores:
- **Numero de inventario** (`inventory_number`): Asignado por el area de inventario del ITCJ
- **Numero de serie** (`serial_number`): Numero del fabricante (opcional)

### Grupos

Los grupos organizan los equipos por ubicacion fisica:

| Tipo | Ejemplo |
|---|---|
| `CLASSROOM` | Salon 101, Aula 203 |
| `LABORATORY` | Laboratorio de Sistemas, Taller CNC |
| `OFFICE` | Cubiculo de Direccion, Jefatura de Sistemas |

### Transferencias

- **Individual**: Mueve un equipo de un departamento/grupo a otro
- **Masiva**: Transfiere multiples equipos en una sola operacion (`/inventory/bulk-transfer`)
- Cada transferencia queda registrada en `helpdesk_inventory_history`

---

## Estadisticas y Analisis

Accesibles desde `/help-desk/admin/stats` y `/help-desk/admin/analysis`.

### Endpoints API

| Ruta | Descripcion |
|---|---|
| `/stats/global` | Metricas generales del sistema |
| `/stats/by-department` | Tickets agrupados por departamento |
| `/stats/by-technician` | Rendimiento por tecnico |
| `/stats/time-breakdown` | Desglose de tiempos (respuesta, resolucion) |
| `/stats/ratings-detail` | Detalle de calificaciones |
| `/stats/analysis/outliers` | Tickets atipicos por metodo IQR |
| `/stats/analysis/kmeans` | Clustering de tickets (K-means Python puro) |
| `/stats/analysis/distribution` | Distribucion de variables |
| `/stats/analysis/trends` | Tendencias temporales |

### Filtros Disponibles

- Periodo academico (`AcademicPeriod`)
- Presets de fecha (ultima semana, mes, trimestre)
- Rango de fechas libre
- Area (DESARROLLO / SOPORTE)

### Permisos de Estadisticas

| Permiso | Descripcion |
|---|---|
| `helpdesk.stats.page.list` | Acceso a las paginas de estadisticas |
| `helpdesk.stats.api.read` | Acceso a los endpoints API de estadisticas |

---

## CLI — Comandos Disponibles

```bash
# Cargar inventario inicial desde CSV (database/CSV/inventario.csv)
# Formato CSV: DEPARTAMENTO;UBICACION;CANTIDAD;MARCA;MODELO;DISCO DURO;RAM (GB)
python -m itcj2.cli.main helpdesk load-inventory-csv
```

---

## Inicializacion

Los datos base de Help-Desk (permisos, roles, categorias, categorias de inventario) se cargan con:

```bash
python -m itcj2.cli.main core init-db
```

Los scripts DML especificos estan en `database/DML/helpdesk/`:

| Script | Contenido |
|---|---|
| `01_insert_permissions.sql` | Permisos de helpdesk |
| `02_insert_roles.sql` | Roles del modulo |
| `03_insert_role_permission.sql` | Asignacion permisos → roles |
| `04_insert_categories.sql` | Categorias de tickets |
| `05_insert_inventory_categories.sql` | Categorias de inventario |

---

## Permisos

Los permisos siguen el formato `helpdesk.recurso.accion`.

Ejemplos:

| Permiso | Descripcion |
|---|---|
| `helpdesk.ticket.create` | Crear tickets |
| `helpdesk.ticket.view_all` | Ver todos los tickets |
| `helpdesk.ticket.assign` | Asignar tickets a tecnicos |
| `helpdesk.ticket.close` | Cerrar tickets |
| `helpdesk.inventory.view` | Ver inventario |
| `helpdesk.inventory.manage` | Crear/editar/transferir equipos |
| `helpdesk.inventory.retire` | Solicitar baja de equipos |
| `helpdesk.stats.page.list` | Acceso al modulo de estadisticas |

---

## Adjuntos y Archivos

### Imagenes (attachments)

- Tamano maximo: 3 MB por imagen
- Extensiones permitidas: `jpg`, `jpeg`, `png`, `gif`, `webp`
- Maximo por resolucion: 10 archivos
- Maximo por comentario: 3 archivos
- Ruta de almacenamiento: `instance/apps/helpdesk/`

### Documentos

- Tamano maximo: 25 MB
- Extensiones permitidas: `xlsx`, `xls`, `csv`, `pdf`, `doc`, `docx`

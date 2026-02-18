# VisteTec - Sistema de Reciclaje de Ropa y Gestión de Despensa

## Descripción General

**VisteTec** es un sistema integral de economía circular diseñado para el Instituto Tecnológico de Ciudad Juárez que facilita la donación, distribución y reciclaje de prendas de vestir entre la comunidad estudiantil, junto con la gestión de campañas de recolección de despensa. El sistema promueve la solidaridad, sustentabilidad y apoyo mutuo mediante un catálogo digital de ropa disponible, sistema de citas para probadores, y reconocimiento a los donadores.

### Características Principales

- 👕 **Catálogo Digital de Prendas**: Navegación intuitiva con filtros, imágenes y descripciones detalladas
- 📅 **Sistema de Citas**: Agendado para probarse prendas con slots organizados por día
- 🎁 **Registro de Donaciones**: Seguimiento completo de donaciones de ropa y despensa
- 🏪 **Gestión de Despensa**: Inventario de artículos con entrada/salida y campañas de recolección
- 📊 **Campañas de Recolección**: Metas específicas con progreso visible y asociación a donaciones
- 🏆 **Reconocimiento Público**: Estadísticas anónimas que motivan la participación
- 📈 **Dashboard Administrativo**: Métricas, reportes y actividad reciente
- 🖼️ **Compresión de Imágenes**: Optimización automática de fotos de prendas (cliente + servidor)
- 🔐 **Permisos Granulares**: Control de acceso por rol (estudiante, voluntario, admin)

---

## Stack Tecnológico

### Backend
- **Framework**: Flask 3.1.1
- **Base de Datos**: PostgreSQL con SQLAlchemy 2.0
- **Migraciones**: Alembic 1.16.5
- **Procesamiento de Imágenes**: Pillow 11.3.0

### Frontend
- **Templates**: Jinja2 con Bootstrap 5.3.0
- **CSS Framework**: Bootstrap 5 + CSS personalizado mobile-first
- **JavaScript**: Vanilla JS con patrón IIFE (Immediately Invoked Function Expression)
- **Iconos**: Bootstrap Icons 1.11.0

### Almacenamiento
- **Imágenes**: Sistema local en `instance/apps/vistetec/garments/YYYY/MM/`
- **Límite**: 10MB (raw), comprimido automáticamente a JPEG 85% quality, max 1920px
- **Formatos permitidos**: jpg, jpeg, png, webp

### Estilo Visual
- **Color principal**: `#8B1538` (Granate institucional)
- **Diseño**: Mobile-first responsive
- **UX**: Acordeones colapsables, tabs dinámicas, búsqueda en tiempo real

---

## Arquitectura de VisteTec

### Estructura de Archivos

```
itcj/apps/vistetec/
├── __init__.py                    # Blueprints principales
├── README.md                      # Este archivo
│
├── config/
│   └── settings.py                # Configuración específica de VisteTec
│
├── models/                        # Modelos de datos
│   ├── __init__.py
│   ├── garment.py                 # Prendas de vestir
│   ├── appointment.py             # Citas para probarse ropa
│   ├── time_slot.py               # Horarios de atención
│   ├── donation.py                # Registro de donaciones
│   ├── pantry_item.py             # Artículos de despensa
│   ├── pantry_campaign.py         # Campañas de recolección
│   └── location.py                # Ubicaciones físicas
│
├── routes/                        # Endpoints
│   ├── api/                       # API REST
│   │   ├── catalog.py             # Catálogo público de prendas
│   │   ├── appointments.py        # Gestión de citas
│   │   ├── garments.py            # CRUD de prendas (voluntarios)
│   │   ├── donations.py           # Registro de donaciones
│   │   ├── time_slots.py          # Gestión de horarios
│   │   ├── pantry.py              # Gestión de despensa y campañas
│   │   └── reports.py             # Reportes y dashboard
│   │
│   └── pages/                     # Vistas HTML
│       ├── student.py             # Panel de estudiante
│       ├── volunteer.py           # Panel de voluntario
│       └── admin.py               # Panel de administrador
│
├── services/                      # Lógica de negocio
│   ├── catalog_service.py         # Lógica del catálogo
│   ├── appointment_service.py     # Lógica de citas
│   ├── garment_service.py         # Lógica de prendas
│   ├── donation_service.py        # Lógica de donaciones
│   ├── time_slot_service.py       # Lógica de horarios
│   ├── pantry_service.py          # Lógica de despensa y campañas
│   ├── image_service.py           # Compresión y manejo de imágenes
│   └── reports_service.py         # Reportes y estadísticas
│
├── templates/vistetec/            # Templates HTML
│   ├── base.html                  # Template base con navbar
│   ├── home.html                  # Landing page
│   │
│   ├── student/                   # Vistas de estudiante
│   │   ├── catalog.html           # Catálogo de prendas
│   │   ├── garment_detail.html    # Detalle y agendar cita
│   │   ├── my_appointments.html   # Mis citas
│   │   └── my_donations.html      # Mis donaciones
│   │
│   ├── volunteer/                 # Vistas de voluntario
│   │   ├── dashboard.html         # Panel principal
│   │   ├── appointments.html      # Gestión de citas (5 tabs)
│   │   ├── garment_form.html      # Alta/edición de prendas
│   │   └── register_donation.html # Registro de donaciones
│   │
│   └── admin/                     # Vistas de administrador
│       ├── dashboard.html         # Dashboard con métricas
│       ├── garments.html          # Gestión completa de prendas
│       ├── pantry.html            # Gestión de despensa
│       ├── campaigns.html         # Gestión de campañas
│       └── reports.html           # Reportes detallados
│
└── static/                        # Assets estáticos
    ├── css/                       # Estilos organizados por rol
    │   ├── shared/                # Compartidos
    │   ├── student/               # Estudiante
    │   ├── volunteer/             # Voluntario
    │   └── admin/                 # Administrador
    │
    └── js/                        # JavaScript organizado por rol
        ├── shared/                # Utilidades compartidas
        │   └── vistetec-utils.js  # VisteTecUtils global
        ├── student/               # Estudiante
        ├── volunteer/             # Voluntario
        └── admin/                 # Administrador
```

---

## Sistema de Roles y Permisos

### Roles Disponibles

#### 1. **Student** (Estudiante)

**Permisos**:
- ✅ Ver catálogo de prendas disponibles
- ✅ Ver detalle de prendas con imágenes
- ✅ Agendar citas para probarse ropa
- ✅ Cancelar sus propias citas (solo si están `scheduled`)
- ✅ Ver sus citas (pasadas y futuras)
- ✅ Ver sus donaciones registradas
- ✅ Ver campañas activas de despensa
- ✅ Indicar si traerá donación en su cita

**Flujo típico**:
```
1. Navegar catálogo → Filtrar por categoría
2. Ver detalle de prenda → Click "Agendar cita"
3. Seleccionar horario disponible (acordeón por día)
4. (Opcional) Ver campañas activas y marcar "Traeré donación"
5. Confirmar cita
6. Asistir a la cita en la fecha/hora programada
7. Ver historial en "Mis Citas"
```

**Nomenclatura de permisos**: `vistetec.{modulo}.{tipo}.{accion}`
- Ejemplo: `vistetec.catalog.api.list`, `vistetec.appointments.api.create`

---

#### 2. **Volunteer** (Voluntario)

**Permisos**:
- ✅ Todo lo del estudiante +
- ✅ Registrar y editar prendas en el catálogo
- ✅ Subir y comprimir imágenes de prendas
- ✅ Crear y gestionar horarios de atención
- ✅ Ver todas las citas programadas (tabs: Hoy, Próximas, Pasadas)
- ✅ Atender citas (marcar asistencia, registrar resultado)
- ✅ Registrar donaciones de ropa y despensa
- ✅ Buscar estudiantes como donantes
- ✅ Gestionar stock de despensa (entrada/salida)
- ✅ Retirar prendas del catálogo (soft delete)

**Flujo típico - Gestión de citas**:
```
1. Ir a "Citas" → Tab "Citas de hoy"
2. Ver citas del día con filtro de fecha
3. Click en cita → Marcar asistencia
4. Si el estudiante toma la prenda → Resultado "taken"
5. Si no es su talla → Resultado "not_fit"
6. Si decide no llevarla → Resultado "declined"
7. Si marcó "Traeré donación" → Link rápido a registrar donación
```

**Flujo típico - Registro de donación**:
```
1. Ir a "Registrar Donación"
2. Seleccionar tipo (Ropa / Despensa)
3. Buscar estudiante donante (o anónimo/externo)
4. Llenar detalles:
   - Ropa: nombre, categoría, talla, condición
   - Despensa: artículo, cantidad, campaña (opcional)
5. Registrar → Código de donación generado
```

---

#### 3. **Admin** (Administrador)

**Permisos**:
- ✅ TODOS los permisos de VisteTec
- ✅ Eliminar prendas (hard delete)
- ✅ Ver dashboard con métricas:
  - Total de prendas, donaciones, citas
  - Actividad reciente (últimas 15 acciones)
- ✅ Gestionar campañas de despensa (CRUD completo)
- ✅ Ver reportes detallados:
  - Reporte de prendas por categoría/condición
  - Reporte de citas por estado/resultado
  - Reporte de donaciones por tipo/periodo
- ✅ Gestionar ubicaciones físicas
- ✅ Configuración de la aplicación

**Dashboard administrativo incluye**:
- 📊 Cards con totales (prendas, citas, donaciones)
- 📈 Gráficos de tendencias
- 📋 Tabla de actividad reciente con timestamps
- 🔗 Accesos rápidos a reportes y gestión

---

## Modelos de Datos

### Diagrama de Relaciones

```
┌─────────────────┐       ┌──────────────────┐       ┌─────────────────┐
│   Garment       │       │   Appointment    │       │   TimeSlot      │
├─────────────────┤       ├──────────────────┤       ├─────────────────┤
│ id              │◄──────│ garment_id       │       │ id              │
│ name            │       │ student_id       │───────┤ volunteer_id    │
│ category        │       │ slot_id          │───────┤ date            │
│ size            │       │ status           │       │ start_time      │
│ condition       │       │ outcome          │       │ end_time        │
│ image_path      │       │ will_bring_don.  │       │ max_students    │
│ is_available    │       │ attended         │       │ current_count   │
└─────────────────┘       └──────────────────┘       │ location_id     │
                                                      └─────────────────┘
┌─────────────────┐       ┌──────────────────┐
│   Donation      │       │   PantryCampaign │
├─────────────────┤       ├──────────────────┤
│ id              │       │ id               │
│ code            │       │ name             │
│ donation_type   │       │ description      │
│ donor_id        │       │ requested_item_id│◄───┐
│ donor_name      │       │ goal_quantity    │    │
│ registered_by   │       │ collected_qty    │    │
│ garment_id      │       │ start_date       │    │
│ pantry_item_id  │───┐   │ end_date         │    │
│ campaign_id     │───┼───┤ is_active        │    │
│ quantity        │   │   └──────────────────┘    │
│ notes           │   │                            │
└─────────────────┘   │   ┌──────────────────┐    │
                      └───┤  PantryItem      │────┘
                          ├──────────────────┤
                          │ id               │
                          │ name             │
                          │ category         │
                          │ unit             │
                          │ current_stock    │
                          │ is_active        │
                          └──────────────────┘
```

### Estados de Citas (Appointment.status)

```
┌───────────────────────────────────────────────────┐
│  scheduled → attended → completed → [closed]      │
│       ↓                                            │
│   cancelled                                        │
│       ↓                                            │
│   no_show (si no asistió)                         │
└───────────────────────────────────────────────────┘
```

**Resultados (Appointment.outcome)**:
- `taken`: El estudiante se llevó la prenda
- `not_fit`: No era su talla
- `declined`: Decidió no llevarla

---

## API REST - Endpoints Principales

### Autenticación

Todas las rutas requieren autenticación JWT via cookie `itcj_token`.

---

### Catálogo (Público para estudiantes)

#### `GET /api/vistetec/v1/catalog`

Lista prendas disponibles con paginación y filtros.

**Query params**:
- `category`: Filtrar por categoría (camisa, pantalon, vestido, etc.)
- `size`: Filtrar por talla
- `gender`: Filtrar por género (masculino, femenino, unisex)
- `search`: Búsqueda por texto en nombre/descripción
- `page`: Página (default: 1)
- `per_page`: Resultados por página (default: 12)

**Response**:
```json
{
  "garments": [
    {
      "id": 1,
      "name": "Camisa azul manga larga",
      "category": "camisa",
      "size": "M",
      "gender": "masculino",
      "condition": "como_nuevo",
      "image_path": "2026/02/abc123.jpg",
      "is_available": true,
      "created_at": "2026-02-01T10:30:00"
    }
  ],
  "pagination": {
    "page": 1,
    "pages": 5,
    "total": 48,
    "per_page": 12,
    "has_next": true,
    "has_prev": false
  }
}
```

---

#### `GET /api/vistetec/v1/catalog/<id>`

Obtiene detalle completo de una prenda.

**Response**:
```json
{
  "id": 1,
  "name": "Camisa azul manga larga",
  "category": "camisa",
  "size": "M",
  "gender": "masculino",
  "condition": "como_nuevo",
  "brand": "Polo",
  "description": "Camisa formal en excelente estado",
  "image_path": "2026/02/abc123.jpg",
  "is_available": true,
  "donated_at": "2026-02-01T10:30:00"
}
```

---

### Citas

#### `POST /api/vistetec/v1/appointments`

Crea una cita para probarse una prenda.

**Permisos**: `vistetec.appointments.api.create`

**Body**:
```json
{
  "garment_id": 1,
  "slot_id": 42,
  "will_bring_donation": true
}
```

**Response**:
```json
{
  "message": "Cita agendada correctamente",
  "appointment": {
    "id": 123,
    "code": "VT-2026-0123",
    "status": "scheduled",
    "garment": { "id": 1, "name": "Camisa azul" },
    "slot": {
      "date": "2026-02-15",
      "start_time": "10:00",
      "end_time": "10:30"
    },
    "will_bring_donation": true
  }
}
```

---

#### `POST /api/vistetec/v1/appointments/<id>/cancel`

Cancela una cita propia.

**Permisos**: `vistetec.appointments.api.cancel`

**Response**:
```json
{
  "message": "Cita cancelada correctamente"
}
```

---

#### `GET /api/vistetec/v1/appointments/my-appointments`

Lista citas del usuario actual.

**Query params**:
- `status`: Filtrar por estado
- `include_past`: `true` para incluir citas pasadas

**Response**:
```json
[
  {
    "id": 123,
    "code": "VT-2026-0123",
    "status": "scheduled",
    "garment": { "id": 1, "name": "Camisa azul", "image_path": "..." },
    "slot": { "date": "2026-02-15", "start_time": "10:00" },
    "location": { "name": "Edificio A, Planta Baja" },
    "will_bring_donation": true
  }
]
```

---

### Horarios

#### `GET /api/vistetec/v1/slots`

Lista slots disponibles para agendar.

**Query params**:
- `from_date`: Fecha inicial (YYYY-MM-DD)
- `to_date`: Fecha final
- `location_id`: Filtrar por ubicación

**Response**:
```json
[
  {
    "id": 42,
    "date": "2026-02-15",
    "start_time": "10:00",
    "end_time": "10:30",
    "max_students": 3,
    "current_count": 1,
    "is_available": true,
    "location": { "id": 1, "name": "Edificio A" }
  }
]
```

---

### Donaciones

#### `POST /api/vistetec/v1/donations/garment`

Registra donación de una prenda.

**Permisos**: `vistetec.donations.api.register`

**Body**:
```json
{
  "garment": {
    "name": "Suéter rojo",
    "category": "sueter",
    "size": "L",
    "condition": "buen_estado",
    "gender": "unisex"
  },
  "donor_id": 123,
  "notes": "Excelente estado, sin manchas"
}
```

---

#### `POST /api/vistetec/v1/donations/pantry`

Registra donación de despensa.

**Body**:
```json
{
  "pantry_item_id": 5,
  "quantity": 10,
  "donor_id": 123,
  "campaign_id": 2,
  "notes": "Latas de atún"
}
```

**Nota**: Si se proporciona `campaign_id`, automáticamente se incrementa `campaign.collected_quantity`.

---

#### `GET /api/vistetec/v1/donations/search-donors?q=<query>`

Busca estudiantes para asignar como donantes.

**Response**:
```json
[
  {
    "id": 123,
    "name": "Juan Pérez García",
    "control_number": "20401234"
  }
]
```

---

### Despensa

#### `GET /api/vistetec/v1/pantry/items`

Lista artículos de despensa.

**Query params**:
- `category`: Filtrar por categoría
- `search`: Búsqueda por texto
- `is_active`: `true` para solo activos

---

#### `POST /api/vistetec/v1/pantry/stock/in`

Registra entrada de stock.

**Body**:
```json
{
  "item_id": 5,
  "quantity": 20,
  "notes": "Donación de supermercado X"
}
```

---

#### `GET /api/vistetec/v1/pantry/campaigns/active`

Lista campañas activas de recolección.

**Response**:
```json
[
  {
    "id": 2,
    "name": "Campaña de Navidad 2026",
    "description": "Recolección de alimentos no perecederos",
    "requested_item": { "id": 5, "name": "Atún enlatado" },
    "goal_quantity": 100,
    "collected_quantity": 45,
    "start_date": "2026-12-01",
    "end_date": "2026-12-20",
    "is_active": true
  }
]
```

---

### Reportes (Admin)

#### `GET /api/vistetec/v1/reports/dashboard`

Resumen general para el dashboard.

**Permisos**: `vistetec.reports.api.dashboard`

**Response**:
```json
{
  "total_garments": 120,
  "total_garments_available": 85,
  "total_appointments": 340,
  "total_appointments_completed": 280,
  "total_donations": 450,
  "total_donations_garment": 350,
  "total_donations_pantry": 100
}
```

---

#### `GET /api/vistetec/v1/reports/garments?date_from=<date>&date_to=<date>`

Reporte de prendas por categoría y condición.

**Response**:
```json
{
  "by_category": {
    "camisa": 45,
    "pantalon": 30,
    "vestido": 15
  },
  "by_condition": {
    "nuevo": 20,
    "como_nuevo": 50,
    "buen_estado": 30
  },
  "total": 120
}
```

---

## Instalación y Configuración

### Requisitos Previos

VisteTec es parte del sistema ITCJ y comparte la infraestructura base. Asegúrate de tener:

- Python 3.11+
- PostgreSQL 14+
- Pillow 11.3.0 (para compresión de imágenes)
- Servidor ITCJ funcionando (ver [README principal](../../../README.md))

---

### 1. Aplicar Migraciones

VisteTec incluye migraciones para sus tablas específicas:

```bash
# Ver migraciones de VisteTec
flask db history | grep vistetec

# Aplicar todas las migraciones
flask db upgrade
```

**Migraciones incluidas**:
- Tablas base: garment, appointment, time_slot, donation, location
- Pantry: pantry_item, pantry_campaign
- Mejora: campo `will_bring_donation` en appointments
- Mejora: campo `campaign_id` en donations

---

### 2. Cargar Datos Iniciales

```bash
# Ejecutar scripts DML desde la raíz del proyecto
cd database/DML/vistetec/

# 1. Registrar la app
psql -U postgres -d itcj_db -f 00_insert_app.sql

# 2. Crear roles específicos de VisteTec
psql -U postgres -d itcj_db -f 01_insert_roles.sql

# 3. Crear permisos
psql -U postgres -d itcj_db -f 02_insert_permissions.sql

# 4. Asignar permisos a roles
psql -U postgres -d itcj_db -f 03_insert_role_permissions.sql

# 5. Verificar que todo está correcto
psql -U postgres -d itcj_db -f 04_verify_permissions.sql
```

**Salida esperada del script de verificación**:
```
NOTICE: === VERIFICACIÓN DE PERMISOS DE VISTETEC ===
NOTICE: Total de permisos definidos: 40
NOTICE: ✅ Todos los permisos requeridos existen
NOTICE: === PERMISOS POR ROL ===
NOTICE: student: 13 permisos
NOTICE: volunteer: 22 permisos
NOTICE: admin: 40 permisos (todos)
```

---

### 3. Crear Ubicaciones Iniciales

```sql
-- Conectarse a la base de datos
psql -U postgres -d itcj_db

-- Insertar ubicaciones de ejemplo
INSERT INTO vistetec_locations (name, description) VALUES
('Edificio A - Planta Baja', 'Junto a la cafetería'),
('Edificio B - Segundo Piso', 'Sala de juntas 201'),
('Área de Servicio Social', 'Oficinas administrativas');
```

---

### 4. Asignar Roles a Usuarios

```bash
# Ejemplo: Asignar rol de voluntario a un usuario
flask assign-role <user_id> volunteer --app vistetec

# Asignar rol de admin
flask assign-role <user_id> admin --app vistetec
```

---

### 5. Crear Carpeta de Imágenes

```bash
# Desde la raíz del proyecto
mkdir -p instance/apps/vistetec/garments
chmod 755 instance/apps/vistetec/garments
```

Las imágenes se organizarán automáticamente en subdirectorios por año/mes:
```
instance/apps/vistetec/garments/
└── 2026/
    ├── 01/
    ├── 02/
    └── 03/
```

---

## Flujos de Uso Comunes

### Flujo 1: Estudiante Agenda Cita

1. **Login** → Dashboard ITCJ → Click en app "VisteTec"
2. **Catálogo** → Navegar prendas disponibles
3. **Detalle** → Click en prenda → Ver imágenes y descripción
4. **Agendar** → Click "Agendar cita"
5. **Modal de cita** se abre con:
   - Acordeones por día (solo primero expandido)
   - Banner de campañas activas (si hay)
   - Checkbox "Traeré una donación" (opcional)
6. **Seleccionar horario** → Click en slot disponible
7. **Confirmar** → Cita creada con código único (ej: VT-2026-0123)
8. **Asistir** → Ir a la ubicación en fecha/hora programada
9. **Ver historial** → "Mis Citas" muestra estado y resultado

---

### Flujo 2: Voluntario Atiende Citas del Día

1. **Login** → VisteTec → Dashboard de voluntario
2. **Citas** → Tab "Citas de hoy"
3. **Filtrar** (opcional) → Seleccionar otra fecha si es necesario
4. **Ver cita** → Click en tarjeta de cita
5. **Marcar asistencia** → Botón "Atender"
6. **Registrar resultado**:
   - "taken" si se llevó la prenda
   - "not_fit" si no era su talla
   - "declined" si decidió no llevarla
7. **Link rápido** → Si marcó "Traeré donación", aparece link directo a registro
8. **Siguiente cita** → Volver a la lista

---

### Flujo 3: Voluntario Registra Donación de Despensa

1. **Dashboard** → Click "Registrar Donación"
2. **Paso 1** → Seleccionar "Despensa"
3. **Paso 2** → Información del donante:
   - Buscar estudiante por número de control o nombre
   - O marcar como anónimo
   - O marcar como externo (no estudiante)
4. **Paso 3** → Detalles:
   - Seleccionar artículo (ej: Atún enlatado)
   - Cantidad (ej: 10)
   - Asociar a campaña activa (se autoselecciona si coincide)
   - Notas opcionales
5. **Registrar** → Donación guardada con código
6. **Éxito** → Modal muestra código y opciones:
   - Nueva donación
   - Ir al dashboard

**Nota**: Si se asoció a una campaña, automáticamente se incrementa `collected_quantity`.

---

### Flujo 4: Admin Crea Campaña de Recolección

1. **Login** → VisteTec → Panel de admin
2. **Despensa** → Tab "Campañas"
3. **Nueva campaña** → Click botón "+ Nueva"
4. **Formulario**:
   - Nombre: "Campaña Navidad 2026"
   - Descripción: "Recolección de alimentos no perecederos"
   - Artículo solicitado: Seleccionar de lista (ej: Atún)
   - Meta: 100 unidades
   - Fecha inicio: 2026-12-01
   - Fecha fin: 2026-12-20
5. **Guardar** → Campaña activa
6. **Estudiantes** → Verán esta campaña al agendar citas
7. **Voluntarios** → Podrán asociar donaciones a esta campaña
8. **Progreso** → Barra visual muestra 45/100 (45%)

---

## Convenciones de Código

### Nomenclatura de Permisos

Todos los permisos siguen la estructura:

```
vistetec.{modulo}.{tipo}.{accion}
```

**Ejemplos**:
- `vistetec.catalog.api.list` → Listar catálogo vía API
- `vistetec.appointments.page.my` → Acceder a página "Mis Citas"
- `vistetec.garments.api.create` → Crear prenda vía API
- `vistetec.pantry.api.manage` → Gestionar despensa (CRUD + stock)

---

### Organización de Assets Estáticos

```
static/
├── css/
│   ├── shared/
│   │   └── base.css          # Estilos compartidos
│   ├── student/
│   │   ├── catalog.css
│   │   └── my_appointments.css
│   ├── volunteer/
│   │   ├── appointments.css
│   │   └── register_donation.css
│   └── admin/
│       └── dashboard.css
│
└── js/
    ├── shared/
    │   └── vistetec-utils.js  # VisteTecUtils global
    ├── student/
    │   ├── catalog.js
    │   ├── garment_detail.js
    │   └── my_appointments.js
    ├── volunteer/
    │   ├── appointments.js
    │   ├── garment_form.js
    │   └── register_donation.js
    └── admin/
        ├── dashboard.js
        └── reports.js
```

---

### Patrón JavaScript (IIFE)

Todos los archivos JS siguen este patrón:

```javascript
/**
 * VisteTec - Nombre del Módulo
 */
(function () {
    'use strict';

    const API_BASE = '/api/vistetec/v1';

    // Variables de estado
    let currentPage = 1;

    // Funciones principales
    async function loadData() {
        // ...
    }

    // Event listeners
    document.getElementById('btnSubmit').addEventListener('click', handleSubmit);

    // Inicialización
    loadData();
})();
```

---

### Utilidades Globales (VisteTecUtils)

Disponible en `shared/vistetec-utils.js`:

```javascript
window.VisteTecUtils = {
    /**
     * Muestra toast de notificación
     * @param {string} message - Mensaje a mostrar
     * @param {string} type - 'success' | 'danger' | 'warning' | 'info'
     */
    showToast(message, type = 'info') { ... },

    /**
     * Muestra modal de confirmación
     * @param {string} title - Título del modal
     * @param {string} message - Mensaje
     * @param {Function} onConfirm - Callback al confirmar
     */
    confirmModal(title, message, onConfirm) { ... },

    /**
     * Comprime imagen usando Canvas API
     * @param {File} file - Archivo de imagen
     * @param {number} maxWidth - Ancho máximo (default: 1920)
     * @param {number} quality - Calidad JPEG (default: 0.85)
     * @returns {Promise<Blob>} - Imagen comprimida
     */
    async compressImage(file, maxWidth = 1920, quality = 0.85) { ... }
};
```

---

## Características Técnicas Destacadas

### 1. Compresión de Imágenes de Dos Niveles

**Cliente (JavaScript)**:
```javascript
const compressed = await VisteTecUtils.compressImage(file, 1920, 0.85);
const formData = new FormData();
formData.append('image', compressed, 'image.jpg');
```

**Servidor (Python)**:
```python
# image_service.py
from PIL import Image

def compress_and_save(file, max_width=1920, quality=85):
    img = Image.open(file)
    # ... resize logic ...
    img.save(output_path, 'JPEG', quality=quality, optimize=True)
```

**Resultado**: Imágenes optimizadas sin pérdida visible de calidad.

---

### 2. Acordeones Colapsables por Día

Los horarios se agrupan automáticamente por día usando Bootstrap Accordions:

```javascript
// Ejemplo simplificado
const grouped = slots.reduce((acc, slot) => {
    const date = slot.date;
    if (!acc[date]) acc[date] = [];
    acc[date].push(slot);
    return acc;
}, {});

Object.keys(grouped).sort().forEach((date, index) => {
    const isExpanded = index === 0; // Solo primero expandido
    html += `<div class="accordion-item">
        <button class="accordion-button ${isExpanded ? '' : 'collapsed'}">
            ${formatDate(date)}
        </button>
        <div class="accordion-collapse ${isExpanded ? 'show' : 'collapse'}">
            ${renderSlots(grouped[date])}
        </div>
    </div>`;
});
```

---

### 3. Búsqueda de Estudiantes en Tiempo Real

Implementa debounce para evitar llamadas excesivas:

```javascript
let searchTimeout;

donorSearch.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        const query = donorSearch.value.trim();
        if (query.length >= 2) {
            searchDonors(query);
        }
    }, 300); // 300ms debounce
});
```

---

### 4. Sistema de Versionado de Assets

```jinja
<!-- Template Jinja2 -->
<link href="{{ url_for('static', filename='vistetec/css/catalog.css') }}?v={{ sv('vistetec', 'css/catalog.css') }}" rel="stylesheet">
```

La función `sv()` genera hash del archivo para invalidar cache.

---

## Métricas y Monitoreo

### Métricas Disponibles en Dashboard

- **Prendas**: Total, disponibles, por categoría, por condición
- **Citas**: Total, completadas, canceladas, no-show
- **Donaciones**: Total, por tipo (ropa/despensa), por periodo
- **Campañas**: Activas, progreso de meta, top items recolectados
- **Actividad**: Últimas 15 acciones (registro, citas, donaciones)

---

## Comandos Útiles

```bash
# Ver permisos de VisteTec
psql -U postgres -d itcj_db -c "
SELECT code, name FROM core_permissions
WHERE app_id = (SELECT id FROM core_apps WHERE key = 'vistetec')
ORDER BY code;
"

# Ver roles asignados a usuario
flask list-user-roles <user_id>

# Ver donaciones recientes
psql -U postgres -d itcj_db -c "
SELECT code, donation_type, created_at
FROM vistetec_donations
ORDER BY created_at DESC
LIMIT 10;
"

# Ver campañas activas
psql -U postgres -d itcj_db -c "
SELECT name, goal_quantity, collected_quantity, end_date
FROM vistetec_pantry_campaigns
WHERE is_active = true;
"
```

---

## Troubleshooting

### Problema: No aparece banner de campañas al agendar cita

**Causa**: No hay campañas activas en la base de datos.

**Solución**:
```sql
-- Verificar campañas activas
SELECT * FROM vistetec_pantry_campaigns WHERE is_active = true;

-- Si no hay, crear una de prueba desde el panel de admin
```

---

### Problema: Error al cancelar cita

**Causa**: Permiso faltante en rol student.

**Solución**:
```bash
# Verificar permisos
psql -U postgres -d itcj_db -f database/DML/vistetec/04_verify_permissions.sql

# Aplicar fix
psql -U postgres -d itcj_db -f database/DML/vistetec/03_insert_role_permissions.sql
```

---

### Problema: Imágenes no se comprimen

**Causa**: Pillow no está instalado o está desactualizado.

**Solución**:
```bash
pip install --upgrade Pillow==11.3.0
```

---

### Problema: Error 403 Forbidden en rutas API

**Causa**: Usuario sin permisos necesarios.

**Solución**:
```bash
# Verificar permisos del usuario
flask list-user-roles <user_id>

# Asignar rol correcto
flask assign-role <user_id> volunteer --app vistetec
```

---

## Roadmap y Mejoras Futuras

### Fase 9: Reconocimiento Público (Pendiente - 20%)

- [ ] Página `/vistetec/recognition` pública
- [ ] Top 10 donadores anónimos del mes
- [ ] Gráfico de donaciones acumuladas
- [ ] Metas de campaña con progreso visual

---

### Mejoras Propuestas

**UX/UI**:
- [ ] Filtros adicionales en catálogo (talla, género, búsqueda)
- [ ] Vista de cuadrícula vs lista en catálogo
- [ ] Notificaciones de recordatorio 24h antes de cita
- [ ] Indicador visual de slots con baja disponibilidad

**Funcionalidad**:
- [ ] Exportar reportes a CSV/Excel
- [ ] Gráficos interactivos (Chart.js)
- [ ] Sistema de reservas temporales (soft-hold)
- [ ] Historial de cambios en prendas (auditoría)

**Rediseño de Slots** (Opcional):
- [ ] Slots generales (no atados a voluntario)
- [ ] Tabla junction `SlotVolunteer` para inscripciones N:N
- [ ] Múltiples voluntarios por slot

---

## Documentación Adicional

- **Revisión completa**: [`docs/VISTETEC_REVISION_COMPLETA.md`](../../docs/VISTETEC_REVISION_COMPLETA.md)
- **Permisos actualizados**: [`docs/VISTETEC_PERMISOS_ACTUALIZADOS.md`](../../docs/VISTETEC_PERMISOS_ACTUALIZADOS.md)
- **Plan original**: [`PLAN_APP_RECICLAJE_ROPA.md`](../../PLAN_APP_RECICLAJE_ROPA.md)
- **Plan de rediseño de slots**: `C:\Users\soporte\.claude\plans\vast-moseying-flurry.md`

---

## Licencia

Este módulo es parte del sistema ITCJ y es de uso interno del Instituto Tecnológico de Ciudad Juárez.

---

**Desarrollado con ❤️ para promover la solidaridad y sustentabilidad en la comunidad ITCJ**

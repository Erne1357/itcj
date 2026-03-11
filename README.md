# ITCJ - Plataforma Digital ITCJ

## Descripción General

**ITCJ** (Instituto Tecnológico de Ciudad Juárez) es una plataforma web integral que digitaliza y optimiza las funciones operativas del instituto mediante un ecosistema modular de aplicaciones especializadas. El sistema centraliza la gestión de servicios académicos y técnicos bajo una arquitectura unificada, facilitando procesos administrativos y mejorando la experiencia de usuarios, personal y administradores.

### Propósito

- **Gestión académica eficiente**: Automatización de procesos de altas/bajas de materias y gestión de citas
- **Soporte técnico centralizado**: Sistema de tickets para los departamentos de Desarrollo y Soporte
- **Autenticación unificada**: Sistema central de autenticación con roles y permisos granulares por aplicación
- **Escalabilidad modular**: Arquitectura que permite agregar nuevas aplicaciones sin afectar las existentes

---

## Stack Tecnológico

### Backend

| Componente | Tecnología |
|---|---|
| Framework | FastAPI (Python 3.11+) |
| ORM | SQLAlchemy 2.0 |
| Migraciones | Alembic |
| Servidor ASGI | Uvicorn |
| Templates | Jinja2 3.1 |
| Validación | Pydantic Settings |

### Autenticación y Seguridad

| Componente | Tecnología |
|---|---|
| Tokens | JWT (PyJWT) en cookies HTTP-only |
| Contraseñas | bcrypt (via Werkzeug) |
| Autorización | Roles y permisos granulares por app |
| Middleware | Starlette `BaseHTTPMiddleware` |

### Tiempo Real

| Componente | Tecnología |
|---|---|
| WebSockets | python-socketio (asyncio) |
| Message Broker | Redis 7 |

### Base de Datos

| Componente | Tecnología |
|---|---|
| Motor | PostgreSQL 14+ |
| Connection Pool | PgBouncer |

### Frontend

| Componente | Tecnología |
|---|---|
| UI Framework | Bootstrap 5 |
| JavaScript | Vanilla JS (sin frameworks) |
| Iconos | Bootstrap Icons |

### Procesamiento de Datos

| Componente | Tecnología |
|---|---|
| Imagenes | Pillow 11+ |
| Excel | xlsxwriter, openpyxl |
| PDF | ReportLab |
| Documentos | python-docx |
| Analisis | pandas |

### Infraestructura

| Componente | Tecnología |
|---|---|
| Proxy Reverso | Nginx (archivos estáticos + proxy) |
| Contenedorizacion | Docker Compose |
| CLI | Click |

---

## Arquitectura del Sistema

### Estructura de Directorios

```
ITCJ/
├── asgi.py                         # Entry point ASGI (uvicorn target)
├── requirements.txt
├── .env                            # Variables de entorno (no en Git)
│
├── itcj2/                          # Paquete principal (FastAPI)
│   ├── main.py                     # Factory: create_app() → FastAPI
│   ├── config.py                   # Configuración global (Pydantic Settings)
│   ├── routers.py                  # Registro centralizado de routers
│   ├── middleware.py               # JWTMiddleware + CORSMiddleware
│   ├── templates.py                # Configuración Jinja2 + url_for()
│   ├── database.py                 # Engine SQLAlchemy + SessionLocal
│   ├── exceptions.py               # PageLoginRequired, PageForbidden
│   ├── utils.py                    # Utilidades globales
│   │
│   ├── cli/                        # Herramientas de administración (Click)
│   │   ├── main.py                 # Entry point: python -m itcj2.cli.main
│   │   ├── core.py                 # init-db, reset-db, check-db, init-themes
│   │   ├── helpdesk.py             # load-inventory-csv
│   │   ├── agendatec.py            # seed-periods, import-students, sync-students
│   │   └── vistetec.py             # init-vistetec
│   │
│   ├── core/                       # Nucleo compartido
│   │   ├── models/                 # User, Role, Department, Permission, AcademicPeriod
│   │   ├── api/                    # REST: auth, users, authz, departments, themes
│   │   ├── pages/                  # HTML: login, dashboard, perfil, config, movil
│   │   ├── schemas/                # Pydantic validators del core
│   │   ├── services/               # AuthService, PermissionService, ThemeService
│   │   ├── templates/              # Templates Jinja2 base y layouts
│   │   ├── static/                 # CSS, JS e imagenes del core
│   │   ├── router.py               # APIRouter del core (/api/core/v2)
│   │   └── utils/                  # Decoradores: @login_required, @permission_required
│   │
│   ├── apps/                       # Aplicaciones modulares
│   │   ├── agendatec/              # Gestion de altas/bajas de materias
│   │   ├── helpdesk/               # Tickets de soporte + inventario institucional
│   │   ├── vistetec/               # Reciclaje de ropa y gestion de despensa
│   │   └── warehouse/              # Almacen global compartido (en desarrollo)
│   │
│   ├── models/                     # Registro central de todos los modelos
│   └── sockets/                    # Namespaces Socket.IO (asyncio)
│
├── migrations/                     # Migraciones Alembic
│   ├── env.py
│   ├── alembic.ini
│   └── versions/
│
├── database/
│   ├── DDL/                        # Esquemas SQL
│   ├── DML/                        # Datos iniciales por modulo
│   └── CSV/                        # Archivos de importacion masiva
│
├── docker/
│   ├── backend/                    # Dockerfile.fastapi, Dockerfile.db, pgbouncer/
│   ├── compose/                    # docker-compose.dev.yml, docker-compose.prod.yml
│   └── nginx/                      # nginx.dev.conf, nginx.prod.conf
│
├── instance/                       # Archivos de instancia (uploads, adjuntos)
│   └── apps/
│       ├── helpdesk/               # Adjuntos de tickets
│       └── vistetec/               # Imagenes de prendas
│
└── tests/
    └── fastapi/
```

### Flujo de Inicio

```
uvicorn asgi:app
    │
    └── asgi.py
          ├── create_app()            → FastAPI (itcj2/main.py)
          │     ├── setup_middleware() → JWTMiddleware + CORS
          │     ├── register_routers() → core, helpdesk, agendatec, vistetec, warehouse
          │     └── lifespan()        → captura event loop, dispose engine al cerrar
          │
          └── socketio.ASGIApp(sio, fastapi_app)
                ├── /socket.io/*     → AsyncServer (python-socketio)
                └── /*               → FastAPI
```

### Estructura Interna de Cada App

Todas las apps en `itcj2/apps/` siguen la misma convención:

```
app_name/
├── router.py           # APIRouter principal (registrado en itcj2/routers.py)
├── models/             # Modelos SQLAlchemy (tablas app_name_*)
├── api/                # Routers REST  →  /api/app-name/v2/...
├── pages/              # Routers HTML  →  /app-name/...
│   └── router.py       # Registro del APIRouter de paginas
├── schemas/            # Pydantic schemas (request/response)
├── services/           # Logica de negocio
├── utils/              # Helpers especificos de la app
├── templates/          # Templates Jinja2
├── static/             # CSS, JS, imagenes (servidos por Nginx)
└── README.md           # Documentacion de la app
```

---

## Sistema de Autenticacion y Autorizacion

### Autenticacion

- **Metodo**: JWT almacenado en cookie HTTP-only `itcj_token`
- **Algoritmo**: HS256
- **Expiracion**: 12 horas (configurable en `JWT_EXPIRES_HOURS`)
- **Refresh automatico**: Si el token expira en menos de 2 horas se renueva en la misma respuesta
- **Seguridad**: `httponly=True`, `samesite=lax`, `secure` configurable por entorno

### Autorizacion

El sistema usa roles y permisos granulares por aplicacion:

```
core_roles            →  Rol base (student, staff, coordinator, admin, etc.)
core_app_roles        →  Rol dentro de una app especifica
core_user_app_roles   →  Asignacion de usuario a un rol de app
core_permissions      →  Permiso individual (ej: helpdesk.ticket.create)
core_role_permissions →  Permisos asignados a un rol
```

### Decoradores de Proteccion

```python
from itcj2.core.utils.decorators import login_required, permission_required, role_required

@login_required                           # Requiere autenticacion
@role_required(["admin", "tech"])         # Requiere rol especifico
@permission_required("ticket.edit")       # Requiere permiso especifico
```

---

## Aplicaciones Incluidas

### Core

Sistema central de autenticacion, usuarios, roles y configuracion global.

- **API**: `/api/core/v2/`
- **Paginas**: `/itcj/` (login, dashboard, perfil, configuracion, movil)
- **Modulos API**: auth, users, authz, departments, positions, themes, notifications, mobile

---

### AgendaTec — Gestion de Altas y Bajas

Sistema para gestionar solicitudes de altas y bajas de materias con citas coordinadas.

**Documentacion detallada**: [`itcj2/apps/agendatec/README.md`](itcj2/apps/agendatec/README.md)

- **API**: `/api/agendatec/v2/`
- **Paginas**: `/agendatec/`

---

### Help-Desk — Soporte Tecnico e Inventario

Sistema integral de soporte tecnico con gestion de tickets, asignaciones y control de equipos institucionales.

**Documentacion detallada**: [`itcj2/apps/helpdesk/README.md`](itcj2/apps/helpdesk/README.md)

- **API**: `/api/help-desk/v2/`
- **Paginas**: `/help-desk/`

---

### VisteTec — Reciclaje de Ropa y Despensa

Sistema de economia circular para donacion, distribucion y reciclaje de ropa, con gestion de campanas de despensa.

**Documentacion detallada**: [`itcj2/apps/vistetec/README.md`](itcj2/apps/vistetec/README.md)

- **API**: `/api/vistetec/v2/`
- **Paginas**: `/vistetec/`

---

### Warehouse — Almacen Global *(en desarrollo)*

Modulo de almacen compartido entre Help-Desk y la futura app de Mantenimiento. Controlara stock de insumos con consumo FIFO, alertas de restock y movimientos por departamento.

- **API**: `/api/warehouse/v2/`
- **Paginas**: `/warehouse/` *(en desarrollo)*

---

## Instalacion y Configuracion

### Requisitos Previos

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Docker y Docker Compose (recomendado)

### Variables de Entorno

Crea un archivo `.env` en la raiz del proyecto:

```bash
# Base de datos (conexion a traves de PgBouncer)
DATABASE_URL=postgresql+psycopg2://itcj_user:password@pgbouncer:5432/itcj_db

# Conexion directa a PostgreSQL para migraciones Alembic (sin PgBouncer)
MIGRATE_DATABASE_URL=postgresql+psycopg2://itcj_user:password@postgres:5432/itcj_db

# Seguridad
SECRET_KEY=your-secret-key-here
JWT_EXPIRES_HOURS=12

# Redis
REDIS_URL=redis://redis:6379/0

# Entorno
FLASK_ENV=development    # o production
COOKIE_SECURE=false      # true en produccion (HTTPS)
COOKIE_SAMESITE=lax
```

---

### Opcion 1: Docker — Desarrollo

```bash
git clone <repository-url>
cd ITCJ
cp .env.example .env          # editar con tus valores

# Levantar servicios
docker-compose -f docker/compose/docker-compose.dev.yml up --build

# Aplicar migraciones (en otra terminal)
docker-compose exec backend alembic upgrade head

# Cargar datos iniciales (roles, permisos, departamentos, admin)
docker-compose exec backend python -m itcj2.cli.main core init-db
```

Servicios disponibles:
- **Aplicacion**: http://localhost:8080
- **API Docs (Swagger)**: http://localhost:8080/api/docs
- **API Docs (ReDoc)**: http://localhost:8080/api/redoc
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

---

### Opcion 2: Docker — Produccion (Blue/Green)

El entorno de produccion usa un esquema de despliegue blue/green con dos instancias del backend (`backend-blue` y `backend-green`) gestionadas por perfiles de Docker Compose. Nginx actua como balanceador y proxy reverso.

```bash
# Activar perfil blue (primera instancia)
docker-compose -f docker/compose/docker-compose.prod.yml --profile blue up -d

# Para despliegue sin downtime, levantar green y luego apagar blue
docker-compose -f docker/compose/docker-compose.prod.yml --profile green up -d
```

> Los archivos estaticos son servidos directamente por Nginx sin pasar por el backend.
> El compose de produccion usa `.env.prod` en lugar de `.env`.

---

### Opcion 3: Local — Desarrollo

```bash
git clone <repository-url>
cd ITCJ

# Entorno virtual
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# Dependencias
pip install -r requirements.txt

# Configurar .env con DATABASE_URL apuntando a PostgreSQL local
# Asegurarse de tener PostgreSQL y Redis corriendo

# Migraciones
alembic upgrade head

# Datos iniciales
python -m itcj2.cli.main core init-db

# Servidor de desarrollo
uvicorn asgi:app --host 0.0.0.0 --port 8001 --reload
```

La aplicacion estara disponible en: http://localhost:8001

---

## Migraciones de Base de Datos

Las migraciones se gestionan directamente con **Alembic** (sin Flask-Migrate).

> Para migraciones se recomienda definir `MIGRATE_DATABASE_URL` con conexion directa a PostgreSQL, ya que PgBouncer en modo transaccional puede causar conflictos con operaciones DDL.

```bash
# Ver estado actual
alembic current

# Ver historial
alembic history

# Crear nueva migracion (detecta cambios automaticamente)
alembic revision --autogenerate -m "Descripcion del cambio"

# Aplicar todas las migraciones pendientes
alembic upgrade head

# Revertir ultima migracion
alembic downgrade -1

# Revertir a una revision especifica
alembic downgrade <revision_id>
```

### Agregar Modelos a las Migraciones

Cuando se crea una nueva app, importar sus modelos en `migrations/env.py`:

```python
import itcj2.apps.nueva_app.models  # noqa: F401
```

---

## CLI de Administracion

El CLI se ejecuta con:

```bash
python -m itcj2.cli.main [grupo] [comando]
```

### `core` — Gestion del nucleo

```bash
# Carga todos los scripts DML de inicializacion en orden
python -m itcj2.cli.main core init-db

# Elimina todas las tablas, las recrea y ejecuta init-db
python -m itcj2.cli.main core reset-db

# Muestra conteos de las tablas principales del core
python -m itcj2.cli.main core check-db

# Inicializa el sistema de tematicas visuales
python -m itcj2.cli.main core init-themes

# Ejecuta un archivo SQL especifico
python -m itcj2.cli.main core execute-sql database/DML/core/init/05_insert_permissions.sql
```

### `helpdesk` — Gestion de Help-Desk

```bash
# Importa equipos desde database/CSV/inventario.csv
python -m itcj2.cli.main helpdesk load-inventory-csv
```

### `agendatec` — Gestion de AgendaTec

```bash
# Crea los periodos academicos base y migra solicitudes existentes
python -m itcj2.cli.main agendatec seed-periods

# Activa un periodo especifico (desactiva el actual)
python -m itcj2.cli.main agendatec activate-period <id>

# Lista todos los periodos con su estado
python -m itcj2.cli.main agendatec list-periods

# Importa estudiantes desde CSV (requiere: no_de_control, nombre, nip)
python -m itcj2.cli.main agendatec import-students --csv-path database/CSV/alumnos.csv

# Sincroniza estudiantes y asigna rol student para AgendaTec
# Con --deactivate-missing desactiva usuarios que ya no estan en el CSV
python -m itcj2.cli.main agendatec sync-students-agendatec --csv-path database/CSV/alumnos.csv
python -m itcj2.cli.main agendatec sync-students-agendatec --dry-run  # solo simula
```

### `vistetec` — Gestion de VisteTec

```bash
# Ejecuta los scripts DML de database/DML/vistetec/ en orden
python -m itcj2.cli.main vistetec init-vistetec
```

---

## Estructura de la Base de Datos

### Core (`core_*`)

| Tabla | Descripcion |
|---|---|
| `core_users` | Usuarios del sistema |
| `core_roles` | Roles base |
| `core_app_roles` | Roles por aplicacion |
| `core_user_app_roles` | Asignacion usuario a rol de app |
| `core_permissions` | Permisos granulares (`app.recurso.accion`) |
| `core_role_permissions` | Permisos asignados a un rol |
| `core_departments` | Departamentos institucionales |
| `core_positions` | Puestos/posiciones |
| `core_user_positions` | Asignacion usuario a puesto |
| `core_apps` | Apps registradas en el sistema |
| `core_themes` | Tematicas visuales |
| `core_academic_periods` | Periodos academicos (compartido con AgendaTec) |

### AgendaTec, Help-Desk y VisteTec

Ver README de cada app para el detalle de sus tablas:
- [`itcj2/apps/agendatec/README.md`](itcj2/apps/agendatec/README.md)
- [`itcj2/apps/helpdesk/README.md`](itcj2/apps/helpdesk/README.md)
- [`itcj2/apps/vistetec/README.md`](itcj2/apps/vistetec/README.md)

### Warehouse (`warehouse_*`) *(en desarrollo)*

| Tabla | Descripcion |
|---|---|
| `warehouse_categories` | Categorias y subcategorias de productos |
| `warehouse_products` | Productos del almacen |
| `warehouse_stock_entries` | Entradas de stock (base para FIFO) |
| `warehouse_movements` | Movimientos de consumo y ajuste |

---

## Documentacion de API

La documentacion interactiva de la API esta disponible automaticamente via FastAPI:

- **Swagger UI**: `/api/docs`
- **ReDoc**: `/api/redoc`
- **OpenAPI JSON**: `/api/openapi.json`

### Health Check

```
GET /health
Response: {"ok": true, "server": "fastapi", "version": "2.0.0"}
```

### Autenticacion (Core)

**`POST /api/core/v2/auth/login`**

```json
// Request
{"username": "user123", "password": "password123"}

// Response 200
{
  "ok": true,
  "user": {"id": 1, "username": "user123", "full_name": "Juan Perez"},
  "apps": ["helpdesk", "agendatec"]
}
```

La cookie `itcj_token` (JWT, HTTP-only) se establece automaticamente en la respuesta.

**`GET /api/core/v2/auth/me`** — Retorna el usuario autenticado (requiere cookie).

**`POST /api/core/v2/auth/logout`** — Elimina la cookie `itcj_token`.

---

## Guia de Desarrollo

### Convenciones de Codigo

| Elemento | Convencion |
|---|---|
| Clases | `PascalCase` |
| Funciones y variables | `snake_case` |
| Constantes | `UPPER_SNAKE_CASE` |
| Privados | Prefijo `_` |

### Estructura de un Modelo SQLAlchemy

```python
from itcj2.models.base import Base
from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Index
from sqlalchemy.orm import relationship

class ExampleModel(Base):
    __tablename__ = "app_example"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)

    user = relationship("User", backref="examples")

    __table_args__ = (
        Index("ix_example_user", "user_id"),
    )
```

### Estructura de un Router API

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from itcj2.database import get_db
from itcj2.core.utils.decorators import login_required, permission_required

router = APIRouter()

@router.get("/")
@login_required
@permission_required("example.view")
def list_examples(db: Session = Depends(get_db)):
    return {"examples": []}

@router.post("/", status_code=201)
@login_required
@permission_required("example.create")
def create_example(db: Session = Depends(get_db)):
    return {"ok": True}
```

### Agregar una Nueva Aplicacion

1. **Crear la estructura de directorios**:

```bash
mkdir -p itcj2/apps/nueva_app/{api,pages,models,schemas,services,utils}
mkdir -p itcj2/apps/nueva_app/{templates/nueva_app,static/{css,js}}
```

2. **Crear `router.py`**:

```python
from fastapi import APIRouter
from .api.resources import router as resources_router

nueva_app_router = APIRouter(prefix="/api/nueva-app/v1", tags=["nueva_app"])
nueva_app_router.include_router(resources_router, prefix="/resources")
```

3. **Registrar en `itcj2/routers.py`**:

```python
from itcj2.apps.nueva_app.router import nueva_app_router
app.include_router(nueva_app_router)
```

4. **Importar modelos en `migrations/env.py`**:

```python
import itcj2.apps.nueva_app.models  # noqa: F401
```

5. **Crear y aplicar migracion**:

```bash
alembic revision --autogenerate -m "Add nueva_app models"
alembic upgrade head
```

6. **Agregar datos iniciales** en `database/DML/nueva_app/` y cargarlos con:

```bash
python -m itcj2.cli.main core execute-sql database/DML/nueva_app/01_init.sql
```

### Archivos Estaticos

Los archivos estaticos son servidos por **Nginx**, no por FastAPI. Los volumenes de Nginx apuntan directamente a los directorios `static/` de cada app.

- Rutas: `/static/{app}/css/...`, `/static/{app}/js/...`
- En templates usar: `{{ sv('app', 'css/styles.css') }}` (incluye version para cache-busting)
- El manifesto `static-manifest.json` en la raiz mapea archivos a hashes

### Sistema de Permisos

Los permisos siguen el formato `app.recurso.accion` (ej: `helpdesk.ticket.create`).

Se definen en scripts SQL dentro de `database/DML/{app}/` y se cargan via `core init-db` o con el comando especifico de la app. No existe un sistema de seeds en Python para permisos.

---

## Testing

```bash
# Todos los tests
pytest

# Tests de FastAPI especificamente
pytest tests/fastapi/

# Con cobertura
pytest --cov=itcj2 tests/
```

---

## Convenciones de Commits

Seguir [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(helpdesk): add bulk transfer endpoint
fix(auth): correct JWT refresh threshold calculation
docs(readme): update installation instructions for FastAPI
refactor(agendatec): extract slot generation to service layer
```

Tipos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

---

## Changelog

### Marzo 2026

#### Apps en Produccion
- **AgendaTec**: Gestion de altas/bajas con periodos academicos y citas
- **Help-Desk**: Tickets de soporte con inventario, metricas SLA y modulo de estadisticas/analisis
- **VisteTec**: Catalogo de ropa, citas, donaciones y gestion de despensa (fases 1-8 completas)

#### En Desarrollo
- **Warehouse**: Modulo de almacen global compartido (estructura implementada, en construccion)
- **VisteTec Fase 9**: Pagina publica de reconocimiento a donadores
- **App de Mantenimiento**: Sistema de tickets para mantenimiento de instalaciones (planificada)

---

**Desarrollado para el Instituto Tecnologico de Ciudad Juarez**

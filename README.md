# ITCJ - Plataforma Digital ITCJ

## Descripción General

**ITCJ** (Instituto Tecnológico de Ciudad Juárez) es una plataforma web integral diseñada para digitalizar y optimizar las funciones operativas del instituto mediante un ecosistema modular de aplicaciones especializadas. El sistema centraliza la gestión de servicios académicos y técnicos bajo una arquitectura unificada, facilitando procesos administrativos y mejorando la experiencia de usuarios, personal y administradores.

### Propósito

Digitalizar las funciones cróticas del instituto encapsulándolas en aplicaciones modulares independientes, permitiendo:

- **Gestión académica eficiente**: Automatización de procesos de altas/bajas de materias y gestión de citas
- **Soporte técnico centralizado**: Sistema de tickets para desarrollo y soporte técnico
- **Autenticación unificada**: Sistema central de autenticación con roles y permisos granulares
- **Escalabilidad modular**: Arquitectura que permite agregar nuevas aplicaciones sin afectar las existentes

---

## Stack Tecnológico

### Backend
- **Framework**: Flask 3.1.1 (Python)
- **Base de Datos**: PostgreSQL
- **ORM**: SQLAlchemy 2.0.43
- **Migraciones**: Alembic 1.16.5 (Flask-Migrate 4.1.0)

### Tiempo Real
- **WebSockets**: Flask-SocketIO 5.4.1
- **Message Broker**: Redis 5.0.1
- **Transport**: python-socketio, python-engineio

### Autenticación y Seguridad
- **Autenticación**: JWT (PyJWT 2.10.1)
- **Encriptación de contraseñas**: Werkzeug 3.1.3
- **Gestión de sesiones**: Flask-Login 0.6.3
- **Autorización**: Sistema personalizado basado en roles y permisos

### Frontend
- **Templates**: Jinja2 3.1.6
- **CSS Framework**: Bootstrap 5 (integrado en templates)
- **JavaScript**: Vanilla JS + WebSockets
- **Formularios**: WTForms 3.2.1, Flask-WTF 1.2.2

### Procesamiento de Datos
- **Análisis**: pandas 2.3.2, numpy 2.3.2
- **Exportación**: xlsxwriter 3.2.5 (Excel)
- **Imágenes**: Pillow 11.3.0

### Servidor de Aplicaciones
- **WSGI**: Gunicorn 23.0.0
- **Workers**: Eventlet 0.40.2 (soporte para WebSockets)
- **Proxy Reverso**: Nginx (Docker)

### Contenerización y Despliegue
- **Docker**: Multi-contenedor
- **Orquestación**: Docker Compose
- **Servicios**: PostgreSQL, Redis, Backend (Flask+Gunicorn), Nginx

---

## Arquitectura del Sistema

### Estructura Modular

`
ITCJ/
 itcj/                          # Paquete principal
    __init__.py                # Factory de la aplicación
    config.py                  # Configuración global
   
    core/                      # Núcleo compartido
       models/                # Modelos centrales (User, Role, Department, etc.)
       routes/                # Rutas globales (auth, config)
       services/              # Servicios compartidos (authz, permissions)
       utils/                 # Utilidades (JWT, decorators, helpers)
       templates/             # Templates base y layouts
       static/                # Assets compartidos (CSS, JS, images)
       sockets/               # Configuración de SocketIO
       extensions.py          # Inicialización de extensiones (db, migrate)
   
    apps/                      # Aplicaciones modulares
        agendatec/             # Sistema de gestión de altas/bajas
           models/            # Modelos de AgendaTec
           routes/            # API y páginas
           services/          # Lógica de negocio
           templates/         # Templates específicos
           static/            # Assets específicos
           README.md          # Documentación de AgendaTec
       
        helpdesk/              # Sistema de tickets de soporte
            models/            # Modelos de Help-Desk
            routes/            # API y páginas
            services/          # Lógica de negocio
            templates/         # Templates específicos
            static/            # Assets específicos
            utils/             # Utilidades específicas
            README.md          # Documentación de Help-Desk

 migrations/                    # Migraciones de base de datos (Alembic)
 database/                      # Scripts SQL y dumps
    DDL/                       # Definición de esquemas
    DML/                       # Datos iniciales
    CSV/                       # Importación de datos

 docker/                        # Configuración de contenedores
    backend/                   # Dockerfile del backend
    nginx/                     # Configuración de Nginx
    compose/                   # Archivos de Docker Compose

 instance/                      # Datos específicos de instancia
    apps/                      # Archivos de apps (uploads, attachments)
    config.py                  # Configuración local (no en Git)

 requirements.txt               # Dependencias de Python
 wsgi.py                        # Punto de entrada WSGI
 .env                           # Variables de entorno (no en Git)
 README.md                      # Este archivo
`

### Flujo de Arquitectura

1. **Punto de Entrada**: `wsgi.py` crea la aplicación usando el factory pattern de `itcj/__init__.py`
2. **Configuración**: Carga `itcj/config.py` y opcionalmente `instance/config.py`
3. **Inicialización**:
   - Extensiones (SQLAlchemy, Flask-Migrate, SocketIO)
   - Blueprints del core (`api_core_bp`, `pages_core_bp`)
   - Blueprints de apps (`agendatec_api_bp`, `helpdesk_api_bp`, etc.)
4. **Middleware**:
   - `before_request`: Decodifica JWT y carga usuario en `g.current_user`
   - `after_request`: Refresca token JWT si está próximo a expirar
   - `teardown_request`: Limpia sesión de base de datos
5. **Enrutamiento**: Cada app tiene sus propios blueprints separados por API y páginas

### Sistema de Autenticación y Autorización

#### Autenticación
- **Método**: JWT (JSON Web Tokens) almacenado en cookies HTTP-only
- **Expiración**: Configurable (default: 12 horas)
- **Refresh automático**: Si el token expira en menos de 2 horas, se renueva automáticamente
- **Seguridad**: Cookies con `httponly=True`, `samesite="Lax"`

#### Autorización
- **Modelo de Permisos**: Basado en roles y permisos granulares por aplicación
- **Tablas principales**:
  - `core_users`: Usuarios del sistema
  - `core_roles`: Roles base (student, staff, coordinator, admin)
  - `core_app_roles`: Roles especóficos por aplicación
  - `core_user_app_roles`: Asignación de usuarios a roles por app
  - `core_permissions`: Permisos granulares (ej: `helpdesk.ticket.create`)
  - `core_role_permissions`: Permisos asignados a roles

#### Decorators de Protección
```python
@login_required                      # Requiere autenticación
@role_required(["admin", "tech"])    # Requiere rol especófico
@permission_required("ticket.edit")  # Requiere permiso especófico
@guard_blueprint(blueprint, "app")   # Protege blueprint completo
```

---

## Aplicaciones Incluidas

### 1. AgendaTec - Gestión de Altas y Bajas

Sistema para gestionar solicitudes de altas y bajas de materias con citas coordinadas.

**Caracterósticas principales**:
- Solicitudes de baja (DROP) directas
- Solicitudes de cita (APPOINTMENT) para alta o alta+baja
- Mini-calendario interactivo con slots de 10 minutos
- Bloqueo de horarios en tiempo real (soft-holds con Redis)
- Notificaciones in-app en tiempo real
- Paneles diferenciados por rol (estudiante, servicio social, coordinador, admin)

**Roles**:
- `student`: Crea solicitudes y consulta estado
- `social_service`: Verifica citas antes del acceso al coordinador
- `coordinator`: Gestiona solicitudes y citas
- `admin`: Configuración global del sistema

**Tecnologóas especiales**:
- WebSockets para sincronización de slots en tiempo real
- Redis para soft-holds temporales (TTL 45s)
- Sistema de ventanas de disponibilidad y generación de slots

"š **Documentación detallada**: [`itcj/apps/agendatec/README.md`](itcj/apps/agendatec/README.md)

---

### 2. Help-Desk - Gestión de Tickets de Soporte

Sistema integral de soporte técnico con gestión de tickets, asignaciones y seguimiento de equipos.

**Caracterósticas principales**:
- Sistema de tickets con flujo de estados configurable
- Clasificación por área (Desarrollo / Soporte)
- Sistema de prioridades (BAJA, MEDIA, ALTA, URGENTE)
- Asignación automática o manual a técnicos/equipos
- Gestión de inventario de equipos institucionales
- Métricas de SLA (Service Level Agreement)
- Sistema de calificaciones y encuestas de satisfacción
- Comentarios y adjuntos en tickets
- Colaboradores en tickets

**Roles**:
- `staff`: Crea y consulta sus propios tickets
- `secretary`: Crea tickets en nombre de otros usuarios
- `tech_desarrollo`: Técnico de desarrollo de software
- `tech_soporte`: Técnico de soporte técnico
- `department_head`: Jefe de departamento (gestión de inventario)
- `admin`: Administrador con acceso completo

**Flujo de Estados de Tickets**:
```
PENDING â’ ASSIGNED â’ IN_PROGRESS â’ RESOLVED_SUCCESS/RESOLVED_FAILED â’ CLOSED
                                  â"
                              CANCELED
```

**Módulos principales**:
- **Tickets**: Gestión completa de solicitudes de soporte
- **Inventario**: Registro y asignación de equipos institucionales
- **Asignaciones**: Distribución de trabajo entre técnicos
- **Comentarios**: Comunicación interna en tickets
- **Adjuntos**: Subida de imágenes y documentos
- **Métricas**: Análisis de SLA, tiempos de resolución, calidad

"š **Documentación detallada**: [`itcj/apps/helpdesk/README.md`](itcj/apps/helpdesk/README.md)

---

## Instalación y Configuración

### Requisitos Previos

- **Python**: 3.11 o superior
- **PostgreSQL**: 14 o superior
- **Redis**: 7 o superior
- **Docker y Docker Compose** (recomendado)
- **Git**: Para clonar el repositorio

### Opción 1: Instalación con Docker (Recomendado)

#### 1. Clonar el repositorio

```bash
git clone <repository-url>
cd ITCJ
```

#### 2. Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```bash
# Base de datos
DATABASE_URL=postgresql://itcj_user:your_password@db:5432/itcj_db

# Seguridad
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here

# Redis
REDIS_URL=redis://redis:6379/0

# Flask
FLASK_ENV=production
FLASK_DEBUG=0

# SocketIO
SOCKETIO_MESSAGE_QUEUE=redis://redis:6379/0
```

#### 3. Construir y levantar los contenedores

```bash
docker-compose up --build
```

Los servicios estarán disponibles en:
- **Aplicación**: http://localhost:80
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

#### 4. Aplicar migraciones

```bash
docker-compose exec backend flask db upgrade
```

#### 5. Crear datos iniciales

```bash
# Roles y permisos base
docker-compose exec backend flask seed-roles

# Usuario administrador
docker-compose exec backend flask create-admin

# Datos de ejemplo (opcional, solo para desarrollo)
docker-compose exec backend flask seed-dev
```

---

### Opción 2: Instalación Local (Desarrollo)

#### 1. Clonar el repositorio

```bash
git clone <repository-url>
cd ITCJ
```

#### 2. Crear entorno virtual

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

#### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

#### 4. Configurar PostgreSQL

```bash
# Conectarse a PostgreSQL
psql -U postgres

# Crear base de datos y usuario
CREATE DATABASE itcj_db;
CREATE USER itcj_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE itcj_db TO itcj_user;
\q
```

#### 5. Configurar Redis

```bash
# Instalar Redis (Ubuntu/Debian)
sudo apt-get install redis-server
sudo systemctl start redis

# macOS con Homebrew
brew install redis
brew services start redis

# Windows: Descargar desde https://redis.io/download
```

#### 6. Configurar variables de entorno

Crea un archivo `.env` en la raíz:

```bash
DATABASE_URL=postgresql://itcj_user:your_password@localhost:5432/itcj_db
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key-here
REDIS_URL=redis://localhost:6379/0
FLASK_ENV=development
FLASK_DEBUG=1
```

#### 7. Aplicar migraciones

```bash
flask db upgrade
```

#### 8. Crear datos iniciales

```bash
# Roles y permisos
flask seed-roles

# Usuario admin
flask create-admin

# Datos de ejemplo (opcional)
flask seed-dev
```

#### 9. Ejecutar el servidor

```bash
# Modo desarrollo con SocketIO
python wsgi.py

# O con Flask CLI (sin SocketIO)
flask run --host=0.0.0.0 --port=8000
```

La aplicación estará disponible en: http://localhost:8000

---

## Comandos Flask Disponibles

### Gestión de Base de Datos

```bash
# Ver todas las migraciones
flask db history

# Crear nueva migración
flask db migrate -m "Descripción del cambio"

# Aplicar migraciones pendientes
flask db upgrade

# Revertir última migración
flask db downgrade

# Ver estado actual
flask db current
```

### Gestión de Usuarios y Roles

```bash
# Crear usuario administrador
flask create-admin

# Crear roles y permisos base
flask seed-roles

# Listar todos los usuarios
flask list-users

# Asignar rol a usuario (Help-Desk)
flask assign-role <user_id> <role_name> --app helpdesk

# Listar roles de un usuario
flask list-user-roles <user_id>
```

### Datos de Ejemplo (Solo Desarrollo)

```bash
# Cargar todos los datos de ejemplo
flask seed-dev

# Solo usuarios de ejemplo
flask seed-users

# Solo datos de AgendaTec
flask seed-agendatec

# Solo datos de Help-Desk
flask seed-helpdesk
```

### Mantenimiento de Help-Desk

```bash
# Limpiar archivos adjuntos huérfanos
flask helpdesk-cleanup-attachments

# Generar reporte de tickets
flask helpdesk-ticket-report

# Actualizar métricas de SLA
flask helpdesk-update-sla
```

---

## Estructura de la Base de Datos

### Esquemas Principales

#### Core (Compartido)
- `core_users`: Usuarios del sistema
- `core_roles`: Roles base
- `core_departments`: Departamentos institucionales
- `core_positions`: Puestos/posiciones
- `core_user_positions`: Asignaciín de usuarios a puestos
- `core_app_roles`: Roles por aplicación
- `core_user_app_roles`: Asignaciín de roles por app
- `core_permissions`: Permisos granulares
- `core_role_permissions`: Permisos por rol

#### AgendaTec
- `agendatec_requests`: Solicitudes de altas/bajas
- `agendatec_appointments`: Citas programadas
- `agendatec_coordinators`: Coordinadores de carrera
- `agendatec_programs`: Programas académicos
- `agendatec_availability_windows`: Ventanas de disponibilidad
- `agendatec_time_slots`: Slots reservables
- `agendatec_notifications`: Notificaciones
- `agendatec_audit_logs`: Auditoróa

#### Help-Desk
- `helpdesk_ticket`: Tickets de soporte
- `helpdesk_category`: Categoróas de tickets
- `helpdesk_assignment`: Asignaciones de tickets
- `helpdesk_comment`: Comentarios en tickets
- `helpdesk_attachment`: Archivos adjuntos
- `helpdesk_status_log`: Historial de estados
- `helpdesk_collaborator`: Colaboradores en tickets
- `helpdesk_inventory_categories`: Categoróas de equipos
- `helpdesk_inventory_items`: Equipos institucionales
- `helpdesk_inventory_groups`: Grupos de equipos (salones, labs)
- `helpdesk_inventory_history`: Historial de cambios
- `helpdesk_ticket_inventory_item`: Relación tickets-equipos

---

## Documentación de API

### Autenticación

#### POST `/api/core/v1/auth/login`
**Body**:
```json
{
  "username": "user123",
  "password": "password123"
}
```

**Response**:
```json
{
  "ok": true,
  "user": {
    "id": 1,
    "username": "user123",
    "full_name": "Usuario Ejemplo",
    "email": "user@example.com"
  },
  "apps": ["helpdesk", "agendatec"]
}
```

**Cookie**: `itcj_token` (JWT, HTTP-only)

---

#### GET `/api/core/v1/auth/me`
**Headers**: Cookie con `itcj_token`

**Response**:
```json
{
  "id": 1,
  "username": "user123",
  "full_name": "Usuario Ejemplo",
  "roles": ["staff", "tech_soporte"],
  "permissions": ["helpdesk.ticket.create", "helpdesk.ticket.view"]
}
```

---

### Help-Desk API

#### GET `/api/help-desk/v1/tickets`
**Query params**:
- `status`: Filtrar por estado (PENDING, ASSIGNED, etc.)
- `priority`: Filtrar por prioridad (BAJA, MEDIA, ALTA, URGENTE)
- `area`: Filtrar por área (DESARROLLO, SOPORTE)
- `assigned_to_me`: `true` para tickets asignados al usuario actual
- `created_by_me`: `true` para tickets creados por el usuario actual
- `page`: Número de página (default: 1)
- `per_page`: Resultados por página (default: 20)

**Response**:
```json
{
  "tickets": [
    {
      "id": 1,
      "ticket_number": "TK-2025-0001",
      "title": "Error en sistema",
      "status": "PENDING",
      "priority": "ALTA",
      "area": "DESARROLLO",
      "created_at": "2025-12-02T10:30:00",
      "requester": {
        "id": 2,
        "name": "Juan Pérez"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 45,
    "pages": 3
  }
}
```

---

#### POST `/api/help-desk/v1/tickets`
**Body**:
```json
{
  "title": "No puedo acceder al sistema",
  "description": "Al intentar iniciar sesión aparece error 500",
  "area": "DESARROLLO",
  "category_id": 3,
  "priority": "MEDIA",
  "location": "Edificio A, Oficina 201"
}
```

**Response**:
```json
{
  "ok": true,
  "ticket": {
    "id": 123,
    "ticket_number": "TK-2025-0123",
    "status": "PENDING",
    ...
  }
}
```

---

#### PATCH `/api/help-desk/v1/tickets/{id}/assign`
**Body**:
```json
{
  "assigned_to_user_id": 5,
  "assigned_to_team": "soporte"
}
```

---

#### POST `/api/help-desk/v1/tickets/{id}/comments`
**Body**:
```json
{
  "content": "He revisado el ticket y procederé con la solución",
  "is_internal": false
}
```

---

### AgendaTec API

Consultar [`itcj/apps/agendatec/README.md`](itcj/apps/agendatec/README.md) para documentación completa.

---

## Guóa de Desarrollo

### Convenciones de Código

#### Estructura de Archivos
- **Modelos**: Un modelo por archivo en `models/`
- **Rutas**: Agrupar por funcionalidad en `routes/api/` y `routes/pages/`
- **Servicios**: Lógica de negocio en `services/`
- **Utilidades**: Funciones helper en `utils/`

#### Nomenclatura
- **Clases**: PascalCase (`class UserService`)
- **Funciones**: snake_case (`def get_user_by_id()`)
- **Constantes**: UPPER_SNAKE_CASE (`MAX_FILE_SIZE = 3 * 1024 * 1024`)
- **Variables privadas**: Prefijo `_` (`_internal_function()`)

#### Estructura de un Modelo SQLAlchemy

```python
from itcj.core.extensions import db

class ExampleModel(db.Model):
    """
    Documentación del modelo.
    Explicar propósito y relaciones principales.
    """
    __tablename__ = 'app_example_model'

    # Identificación
    id = db.Column(db.Integer, primary_key=True)

    # Campos principales
    name = db.Column(db.String(100), nullable=False)

    # Claves foráneas
    user_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'))

    # Timestamps
    created_at = db.Column(db.DateTime, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"))

    # Relaciones
    user = db.relationship('User', backref='examples')

    # óndices
    __table_args__ = (
        db.Index('ix_example_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self):
        """Serialización para API"""
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat()
        }
```

---

### Estructura de una Ruta API

```python
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import login_required, permission_required

example_api_bp = Blueprint('example_api', __name__)

@example_api_bp.get('/')
@login_required
@permission_required('example.view')
def list_examples():
    """
    Lista todos los ejemplos.

    Query params:
        - page (int): Número de página
        - per_page (int): Resultados por página

    Returns:
        JSON con lista de ejemplos y paginación
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Lógica de negocio
    examples = ExampleModel.query.paginate(page=page, per_page=per_page)

    return jsonify({
        'examples': [e.to_dict() for e in examples.items],
        'pagination': {
            'page': examples.page,
            'pages': examples.pages,
            'total': examples.total
        }
    })

@example_api_bp.post('/')
@login_required
@permission_required('example.create')
def create_example():
    """Crea un nuevo ejemplo"""
    data = request.get_json()

    # Validación
    if not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    # Creación
    example = ExampleModel(
        name=data['name'],
        user_id=g.current_user['sub']
    )

    db.session.add(example)
    db.session.commit()

    return jsonify({'ok': True, 'example': example.to_dict()}), 201
```

---

### Agregar una Nueva Aplicación

#### 1. Crear estructura de directorios

```bash
mkdir -p itcj/apps/nueva_app/{models,routes/{api,pages},services,templates/nueva_app,static/{css,js}}
```

#### 2. Crear `__init__.py` de la app

```python
# itcj/apps/nueva_app/__init__.py
from flask import Blueprint

# Blueprints
nueva_app_api_bp = Blueprint('nueva_app_api', __name__)
nueva_app_pages_bp = Blueprint('nueva_app_pages', __name__,
                               template_folder='templates',
                               static_folder='static')

# Registrar sub-blueprints
from itcj.apps.nueva_app.routes.api import example_api_bp
nueva_app_api_bp.register_blueprint(example_api_bp, url_prefix='/examples')
```

#### 3. Registrar blueprints en la app principal

```python
# itcj/__init__.py - funciín register_blueprints()
from itcj.apps.nueva_app import nueva_app_api_bp, nueva_app_pages_bp

app.register_blueprint(nueva_app_api_bp, url_prefix="/api/nueva-app/v1")
app.register_blueprint(nueva_app_pages_bp, url_prefix="/nueva-app")
```

#### 4. Crear modelos, rutas y servicios

Seguir las convenciones establecidas en las apps existentes.

#### 5. Crear migración

```bash
flask db migrate -m "Add nueva_app models"
flask db upgrade
```

---

### Trabajar con Migraciones

#### Crear una nueva migración

```bash
# Detectar cambios automáticamente
flask db migrate -m "Descripción del cambio"

# Revisar el archivo generado en migrations/versions/
# Editar si es necesario

# Aplicar la migración
flask db upgrade
```

#### Revertir una migración

```bash
# Revertir última migración
flask db downgrade

# Revertir a una versión especófica
flask db downgrade <revision_id>
```

#### Mejores prácticas

1. **Siempre revisar** los archivos de migración generados automáticamente
2. **No modificar** migraciones ya aplicadas en producción
3. **Usar transacciones** para cambios complejos
4. **Documentar** cambios significativos en el mensaje de la migración
5. **Probar** las migraciones en desarrollo antes de aplicar en producción

---

### Sistema de Permisos Personalizado

#### Definir nuevos permisos

```python
# En un comando Flask o script de seed
from itcj.core.models import Permission, Role, db

# Crear permiso
perm = Permission(
    code='nueva_app.resource.action',
    name='Descripción del permiso',
    app='nueva_app',
    description='Descripción detallada'
)
db.session.add(perm)

# Asignar a rol
role = Role.query.filter_by(name='admin').first()
role.permissions.append(perm)

db.session.commit()
```

#### Usar permisos en rutas

```python
from itcj.core.utils.decorators import permission_required

@bp.get('/protected')
@permission_required('nueva_app.resource.view')
def protected_route():
    return jsonify({'message': 'Acceso permitido'})
```

---

## Testing

### Ejecutar Tests

```bash
# Todos los tests
pytest

# Tests específicos
pytest tests/test_helpdesk.py

# Con cobertura
pytest --cov=itcj tests/
```

### Estructura de Tests

```
tests/
--- conftest.py              # Fixtures compartidos
--- test_core/               # Tests del core
-------test_auth.py
-------test_permissions.py
-----test_agendatec/          # Tests de AgendaTec
-----test_helpdesk/           # Tests de Help-Desk
--------test_tickets.py
--------test_inventory.py
--------test_assignments.py
```

---

## Contribución

### Flujo de Trabajo

1. **Fork** del repositorio
2. **Crear rama** para la funcionalidad: `git checkout -b feature/nueva-funcionalidad`
3. **Commits descriptivos**: `git commit -m "feat(helpdesk): add ticket filtering"`
4. **Push**: `git push origin feature/nueva-funcionalidad
5. **Pull Request** con descripción detallada

### Convenciones de Commits

Seguir [Conventional Commits](https://www.conventionalcommits.org/):

- `feat(scope)`: Nueva funcionalidad
- `fix(scope)`: Corrección de bug
- `docs(scope)`: Cambios en documentación
- `style(scope)`: Formato de código (sin cambios funcionales)
- `refactor(scope)`: Refactorización de código
- `test(scope)`: Agregar o modificar tests
- `chore(scope)`: Tareas de mantenimiento

**Ejemplos**:
```bash
feat(helpdesk): add ticket priority filtering
fix(auth): correct JWT expiration validation
docs(readme): update installation instructions
```

---

## Soporte y Contacto

### Reportar Problemas

- **Issues**: Crear un issue en el repositorio con descripción detallada
- **Template**: Incluir pasos para reproducir, comportamiento esperado, y actual

### Recursos Adicionales

- **Documentación de Apps**: Ver README específico de cada app
  - [`itcj/apps/agendatec/README.md`](itcj/apps/agendatec/README.md)
  - [`itcj/apps/helpdesk/README.md`](itcj/apps/helpdesk/README.md)
- **Base de Datos**: Ver [`database/VERIFICATION_GUIDE.md`](database/VERIFICATION_GUIDE.md)

---

## Licencia

Este proyecto es de uso interno del Instituto Tecnológico de Ciudad Juárez.

---

## Changelog

### Versión Actual (Diciembre 2025)

#### Apps Disponibles
✅ **AgendaTec**: Sistema de altas/bajas funcional
✅ **Help-Desk**: Sistema de tickets con inventario

#### Características Implementadas
✅ Autenticación JWT con refresh automático
✅ Sistema de roles y permisos por aplicación
✅ WebSockets para tiempo real (AgendaTec, Help-Desk)
✅ Sistema de notificaciones in-app
✅ Gestión de inventario institucional
✅ Métricas de SLA y calidad
✅ Sistema de calificaciones y encuestas
✅ Responsive design (Bootstrap 5)
✅ Docker Compose para despliegue

#### En Desarrollo
⏳ Dashboard de métricas general
⏳ Sistema de reportes avanzados
⏳ Notificaciones por email
⏳ API REST documentada (OpenAPI/Swagger)

---

**Desarrollado con ❤️ para el Instituto Tecnológico de Ciudad Juárez**

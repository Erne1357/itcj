# Plan de Migración: Flask → FastAPI + Docker Swarm

## Resumen Ejecutivo

Este plan detalla la migración del backend de **Flask 3.1.1** a **FastAPI** con workers asíncronos, y la transición de **Docker Compose (Blue-Green)** a **Docker Swarm** con rolling updates.

### Prioridades del Plan

```
┌─────────────────────────────────────────────────────────────────┐
│  CRÍTICO (Fases 1-3)          │  RECOMENDADO (Fases 4-5)       │
│  ─────────────────────        │  ───────────────────           │
│  • FastAPI + async            │  • Docker Swarm                │
│  • Múltiples workers (4+)     │  • Rolling updates             │
│  • Health checks              │  • GHCR                        │
│  • Socket.IO ASGI             │  • Docker Secrets              │
├─────────────────────────────────────────────────────────────────┤
│  FUTURO (cuando lo necesites)                                   │
│  ────────────────────────────                                   │
│  • Multi-node Swarm (cuando 1 servidor no baste)               │
│  • Microservicios (cuando tengas 5+ apps o equipos separados)  │
│  • Kubernetes (cuando Swarm se quede corto)                    │
└─────────────────────────────────────────────────────────────────┘
```

### ¿Por qué estos cambios?

| Cambio | Problema que resuelve |
|--------|----------------------|
| **FastAPI** | Flask con Eventlet es un hack. Async real = mejor rendimiento |
| **Múltiples workers** | Actualmente 1 worker. Si se bloquea, todo muere |
| **Socket.IO ASGI** | Mantiene tu código frontend, pero con async real |
| **Swarm** | Rolling updates = zero-downtime. Blue-green es más complejo |

### ¿Por qué NO microservicios?

Tu arquitectura actual (monolito modular) es **correcta** para tu escala:
- 1-3 desarrolladores
- 3 apps que comparten auth y base de datos
- Tráfico predecible (horarios académicos)

Microservicios agregan complejidad operacional masiva sin beneficio real para tu caso.

### Decisiones Técnicas

| Aspecto | Decisión | Razón |
|---------|----------|-------|
| Frontend | Mantener Jinja2 (SSR) | Funciona, no hay razón para cambiar |
| WebSockets | Socket.IO ASGI | Ya implementado en frontend, rooms built-in |
| Swarm | Single-node | Suficiente para miles de usuarios |
| Secretos | Docker Secrets | Más seguro que .env expuesto |
| Migración | Gradual | Flask + FastAPI coexisten durante transición |

---

# PARTE 1: CRÍTICO - Migración a FastAPI

> **Estas fases son las que realmente importan. El beneficio principal está aquí.**

---

## Fase 1: FastAPI Core + Configuración Base
**Duración estimada: 3-5 días**

### 1.1 Nuevas Dependencias

Agregar a `requirements.txt`:
```txt
# FastAPI Stack
fastapi==0.115.0
uvicorn[standard]==0.32.0
python-multipart==0.0.9

# Async Database
asyncpg==0.30.0
sqlalchemy[asyncio]==2.0.43

# Socket.IO ASGI
python-socketio[asyncio]==5.13.0

# Testing
httpx==0.28.0
pytest-asyncio==0.24.0
```

### 1.2 Nueva Estructura de Directorios

```
itcj/
├── __init__.py              # Flask app (mantener durante migración)
├── main.py                  # FastAPI app (NUEVO)
├── asgi.py                  # Punto de entrada ASGI (NUEVO)
├── config.py                # Config compartida
├── core/
│   ├── api/                 # FastAPI routers (NUEVO)
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── users.py
│   │   └── deps.py          # Dependencias (auth, db session)
│   ├── schemas/             # Pydantic schemas (NUEVO)
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   └── user.py
│   ├── routes/              # Flask blueprints (legacy)
│   ├── models/              # SQLAlchemy models (compartido)
│   ├── services/            # Business logic (compartido, adaptar a async)
│   └── sockets/             # Socket.IO (adaptar a ASGI)
└── apps/
    ├── agendatec/
    │   ├── api/             # FastAPI routers (NUEVO)
    │   ├── schemas/         # Pydantic schemas (NUEVO)
    │   ├── routes/          # Flask blueprints (legacy)
    │   └── ...
    └── ...
```

### 1.3 Aplicación FastAPI Base

**Archivo: `itcj/main.py`**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from itcj.config import Config
from itcj.core.extensions import async_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    await async_engine.dispose()

app = FastAPI(
    title="ITCJ API",
    version="2.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(SessionMiddleware, secret_key=Config.SECRET_KEY)

# Static files
app.mount("/static", StaticFiles(directory="itcj/core/static"), name="static")

# Templates
templates = Jinja2Templates(directory="itcj/core/templates")

# Health check (CRÍTICO para rolling updates)
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Importar routers después de crear app
from itcj.core.api import auth_router, users_router
app.include_router(auth_router, prefix="/api/core/v1/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/core/v1/users", tags=["users"])
```

### 1.4 SQLAlchemy Async

**Modificar: `itcj/core/extensions.py`**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from itcj.config import Config

# Convertir URL sync a async
DATABASE_URL_ASYNC = Config.SQLALCHEMY_DATABASE_URI.replace(
    "postgresql+psycopg2://",
    "postgresql+asyncpg://"
)

# Engine async
async_engine = create_async_engine(
    DATABASE_URL_ASYNC,
    echo=False,
    pool_size=5,
    max_overflow=10
)

# Session factory async
async_session = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base para modelos (compartida)
class Base(DeclarativeBase):
    pass

# ═══════════════════════════════════════════════════════
# MANTENER DURANTE MIGRACIÓN - Flask sync
# ═══════════════════════════════════════════════════════
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()
```

### 1.5 Dependencias FastAPI

**Archivo: `itcj/core/api/deps.py`**
```python
from typing import AsyncGenerator, Annotated
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from itcj.core.extensions import async_session
from itcj.core.utils.jwt_tools import decode_jwt
from itcj.core.models import User

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    token = request.cookies.get("itcj_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado"
        )

    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )

    user = await db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo"
        )

    return user

async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User | None:
    """Para rutas donde auth es opcional"""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None

# Type aliases para usar en routers
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
```

### 1.6 Schemas Pydantic Core

**Archivo: `itcj/core/schemas/auth.py`**
```python
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    control_number: str | None = None
    username: str | None = None
    nip: str = Field(..., min_length=1)

class LoginResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool = False

class TokenPayload(BaseModel):
    sub: int
    role: str
    cn: str
    name: str
```

**Archivo: `itcj/core/schemas/user.py`**
```python
from pydantic import BaseModel, EmailStr, ConfigDict
from datetime import datetime

class UserBase(BaseModel):
    username: str
    control_number: str
    first_name: str
    last_name: str
    email: EmailStr | None = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None

class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
```

### 1.7 Router de Auth (Ejemplo)

**Archivo: `itcj/core/api/auth.py`**
```python
from fastapi import APIRouter, Response, HTTPException, status
from sqlalchemy import select

from itcj.core.api.deps import DbSession, CurrentUser
from itcj.core.schemas.auth import LoginRequest, LoginResponse
from itcj.core.models import User
from itcj.core.utils.jwt_tools import encode_jwt
from itcj.core.utils.security import verify_nip
from itcj.config import Config

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest, response: Response, db: DbSession):
    # Buscar usuario
    if data.control_number:
        stmt = select(User).where(User.control_number == data.control_number)
    elif data.username:
        stmt = select(User).where(User.username == data.username)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere control_number o username"
        )

    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_nip(data.nip, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado"
        )

    # Generar JWT
    token = encode_jwt({
        "sub": user.id,
        "role": user.role.name if user.role else "user",
        "cn": user.control_number,
        "name": f"{user.first_name} {user.last_name}"
    })

    # Set cookie
    response.set_cookie(
        key="itcj_token",
        value=token,
        httponly=True,
        secure=Config.COOKIE_SECURE,
        samesite=Config.COOKIE_SAMESITE,
        max_age=Config.JWT_EXPIRES_HOURS * 3600
    )

    return LoginResponse(
        id=user.id,
        username=user.username,
        full_name=f"{user.first_name} {user.last_name}",
        role=user.role.name if user.role else "user",
        must_change_password=user.must_change_password
    )

@router.get("/me", response_model=LoginResponse)
async def get_me(current_user: CurrentUser):
    return LoginResponse(
        id=current_user.id,
        username=current_user.username,
        full_name=f"{current_user.first_name} {current_user.last_name}",
        role=current_user.role.name if current_user.role else "user",
        must_change_password=current_user.must_change_password
    )

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("itcj_token")
    return {"message": "Sesión cerrada"}
```

### 1.8 Coexistencia Flask + FastAPI

**Archivo: `itcj/asgi.py`**
```python
"""
Punto de entrada ASGI que permite Flask y FastAPI coexistir.
FastAPI maneja /api/v2/*, Flask maneja todo lo demás.
"""
from starlette.applications import Starlette
from starlette.routing import Mount
from asgiref.wsgi import WsgiToAsgi

# FastAPI app (nuevas rutas)
from itcj.main import app as fastapi_app

# Flask app (rutas legacy)
from itcj import create_app
flask_app = create_app()
flask_asgi = WsgiToAsgi(flask_app)

# App combinada
app = Starlette(
    routes=[
        # Nuevos endpoints van a FastAPI
        Mount("/api/v2", app=fastapi_app),
        Mount("/health", app=fastapi_app),

        # Todo lo demás va a Flask (legacy)
        Mount("/", app=flask_asgi),
    ]
)
```

### 1.9 Actualizar Gunicorn

**Modificar: `docker/backend/gunicorn.conf.py`**
```python
# De Eventlet a Uvicorn workers
bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
workers = 4  # ¡Ahora podemos usar múltiples workers!
worker_connections = 1000
timeout = 300
keepalive = 75
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
```

**Modificar: `docker/backend/entrypoint.sh`**
```bash
#!/bin/bash
set -e

echo "=== ITCJ Backend Startup ==="

# Esperar a que PostgreSQL esté listo
echo "Esperando a PostgreSQL..."
while ! pg_isready -h postgres -p 5432 -U postgres -q; do
    sleep 1
done
echo "PostgreSQL listo"

# Esperar a que Redis esté listo
echo "Esperando a Redis..."
while ! redis-cli -h redis ping > /dev/null 2>&1; do
    sleep 1
done
echo "Redis listo"

# Ejecutar migraciones
echo "Ejecutando migraciones..."
python -m alembic upgrade head

# Iniciar servidor
echo "Iniciando Gunicorn con Uvicorn workers..."
exec gunicorn asgi:app -c /app/gunicorn.conf.py
```

### Entregables Fase 1

- [ ] Dependencias instaladas y probadas localmente
- [ ] Estructura de directorios creada
- [ ] `main.py` con FastAPI funcionando
- [ ] SQLAlchemy async configurado
- [ ] Dependencias (`deps.py`) creadas
- [ ] Schemas Pydantic core creados
- [ ] Router de auth migrado y probado
- [ ] `asgi.py` combinando Flask + FastAPI
- [ ] Gunicorn con Uvicorn workers
- [ ] Health check funcionando

---

## Fase 2: Migración de Aplicaciones
**Duración estimada: 5-7 días por aplicación**

### 2.1 Orden de Migración

1. **Core** (auth, users, notifications) - Fase 1
2. **AgendaTec** - App más usada
3. **HelpDesk** - Complejidad media
4. **VisteTec** - App más nueva

### 2.2 Proceso por Aplicación

Para cada app, repetir este proceso:

#### Paso 1: Crear schemas Pydantic

```
itcj/apps/<app>/schemas/
├── __init__.py
├── request.py       # Solicitudes
├── appointment.py   # Citas
├── common.py        # Schemas compartidos
└── ...
```

Ejemplo para AgendaTec:
```python
# itcj/apps/agendatec/schemas/request.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from enum import Enum

class RequestType(str, Enum):
    DROP = "DROP"
    APPOINTMENT = "APPOINTMENT"

class RequestStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED_SUCCESS = "RESOLVED_SUCCESS"
    RESOLVED_NOT_COMPLETED = "RESOLVED_NOT_COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELED = "CANCELED"

class RequestCreate(BaseModel):
    program_id: int
    type: RequestType
    description: str | None = None

class RequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: RequestType
    status: RequestStatus
    description: str | None
    created_at: datetime
    student_name: str | None = None
```

#### Paso 2: Adaptar services a async

```python
# Antes (sync - Flask)
def get_student_requests(db, student_id: int):
    return db.query(Request).filter_by(student_id=student_id).all()

# Después (async - FastAPI)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_student_requests(db: AsyncSession, student_id: int):
    stmt = (
        select(Request)
        .where(Request.student_id == student_id)
        .options(selectinload(Request.appointment))
        .order_by(Request.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()
```

#### Paso 3: Crear routers FastAPI

```python
# itcj/apps/agendatec/api/requests.py
from fastapi import APIRouter, HTTPException, status
from itcj.core.api.deps import DbSession, CurrentUser
from itcj.apps.agendatec.schemas.request import RequestCreate, RequestResponse
from itcj.apps.agendatec.services import request_service

router = APIRouter()

@router.post("/", response_model=RequestResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    data: RequestCreate,
    db: DbSession,
    current_user: CurrentUser
):
    # Verificar que es estudiante
    if current_user.role.name != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo estudiantes pueden crear solicitudes"
        )

    request = await request_service.create_request(db, current_user.id, data)
    return request

@router.get("/", response_model=list[RequestResponse])
async def list_my_requests(db: DbSession, current_user: CurrentUser):
    requests = await request_service.get_student_requests(db, current_user.id)
    return requests

@router.get("/{request_id}", response_model=RequestResponse)
async def get_request(request_id: int, db: DbSession, current_user: CurrentUser):
    request = await request_service.get_request(db, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # Verificar acceso
    if request.student_id != current_user.id and current_user.role.name not in ["admin", "coordinator"]:
        raise HTTPException(status_code=403, detail="Sin acceso a esta solicitud")

    return request
```

#### Paso 4: Registrar en main.py

```python
# En itcj/main.py
from itcj.apps.agendatec.api import router as agendatec_router

app.include_router(
    agendatec_router,
    prefix="/api/agendatec/v1",
    tags=["agendatec"]
)
```

### 2.3 Migración de Templates Jinja2

FastAPI soporta Jinja2 nativamente:

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="itcj/apps/agendatec/templates")

@router.get("/home", response_class=HTMLResponse)
async def student_home(request: Request, current_user: CurrentUser):
    return templates.TemplateResponse(
        request=request,
        name="student/home.html",
        context={"user": current_user}
    )
```

### 2.4 Checklist por Aplicación

#### AgendaTec
- [ ] Schemas: Request, Appointment, TimeSlot, Program, Period, Coordinator
- [ ] Services adaptados a async
- [ ] API: `/api/agendatec/v1/requests`, `/slots`, `/appointments`, `/availability`
- [ ] API Admin: `/api/agendatec/v1/admin/*`
- [ ] Pages migradas (student, coord, social, admin)
- [ ] Tests básicos

#### HelpDesk
- [ ] Schemas: Ticket, Category, Comment, Attachment, Inventory
- [ ] Services adaptados a async
- [ ] API: `/api/help-desk/v1/tickets`, `/categories`, `/inventory`
- [ ] Pages migradas
- [ ] Tests básicos

#### VisteTec
- [ ] Schemas: Garment, Donation, Campaign, Appointment, Location
- [ ] Services adaptados a async
- [ ] API: `/api/vistetec/v1/garments`, `/donations`, `/campaigns`
- [ ] Pages migradas
- [ ] Tests básicos

### Entregables Fase 2

- [ ] AgendaTec 100% migrado a FastAPI
- [ ] HelpDesk 100% migrado a FastAPI
- [ ] VisteTec 100% migrado a FastAPI
- [ ] Todas las rutas Flask legacy pueden eliminarse
- [ ] Tests pasando para cada app

---

## Fase 3: WebSockets con ASGI
**Duración estimada: 2-3 días**

### 3.1 Socket.IO ASGI

**Archivo: `itcj/core/sockets/manager.py`**
```python
import socketio
from itcj.config import Config

# Servidor Socket.IO async
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    client_manager=socketio.AsyncRedisManager(Config.REDIS_URL),
    logger=True,
    engineio_logger=True
)

# ASGI app
socket_app = socketio.ASGIApp(
    sio,
    socketio_path="/socket.io"
)
```

### 3.2 Eventos Socket.IO

**Archivo: `itcj/core/sockets/events.py`**
```python
from itcj.core.sockets.manager import sio
from itcj.core.utils.jwt_tools import decode_jwt
import re

def extract_token_from_cookies(cookie_header: str) -> str | None:
    """Extraer itcj_token de la cabecera de cookies"""
    if not cookie_header:
        return None
    match = re.search(r'itcj_token=([^;]+)', cookie_header)
    return match.group(1) if match else None

@sio.event
async def connect(sid, environ, auth):
    """Conexión de cliente"""
    cookies = environ.get("HTTP_COOKIE", "")
    token = extract_token_from_cookies(cookies)

    if not token:
        raise socketio.exceptions.ConnectionRefusedError("No autenticado")

    payload = decode_jwt(token)
    if not payload:
        raise socketio.exceptions.ConnectionRefusedError("Token inválido")

    # Guardar sesión
    await sio.save_session(sid, {
        "user_id": payload["sub"],
        "role": payload["role"],
        "name": payload["name"]
    })

    # Unir a rooms
    await sio.enter_room(sid, f"user_{payload['sub']}")

    if payload["role"] in ["admin", "coordinator"]:
        await sio.enter_room(sid, "staff")

    print(f"[Socket.IO] Usuario {payload['name']} conectado (sid: {sid})")

@sio.event
async def disconnect(sid):
    """Desconexión de cliente"""
    session = await sio.get_session(sid)
    if session:
        print(f"[Socket.IO] Usuario {session.get('name')} desconectado")

# Función helper para emitir desde cualquier parte de la app
async def notify_user(user_id: int, event: str, data: dict):
    """Enviar notificación a un usuario específico"""
    await sio.emit(event, data, room=f"user_{user_id}")

async def notify_staff(event: str, data: dict):
    """Enviar notificación a todo el staff"""
    await sio.emit(event, data, room="staff")
```

### 3.3 Integrar con FastAPI

**Modificar: `itcj/main.py`**
```python
# Al final del archivo
from itcj.core.sockets.manager import socket_app

# Montar Socket.IO
app.mount("/ws", socket_app)
```

### 3.4 Usar desde Services

```python
# En cualquier service
from itcj.core.sockets.events import notify_user, notify_staff

async def create_request(db: AsyncSession, student_id: int, data: RequestCreate):
    # ... crear request ...

    # Notificar al estudiante
    await notify_user(student_id, "request_created", {
        "request_id": request.id,
        "message": "Tu solicitud ha sido creada"
    })

    # Notificar al staff
    await notify_staff("new_request", {
        "request_id": request.id,
        "student_name": student.full_name
    })

    return request
```

### Entregables Fase 3

- [ ] Socket.IO ASGI configurado
- [ ] Eventos migrados a async
- [ ] Redis manager funcionando
- [ ] Helper functions para notificaciones
- [ ] Frontend conectando correctamente
- [ ] Tests de WebSocket

---

# PARTE 2: RECOMENDADO - Infraestructura

> **Estas fases mejoran la operación pero no son críticas. Puedes hacerlas después.**

---

## Fase 4: Docker Swarm
**Duración estimada: 1-2 días**

### 4.1 Inicializar Swarm en Servidor

```bash
# SSH al servidor
ssh user@servidor

# Inicializar Swarm (single-node)
docker swarm init

# Crear red overlay
docker network create --driver overlay --attachable itcj-network

# Crear volúmenes
docker volume create itcj-pgdata
docker volume create itcj-redis-data
docker volume create itcj-instance
```

### 4.2 Docker Secrets

```bash
# Crear secretos desde .env actual
cat .env | grep SECRET_KEY | cut -d'=' -f2 | docker secret create itcj_secret_key -
cat .env | grep DATABASE_URL | cut -d'=' -f2 | docker secret create itcj_database_url -
cat .env | grep REDIS_URL | cut -d'=' -f2 | docker secret create itcj_redis_url -

# Para PostgreSQL
echo "postgres" | docker secret create postgres_user -
echo "tu_password_seguro" | docker secret create postgres_password -
```

### 4.3 Stack File

**Archivo: `docker/swarm/stack.yml`**
```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    networks:
      - itcj-network
    volumes:
      - itcj-redis-data:/data
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 5s
      resources:
        limits:
          memory: 256M

  postgres:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: itcj
      POSTGRES_USER_FILE: /run/secrets/postgres_user
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_user
      - postgres_password
    networks:
      - itcj-network
    volumes:
      - itcj-pgdata:/var/lib/postgresql/data
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager

  backend:
    image: itcj-backend:latest
    secrets:
      - itcj_secret_key
      - itcj_database_url
      - itcj_redis_url
    environment:
      - TZ=America/Ciudad_Juarez
      - APP_TZ=America/Ciudad_Juarez
    networks:
      - itcj-network
    volumes:
      - itcj-instance:/app/instance
    deploy:
      replicas: 2
      update_config:
        parallelism: 1
        delay: 10s
        failure_action: rollback
        order: start-first
      rollback_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
      resources:
        limits:
          memory: 512M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  nginx:
    image: itcj-nginx:latest
    ports:
      - "80:80"
      - "443:443"
    networks:
      - itcj-network
    volumes:
      - /etc/letsencrypt:/etc/letsencrypt:ro
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

networks:
  itcj-network:
    external: true

volumes:
  itcj-pgdata:
    external: true
  itcj-redis-data:
    external: true
  itcj-instance:
    external: true

secrets:
  itcj_secret_key:
    external: true
  itcj_database_url:
    external: true
  itcj_redis_url:
    external: true
  postgres_user:
    external: true
  postgres_password:
    external: true
```

### 4.4 Leer Secrets en la App

**Modificar: `itcj/config.py`**
```python
import os

def read_secret(name: str, default: str = "") -> str:
    """Leer un Docker secret o variable de entorno"""
    # Primero intentar leer del archivo de secret
    secret_path = f"/run/secrets/{name}"
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as f:
            return f.read().strip()

    # Fallback a variable de entorno
    env_name = name.upper()
    return os.getenv(env_name, default)

class Config:
    SECRET_KEY = read_secret("itcj_secret_key", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = read_secret("itcj_database_url", "sqlite:///dev.db")
    REDIS_URL = read_secret("itcj_redis_url", "redis://localhost:6379/0")
    # ... resto de config
```

### 4.5 Deploy y Comandos Útiles

```bash
# Deploy inicial
docker stack deploy -c docker/swarm/stack.yml itcj

# Ver servicios
docker service ls

# Ver logs de backend
docker service logs itcj_backend -f

# Escalar backend
docker service scale itcj_backend=3

# Actualizar imagen (rolling update automático)
docker service update --image itcj-backend:v2 itcj_backend

# Rollback
docker service rollback itcj_backend

# Ver estado de un servicio
docker service ps itcj_backend
```

### Entregables Fase 4

- [ ] Swarm inicializado
- [ ] Secrets creados
- [ ] Stack funcionando
- [ ] Rolling updates probados
- [ ] Rollback probado

---

## Fase 5: CI/CD con GitHub Actions
**Duración estimada: 1-2 días**

### 5.1 Build y Push a GHCR (Opcional)

**Archivo: `.github/workflows/build.yml`**
```yaml
name: Build and Push

on:
  push:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}-backend

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/backend/Dockerfile
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### 5.2 Deploy Automático

**Archivo: `.github/workflows/deploy.yml`**
```yaml
name: Deploy to Production

on:
  workflow_run:
    workflows: ["Build and Push"]
    types: [completed]
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'success' || github.event_name == 'workflow_dispatch' }}

    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          port: ${{ secrets.SERVER_PORT }}
          command_timeout: 10m
          script: |
            cd /home/cuaderno/ITCJ

            # Pull código
            git pull origin main

            # Build local (alternativa a GHCR)
            docker build -t itcj-backend:latest -f docker/backend/Dockerfile .

            # Update service (rolling update)
            docker service update --image itcj-backend:latest itcj_backend

            # Esperar y verificar
            sleep 30
            docker service ps itcj_backend --no-trunc
```

### 5.3 Alternativa: Build en Servidor (Sin GHCR)

Si prefieres no usar GHCR, el deploy puede hacer build directamente:

```yaml
script: |
  cd /home/cuaderno/ITCJ
  git pull origin main

  # Build en servidor
  docker build -t itcj-backend:$(git rev-parse --short HEAD) -f docker/backend/Dockerfile .
  docker tag itcj-backend:$(git rev-parse --short HEAD) itcj-backend:latest

  # Update
  docker service update --image itcj-backend:latest itcj_backend
```

### Entregables Fase 5

- [ ] Workflow de build configurado
- [ ] Workflow de deploy configurado
- [ ] Deploy automático funcionando
- [ ] Rolling updates sin downtime

---

# PARTE 3: FUTURO

> **No hagas esto ahora. Solo cuando realmente lo necesites.**

---

## Cuándo Considerar Multi-Node Swarm

**Señales de que lo necesitas:**
- Un servidor no puede manejar la carga
- Necesitas alta disponibilidad (si el servidor cae, todo cae)
- Tienes múltiples servidores disponibles

**Cómo hacerlo:**
```bash
# En el manager (servidor actual)
docker swarm join-token worker

# En los workers (nuevos servidores)
docker swarm join --token <token> <manager-ip>:2377

# En el manager, distribuir servicios
docker service update --replicas 4 itcj_backend
```

---

## Cuándo Considerar Microservicios

**Señales de que lo necesitas:**
- 5+ equipos de desarrollo trabajando en paralelo
- Diferentes partes necesitan escalar independientemente
- Diferentes tecnologías por servicio
- Deploys deben ser completamente independientes

**Por qué NO ahora:**
- Complejidad operacional masiva
- Necesitas: API Gateway, Service Mesh, Distributed Tracing
- Tu monolito modular es perfectamente válido para tu escala

---

## Cuándo Considerar Kubernetes

**Señales de que lo necesitas:**
- Docker Swarm se queda corto
- Necesitas auto-scaling avanzado
- Multi-cloud o hybrid cloud
- Tienes equipo de DevOps dedicado

**Por qué NO ahora:**
- Curva de aprendizaje enorme
- Overhead operacional significativo
- Swarm es suficiente para single-node o pequeños clusters

---

# Cronograma Resumido

| Fase | Duración | Prioridad |
|------|----------|-----------|
| **Fase 1:** FastAPI Core | 3-5 días | CRÍTICO |
| **Fase 2:** Apps (AgendaTec, HelpDesk, VisteTec) | 15-21 días | CRÍTICO |
| **Fase 3:** WebSockets ASGI | 2-3 días | CRÍTICO |
| **Fase 4:** Docker Swarm | 1-2 días | Recomendado |
| **Fase 5:** CI/CD | 1-2 días | Recomendado |

**Total crítico: ~3-4 semanas**
**Total con infraestructura: ~4-5 semanas**

---

# Resumen de Archivos

### Crear
```
itcj/main.py
itcj/asgi.py
itcj/core/api/__init__.py
itcj/core/api/deps.py
itcj/core/api/auth.py
itcj/core/api/users.py
itcj/core/schemas/__init__.py
itcj/core/schemas/auth.py
itcj/core/schemas/user.py
itcj/core/sockets/manager.py
itcj/core/sockets/events.py
itcj/apps/*/api/
itcj/apps/*/schemas/
docker/swarm/stack.yml
.github/workflows/build.yml
.github/workflows/deploy.yml
```

### Modificar
```
requirements.txt
itcj/config.py
itcj/core/extensions.py
docker/backend/Dockerfile
docker/backend/gunicorn.conf.py
docker/backend/entrypoint.sh
```

### Eliminar (después de migración completa)
```
itcj/__init__.py (Flask factory)
wsgi.py
itcj/core/routes/*
itcj/apps/*/routes/*
docker/compose/*.yml
```

---

# Tips Finales

1. **Migra gradualmente** - No intentes hacer todo de una vez
2. **Prueba cada paso** - Antes de pasar al siguiente
3. **Mantén Flask funcionando** - Hasta que todo esté migrado
4. **Backups antes de deploy** - Siempre
5. **Health checks son críticos** - Para rolling updates

¿Preguntas? Podemos ajustar cualquier parte del plan.

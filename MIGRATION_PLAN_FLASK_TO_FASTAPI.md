# Plan de Migración: Flask → FastAPI

> **Fecha**: 2026-02-24
> **Proyecto**: ITCJ Platform
> **Estrategia**: Migración gradual con coexistencia Flask + FastAPI

---

## Tabla de Contenidos

1. [Visión General](#1-visión-general)
2. [Arquitectura de Coexistencia](#2-arquitectura-de-coexistencia)
3. [Estructura del Proyecto](#3-estructura-del-proyecto)
4. [Fase 0: Infraestructura Base](#4-fase-0-infraestructura-base)
5. [Fase 1: Core Compartido](#5-fase-1-core-compartido)
6. [Fase 2: APIs v2 (FastAPI)](#6-fase-2-apis-v2-fastapi)
7. [Fase 3: Socket.IO ASGI](#7-fase-3-socketio-asgi)
8. [Fase 4: Templates/Pages](#8-fase-4-templatespages)
9. [Fase 5: Eliminar Flask](#9-fase-5-eliminar-flask)
10. [Docker & Nginx](#10-docker--nginx)
11. [Checklist por App](#11-checklist-por-app)
12. [Dependencias Nuevas](#12-dependencias-nuevas)
13. [Equivalencias Flask → FastAPI](#13-equivalencias-flask--fastapi)
14. [Riesgos y Mitigación](#14-riesgos-y-mitigación)

---

## 1. Visión General

### Qué cambia
| Componente | Flask (actual) | FastAPI (nuevo) |
|---|---|---|
| Framework | Flask 3.1.1 | FastAPI (latest) |
| Server | Gunicorn + Eventlet (WSGI) | Uvicorn (ASGI) |
| ORM | Flask-SQLAlchemy | SQLAlchemy 2.0 directo (sin wrapper Flask) |
| Migraciones | Flask-Migrate (Alembic) | Alembic directo |
| Socket.IO | Flask-SocketIO (eventlet) | python-socketio (ASGI nativo) |
| Templates | Jinja2 (vía Flask) | Jinja2 (vía Starlette/FastAPI) |
| Auth | JWT en cookies (PyJWT) | Mismo JWT, mismas cookies |
| Validación | Manual / WTForms | Pydantic v2 (ya instalado) |
| API docs | No tiene | Swagger UI + ReDoc automáticos |

### Qué NO cambia
- **Base de datos**: Misma PostgreSQL, mismos modelos SQLAlchemy
- **Redis**: Mismo Redis para Socket.IO y cache
- **Nginx**: Sigue sirviendo estáticos y haciendo proxy
- **Static files**: Sin cambios (nginx los sirve directo)
- **Estructura de apps**: Misma separación por módulos (core, agendatec, helpdesk, vistetec)
- **JWT**: Misma lógica de tokens, mismas cookies
- **Blue-green deploy**: Se mantiene el patrón

### Principio de coexistencia
```
                    ┌─────────────┐
                    │    Nginx    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
    /api/*/v1/*     /api/*/v2/*    /static/*
    /itcj/*         (nuevo)        (nginx directo)
    /agendatec/*
    /help-desk/*
    /vistetec/*
              │            │
              ▼            ▼
       ┌──────────┐ ┌──────────┐
       │  Flask   │ │ FastAPI  │
       │  :8000   │ │  :8001   │
       └──────────┘ └──────────┘
              │            │
              └─────┬──────┘
                    ▼
            ┌──────────────┐
            │  PostgreSQL  │
            │  Redis       │
            └──────────────┘
```

**Regla de oro**: Flask sigue manejando todo lo que ya funciona. FastAPI solo maneja rutas nuevas (v2). Gradualmente se migran las existentes.

---

## 2. Arquitectura de Coexistencia

### Dos servidores, un solo sistema

Flask y FastAPI corren como **servicios separados** en Docker:

- **Flask** (`backend-flask`): Puerto 8000 - Maneja v1 APIs + todas las pages actuales
- **FastAPI** (`backend-fastapi`): Puerto 8001 - Maneja v2 APIs + pages migradas

Ambos comparten:
- Misma base de datos PostgreSQL
- Mismo Redis
- Mismos modelos SQLAlchemy (importados desde `itcj/`)
- Misma lógica JWT (librería compartida)

### Routing en Nginx
```nginx
# v2 APIs → FastAPI
location /api/core/v2/     { proxy_pass http://backend-fastapi:8001; }
location /api/agendatec/v2/ { proxy_pass http://backend-fastapi:8001; }
location /api/help-desk/v2/ { proxy_pass http://backend-fastapi:8001; }
location /api/vistetec/v2/  { proxy_pass http://backend-fastapi:8001; }

# Socket.IO v2 → FastAPI (cuando se migre)
# location /socket.io/      { proxy_pass http://backend-fastapi:8001; }

# Todo lo demás → Flask (v1 APIs + pages)
location /api/  { proxy_pass http://backend-flask:8000; }
location /      { proxy_pass http://backend-flask:8000; }
```

---

## 3. Estructura del Proyecto

### Directorio `itcj2/` (nuevo, paralelo a `itcj/`)

```
ITCJ/
├── itcj/                          # Flask (existente, sin cambios)
│   ├── __init__.py                # create_app() Flask
│   ├── config.py
│   ├── core/
│   │   ├── models/                # ← Compartido (FastAPI importa de aquí)
│   │   ├── services/              # ← Compartido
│   │   ├── utils/                 # ← Compartido (jwt_tools, etc.)
│   │   ├── extensions.py          # Flask-SQLAlchemy (solo Flask)
│   │   ├── sockets/               # Flask-SocketIO (hasta que se migre)
│   │   ├── routes/
│   │   └── templates/
│   └── apps/
│       ├── agendatec/
│       │   ├── models/            # ← Compartido
│       │   ├── services/          # ← Compartido
│       │   ├── routes/            # Solo Flask
│       │   └── templates/         # Solo Flask (hasta migrar pages)
│       ├── helpdesk/              # (misma estructura)
│       └── vistetec/              # (misma estructura)
│
├── itcj2/                         # FastAPI (NUEVO)
│   ├── __init__.py                # (vacío o versión)
│   ├── main.py                    # create_app() FastAPI
│   ├── config.py                  # Settings con Pydantic
│   ├── database.py                # SQLAlchemy engine + SessionLocal
│   ├── dependencies.py            # Depends() comunes (auth, db session)
│   ├── middleware.py               # JWT middleware, CORS
│   ├── templates.py               # Jinja2 config + context processors
│   │
│   ├── core/                      # Core FastAPI
│   │   ├── __init__.py
│   │   ├── router.py              # APIRouter principal core
│   │   ├── schemas/               # Pydantic schemas
│   │   │   ├── auth.py
│   │   │   ├── user.py
│   │   │   └── ...
│   │   ├── api/                   # Endpoints API v2
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── notifications.py
│   │   │   └── ...
│   │   └── pages/                 # Page routes (cuando se migren)
│   │       ├── auth.py
│   │       ├── dashboard.py
│   │       └── ...
│   │
│   ├── apps/
│   │   ├── agendatec/
│   │   │   ├── __init__.py
│   │   │   ├── router.py          # APIRouter de la app
│   │   │   ├── schemas/           # Pydantic schemas
│   │   │   ├── api/               # Endpoints v2
│   │   │   └── pages/             # (cuando se migren)
│   │   ├── helpdesk/              # (misma estructura)
│   │   └── vistetec/              # (misma estructura)
│   │
│   └── sockets/                   # Socket.IO ASGI (cuando se migre)
│       ├── __init__.py
│       ├── slots.py
│       ├── requests.py
│       ├── notifications.py
│       └── helpdesk.py
│
├── wsgi.py                        # Entry point Flask (sin cambios)
├── asgi.py                        # Entry point FastAPI (NUEVO)
├── docker/
│   ├── backend/
│   │   ├── Dockerfile             # Flask (sin cambios)
│   │   ├── Dockerfile.fastapi     # FastAPI (NUEVO)
│   │   ├── entrypoint.sh          # Flask (sin cambios)
│   │   ├── entrypoint-fastapi.sh  # FastAPI (NUEVO)
│   │   └── gunicorn.conf.py       # Flask (sin cambios)
│   ├── compose/
│   │   ├── docker-compose.dev.yml # Actualizado (2 backends)
│   │   └── docker-compose.prod.yml # Actualizado (2 backends)
│   └── nginx/
│       ├── nginx.dev.conf         # Actualizado (routing v2)
│       └── nginx.prod.conf        # Actualizado (routing v2)
└── requirements-fastapi.txt       # Deps FastAPI (NUEVO)
```

### ¿Por qué `itcj2/` separado y no dentro de `itcj/`?

1. **Cero riesgo de romper Flask**: `itcj/` no se toca en absoluto durante las primeras fases
2. **Imports claros**: `from itcj.core.models.user import User` funciona desde ambos
3. **Entrypoints separados**: `wsgi.py` (Flask) y `asgi.py` (FastAPI) son independientes
4. **Fácil de eliminar**: Cuando Flask ya no se use, se borra `itcj/` y se renombra `itcj2/` → `itcj/`

### ¿Cómo comparte modelos y servicios con Flask?

FastAPI importa directamente de `itcj/`:
```python
# En itcj2/apps/helpdesk/api/tickets.py
from itcj.apps.helpdesk.models.ticket import Ticket          # Modelo compartido
from itcj.apps.helpdesk.services.ticket_service import ...    # Servicio compartido
from itcj2.apps.helpdesk.schemas.ticket import TicketCreate   # Schema nuevo (Pydantic)
```

La única diferencia es que FastAPI no usa `Flask-SQLAlchemy` (el wrapper), sino SQLAlchemy directo:
```python
# itcj2/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Los modelos siguen usando `db.Model` de Flask-SQLAlchemy, que internamente hereda de `DeclarativeBase`. Esto es **100% compatible** con SQLAlchemy puro — el engine de FastAPI puede leer/escribir las mismas tablas.

---

## 4. Fase 0: Infraestructura Base

> **Objetivo**: Tener FastAPI corriendo en paralelo, con health check, sin funcionalidad aún.
> **Estimación**: Archivo base de configuración

### Tareas

- [ ] **0.1** Crear `requirements-fastapi.txt`
  ```
  fastapi>=0.115.0
  uvicorn[standard]>=0.34.0
  python-socketio[asyncio]>=5.13.0
  python-multipart>=0.0.20
  jinja2>=3.1.6
  ```
  > Nota: SQLAlchemy, PyJWT, redis, pydantic, etc. ya están en `requirements.txt`

- [ ] **0.2** Crear `itcj2/config.py` - Configuración con Pydantic Settings
  ```python
  from pydantic_settings import BaseSettings
  from functools import lru_cache

  class Settings(BaseSettings):
      DATABASE_URL: str
      REDIS_URL: str = "redis://redis:6379/0"
      SECRET_KEY: str
      JWT_SECRET_KEY: str
      JWT_EXPIRES_HOURS: int = 12
      FLASK_ENV: str = "production"
      CORS_ORIGINS: str = ""
      APP_TZ: str = "America/Ciudad_Juarez"

      class Config:
          env_file = ".env"

  @lru_cache
  def get_settings() -> Settings:
      return Settings()
  ```

- [ ] **0.3** Crear `itcj2/database.py` - SQLAlchemy engine compartido
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.orm import sessionmaker, Session
  from typing import Generator
  from .config import get_settings

  engine = create_engine(
      get_settings().DATABASE_URL,
      pool_pre_ping=True,
      pool_size=10,
      max_overflow=20,
  )
  SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

  def get_db() -> Generator[Session, None, None]:
      db = SessionLocal()
      try:
          yield db
      finally:
          db.close()
  ```

- [ ] **0.4** Crear `itcj2/main.py` - App factory FastAPI
  ```python
  from fastapi import FastAPI
  from fastapi.staticfiles import StaticFiles
  from contextlib import asynccontextmanager

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Startup
      yield
      # Shutdown: cerrar engine
      from .database import engine
      engine.dispose()

  def create_app() -> FastAPI:
      app = FastAPI(
          title="ITCJ Platform API v2",
          version="2.0.0",
          docs_url="/api/docs",
          redoc_url="/api/redoc",
          lifespan=lifespan,
      )

      # Middleware
      from .middleware import setup_middleware
      setup_middleware(app)

      # Routers
      from .routers import register_routers
      register_routers(app)

      # Health check
      @app.get("/health")
      async def health():
          return {"ok": True, "server": "fastapi"}

      return app
  ```

- [ ] **0.5** Crear `asgi.py` - Entry point FastAPI
  ```python
  from itcj2.main import create_app
  app = create_app()
  ```

- [ ] **0.6** Crear `itcj2/middleware.py` - JWT + CORS
  ```python
  from fastapi import FastAPI, Request
  from fastapi.middleware.cors import CORSMiddleware
  from starlette.middleware.base import BaseHTTPMiddleware
  from itcj.core.utils.jwt_tools import decode_jwt

  class JWTMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          token = request.cookies.get("itcj_token")
          request.state.current_user = decode_jwt(token) if token else None
          response = await call_next(request)
          return response

  def setup_middleware(app: FastAPI):
      app.add_middleware(CORSMiddleware, ...)
      app.add_middleware(JWTMiddleware)
  ```

- [ ] **0.7** Crear `itcj2/dependencies.py` - Dependencias inyectables
  ```python
  from fastapi import Depends, HTTPException, Request
  from sqlalchemy.orm import Session
  from .database import get_db

  def get_current_user(request: Request) -> dict:
      user = request.state.current_user
      if not user:
          raise HTTPException(status_code=401, detail="No autenticado")
      return user

  def get_current_user_optional(request: Request) -> dict | None:
      return request.state.current_user
  ```

- [ ] **0.8** Crear `docker/backend/Dockerfile.fastapi`
  ```dockerfile
  FROM python:3.12-slim
  # ... (mismas deps de sistema que Dockerfile Flask)
  COPY requirements.txt /app/requirements.txt
  COPY requirements-fastapi.txt /app/requirements-fastapi.txt
  RUN pip install --no-cache-dir -r /app/requirements.txt \
      -r /app/requirements-fastapi.txt
  COPY docker/backend/entrypoint-fastapi.sh /usr/local/bin/
  RUN chmod +x /usr/local/bin/entrypoint-fastapi.sh
  EXPOSE 8001
  ENTRYPOINT ["/usr/local/bin/entrypoint-fastapi.sh"]
  ```

- [ ] **0.9** Crear `docker/backend/entrypoint-fastapi.sh`
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd /app
  # Nota: Las migraciones las sigue corriendo Flask
  exec uvicorn asgi:app --host 0.0.0.0 --port 8001 --workers 1
  ```

- [ ] **0.10** Actualizar `docker-compose.dev.yml` - Agregar servicio FastAPI
  ```yaml
  backend-fastapi:
    build:
      context: ../..
      dockerfile: docker/backend/Dockerfile.fastapi
    volumes:
      - ../../:/app
    ports:
      - "8001:8001"
    env_file:
      - ../../.env
    depends_on:
      - redis
      - postgres
  ```

- [ ] **0.11** Actualizar `nginx.dev.conf` - Routing v2
  ```nginx
  upstream backend_fastapi {
      server backend-fastapi:8001;
  }

  # Agregar antes del location /api/ existente:
  location /api/core/v2/      { proxy_pass http://backend_fastapi; }
  location /api/agendatec/v2/  { proxy_pass http://backend_fastapi; }
  location /api/help-desk/v2/  { proxy_pass http://backend_fastapi; }
  location /api/vistetec/v2/   { proxy_pass http://backend_fastapi; }
  ```

### Resultado Fase 0
- `GET http://localhost:8001/health` → `{"ok": true, "server": "fastapi"}`
- `GET http://localhost:8001/api/docs` → Swagger UI vacío
- Flask sigue funcionando exactamente igual en `:8000`

---

## 5. Fase 1: Core Compartido

> **Objetivo**: Autenticación, autorización y utilidades funcionando en FastAPI.

### Tareas

- [ ] **1.1** Crear `itcj2/core/__init__.py` + `itcj2/core/router.py`
  ```python
  from fastapi import APIRouter
  core_router = APIRouter(prefix="/api/core/v2", tags=["core"])
  ```

- [ ] **1.2** Crear `itcj2/core/schemas/` - Schemas Pydantic para auth, user, etc.
  ```python
  # itcj2/core/schemas/auth.py
  from pydantic import BaseModel

  class LoginRequest(BaseModel):
      username: str
      password: str

  class LoginResponse(BaseModel):
      success: bool
      user: dict
  ```

- [ ] **1.3** Crear `itcj2/core/api/auth.py` - Login/logout v2
  - Reusar `itcj.core.services.auth_service` para la lógica
  - Crear endpoint que setea la misma cookie `itcj_token`
  - **Importante**: Misma cookie = sesión compartida Flask/FastAPI

- [ ] **1.4** Crear dependencias de autorización equivalentes a decorators Flask
  ```python
  # itcj2/dependencies.py
  def require_app(app_key: str):
      """Equivalente a @app_required("helpdesk")"""
      def dependency(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
          from itcj.core.services.authz_service import has_any_assignment
          if not has_any_assignment(int(user["sub"]), app_key):
              raise HTTPException(403, "Sin acceso a esta aplicación")
          return user
      return Depends(dependency)

  def require_roles(app_key: str, roles: list[str]):
      """Equivalente a @app_required_enhanced("helpdesk", roles=["admin"])"""
      ...
  ```

- [ ] **1.5** Crear `itcj2/core/api/users.py` - Endpoints de usuario
- [ ] **1.6** Crear `itcj2/core/api/notifications.py` - Notificaciones v2
- [ ] **1.7** Registrar routers core en `itcj2/main.py`

### Resultado Fase 1
- `POST /api/core/v2/auth/login` funciona y comparte sesión con Flask
- `GET /api/core/v2/users/me` devuelve el usuario actual
- Los decoradores de autorización están listos para las apps

---

## 6. Fase 2: APIs v2 (FastAPI)

> **Objetivo**: Migrar las APIs de cada app a v2. Este es el trabajo principal.
> **Orden sugerido**: helpdesk → agendatec → vistetec (de menor a mayor complejidad de pages)

### Patrón de migración por endpoint

Para cada endpoint Flask:

```python
# ANTES (Flask) - itcj/apps/helpdesk/routes/api/tickets.py
@tickets_api_bp.route("/", methods=["GET"])
@api_app_required("helpdesk")
def get_tickets():
    page = request.args.get("page", 1, type=int)
    result = ticket_service.get_tickets(page=page)
    return jsonify(result)
```

```python
# DESPUÉS (FastAPI) - itcj2/apps/helpdesk/api/tickets.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from itcj2.dependencies import get_current_user, get_db, require_app
from itcj.apps.helpdesk.services.ticket_service import get_tickets  # ← MISMO servicio
from itcj2.apps.helpdesk.schemas.ticket import TicketListResponse

router = APIRouter(prefix="/tickets", tags=["helpdesk-tickets"])

@router.get("/", response_model=TicketListResponse)
async def list_tickets(
    page: int = Query(1, ge=1),
    user: dict = require_app("helpdesk"),
    db: Session = Depends(get_db),
):
    return get_tickets(page=page)
```

**Puntos clave**:
- Los **servicios** (`ticket_service`, etc.) se reusan sin cambios
- Solo se crean **schemas Pydantic** nuevos para request/response
- Los **modelos SQLAlchemy** se importan directo de `itcj/`
- Cada endpoint nuevo está **documentado automáticamente** en Swagger

### 2.1 Help-Desk APIs v2

- [ ] **2.1.1** Crear `itcj2/apps/helpdesk/schemas/` (ticket, comment, category, etc.)
- [ ] **2.1.2** Crear `itcj2/apps/helpdesk/api/tickets.py` - CRUD tickets
- [ ] **2.1.3** Crear `itcj2/apps/helpdesk/api/assignments.py`
- [ ] **2.1.4** Crear `itcj2/apps/helpdesk/api/comments.py`
- [ ] **2.1.5** Crear `itcj2/apps/helpdesk/api/attachments.py` (file upload)
- [ ] **2.1.6** Crear `itcj2/apps/helpdesk/api/categories.py`
- [ ] **2.1.7** Crear `itcj2/apps/helpdesk/api/inventory.py`
- [ ] **2.1.8** Crear `itcj2/apps/helpdesk/api/stats.py`
- [ ] **2.1.9** Crear `itcj2/apps/helpdesk/api/documents.py`
- [ ] **2.1.10** Crear `itcj2/apps/helpdesk/router.py` - Registrar todos los sub-routers
  ```python
  from fastapi import APIRouter
  from .api import tickets, assignments, comments, ...

  helpdesk_router = APIRouter(prefix="/api/help-desk/v2", tags=["helpdesk"])
  helpdesk_router.include_router(tickets.router)
  helpdesk_router.include_router(assignments.router)
  # ...
  ```

### 2.2 AgendaTec APIs v2

- [ ] **2.2.1** Crear `itcj2/apps/agendatec/schemas/`
- [ ] **2.2.2** Crear `itcj2/apps/agendatec/api/requests.py`
- [ ] **2.2.3** Crear `itcj2/apps/agendatec/api/slots.py`
- [ ] **2.2.4** Crear `itcj2/apps/agendatec/api/availability.py`
- [ ] **2.2.5** Crear `itcj2/apps/agendatec/api/programs.py`
- [ ] **2.2.6** Crear `itcj2/apps/agendatec/api/admin.py`
- [ ] **2.2.7** Crear `itcj2/apps/agendatec/api/notifications.py`
- [ ] **2.2.8** Crear `itcj2/apps/agendatec/api/periods.py`
- [ ] **2.2.9** Crear `itcj2/apps/agendatec/router.py`

### 2.3 VisteTec APIs v2

- [ ] **2.3.1** Crear `itcj2/apps/vistetec/schemas/`
- [ ] **2.3.2** Crear `itcj2/apps/vistetec/api/catalog.py`
- [ ] **2.3.3** Crear `itcj2/apps/vistetec/api/garments.py`
- [ ] **2.3.4** Crear `itcj2/apps/vistetec/api/appointments.py`
- [ ] **2.3.5** Crear `itcj2/apps/vistetec/api/donations.py`
- [ ] **2.3.6** Crear `itcj2/apps/vistetec/api/pantry.py`
- [ ] **2.3.7** Crear `itcj2/apps/vistetec/api/slots.py`
- [ ] **2.3.8** Crear `itcj2/apps/vistetec/api/reports.py`
- [ ] **2.3.9** Crear `itcj2/apps/vistetec/router.py`

### 2.4 Core APIs v2

- [ ] **2.4.1** `itcj2/core/api/authz.py` - Gestión de permisos
- [ ] **2.4.2** `itcj2/core/api/departments.py`
- [ ] **2.4.3** `itcj2/core/api/positions.py`
- [ ] **2.4.4** `itcj2/core/api/themes.py`
- [ ] **2.4.5** `itcj2/core/api/deploy.py`
- [ ] **2.4.6** `itcj2/core/api/mobile.py`

### Resultado Fase 2
- Todas las APIs disponibles en v2 con documentación Swagger automática
- Flask v1 sigue funcionando sin cambios
- Frontend puede migrar gradualmente de `/api/*/v1/` a `/api/*/v2/`

---

## 7. Fase 3: Socket.IO ASGI

> **Objetivo**: Migrar Socket.IO de Flask-SocketIO (eventlet) a python-socketio (ASGI nativo).

### Tareas

- [ ] **3.1** Crear `itcj2/sockets/__init__.py`
  ```python
  import socketio
  from .config import get_settings

  # Crear servidor Socket.IO ASGI
  sio = socketio.AsyncServer(
      async_mode="asgi",
      client_manager=socketio.AsyncRedisManager(get_settings().REDIS_URL),
      cors_allowed_origins=...,
  )

  # ASGI app para montar en FastAPI
  socket_app = socketio.ASGIApp(sio, socketio_path="/socket.io")
  ```

- [ ] **3.2** Migrar eventos: `slots.py`, `requests.py`, `notifications.py`, `helpdesk.py`
  ```python
  # ANTES (Flask-SocketIO)
  @socketio.on("join_ticket_room")
  def handle_join(data):
      join_room(f"ticket_{data['ticket_id']}")

  # DESPUÉS (python-socketio ASGI)
  @sio.on("join_ticket_room")
  async def handle_join(sid, data):
      await sio.enter_room(sid, f"ticket_{data['ticket_id']}")
  ```

- [ ] **3.3** Montar Socket.IO en FastAPI
  ```python
  # itcj2/main.py
  from itcj2.sockets import socket_app
  app.mount("/socket.io", socket_app)
  ```

- [ ] **3.4** Actualizar servicios que emiten eventos (NotificationService, etc.)
  - Los servicios en `itcj/core/services/` que usan `socketio.emit()` necesitan un adaptador
  - Crear un wrapper que detecte si está corriendo en Flask o FastAPI:
  ```python
  # itcj/core/services/notification_service.py (actualizado)
  def emit_notification(event, data, room=None):
      try:
          # Intentar Flask-SocketIO
          from itcj.core.extensions import socketio
          if socketio:
              socketio.emit(event, data, room=room)
              return
      except:
          pass
      # Fallback: publicar directo a Redis (python-socketio lo recoge)
      import redis
      r = redis.from_url(os.getenv("REDIS_URL"))
      r.publish("socketio", json.dumps({"event": event, "data": data, "room": room}))
  ```

- [ ] **3.5** Actualizar Nginx para routear Socket.IO a FastAPI
  ```nginx
  location /socket.io/ {
      proxy_pass http://backend_fastapi;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_read_timeout 86400;
      proxy_send_timeout 86400;
  }
  ```

- [ ] **3.6** Eliminar eventlet de las dependencias (ya no se necesita)
  - Uvicorn usa asyncio nativo, no necesita eventlet
  - Flask puede seguir con eventlet o cambiar a gevent si se necesita

### Resultado Fase 3
- Socket.IO corriendo en modo ASGI nativo (mejor performance)
- Todos los eventos en tiempo real funcionando vía FastAPI
- Flask ya no maneja WebSockets

---

## 8. Fase 4: Templates/Pages

> **Objetivo**: Migrar las páginas HTML de Flask a FastAPI.
> **Nota**: Esta es la ÚLTIMA fase para evitar conflictos de rutas.

### Setup de Jinja2 en FastAPI

- [ ] **4.1** Crear `itcj2/templates.py`
  ```python
  from fastapi.templating import Jinja2Templates
  from starlette.requests import Request
  import json

  # Reusar los mismos directorios de templates
  templates = Jinja2Templates(directory=[
      "itcj/core/templates",            # Templates core
      "itcj/apps/agendatec/templates",  # Templates agendatec
      "itcj/apps/helpdesk/templates",   # Templates helpdesk
      "itcj/apps/vistetec/templates",   # Templates vistetec
  ])

  # Equivalente a @app.context_processor
  def render(request: Request, template: str, context: dict = {}):
      """Helper para renderizar con contexto global inyectado."""
      # Cargar manifest estático
      manifest = load_manifest()

      context.update({
          "request": request,  # Requerido por Starlette
          "current_user": request.state.current_user,
          "sv": lambda app, file: manifest.get(app, {}).get(file, "1.0.0"),
          # ... otros context processors
      })
      return templates.TemplateResponse(template, context)
  ```

### Migración de pages (gradual)

La estrategia es migrar app por app, y dentro de cada app, ruta por ruta:

- [ ] **4.2** Migrar pages Core (`/itcj/...`)
  - Login, dashboard, perfil, configuración
  - Actualizar Nginx: `location /itcj/ { proxy_pass http://backend_fastapi; }`

- [ ] **4.3** Migrar pages Help-Desk (`/help-desk/...`)
- [ ] **4.4** Migrar pages AgendaTec (`/agendatec/...`)
- [ ] **4.5** Migrar pages VisteTec (`/vistetec/...`)

### Patrón de migración por page

```python
# ANTES (Flask) - itcj/apps/helpdesk/routes/pages/user.py
@user_pages_bp.route("/")
@app_required("helpdesk")
def user_home():
    return render_template("helpdesk/home_landing.html")

# DESPUÉS (FastAPI) - itcj2/apps/helpdesk/pages/user.py
from fastapi import APIRouter, Request, Depends
from itcj2.templates import render
from itcj2.dependencies import require_app

router = APIRouter(tags=["helpdesk-pages"])

@router.get("/")
async def user_home(request: Request, user: dict = require_app("helpdesk")):
    return render(request, "helpdesk/home_landing.html")
```

### Cambios mínimos en templates

Los templates `.html` existentes necesitan **muy pocos cambios**:

| Flask (actual) | FastAPI (nuevo) | Notas |
|---|---|---|
| `{{ url_for('static', ...) }}` | Usar paths directos `/static/...` o crear helper | Nginx sirve los estáticos |
| `{{ url_for('endpoint') }}` | Crear helper `url_for()` en context | O usar paths directos |
| `{{ current_user }}` | `{{ current_user }}` | Sin cambio (inyectado) |
| `{{ sv('app', 'file') }}` | `{{ sv('app', 'file') }}` | Sin cambio (inyectado) |
| `{{ request.path }}` | `{{ request.url.path }}` | Pequeño cambio |

- [ ] **4.6** Crear helper `url_for` compatible en Jinja2 context
  ```python
  # Mapeo simple de endpoints a URLs
  def url_for_compat(endpoint: str, **kwargs) -> str:
      """Emula Flask url_for() para compatibilidad de templates."""
      # Mapeo de endpoints conocidos
      routes = {
          "pages_core.pages_auth.login_page": "/itcj/auth/login",
          "helpdesk_pages.user_home": "/help-desk/user/",
          # ... se va completando conforme se migran
      }
      return routes.get(endpoint, "#")
  ```

### Notas sobre `url_for`

La función `url_for` de Flask es la que más trabajo da al migrar templates. Opciones:

1. **Reemplazar con paths directos** (recomendado para estáticos): `"/static/helpdesk/css/style.css"`
2. **Crear diccionario de rutas** (para navegación): mapeo endpoint → URL
3. **Usar `request.url_for()`** de Starlette (funciona si los endpoints tienen `name`)

### Resultado Fase 4
- Todas las páginas servidas por FastAPI
- Flask solo mantiene las APIs v1 (para compatibilidad)
- Los templates existentes funcionan con mínimos cambios

---

## 9. Fase 5: Eliminar Flask

> **Objetivo**: Remover Flask por completo una vez que todo funciona en FastAPI.

### Tareas

- [ ] **5.1** Verificar que ningún frontend llama a `/api/*/v1/` (deprecar v1)
- [ ] **5.2** Migrar servicios que dependan de `flask.g` o `current_app`
  - Reemplazar `db.session` (Flask-SQLAlchemy) por `SessionLocal()` directo
  - Reemplazar `current_app.config` por `get_settings()`
  - Reemplazar `current_app.logger` por `logging.getLogger()`
- [ ] **5.3** Migrar Flask CLI commands a FastAPI/Typer
  ```python
  # Usar typer o click directo (sin Flask)
  import typer
  app = typer.Typer()

  @app.command()
  def sync_students():
      ...
  ```
- [ ] **5.4** Migrar migraciones de Flask-Migrate a Alembic directo
  ```python
  # alembic.ini ya existe, solo cambiar el runner
  # En vez de: flask db upgrade
  # Usar: alembic upgrade head
  ```
- [ ] **5.5** Actualizar `entrypoint-fastapi.sh` para correr migraciones
- [ ] **5.6** Eliminar servicio `backend-flask` de docker-compose
- [ ] **5.7** Actualizar Nginx para que todo vaya a FastAPI
- [ ] **5.8** Eliminar directorio `itcj/` (o archivar)
- [ ] **5.9** Renombrar `itcj2/` → `itcj/` y `asgi.py` → `main.py`
- [ ] **5.10** Limpiar dependencias: remover Flask, Flask-SocketIO, Flask-SQLAlchemy, eventlet, etc.
- [ ] **5.11** Actualizar deploy script para un solo backend

---

## 10. Docker & Nginx

### Cambios en docker-compose (dev)

```yaml
# docker/compose/docker-compose.dev.yml - CAMBIOS
services:
  # ... redis, postgres sin cambios ...

  backend:  # Flask (sin cambios)
    # ... existente ...

  backend-fastapi:  # NUEVO
    build:
      context: ../..
      dockerfile: docker/backend/Dockerfile.fastapi
    volumes:
      - ../../:/app
    ports:
      - "8001:8001"
    environment:
      - PYTHONPATH=/app
    env_file:
      - ../../.env
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    command: uvicorn asgi:app --host 0.0.0.0 --port 8001 --reload

  nginx:
    # ... actualizar config para incluir v2 routing ...
```

### Cambios en Nginx (dev)

```nginx
# docker/nginx/nginx.dev.conf - ADICIONES

upstream backend_fastapi {
    server backend-fastapi:8001;
    keepalive 32;
}

# ANTES de "location /api/" agregar:
location /api/core/v2/ {
    proxy_pass http://backend_fastapi;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60;
    proxy_send_timeout 60;
}
location /api/agendatec/v2/ { proxy_pass http://backend_fastapi; ... }
location /api/help-desk/v2/ { proxy_pass http://backend_fastapi; ... }
location /api/vistetec/v2/  { proxy_pass http://backend_fastapi; ... }

# Docs de FastAPI
location /api/docs { proxy_pass http://backend_fastapi; }
location /api/redoc { proxy_pass http://backend_fastapi; }
location /api/openapi.json { proxy_pass http://backend_fastapi; }
```

### Producción (blue-green con 2 frameworks)

Para producción, durante la coexistencia:
```yaml
# docker-compose.prod.yml
backend-blue:      # Flask
backend-green:     # Flask
backend-fastapi:   # FastAPI (siempre on, sin blue-green por ahora)
```

FastAPI no necesita blue-green inicialmente porque solo maneja APIs v2 (sin estado). Se puede agregar después cuando maneje pages.

---

## 11. Checklist por App

### Core
| Componente | Flask v1 | FastAPI v2 | Estado |
|---|---|---|---|
| Auth (login/logout) | `/api/core/v1/auth` | `/api/core/v2/auth` | ⬜ Pendiente |
| Users | `/api/core/v1/users` | `/api/core/v2/users` | ⬜ Pendiente |
| Authorization | `/api/core/v1/authz` | `/api/core/v2/authz` | ⬜ Pendiente |
| Departments | `/api/core/v1/departments` | `/api/core/v2/departments` | ⬜ Pendiente |
| Positions | `/api/core/v1/positions` | `/api/core/v2/positions` | ⬜ Pendiente |
| Notifications | `/api/core/v1/notifications` | `/api/core/v2/notifications` | ⬜ Pendiente |
| Themes | `/api/core/v1/themes` | `/api/core/v2/themes` | ⬜ Pendiente |
| Deploy | `/api/core/v1/deploy` | `/api/core/v2/deploy` | ⬜ Pendiente |
| Pages (auth) | `/itcj/auth/*` | `/itcj/auth/*` | ⬜ Pendiente |
| Pages (dashboard) | `/itcj/dashboard/*` | `/itcj/dashboard/*` | ⬜ Pendiente |
| Pages (config) | `/itcj/config/*` | `/itcj/config/*` | ⬜ Pendiente |
| Socket.IO | Flask-SocketIO | python-socketio ASGI | ⬜ Pendiente |

### Help-Desk
| Componente | Flask v1 | FastAPI v2 | Estado |
|---|---|---|---|
| Tickets | `/api/help-desk/v1/tickets` | `/api/help-desk/v2/tickets` | ⬜ Pendiente |
| Assignments | `/api/help-desk/v1/assignments` | `/api/help-desk/v2/assignments` | ⬜ Pendiente |
| Comments | `/api/help-desk/v1/comments` | `/api/help-desk/v2/comments` | ⬜ Pendiente |
| Attachments | `/api/help-desk/v1/attachments` | `/api/help-desk/v2/attachments` | ⬜ Pendiente |
| Categories | `/api/help-desk/v1/categories` | `/api/help-desk/v2/categories` | ⬜ Pendiente |
| Inventory | `/api/help-desk/v1/inventory` | `/api/help-desk/v2/inventory` | ⬜ Pendiente |
| Stats | `/api/help-desk/v1/stats` | `/api/help-desk/v2/stats` | ⬜ Pendiente |
| Documents | `/api/help-desk/v1/documents` | `/api/help-desk/v2/documents` | ⬜ Pendiente |
| Pages | `/help-desk/*` | `/help-desk/*` | ⬜ Pendiente |

### AgendaTec
| Componente | Flask v1 | FastAPI v2 | Estado |
|---|---|---|---|
| Requests | `/api/agendatec/v1/requests` | `/api/agendatec/v2/requests` | ⬜ Pendiente |
| Slots | `/api/agendatec/v1/slots` | `/api/agendatec/v2/slots` | ⬜ Pendiente |
| Availability | `/api/agendatec/v1/availability` | `/api/agendatec/v2/availability` | ⬜ Pendiente |
| Programs | `/api/agendatec/v1/programs` | `/api/agendatec/v2/programs` | ⬜ Pendiente |
| Admin | `/api/agendatec/v1/admin` | `/api/agendatec/v2/admin` | ⬜ Pendiente |
| Periods | `/api/agendatec/v1/periods` | `/api/agendatec/v2/periods` | ⬜ Pendiente |
| Pages | `/agendatec/*` | `/agendatec/*` | ⬜ Pendiente |

### VisteTec
| Componente | Flask v1 | FastAPI v2 | Estado |
|---|---|---|---|
| Catalog | `/api/vistetec/v1/catalog` | `/api/vistetec/v2/catalog` | ⬜ Pendiente |
| Garments | `/api/vistetec/v1/garments` | `/api/vistetec/v2/garments` | ⬜ Pendiente |
| Appointments | `/api/vistetec/v1/appointments` | `/api/vistetec/v2/appointments` | ⬜ Pendiente |
| Donations | `/api/vistetec/v1/donations` | `/api/vistetec/v2/donations` | ⬜ Pendiente |
| Pantry | `/api/vistetec/v1/pantry` | `/api/vistetec/v2/pantry` | ⬜ Pendiente |
| Slots | `/api/vistetec/v1/slots` | `/api/vistetec/v2/slots` | ⬜ Pendiente |
| Reports | `/api/vistetec/v1/reports` | `/api/vistetec/v2/reports` | ⬜ Pendiente |
| Pages | `/vistetec/*` | `/vistetec/*` | ⬜ Pendiente |

---

## 12. Dependencias Nuevas

### `requirements-fastapi.txt`
```
# FastAPI core
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
python-multipart>=0.0.20

# Settings
pydantic-settings>=2.7.0

# Socket.IO ASGI (ya tienes python-socketio, pero necesitas extras async)
# python-socketio[asyncio] ya incluye aiohttp

# ASGI server para producción
httptools>=0.6.0
uvloop>=0.21.0; sys_platform != 'win32'
```

> **Nota**: `pydantic`, `jinja2`, `sqlalchemy`, `redis`, `pyjwt` ya están en `requirements.txt`.

---

## 13. Equivalencias Flask → FastAPI

### Conceptos principales

| Flask | FastAPI | Notas |
|---|---|---|
| `Blueprint` | `APIRouter` | Casi 1:1 en funcionalidad |
| `@bp.route("/", methods=["GET"])` | `@router.get("/")` | Decoradores separados por método |
| `request.args` | Parámetros de función + `Query()` | Type-safe automático |
| `request.json` | Pydantic model como parámetro | Validación automática |
| `request.form` | `Form()` dependency | Para formularios |
| `request.files` | `UploadFile` | Mejor soporte async |
| `jsonify(data)` | `return data` | FastAPI serializa automático |
| `abort(404)` | `raise HTTPException(404)` | Excepciones en vez de abort |
| `g.current_user` | `request.state.current_user` | Via middleware |
| `@login_required` | `Depends(get_current_user)` | Dependency injection |
| `@app_required("hd")` | `require_app("hd")` | Custom dependency |
| `render_template()` | `templates.TemplateResponse()` | Muy similar |
| `url_for()` | `request.url_for()` / manual | Necesita adaptación |
| `before_request` | Middleware | ASGI middleware |
| `after_request` | Middleware | ASGI middleware |
| `context_processor` | Template context dict | Manual pero simple |
| `errorhandler` | Exception handlers | `@app.exception_handler()` |
| `Flask-SQLAlchemy db.session` | `Depends(get_db)` | Session por request |
| `app.config["KEY"]` | `settings.KEY` | Pydantic Settings |
| `current_app.logger` | `logging.getLogger()` | Standard logging |

### Estructura de Router (equivalente a Blueprint)

```python
# Flask Blueprint
helpdesk_api_bp = Blueprint('helpdesk_api', __name__)
helpdesk_api_bp.register_blueprint(tickets_bp, url_prefix='/tickets')

# FastAPI Router
helpdesk_router = APIRouter(prefix="/api/help-desk/v2")
helpdesk_router.include_router(tickets_router, prefix="/tickets")
```

---

## 14. Riesgos y Mitigación

### Riesgo 1: Sesiones compartidas
- **Problema**: Flask y FastAPI usan la misma cookie `itcj_token`
- **Mitigación**: Ambos usan exactamente la misma librería `jwt_tools.py` para encode/decode
- **Test**: Login en Flask → acceder API v2 en FastAPI (y viceversa)

### Riesgo 2: Modelos SQLAlchemy con Flask-SQLAlchemy
- **Problema**: Los modelos heredan de `db.Model` (Flask-SQLAlchemy wrapper)
- **Mitigación**: `db.Model` hereda de `DeclarativeBase` de SQLAlchemy. El engine de FastAPI puede trabajar con las mismas tablas sin problemas. Ya probado en muchos proyectos.
- **Nota**: `db.session` de Flask-SQLAlchemy NO se usa en FastAPI. FastAPI usa `SessionLocal()` directo.

### Riesgo 3: Servicios que usan `flask.g` o `current_app`
- **Problema**: Algunos servicios en `itcj/core/services/` importan Flask globals
- **Mitigación**: Refactorizar gradualmente para recibir dependencias como parámetros
  ```python
  # ANTES
  def get_tickets():
      user = g.current_user  # ❌ Acoplado a Flask

  # DESPUÉS
  def get_tickets(user_id: int, db_session=None):
      session = db_session or db.session  # ✅ Funciona en ambos
  ```

### Riesgo 4: Socket.IO durante la transición
- **Problema**: Si Flask y FastAPI emiten eventos, ¿se duplican?
- **Mitigación**: Redis message queue sincroniza ambos. Solo UN servidor maneja Socket.IO a la vez. La migración se hace en un solo paso (Fase 3).

### Riesgo 5: `url_for()` en templates
- **Problema**: Templates usan extensivamente `url_for('endpoint_name')`
- **Mitigación**:
  1. Para estáticos: ya usa Nginx, paths directos funcionan (`/static/helpdesk/...`)
  2. Para navegación: crear helper que mapea endpoints a URLs
  3. Migrar gradualmente template por template

### Riesgo 6: File uploads
- **Problema**: Flask usa `request.files`, FastAPI usa `UploadFile`
- **Mitigación**: La lógica de procesamiento (Pillow compression, etc.) vive en servicios, no en las rutas. Solo cambia cómo se recibe el archivo.

---

## Orden Recomendado de Ejecución

```
Fase 0 (Infraestructura) ─────────────────── Semana 1
  │
  ├── 0.1-0.5: Archivos base itcj2/
  ├── 0.6-0.7: Middleware y dependencies
  └── 0.8-0.11: Docker y Nginx
  │
Fase 1 (Core compartido) ─────────────────── Semana 2
  │
  ├── 1.1-1.4: Auth + Authorization en FastAPI
  └── 1.5-1.7: Users, Notifications
  │
Fase 2 (APIs v2) ─────────────────────────── Semanas 3-6
  │
  ├── 2.1: Help-Desk APIs (1-2 semanas)
  ├── 2.2: AgendaTec APIs (1-2 semanas)
  ├── 2.3: VisteTec APIs (1 semana)
  └── 2.4: Core APIs restantes (unos días)
  │
Fase 3 (Socket.IO) ───────────────────────── Semana 7
  │
  └── 3.1-3.6: Migrar a ASGI nativo
  │
Fase 4 (Pages/Templates) ─────────────────── Semanas 8-10
  │
  ├── 4.1: Setup Jinja2 en FastAPI
  ├── 4.2: Core pages
  ├── 4.3: Help-Desk pages
  ├── 4.4: AgendaTec pages
  └── 4.5: VisteTec pages
  │
Fase 5 (Cleanup) ─────────────────────────── Semana 11
  │
  └── 5.1-5.11: Eliminar Flask, renombrar, limpiar
```

> **Nota importante**: Durante todo este proceso, las funcionalidades NUEVAS que desarrolles ya las haces directamente en `itcj2/` con FastAPI. No hay necesidad de esperar a que termine la migración completa.

---

## Comandos Útiles

```bash
# Desarrollo - levantar ambos
docker compose -f docker/compose/docker-compose.dev.yml up

# Solo FastAPI (sin Docker, para desarrollo rápido)
PYTHONPATH=. uvicorn asgi:app --reload --port 8001

# Ver docs automáticos
# http://localhost:8001/api/docs      (Swagger)
# http://localhost:8001/api/redoc     (ReDoc)

# Correr tests FastAPI
pytest tests/fastapi/ -v
```

# Plan: Integración de Celery — Gestión de Tareas en Background

**Rama sugerida:** `feature/celery-task-manager`
**Fecha de planeación:** 2026-03-11
**Stack base:** FastAPI + SQLAlchemy 2.0 + Redis (ya activo) + PostgreSQL

---

## Resumen ejecutivo

Se integrará Celery como sistema de ejecución de tareas en background, añadiendo:

1. **Dos nuevos contenedores Docker**: `celery-worker` y `celery-beat`
2. **Tres nuevos modelos en la DB**: `TaskDefinition`, `PeriodicTask`, `TaskRun`
3. **Vista de administración** en `/config/system/tasks/` (dentro de la sección Sistema del panel de configuración existente)
4. **Cuatro tareas iniciales** implementadas y listas para ejecutar o agendar

---

## 1. Decisiones de diseño

| Decisión | Elección | Justificación |
|---|---|---|
| Broker | Redis (ya activo en `REDIS_URL`) | Sin costo de infraestructura, ya configurado |
| Result backend | PostgreSQL (modelo `TaskRun` propio) | Historial permanente, consultable desde UI, sin TTL |
| Schedules | DB-driven (modelo `PeriodicTask`) | Editable desde UI sin tocar código ni reiniciar contenedores |
| Permisos UI | Solo super-admin de sistema (`core.config.admin`) | Vista sensible, acceso restringido |
| Comunicación tareas→app | Redis Pub/Sub para notificaciones en tiempo real | Celery workers son procesos separados, no comparten el event loop de Uvicorn |

### Diagrama de arquitectura

```
┌─────────────────────────────────────────────────────┐
│                    Docker Network                    │
│                                                      │
│  ┌──────────┐   HTTP    ┌──────────┐                │
│  │  nginx   │ ────────► │ backend  │                │
│  └──────────┘           │(FastAPI) │                │
│                         └────┬─────┘                │
│                              │ Socket.IO             │
│  ┌──────────────┐            │ + Redis Sub           │
│  │ celery-worker│◄──────┐   ┌▼──────────┐           │
│  │  (4 workers) │       │   │   redis   │           │
│  └──────┬───────┘  broker│   └──────┬───┘           │
│         │                └──────────┘               │
│  ┌──────▼───────┐         pub/sub                   │
│  │ celery-beat  │◄──────── PeriodicTask (DB)         │
│  └──────────────┘                                    │
│                         ┌──────────┐                │
│  TaskRun (results) ────►│ postgres │                │
│  PeriodicTask      ────►│          │                │
│  TaskDefinition    ────►└──────────┘                │
└─────────────────────────────────────────────────────┘
```

---

## 2. Nuevos archivos y estructura

```
itcj2/
├── celery_app.py                    # Factory de la app Celery
├── tasks/
│   ├── __init__.py
│   ├── base.py                      # Clase base LoggedTask (registra TaskRun automáticamente)
│   ├── helpdesk_tasks.py            # cleanup adjuntos, conversión docs, exportación reportes
│   └── notification_tasks.py        # notificaciones masivas
├── core/
│   ├── models/
│   │   └── task_models.py           # TaskDefinition, PeriodicTask, TaskRun
│   ├── api/
│   │   └── tasks.py                 # Endpoints REST para la UI de tareas
│   ├── pages/config/
│   │   └── tasks.py                 # Página HTML para la vista de tareas
│   └── templates/core/config/system/
│       └── tasks.html               # Vista de gestión de tareas
docker/
├── compose/
│   ├── docker-compose.dev.yml       # + servicios celery-worker y celery-beat
│   └── docker-compose.prod.yml      # + servicios celery-worker y celery-beat (con replicas)
├── backend/
│   └── celery/
│       ├── entrypoint-worker.sh     # Script de arranque del worker
│       └── entrypoint-beat.sh       # Script de arranque del beat
migrations/versions/
└── xxxx_add_celery_task_models.py   # Migración para los 3 nuevos modelos
```

---

## 3. Modelos de base de datos

### 3.1 `TaskDefinition` — Catálogo de tareas disponibles

```python
# Representa las tareas "registradas" en el sistema.
# Se puebla automáticamente al arrancar los workers.
class TaskDefinition(Base):
    __tablename__ = "task_definitions"

    id: int (PK)
    task_name: str           # "itcj2.tasks.helpdesk_tasks.cleanup_attachments"
    display_name: str        # "Limpieza de Adjuntos Expirados"
    description: str         # Descripción larga
    app_name: str            # "helpdesk" | "core" | etc.
    category: str            # "maintenance" | "notification" | "report" | "import"
    default_args: JSON       # {} (parámetros por defecto)
    is_active: bool          # Si está disponible para uso
    created_at: datetime
    updated_at: datetime
```

### 3.2 `PeriodicTask` — Tareas periódicas configuradas desde la UI

```python
# Schedule gestionado desde la base de datos.
# celery-beat lee esta tabla para generar su schedule dinámico.
class PeriodicTask(Base):
    __tablename__ = "periodic_tasks"

    id: int (PK)
    name: str (único)        # "Limpieza diaria de adjuntos"
    task_name: str           # FK lógica a TaskDefinition.task_name
    cron_expression: str     # "0 2 * * *" (cron estándar, 5 campos)
    args_json: JSON          # [] (argumentos posicionales)
    kwargs_json: JSON        # {} (argumentos con nombre)
    is_active: bool          # Pausar/reanudar sin borrar
    description: str         # Nota de para qué sirve
    last_run_at: datetime    # Cuándo se ejecutó por última vez
    next_run_at: datetime    # Cuándo correrá la siguiente vez (calculado)
    created_by: int          # FK a User (quien creó el schedule)
    created_at: datetime
    updated_at: datetime
```

### 3.3 `TaskRun` — Historial de ejecuciones

```python
# Registro de cada ejecución. Se crea al inicio, se actualiza al final.
class TaskRun(Base):
    __tablename__ = "task_runs"

    id: int (PK)
    celery_task_id: str      # UUID asignado por Celery
    task_name: str           # Nombre de la tarea
    display_name: str        # Copia del display_name en el momento de ejecución
    status: Enum             # PENDING | RUNNING | SUCCESS | FAILURE | REVOKED
    trigger: Enum            # MANUAL | SCHEDULED | API
    triggered_by_user_id: int  # FK a User (null si fue por scheduler)
    periodic_task_id: int    # FK a PeriodicTask (null si fue manual)
    args_json: JSON          # Argumentos con los que se ejecutó
    result_json: JSON        # Resultado o error devuelto por la tarea
    progress: int            # 0-100 (para tareas largas)
    progress_message: str    # "Procesando 45/200 registros..."
    started_at: datetime
    finished_at: datetime
    duration_seconds: float  # Calculado: finished - started
    created_at: datetime
```

---

## 4. Celery App Factory

### `itcj2/celery_app.py`

```python
from celery import Celery
from itcj2.config import get_settings

def create_celery_app() -> Celery:
    settings = get_settings()

    app = Celery(
        "itcj2",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,   # Redis para estado en memoria, DB para historial real
        include=[
            "itcj2.tasks.helpdesk_tasks",
            "itcj2.tasks.notification_tasks",
        ]
    )

    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="America/Ciudad_Juarez",
        enable_utc=True,
        task_track_started=True,        # Permite saber cuándo inicia realmente
        task_acks_late=True,            # Reconoce solo al terminar (evita pérdida en crash)
        worker_prefetch_multiplier=1,   # Una tarea por worker a la vez (más justo)
        result_expires=3600,            # Redis result TTL: 1 hora (complementa la DB)
    )

    return app

celery_app = create_celery_app()
```

### `itcj2/tasks/base.py` — Clase base `LoggedTask`

Toda tarea hereda de esta clase. Su responsabilidad es:
1. Crear el registro `TaskRun` con status `RUNNING` al inicio
2. Actualizar el `TaskRun` con status `SUCCESS` o `FAILURE` al final
3. Emitir notificación Redis Pub/Sub cuando termina (para que Uvicorn la retransmita por Socket.IO)

```python
class LoggedTask(celery_app.Task):
    abstract = True

    def on_success(self, retval, task_id, args, kwargs): ...
    def on_failure(self, exc, task_id, args, kwargs, einfo): ...
    def update_progress(self, current, total, message=""): ...
```

---

## 5. Tareas a implementar

### 5.1 `cleanup_attachments` (helpdesk)
- **Ubicación:** `itcj2/tasks/helpdesk_tasks.py`
- **Basada en:** `itcj2/apps/helpdesk/services/attachment_cleanup.py` (ya existe)
- **Qué hace:** Busca adjuntos con `auto_delete_at < now()` → elimina archivos del disco → borra registros DB
- **Parámetros:** `dry_run: bool = False` (para simular sin borrar)
- **Schedule sugerido:** `0 3 * * *` (diario 3am)
- **Resultado:** `{"deleted_files": 12, "freed_mb": 45.3, "errors": []}`

### 5.2 `send_mass_notification` (core)
- **Ubicación:** `itcj2/tasks/notification_tasks.py`
- **Qué hace:** Recibe lista de `user_ids` (o filtros: por rol, por app, por departamento) y crea registros `Notification` para cada uno + emite Socket.IO broadcast
- **Parámetros:**
  ```json
  {
    "title": "Mantenimiento programado",
    "message": "El sistema estará en mantenimiento el viernes...",
    "target": "all" | "role:admin" | "app:helpdesk" | "users:[1,2,3]",
    "app_name": "core",
    "link": "/itcj/..."
  }
  ```
- **Resultado:** `{"sent_to": 142, "failed": 0}`

### 5.3 `convert_document` (helpdesk)
- **Ubicación:** `itcj2/tasks/helpdesk_tasks.py`
- **Qué hace:** Toma `attachment_id`, convierte el DOCX a PDF con LibreOffice, guarda el PDF y actualiza el registro
- **Actualmente:** Conversion bloquea el request HTTP durante ~2-5 segundos. Con Celery, el endpoint devuelve inmediatamente y el usuario recibe notificación Socket.IO cuando el PDF está listo
- **Parámetros:** `attachment_id: int`, `ticket_id: int`, `notify_user_id: int`
- **Resultado:** `{"pdf_path": "instance/apps/helpdesk/...", "pages": 3}`

### 5.4 `export_inventory_report` (helpdesk)
- **Ubicación:** `itcj2/tasks/helpdesk_tasks.py`
- **Qué hace:** Genera un reporte CSV/XLSX de inventario en background (puede tardar varios segundos con miles de registros), guarda el archivo en `instance/apps/helpdesk/exports/`, crea notificación con link de descarga
- **Parámetros:** `filters: dict`, `format: "csv" | "xlsx"`, `requested_by_user_id: int`
- **Resultado:** `{"file_path": "...", "rows": 1240, "download_url": "/api/helpdesk/exports/..."}`

---

## 6. Docker — Nuevos servicios

### Cambios en `docker-compose.dev.yml`

```yaml
  celery-worker:
    build:
      context: ../..
      dockerfile: docker/backend/Dockerfile.fastapi   # mismo Dockerfile que backend
    env_file: ../../.env
    volumes:
      - ../../:/app
    command: sh /app/docker/backend/celery/entrypoint-worker.sh
    depends_on:
      pgbouncer:
        condition: service_healthy
      redis:
        condition: service_started

  celery-beat:
    build:
      context: ../..
      dockerfile: docker/backend/Dockerfile.fastapi
    env_file: ../../.env
    volumes:
      - ../../:/app
    command: sh /app/docker/backend/celery/entrypoint-beat.sh
    depends_on:
      pgbouncer:
        condition: service_healthy
      redis:
        condition: service_started
```

> **Nota prod:** En `docker-compose.prod.yml`, `celery-worker` puede tener `deploy.replicas: 2` para paralelismo. Beat siempre debe correr en una sola instancia (evitar duplicados de schedules).

### `docker/backend/celery/entrypoint-worker.sh`
```bash
#!/bin/sh
cd /app
python -m itcj2.cli.main db-check  # Esperar a que la DB esté lista
celery -A itcj2.celery_app worker \
  --loglevel=info \
  --concurrency=4 \
  --queues=default,reports,notifications
```

### `docker/backend/celery/entrypoint-beat.sh`
```bash
#!/bin/sh
cd /app
celery -A itcj2.celery_app beat \
  --loglevel=info \
  --scheduler itcj2.tasks.scheduler:DatabaseScheduler
```

### Colas (Queues)
| Cola | Propósito | Concurrencia |
|---|---|---|
| `default` | Tareas generales y mantenimiento | 4 |
| `reports` | Exportaciones y reportes (pueden ser lentos) | 2 |
| `notifications` | Notificaciones masivas (alta prioridad) | 2 |

---

## 7. Scheduler DB-driven

Para que Celery Beat lea los schedules de la DB (en lugar de un archivo estático), se implementa un scheduler personalizado.

### `itcj2/tasks/scheduler.py`
```python
from celery.beat import Scheduler, ScheduleEntry
from itcj2.database import SessionLocal
from itcj2.core.models.task_models import PeriodicTask

class DatabaseScheduler(Scheduler):
    """
    Lee PeriodicTask de la DB cada 30 segundos.
    Detecta cambios (is_active, cron_expression, etc.) sin reiniciar.
    """

    def setup_schedule(self): ...
    def update_from_dict(self, mapping): ...
    def tick(self): ...   # Override para recargar desde DB periódicamente
```

El scheduler relee la tabla cada `CELERY_BEAT_SYNC_EVERY = 30` segundos, detectando:
- Nuevas tareas agregadas desde la UI → las programa
- Tareas pausadas (`is_active=False`) → las remueve del schedule activo
- Cambios de `cron_expression` → actualiza la próxima ejecución

---

## 8. Redis Pub/Sub para notificaciones en tiempo real

**Problema:** Los workers de Celery corren en procesos separados y no tienen acceso al event loop de Uvicorn ni al servidor Socket.IO.

**Solución:** Redis Pub/Sub como puente entre procesos.

```
Celery Worker                    Uvicorn Backend
─────────────                    ───────────────
task finishes
  → redis.publish(               socket_io_subscriber (background task)
      "task_completed",            → recibe mensaje Redis
      {task_id, user_id, ...})     → llama sio.emit() al usuario
```

### Implementación

**En Uvicorn (`itcj2/main.py` — lifespan):**
```python
@asynccontextmanager
async def lifespan(app):
    # Al arrancar: iniciar subscriber de Redis
    asyncio.create_task(redis_task_subscriber())
    yield
    # Al apagar: cancelar task
```

**Subscriber:**
```python
async def redis_task_subscriber():
    """Escucha el canal 'task_events' y retransmite por Socket.IO."""
    async with aioredis.from_url(settings.REDIS_URL) as r:
        async with r.pubsub() as pubsub:
            await pubsub.subscribe("task_events")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await handle_task_event(data)
```

**En el worker (al completar tarea):**
```python
import redis
r = redis.from_url(settings.REDIS_URL)
r.publish("task_events", json.dumps({
    "type": "task_completed",
    "task_run_id": task_run.id,
    "task_name": "cleanup_attachments",
    "status": "SUCCESS",
    "user_id": triggered_by_user_id,
    "message": "Limpieza completada: 12 archivos eliminados"
}))
```

---

## 9. Vista de administración — `/config/system/tasks/`

### 9.1 Estructura de la UI

La vista se integra al panel de configuración existente (`config_base.html`), añadiendo una entrada en la sección "Sistema" del sidebar:

```
Configuración
└── Sistema
    ├── Aplicaciones
    ├── Roles Globales
    ├── Temáticas
    ├── Correo
    └── Tareas Programadas  ← NUEVO  (icono: bi-cpu)
```

### 9.2 Layout de la página `tasks.html`

La página tiene **3 pestañas** (tabs de Bootstrap):

#### Tab 1: "Catálogo de Tareas"
Muestra todas las `TaskDefinition` disponibles en el sistema.

```
┌─────────────────────────────────────────────────────────────────────┐
│  [🔄 Sincronizar tareas]                                            │
├──────────────┬──────────────────┬────────────┬─────────────────────┤
│ Nombre       │ App              │ Categoría  │ Acciones            │
├──────────────┼──────────────────┼────────────┼─────────────────────┤
│ Limpieza adj │ helpdesk         │ maintenance│ [▶ Ejecutar] [📅]   │
│ Notif. masiva│ core             │ notificatn │ [▶ Ejecutar] [📅]   │
│ Convertir doc│ helpdesk         │ document   │ [▶ Ejecutar] [📅]   │
│ Export reporte│ helpdesk        │ report     │ [▶ Ejecutar] [📅]   │
└──────────────┴──────────────────┴────────────┴─────────────────────┘
```

- **[▶ Ejecutar]**: Abre modal para ingresar parámetros y confirmar ejecución manual
- **[📅 Agendar]**: Abre modal para crear/editar un `PeriodicTask`

#### Tab 2: "Tareas Programadas"
CRUD de `PeriodicTask`.

```
┌─────────────────────────────────────────────────────────────────────┐
│  [+ Nueva tarea programada]                                         │
├────────────────────┬────────────────┬──────────────┬───────────────┤
│ Nombre             │ Schedule       │ Última ejecución│ Estado     │
├────────────────────┼────────────────┼──────────────┼───────────────┤
│ Limpieza diaria    │ 0 3 * * *     │ hace 2h       │ ●Activa [✏][🗑]│
│ Reporte semanal inv│ 0 8 * * 1     │ hace 5d       │ ●Activa [✏][🗑]│
│ Notif. inicio sem  │ 0 7 * * 1     │ hace 5d       │ ○Pausada[✏][🗑]│
└────────────────────┴────────────────┴──────────────┴───────────────┘
```

- Toggle de activar/pausar directamente en la tabla
- Editar: modal con campo cron + helper visual (descripción en lenguaje natural)
- "Próxima ejecución" calculada en frontend con `cronstrue.js`

#### Tab 3: "Historial de Ejecuciones"
Lista de `TaskRun` con filtros.

```
┌─────────────────────────────────────────────────────────────────────┐
│  [Todas las apps ▼] [Todos los estados ▼] [Últimos 7 días ▼]  [🔄]  │
├───────────────┬──────────────┬─────────┬───────────┬───────────────┤
│ Tarea         │ Disparador   │ Estado  │ Duración  │ Hace          │
├───────────────┼──────────────┼─────────┼───────────┼───────────────┤
│ Limpieza adj  │ Programada   │ ✅ OK   │ 1.2s      │ 2h [Ver]      │
│ Notif. masiva │ Manual:Admin │ ✅ OK   │ 3.4s      │ 5h [Ver]      │
│ Export rep.   │ Manual:Admin │ ❌ Error│ 0.1s      │ 1d [Ver]      │
│ Limpieza adj  │ Programada   │ ✅ OK   │ 0.9s      │ 1d [Ver]      │
└───────────────┴──────────────┴─────────┴───────────┴───────────────┘
```

- **[Ver]**: Expande o modal con detalles completos: args, result_json, error traceback, progress log
- Fila con estado `RUNNING`: muestra barra de progreso animada + botón [⛔ Cancelar]
- Auto-refresh cada 5 segundos cuando hay tareas `PENDING` o `RUNNING`

### 9.3 Modal "Ejecutar tarea"

```
┌─────────────────────────────────────────┐
│ Ejecutar: Limpieza de Adjuntos          │
│─────────────────────────────────────────│
│ Descripción: Elimina archivos expirados │
│ de tickets resueltos...                 │
│                                         │
│ Parámetros:                             │
│   [ ] Modo simulación (dry_run)         │
│                                         │
│ Esta tarea se ejecutará inmediatamente  │
│ en segundo plano.                       │
│                                         │
│          [Cancelar]  [▶ Ejecutar]       │
└─────────────────────────────────────────┘
```

### 9.4 Modal "Agendar tarea" (crear/editar `PeriodicTask`)

```
┌─────────────────────────────────────────┐
│ Nueva tarea programada                  │
│─────────────────────────────────────────│
│ Nombre: [________________________]      │
│ Tarea:  [Limpieza de Adjuntos      ▼]   │
│ Cron:   [0  ] [3  ] [*  ] [*  ] [*  ]  │
│         min  hora  día  mes   sem       │
│ → "Cada día a las 3:00 AM"              │
│                                         │
│ Descripción: [__________________]       │
│ [ ] Activar inmediatamente              │
│                                         │
│          [Cancelar]  [💾 Guardar]       │
└─────────────────────────────────────────┘
```

---

## 10. Endpoints API

Todos bajo el prefijo `/api/core/v2/tasks/` con permiso `core.config.admin`.

### TaskDefinitions
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/definitions` | Lista todas las TaskDefinition |
| `POST` | `/definitions/sync` | Reimporta tareas desde los módulos registrados |

### PeriodicTasks
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/periodic` | Lista todas las tareas programadas |
| `POST` | `/periodic` | Crea nueva tarea programada |
| `PATCH` | `/periodic/{id}` | Edita nombre, cron, args, descripción |
| `PATCH` | `/periodic/{id}/toggle` | Activa/pausa sin editar |
| `DELETE` | `/periodic/{id}` | Elimina tarea programada |

### TaskRuns (Historial)
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/runs` | Lista con filtros: `status`, `task_name`, `app`, `days`, paginación |
| `GET` | `/runs/{id}` | Detalle de una ejecución (con result_json completo) |
| `POST` | `/runs` | Dispara una tarea manualmente → crea TaskRun PENDING → encola en Celery |
| `DELETE` | `/runs/{id}/revoke` | Cancela una tarea PENDING o RUNNING (Celery revoke) |

---

## 11. Variables de entorno a agregar al `.env`

```bash
# Celery
CELERY_BROKER_URL=${REDIS_URL}         # Reutiliza REDIS_URL
CELERY_RESULT_BACKEND=${REDIS_URL}     # Redis para estado temporal
CELERY_WORKER_CONCURRENCY=4            # Workers por contenedor
CELERY_BEAT_SYNC_EVERY=30              # Segundos entre recarga de schedules desde DB
```

---

## 12. Migración de base de datos

Una sola migración Alembic que crea las 3 tablas nuevas:
- `task_definitions`
- `periodic_tasks`
- `task_runs`

Y el índice de búsqueda: `CREATE INDEX idx_task_runs_status ON task_runs(status, created_at DESC)`.

---

## 13. CLI — Nuevos comandos

Se añade el subgrupo `celery` al CLI existente en `itcj2/cli/main.py`:

```bash
# Sincronizar TaskDefinitions en la DB con las tareas registradas en el código
python -m itcj2.cli.main celery sync-tasks

# Ejecutar tarea manualmente desde CLI (útil para testing)
python -m itcj2.cli.main celery run cleanup-attachments --dry-run

# Ver estado de los workers activos
python -m itcj2.cli.main celery status
```

---

## 14. Plan de implementación por fases

### Fase 1 — Infraestructura base (sin UI aún)
1. Crear `itcj2/celery_app.py`
2. Crear `itcj2/tasks/base.py` (LoggedTask)
3. Crear modelos en `itcj2/core/models/task_models.py`
4. Generar y aplicar migración Alembic
5. Añadir servicios `celery-worker` y `celery-beat` en docker-compose
6. Implementar `itcj2/tasks/helpdesk_tasks.py` → tarea `cleanup_attachments`
7. Verificar que la tarea se ejecuta y registra en `TaskRun`

### Fase 2 — Scheduler DB-driven
1. Implementar `itcj2/tasks/scheduler.py` (DatabaseScheduler)
2. Añadir CLI `celery sync-tasks` para poblar `TaskDefinition`
3. Probar creación de `PeriodicTask` directamente en DB y que Beat la ejecuta

### Fase 3 — Implementar tareas restantes
1. `send_mass_notification` en `notification_tasks.py`
2. `convert_document` en `helpdesk_tasks.py`
3. `export_inventory_report` en `helpdesk_tasks.py`
4. Implementar Redis Pub/Sub subscriber en el lifespan de Uvicorn

### Fase 4 — Vista de administración
1. Crear endpoints API en `itcj2/core/api/tasks.py`
2. Crear página en `itcj2/core/pages/config/tasks.py`
3. Crear template `tasks.html` con las 3 pestañas
4. Agregar entrada "Tareas Programadas" al sidebar de `config_base.html`
5. Registrar rutas en `itcj2/routers.py`

---

## 15. Consideraciones técnicas importantes

### Celery + pgBouncer (transaction mode)
pgBouncer en modo transacción no soporta conexiones persistentes. Los workers de Celery **deben** crear y cerrar sesiones por tarea, lo cual SQLAlchemy ya maneja correctamente con `SessionLocal()` como context manager. No usar `scoped_session`.

### Una sola instancia de celery-beat
Beat debe correr siempre en **una sola instancia** para evitar que el mismo schedule se dispare múltiples veces. En producción con Blue-Green, beat no se duplica (no tiene perfiles de blue/green).

### Importación de modelos en workers
Los workers deben importar `itcj2.models` al arrancar (igual que el CLI) para que SQLAlchemy mapee todas las relaciones antes de ejecutar tareas.

### Tareas idempotentes
Las tareas deben ser seguras para re-ejecutarse si fallan a mitad (Celery puede reintentar). Por ejemplo, `cleanup_attachments` verifica si el archivo existe antes de intentar borrarlo.

### Timeouts
- `cleanup_attachments`: soft_time_limit=120s, hard_time_limit=150s
- `export_inventory_report`: soft_time_limit=300s, hard_time_limit=360s
- `send_mass_notification`: soft_time_limit=120s
- `convert_document`: soft_time_limit=60s

---

## 16. Dependencias a agregar en `requirements.txt`

```
celery[redis]==5.3.6
kombu==5.3.4          # Celery dependency, pinear para estabilidad
billiard==4.2.0       # Process pool (Celery dependency)
cronstrue             # No es Python, es JS para la UI (desde CDN)
```

> `redis` ya está en requirements. No se necesita flower (se tiene UI propia).

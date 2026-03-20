# AgendaTec — Gestion de Altas y Bajas de Materias

## Descripcion

**AgendaTec** es el sistema de gestion de solicitudes de altas y bajas de materias del ITCJ. Permite a los estudiantes solicitar cambios en su carga academica y agendar citas con coordinadores, con sincronizacion de horarios en tiempo real mediante WebSockets y bloqueo temporal de slots con Redis.

---

## Roles

| Rol | Descripcion |
|---|---|
| `student` | Crea solicitudes y consulta su estado |
| `social_service` | Verifica y valida solicitudes antes del coordinador |
| `coordinator` | Gestiona solicitudes asignadas y administra su disponibilidad |
| `admin` | Configuracion global, periodos academicos, reportes |

---

## Caracteristicas Principales

- **Solicitudes de baja (DROP)**: El estudiante solicita dar de baja una materia directamente
- **Solicitudes de cita (APPOINTMENT)**: El estudiante agenda una cita para tramitar alta o alta+baja
- **Mini-calendario interactivo**: Seleccion de fecha y slot de 10 minutos
- **Bloqueo en tiempo real**: Los slots se reservan temporalmente con Redis (TTL ~45 s) mientras el estudiante confirma
- **Periodos academicos**: Cada ciclo tiene fechas de admision, dias habilitados y configuracion propia
- **Notificaciones in-app**: Via WebSocket al actualizarse el estado de una solicitud
- **Encuestas de satisfaccion**: Al cerrar una solicitud el estudiante puede calificar la atencion
- **Reportes y estadisticas**: Panel de administracion con metricas por periodo

---

## URLs

| Tipo | Prefijo |
|---|---|
| API REST | `/api/agendatec/v2/` |
| Paginas HTML | `/agendatec/` |

### Modulos API

| Sub-ruta | Descripcion |
|---|---|
| `/requests` | CRUD de solicitudes del estudiante |
| `/slots` | Consulta y reserva de slots |
| `/availability` | Ventanas de disponibilidad por coordinador |
| `/programs` | Programas academicos y coordinadores |
| `/notifications` | Notificaciones del usuario |
| `/periods` | Consulta del periodo activo |
| `/social` | Endpoints para servicio social |
| `/admin/...` | Gestion administrativa (solicitudes, usuarios, stats, reportes, encuestas) |
| `/coord/...` | Panel del coordinador (citas, configuracion de dias, drops, cambio de contrasena) |

### Paginas HTML

| Ruta | Descripcion |
|---|---|
| `/agendatec/` | Landing / seleccion de rol |
| `/agendatec/student/` | Dashboard del estudiante |
| `/agendatec/coordinator/` | Dashboard del coordinador |
| `/agendatec/social/` | Dashboard de servicio social |
| `/agendatec/admin/` | Panel de administracion |
| `/agendatec/surveys/` | Encuestas de satisfaccion |

---

## Estructura de Directorios

```
agendatec/
├── router.py              # APIRouter principal (/api/agendatec/v2)
├── models/                # Modelos SQLAlchemy
│   ├── request.py         # Solicitudes de alta/baja
│   ├── appointment.py     # Citas agendadas
│   ├── coordinator.py     # Coordinadores por carrera
│   ├── time_slot.py       # Slots de 10 minutos
│   ├── availability.py    # Ventanas de disponibilidad
│   ├── period_config.py   # Configuracion por periodo
│   ├── notification.py    # Notificaciones
│   └── audit_log.py       # Auditoria de cambios
├── api/
│   ├── requests.py        # Solicitudes del estudiante
│   ├── slots.py           # Gestion de slots
│   ├── availability.py    # Disponibilidad
│   ├── programs.py        # Programas academicos
│   ├── notifications.py   # Notificaciones
│   ├── periods.py         # Periodo activo
│   ├── social.py          # Servicio social
│   ├── admin/             # Endpoints de administrador
│   └── coord/             # Endpoints de coordinador
├── pages/
│   ├── router.py          # APIRouter de paginas HTML
│   ├── student.py
│   ├── coordinator.py
│   ├── social.py
│   ├── admin.py
│   └── surveys.py
├── schemas/               # Pydantic validators
├── services/              # Logica de negocio
├── utils/                 # Helpers especificos
├── templates/agendatec/   # Templates Jinja2
└── static/                # CSS, JS (servidos por Nginx)
```

---

## Modelos de Base de Datos

Todas las tablas usan el prefijo `agendatec_`.

| Tabla | Descripcion |
|---|---|
| `agendatec_requests` | Solicitudes de alta/baja de materias |
| `agendatec_appointments` | Citas programadas entre estudiante y coordinador |
| `agendatec_coordinators` | Coordinadores y sus carreras asignadas |
| `agendatec_programs` | Programas academicos (carreras) |
| `agendatec_availability_windows` | Rangos de disponibilidad del coordinador |
| `agendatec_time_slots` | Slots individuales de 10 minutos |
| `agendatec_period_enabled_days` | Dias habilitados por periodo |
| `agendatec_period_config` | Configuracion de admision por periodo |
| `agendatec_notifications` | Notificaciones in-app |
| `agendatec_audit_logs` | Historial de cambios en solicitudes |

> Los periodos academicos (`core_academic_periods`) son un modelo del core compartido entre apps.

---

## Flujo de una Solicitud

```
Estudiante crea solicitud
        │
        ├── DROP directo      → PENDING → RESOLVED / CANCELED
        │
        └── APPOINTMENT
              │
              ├── Servicio social valida → VALIDATED
              │
              └── Coordinador atiende cita → RESOLVED / CANCELED
```

### Estados de Solicitud

| Estado | Descripcion |
|---|---|
| `PENDING` | Recien creada, esperando atencion |
| `VALIDATED` | Validada por servicio social |
| `ASSIGNED` | Asignada a un coordinador |
| `IN_PROGRESS` | El coordinador esta atendiendo |
| `RESOLVED` | Procesada exitosamente |
| `CANCELED` | Cancelada por el estudiante o el sistema |

---

## Periodos Academicos

Cada ciclo escolar se representa como un `AcademicPeriod` con:

- **Codigo**: formato `YYYYN` (ej: `20261` para Ene-Jun 2026)
- **Estado**: `ACTIVE`, `INACTIVE`, `ARCHIVED`
- **Configuracion**: fechas de admision de estudiantes, maximo de cancelaciones
- **Dias habilitados**: fechas especificas en las que se pueden agendar citas

Solo puede haber un periodo `ACTIVE` a la vez. Al activar uno, el anterior pasa a `INACTIVE`.

---

## WebSockets

AgendaTec usa Socket.IO para:

- Sincronizar disponibilidad de slots en tiempo real entre multiples estudiantes
- Notificar cambios de estado en solicitudes
- Bloquear temporalmente un slot mientras el estudiante confirma su reserva (soft-hold ~45 s via Redis)

Namespace: `/agendatec` (registrado en `itcj2/sockets/`)

---

## CLI — Comandos Disponibles

```bash
# Crear periodos academicos iniciales
python -m itcj2.cli.main agendatec seed-periods

# Activar un periodo especifico (desactiva el actual)
python -m itcj2.cli.main agendatec activate-period <id>

# Listar todos los periodos con conteo de solicitudes
python -m itcj2.cli.main agendatec list-periods

# Importar estudiantes desde CSV (no_de_control, apellidos, nombre, nip)
python -m itcj2.cli.main agendatec import-students --csv-path database/CSV/alumnos.csv

# Sincronizar estudiantes: importa + asigna rol student + desactiva los que ya no estan
python -m itcj2.cli.main agendatec sync-students-agendatec \
    --csv-path database/CSV/alumnos.csv \
    --deactivate-missing
```

> `sync-students-agendatec` acepta `--dry-run` para simular sin hacer cambios.

---

## Inicializacion

Los permisos y datos base de AgendaTec se cargan con:

```bash
python -m itcj2.cli.main core init-db
```

Los scripts DML especificos de AgendaTec estan en `database/DML/core/agendatec/` y `database/DML/agendatec/`.

---

## Permisos

Los permisos siguen el formato `agendatec.recurso.accion`. Se definen en `database/DML/core/agendatec/01_insert_permissions.sql` y se asignan a roles en `03_insert_role_permission.sql`.

Ejemplos:
- `agendatec.request.create` — Crear solicitudes
- `agendatec.request.view_all` — Ver todas las solicitudes (admin/coordinator)
- `agendatec.appointment.manage` — Gestionar citas (coordinator)
- `agendatec.period.manage` — Administrar periodos academicos (admin)

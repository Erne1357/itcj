# AgendaTec

## Overview

**AgendaTec** es una aplicación web responsive para gestionar solicitudes de altas y bajas de materias en un instituto. Los estudiantes pueden:
- Solicitar **baja** (DROP)
- Solicitar **cita** para alta o alta+baja (APPOINTMENT)
- Hacer **una única solicitud activa** a la vez

El sistema incluye:
- Coordinadores que atienden y actualizan el estado de las solicitudes y citas
- Personal de servicio social que filtra y verifica citas antes del acceso al coordinador
- Notificaciones en tiempo real
- Bloqueo temporal de horarios para evitar sobre-reservas

### Roles
1. **Student**: crea solicitudes, ve su estado, recibe notificaciones.
2. **Social Service**: consulta lista de citas para verificación.
3. **Coordinator**: gestiona bajas y citas, cambia estados.
4. **Admin**: (opcional) gestiona configuraciones globales.

### UI Features
- Diseño mobile-first con Bootstrap
- Flujo paso a paso: seleccionar carrera → mostrar info del coordinador → formulario
- Mini-calendario para elegir entre 3 días (25, 26, 27 agosto) y slots de 10 minutos
- Bloqueo de slots en tiempo real con WebSockets y Redis (soft-hold)
- Panel de notificaciones rápido

### Stack Tecnológico
- **Backend**: Flask (Python)
- **Frontend**: Bootstrap + JS
- **DB**: PostgreSQL
- **Tiempo real**: Flask-SocketIO + Redis
- **Contenerización**: Docker
- **Despliegue**: multi-contenedor con DB, app, Redis

---

## Database Structure

### Core Concepts
- Cada usuario tiene un rol (`student`, `social_service`, `coordinator`, `admin`).
- `requests` almacena tanto bajas como citas.
- `appointments` se enlaza a solicitudes de tipo `APPOINTMENT`.
- `time_slots` se pre-generan a partir de `availability_windows`.
- Soft-holds de slots se manejan en Redis.

### Main Tables
- **roles**: catálogo de roles.
- **users**: todos los usuarios; `control_number` (8 dígitos), `nip_hash`, FK a `roles`.
- **programs**: carreras.
- **coordinators**: datos del coordinador, vinculado a un `user`.
- **program_coordinator**: relación carrera–coordinador.
- **availability_windows**: ventanas de atención por coordinador/día.
- **time_slots**: slots reservables, únicos por coordinador y hora.
- **requests**: solicitudes de baja/cita, una `PENDING` por alumno (enforced en DB).
- **appointments**: citas ligadas a solicitudes tipo `APPOINTMENT`.
- **notifications**: notificaciones in-app.
- **audit_logs**: registro de acciones.

### Relationships & Cascades
- Muchas relaciones con `ON DELETE CASCADE` para limpieza coherente.
- `roles → users` usa `ON DELETE RESTRICT`.
- Coordinadores borran disponibilidad, slots y citas asociadas.
- Programas borran solicitudes y citas asociadas.

### Enums
- `request_type_enum`: `DROP` / `APPOINTMENT`
- `request_status_enum`: `PENDING`, `RESOLVED_SUCCESS`, `RESOLVED_NOT_COMPLETED`, `NO_SHOW`, `ATTENDED_OTHER_SLOT`, `CANCELED`
- `appointment_status_enum`: `SCHEDULED`, `DONE`, `NO_SHOW`, `CANCELED`

### Triggers
- `set_updated_at()`: actualiza `updated_at` automáticamente en `UPDATE` para tablas clave.

---

## Development Modules Plan

### Módulo 0 — Base del proyecto (Día 1)
- Stack en Docker: Postgres, Redis, Backend (Flask+Gunicorn+Eventlet), Nginx
- `.env` y healthcheck `/health`

### Módulo 1 — Autenticación y Roles (Día 1–2)
- `/auth/login`, `/auth/me`
- Login con `control_number` + NIP
- Middleware `@role_required`

### Módulo 2 — Catálogos (Día 2)
- `/programs`
- `/programs/:id/coordinator`

### Módulo 3 — Disponibilidad y Slots (Día 2–3)
- Semilla de ventanas (25–27 ago)
- Script `generate_slots.py`
- `/availability/program/:id/slots`

### Módulo 4 — Solicitudes (Día 3–4)
- `/requests/mine`, POST, cancel
- Reserva atómica de slot
- Una sola `PENDING` por alumno

### Módulo 5 — Sockets + Soft-Hold (Día 4–5)
- Eventos: `join_day`, `slots_snapshot`, `hold_slot`, `release_hold`, `reserve_slot`
- TTL 45s en holds con Redis

### Módulo 6 — Panel Coordinador (Día 5–6)
- `/coord/drops`
- `/coord/appointments`
- Cambios de estado

### Módulo 7 — Panel Servicio Social (Día 6)
- `/servicio/appointments` por día/carrera

### Módulo 8 — Notificaciones In-App (Día 7)
- Servicio de creación de notificaciones
- `/notifications/mine`

### Módulo 9 — Seguridad y Validaciones (Día 7–8)
- Rate-limits
- Validación de relaciones (slot pertenece a programa)

### Módulo 10 — UX Mobile (Día 8)
- Ajustes responsive, toasts, loaders

### Módulo 11 — Seeders y Datos Demo (Día 8)
- `seed_dev.py` con datos iniciales

### Módulo 12 — Logs/Auditoría (Día 9)
- Registro de cambios clave

### Módulo 13 — QA (Día 9–10)
- Unit, E2E, concurrencia

### Módulo 14 — Despliegue (Día 10–11)
- Nginx con WebSockets
- Configuración segura

### Módulo 15 — Extras (si hay tiempo)
- Emails de confirmación
- PDF acuse para DROP
- Reprogramación de citas

---

## Quick Start (dev)

```bash
docker compose up --build

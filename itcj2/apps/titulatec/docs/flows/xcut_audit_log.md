# Bitácora de auditoría: quién hizo qué, cuándo y con qué antes/después

> **Objetivo:** que un administrador pueda reconstruir cualquier cambio de TitulaTec (quién, cuándo, desde dónde, antes y después) sin entrar a la base, con un registro que nadie puede reescribir.

| | |
|---|---|
| **Actor(es)** | 🤖 el sistema escribe (toda acción de cualquier actor); el rol `admin` de TitulaTec lee |
| **Permiso(s)** | `titulatec.audit.page.list` (las 3 rutas; solo `admin`) |
| **Trigger** | cualquier mutación de TitulaTec (HTTP, CLI o Celery); para leer, la pestaña «Bitácora» o el enlace del expediente |
| **Precondiciones** | tabla `titulatec_audit_log` migrada (`tt20261007b`) ANTES de servir tráfico; permiso sembrado con `titulatec init-bitacora` |
| **Sub-flujos** | ninguno; la escucha acompaña a los demás flujos (p. ej. [motor de avance](engine_approve_advance_phase.md) deja `process.*`) |
| **Estado final** | filas nuevas en `titulatec_audit_log`, inmutables; salen de ahí solo por `titulatec audit-purge` |

## Ruta en la app (UI)

1. Menú admin → **Bitácora** (`/titulatec/admin/bitacora`; solo `admin`). Por omisión, últimos 7 días, sin cambios de datos.
2. Filtros arriba (desde, hasta, módulo, acción, quién, alumno —nº de control, nombre o folio del proceso—, expediente, texto del motivo, «Incluir cambios de datos»): repintan solo `#tt-audit-body` por HTMX (`GET /body`); los filtros viven fuera del swap.
3. Clic en una fila → detalle (`GET /entry/{id}`): antes/después, payload, huella de la petición (IP, navegador, ruta, `request_id`) y las filas hermanas del mismo `request_id`. «Ocultar detalle» lo pliega (y entonces dice «Ver detalle»); abrirlo no aprieta las columnas de la tabla.
4. Desde el detalle de un expediente, el enlace a la bitácora (`?process_id=`) abre TODO su historial, sin ventana de 7 días: sus filas más las de su solicitud de inscripción (aprobar, rechazar, reabrir, devolver, reenviar liga), que no llevan `process_id` pero sí el nº de control del alumno en `subject_label`.

## Secuencia

```mermaid
sequenceDiagram
    actor U as Actor (HTTP / CLI / Celery)
    participant SVC as Service
    participant CTX as audit_context
    participant LST as audit_listeners (after_flush)
    participant DB as Postgres
    U->>SVC: operación de negocio
    SVC->>SVC: valida (puede lanzar)
    SVC->>CTX: AuditService.record(db, "codigo", ...)
    Note over SVC,CTX: db.add de una fila source='action'; sin flush ni commit
    SVC->>DB: db.commit() ⇒ flush
    LST->>LST: espejo de ProcessEvent + red ORM (solo estado cargado)
    LST->>DB: INSERT multi-fila (source='process_event' / 'data')
    DB->>DB: trigger: UPDATE/DELETE/TRUNCATE rechazados
    Note over DB: rollback del cambio ⇒ se va también su rastro
```

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Notif |
|---|---|---|---|---|---|---|---|
| 1 | 🤖 | cualquier flujo | acción explícita con semántica de negocio | la del flujo | `AuditService.record(db, "<código>", ...)` antes del `commit` | `titulatec_audit_log` ← fila `source='action'` | — |
| 2 | 🤖 | cualquier flujo | espejo de cada `ProcessEvent` nuevo | la del flujo | `audit_listeners` (`after_flush`) | fila `source='process_event'`, `action='process.<event_type>'` | — |
| 3 | 🤖 | cualquier flujo | red ORM: fila nueva/modificada/borrada de una tabla `titulatec_*` | la del flujo | `audit_listeners` (`after_flush`) | fila `source='data'`, `data.insert/update/delete` con diff | — |
| 4 | 🤖 | CLI | cada comando de `titulatec_cli` corre en `audit_context("cli")` | — | `_AuditedCommand.invoke` | fila `system.cli_command` (commit propio) | — |
| 5 | 🤖 | Celery | cada tarea abre `audit_context("celery", label=...)` | — | `tasks/titulatec_tasks.py` | filas con `actor_kind='celery'` | — |
| 6 | 🛠️ `admin` | `/titulatec/admin/bitacora` | consulta con filtros | `GET /titulatec/admin/bitacora`, `GET .../body` | `pages/audit_admin.py` | solo lectura | — |
| 7 | 🛠️ `admin` | detalle de fila | ver antes/después y hermanas | `GET /titulatec/admin/bitacora/entry/{id}` | `pages/audit_admin.py::entry` | solo lectura (404 si el id no existe o excede BIGINT) | — |
| 8 | operador | consola | purga por antigüedad | — | `titulatec audit-purge --before ...` | `DELETE` bajo `SET LOCAL titulatec.audit_purge='on'` + fila `system.audit_purged` | — |

## Estado resultante

- `titulatec_audit_log`: una fila por cosa que pasó. Columnas clave: `occurred_at` (hora local naive), `source` (`action|process_event|data`), `action`, `module`, `actor_id`/`actor_kind` (`user|public|system|cli|celery`)/`actor_label`, `entity_type`/`entity_id`, `process_id`, `subject_label`, `reason`, `before`/`after`/`payload` (JSON; `None` es NULL de SQL), `request_id`, `ip`, `user_agent`, `route`. Sin FKs (sobrevive al borrado de usuarios y procesos).
- Vocabulario cerrado en `services/audit_actions.py` (`AUDIT_ACTIONS`, 18 módulos); las tablas nuevas se clasifican en `TABLE_MODULES`/`TABLE_LABELS` o `NET_EXCLUDED_TABLES`.
- Costo: +1 sentencia por flush con escrituras titulatec (+2 si hay filas de `record`); 0 en lecturas.

## Caminos alternos / errores ❗

- **Falla después de `record()` y antes del commit** → rollback: el rastro se va con el cambio (no hay «aprobado» fantasma). Si el llamador commitea la misma sesión tras capturar la excepción, la fila pendiente persiste: por eso `record` va después de las validaciones que pueden lanzar.
- **Sin petición HTTP** (Celery, CLI, script) → el contexto cae en `cli`/`celery`/`system`, sin tronar. Un `threading.Thread` crudo no hereda las ContextVars y cae en `system`.
- **Columnas sensibles** (`password`, `nip`, `token`, `secret`, `hash`) → `"***"` en `payload`, `before`, `after` y en la red.
- **Fuera de la red**: `query().update()/.delete()` masivos, `bulk_*`, `text(...)` y DML; tablas del core; `NET_EXCLUDED_TABLES` (`titulatec_audit_log`, `titulatec_process_events`, `titulatec_email_outbox` y las 3 tablas de contenido de la encuesta: PII). Lo que importe de esas vías lleva `record` explícito.
- **Un error de Python al armar UNA fila** → se loguea y esa fila se omite; la operación sigue. Un código fuera de `AUDIT_ACTIONS` lanza `ValueError` solo en pruebas/dev.
- **Filtros HTMX vacíos** (`process_id=`) → se parsean a mano como `str`; nunca 422. Un valor fuera de catálogo se ignora.
- **Atributo asignado sin leerlo tras un commit** (producción expira al commitear) → la red no sabe el valor previo: la llave se omite de `before` (nunca un `null` que diga «estaba vacío»). Reasignar el mismo valor conocido no deja fila.
- **Error de un comando de consola** → `system.cli_command` guarda la clase y la primera línea del mensaje, sin `[SQL: …]`/`[parameters: …]` ni el `DETAIL` de la BD, enmascarada si nombra un secreto.
- **Altas por solicitud** (`_create_account`, liga de activación) → no dejan `import.students_committed` (es solo de CSV y alta manual); `import.roles_synced` solo para cuentas que ya existían.
- **Intento de `UPDATE`/`DELETE`/`TRUNCATE`** → el trigger `titulatec_audit_log_guard()` lo rechaza; `DELETE`/`TRUNCATE` solo pasan con `SET LOCAL titulatec.audit_purge = 'on'`.
- **`audit-purge`**: corte más reciente de 365 días exige `--force`; `--archive` (JSONL, antes de borrar) rechaza un archivo existente; si lo archivado ≠ lo borrado se revierte todo; `--dry-run` solo cuenta; deja `system.audit_purged`. **El archivo va a un volumen montado**: el comando corre dentro del contenedor del backend y cada deploy lo recrea, así que un JSONL fuera de un montaje (la única copia de lo purgado) se pierde. En producción: `--archive /app/instance/audit_archive/<nombre>.jsonl` (bind mount de `instance/`; la carpeta se crea sola) y luego copiarlo fuera del servidor. `/app/database` es de solo lectura.

## Despliegue (orden obligatorio)

1. `alembic upgrade head` (`tt20261007b`) **antes** de que el código sirva tráfico: sin la tabla, toda escritura de TitulaTec falla. Hace backfill del historial de `titulatec_process_events`.
2. Copiar `database/DML/titulatec/audit_2026_10/` al servidor y `python -m itcj2.cli.main titulatec init-bitacora --dry-run` → sin `--dry-run`. Corre SOLO el `25_insert_audit_perm.sql` (permiso `titulatec.audit.page.list` + concesión EXPLÍCITA a `admin`); **nunca re-corre el `15_grant_admin_all_perms.sql`**, que en producción no se re-ejecuta (concede todo titulatec a `admin`).
3. Recrear los workers de Celery.

## Reversa (en este orden)

1. **Primero** `./docker/scripts/rollback.sh`: el código viejo no trae la escucha y deja de escribir en la tabla.
2. **Después**, desde la imagen NUEVA (la vieja no conoce la revisión), `alembic -c migrations/alembic.ini downgrade tt20261007a`. Al revés, con el código nuevo sirviendo y la tabla ya borrada, **toda** escritura de TitulaTec falla. El downgrade borra la bitácora (el historial de procesos sigue en `titulatec_process_events`); para conservarla, exportarla antes a `/app/instance/...` o fuera del contenedor.

## Flujos relacionados

- ⤵ [Motor de avance de fase](engine_approve_advance_phase.md) — sus `ProcessEvent` se espejan como `process.*`.
- ⤵ [Expediente del admin](xcut_admin_process_expediente.md) — trae el enlace «Ver bitácora» con `?process_id=`.
- ⤵ [Pestaña «Correos»](xcut_mail_outbox_admin.md) — la bandeja de correo es su propio registro y no pasa por la red.
- Código y reglas para código nuevo: `itcj2/apps/titulatec/CLAUDE.md` §20.

# Elegibilidad automática contra el SII (transversal, modo `sii`)

> **Objetivo:** que una solicitud de inscripción pública se decida sola contra la base del **SII**
> (fuente de verdad, Sybase): el sistema consulta, dice si la persona es **apta** y **por qué**, y
> si lo es la aprueba sin que nadie la toque. Servicios Escolares conserva el control: interruptor
> por convocatoria, bandeja con los motivos de lo no apto, y **revocar** una inscripción aprobada.

| | |
|---|---|
| **Actor(es)** | 🤖 tarea celery + barrido periódico (consulta y aprobación automática) · 🏛️ Servicios Escolares (bandeja de Solicitudes, interruptor, reconsultar, aprobar como excepción, revocar) · 👤 visitante (formulario público, sin cambios) |
| **Permiso(s)** | Ninguno nuevo. Bandeja: `titulatec.enrollment_request.page.list` · aprobar y **«Reintentar consulta»**: `titulatec.enrollment_request.api.approve` · rechazar: `titulatec.enrollment_request.api.reject` · interruptor: `titulatec.cohort.api.update` (el mismo panel de la ventana) · revocar: `titulatec.process.api.cancel` (desde 2026-09-25 también en `titulatec_school_services` y `titulatec_school_services_head`, `03_insert_role_permissions.sql`) |
| **Trigger** | El commit del alta pública (`EnrollmentRequestService.create`) encola `titulatec.sii_check_request(req_id)`; la periódica `titulatec.sii_sweep` (cada 10 min) recoge lo que quedó atrás. |
| **Precondiciones** | `TITULATEC_ENROLLMENT_REVIEWER=sii` y `TITULATEC_SII_BACKEND` = `fake` u `odbc`. Reglas en `TITULATEC_SII_RULES_DIR` (default `database/SII/titulatec/`, gitignored). Solicitud en `pending_review`. |
| **Sub-flujos** | ⤵ [Inscripción pública con revisión previa](xcut_public_enrollment.md) (formulario, liga, correos, rol `graduate`) · ⤵ [Formato de las reglas del SII](../sii_rules_format.md) · ⤵ `EnrollmentRequestService._approve_locked` (el MISMO núcleo que aprueba desde la bandeja) · ⤵ `ProcessService.cancel` (revocar) |
| **Estado final** | Apta y sin frenos → `converted` (cuenta nueva con el NIP del SII) o `approved` (ya tenía cuenta: liga de 21 días). No apta / error / frenada → sigue `pending_review` con el veredicto y el motivo a la vista de SE. |

Los modos `school_services` (oficial, por omisión) y `computer_center` (alterno) **no cambian**:
todo lo de este archivo solo corre con `reviewer_mode() == "sii"`. `reviewer_label()` en modo `sii`
es «Servicios Escolares» (quien firma el correo de rechazo).

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Configuración | `itcj2/config.py` | 8 settings `TITULATEC_SII_*` (ver [Configuración](#configuración)). Se leen **solo** por métodos estáticos: `SiiConfig` (`services/sii/client.py`) y `EligibilityService.delay_hours()/max_attempts()`. |
| Conector | `services/sii/client.py` | `get_sii_client()` → `OdbcSiiClient` (`pyodbc` importado **perezosamente**, FreeTDS, solo lectura, timeouts, parámetros `?`) · `FakeSiiClient` (JSON local) · `disabled` lanza `SiiUnavailable`. Errores: `SiiUnavailable` (reintentable) vs `SiiQueryError`/`SiiRulesError` (configuración). Mensajes sin cadena de conexión ni valores de fila. |
| Motor de reglas | `services/sii/rules.py` | `RuleSet.load/validate/evaluate/fetch_credential`. Formato: [`sii_rules_format.md`](../sii_rules_format.md) (no se duplica aquí). |
| Modelo | `models/eligibility_check.py` | `titulatec_eligibility_checks` (una fila por intento) · `titulatec_enrollment_requests.last_check_id` (la vigente) · `titulatec_cohorts.sii_auto_approve` (interruptor, `server_default true`). Migraciones `tt20260925a` + `tt20260925b` (columna `retryable`). |
| Servicio | `services/eligibility_service.py` | `EligibilityService.check / auto_approve / sweep / latest_check`, `enqueue_check`, `fetch_sii_nip`. |
| Tareas | `itcj2/tasks/titulatec_tasks.py` | `titulatec.sii_check_request(req_id, attempt, force)` y `titulatec.sii_sweep()`. |
| Periódica | `database/DML/titulatec/sii_2026_09/16_insert_sii_sweep_task.sql` (gitignored, plegado a `SEED_FILES` antes del `15`) | `core_task_definitions` + `core_periodic_tasks` «TitulaTec: barrido de elegibilidad del SII», `*/10 * * * *`, activa en todos los entornos (fuera del modo `sii` no hace nada). |
| Bandeja | `pages/requests_admin.py` + `partials/requests_body.html` | Veredicto por fila, motivos, discrepancias, «Reintentar consulta» (`POST /{req_id}/reconsultar`), píldora «Aprobada automáticamente (SII)». |
| Interruptor | `pages/admin.py::cohort_window` + `partials/cohort/cohort_window.html` | Switch «Aprobación automática (SII)» en el panel de la ventana, solo en modo `sii`. |
| CLI | `itcj2/cli/titulatec.py` | `sii-ping`, `sii-rules-validate`, `sii-check`, `sii-sweep`. |

## Ruta en la app (UI)

1. 👤 `/titulatec/inscripcion` → el formulario y la tarjeta de «Recibimos tu solicitud» **no cambian**
   (indistinguibilidad E8: la consulta es asíncrona, la respuesta pública no depende del SII).
2. 🏛️ Convocatoria › pestaña **Resumen** › panel de la ventana → switch **«Aprobación automática (SII)»**
   (encendido por omisión). En solo lectura muestra «encendida/apagada». Se guarda con el mismo
   botón que la ventana, en **un solo commit** con ella.
3. 🏛️ `/titulatec/admin/solicitudes` › **Por revisar** → cada fila `pending_review` trae el bloque
   `#tt-req-sii-<id>`: estado (Sin consultar / Consultando… / Consultando… sin respuesta desde … /
   Apta / No apta / Error de consulta), reglas incumplidas con su motivo (las cumplidas plegadas),
   discrepancias de identidad formulario↔SII, «SII · intento N de M», y el **por qué** una apta sigue
   ahí (nota, interruptor apagado, convocatoria no abierta, ventana de veto con fecha, «se aprobará
   sola en el siguiente barrido»). Botón **«Reintentar consulta»** (o «Consultar al SII» si nunca se
   consultó), oculto mientras hay una consulta en curso.
4. 🏛️ Misma fila → **«Aprobar y crear cuenta»** (sin cuenta: nace con el NIP del SII, el correo no lo
   lleva) / «Aprobar y enviar liga» (con cuenta) / **Rechazar**. En modo `sii` no existe «pasar a Cómputo».
5. 🏛️ Pestañas **Liga enviada / Inscritas / Todas** → píldora **«Aprobada automáticamente (SII)»**.
   KPIs, «Por año de ingreso» y todas las pestañas siguen como en el modo oficial (decisión S9).
6. 🏛️ **Revocar inscripción** (motivo obligatorio): en el expediente (`#exp-revocar-abrir` → modal
   `#exp-modal-revocar`) y en Solicitudes › Inscritas. Ver [Revocar](#revocar-inscripción).

## Secuencia

```mermaid
sequenceDiagram
    actor V as 👤 Visitante
    participant P as pages/public.py
    participant S as EnrollmentRequestService
    participant Q as Celery (titulatec.sii_check_request)
    participant E as EligibilityService
    participant SII as SII (odbc | fake)
    participant DB as Postgres
    participant M as Correo
    V->>P: POST /titulatec/inscripcion
    P->>S: create()
    S->>DB: INSERT solicitud (pending_review) · COMMIT
    S-)Q: enqueue_check(req_id) (send_task, best-effort)
    P-->>V: «Recibimos tu solicitud» (igual que siempre)
    Q->>E: check(db, req_id, attempt)
    E->>DB: lock + refresh · INSERT check (pending) · last_check_id · COMMIT
    E->>SII: RuleSet.evaluate (sin lock ni transacción)
    SII-->>E: Verdict(status, results, facts, identity, rules_version)
    E->>DB: lock + refresh · check ← apt | not_apt | error (+retryable) · COMMIT
    alt apt ∧ delay_hours == 0
        E->>E: auto_approve(): revalida bajo lock
        alt sin cuenta
            E->>SII: fetch_credential (NIP, modo sensible)
            E->>DB: _approve_locked: cuenta (hash_nip) + import_rows · converted · COMMIT
            E->>M: «entra con tu número de control y tu NIP del SII» (sin NIP)
        else con cuenta
            E->>DB: _approve_locked: token 21 días · approved · COMMIT
            E->>M: liga de activación → correo personal
        end
    else not_apt | error | frenada
        Note over E,DB: queda pending_review; SE ve el veredicto y el motivo
    end
    Note over Q: error reintentable → self.retry con backoff hasta TITULATEC_SII_MAX_ATTEMPTS
```

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint / tarea | Service · método | Efecto en BD | Eventos / Correo |
|---|---|---|---|---|---|---|---|
| 1 | 👤 | `/titulatec/inscripcion` | Enviar el formulario | `POST /titulatec/inscripcion` | `EnrollmentRequestService.create` → `eligibility_service.enqueue_check(req.id)` **tras el commit** | solicitud `pending_review` | Encola `titulatec.sii_check_request` por nombre (`send_task`, `retry=False`): el web no importa el módulo de tareas; con el broker caído, lo recoge el barrido |
| 2 | 🤖 | celery | Consultar | `titulatec.sii_check_request(req_id, attempt=1, force=False)` | `EligibilityService.check` | fase ①: fila `pending` + `last_check_id`; fase ③: `status`, `rules_version`, `results`, `facts`, `identity_mismatch`, `error`, `retryable`, `finished_at`, `duration_ms` | Reintento con `self.retry` (60 s × 2^(n-1), tope 1 h) **solo** si `retryable` y `attempt < max_attempts()` |
| 3 | 🤖 | — | Aprobar sola | (dentro de `check` si `delay_hours() == 0`, o del barrido) | `EligibilityService.auto_approve` → `EnrollmentRequestService._approve_locked(actor_id=None)` | sin cuenta → `converted` (`core_users` con `hash_nip(NIP del SII)`, `must_change_password=False`, proceso); con cuenta → `approved` + token. `reviewed_by_id = NULL`, `reviewed_at` lleno | `ProcessEvent(enrollment_self_service)` con `auto: true`, `rules_version`, `check_id`, `nip_source: "sii"` (con cuenta, lo escribe `_convert` al abrir la liga); correo **después** del commit |
| 4 | 🤖 | beat | Barrer | `titulatec.sii_sweep()` cada 10 min (`soft_time_limit=540`, presupuesto 480 s) | `EligibilityService.sweep` | ver [Barrido](#barrido-periódico) | — |
| 5 | 🏛️ | Solicitudes, fila `pending_review` | Reintentar consulta | `POST /titulatec/admin/solicitudes/{id}/reconsultar` (`api.approve`) | `enqueue_check(req.id, force=True)` | nada propio (la fila la abre la tarea bajo lock) | 200 + parcial + `X-Tt-Notice` «Consulta al SII solicitada: el veredicto aparece al terminar.» |
| 6 | 🏛️ | Solicitudes | Aprobar como excepción (no apta, error, interruptor apagado) | `POST …/{id}/aprobar` | `approve` → `_approve_locked(actor_id=…)` | sin cuenta: **re-consulta el NIP al SII** (el del formulario se ignora) | Si el SII no lo da o no responde → 400 «No se pudo obtener el NIP del SII.» sin escribir |
| 7 | 🏛️ | Solicitudes | Rechazar | `POST …/{id}/rechazar` | `reject` | igual que el modo oficial | `send_enrollment_rejected`, firmado «Servicios Escolares» |
| 8 | 🏛️ | Resumen de la convocatoria | Interruptor | `POST /titulatec/admin/cohorts/{id}/ventana` (`cohort.api.update`) | `cohort_window` marca `cohort.sii_auto_approve` antes de `CohortService.set_window` → un solo commit | `titulatec_cohorts.sii_auto_approve` | `logger.info` con convocatoria, estado nuevo y actor |

## Estado resultante

- `titulatec_eligibility_checks`: una fila por intento; la vigente es `last_check_id`.
  `status` ∈ `pending | apt | not_apt | error`. `results = [{rule, ok, message}]`; `facts` = solo las
  columnas de la lista blanca `[facts]`; **nunca** la columna ni la consulta de `[credential]`.
- `retryable` (Boolean, nullable): `true` si el `error` fue `SiiUnavailable` (SII caído, backend
  `disabled`, cadena vacía); `false` si es de configuración (reglas que no cargan, SQL inválido,
  columna faltante); `NULL` fuera de `error`.
- Aprobada sola = `reviewed_by_id IS NULL` ∧ `reviewed_at` lleno ∧ vigente `apt`
  (`_auto_approval_marker`; la píldora de la bandeja usa la misma función).

## Cuándo la aprobación automática NO procede ❗

`auto_approve` revalida **bajo el lock** de la solicitud, en este orden; si una falla no escribe
nada (o deja nota, donde se indica):

| Freno | Resultado |
|---|---|
| Modo distinto de `sii` | nada |
| La solicitud ya no está `pending_review` | nada |
| La consulta vigente no es `apt` | nada: queda «Por revisar» con los motivos |
| Dentro de la ventana de veto (`TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS` desde `finished_at`) | nada; el barrido la aprueba al vencer |
| Convocatoria no `open` (`_cohort_gate`, D5) | nada |
| Interruptor `sii_auto_approve` apagado | nada: SE decide a mano |
| **Nombre del formulario distinto al del SII** (`identity_mismatch` en nombre/apellidos, sin acentos ni mayúsculas) | nota «El nombre del formulario no coincide con el del SII (…); confirma que la solicitud sea de esa persona antes de aprobarla.» — solo etiquetas, nunca valores. Una **carrera** distinta NO frena (el SII la abrevia); se muestra a SE |
| **El SII no tiene NIP** (0 filas o columna vacía) | nota «El SII no devolvió NIP.» |
| La consulta del NIP falla por configuración (`SiiRulesError`, `SiiQueryError`, otro) | nota «No se pudo leer el NIP en el SII (Tipo): revisa [credential] …» |
| El SII no responde al pedir el NIP (`SiiUnavailable`) | nada, **sin nota**: el barrido reintenta |
| NIP con otro formato (≠ 4 dígitos), D5, cuenta sin contraseña, datos inválidos, inscripción revocada en esta convocatoria, fallo al crear la cuenta | nota con el motivo de `_approve_locked` |

La **nota** (`review_note`) es la marca de «necesita a una persona»: el barrido ya no toma esa
solicitud. SE la resuelve aprobando, rechazando o con «Reintentar consulta».

Sin `[identity]` en las reglas no hay nada que comparar y la aprobación procede: **en producción
conviene declarar `[identity]`**.

## Barrido periódico

`EligibilityService.sweep` sobre `pending_review` (lotes de 200, ordenados por id; cada solicitud en
su transacción, la que revienta se registra por **tipo** y no detiene a las demás):

- sin consulta vigente → primera consulta (`checked`);
- vigente `error` con `retryable` y `attempt < max_attempts()`, o `pending` colgada (> 15 min,
  `_PENDING_STALE`) con `attempt < max_attempts()` → siguiente intento (`retried`);
- vigente `apt`, ventana vencida, sin `review_note`, convocatoria `open` e interruptor encendido →
  `auto_approve` (`approved`).

Manual: `python -m itcj2.cli.main titulatec sii-sweep [--cohort ID]` (solo en modo `sii`; imprime
los conteos).

## Concurrencia

- Transiciones con `pg_advisory_xact_lock(_REQUEST_LOCK_NS, id)` + `db.refresh` antes de leer el
  estado. La consulta al SII corre **sin** lock ni transacción abierta (lock → commit → SII → lock →
  commit); el NIP sí se pide con el lock tomado (una sola consulta).
- Una `pending` de menos de 15 min = otra tarea consultando: no se duplica, ni con `force`.
- Sin `force` no se repite un intento ya hecho (`vigente.attempt >= attempt`) ni se pasa del tope.
  Una tarea que llega antes de que el commit del alta sea visible no encuentra la solicitud y no
  hace nada; el barrido la recoge.
- La bandeja rechaza «Reintentar consulta» con 400 «Ya se está consultando al SII; espera el
  resultado.» si la vigente está en curso (misma regla `_in_flight` que el servicio, fijada por
  `test_la_bandeja_y_el_servicio_coinciden_en_que_es_una_consulta_en_curso`).

## El NIP del SII

Vive **solo en memoria** entre `fetch_credential` (un `Secret` cuyo `repr`/`str` es `****`) y
`hash_nip`: jamás en BD en claro, log, `X-Tt-Error`, correo, payload, `facts`, `results` ni salida de
CLI. La consulta de `[credential]` corre en modo **sensible** (errores del driver reducidos a tipo +
SQLSTATE). El correo de cuenta nueva dice «Entra con tu número de control y tu NIP del SII»; la
celda de NIP dice «Tu NIP del SII».

## Revocar inscripción

`ProcessService.cancel(db, process_id, *, reason, actor_id)` es la **única** escritura de
`TitulationProcess.status = 'cancelled'`:

- revocables: `active` y `on_hold`; `cancelled` → 400 «Esta inscripción ya estaba revocada.»
  (idempotente, sin evento ni correo); `completed` → 400; motivo obligatorio (≤ 2000).
- toma el advisory de citas del proceso (`SlotService._lock_process`) **antes** del `FOR UPDATE` de
  la fila (orden anti-deadlock con agendar); cancela la cita vigente si está `scheduled`/`confirmed`
  (libera la franja, en la misma transacción, sin su propio aviso);
- evento `process_cancelled` (payload `reason`, `previous_status`, `appointment_cancelled`), aviso en
  la app, y **después del commit** `send_process_cancelled` al institucional y al personal — sin
  motivo, folio ni número de control (el motivo se lee en la plataforma con sesión);
- el alumno conserva `graduate`: en su dashboard ve «Tu inscripción fue cancelada: motivo» en lugar
  de la fase actual.

Rutas: `POST /titulatec/admin/processes/{process_id}/cancelar` (expediente; `assert_process_in_scope`,
404 liso fuera de carrera) y `POST /titulatec/admin/solicitudes/{req_id}/revocar` (formulario
«Revocar inscripción» de Solicitudes › Inscritas; `titulatec.process.api.cancel`, alcance por
carrera de la bandeja con `_load_scoped_request`; revoca `converted_process_id`).

**Decisión por sitio de los lectores de `TitulationProcess.status`** (barrido de la Task 6; detalle
completo en la máquina de estados): excluidas de Por agendar, En revisión de GTV, Liberados/CSV,
resumen de la convocatoria, kanban y agenda; **etiquetadas** «Revocado» en la bandeja de Procesos,
la pestaña Alumnos y el expediente (banner con motivo); **bloqueadas** en las guardas de fase y al
agendar/reagendar (`EnrollmentRevoked`, también dentro del lock); reabrir una convocatoria no las
resucita.

**D1 — sin readmisión en la misma convocatoria.** Una revocada no cuenta como proceso vivo, así que
la persona **sí** puede inscribirse en **otra** convocatoria. En la **misma** no: hay una sola fila
por `(alumno, convocatoria)` e `import_rows` reutilizaría la revocada; aprobar (a mano o sola) y
abrir la liga responden «Esa persona tiene una inscripción revocada en esta convocatoria; solo puede
inscribirse en otra.». No existe «des-revocar».

## Configuración

| Variable | Default | Nota |
|---|---|---|
| `TITULATEC_ENROLLMENT_REVIEWER` | `school_services` | `school_services \| computer_center \| sii` |
| `TITULATEC_SII_BACKEND` | `disabled` | `disabled \| fake \| odbc`; `disabled` = toda consulta es `error` reintentable |
| `TITULATEC_SII_ODBC` | `""` | `SecretStr`, fuera del `repr`; p. ej. `DRIVER=FreeTDS;SERVER=…;PORT=…;DATABASE=…;UID=…;PWD=…;TDS_Version=5.0` |
| `TITULATEC_SII_RULES_DIR` | `database/SII/titulatec` | relativa a la raíz del proyecto |
| `TITULATEC_SII_FAKE_FILE` | `database/SII/titulatec/fake_sii.json` | solo con `fake` |
| `TITULATEC_SII_CONNECT_TIMEOUT_S` | `5` | 1–60 |
| `TITULATEC_SII_QUERY_TIMEOUT_S` | `10` | 1–120 |
| `TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS` | `0` | 0–168; 0 = inmediata |
| `TITULATEC_SII_MAX_ATTEMPTS` | `5` | 1–20 |

`get_settings()` está en `lru_cache` por proceso: cambiar cualquiera exige reiniciar **todos** los
procesos (backend HTTP, sockets, celery worker y beat).

## Despliegue

Pasos del spec §7, cuando haya accesos al SII:

1. **Reconstruir imágenes** backend y celery (`docker/backend/Dockerfile.fastapi` ya instala
   `unixodbc tdsodbc freetds-bin`; `pyodbc` está en `requirements.txt`). El paquete `tdsodbc`
   registra el driver `[FreeTDS]` en `/etc/odbcinst.ini`; no se escribe a mano.
2. **Copiar `database/SII/titulatec/`** al servidor (`rules.toml`, `queries/*.sql`; gitignored, como el DML).
3. **`.env.prod`**: `TITULATEC_SII_BACKEND=odbc`, `TITULATEC_SII_ODBC=…`, `TITULATEC_ENROLLMENT_REVIEWER=sii`.
4. `alembic upgrade head` (con `MIGRATE_DATABASE_URL` directo a Postgres; llega a `tt20260925b`).
5. `python -m itcj2.cli.main titulatec init-titulatec` (siembra la periódica `sii_2026_09/16` y el
   `process.api.cancel` de Servicios Escolares en el `03`).
6. Validar (ninguno escribe en la BD):
   ```bash
   python -m itcj2.cli.main titulatec sii-ping                          # ¿responde el SII? (exit 1 si no)
   python -m itcj2.cli.main titulatec sii-rules-validate                # reglas válidas, SQL solo-SELECT
   python -m itcj2.cli.main titulatec sii-check <control de prueba> --cohort <id>
   ```
   `sii-check` imprime el veredicto por regla, hechos, identidad, advertencias, `NIP: ****` o «sin
   NIP», y con `--cohort` si se aprobaría sola o quedaría «Por revisar». Sale con código 1 si el
   veredicto es `error` o si la consulta de `[credential]` falla o no trae su columna. Probar al
   menos: un apto con NIP, un no apto, uno sin NIP y un control inexistente.
7. **Reiniciar todos los procesos** (HTTP, sockets, celery worker y beat). Confirmar en el log del
   worker `titulatec.sii_check_request` y `titulatec.sii_sweep`, y que el beat despacha «TitulaTec:
   barrido de elegibilidad del SII».

Para desarrollo o demo sin accesos: `TITULATEC_SII_BACKEND=fake` + `fake_sii.json` (formato en
[`sii_rules_format.md`](../sii_rules_format.md#fake_siijson-sii-falso)).

## Flujos relacionados

- ← [Inscripción pública con revisión previa](xcut_public_enrollment.md) — el formulario y los otros dos modos.
- ⤵ [Formato de las reglas del SII](../sii_rules_format.md)
- ⤵ [Accesos de Centro de Cómputo](xcut_computer_center_access.md) — el modo `computer_center`, que este reemplaza cuando se activa.
- ⤵ [Expediente del alumno](xcut_admin_process_expediente.md) — botón «Revocar inscripción».
- ← [Máquina de estados](00_state_machine.md) · [Glosario](_glossary.md)

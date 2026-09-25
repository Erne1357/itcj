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
es «Servicios Escolares» (quien firma el correo de rechazo). En modo `sii` **Centro de Cómputo no
participa**: su bandeja de Accesos solo pinta el aviso «En este modo las solicitudes las contesta el
SII y Servicios Escolares; Centro de Cómputo no tiene acciones.» y sus cinco POST responden 400 con
ese motivo antes de abrir sesión ([Accesos](xcut_computer_center_access.md)). Vaciar «Por dar
acceso» antes de activar el modo: una `awaiting_access` sobrante ya no tiene quién le dé el NIP.

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Configuración | `itcj2/config.py` | 9 settings `TITULATEC_SII_*` (ver [Configuración](#configuración)) y dos validadores de arranque (`fake` prohibido con `FLASK_ENV=production`; edad del veredicto > ventana de veto). Se leen **solo** por métodos estáticos: `SiiConfig` (`services/sii/client.py`) y `EligibilityService.delay_hours()/max_attempts()/verdict_max_age_hours()/rules_version()`. |
| Conector | `services/sii/client.py` | `get_sii_client()` → `OdbcSiiClient` (`pyodbc` importado **perezosamente**, FreeTDS, solo lectura, timeouts, parámetros `?`) · `FakeSiiClient` (JSON local) · `disabled` lanza `SiiUnavailable`. Errores: `SiiUnavailable` (reintentable) vs `SiiQueryError`/`SiiRulesError` (configuración). Mensajes sin cadena de conexión ni valores de fila. |
| Motor de reglas | `services/sii/rules.py` | `RuleSet.load/validate/evaluate/fetch_credential`. Formato: [`sii_rules_format.md`](../sii_rules_format.md) (no se duplica aquí). |
| Modelo | `models/eligibility_check.py` | `titulatec_eligibility_checks` (una fila por intento) · `titulatec_enrollment_requests.last_check_id` (la vigente) · `titulatec_cohorts.sii_auto_approve` (interruptor, `server_default true`). Migraciones `tt20260925a` + `tt20260925b` (columna `retryable`). |
| Servicio | `services/eligibility_service.py` | `EligibilityService.check / auto_approve / sweep / recheck_errors / stale_apt_count / latest_check`, `enqueue_check` (devuelve `bool`), `identity_block`, `fetch_sii_nip`. |
| Tareas | `itcj2/tasks/titulatec_tasks.py` | `titulatec.sii_check_request(req_id, attempt, force)` y `titulatec.sii_sweep()`. |
| Periódica | `database/DML/titulatec/sii_2026_09/16_insert_sii_sweep_task.sql` (gitignored, plegado a `SEED_FILES` antes del `15`) | `core_task_definitions` + `core_periodic_tasks` «TitulaTec: barrido de elegibilidad del SII», `*/10 * * * *`. Se siembra activa; fuera del modo `sii` no hace nada, pero cada corrida deja su registro (144 al día). **Mientras el modo no sea `sii` se puede pausar** en `/itcj/config/system/tasks` › «Tareas Programadas» (switch de la fila), y se **activa en el go-live** ([Despliegue](#despliegue), paso 8). Re-sembrar respeta `is_active` (el `ON CONFLICT` no lo toca). |
| Bandeja | `pages/requests_admin.py` + `partials/requests_body.html` | Veredicto por fila, motivos, discrepancias, «Reintentar consulta» (`POST /{req_id}/reconsultar`), píldora «Aprobada automáticamente (SII)». |
| Interruptor | `pages/admin.py::cohort_window` + `partials/cohort/cohort_window.html` | Switch «Aprobación automática (SII)» en el panel de la ventana, solo en modo `sii`. |
| CLI | `itcj2/cli/titulatec.py` | `sii-ping`, `sii-rules-validate`, `sii-check`, `sii-sweep [--cohort ID] [--reconsultar-errores]`. |

## Ruta en la app (UI)

1. 👤 `/titulatec/inscripcion` → el formulario y la tarjeta de «Recibimos tu solicitud» **no cambian**
   (indistinguibilidad E8: la consulta es asíncrona, la respuesta pública no depende del SII).
2. 🏛️ Convocatoria › pestaña **Resumen** › panel de la ventana → switch **«Aprobación automática (SII)»**
   (encendido por omisión). En solo lectura muestra «encendida/apagada». Se guarda con el mismo
   botón que la ventana, en **un solo commit** con ella. El aviso al guardar confirma el cambio:
   encendida → «N solicitud(es) apta(s) pendiente(s) se reconsultarán en el SII antes de
   aprobarse» (las de veredicto viejo o de otras reglas, `stale_apt_count`); apagada → «las
   solicitudes quedan en «Por revisar» para Servicios Escolares».
3. 🏛️ `/titulatec/admin/solicitudes` › **Por revisar** → cada fila `pending_review` trae el bloque
   `#tt-req-sii-<id>`: estado (Sin consultar / Consultando… / Consultando… sin respuesta desde … /
   Apta / No apta / Error de consulta), reglas incumplidas con su motivo (las cumplidas plegadas),
   discrepancias de identidad formulario↔SII, «SII · intento N de M», y el **por qué** una apta sigue
   ahí (nota, nombre sin confirmar, interruptor apagado —«Actívala en la convocatoria (Resumen ›
   Ventana de inscripción)»—, convocatoria no abierta, ventana de veto con fecha, «se aprobará
   sola en el siguiente barrido»). Un error reintentable bajo el tope dice «Se reintenta sola
   (intento N de M).». Botón **«Reintentar consulta»** (o «Consultar al SII» si nunca se
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
| 5 | 🏛️ | Solicitudes, fila `pending_review` | Reintentar consulta | `POST /titulatec/admin/solicitudes/{id}/reconsultar` (`api.approve`) | `enqueue_check(req.id, force=True)` | nada propio (la fila la abre la tarea bajo lock) | 200 + parcial + `X-Tt-Notice` «Consulta al SII solicitada: el veredicto aparece al terminar.»; si no se pudo encolar (broker caído) → 400 «No se pudo solicitar la consulta; intenta de nuevo.» |
| 6 | 🏛️ | Solicitudes | Aprobar como excepción (no apta, error, interruptor apagado) | `POST …/{id}/aprobar` (en `run_in_threadpool`: no congela el event loop) | `approve` → `_approve_locked(actor_id=…)` | sin cuenta: **re-consulta el NIP al SII** (el del formulario se ignora), fuera del lock, y revalida bajo el lock | Si el SII no lo da o no responde → 400 «No se pudo obtener el NIP del SII.» sin escribir; NIP que no son 4 dígitos → 400 «NIP del SII con formato inválido…» |
| 7 | 🏛️ | Solicitudes | Rechazar | `POST …/{id}/rechazar` | `reject` | igual que el modo oficial | `send_enrollment_rejected`, firmado «Servicios Escolares» |
| 8 | 🏛️ | Resumen de la convocatoria | Interruptor | `POST /titulatec/admin/cohorts/{id}/ventana` (`cohort.api.update`) | `cohort_window` marca `cohort.sii_auto_approve` antes de `CohortService.set_window` → un solo commit | `titulatec_cohorts.sii_auto_approve` | `logger.info` con convocatoria, estado nuevo y actor |

## Estado resultante

- `titulatec_eligibility_checks`: una fila por intento; la vigente es `last_check_id`.
  `status` ∈ `pending | apt | not_apt | error`. `results = [{rule, ok, message}]`; `facts` = solo las
  columnas de la lista blanca `[facts]`; **nunca** la columna ni la consulta de `[credential]`.
- `retryable` (Boolean, nullable): `true` si el `error` fue `SiiUnavailable` (SII caído, backend
  `disabled`, cadena vacía) o `SoftTimeLimitExceeded` (celery cortó la tarea por tiempo); `false`
  si es de configuración (reglas que no cargan, SQL inválido, columna faltante, `NULL` en una regla
  `truthy`/`falsy`); `NULL` fuera de `error`.
- `identity_mismatch`: `NULL` = no se comparó · `{}` = se comparó y coincide · con claves = los
  campos que difieren · `_unverified` = `first_name`/`last_name` vacíos en algún lado o columna mal
  escrita (no se pudo comparar).
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
| **Veredicto viejo o de otras reglas**: terminó hace más de `TITULATEC_SII_VERDICT_MAX_AGE_HOURS` (24 h por omisión, contadas desde `finished_at`) o su `rules_version` no es la vigente (o las reglas no cargan) | no aprueba, **sin nota**: tras soltar el lock encola una consulta forzada (`_MSG_STALE_VERDICT`; el barrido la cuenta en `retried`). Así, reencender el interruptor no aprueba en silencio un rezago decidido con reglas anteriores |
| Convocatoria no `open` (`_cohort_gate`, D5) | nada |
| Interruptor `sii_auto_approve` apagado | nada: SE decide a mano |
| **Nombre del formulario distinto al del SII** (`identity_mismatch` en nombre/apellidos, sin acentos ni mayúsculas) | nota «El nombre del formulario no coincide con el del SII (…); confirma que la solicitud sea de esa persona antes de aprobarla.» — solo etiquetas, nunca valores. Una **carrera** distinta NO frena (el SII la abrevia); se muestra a SE |
| **No se pudo comparar el nombre** (sin `[identity]`, sin `first_name`/`last_name` mapeados, nombre vacío en el SII o en el formulario, columna mal escrita) | nota «No se pudo comparar el nombre con el SII.» — la identidad es **obligatoria** para aprobar sola (falla cerrado) |
| **La cuenta existe desactivada** | nota «La cuenta está desactivada: al abrir la liga se reactivaría.» — queda para SE, que la ve antes de aprobar |
| **El SII no tiene NIP** (0 filas o columna vacía) | nota «El SII no devolvió NIP.» |
| La consulta del NIP falla por configuración (`SiiRulesError`, `SiiQueryError`, otro) | nota «No se pudo leer el NIP en el SII (Tipo): revisa [credential] …» |
| El SII no responde al pedir el NIP (`SiiUnavailable`) | nada, **sin nota**: el barrido reintenta |
| NIP con otro formato (≠ 4 dígitos), D5, cuenta sin contraseña, datos inválidos, inscripción revocada en esta convocatoria, fallo al crear la cuenta | nota con el motivo de `_approve_locked` |

La **nota** (`review_note`) es la marca de «necesita a una persona»: el barrido ya no toma esa
solicitud. SE la resuelve aprobando, rechazando o con «Reintentar consulta».

Sin `[identity]` (o sin `first_name` y `last_name` en ella) **nada se aprueba solo**: toda apta
queda para SE con la nota de identidad. `sii-rules-validate` lo advierte y `sii-check --cohort` ya no
promete «se aprobaría automáticamente». La guarda la comparten `auto_approve` y la bandeja
(`identity_block`), así las dos dicen lo mismo.

## Barrido periódico

`EligibilityService.sweep` sobre `pending_review` (lotes de 200, ordenados por id; cada solicitud en
su transacción, la que revienta se registra por **tipo** y no detiene a las demás):

- sin consulta vigente → primera consulta (`checked`);
- vigente `error` con `retryable` y `attempt < max_attempts()` → siguiente intento (`retried`);
  `pending` colgada (> 15 min, `_PENDING_STALE`) → se retoma **forzada, aunque esté en el tope**;
- vigente `apt`, ventana vencida, sin `review_note`, convocatoria `open` e interruptor encendido →
  `auto_approve` (`approved`; si el veredicto era viejo o de otras reglas, encola la reconsulta y
  cuenta en `retried`).

Un `error` de **configuración** (no reintentable) o uno reintentable que ya llegó al tope **no** lo
vuelve a tomar el barrido: esperar no lo arregla. Tras corregir la causa (reglas, conexión, el
montaje del worker):

```bash
python -m itcj2.cli.main titulatec sii-sweep --reconsultar-errores [--cohort ID]
```

(`EligibilityService.recheck_errors`) **encola** una consulta forzada para toda `pending_review` cuya
vigente sea `error` —cualquiera— o `pending` colgada, e imprime cuántas encoló y cuántas no se
pudieron encolar (broker caído). La consulta la hace el worker. «Reintentar consulta» de la bandeja
es lo mismo, fila por fila.

Manual: `python -m itcj2.cli.main titulatec sii-sweep [--cohort ID]` (solo en modo `sii`; imprime
los conteos).

## Concurrencia

- Transiciones con `pg_advisory_xact_lock(_REQUEST_LOCK_NS, id)` + `db.refresh` antes de leer el
  estado. La consulta al SII corre **sin** lock ni transacción abierta (lock → commit → SII → lock →
  commit). El NIP también: `approve()` y `auto_approve` validan bajo el lock, sueltan
  (`_sii_nip_unlocked`), piden el NIP y en una segunda vuelta re-toman el lock y **revalidan todo**
  antes de `_approve_locked(..., sii_nip=...)`; la automática solo lo pide si todas sus guardas
  pasan. La ruta `aprobar` corre en `run_in_threadpool` (pyodbc es bloqueante).
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
- toma el advisory de citas del proceso (`SlotService._lock_process`) **antes** del bloqueo de la
  fila (orden anti-deadlock con agendar). La fila va con `FOR NO KEY UPDATE`
  (`with_for_update(key_share=True)`): serializa dos revocaciones y a `CohortService.set_window`,
  pero no choca con el `FOR KEY SHARE` de los INSERT con FK al proceso (citas, eventos).
  `set_window` lee con `FOR UPDATE` los procesos que pausa o reanuda, así una revocación que hace
  commit entretanto no se pisa (Postgres re-evalúa el filtro de estado tras la espera). Cancela la
  cita vigente si está `scheduled`/`confirmed` (libera la franja, en la misma transacción, sin su
  propio aviso);
- evento `process_cancelled` (payload `reason`, `previous_status`, `appointment_cancelled`), aviso en
  la app («Tu inscripción a titulación fue revocada») y **después del commit**
  `send_process_cancelled` al institucional y al personal — texto **neutro** («Tu inscripción al
  proceso de titulación fue revocada», sin atribuirla a un área), sin motivo, folio ni número de
  control (el motivo se lee en la plataforma con sesión);
- el alumno conserva `graduate`: en su dashboard ve «Inscripción revocada» / «Tu inscripción fue
  revocada: motivo» en lugar de la fase actual, **sin** barra de avance ni fase «Actual» en el
  acordeón (ninguna fase se presenta como viva);
- en la bandeja de GTV («Con observaciones» y «Liberadas») la fila de una inscripción revocada no
  ofrece acciones (todas responderían 400) y lleva la píldora «Revocada».

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
| `TITULATEC_SII_BACKEND` | `disabled` | `disabled \| fake \| odbc`; `disabled` = toda consulta es `error` reintentable. `fake` **no arranca** con `FLASK_ENV=production` |
| `TITULATEC_SII_ODBC` | `""` | `SecretStr`, fuera del `repr`; p. ej. `DRIVER=FreeTDS;SERVER=…;PORT=…;DATABASE=…;UID=…;PWD=…;TDS_Version=5.0;ClientCharset=UTF-8` (`ClientCharset=UTF-8`: sin él una Ñ o un acento del SII llegan mal y la comparación del nombre falla) |
| `TITULATEC_SII_RULES_DIR` | `database/SII/titulatec` | relativa a la raíz del proyecto |
| `TITULATEC_SII_FAKE_FILE` | `database/SII/titulatec/fake_sii.json` | solo con `fake` |
| `TITULATEC_SII_CONNECT_TIMEOUT_S` | `5` | 1–60 |
| `TITULATEC_SII_QUERY_TIMEOUT_S` | `10` | 1–120 |
| `TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS` | `0` | 0–168; 0 = inmediata |
| `TITULATEC_SII_MAX_ATTEMPTS` | `5` | 1–20 |
| `TITULATEC_SII_VERDICT_MAX_AGE_HOURS` | `24` | ≥ 1; edad máxima de un `apt` para aprobar solo, desde `finished_at`. Tiene que ser **mayor** que `TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS` (si no, `Settings` truena al arrancar nombrando las dos: todo veredicto llegaría viejo al vencer la ventana) |

`get_settings()` está en `lru_cache` por proceso: cambiar cualquiera exige reiniciar **todos** los
procesos (backend HTTP, sockets, celery worker y beat).

## Despliegue

Pasos del spec §7, cuando haya accesos al SII:

1. **Reconstruir imágenes** backend y celery (`docker/backend/Dockerfile.fastapi` ya instala
   `unixodbc tdsodbc freetds-bin`; `pyodbc` está en `requirements.txt`). El paquete `tdsodbc`
   registra el driver `[FreeTDS]` en `/etc/odbcinst.ini`; no se escribe a mano.
2. **Copiar al servidor** (gitignored, no viajan con `git pull`):
   - `database/SII/titulatec/` (`rules.toml`, `queries/*.sql`);
   - `database/DML/titulatec/` **completo**, incluidos `sii_2026_09/` (la periódica) y el `03`
     (`process.api.cancel` para Servicios Escolares).
3. **El worker de Celery tiene que ver las reglas.** La consulta (`titulatec.sii_check_request`) y
   el barrido (`titulatec.sii_sweep`) van a la cola `default`, que consume el servicio
   `celery-worker`; la imagen no trae `database/` (`.dockerignore`). En
   `docker/compose/docker-compose.prod.yml`, `celery-worker` (y cualquier worker que consuma
   `default`) monta `../../database/SII:/app/database/SII:ro`. Sin ese montaje **toda** consulta
   termina en «Error de consulta» no reintentable y nada se aprueba solo. Comprobar:
   `docker compose exec celery-worker ls /app/database/SII/titulatec/rules.toml`.
4. **Canal al SII cifrado y en UTF-8.** Exigir cifrado del lado de FreeTDS (`encryption = require`
   en la sección del servidor de `freetds.conf`, o el equivalente del driver) o, si ASE no lo
   soporta, un segmento de red aislado entre el servidor y el SII: por ese canal viajan el usuario
   de BD y el NIP de cada alumno. Y `ClientCharset=UTF-8` en `TITULATEC_SII_ODBC`.
5. **`.env.prod`**: `TITULATEC_SII_BACKEND=odbc`, `TITULATEC_SII_ODBC=…`, `TITULATEC_ENROLLMENT_REVIEWER=sii`
   (y, si se usa ventana de veto, `TITULATEC_SII_VERDICT_MAX_AGE_HOURS` mayor que ella).
6. `alembic upgrade head` (con `MIGRATE_DATABASE_URL` directo a Postgres; llega a `tt20260925b`)
   y `python -m itcj2.cli.main titulatec init-titulatec` (siembra la periódica `sii_2026_09/16` y el
   `process.api.cancel` de Servicios Escolares en el `03`).
7. **Validar desde el worker** (ninguno escribe en la BD; en el worker porque es quien consulta de
   verdad —el backend HTTP monta `database/` entero y saldría en verde aunque el worker no vea nada):
   ```bash
   docker compose exec celery-worker python -m itcj2.cli.main titulatec sii-ping              # exit 1 si no responde
   docker compose exec celery-worker python -m itcj2.cli.main titulatec sii-rules-validate    # reglas + advertencias
   docker compose exec celery-worker python -m itcj2.cli.main titulatec sii-check <control> --cohort <id>
   ```
   `sii-check` imprime el veredicto por regla, hechos, identidad, advertencias, `NIP: **** (… 4
   dígitos: sí|no)` o «sin NIP», y con `--cohort` si se aprobaría sola o quedaría «Por revisar».
   Sale con código 1 si el veredicto es `error`, si la consulta de `[credential]` falla o no trae su
   columna, o si el NIP no tiene 4 dígitos. Probar al menos: un apto con NIP, un no apto, uno sin
   NIP, un control inexistente y uno con Ñ o acento en el nombre (charset). `sii-rules-validate` no
   debe advertir de `[identity]`: sin ella nada se aprueba solo.
8. **Reiniciar todos los procesos** (HTTP, sockets, celery worker y beat) y **activar la periódica**
   «TitulaTec: barrido de elegibilidad del SII» en `/itcj/config/system/tasks` › «Tareas
   Programadas» si estaba pausada. Confirmar en el log del worker `titulatec.sii_check_request` y
   `titulatec.sii_sweep`, y que el beat la despacha.
9. **Tras corregir cualquier configuración** (reglas, cadena ODBC, montaje, charset) reconsultar lo
   que ya quedó en error — el barrido no lo retoma:
   ```bash
   docker compose exec celery-worker python -m itcj2.cli.main titulatec sii-sweep --reconsultar-errores
   ```

Mientras el modo **no** sea `sii` (la periódica ya sembrada en un entorno que aún no entra en
vivo), la periódica puede quedarse **pausada** desde la misma pantalla: no hace nada fuera del modo
`sii`, pero cada corrida deja su registro.

Para desarrollo o demo sin accesos: `TITULATEC_SII_BACKEND=fake` + `fake_sii.json` (formato en
[`sii_rules_format.md`](../sii_rules_format.md#fake_siijson-sii-falso)).

## Flujos relacionados

- ← [Inscripción pública con revisión previa](xcut_public_enrollment.md) — el formulario y los otros dos modos.
- ⤵ [Formato de las reglas del SII](../sii_rules_format.md)
- ⤵ [Accesos de Centro de Cómputo](xcut_computer_center_access.md) — el modo `computer_center`, que este reemplaza cuando se activa.
- ⤵ [Expediente del alumno](xcut_admin_process_expediente.md) — botón «Revocar inscripción».
- ← [Máquina de estados](00_state_machine.md) · [Glosario](_glossary.md)

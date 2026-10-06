# Detalle de convocatoria: 5 sub-pestañas HTMX (Fase 0)

> **Objetivo:** dar a Servicios Escolares una sola pantalla por convocatoria donde ve el
> avance del padrón, da de alta alumnos (uno a uno o por CSV) y —si es la jefa— configura
> los días habilitados para el cotejo, los requisitos de cotejo y **la ventana de
> inscripción pública** (fecha y hora de apertura y de cierre + `status`).

| | |
|---|---|
| **Actor(es)** | 🏛️ Servicios Escolares (encargado) · 🏛️ Jefa de Servicios Escolares (solo ella toca *Días de cotejo*) |
| **Permiso(s)** | Página: `titulatec.cohort.page.list` a secas (`_COHORT_PERMS`; los `dashboard.*` se quitaron tras el incidente documentado en `pages/admin.py:16-29`). Acciones: `titulatec.cohort.api.import_csv` (alta manual + wizard CSV) · `titulatec.cohort.api.review_days` (calendario editable) · `titulatec.cohort.api.cotejo_reqs` (requisitos) · `titulatec.cohort.api.update` (ventana de inscripción) |
| **Trigger** | Clic en el nombre / botón **Detalles** de una fila de `/titulatec/admin/cohorts` (`admin/cohorts.html:55,60`) |
| **Precondiciones** | Existe el `Cohort` (creado en la lista; uno por `core_academic_periods.id`) |
| **Sub-flujos** | ⤵ [importación por CSV](phase0_school_services_import_csv.md) · ⤵ [cita de cotejo](phase2_appointment_loop.md) (consume los días) |
| **Estado final** | No muta por sí misma: es el hub. Cada tab escribe en `core_users` / `titulatec_processes` / `titulatec_cohort_review_days` |

## Ruta en la app (UI)

1. Sidebar admin → **Convocatorias** (`/titulatec/admin/cohorts`; entrada de `_ADMIN_NAV` gateada
   por `titulatec.cohort.page.list`, `pages/nav.py:99`) → fila → **Detalles**.
2. `/titulatec/admin/cohorts/{id}` — encabezado (nombre, `status`, `period_code`, y
   **Apertura**/**Cierre** con fecha y hora, «dd/mm/aaaa hh:mm», `window_header` de
   `cohort_detail`) + barra de tabs.
3. Tabs (orden en pantalla, `admin/cohort_detail.html:21`):

| Tab | `?tab=` | Parcial incluido | Qué muestra |
|---|---|---|---|
| **Resumen** | `resumen` (default) | `partials/cohort_summary.html` | 4 KPIs + **editor de ventana** (`cohort/cohort_window.html`) + embudo por fase |
| **Alumnos** | `alumnos` | `partials/cohort_students.html` | alta manual + buscador + tabla paginada |
| **Días de cotejo** | `dias` | `partials/cohort_days_calendar.html` | calendario mensual toggle (o solo lectura) |
| **Importar** | `importar` | `partials/cohort_import.html` | dropzone del wizard CSV |
| **Requisitos** | `cotejo` | `partials/cohort/cohort_cotejo_reqs.html` | alta/edición/baja de requisitos de cotejo |

> Son **5**. `cohort_detail()` normaliza `tab` contra la tupla
> `("resumen", "dias", "alumnos", "importar", "cotejo")` y cae a `"resumen"` con cualquier otro
> valor. Ánclate por el nombre `cohort_detail`, no por número de línea: cinco tareas han editado
> `pages/admin.py`.

## Patrón de navegación entre tabs

Cada tab es un **link real** (`href`) **y** un `hx-get` a la misma URL con `?tab=`, con
`hx-push-url="true"`: funciona con y sin JS, y la URL siempre refleja el tab abierto.

El swap **no** es sobre `#cohort-tab-body`: es sobre `#cohort-pane`, el contenedor que envuelve
*la barra de tabs + el cuerpo*, con `hx-target="#cohort-pane" hx-select="#cohort-pane"
hx-swap="outerHTML"` (`admin/cohort_detail.html:25`). El comentario del template lo justifica:
swappear el pane completo deja el estado `is-active` correcto y evita IDs duplicados. El endpoint
devuelve **la página completa** (`cohort_detail.html`, que extiende `base_admin.html`) y es HTMX
quien recorta `#cohort-pane` con `hx-select`.

`#cohort-tab-body` sí existe (`admin/cohort_detail.html:29`) pero como **destino de un solo uso**:
el submit del alta manual de alumno (`cohort_student_addform.html:6`,
`hx-target="#cohort-tab-body" hx-swap="innerHTML"`).

Todo esto vive dentro de `#tt-admin-content`, el área que el sidebar swappea con
`hx-swap="morph:outerHTML"` (`admin/base_admin.html:48,63`): son dos niveles de swap
independientes.

```mermaid
sequenceDiagram
    actor S as 🏛️
    participant FE as Navegador (HTMX)
    participant API as pages/admin.py::cohort_detail
    participant DB as Postgres
    S->>FE: clic en tab "Alumnos"
    FE->>API: GET /titulatec/admin/cohorts/{id}?tab=alumnos
    API->>DB: Cohort + cached_perms + _students_ctx
    API-->>FE: cohort_detail.html completo
    Note over FE: hx-select recorta #cohort-pane · outerHTML · push-url
    FE-->>S: barra de tabs + cuerpo nuevos, sidebar intacto
```

## Pasos detallados

Prefijos: router de páginas `/titulatec` (`pages/router.py:18`) + router admin `/admin`
(`pages/admin.py:14`). Abajo se omiten.

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Permiso del endpoint |
|---|---|---|---|---|---|---|---|
| 0 | 🏛️ | lista | abrir detalle | `GET /cohorts/{id}[?tab=]` | `_cohort_summary_ctx` / `_students_ctx` / `_review_days_ctx` | — (lectura) | `_COHORT_PERMS` |
| 1 | 🏛️ | Alumnos | desplegar alta | `GET /cohorts/{id}/students/lookup?control=` | (inline, `User.control_number`) | — | `_COHORT_PERMS` |
| 1b | 🏛️ | Alumnos | cancelar alta | `GET /cohorts/{id}/students/cancel` | — | — | `_COHORT_PERMS` |
| 2 | 🏛️ | Alumnos | crear/adjuntar alumno | `POST /cohorts/{id}/students` | `_add_student` → `ImportService.import_rows` | `core_users` (UPSERT por `control_number`) + `titulatec_processes` + 9 `titulatec_process_phases` + rol `graduate` (fuera `student`); si el user es nuevo: `password_hash=hash_nip(control)`, `must_change_password=True` | `titulatec.cohort.api.import_csv` |
| 3 | 🏛️ | Alumnos | buscar / filtrar fase / paginar | `GET /cohorts/{id}/students?q=&phase=&page=` | `_students_ctx` | — | `_COHORT_PERMS` |
| 4 | 🏛️ jefa | Días de cotejo | navegar de mes | `GET /cohorts/{id}/review-days?month=YYYY-MM` | `ReviewDayService.list_days` | — | `titulatec.cohort.api.review_days` |
| 5 | 🏛️ jefa | Días de cotejo | marcar/desmarcar día | `POST /cohorts/{id}/review-days/toggle` (`date`, `month`) | `ReviewDayService.toggle` | INSERT o DELETE en `titulatec_cohort_review_days` | `titulatec.cohort.api.review_days` |
| 6 | 🏛️ | Importar | subir CSV | `POST /cohorts/{id}/import/upload` | `ImportService.save_temp` + `parse` + `autodetect_mapping` | — (CSV temporal por token) | `titulatec.cohort.api.import_csv` |
| 7 | 🏛️ | Importar | ajustar mapeo | `POST /cohorts/{id}/import/revalidate` | `ImportService.read_temp` + `build_preview` | — | `titulatec.cohort.api.import_csv` |
| 8 | 🏛️ | Importar | confirmar | `POST /cohorts/{id}/import/commit` | `ImportService.save_mapping` + `import_rows` + `delete_temp` | igual que el paso 2, en lote; notif `PROCESS_CREATED` por proceso creado | `titulatec.cohort.api.import_csv` |
| 9 | 🏛️ jefa | Resumen | guardar ventana | `POST /cohorts/{id}/ventana` (`status`, `opens_date` + `opens_time`, `closes_date` + `closes_time`; los nombres viejos `opens_at`/`closes_at` solo como respaldo de fecha) | `_parse_window_dt` → `CohortService.set_window` | UPDATE de `opens_at`/`closes_at`/`status` en `titulatec_cohorts` **+ el flip de procesos**: al cerrar, los `active` de esa convocatoria pasan a `on_hold`; al abrir, los `on_hold` de convocatorias cerradas vuelven a `active`. Un `ProcessEvent` (`process_paused`/`process_resumed`) por proceso tocado | `titulatec.cohort.api.update` |

### Targets HTMX (no todo swappea el tab)

| Acción | `hx-target` | Fuente |
|---|---|---|
| Cambio de tab · botón "Importar CSV" del tab Alumnos | `#cohort-pane` (`outerHTML` + `hx-select`) | `cohort_detail.html:25` · `cohort_students.html:8` |
| Submit del alta manual | `#cohort-tab-body` (`innerHTML`) → `cohort_students.html` | `cohort_student_addform.html:6` |
| Lookup / cancelar alta | `#student-add` (`innerHTML`) | `cohort_student_addbtn.html:2` · `cohort_student_addform.html:10,29` |
| Buscador, filtro de fase, paginación | `#students-body` (`innerHTML`) → `cohort_students_table.html` | `cohort_students.html:16,20` · `cohort_students_table.html:30,33` |
| Flechas de mes y toggle del calendario | `#tt-cal-wrap` (`outerHTML` + `hx-select="#tt-cal-wrap"`) | `cohort_days_calendar.html:6,9,23` |
| Upload / revalidate / commit del CSV | `#import-body` (`innerHTML`) | `cohort_import.html:11` · `import_preview.html:32,92` |
| Guardar la ventana de inscripción | `#cohort-window` (`outerHTML`) | `cohort/cohort_window.html` |

## Detalle por sub-pestaña

### Resumen (`tab=resumen`, default)

`_cohort_summary_ctx` (`pages/admin.py:53-89`) carga **todos** los `TitulationProcess` del cohort
y agrega en memoria:

- KPIs: `total`, `completed` + `pct_completed`, `with_appt` (procesos con al menos un
  `ReviewAppointment`, `DISTINCT process_id`), `review_days` (`len(ReviewDayService.list_days)`).
- `phase_rows`: una franja del embudo por cada `PhaseDefinition` activa ordenada por
  `order_index`, **incluidas las de count 0** para ver el flujo completo. El color es
  `hsl(222 → 38)` interpolado por posición (`cohort_summary.html:18-20`).
- Con `total == 0` el embudo se sustituye por un texto que apunta a los tabs *Importar* y
  *Alumnos* (`cohort_summary.html:33`).

`ReviewDayService.list_days` va dentro de un `try/except` que degrada a `review_days = 0`: el KPI
nunca tumba la página.

#### Editor de ventana de inscripción

Entre los KPIs y el embudo va `partials/cohort/cohort_window.html`, raíz `#cohort-window`. Es lo
único **accionable** del tab, y es lo que decide si el formulario **público** de auto-inscripción
está abierto (`CohortService.is_public_enrollment_open`). El personal nunca queda bloqueado por
esto: importar CSV y dar de alta a mano siguen funcionando con la convocatoria `closed` o `draft`.

- **Editabilidad por contexto, igual que el calendario**: `_window_ctx(db, cohort, can_edit=...)`
  resuelve `can_edit_window = "titulatec.cohort.api.update" in cached_perms(...)`
  dentro de la rama `resumen` de `cohort_detail`. Sin el permiso, la tarjeta se pinta en solo
  lectura (fechas y estado, sin `<form>`).
- **El POST lleva UN SOLO código en `perms`**, `titulatec.cohort.api.update`, y es deliberado:
  `require_page_app` evalúa la lista como **OR**, así que un `dashboard.*` de más entregaría a
  cualquier oficial el interruptor que pausa los procesos de toda una convocatoria. Es el mismo
  incidente que documenta `_COHORT_PERMS`.
- **Fecha y hora por extremo (2026-09-27, spec §B).** `opens_at` y `closes_at` son `DateTime`
  (naive, hora local de `APP_TZ`: el mismo reloj que `db_now()`) **NOT NULL** desde la migración
  `tt20260927b`. Cada extremo se edita con la macro `window_end` de `_macros.html` (compartida con
  el alta de convocatoria): `<input type="date">` **obligatorio** + `<input type="time">`
  **opcional**, con la ayuda «Hora opcional · vacío = 00:00» (apertura) / «vacío = 23:59» (cierre).
  `_parse_window_dt` aplica la hora de omisión: 00:00 en la apertura y **23:59:59** en el cierre
  (se muestra «23:59»: quien envía a las 23:59:30 del último día sigue dentro; con un cierre
  tecleado «23:59», guardado 23:59:00, también, porque la lectura trunca al minuto). Una hora ilegible
  NO cae a la de omisión: se rechaza. Sin `style=`: los anchos son `.tt-win-*` de `titulatec.css`.
- **Todo se entrega precargado** (`_window_ctx`: fecha en ISO `YYYY-MM-DD`, hora en `HH:MM`),
  porque `set_window` escribe SIEMPRE los dos extremos con lo que reciba: no existe "conservar lo
  anterior". La hora que coincide con la de omisión va **vacía** (Ruling R14): un
  `<input type="time">` de minutos no lleva segundos, y precargar «23:59» movería el cierre a
  23:59:00 al re-guardar sin tocarlo.
- **Validación** (siempre antes de escribir): fecha vacía o ilegible, u hora ilegible → 400
  «La apertura y el cierre son obligatorios.»; cierre igual o anterior a la apertura → 400 «El
  cierre tiene que ser posterior a la apertura.» (`CohortService.set_window`, que además exige los
  dos extremos: vacío ya no significa «sin tope»).
- **Lectura al minuto con `db_now()`**, nunca el reloj del proceso (el contenedor puede correr en
  UTC): `db_now()` se trunca a su minuto (`cohort_service._al_minuto`) y
  `is_public_enrollment_open` = `status == 'open'` y `opens_at <= ahora <= closes_at`;
  `next_public_enrollment_window` = `opens_at > ahora`, con el MISMO truncado. Así un cierre
  tecleado «23:59» (guardado 23:59:00) conserva su último minuto igual que el de omisión
  (23:59:30 abierto, 00:00:00 del día siguiente cerrado) y una apertura a las 09:00 abre al empezar
  ese minuto (revisión final F10). Lo que sigue a una solicitud ya enviada (aprobar, dar acceso, la
  liga) no mira las fechas (D5 de 09-24).
- Sin el permiso, la tarjeta es de solo lectura: «Apertura dd/mm/aaaa hh:mm · Cierre dd/mm/aaaa
  hh:mm».
- El interruptor «Aprobación automática (SII)» que vivió en este panel del 2026-09-25 al
  2026-09-27 se **retiró el 2026-09-27** con la aprobación automática; un formulario viejo en caché
  que aún mande su campo no mueve nada ([Consulta de elegibilidad al SII](xcut_sii_eligibility.md)).
- Éxito → 200 con el parcial re-renderizado + `X-Tt-Notice` («Ventana guardada: N proceso(s) en
  pausa.»). Rechazo → **400 + `X-Tt-Error`** percent-codificado, porque htmx no swappea en 4xx.
- El flip de procesos lo hace **`CohortService.set_window`, no la ruta**: es el actor único de esa
  transición y hace su propio `commit`. Duplicarlo en la ruta descuadraría los `ProcessEvent`.

### Alumnos (`tab=alumnos`)

- **Alta manual unificada por nº de control** (`#student-add`): el botón colapsado
  (`cohort_student_addbtn.html`) se reemplaza por el form del lookup; el input dispara
  `GET .../students/lookup` con `hx-trigger="change, keyup changed delay:500ms"`. Si el
  `control_number` ya existe, el nombre sale en solo lectura y el botón dice **Agregar**; si no
  existe, pide nombre + email y el botón dice **Crear y agregar**
  (`cohort_student_addform.html:13-18,27`).
- El submit reusa `ImportService.import_rows` con una sola fila: mismo folio secuencial
  `TT-{period_code}-{seq:04d}` y las 9 fases (fase 0 `approved`, fase 1 `in_progress`, resto
  `pending` — `import_service.py:300-313`). Extra sobre el CSV: si el usuario es nuevo,
  `_add_student` le pone la contraseña = número de control (`hash_nip`) y
  `must_change_password=True` (`pages/admin.py:124-138`).
- **Tabla**: 25 filas por página (`_STUDENTS_PER_PAGE`), orden `created_at DESC`, filtro `ILIKE`
  sobre `control_number` o `full_name`, filtro por `current_phase`. Cada fila enlaza al detalle del
  proceso (`/titulatec/admin/processes/{process_id}`).
- El selector de fase ofrece `0..8` (`cohort_students.html:22`).

### Días de cotejo (`tab=dias`)

- Contexto: `_review_days_ctx` (`pages/admin.py:141-168`) — matriz
  `Calendar(firstweekday=0).monthdatescalendar(year, month)` del **mes actual** al abrir el tab,
  con `on = fecha ∈ ReviewDayService.list_days`, más `prev_month`/`next_month` precalculados.
- **La editabilidad es del contexto, no de la ruta**: `cohort_detail()` resuelve
  `can_edit_days = "titulatec.cohort.api.review_days" in cached_perms(...)`
  (`cohort_detail`, `pages/admin.py`; `cached_perms` es la misma fuente que el gate, sin consultas con la caché tibia). Con el permiso, cada celda del mes lleva
  `hx-post .../review-days/toggle`; sin él las celdas son `<td>` inertes y la cabecera dice
  **"· solo lectura"** (`cohort_days_calendar.html:7,19-29`).
- Hoy solo `titulatec_school_services_head` tiene `titulatec.cohort.api.review_days`
  (`database/DML/titulatec/03_insert_role_permissions.sql:62`, confirmado contra la BD de dev). El
  encargado operativo ve el calendario en solo lectura.
- El toggle es idempotente por fecha: `ReviewDayService.toggle` borra si existe, inserta si no, y
  hace `commit` en el service (`services/review_day_service.py:36-46`).
- Los días marcados son la lista de fechas agendables del
  [loop de cita de cotejo](phase2_appointment_loop.md): `ReviewDayService.is_allowed` valida el alta
  de cita y `months_with_days` alimenta el selector de fechas.

### Importar (`tab=importar`)

`cohort_detail()` no precarga nada para este tab (`pass`, `pages/admin.py:402-403`):
`cohort_import.html` solo pinta la dropzone y un `#import-body` vacío. A partir del `change` del
`<input type=file>` el wizard es **exactamente** el standalone
`/titulatec/admin/cohorts/{id}/import` — mismos endpoints y mismos parciales
(`import_preview.html` → `import_success.html`). Detalle completo del parseo, auto-mapeo y commit:
⤵ [importación por CSV](phase0_school_services_import_csv.md).

`import_success.html:15-16` cierra el ciclo devolviendo al detalle con `?tab=alumnos` o
`?tab=importar`.

## Estado resultante

- `titulatec_cohorts` **sí se modifica** desde esta pantalla desde 2026-09-08: el editor de ventana
  del tab *Resumen* escribe `opens_at`, `closes_at` (fecha y hora) y `status`. Ese mismo POST puede
  además mover `titulatec_processes.status` (`active` ↔ `on_hold`) y escribir `ProcessEvent`.
- El **alta** vive en la lista (`/titulatec/admin/cohorts` → «Nueva convocatoria» →
  `POST /cohorts`, perm `titulatec.cohort.api.create`): desde 2026-09-27 pide, además del período
  académico, la **ventana** con la misma macro `window_end` (fecha obligatoria + hora opcional por
  extremo, mismas horas de omisión). Si falta una fecha, una hora es ilegible o el cierre no es
  posterior a la apertura → **303 a `/titulatec/admin/cohorts?error=ventana`** sin crear nada: la
  lista pinta «Indica apertura y cierre (el cierre después de la apertura).» (`#tt-cohort-new-error`)
  y deja el formulario desplegado. La convocatoria nace `draft` con esa ventana y sus requisitos
  de cotejo (misma transacción).
- Tras *Alumnos* / *Importar*: N `titulatec_processes` (`current_phase=1`, `status=active`,
  `is_app_active=true`) + 9 `titulatec_process_phases` c/u + rol `graduate` en la app (fuera `student`).
- Tras *Días de cotejo*: filas en `titulatec_cohort_review_days` que habilitan el agendado de la
  fase 2.

## Caminos alternos / errores ❗

- `Cohort` inexistente → `Response(status_code=404)` **sin cuerpo** (`pages/admin.py:395-396`).
  Como el swap del tab usa `hx-select`, un 404 no reemplaza nada: la pantalla queda como estaba.
- Alta manual sin nº de control o sin nombre → `400` + header `X-Tt-Error`
  (`pages/admin.py:227,232`); el listener global de `htmx:responseError` en
  `base_admin.html:61-66` lo convierte en toast.
- `import_rows` descarta en silencio (`skipped++`) las filas sin control/nombre y las que no pasan
  `CONTROL_NUMBER_RE` — el control number acaba siendo tramo de ruta en
  `instance/apps/titulatec/{period}/{control}/documents/` (`import_service.py:264-273`).
- `phase` llega como `str` y se parsea con `isdigit()` (`pages/admin.py:180`), no como `int|None`:
  el mismo blindaje anti-422 que en la agenda de citas.
- **`?tab=dias` en solo lectura, flechas de mes rotas**: las flechas ‹ › apuntan siempre a
  `GET /cohorts/{id}/review-days`, que exige `titulatec.cohort.api.review_days`
  (`pages/admin.py:244`). Un encargado sin ese permiso ve bien el mes actual, pero al cambiar de mes
  recibe la página 403 de `PageForbidden` (`itcj2/main.py:331-344`), que no contiene `#tt-cal-wrap`
  → `hx-select` no encuentra nada y el calendario desaparece del tab hasta recargar.
- La paginación interpola `q` sin escapar en el query string (`cohort_students_table.html:30,33`):
  una búsqueda con `&` o `#` se trunca al pasar de página.

## Notas de implementación

- `GET /cohorts/{id}/review-days` (`admin/cohort_review_days.html`) sigue existiendo como **página
  completa** y fuerza `can_edit_days = True` en el template (línea 11) — coherente porque la ruta ya
  exige el permiso. Ningún template enlaza a ella; se llega solo por las flechas de mes / el toggle
  del tab, que recortan `#tt-cal-wrap` con `hx-select`.
- Las rutas de este flujo abren su propia `SessionLocal()` con `try/finally: db.close()`; ninguna
  usa `DbSession`. La única sesión inyectada es la de `require_page_app` (gate). Son `def` (corren en el
  threadpool); las que leen el form delegan en un `_cuerpo_*` síncrono (`CLAUDE.md` §1 de la app).
- `_cohort_summary_ctx` construye un dict `defs` (`pages/admin.py:61`) que no usa.
- De los permisos `cohort.*` seedeados ya gatean código 6: `page.list`, `api.create`,
  `api.import_csv`, `api.review_days`, `api.cotejo_reqs` y —desde 2026-09-08—
  `api.update` (el editor de ventana; llevaba sembrado desde el primer DML sin gatear nada).
  Siguen decorativos `titulatec.cohort.page.detail` y `titulatec.cohort.api.read`: están asignados a
  roles pero no aparecen en ningún `require_page_app`.
- `titulatec_cotejo_requirements` **sí está cableado**: cuatro rutas `/cohorts/{id}/cotejo-reqs*` en
  `pages/admin.py` y la quinta pestaña *Requisitos*, que incluye
  `partials/cohort/cohort_cotejo_reqs.html`. `CotejoRequirementService` ya no revienta al importar.

## Flujos relacionados

- ⤵ [Servicios Escolares importa alumnos por CSV](phase0_school_services_import_csv.md) — el tab *Importar* en detalle.
- ⤵ [Cita de cotejo (loop completo)](phase2_appointment_loop.md) — consume los días marcados aquí.
- [Alcance por carrera](engine_officer_scope.md) — **no** se aplica aquí: `_students_ctx`
  (`pages/admin.py:92-121`) filtra solo por `cohort_id`/`q`/`phase`, sin
  `scope_service.officer_programs`. Cualquier encargado con acceso a la página ve el padrón
  completo de la convocatoria, aunque en `/admin/processes` solo vea sus carreras.
- → [Revisión de docs iniciales](phase1_school_services_review_docs.md) — a dónde va el alumno recién dado de alta.
- ← [Glosario: `Cohort`, permisos `cohort.*`](_glossary.md) · [Máquina de estados](00_state_machine.md)

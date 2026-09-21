# El proceso pasa a Titulación: corte a T-soft y bandeja de Liberados

> **Objetivo:** que de la fase 3 (Formato B) en adelante el proceso deje de operarse en
> TitulaTec — lo continúa el Departamento de Titulación en su propio sistema (T-soft) — y que
> quién ya soltó Servicios Escolares sea visible desde algún lado.

| | |
|---|---|
| **Actor(es)** | 👤 Alumno (topado en la fase 3) · 🏛️ Servicios Escolares (libera la fase 2, dictamina documentos) · 🎓 Titulaciones/DEP (supervisión, lee la bandeja) · 🎓 Departamento de Titulación (rol nuevo, dictamina Formato B/documentos/fases — hoy sin ocupantes) · 🤖 los cuatro puntos de aplicación del corte |
| **Permiso(s)** | El corte en sí **no exige ninguno nuevo** — es ortogonal al permiso, igual que sus gemelas ([`engine_student_phase_lock.md`](engine_student_phase_lock.md)). La bandeja **Liberados** sí: `titulatec.handoff.page.list` (ver/filtrar), `titulatec.handoff.api.export` (CSV) |
| **Trigger** | `TitulationProcess.current_phase` alcanza `PhaseService._handoff_phase()` (config `TITULATEC_HANDOFF_PHASE`, default `3`). Hoy solo ocurre por un camino: Servicios Escolares aprueba la fase 2 (Cita de cotejo) |
| **Precondiciones** | Para aparecer en Liberados: `ProcessPhase(phase_number=2).status == 'approved'` (nada que ver con el estado de la cita) |
| **Sub-flujos** | ⤵ extiende cuatro puntos de aplicación: las dos guardas gemelas de [motor de avance / dictamen del admin](engine_approve_advance_phase.md) y [guarda de ejecución del alumno](engine_student_phase_lock.md), más `FormatBService.review` y `DocumentService.review` (ver abajo). ⤵ la bandeja compone [alcance por carrera](engine_officer_scope.md) |
| **Estado final** | El proceso sigue vivo en BD (`current_phase=3`, fase 3 en `in_progress`); ninguna ruta de esta app puede volver a moverlo. Aparece en Liberados hasta que alguien lo dé de alta en T-soft (fuera de esta app: sin acuse, D12) |

Spec: `docs/superpowers/specs/2026-09-21-titulatec-dpto-titulacion-design.md` (no versionado).

---

## Ruta en la app (UI)

1. **Alumno** → `/titulatec/student/dashboard`. La tarjeta grande de la fase actual pierde su
   CTA y pinta el aviso de T-soft; en el acordeón, cualquier fase futura ≥ 3 pinta el mismo
   aviso en vez de «Se habilitará cuando llegues a esta fase».
2. **Titulación / jefatura de la División** → menú admin → **Liberados**
   (`/titulatec/admin/liberados`) → filtra por convocatoria/carrera/modalidad/búsqueda →
   por fila, «Ver expediente» (`/titulatec/admin/processes/{id}`) o el botón «Exportar CSV»
   arriba de la tabla.
3. **Camino que ya no lleva a ningún lado**: el botón «Mover de fase» del expediente
   (`/titulatec/admin/processes/{id}`) sigue existiendo para *cualquier* fase — al usarlo sobre
   una fase ≥ 3 el POST se rechaza con el mismo aviso.

---

## Secuencia

### a) El corte (intento de actuar sobre una fase ≥ 3)

```mermaid
sequenceDiagram
    actor S as Alumno (👤)
    participant FE as Navegador (HTMX)
    participant PS as PhaseService
    actor T as Titulación / Servicios Escolares (🎓🏛️, dictamen)

    S->>FE: GET/POST /student/formato-b... (o cualquier ruta de fase ≥ 3)
    FE->>PS: _phase_guard / _phase_guard_page → assert_student_can_act
    PS-->>FE: ValueError(HANDOFF_MSG) — phase_number >= _handoff_phase()
    FE-->>S: 400 + X-Tt-Error (mutación/parcial) · 302 a /student/dashboard?fase=N (página)

    T->>FE: "Mover de fase" → Aprobar/Rechazar la fase actual (≥3)
    FE->>PS: PhaseService.approve_phase / reject_phase → assert_can_transition
    PS-->>FE: ValueError(HANDOFF_MSG)
    FE-->>T: 400 + X-Tt-Error (toast)

    T->>FE: "Aprobar/Rechazar Formato B" (expediente, fase 3)
    FE->>PS: FormatBService.review → assert_can_transition (n=format_b)
    PS-->>FE: ValueError(HANDOFF_MSG)
    FE-->>T: 400 + X-Tt-Error (toast)

    T->>FE: Dictamina un documento de TIPO congelado (ej. anexo_iii, fase 6)
    FE->>PS: DocumentService.review → dtype.phase_number >= _handoff_phase()
    PS-->>FE: ValueError(HANDOFF_MSG)
    FE-->>T: 400 + X-Tt-Error (toast)
```

### b) Bandeja Liberados (solo lectura)

```mermaid
sequenceDiagram
    actor T as Titulación / jefatura (🎓)
    participant FE as Navegador (HTMX)
    participant API as pages/handoff_admin.py
    participant SVC as HandoffService
    participant DB as Postgres

    T->>FE: abre «Liberados» / cambia un filtro / pagina
    FE->>API: GET /admin/liberados/body?cohort_id=...&program_id=...&q=...
    API->>SVC: list_released(allowed_program_ids=scope, ...)
    SVC->>DB: JOIN ProcessPhase(phase_number=2, status='approved') + User + Program (INNER) + Cohort + Modality (LEFT)
    DB-->>SVC: filas + total
    SVC-->>API: [ReleasedRow], total
    API-->>FE: partials/handoff_table.html
```

---

## Pasos detallados

### El corte

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Notif |
|---|---|---|---|---|---|---|---|
| 1 | 👤 | `/titulatec/student/formato-b`, `/step/{n}` GET/POST y las demás rutas de fase | intenta ejecutar una fase ≥ `_handoff_phase()` | `pages/student.py` (10 rutas guardadas) | `PhaseService.assert_student_can_act` (`services/phase_service.py:214`, vía `_student_action_error`:170-202, chequeo de corte en `:196-198`) | ninguno — corta antes de escribir | ninguno |
| 2 | 👤 | (mutación de fase, vía `FormatBService.submit`) | reenvío de la guarda en el punto de mutación | — | `FormatBService.submit` (`services/format_b_service.py:92-121`) re-invoca `assert_student_can_act` en `:113` | ninguno si falla | ninguno |
| 3 | 🎓/Admin | expediente, botón «Mover de fase» (`_exp_shell.html:34-40`, siempre apunta a `current_phase`) | intenta aprobar/rechazar la fase actual (≥3) | `POST /admin/processes/{id}/phase/{n}/approve` · `/reject` (`pages/admin.py:1551-1604`) | `PhaseService.approve_phase` / `reject_phase` → `assert_can_transition` (`services/phase_service.py:121-133`, vía `_transition_error`:72-106, chequeo de corte en `:99-102`) | ninguno | ninguno |
| 4 | 🎓 | expediente, botones «Aprobar/Rechazar Formato B» (`partials/processes/_exp_phase.html:228-241`, solo visibles con `formato_b.status=='submitted'`) | intenta dictaminar el Formato B de una fase ≥3 | `POST /admin/processes/{id}/format-b/review` (`pages/admin.py:1520-1548`) | `FormatBService.review` (`services/format_b_service.py:123-157`) reusa la MISMA `assert_can_transition` que la fila 3, con `n = format_b` del catálogo (`:146-147`) — cerrado 2026-09-21, commit `99554755` (Ronda 2 de esta tarea) | ninguno | ninguno |
| 5 | 🏛️/🎓 | bandeja Documentos, botones aprobar/rechazar (`partials/documents_body.html:115-120`) | intenta dictaminar un documento cuyo TIPO pertenece a una fase ≥3 | `POST /admin/documents/{process_id}/document/review` (`pages/documents.py:153-195`) | `DocumentService.review` (`services/document_service.py:194-253`) — chequeo PROPIO y angosto (`:224-227`): `dtype.phase_number >= _handoff_phase()`, **no** mira `current_phase` — cerrado 2026-09-21, commit `c75b352f` (Ronda 2 de esta tarea, ver asimetría abajo) | ninguno | ninguno |

### Bandeja Liberados

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Notif |
|---|---|---|---|---|---|---|---|
| 1 | 🏛️ | expediente del proceso, fase 2 | aprueba la Cita de cotejo (el acto de liberación) | `POST /admin/processes/{id}/phase/2/approve` | `PhaseService.approve_phase` (`services/phase_service.py:373-439`) | `titulatec_process_phases`: fase 2 → `status='approved'`, `completed_at=now()`; `titulatec_processes.current_phase=3`; fase 3 → `in_progress` | `ProcessEvent(phase_approved)`, notif `PHASE_APPROVED` al alumno |
| 2 | 🎓 | pestaña **Liberados** (`_ADMIN_NAV`, `pages/nav.py:110`) | abre la bandeja / cambia un filtro / pagina | `GET /admin/liberados` (`pages/handoff_admin.py:104-116`) · `GET /admin/liberados/body` (`:119-132`) | `HandoffService.list_released` (`services/handoff_service.py:143-166`) | solo lectura | ninguno |
| 3 | 🎓 | botón «Exportar CSV» | descarga el CSV de todo lo que cae en su alcance + filtros | `GET /admin/liberados/export.csv` (`pages/handoff_admin.py:135-181`) | `HandoffService.export_rows` (`services/handoff_service.py:169-183`) | solo lectura | ninguno |

---

## Dictamen de Formato B y de documentos: dos guardas más, con una asimetría a propósito

Hasta el 2026-09-21 (ronda de fix 2/3 de esta misma tarea), **ninguno de los dos dictámenes
pasaba por guarda alguna del corte** — dos huecos reales, no hipotéticos, cada uno cerrado en
su propio commit:

- **`FormatBService.review`** (`services/format_b_service.py:123-157`, vía
  `pages/admin.py::fb_review`, `:1520-1548`) — commit `99554755`. Ganó `process` como
  parámetro nuevo y ahora exige `PhaseService.assert_can_transition(db, process, n)` con
  `n` = fase `format_b` del catálogo (`:146-147`), la MISMA función que usan
  `approve_phase`/`reject_phase` (fila 3 de la tabla de arriba). El hueco era real por el
  propio mecanismo de reversión que esta sección documenta: subir `TITULATEC_HANDOFF_PHASE`
  a 9, dejar pasar un Formato B a `submitted`, y volver a bajarlo a 3 dejaba ese Formato B
  aprobable/rechazable para siempre pese al corte — el corte dejaba de ser cierto justo por
  el camino documentado para desactivarlo.
- **`DocumentService.review`** (`services/document_service.py:194-253`, vía
  `pages/documents.py::review`, `:153-195`) — commit `c75b352f`, encontrado **al cerrar el
  de arriba** (mismo patrón exacto: cero guarda, solo permiso y alcance por carrera). Gana
  un chequeo propio y angosto (`:224-227`): rechaza **solo** si `dtype.phase_number >=
  PhaseService._handoff_phase()`, sin mirar `current_phase` en ningún momento.

**La asimetría entre los dos arreglos es deliberada, no un descuido.**
`assert_can_transition` exige `phase_number == process.current_phase` — correcto para
Formato B, porque ese dictamen SIEMPRE es sobre la fase en curso. Aplicarle la misma regla
a documentos **rompería el dictamen tardío**: revisar HOY un acta de la fase 1 con el
proceso ya en la fase 2 (o más adelante) es el **uso normal** de la bandeja de Documentos
(la cola de rezagados), no una excepción — `DocumentService.save` ya trata la fase del
documento como la del TIPO (`dtype.phase_number`), nunca la del proceso, y esta guarda
respeta la misma idea. Por debajo del corte, el comportamiento de Documentos no cambió ni
un ápice; lo único nuevo es que se cierra el dictamen de un documento cuyo TIPO pertenece a
una fase ya congelada (`anexo_iii` fase 6, `ine`/`residency_proof` fase 7,
`final_project`/`presentation` fase 8 — los tipos de las fases 1 y 2 nunca caen en esta
regla, con o sin corte). Endurecer esta guarda para que también exigiera `current_phase`
sería un **defecto nuevo**, no una mejora: cerraría el dictamen tardío legítimo. Hay un
test que fija ese comportamiento como el deseado, para que nadie lo "corrija" sin darse
cuenta (`test_handoff_phase_cut.py`, el caso donde un documento de fase 1 se sigue
dictaminando tarde con el proceso ya en fase 2 y el corte puesto).

Ninguno de los dos arreglos mueve `ProcessPhase`/`current_phase`: no hay auto-avance en
`FormatBService.review` ni en `DocumentService.review`. Los dos cierran el DICTAMEN fuera
de tiempo; no cambian de qué fase va el proceso. Por eso no contradicen la nota de
["Tiene gemela"](engine_approve_advance_phase.md#guarda-de-transición-desde-2026-09):
`assert_can_transition`/`assert_student_can_act` siguen siendo las únicas dos puertas por
las que `current_phase` cambia — `FormatBService.review` solo REUSA la primera para un
dictamen que no toca `current_phase`.

---

## Estado resultante

- `TitulationProcess.current_phase` queda congelado en `PhaseService._handoff_phase()` (3 por
  defecto): con los cuatro puntos de aplicación puestos, ninguna ruta de esta app puede volver
  a moverlo hacia adelante ni hacia atrás, ni dictaminar Formato B o un documento de una fase
  ya congelada.
- El **único** hecho que consulta la bandeja Liberados es
  `ProcessPhase(phase_number=2).status == 'approved'`, resuelto por número de fase vía
  `PhaseService.phase_number_for_code(db, "review_appointment")`
  (`services/handoff_service.py:86`) — nunca a mano. La fecha que se muestra es su
  `completed_at`, no la fecha de la cita ni la de creación del proceso.
- Leer la bandeja o exportar el CSV **no escribe nada**: `HandoffService` no hace `commit` ni
  `add` (docstring de `services/handoff_service.py:18`).
- Un proceso sale en Liberados **una sola vez**: el criterio es la fila `ProcessPhase`, no la
  cita — los intentos múltiples de cotejo (`no_show`, `superseded`, reagendados) no la duplican,
  y el `UNIQUE(process_id, phase_number)` de `titulatec_process_phases` lo garantiza sin
  necesitar `DISTINCT`.

---

## Cómo revertir el corte

Una sola variable, sin migración ni backfill: `TITULATEC_HANDOFF_PHASE` en
`itcj2/config.py:282` (default `3`). Fijarla en **`9`** (o cualquier número por encima de la
última fase del catálogo, hoy 8) y **reiniciar el proceso** desactiva el corte por completo —
`PhaseService._handoff_phase()` (`services/phase_service.py:65-70`) lee `get_settings()`, que
está cacheado, así que sin reinicio el cambio no aplica.

Al revertir: las fases 3-8 vuelven a ser operables por quien tenga los permisos de dictamen
(hoy `titulatec_titulacion`), el alumno recupera el CTA de Formato B, y la bandeja Liberados
sigue funcionando igual (no depende de la variable). Nada de esto toca datos: un `FormatB` que
se quedó en `draft` mientras el corte estuvo puesto sigue en `draft` después de revertir — nadie
lo borra ni lo envía por él.

---

## Caminos alternos / errores ❗

- **Un proceso sin carrera (`program_id IS NULL`) NUNCA aparece en Liberados, ni con alcance
  `"ALL"`.** El `JOIN` con `Program` en `HandoffService._query` es **INNER a propósito**
  (`services/handoff_service.py:104`, comentado en el código): esa cola de reparación es la
  misma que `scope_service` ya trata aparte, y mezclarla aquí la volvería invisible **para
  todos**, no solo para quien tiene alcance acotado. Hoy hay **0 casos** en BD (verificado), pero
  quien opere la bandeja tiene que saberlo — un liberado así de raro quedaría fuera sin ningún
  aviso en pantalla.
- **Los puestos nuevos nacen sin ocupantes.** `head_titulacion` y `aux_titulacion`
  (`database/DML/titulatec/04b_insert_titulacion_department.sql`) se siembran vacíos — el
  Departamento de Titulación no ve nada hasta que un admin le asigne gente desde el organigrama
  del core (`/itcj/config` → organigrama). Es un paso manual del lanzamiento, no un defecto; la
  jefatura de la División (`titulatec_titulaciones`, vía `head_prof_studies_div`) sí puede
  usar la bandeja desde el primer momento porque su puesto ya tiene ocupante.
- **Alcance vacío = bandeja vacía, en silencio.** Igual que el resto de listados con alcance por
  carrera: `scope_service.officer_programs` devolviendo `set()` no es un error, es "no tienes
  carreras asignadas" (`pages/handoff_admin.py:76-78`, `ctx["no_programs"] = True`).
- **`_transition_error`/`_student_action_error` cortan ANTES que la regla de "fase futura"**,
  no después (`services/phase_service.py:99-102`, `:196-198`, con el porqué en el docstring de
  `_student_action_error`): sin ese orden, un alumno parado en la fase 2 que pidiera acción
  sobre la fase 3 leería «se habilitará cuando llegues a ella» — promesa que el corte vuelve
  falsa, porque esa fase ya no se habilita en esta app.
- **Rechazo de fase 2** deja `current_phase = 2`: del lado vivo del corte, nada cambia.
- **El dictamen de Formato B y de documentos también pasa por guarda, desde 2026-09-21** — no
  fue así en la primera versión de esta feature (Tareas 2/3): `FormatBService.review` y
  `DocumentService.review` no comprobaban nada del corte, cada una un hueco real (no
  hipotético) cerrado en su propio commit. Detalle completo, con la asimetría entre las dos
  guardas y por qué es a propósito: ["Dictamen de Formato B y de documentos"](#dictamen-de-formato-b-y-de-documentos-dos-guardas-más-con-una-asimetría-a-propósito),
  arriba.

---

## Flujos relacionados

- ⇄ Gemelas: [motor de avance de fase (dictamen del admin)](engine_approve_advance_phase.md),
  [guarda de ejecución del alumno](engine_student_phase_lock.md) — el corte es la regla que
  comparten los cuatro puntos de aplicación (las dos de arriba, más `FormatBService.review` y
  `DocumentService.review`, ver "Dictamen de Formato B y de documentos" arriba).
- 📐 Reglas de transición y qué significa "liberado": [máquina de estados](00_state_machine.md).
- ⤵ Alcance por carrera que filtra la bandeja: [engine_officer_scope.md](engine_officer_scope.md).
- 🖥️ Donde el alumno lee el aviso: [acordeón de fases](xcut_student_phase_detail.md).
- 🖥️ Donde Titulación abre el expediente desde una fila de la bandeja:
  [expediente del alumno](xcut_admin_process_expediente.md).
- ← Precede: [Cita de cotejo (loop completo)](phase2_appointment_loop.md) — aprobar su fase 2 es
  el trigger de este flujo.
- → Ya no aplica dentro de la app: [el alumno llena el Formato B](phase3_student_formato_b.md)
  (fase 3, hoy congelada por el corte).

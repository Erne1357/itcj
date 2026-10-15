# Reemplazo de un documento en la cita de cotejo

> **Objetivo:** cuando el egresado presenta en la cita de cotejo (fase 2) un documento DISTINTO del que subió
> en la fase 1, la jefatura de Servicios Escolares pide el reemplazo, el egresado lo sube y se aprueba — **sin
> regresar el proceso de fase** y sin romper el congelado del dictamen de la fase 1.

| | |
|---|---|
| **Actor(es)** | 🏛️ Jefatura de Servicios Escolares (pide) · 🏛️ jefa o encargado con `document.api.approve` (aprueba) · 👤 Alumno (sube) |
| **Permiso(s)** | pedir: `titulatec.document.api.request_replacement` (solo `titulatec_school_services_head` y `admin`, D1) · aprobar: `titulatec.document.api.approve` · alumno: `document.api.upload.own` |
| **Trigger** | En la cita, el egresado trae en físico otro documento válido que el subido en la fase 1 |
| **Precondiciones** | Proceso `active`, `current_phase` == fase `review_appointment` del catálogo y esa `ProcessPhase` **no** `approved`; el tipo es de la fase `initial_docs` y está en el set del perfil; el documento tiene fila |
| **Sub-flujos** | ⤵ [bandeja de Documentos](phase1_school_services_review_docs.md) · ⤵ [panel de la cita](phase2_appointment_loop.md) · ⤵ [expediente](xcut_admin_process_expediente.md) · ⤵ [el alumno sube](phase1_student_upload_initial_docs.md) · ⤵ [correos](xcut_student_email_notifications.md) |
| **Estado final** | Documento `approved` con `replacement_requested_at = NULL`; la fase 2 puede liberarse otra vez |

Spec: `docs/superpowers/specs/2026-10-15-titulatec-reemplazo-cotejo-design.md`. Estados: [máquina de
estados](00_state_machine.md#reemplazo-abierto-en-el-cotejo-2026-10-15).

## Por qué existe

`DocumentService.review` congela el dictamen en cuanto el proceso pasó la fase del documento
(`PHASE_CLOSED_MSG`, decisión 2026-10-04: rechazar tarde dejaba al alumno trabado) y la guarda del alumno
cierra Documentos fuera de la fase 1. Sin una vía aparte, el documento físico distinto no podía volverse el
«oficial». **La regla de congelado no cambió**; esta es una vía aparte con permiso propio.

## Modelo: «reemplazo abierto»

`titulatec_documents.replacement_requested_at` (`DateTime`, NULL; `models/document.py:41`; migración
`tt20261015a`) es la **bandera** del reemplazo. La escribe solo `DocumentService.request_replacement` (la
primera vez: pedirlo otra vez conserva la fecha) y la limpia solo `DocumentService.review(status="approved")`.
`save()` (la resubida) no la toca. No guarda «quién»: lo guardan el `ProcessEvent` y la bitácora.
`review_status` no cambia de dominio: pedir = `rejected` + `review_note` = motivo + `reviewed_by_id` = la jefa;
el alumno sube → `pending`; se aprueba → `approved` y el reemplazo se cierra.

**Reemplazo ABIERTO = bandera no NULL *y* `review_status != "approved"`** (Ruling R7 de la revisión final).
Un solo predicado, `DocumentService.replacement_open(status, requested_at)` (`services/document_service.py:997`,
puro) con su gemelo SQL `_replacement_open_sql()` (`:1020`); lo consultan todos los que deciden «abierto»:
`open_replacements` (y por él la compuerta de la fase 2 y los avisos del alumno), `student_can_replace`,
`save()`, `initial_docs_approved_map(replacement_ok=)` y las banderas `replacement` de la bandeja
(`pages/documents.py::_doc_states`), del panel de Citas (`pages/appointments.py::_detail_ctx`) y del expediente
(`pages/admin.py::_detail_ctx`). Un `approved` con la bandera puesta —solo pasa tras una reversa: el código viejo
aprueba sin limpiarla— es un reemplazo **cerrado** en todas partes. Antes, la compuerta lo contaba abierto y la
fase 2 quedaba trabada para siempre (aprobar otra vez un `approved` de una fase pasada da `PHASE_CLOSED_MSG`),
mientras la subida del alumno lo daba por cerrado.

## Ruta en la app (UI)

Tres sitios para **pedir** (D5), uno para **subir**, dos para **aprobar**:

1. 🏛️ **Bandeja Documentos** (`/titulatec/admin/documents`): con la fase 1 ya cerrada y el proceso en cotejo,
   botón «Pedir reemplazo» junto al dictamen; usa el motivo del formulario. La fila lleva la píldora
   «Reemplazo en cotejo».
2. 🏛️ **Panel «Atender» de la cita** (`/titulatec/admin/appointments`): bajo el visor del documento abierto,
   «Pedir reemplazo» (abre un textarea por `&reemplazo=<code>`) y, si el alumno ya subió, «Aprobar reemplazo».
3. 🏛️ **Expediente** (`/titulatec/admin/processes/{id}`): en la lista de documentos de la fase 1, `<details>`
   «Pedir reemplazo» con motivo obligatorio y la píldora «Reemplazo pedido en cotejo».
4. 👤 **Alumno**: aviso con botón «Subir reemplazo» en el tablero (tarjeta de la fase de cotejo) y en «Mi
   cita»; lleva a `/titulatec/student/documents`, que se pinta en **modo reemplazo** (solo el documento
   pedido es subible, el resto de solo lectura, sin borrar).
5. 🏛️ **Aprobar**: el Aprobar de siempre de la bandeja Documentos (el reemplazo subido entra a «Por evaluar») o
   «Aprobar reemplazo» del panel de la cita.

## Secuencia

```mermaid
sequenceDiagram
    actor J as 🏛️ Jefa
    actor A as 👤 Alumno
    participant FE as Navegador (HTMX)
    participant API as pages/*
    participant DS as DocumentService
    participant DB as Postgres
    J->>FE: «Pedir reemplazo» + motivo
    FE->>API: POST .../reemplazo
    API->>API: assert_process_in_scope · _exigir_bandeja/_vista_completa
    API->>DS: request_replacement(process_id, type_code, note, actor_id)
    DS->>DB: proceso FOR NO KEY UPDATE (R9) · Document FOR UPDATE
    DS->>DB: Document rejected + review_note + replacement_requested_at
    DS->>DB: ProcessEvent document_replacement_requested · aviso DOCUMENT_REPLACEMENT_REQUESTED · outbox docs_review
    API-->>FE: re-render + X-Tt-Notice
    A->>FE: abre el aviso → Documentos (modo reemplazo)
    FE->>API: POST /student/documents/{type_code}
    API->>DS: student_can_replace → save()
    DS->>DB: Document FOR UPDATE · ¿sigue abierto? (R8) → archivo → pending (replacement_requested_at intacta)
    J->>FE: Aprobar (bandeja o panel de la cita; el panel manda la versión vista)
    FE->>API: POST .../document/review · .../documents/{code}/aprobar (version)
    API->>DS: review(approved[, expected_version])
    DS->>DB: Document FOR UPDATE · ¿misma versión? (R10, panel) → approved · NULL · document_approved {replacement: true}
```

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Notif |
|---|---|---|---|---|---|---|---|
| 1a | 🏛️ | Bandeja Documentos | pedir reemplazo | `POST /titulatec/admin/documents/{pid}/document/reemplazo` (form `type_code`, `note`) — `pages/documents.py:509` | `DocumentService.request_replacement` (`services/document_service.py:899`) | `titulatec_documents`: `rejected`, `review_note`, `reviewed_by_id`, `replacement_requested_at` | `document_replacement_requested` (fase de cotejo, `{type_code, note}`) · notif `DOCUMENT_REPLACEMENT_REQUESTED` · correo `docs_review` (rechazo) |
| 1b | 🏛️ | Panel de Citas | ídem | `POST /titulatec/admin/appointments/{pid}/documents/{type_code}/reemplazo` (`note`) — `pages/appointments.py:2213` | ídem | ídem | ídem |
| 1c | 🏛️ | Expediente | ídem | `POST /titulatec/admin/processes/{pid}/documents/{type_code}/reemplazo` (`note`) — `pages/admin.py:2611` | ídem | ídem | ídem |
| 2 | 👤 | `/student/documents` (modo reemplazo) | sube el reemplazo | `POST /student/documents/{type_code}` — `pages/student.py:1270` | `DocumentService.student_can_replace` → `save()` (`:635`, re-verifica con la fila bloqueada, R8) | `pending`, nota y revisor limpios; `version` suma 1; **la bandera sigue abierta** | `document_uploaded` |
| 3a | 🏛️ | Bandeja Documentos | aprobar (Aprobar de siempre) | `POST /titulatec/admin/documents/{pid}/document/review` | `DocumentService.review(approved)` (`:761`) | `approved`, `replacement_requested_at = NULL` | `document_approved` con `replacement: true` · correo `docs_review` |
| 3b | 🏛️ | Panel de Citas | «Aprobar reemplazo» | `POST /titulatec/admin/appointments/{pid}/documents/{type_code}/aprobar` (form `version`, por `hx-vals`) — `pages/appointments.py:2265` → `_cuerpo_document_replacement_approve` (`:2293`) | `open_replacements` (exige abierto, si no 400) → `review(approved, expected_version=version)`; otra versión o sin versión → 200 + aviso, sin aprobar (R10) | ídem | ídem |
| 4 | 🏛️ | Cita / expediente | liberar la fase 02 | `POST /{pid}/fase2/aprobar` · `POST .../phase/{n}/approve` | `PhaseService.approve_phase` → `_cotejo_gate_error` (`services/phase_service.py:327`) | — | se **niega** con un reemplazo abierto (ver abajo) |

Reglas de `request_replacement` (en este orden, todas `ValueError` ASCII sin escribir nada): motivo no vacío
tras `strip()` y ≤ `REPLACEMENT_NOTE_MAX` = 1000; el proceso existe y está `active`; `current_phase` == fase de
cotejo (sin esa fase en el catálogo falla CERRADO) y esa `ProcessPhase` no está `approved`; el tipo es de la
fase `initial_docs`, está activo y en el set del perfil (`initial_doc_types_for`); el documento existe (se
bloquea con `with_for_update`). Antes de validar la fase bloquea la fila del **proceso** (R9, abajo). Pedirlo desde
`pending` + abierto vale (archivo equivocado) y conserva la fecha.
Aprobar un `rejected` + abierto sin resubida es «el original sí sirve» y cierra el reemplazo. Las rutas de
admin traducen el `ValueError` a `400` + `X-Tt-Error`; el éxito re-renderiza el contenedor de la vista +
`X-Tt-Notice` (+ `X-Tt-Notice-Kind: success`; la bandeja también, percent-encoded con su `_hdr`, R12). Las
tres rutas de «pedir» y la de «Aprobar reemplazo» son `async def` solo para leer el form y terminan en
`run_in_threadpool(_cuerpo_…)`, con `assert_process_in_scope` primera sentencia del `try`.

## Concurrencia (revisión final, Rulings R8–R10)

Tres carreras que la primera versión dejaba abiertas, cada una cerrada con un bloqueo de fila:

- **Subida en vuelo vs. aprobación (R8).** La guarda de la ruta del alumno (`student_can_replace`) corre en
  otra transacción que su `save()`; entre las dos la jefa podía aprobar el reemplazo y la subida lo pisaba
  (archivo y dictamen de vuelta a `pending`, fase 2 liberable con un documento sin dictaminar). Ahora
  `save()` y `review()` leen la fila con `DocumentService._locked_document` (`:572`, `SELECT … FOR UPDATE` +
  `populate_existing`) y se serializan; `save()` lo hace **antes de tocar el disco** (el nombre del archivo
  es fijo por tipo) y, si el tipo es de una fase que el proceso ya pasó, exige ahí mismo `replacement_open`
  o levanta `REPLACEMENT_CLOSED_MSG` («El reemplazo de este documento ya se cerro: ya no admite cambios.»)
  sin escribir nada (`services/document_service.py:683-690`). La fase actual y las futuras no cambian.
- **Pedir vs. liberar la fase 2 (R9).** `request_replacement` bloquea la fila del proceso (`FOR NO KEY UPDATE`,
  `key_share=True`, mismo modo que `ProcessService.cancel`) antes de validar la fase, y
  `PhaseService.approve_phase` toma el mismo bloqueo **solo** cuando libera `PHASE_COTEJO`, antes de su
  compuerta (`services/phase_service.py:422-425`). O el pedido ve la fase ya liberada, o la liberación espera y
  ve el reemplazo abierto. `NO KEY` no choca con el `FOR KEY SHARE` de los INSERT con FK al proceso.
- **Aprobar el archivo que se vio (R10, solo el panel de Citas).** «Aprobar reemplazo» manda la `version` que
  pintó (`hx-vals`) y `review(..., expected_version=)` la compara con la fila bloqueada; si cambió levanta
  `DocumentVersionChanged` (`:7`, subclase de `ValueError`), y sin versión (o ilegible) la ruta ni lo intenta:
  en los dos casos responde **200** + re-render + `X-Tt-Notice` «El alumno cambió el archivo: revísalo antes de
  aprobar.» (`X-Tt-Notice-Kind: warning`; htmx no hace swap en 4xx). El visor pide
  `…/document/{code}?v={version}`: con el archivo nuevo su `src` cambia y el morph lo recarga. La bandeja
  Documentos NO cambia (su Aprobar es el dictamen de siempre).

## Lo que bloquea y lo que no

- **Bloquea liberar la fase 2 (D4).** `DocumentService.replacement_gate_error` (`:1097`) lo consulta
  `PhaseService._cotejo_gate_error` (`services/phase_service.py:356-358`) **antes** que los requisitos de
  cotejo: «No se puede liberar la fase 02: falta aprobar el reemplazo de: {nombres}.». Aplica a las dos vías
  de aprobar la fase 2 (la cita y el expediente, que es también «Mover de fase»); el mensaje lleva acentos, así
  que las rutas lo pasan por `_hdr()`.
- **No bloquea agendar (D2).** La cola del encargado cuenta un documento con reemplazo abierto como «ok»
  (`initial_docs_approved_map(..., replacement_ok=True)`, `services/appointment_service.py:411`); el
  auto-avance 1→2 de la bandeja sigue con la regla estricta. `AppointmentService.create` nunca miró documentos.
- **No se puede borrar** el documento fuera de la fase 1 (sin excepción); solo subir.

## Estado resultante

- Tras pedir: documento `rejected` + abierto; el alumno recibe aviso, correo y el aviso del tablero/«Mi cita».
- Tras subir: `pending` + abierto («Reemplazo subido · por aprobar» al personal; «Tu reemplazo está en
  revisión» al alumno). El motivo ya no está en la fila (`save()` limpia el dictamen); sigue en el evento.
- Tras aprobar: `approved`, `replacement_requested_at = NULL`; si era el último abierto, la fase 2 se puede
  liberar.

## Eventos, avisos y correos

- `ProcessEvent` `document_replacement_requested` (`models/process_event.py:39`), `phase_number` = fase de
  cotejo, payload `{type_code, note}`. Etiqueta del alumno en `_EVENT_LABELS` («Servicios Escolares te pidió
  reemplazar un documento», `pages/student.py:290`) y del personal en `_EVENT_UI` («Reemplazo de documento
  solicitado», `arrow-repeat`, `amber`, `pages/admin.py:1328`). El espejo de la bitácora lo cubre el prefijo
  `document_` (`services/audit_actions.py:158`).
- Aviso in-app `DOCUMENT_REPLACEMENT_REQUESTED` («{nombre}: {motivo}»), cuya liga `/student/fase/2` redirige al
  tablero: el aviso `partials/student/_replacement_notice.html` es el destino real.
- Correo: el de dictamen de siempre, `StudentMail.doc_reviewed(status="rejected", note=motivo)`, grupo
  `docs:{pid}`, que lleva a Documentos (ahora en modo reemplazo). Sin `kind` nuevo.

## Caminos alternos / errores ❗

- Motivo vacío → 400 `X-Tt-Error` (en el panel de Citas, antes de abrir sesión). Proceso fuera de alcance → 404.
  Sin permiso → 403. Vista resumida del Departamento de Titulación (expediente) → 403.
- Proceso no en cotejo / fase 2 ya liberada / tipo fuera del set / sin documento → 400 con el
  `REPLACEMENT_*_MSG` correspondiente.
- «Aprobar reemplazo» del panel sobre un documento sin reemplazo abierto (incluido un `approved` con la
  bandera vieja, R7) → 400 «Ese documento no tiene un reemplazo pendiente.».
- «Aprobar reemplazo» con otra versión en la fila, o sin versión → 200 + re-render + aviso de advertencia,
  sin aprobar (R10).
- El alumno intenta subir un documento sin reemplazo abierto (o `approved`) estando en la fase 2 → el 400 de
  la guarda de fase de siempre. Si la guarda pasó pero el reemplazo se aprobó antes de que llegara su
  `save()` → 200 con el slot re-pintado y `X-Tt-Error` `REPLACEMENT_CLOSED_MSG` (R8); nada se escribe.

## Despliegue y reversa

1. Fusionar → `deploy.sh` aplica `tt20261015a` (columna NULL —el código viejo la ignora— y corrige
   `version`).
2. Copiar `database/DML/titulatec/reemplazo_2026_10/` (gitignored) al servidor →
   `titulatec init-reemplazo-docs --dry-run` → real. Corre SOLO el `27_insert_doc_replacement_perm.sql` (nunca
   el 15), invalida solo titulatec y verifica los dos roles. Hasta este paso nadie ve «Pedir reemplazo».
3. `STATIC_VERSION` sube (cambia `doc-viewer.js`).

**Reversa:** `rollback.sh` primero. El downgrade a `tt20261013b` es opcional y PIERDE los reemplazos abiertos;
antes, aprobarlos o listarlos con `SELECT process_id, type_code FROM titulatec_documents WHERE
replacement_requested_at IS NOT NULL;`. Con el código viejo, un documento `rejected` en fase 2 deja otra vez al
alumno sin poder subirlo.

Si se volvió al código viejo SIN bajar la migración y luego se re-despliega, el código viejo pudo aprobar
documentos sin limpiar la bandera. El predicado R7 ya los trata como cerrados (no traban la fase 2 ni pintan
avisos), pero conviene limpiar la columna:
`UPDATE titulatec_documents SET replacement_requested_at = NULL WHERE review_status = 'approved' AND replacement_requested_at IS NOT NULL;`

## Fuera de alcance

Recordatorios por reemplazo abierto; el motivo en el Tablero de la jefa; el botón dentro del modal grande del
visor de la bandeja; reemplazar documentos de fases ≥ 3; que Servicios Escolares suba el archivo por el alumno.

## Qué lo cubre

`tests/fastapi/titulatec/`: `test_document_replacement.py` (service; revisión final: `TestPredicadoUnico` R7,
`TestCarreraSubirVsAprobar` R8 —la carrera determinista guarda → `review(approved)` → `save` levanta con el
archivo intacto—, `TestBloqueoDelProceso` R9 —orden de las sentencias— y `TestAprobarLaVersionVista` R10),
`test_document_version.py` (versión + SQL de la migración), `test_documents_replacement.py` (bandeja; R7 y R12),
`test_appt_doc_replacement.py` (panel de la cita; R7, R10 y liberar la fase 2 con un reemplazo abierto),
`test_expediente_replacement.py` (R7 y `phase/2/approve` con un reemplazo abierto),
`test_student_replacement.py` (modo reemplazo, posgrado R11, tablero y «Mi cita» con R7),
`test_document_service.py` (los mocks de `review` leen la fila bloqueada),
`test_cli_init_reemplazo_docs.py`; los censos `test_scope_guard.py` (29 rutas con `{process_id}`) y
`test_permissions_contract.py` (103 permisos).

## Flujos relacionados

- ← [El alumno sube sus documentos iniciales](phase1_student_upload_initial_docs.md) (fase 1; aquí se reabre).
- ↔ [Revisión de documentos](phase1_school_services_review_docs.md) (el congelado y su excepción).
- ↔ [Cita de cotejo](phase2_appointment_loop.md) · [Expediente](xcut_admin_process_expediente.md).
- ⤵ [Correos del proceso](xcut_student_email_notifications.md).

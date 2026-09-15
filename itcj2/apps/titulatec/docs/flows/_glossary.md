# Glosario · entidades, tablas, roles, permisos

> Referencia para enlazar desde los flujos. No describe pasos; describe **qué es cada cosa**.
> Verificado contra el código y la BD de dev el **2026-09-01** (alembic `s1e2s3s4v001`, seeders
> `database/DML/titulatec/00..07` cargados). Las piezas de la liberación GTV de la encuesta de
> egresados (`SurveyReview`, rol `titulatec_tech_management`, permisos `survey_review.*`,
> `SurveyReviewService`) se verificaron aparte contra código y BD el **2026-09-15**; el resto de
> este archivo NO se re-auditó a esa fecha y puede haber quedado atrás de otras apps de la misma
> campaña (encuesta, solicitudes de inscripción, espacios de cotejo) — ver las notas fechadas
> 2026-09-15 en este mismo archivo para lo que sí se corrigió.

## Entidades / tablas (`titulatec_*`)

17 tablas; una clase por tabla en `itcj2/apps/titulatec/models/` (el prefijo `titulatec_` va solo en
`__tablename__`, no en el nombre de clase).

| Clase (inglés) | Tabla | Qué guarda | Campos clave |
|---|---|---|---|
| `Cohort` | `titulatec_cohorts` | Convocatoria por período académico | `period_id`, `name`, `opens_at`, `closes_at` (cierre de **inscripción**), `status` (`draft`/`open`/`closed`) |
| `CohortReviewDay` | `titulatec_cohort_review_days` | Días habilitados para cotejo, por convocatoria | `cohort_id`, `date` · `UNIQUE(cohort_id, date)` |
| `CotejoRequirement` | `titulatec_cotejo_requirements` | Requisitos "qué llevar a la cita", configurables por convocatoria | `cohort_id`, `label`, `hint`, `icon`, `order_index`, `is_required`, `info_html` (HTML sanitizado con `utils/rich_text.py`, 2026-09-15) |
| `Modality` | `titulatec_modalities` | Catálogo de modalidades (4 sembradas) | `code`, `requires_synodals`, `signature_rule` (`president_only`/`all_synodals`), `skips_phases` (JSON) |
| `TitulationProcess` | `titulatec_processes` | Proceso raíz, `UNIQUE(student_id, cohort_id)` | `folio` (`TT-{period}-{NNNN}`), `student_id`, `cohort_id`, `program_id`, `modality_id`, `current_phase` (0–8), `status` (`active`/`completed`/`cancelled`/`on_hold`), `is_app_active` |
| `ProcessPhase` | `titulatec_process_phases` | Instancia de cada fase del proceso | `phase_number` (0–8), `status` (`pending`/`in_progress`/`in_review`/`approved`/`rejected`/`skipped`), `completed_at`, `reviewed_by_id`, `rejection_reason` |
| `PhaseDefinition` | `titulatec_phase_definitions` | Catálogo de las 9 fases | `number`, `code`, `name`, `responsible`, `icon`, `order_index` |
| `DocumentType` | `titulatec_document_types` | Catálogo de tipos de doc (9 sembrados) | `code`, `name`, `phase_number`, `file_kind` (`pdf`/`image`), `max_size`, `is_versionable` |
| `Document` | `titulatec_documents` | Archivo subido; **una fila por (proceso, tipo)**: `UNIQUE(process_id, type_code)` | `phase_number`, `file_path` (relativa a `TITULATEC_UPLOAD_PATH`), `review_status` (`pending`/`approved`/`rejected`), `review_note`, `version` (contador informativo) |
| `FormatB` | `titulatec_format_b` | Formato B (PK = `process_id`) | `status` (`draft`/`submitted`/`approved`/`rejected`), datos personales/escolares, `project_name`, `rejection_reason` |
| `ReviewAppointment` | `titulatec_review_appointments` | Cita de cotejo (fase 2) | `process_id`, `scheduled_at`, `location`, `status` (`scheduled`/`confirmed`/`in_progress`/`attended`/`no_show`), `confirmed_at`, `note`, `created_by_id` |
| `SurveyReview` | `titulatec_survey_reviews` | Solicitud de liberación de GTV para el requisito de cotejo `graduate_survey` (fase 2); una por proceso, nace al enviar la encuesta (2026-09-15) | `process_id` (FK `titulatec_processes`, UNIQUE), `response_id` (FK `titulatec_survey_responses`), `status` (`in_review`/`approved`/`rejected`), `rejection_reason`, `reviewed_by_id`, `reviewed_at`, `submitted_at` |
| `ProcessEvent` | `titulatec_process_events` | Auditoría / timeline | `event_type`, `phase_number`, `actor_id`, `payload` (JSON) |
| `SynodalAssignment` | `titulatec_synodal_assignments` | Sinodales asignados (fase 4) | `user_id`, `role` (`president`/`secretary`/`vocal`), `vote` (`approved`/`changes_requested`), `vote_note`, `assigned_by_id` |
| `ProcessChat` | `titulatec_chats` | Chat de titulación, 1 por proceso (`process_id` único) | `pinned_document_id` |
| `ChatMessage` | `titulatec_chat_messages` | Mensaje del chat | `chat_id`, `author_id`, `body`, `attachment_path`, `parent_id` (reply) |
| `Ceremony` | `titulatec_ceremonies` | Acto protocolario (fase 8) | `cohort_id`, `scheduled_at`, `room`, `whatsapp_group_url`, `status` (`pending`/`scheduled`/`done`) |
| `CeremonyProcess` | `titulatec_ceremony_processes` | Alumnos dentro de un acto (M2M) | `ceremony_id`, `process_id`, `final_project_path`, `presentation_path` |

> FK a alumnos/usuarios: `core_users.id` (**BigInteger**). Carrera: reusa `core_programs`.
> Período: `core_academic_periods` (vía `Cohort.period_id`).

## Roles (en app `titulatec`)

`core_roles` es **global** (la tabla no tiene `app_id`); el amarre a la app va por
`core_user_app_roles` (directo) o `core_position_app_roles` (por puesto). El conteo son los permisos
de la app `titulatec` que el rol tiene hoy en `core_role_permissions`.

| Rol (`core_roles.name`) | Cómo se asigna hoy | Perms titulatec | Emoji |
|---|---|---|---|
| `graduate` (egresado, desde 2026-09-15) | **directa** en cada alta: `ImportService.import_rows` → `_sync_graduate_roles` (`services/import_service.py:81`) — CSV, alta manual, aprobación de bandeja y liga de activación son los cuatro caminos | 21 (+2 de `itcj`) | 👤 |
| `student` (global — **ya NO** es el alumno de titulación) | rol de **AgendaTec**; `03_insert_role_permissions.sql` le revoca en cada corrida todo lo de `titulatec` que le quedara; `core_users.role_id` conserva el alias en filas viejas que no han pasado por el backfill | 0 | — |
| `titulatec_school_services` | por puesto: `aux_school_services`, `secretary_school_services`. Es también el rol que reciben los **encargados** dados de alta desde la pestaña Encargados (`pages/officers.py:13`, `ROLE_ASSIGNED`) | 22 | 🏛️ |
| `titulatec_school_services_head` | por puesto: `head_school_services` | 27 | 🏛️ |
| `titulatec_titulaciones` | por puesto: `head_prof_studies_div`, `secretary_prof_studies_div`, `aux_prof_studies_div` | 20 | 🎓 |
| `titulatec_tech_management` | por puesto: `head_tech_management` (jefatura de GTV, ya en el organigrama del core) + `external_service_tech_management` («Servicio Externo», puesto NUEVO 2026-09-15, `allows_multiple=TRUE`) — `05_insert_position_app_roles.sql` | 9 | 🛠️ |
| `titulatec_vinculacion` | por puesto: los 5 `coord_vinculacion_*` (`database/DML/titulatec/04_insert_vinculacion_positions.sql`) | 13 | 🔗 |
| `titulatec_sinodal` | **sin ruta de asignación en el código todavía**: 0 filas en `core_position_app_roles` y ningún `grant_role`; solo aparece en el resolver de dashboard (`pages/nav.py:61`) | 14 | 🧑‍⚖️ |
| `admin` (global) | fuera de la app | **0** | — |

> ⚠️ El rol `admin` **no** trae permisos de titulatec, y `require_page_app` **no** tiene bypass de
> admin global: resuelve `cached_has_assignment` + `cached_perms` contra BD
> (`itcj2/dependencies.py:118-137`). Un admin global sin asignación a la app recibe `PageForbidden`.
> Su único trato especial en la app es el ruteo del landing (`pages/nav.py:68-69`).

### Encargados con alcance por carrera

"Encargado" no es un rol nuevo: es un `Position` `se_officer_{hex}` que
`OfficerService.create_officer()` (`services/officer_service.py:88-101`) crea dentro del departamento
que dirige el manager, con `PositionAppRole` → `titulatec_school_services` y `ProgramPosition` → las
carreras. El alcance se lee después con `scope_service.officer_programs()`. Ver
[engine_officer_scope](engine_officer_scope.md).

### GTV: dos puestos, sin alcance por carrera (2026-09-15)

Gestión Tecnológica y Vinculación (GTV, `core_departments.code = 'tech_management'`) llega al
rol `titulatec_tech_management` por DOS puestos, sin `ProgramPosition` de por medio — GTV ve
**todas** las solicitudes, no una por carrera:

- `head_tech_management` — jefatura de GTV, ya existía en el organigrama del core (no lo crea
  el DML de titulatec).
- `external_service_tech_management` — título «Servicio Externo» (Residencias, Prácticas,
  Servicio Social), puesto NUEVO (`04_insert_vinculacion_positions.sql`), `allows_multiple =
  TRUE`: no es una sola persona, y no tiene ocupante fijo por diseño (se asigna a quien esté de
  ventanilla desde `/itcj/config/positions/{id}`).

Detalle completo del flujo que habilita: [liberación GTV de la encuesta de
egresados](phase2_tech_management_survey_release.md).

## Permisos (`titulatec.{modulo}.{tipo}.{accion}[.scope]`)

Son dos cosas distintas y aquí van como dos columnas:

- **Definidos en BD** — sembrados por `database/DML/titulatec/02_insert_permissions.sql` (+ `07`,
  `08`, `survey_2026_09/09`); hoy **80** filas en `core_permissions` para la app (verificado en
  BD, 2026-09-15).
- **Exigidos por el código** — los que aparecen en un `require_page_app(..., perms=[...])` o en una
  entrada del menú `_ADMIN_NAV`; **39** códigos distintos a la fecha de la última auditoría
  (2026-09-01) — cifra sin recalcular tras `07`/`08`/`survey_2026_09` (requisitos de cotejo,
  espacios de cotejo, encuesta/solicitudes/liberación GTV), así que hoy es un PISO, no el total
  vigente.

Un permiso definido y no exigido **no es un error**: es capacidad ya modelada para fases que aún no
tienen pantalla. En sentido contrario sí sería bug, y hoy no lo hay: los 39 exigidos existen en BD.

| Módulo | Definidos en BD | Exigidos por el código |
|---|---|---|
| `appointment` (7) | `page.list`, `page.my`, `api.create`, `api.update`, `api.reschedule`, `api.mark_attended`, `api.confirm.own` | **los 7** |
| `ceremony` (5) | `page.list`, `page.my`, `api.create`, `api.update`, `api.upload.own` | `page.list` (solo como ítem de menú, `pages/nav.py:102`, con URL `#`) |
| `chat` (5) | `page.view`, `api.read`, `api.send`, `api.upload`, `api.pin_document` | — |
| `cohort` (8) | `page.list`, `page.detail`, `api.read`, `api.create`, `api.update`, `api.import_csv`, `api.review_days`, `api.cotejo_reqs` | `page.list`, `api.create`, `api.import_csv`, `api.review_days` |
| `dashboard` (6) | `student`, `school_services`, `titulaciones`, `sinodal`, `vinculacion`, `admin` | **los 6** |
| `document` (7) | `page.list`, `api.upload.own`, `api.read.own`, `api.read.all`, `api.delete.own`, `api.approve`, `api.reject` | **los 7** |
| `format_b` (7) | `page.fill`, `api.save`, `api.submit`, `api.read.own`, `api.read.all`, `api.approve`, `api.reject` | `page.fill`, `api.save`, `api.approve`, `api.reject` |
| `notifications` (2) | `api.read.own`, `api.mark_read` | — |
| `officers` (2) | `page.list`, `api.manage` | **los 2** |
| `process` (11) | `page.my`, `page.list`, `page.detail`, `api.read.own`, `api.read.all`, `api.read.department`, `api.advance`, `api.approve_phase`, `api.reject_phase`, `api.cancel`, `api.hold` | `page.my`, `page.list`, `page.detail`, `api.read.own`, `api.read.all`, `api.advance`, `api.approve_phase`, `api.reject_phase` |
| `survey_review` (3, 2026-09-15) | `page.list`, `api.approve`, `api.reject` | **los 3** (`pages/survey_reviews_admin.py`, bandeja de GTV) |
| `synodal` (6) | `page.list`, `page.my_reviews`, `api.assign`, `api.read`, `api.release`, `api.vote` | — |

Definidos y todavía sin exigir (27): todo `chat.*`, todo `synodal.*`, todo `notifications.*`,
`ceremony.{page.my, api.create, api.update, api.upload.own}`,
`cohort.{page.detail, api.read, api.update, api.cotejo_reqs}`,
`format_b.{api.submit, api.read.own, api.read.all}`,
`process.{api.cancel, api.hold, api.read.department}`.

Dónde se exigen los menos obvios:

| Permiso | Sitio |
|---|---|
| `titulatec.officers.page.list` | `pages/officers.py:41`, `pages/nav.py:101` |
| `titulatec.officers.api.manage` | `pages/officers.py:56, 81, 103` |
| `titulatec.document.page.list` | `pages/documents.py:14` (`_VIEW_PERMS`), `pages/nav.py:98` |
| `titulatec.cohort.api.review_days` | `pages/admin.py:244, 257, 399` |
| `titulatec.process.api.read.all` | `pages/admin.py:25` (`_PROCESS_VIEW_PERMS`) y, como discriminador de alcance, `services/scope_service.py:12` |
| `titulatec.ceremony.page.list` | solo `pages/nav.py:102` |

Quién los tiene en BD hoy (los de puerta):

| Permiso | Roles |
|---|---|
| `cohort.page.list`, `appointment.page.list` | `titulatec_school_services`, `titulatec_school_services_head` |
| `process.page.list`, `document.page.list` | `titulatec_school_services`, `titulatec_school_services_head`, `titulatec_titulaciones` |
| `officers.page.list`, `officers.api.manage`, `cohort.api.review_days`, `cohort.api.cotejo_reqs` | solo `titulatec_school_services_head` |
| `process.api.read.all` (⇒ alcance `"ALL"`) | `titulatec_school_services_head`, `titulatec_titulaciones` |
| `ceremony.page.list` | solo `titulatec_titulaciones` |
| `survey_review.page.list`, `survey_review.api.approve`, `survey_review.api.reject` | solo `titulatec_tech_management` (2026-09-15) |

> Authz en páginas: **todas** las rutas usan `require_page_app("titulatec", perms=[...])` (any-of, sin
> bypass de admin). Ninguna usa `require_perms`. Reparto completo por rol en
> [`plan/02_roles_permissions.md`](../../plan/02_roles_permissions.md).
> `user["sub"]` es **string** → `int(user["sub"])`.

## Servicios

11 de los ~19 módulos en `itcj2/apps/titulatec/services/` están documentados abajo (lista
PARCIAL, no exhaustiva — quedan fuera `cohort_service`, `email_helper`,
`enrollment_request_service`, `process_service`, `requirement_service`,
`review_window_service`, `slot_service` y `survey_service`: deuda de documentación de la
campaña de encuesta/convocatoria anterior a esta tarea).

| Símbolo | Archivo | Responsabilidad |
|---|---|---|
| `PhaseService` | `services/phase_service.py` | Motor de fases: `approve_phase`/`reject_phase`, salto de fases según la modalidad (`_skips`/`_next_applicable`) y log de `ProcessEvent`. **Y las dos guardas**: `assert_can_transition` (dictamen 🏛️🎓) y `assert_student_can_act` (ejecución 👤) — [guarda de fase del alumno](engine_student_phase_lock.md) |
| `DocumentService` | `services/document_service.py` | Guardar/leer/borrar documentos y `review()`; además las consultas de elegibilidad `initial_docs_all_approved` y `list_phase_document_types` |
| `FormatBService` | `services/format_b_service.py` | Formato B multi-step: `get_or_create`, `save_step`, `submit(db, fb, process)` (reaplica la guarda de fase), `review`, `to_ctx` |
| `ImportService` | `services/import_service.py` | Import CSV de la convocatoria: `parse` → `autodetect_mapping` → `build_preview` → `import_rows` (crea/empata usuario, otorga rol `graduate` y revoca `student` vía `_sync_graduate_roles`, crea proceso + sus 9 `ProcessPhase`) |
| `AppointmentService` | `services/appointment_service.py` | Cita de cotejo (fase 2): `create`, `reschedule`, `start`, `mark_attended`, `mark_no_show`, `confirm`, `request_change`; y las lecturas de la agenda `list_appointments`, `counts_by_day`, `list_for_day`, `list_pending_processes`, `agenda_process_ids` (universo acotado contra el que se valida el `?selected=`). **Las cinco lecturas tienen `allowed_program_ids` con default ABIERTO** |
| `ReviewDayService` | `services/review_day_service.py` | Días de cotejo por convocatoria: `list_days`, `is_allowed`, `set_days`, `toggle`, `months_with_days` |
| `CotejoRequirementService` | `services/cotejo_requirement_service.py` | Requisitos "qué llevar a la cita" por convocatoria: `list_or_seed` (siembra DEFAULTS si la cohorte no tiene), `create`, `update`, `delete` |
| `OfficerService` | `services/officer_service.py` | Alta delegada de encargados: `create_officer` (Position + rol + usuarios del depto + carreras), `set_users`, `set_programs`, `list_officers`, `deactivate_officer` |
| `SurveyReviewService` | `services/survey_review_service.py` | Solicitud de liberación de GTV para la encuesta de egresados (fase 2, 2026-09-15): `open_for_submission`, `approve`, `reject`, `revoke`, `can_revoke`, `summary_for_process`, `counts_by_status`, `list_for_inbox` — único dueño de `SurveyReview.status` |
| `scope_service` (módulo, no clase) | `services/scope_service.py` | `officer_programs(db, user_id)` → `"ALL"` si tiene `titulatec.process.api.read.all`, si no el set de `program_id` ligados a sus puestos |
| `notify` (módulo, no clase) | `services/notify.py` | `notify_student(...)`: enruta los avisos in-app por el `NotificationService` del core (tab **Avisos** del shell mobile + FAB por-app) |

> Patrón: métodos `@staticmethod`, primer arg `db: Session`, **commit dentro del service**.
> `scope_service` y `notify` son funciones de módulo, no clases.

### Días de cotejo

- `CohortReviewDay` (`titulatec_cohort_review_days`, `UNIQUE(cohort_id, date)`): fechas que la jefa
  habilita por convocatoria. Perm `titulatec.cohort.api.review_days` (solo
  `titulatec_school_services_head`), exigido en `pages/admin.py:244, 257, 399`.
- Pestaña **Documentos** (perm `titulatec.document.page.list`): bandeja de revisión. Al aprobar los 3
  iniciales (`birth_certificate`, `high_school_cert`, `curp` — `pages/documents.py:13`) con la fase en
  1, `pages/documents.py:135-137` llama `PhaseService.approve_phase(db, proc, 1, ...)` y auto-avanza
  1→2. Elegibilidad de cotejo = `DocumentService.initial_docs_all_approved`.

## UI / convenciones front

- Shell admin (desktop): `templates/titulatec/admin/base_admin.html` (sidebar único, activo por `current_route`; en <992px pasa a drawer + topbar, ver [responsive](xcut_student_shell_embed.md)).
- Menú admin **data-driven por permiso**: `_ADMIN_NAV` + `admin_nav_items()` en `pages/nav.py:95-120`,
  inyectado por `render_titulatec`. Una página sin entrada ahí es invisible.
- Shell alumno (mobile-first): `templates/titulatec/student/base_student.html` (appbar + drawer hamburguesa core / rail en desktop; embebible en el shell del core sin chrome duplicada). Ver [integración en el shell](xcut_student_shell_embed.md).
- La app es **pages-only**: `api/` y `schemas/` están vacíos y `/api/titulatec/v2` no monta
  sub-routers. HTMX devuelve **parciales HTML**; las acciones que mutan re-renderizan su sección.
- Toasts/confirm: `window.TitulaTecUtils` (`static/js/shared/titulatec-utils.js:91` expone
  `showToast`, `confirmDialog`, `escapeHtml`); prohibido `alert/confirm/prompt` nativos.
- **Movimiento/indicadores/micro-interacciones**: primitivas reutilizables del design system
  (`tt-anim-in`, `tt-stagger`, `tt-enter`, `tt-hover-lift`, indicador de carga
  `tt-ind-host`+`tt-ind--overlay`, spinner automático en botones HTMX). Toda vista nueva las
  reutiliza. Ver [docs/design/ui_motion.md](../design/ui_motion.md).
- **Indicador de carga**: dos reglas, no una. No aparece antes de `--tt-ind-delay` (300 ms) y,
  cuando aparece, es overlay: **reserva 0 px**. Antes empujaba 24 px en Documentos y 341.8 px en
  Citas.

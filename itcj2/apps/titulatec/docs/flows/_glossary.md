# Glosario · entidades, tablas, roles, permisos

> Referencia para enlazar desde los flujos. No describe pasos; describe **qué es cada cosa**.

## Entidades / tablas (`titulatec_*`)

| Clase (inglés) | Tabla | Qué guarda | Campos clave |
|---|---|---|---|
| `Cohort` | `titulatec_cohorts` | Convocatoria por período académico | `period_id`, `status`, `name` |
| `TitulationProcess` | `titulatec_processes` | Proceso raíz (1 por alumno×cohorte) | `folio`, `student_id`, `cohort_id`, `program_id`, `modality_id`, `current_phase`, `status`, `is_app_active` |
| `ProcessPhase` | `titulatec_process_phases` | Instancia de cada fase del proceso | `phase_number` (0–8), `status`, `completed_at`, `reviewed_by_id`, `rejection_reason` |
| `PhaseDefinition` | `titulatec_phase_definitions` | Catálogo de las 9 fases | `number`, `name`, `order_index` |
| `DocumentType` | `titulatec_document_types` | Catálogo de tipos de doc | `code`, `name`, `file_kind` (`pdf`/`image`), `phase_number` |
| `Document` | `titulatec_documents` | Archivo subido (solo última versión) | `process_id`, `type_code`, `file_path`, `review_status`, `version` |
| `FormatB` | `titulatec_format_b` | Formato B (PK = `process_id`) | `status` (`draft`/`submitted`/`approved`/`rejected`), campos del form |
| `ReviewAppointment` | `titulatec_review_appointments` | Cita de cotejo (fase 2) | `process_id`, `scheduled_at`, `location`, `status`, `confirmed_at`, `note`, `created_by_id` |
| `ProcessEvent` | `titulatec_process_events` | Auditoría / timeline | `event_type`, `phase_number`, `actor_id`, `payload` (JSON) |
| `SynodalAssignment` | `titulatec_synodal_assignments` | Sinodales asignados (fase 4) | rol presidente/secretario/vocal |
| `ProcessChat` / `ChatMessage` | `titulatec_process_chats` / `_chat_messages` | Chat de titulación (fase 5) | — |
| `Ceremony` / `CeremonyProcess` | `titulatec_ceremonies` / `_ceremony_processes` | Acto protocolario (fase 8) | evento compartido M2M |

> FK a alumnos/usuarios: `core_users.id` (**BigInteger**). Carrera: reusa `core_programs`.
> Período: `core_academic_periods` (vía `Cohort.period_id`).

## Roles (en app `titulatec`)

| Rol | Asignación | Emoji |
|---|---|---|
| `student` (global reciclado) | directa al user al importar CSV | 👤 |
| `titulatec_school_services` | vía puestos del depto Servicios Escolares | 🏛️ |
| `titulatec_titulaciones` | vía puestos del depto DEP | 🎓 |
| `titulatec_vinculacion` | directa (puestos `coord_vinculacion_*`) | 🔗 |
| `titulatec_sinodal` | directa (auto-grant al asignar) | 🧑‍⚖️ |
| `admin` | global, **bypassa** `require_perms` | — |

## Permisos por módulo (formato `titulatec.{modulo}.{tipo}.{accion}[.scope]`)

- `process`: `page.my|list|detail`, `api.read.own|all|department`, `api.advance|approve_phase|reject_phase|cancel|hold`
- `cohort`: `page.list|detail`, `api.read|create|update|import_csv`
- `document`: `api.upload.own|read.own|read.all|delete.own|approve|reject`
- `format_b`: `page.fill`, `api.save|submit|read.own|read.all|approve|reject`
- `appointment`: `page.list|my`, `api.create|update|confirm.own|mark_attended|reschedule`
- `synodal` / `chat` / `ceremony` / `notifications`: ver `plan/02_roles_permissions.md`
- `dashboard.{student|school_services|titulaciones|sinodal|vinculacion|admin}`

> Authz en páginas: `require_page_app("titulatec", perms=[...])` (any-of; admin bypassa).
> `user["sub"]` es **string** → `int(user["sub"])`.

## Servicios

| Service | Archivo | Responsabilidad |
|---|---|---|
| `PhaseService` | `services/phase_service.py` | Avance/rechazo de fase (motor) |
| `DocumentService` | `services/document_service.py` | CRUD + review de documentos |
| `FormatBService` | `services/format_b_service.py` | Formato B multi-step + review |
| `ImportService` | `services/import_service.py` | Import CSV (auto-detect + merge) |
| `AppointmentService` | `services/appointment_service.py` | Cita de cotejo (fase 2) + `counts_by_day`/`list_for_day` |
| `ReviewDayService` | `services/review_day_service.py` | Fechas de cotejo por convocatoria (`list_days`/`is_allowed`/`toggle`) |

> Patrón: métodos `@staticmethod`, primer arg `db: Session`, **commit dentro del service**.

### Días de cotejo

- `CohortReviewDay` (`titulatec_cohort_review_days`, `UNIQUE(cohort_id, date)`): fechas que la jefa
  habilita por convocatoria. Perm `titulatec.cohort.api.review_days` (solo `titulatec_school_services_head`).
- Pestaña **Documentos** (perm `titulatec.document.page.list`): bandeja de revisión; al aprobar las 3
  iniciales, auto-avance fase 1→2. Elegibilidad de cotejo = `DocumentService.initial_docs_all_approved`.

## UI / convenciones front

- Shell admin (desktop): `templates/titulatec/admin/base_admin.html` (sidebar único, activo por `current_route`; en <992px pasa a drawer + topbar, ver [responsive](xcut_student_shell_embed.md)).
- Shell alumno (mobile-first): `templates/titulatec/student/base_student.html` (appbar + drawer hamburguesa core / rail en desktop; embebible en el shell del core sin chrome duplicada). Ver [integración en el shell](xcut_student_shell_embed.md).
- HTMX devuelve **parciales HTML**; las acciones que mutan re-renderizan su sección.
- Toasts/confirm: `window.TitulaTecUtils` (prohibido `alert/confirm/prompt` nativos).
- **Movimiento/skeletons/micro-interacciones**: primitivas reutilizables del design system
  (`tt-anim-in`, `tt-stagger`, `tt-hover-lift`, skeletons `skel_rows`, spinner automático en
  botones HTMX). Toda vista nueva las reutiliza. Ver [docs/design/ui_motion.md](../design/ui_motion.md).

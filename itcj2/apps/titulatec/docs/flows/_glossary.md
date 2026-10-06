# Glosario · entidades, tablas, roles, permisos

> Referencia para enlazar desde los flujos. No describe pasos; describe **qué es cada cosa**.
> Verificado contra el código y la BD de dev el **2026-09-01** (alembic `s1e2s3s4v001`, seeders
> `database/DML/titulatec/00..07` cargados). Las piezas de la liberación GTV de la encuesta de
> egresados (`SurveyReview`, rol `titulatec_tech_management`, permisos `survey_review.*`,
> `SurveyReviewService`) se verificaron aparte contra código y BD el **2026-09-15**; el resto de
> este archivo NO se re-auditó a esa fecha y puede haber quedado atrás de otras apps de la misma
> campaña (encuesta, solicitudes de inscripción, espacios de cotejo) — ver las notas fechadas
> 2026-09-15 en este mismo archivo para lo que sí se corrigió. El perfil de titulación por nivel de
> carrera (`core_programs.level`, `TrackService`, fila nueva de la tabla de Servicios) se verificó
> aparte contra código el **2026-09-30**; detalle completo en
> [engine_process_track.md](engine_process_track.md), no en este archivo. El no adeudo de
> biblioteca y las constancias por lote (`LibraryClearance`, `Certificate`/`CertificateBatch`/
> `CertificateCounter`, `PriorClearance`, roles `titulatec_library`/`titulatec_cashier`, permisos
> `library_clearance.*`/`library_payment.*`/`certificate.*`) se verificaron aparte contra código y
> BD el **2026-10-01**; detalle completo en [no adeudo de biblioteca](phase2_library_clearance.md),
> [constancias por lote](xcut_certificates_batch.md) y [constancias previas](xcut_prior_clearances.md).

## Entidades / tablas (`titulatec_*`)

22 tablas (17 + 5 el 2026-10-01: `titulatec_library_clearances`, `titulatec_certificates`,
`titulatec_certificate_batches`, `titulatec_certificate_counters`, `titulatec_prior_clearances`);
una clase por tabla en `itcj2/apps/titulatec/models/` (el prefijo `titulatec_` va solo en
`__tablename__`, no en el nombre de clase).

| Clase (inglés) | Tabla | Qué guarda | Campos clave |
|---|---|---|---|
| `Cohort` | `titulatec_cohorts` | Convocatoria por período académico | `period_id`, `name`, `opens_at`, `closes_at` (ventana de **inscripción** pública: fecha **y hora**, `DateTime` naive en hora local de `APP_TZ`, NOT NULL desde `tt20260927b` — antes fechas nullable; cierre por omisión 23:59:59, que se lee «23:59»), `status` (`draft`/`open`/`closed`), `book_donation_amount` (`Numeric(10,2)`, NULL = sin configurar, 2026-10-01: «Donación voluntaria de libro», obligatoria en el alta, D19) |
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
| `SurveyReview` | `titulatec_survey_reviews` | Solicitud de liberación de GTV para el requisito de cotejo `graduate_survey` (fase 2); una por proceso, nace al enviar la encuesta (2026-09-15) | `process_id` (FK `titulatec_processes`, UNIQUE), `response_id` (FK `titulatec_survey_responses`, **NULL** desde 2026-10-01: una previa D9 no tiene respuesta), `status` (`in_review`/`approved`/`rejected`), `rejection_reason`, `reviewed_by_id`, `reviewed_at`, `submitted_at`, `origin` (`submission`/`prior`, 2026-10-01), `prior_issued_on` (Date, NULL salvo `origin='prior'`) |
| `LibraryClearance` | `titulatec_library_clearances` | No adeudo de biblioteca (fase 2, 2026-10-01); una por proceso, nace `pending` al crear el proceso (antes de la fase 2) | `process_id` (FK, UNIQUE), `status` (`pending`/`awaiting_payment`/`cleared`), `cleared_via` (`payment`/`no_charge`/`prior`/`legacy`, NULL salvo `cleared`), `debt_amount`/`donation_amount`/`total_amount` (`Numeric(10,2)`, congelados), `library_note`/`library_by_id`/`library_at`, `ready_at` (entrada vigente a Caja, Ruling R10), `paid_by_id`/`paid_at`/`receipt_number`, `prior_issued_on`/`prior_note`/`prior_by_id` |
| `Certificate` | `titulatec_certificates` | Constancia emitida (GTV o no adeudo, 2026-10-01); desde 2026-10-05 es sobre todo un FOLIO (la impresión está tras `TITULATEC_CERTIFICATE_PRINTING`, apagado); única por folio, nunca se borra (se anula) | `kind` (`survey_release`/`library_clearance`), `number` (UNIQUE, `{PREFIJO}-{AAAA}{A\|B}-{NNNN}`, p. ej. `BIB-2026B-0001`; antes `{PREFIJO}-{AAAA}-{NNNN}`), `process_id`, `source_ref` (`"survey_review:{id}"`\|`"library_clearance:{id}"`, sin FK real), `control_number`/`student_name`/`program_name`/`period_label` (congelados al emitir), `issued_at`/`issued_by_id` (NULLABLE desde `tt20261005c`: NULL = emitida sin usuario, importación o backfill), `batch_id` (FK `titulatec_certificate_batches`, NULL hasta imprimir), `voided_at`/`voided_by_id`/`void_reason`; a lo más UNA vigente por `source_ref` (UNIQUE parcial `uq_titulatec_certificates_live_source`, Ruling R29) |
| `CertificateBatch` | `titulatec_certificate_batches` | Lote de impresión de constancias (2026-10-01); el PDF NUNCA se guarda, se regenera siempre | `kind`, `created_at`, `created_by_id`, `count` |
| `CertificateCounter` | `titulatec_certificate_counters` | Contador atómico de folio por tipo y SEMESTRE (2026-10-01; por semestre desde `tt20261005c`, 2026-10-05, antes por año); PK compuesta | `kind` (PK), `semester` (PK, `String(5)`: `2026A`/`2026B`, `SEMESTER_RE`; antes `year` Integer), `last_value` |
| `PriorClearance` | `titulatec_prior_clearances` | Constancia previa DIFERIDA (D9, 2026-10-01): liberación de encuesta o no adeudo de ANTES de este sistema sin proceso abierto que la reciba, pendiente de aplicarse o ya aplicada; una MÁS NUEVA reemplaza a la ya aplicada y vuelve a quedar pendiente (Ruling R28) | `kind` (`survey`/`library`), `control_number` (UNIQUE con `kind`), `issued_on` (Date, NULLABLE en el esquema; el servicio siempre la exige), `note`, `source`, `applied_process_id`/`applied_at` (NULL hasta que se aplica) |
| `ProcessEvent` | `titulatec_process_events` | Auditoría / timeline | `event_type`, `phase_number`, `actor_id`, `payload` (JSON) |
| `SynodalAssignment` | `titulatec_synodal_assignments` | Sinodales asignados (fase 4) | `user_id`, `role` (`president`/`secretary`/`vocal`), `vote` (`approved`/`changes_requested`), `vote_note`, `assigned_by_id` |
| `ProcessChat` | `titulatec_chats` | Chat de titulación, 1 por proceso (`process_id` único) | `pinned_document_id` |
| `ChatMessage` | `titulatec_chat_messages` | Mensaje del chat | `chat_id`, `author_id`, `body`, `attachment_path`, `parent_id` (reply) |
| `Ceremony` | `titulatec_ceremonies` | Acto protocolario (fase 8) | `cohort_id`, `scheduled_at`, `room`, `whatsapp_group_url`, `status` (`pending`/`scheduled`/`done`) |
| `CeremonyProcess` | `titulatec_ceremony_processes` | Alumnos dentro de un acto (M2M) | `ceremony_id`, `process_id`, `final_project_path`, `presentation_path` |

> FK a alumnos/usuarios: `core_users.id` (**BigInteger**). Carrera: reusa `core_programs` —
> **desde 2026-09-30** trae `level` (`licenciatura`\|`maestria`\|`doctorado`, `CheckConstraint
> ck_core_programs_level`), de donde `TrackService` deriva el perfil de titulación `posgrado`; ver
> [perfil de titulación por nivel de carrera](engine_process_track.md). Período:
> `core_academic_periods` (vía `Cohort.period_id`).

## Roles (en app `titulatec`)

`core_roles` es **global** (la tabla no tiene `app_id`); el amarre a la app va por
`core_user_app_roles` (directo) o `core_position_app_roles` (por puesto). El conteo son los permisos
de la app `titulatec` que el rol tiene hoy en `core_role_permissions`.

| Rol (`core_roles.name`) | Cómo se asigna hoy | Perms titulatec | Emoji |
|---|---|---|---|
| `graduate` (egresado, desde 2026-09-15) | **directa** en cada alta: `ImportService.import_rows` → `_sync_graduate_roles` (`services/import_service.py:81`) — CSV, alta manual, aprobación de bandeja y liga de activación son los cuatro caminos | 21 (+2 de `itcj`) | 👤 |
| `student` (global — **ya NO** es el alumno de titulación) | rol de **AgendaTec**; `03_insert_role_permissions.sql` le revoca en cada corrida todo lo de `titulatec` que le quedara; `core_users.role_id` conserva el alias en filas viejas que no han pasado por el backfill | 0 | — |
| `titulatec_school_services` | por puesto: `aux_school_services`, `secretary_school_services`. Es también el rol que reciben los **encargados** dados de alta desde la pestaña Encargados (`pages/officers.py:13`, `ROLE_ASSIGNED`) | 22 (verificado en BD, 2026-09-21 — el "22" que traía esta fila desde la auditoría de 2026-09-01 no correspondía a ningún estado real; sube a 22 justo el 2026-09-21 con los 3 `enrollment_request.*`, ver [xcut_public_enrollment.md](xcut_public_enrollment.md)) | 🏛️ |
| `titulatec_school_services_head` | por puesto: `head_school_services` | 27 | 🏛️ |
| `titulatec_titulaciones` | por puesto: **solo** `head_prof_studies_div` (2026-09-21: perdió `secretary_prof_studies_div`/`aux_prof_studies_div` en el deslinde a T-soft, D6/D7 — ese mapeo NO se revirtió, sigue siendo 1 fila) | 25 (2026-09-21: bajó a 12 con el recorte D6/D7 y el usuario REVIRTIÓ ese mismo día — reparto PLENO de nuevo: dictamen, ceremony y cohort incluidos) | 🎓 |
| `titulatec_titulacion` (Departamento de Titulación, NUEVO 2026-09-21) | por puesto: `head_titulacion`, `aux_titulacion` (colgados de `prof_studies_div`, `04b_insert_titulacion_department.sql`; **nacen sin ocupantes**) | 22 | 🎓 |
| `titulatec_tech_management` | por puesto: `head_tech_management` (jefatura de GTV, ya en el organigrama del core) + `external_service_tech_management` («Servicio Externo», puesto NUEVO 2026-09-15, `allows_multiple=TRUE`) — `05_insert_position_app_roles.sql` | 9 | 🛠️ |
| `titulatec_vinculacion` | por puesto: los 5 `coord_vinculacion_*` (`database/DML/titulatec/04_insert_vinculacion_positions.sql`) | 13 | 🔗 |
| `titulatec_sinodal` | **sin ruta de asignación en el código todavía**: 0 filas en `core_position_app_roles` y ningún `grant_role`; solo aparece en el resolver de dashboard (`pages/nav.py:61`) | 14 | 🧑‍⚖️ |
| `titulatec_library` (NUEVO 2026-10-01) | por puesto: `library_clearance_info_center` «Biblioteca · No adeudo», en `info_center` — nace SIN ocupante, asignarlo es paso del lanzamiento | 6 (los 5 `library_clearance.*` + `certificate.page.list`) | 📚 |
| `titulatec_cashier` (NUEVO 2026-10-01) | por puesto: `cashier_financial_resources` «Caja», en `financial_resources` — nace SIN ocupante | 3 (los 3 `library_payment.*`) | 💰 |
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
  `08`, `survey_2026_09/09`, …); **80** filas verificadas en BD el 2026-09-15 — cifra sin
  recalcular entre medias para los deltas de cotejo-con-espacios/correos/posgrado. **98** filas
  verificadas en BD el 2026-10-01 (DML `biblioteca_2026_10/21_insert_library_cashier_roles_perms.sql`:
  88 → 98, +10 nuevos — ver módulos `library_clearance`/`library_payment`/`certificate` abajo; el
  comando `titulatec init-biblioteca-caja` —paso 1 del despliegue, que ya no enciende el
  candado— lo confirma en su `_verify_biblioteca_caja()`).
- **Exigidos por el código** — los que aparecen en un `require_page_app(..., perms=[...])`
  (resolviendo el nombre a su lista/tupla cuando `perms=` pasa una constante en vez de un literal
  inline) o en una entrada del menú `_ADMIN_NAV`; **69** códigos `titulatec.*` distintos,
  recalculados el **2026-10-02** (m38) con un barrido AST propio sobre TODO
  `itcj2/apps/titulatec/**/*.py` (118 llamadas a `require_page_app` encontradas: 117 con un
  `perms=` resoluble —0 sin resolver— y 1 SIN `perms=`, `pages/landing.py:18`
  (`require_page_app("titulatec")`, el ruteo del landing: solo exige acceso a la app y no aporta
  ningún código, así que no mueve la cifra); 16 códigos en `_ADMIN_NAV`; unión sin duplicados).
  Reemplaza el **39** de la auditoría manual del 2026-09-01 (ya un PISO desde entonces, por
  `07`/`08`/`survey_2026_09`/el delta de biblioteca-caja). Los 10 de biblioteca-caja de ayer SÍ
  entran en esta cuenta, salvo los DOS `api.print_certificates` (`library_clearance`/
  `survey_review`): esos se exigen por OTRA vía —`_visible_kinds` (antes `_printable_kinds`)/`cached_perms`
  en `pages/certificates_admin.py`, pertenencia directa al set de permisos del actor, nunca
  `require_page_app`— así que el método (y la cifra) de este párrafo no los cuenta, aunque la
  tabla de abajo sí los liste como exigidos. Como todo conteo sobre código: hay que re-correr el
  barrido si se agregan rutas nuevas.

Un permiso definido y no exigido **no es un error**: es capacidad ya modelada para fases que aún no
tienen pantalla. En sentido contrario sí sería bug, y hoy no lo hay: verificado contra
`database/DML/titulatec/**/*.sql` (02/07/08/`survey_2026_09`/`biblioteca_2026_10`/21) que los 69
exigidos existen en BD.

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
| `survey_review` (4, +1 el 2026-10-01) | `page.list`, `api.approve`, `api.reject`, `api.print_certificates` | **los 4** (`pages/survey_reviews_admin.py` + `pages/certificates_admin.py`) |
| `synodal` (6) | `page.list`, `page.my_reviews`, `api.assign`, `api.read`, `api.release`, `api.vote` | — |
| `library_clearance` (5, NUEVO 2026-10-01) | `page.list`, `api.register`, `api.prior`, `api.revert`, `api.print_certificates` | **los 5** (`pages/library_admin.py` + respaldo D9 en `pages/admin.py`/`pages/appointments.py` + `pages/certificates_admin.py`) |
| `library_payment` (3, NUEVO 2026-10-01) | `page.list`, `api.register`, `api.revert` | **los 3** (`pages/cashier_admin.py`) |
| `certificate` (1, NUEVO 2026-10-01) | `page.list` | **el 1** (`pages/certificates_admin.py`, las 4 rutas) |

Definidos y todavía sin exigir (27): todo `chat.*`, todo `synodal.*`, todo `notifications.*`,
`ceremony.{page.my, api.create, api.update, api.upload.own}`,
`cohort.{page.detail, api.read, api.update, api.cotejo_reqs}`,
`format_b.{api.submit, api.read.own, api.read.all}`,
`process.{api.cancel, api.hold, api.read.department}`. Los 10 de biblioteca-caja (2026-10-01) se
exigen TODOS — ninguno se suma a esta lista.

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
| `appointment.page.list` | `titulatec_school_services`, `titulatec_school_services_head` |
| `cohort.page.list` | `titulatec_school_services_head`, `titulatec_titulaciones` (2026-09-21: recupera Convocatorias al revertirse D6/D7, decisión explícita del usuario — el operativo `titulatec_school_services` NUNCA lo tuvo) |
| `process.page.list`, `document.page.list` | `titulatec_school_services`, `titulatec_school_services_head`, `titulatec_titulaciones`, `titulatec_titulacion` |
| `officers.page.list`, `officers.api.manage`, `cohort.api.review_days`, `cohort.api.cotejo_reqs` | solo `titulatec_school_services_head` |
| `process.api.read.all` (⇒ alcance `"ALL"`) | `titulatec_school_services_head`, `titulatec_titulaciones`, `titulatec_titulacion` |
| `ceremony.page.list` | `titulatec_titulaciones`, `titulatec_titulacion` (2026-09-21: ya no es "solo" uno) |
| `survey_review.page.list`, `survey_review.api.approve`, `survey_review.api.reject` | solo `titulatec_tech_management` (2026-09-15) |
| `enrollment_request.page.list`, `enrollment_request.api.approve`, `enrollment_request.api.reject` | `titulatec_school_services_head` (jefatura, alcance `"ALL"`) y, desde 2026-09-21, también `titulatec_school_services` (operativo: secretaria, auxiliar y los `se_officer_*` de los encargados, acotados a su carrera) — ver [xcut_public_enrollment.md](xcut_public_enrollment.md) |
| `library_clearance.*` (los 5) | solo `titulatec_library` — salvo `api.prior` (constancia previa, D9), que SUMA `titulatec_school_services`/`_head` (respaldo) |
| `library_payment.*` (los 3) | solo `titulatec_cashier` |
| `certificate.page.list` | `titulatec_library`, `titulatec_tech_management` (+2 el 2026-10-01: ve la página de Constancias —desde 2026-10-05 «Folios»— aunque solo vea/imprima `survey_release`) |
| `survey_review.api.print_certificates` | `titulatec_tech_management` (2026-10-01; desde 2026-10-05 significa «ver los folios de encuesta», y además imprimir con el switch encendido; sin renombrar) |
| `library_clearance.api.print_certificates` | `titulatec_library` (2026-10-01; desde 2026-10-05 significa «ver los folios de no adeudo», y además imprimir con el switch encendido; sin renombrar) |
| (2026-10-01) `admin` global | recibe los 10 EXPLÍCITOS en el DML (`biblioteca_2026_10/21_...sql`): producción nunca re-corre `15_grant_admin_all_perms.sql` |

> Authz en páginas: **todas** las rutas usan `require_page_app("titulatec", perms=[...])` (any-of, sin
> bypass de admin). Ninguna usa `require_perms`. Reparto completo por rol en
> [`plan/02_roles_permissions.md`](../../plan/02_roles_permissions.md).
> `user["sub"]` es **string** → `int(user["sub"])`.

## Servicios

16 de los ~24 módulos en `itcj2/apps/titulatec/services/` están documentados abajo (lista
PARCIAL, no exhaustiva — quedan fuera `cohort_service` (salvo `set_book_donation`, abajo),
`email_helper`, `enrollment_request_service`, `process_service`, `requirement_service`,
`review_window_service`, `slot_service` y `survey_service`: deuda de documentación de la
campaña de encuesta/convocatoria anterior a esta tarea; `survey_service.form_for_user` sí está
documentado, pero en [el perfil de titulación](engine_process_track.md), no aquí). Los 4
servicios del no adeudo de biblioteca y constancias (2026-10-01) SÍ están completos abajo y en
detalle en sus propios flujos.

| Símbolo | Archivo | Responsabilidad |
|---|---|---|
| `TrackService` (2026-09-30) | `services/track_service.py` | Perfil de titulación por nivel de carrera: `for_level`/`for_process`/`for_process_id`/`for_processes` traducen `core_programs.level` a `licenciatura` \| `posgrado` — **único** lugar que compara `.level` o nombres de carrera. Detalle: [perfil de titulación por nivel de carrera](engine_process_track.md) |
| `PhaseService` | `services/phase_service.py` | Motor de fases: `approve_phase`/`reject_phase`, salto de fases según la modalidad (`_skips`/`_next_applicable`) y log de `ProcessEvent`. **Y las dos guardas**: `assert_can_transition` (dictamen 🏛️🎓) y `assert_student_can_act` (ejecución 👤) — [guarda de fase del alumno](engine_student_phase_lock.md) |
| `DocumentService` | `services/document_service.py` | Guardar/leer/borrar documentos y `review()` (2026-09-21: rechaza dictaminar un documento cuyo TIPO pertenece a una fase congelada por el corte a T-soft — `dtype.phase_number >= PhaseService._handoff_phase()`; guarda angosta a propósito, NO mira `current_phase`, para no romper el dictamen tardío); además las consultas de elegibilidad `initial_docs_all_approved` y `list_phase_document_types`. El set de fase 1 por perfil (`initial_doc_types*`) también vive aquí. R-G (2026-09-30, Ruling R11 revisión final): `excused_initial_docs` es el ÚNICO predicado que exceptúa extras de posgrado FALTANTES si la fase 1 ya cerró — lo consultan `initial_docs_all_approved` (elegibilidad) Y `initial_docs_summary`/la bandeja/el visor de cotejo/el expediente (contadores) — ver [perfil de titulación](engine_process_track.md) |
| `FormatBService` | `services/format_b_service.py` | Formato B multi-step: `get_or_create`, `save_step`, `submit(db, fb, process)` (reaplica la guarda de fase del alumno), `review(db, fb, process, ...)` (2026-09-21: ganó `process` y reaplica `assert_can_transition`, la guarda gemela del admin), `to_ctx` |
| `ImportService` | `services/import_service.py` | Import CSV de la convocatoria: `parse` → `autodetect_mapping` → `build_preview` → `import_rows` (crea/empata usuario, otorga rol `graduate` y revoca `student` vía `_sync_graduate_roles`, crea proceso + sus 9 `ProcessPhase`) |
| `AppointmentService` | `services/appointment_service.py` | Cita de cotejo (fase 2): `create`, `reschedule`, `start`, `mark_attended`, `mark_no_show`, `confirm`, `request_change`; y las lecturas de la agenda `list_appointments`, `counts_by_day`, `list_for_day`, `list_pending_processes`, `agenda_process_ids` (universo acotado contra el que se valida el `?selected=`). **Las cinco lecturas tienen `allowed_program_ids` con default ABIERTO** |
| `ReviewDayService` | `services/review_day_service.py` | Días de cotejo por convocatoria: `list_days`, `is_allowed`, `set_days`, `toggle`, `months_with_days` |
| `CotejoRequirementService` | `services/cotejo_requirement_service.py` | Requisitos "qué llevar a la cita" por convocatoria: `list_or_seed` (siembra DEFAULTS si la cohorte no tiene), `create`, `update`, `delete` |
| `OfficerService` | `services/officer_service.py` | Alta delegada de encargados: `create_officer` (Position + rol + usuarios del depto + carreras), `set_users`, `set_programs`, `list_officers`, `deactivate_officer` |
| `SurveyReviewService` | `services/survey_review_service.py` | Solicitud de liberación de GTV para la encuesta de egresados (fase 2, 2026-09-15): `open_for_submission`, `approve`, `reject`, `revoke`, `can_revoke`, `summary_for_process`, `counts_by_status`, `list_for_inbox`, `register_prior`/`prior_outcome` (D9, 2026-10-01), `certificate_ref` (el `source_ref` de sus constancias, para la UNA llamada a `print_status_map` de las vistas de SE, Ruling R14) — único dueño de `SurveyReview.status`. `register_prior` emite el folio de la previa (semestre anterior al registro, kwarg `registered_at`) desde 2026-10-05 |
| `LibraryClearanceService` (NUEVO 2026-10-01) | `services/library_clearance_service.py` | No adeudo de biblioteca (fase 2): `register` (Registrar/Corregir), `register_no_debt_bulk` (lote D10), `register_payment`, `register_prior` (D9), `revert_payment`, `revert_clearance`, `undo_prior`, `for_process_locked` (respaldo SE), `summary_for_process`, `list_for_inbox`, `search`, `day_cut` (corte del día FIJO desde `ProcessEvent`, 2026-10-02), `certificate_ref` (Ruling R14, gemelo del de `SurveyReviewService`) — único dueño de `LibraryClearance.status` (`register_prior` emite el folio de la previa y `undo_prior` lo anula, 2026-10-05). `release_status[_map]`/`summary_for_process` dicen `not_applicable` (`NOT_APPLICABLE`, Ruling R21) cuando la fase 2 ya está aprobada sin el no adeudo liberado; el choque de concurrencia es `ClearanceConflict` (subclase de `ValueError`, Ruling R24). El mismo archivo expone `parse_amount`/`format_amount` como funciones de MÓDULO, no métodos de la clase. Detalle: [no adeudo de biblioteca](phase2_library_clearance.md) |
| `ClearanceGate` (NUEVO 2026-10-01) | `services/clearance_gate.py` | Candado único de liberaciones para agendar: `status`/`status_map` (dominios cerrados `SURVEY_STATES`/`LIBRARY_STATES`; `not_required` y `not_applicable` no bloquean), `blockers`, `is_clear`, `released_clause`/`not_released_clause`, `library_required` — ÚNICA fuente de «¿le falta alguna liberación?» (invariante 2; prueba estructural). Detalle: [no adeudo de biblioteca § el candado único](phase2_library_clearance.md#el-candado-único-clearancegate) |
| `CertificateService` (NUEVO 2026-10-01) | `services/certificate_service.py` | Motor compartido de constancias y folios (GTV y no adeudo): `issue(..., actor_id: int \| None, semester: str \| None = None)` (folio `{BIB\|GTV}-{AAAA}{A\|B}-{NNNN}`), `void`, `pending`/`pending_count`/`create_batch` (las de una inscripción revocada NO se imprimen, Ruling R26), `list_batches`, `certificates_of`, `period_label`, `list_folios` (la tabla de la página «Folios», 2026-10-05; lee solo `titulatec_certificates`), `printing_enabled()` (el switch `TITULATEC_CERTIFICATE_PRINTING`) y las funciones de módulo `semester_key`/`previous_semester_key`/`SEMESTER_RE`, y (2026-10-02) `print_status_map`/`voided_after_print` — el estado de impresión, ≤2 consultas por llamada, invariante 4 (no lee ninguna tabla de liberación) — único dueño de `Certificate`/`CertificateBatch`/`CertificateCounter`. Detalle: [constancias por lote](xcut_certificates_batch.md) |
| `PriorClearanceService` (NUEVO 2026-10-01) | `services/prior_clearance_service.py` | Constancias previas (D9): `apply_pending` (alta de proceso), `import_rows` (CLI). Nunca muta `SurveyReview`/`LibraryClearance` directo: llama a los dueños; para la previa diferida les pasa `registered_at=PriorClearance.created_at` (el semestre del folio sale de la importación, 2026-10-05). Detalle: [constancias previas](xcut_prior_clearances.md) |
| `FolioBackfillService` (NUEVO 2026-10-05) | `services/folio_backfill_service.py` | Folia las previas y el legado `cleared/legacy` que quedaron sin folio vigente: `candidates(db)` y `run(db, *, dry_run)` (conteo por `(kind, semester)`, `actor_id=None`, semestre anterior al ancla, UN commit, idempotente; la corrida real bloquea las filas fuente con `FOR UPDATE OF` y re-verifica cada una antes de emitir). Lo usan la CLI `titulatec emitir-folios-previos` y el paso 5 de `activar-biblioteca-caja`. Único lector de `.status` fuera de los dueños y del gate (`_LECTORES_DE_REPARACION` en `test_clearance_gate.py`); su única escritura es `CertificateService.issue`. Detalle: [folios](xcut_certificates_batch.md#backfill-de-folios-de-previas-y-legado-foliobackfillservice) |
| `scope_service` (módulo, no clase) | `services/scope_service.py` | `officer_programs(db, user_id)` → `"ALL"` si tiene `titulatec.process.api.read.all`, si no el set de `program_id` ligados a sus puestos |
| `notify` (módulo, no clase) | `services/notify.py` | `notify_student(...)`: enruta los avisos in-app por el `NotificationService` del core (tab **Avisos** del shell mobile + FAB por-app) |
| `CohortService.set_book_donation` (NUEVO 2026-10-01) | `services/cohort_service.py` | Única escritura de `Cohort.book_donation_amount` (D5); devuelve cuántos `LibraryClearance` ya tienen monto congelado (Review Focus #2) |

> Patrón: métodos `@staticmethod`, primer arg `db: Session`, **commit dentro del service**.
> `scope_service` y `notify` son funciones de módulo, no clases.

### Días de cotejo

- `CohortReviewDay` (`titulatec_cohort_review_days`, `UNIQUE(cohort_id, date)`): fechas que la jefa
  habilita por convocatoria. Perm `titulatec.cohort.api.review_days` (solo
  `titulatec_school_services_head`), exigido en `pages/admin.py:244, 257, 399`.
- Pestaña **Documentos** (perm `titulatec.document.page.list`): bandeja de revisión. Al aprobar TODOS
  los documentos iniciales DEL PERFIL del proceso (3 en licenciatura; 7 en posgrado —
  `DocumentService.initial_doc_types_for`, ver [perfil de titulación](engine_process_track.md); R-G
  exceptúa los extras de posgrado FALTANTES si la fase 1 ya cerró) con la fase en 1,
  `pages/documents.py:334-336` llama `PhaseService.approve_phase(db, proc, 1, ...)` y auto-avanza
  1→2. Elegibilidad de cotejo = `DocumentService.initial_docs_all_approved` (consulta
  `excused_initial_docs` para R-G).

## UI / convenciones front

- Shell admin (desktop): `templates/titulatec/admin/base_admin.html` (sidebar único, activo por `current_route`; en <992px pasa a drawer + topbar, ver [responsive](xcut_student_shell_embed.md)).
- Menú admin **data-driven por permiso**: `_ADMIN_NAV` + `admin_nav_items(user_id, db=None)` en
  `pages/nav.py:119-170` (permisos por `cached_perms`), inyectado por `render_titulatec` como un callable
  perezoso (`admin_nav`) que solo evalúa `base_admin.html`. Una página sin entrada ahí es invisible.
- Rutas de `pages/` (2026-10-05): `def` si no hacen `await`; si leen el form o un archivo, `async def` solo para
  ese `await` y `return await run_in_threadpool(_cuerpo_x, ...)` (`CLAUDE.md` §1 de la app;
  `test_route_threadpool_convention.py`).
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

# TitulaTec · Flujos (docs/flows)

> **Qué es esto.** Un mapa vivo de *cómo se mueven los datos* en TitulaTec: qué hace
> cada acción, desde qué pantalla, qué endpoint la atiende, qué service la ejecuta,
> qué tablas muta, qué eventos/notificaciones dispara y a qué estado deja el proceso.
> Cuando no recuerde "¿cómo se hace X / hacia dónde van los datos?", **empieza aquí**.

Cada archivo describe **un flujo** = un objetivo concreto (ej: "el alumno sube sus
documentos iniciales"). Un flujo puede **componer** a otros (ej: la cita de cotejo
termina invocando el [motor de avance de fase](engine_approve_advance_phase.md)).

---

## Cómo usar / mantener

- **Antes de tocar un flujo en código**, lee su `.md` aquí. **Después de cambiarlo**,
  actualiza el `.md` en el mismo commit. Doc desincronizado = doc inútil.
- **Flujo nuevo** → copia [`_TEMPLATE.md`](_TEMPLATE.md), no inventes estructura.
- **Rutas (desde 2026-10-05)**: las de `pages/` son `def`, salvo las que leen el form o un archivo, que son
  `async def` solo para ese `await` y terminan en `return await run_in_threadpool(_cuerpo_x, ...)`. Cuando un
  flujo dice «la ruta abre su `SessionLocal()`», es la ruta `def` o su `_cuerpo_*`. Lo fija
  `tests/fastapi/titulatec/test_route_threadpool_convention.py`; forma completa en el `CLAUDE.md` de la app, §1.
- **No dupliques** la máquina de estados ni el glosario: enlázalos.
- Convención de nombre: `{faseOrScope}_{actor}_{accion}.md` en minúsculas-kebab.
  - `phaseN_...` para flujos atados a una fase del proceso.
  - `engine_...` / `xcut_...` para piezas transversales reutilizables (building blocks).
- Los diagramas son **mermaid** (`sequenceDiagram` / `stateDiagram`); GitHub y VS Code
  los renderizan. La **tabla de pasos** es la fuente de verdad textual.

## Leyenda

| Símbolo | Significado |
|---|---|
| 👤 | Acción del **alumno** (rol `graduate` desde 2026-09-15; antes `student`), mobile |
| 🏛️ | Acción de **Servicios Escolares** (`titulatec_school_services`) |
| 🎓 | Acción de **Titulaciones / DEP** (`titulatec_titulaciones`) o del **Departamento de Titulación** (`titulatec_titulacion`; desde 2026-10-07 Liberados + expediente resumido; desde 2026-10-21 también la pestaña Titulación, solo tras `init-titulatec-fase-2`) |
| 🛠️ | Acción de **Gestión Tecnológica y Vinculación** (`titulatec_tech_management`, GTV — desde 2026-09-15) |
| 🔗 | Jefe de **departamento académico** o coordinador de **Vinculación** (`titulatec_vinculacion`; desde 2026-10-21 asigna sinodales y gestiona los docentes de su departamento) · 🧑‍⚖️ **Sinodal** (`titulatec_sinodal`) |
| 💻 | Acción de **Centro de Cómputo** (`titulatec_computer_center` — desde 2026-09-24) |
| 📚 | Acción de **Biblioteca** (`titulatec_library`, puesto «Biblioteca · No adeudo» — desde 2026-10-01) |
| 💰 | Acción de **Caja** (`titulatec_cashier`, puesto «Caja» — desde 2026-10-01) |
| 🤖 | Paso automático del sistema (sin humano) |
| ⤵ | Compone/invoca otro flujo |
| ❗ | Camino alterno / error |

---

## Índice de flujos

### Fase 0 — Convocatoria / intake
- [Detalle de convocatoria: 5 sub-pestañas HTMX](phase0_school_services_cohort_detail.md) 🏛️ ⤵ compone las dos altas — el hub por convocatoria: resumen (con la ventana de inscripción, fecha y hora; desde 2026-10-22 cerrar solo pausa a quien no pasó el primer *checkpoint*, D12), alumnos, días de cotejo, importar, requisitos.
- [Servicios Escolares importa alumnos por CSV](phase0_school_services_import_csv.md) 🏛️🤖 — asistente de 3 pasos: subir → mapear/validar → confirmar.
- [Alta manual de un alumno suelto](phase0_school_services_add_student_manual.md) 🏛️ ⤵ reusa `ImportService` — el que no venía en el CSV, por nº de control.
- [Inscripción pública con revisión previa](xcut_public_enrollment.md) 👤🏛️🤖 ⤵ reusa `ImportService` — formulario público → bandeja de Solicitudes → usuario + NIP por correo (cuenta nueva) o liga de activación (cuenta existente, que se reactiva si estaba desactivada); el alumno recibe el rol `graduate`; riesgo aceptado y su contención.
- [Consulta de elegibilidad al SII: el SII informa, Servicios Escolares decide](xcut_sii_eligibility.md) 🤖🏛️💻 (2026-09-25; modo **por omisión** desde 2026-09-27) — tras el alta, celery consulta el SII con reglas declarativas (`database/SII/titulatec/`, formato en [`../sii_rules_format.md`](../sii_rules_format.md)) y guarda el veredicto, su porqué y, sin cuenta, si el SII tiene NIP (`nip_status`); **nada se aprueba solo**: SE decide en Solicitudes con la columna «SII» — «Aprobar y enviar liga» / «Aprobar y dar acceso» (la cuenta nace con el NIP del SII) / «Aprobar y pasar a Accesos» (respaldo) —, con confirmación si el SII no dijo «Apta»; SII no configurado, «Reintentar consulta», «Reenviar aviso», barrido periódico, **revocar inscripción** y los pasos de despliegue.
- [Accesos de Centro de Cómputo](xcut_computer_center_access.md) 🏛️💻🤖 (2026-09-24) — continúa las anteriores: la solicitud sin cuenta que SE pasa a Centro de Cómputo (`awaiting_access`; en modo `sii` solo el respaldo, en el oficial todo lo sin cuenta) recibe el NIP, vuelve con nota, o se le reasigna el NIP si el correo no salió (D8); modo alterno (variable de entorno): Centro de Cómputo aprueba y rechaza todo, Solicitudes queda de solo lectura.

### Fase 1 — Documentos iniciales
- [El alumno sube sus documentos iniciales](phase1_student_upload_initial_docs.md) 👤
- [Servicios Escolares / Titulaciones revisa los documentos](phase1_admin_review_initial_docs.md) 🏛️🎓 ⤵ engine
- [Revisión de documentos (pestaña Documentos + auto-avance)](phase1_school_services_review_docs.md) 🏛️🎓 ⤵ engine — bandeja dedicada; todos los documentos DEL PERFIL aprobados (3 en licenciatura, 7 en posgrado, desde 2026-09-30) → fase 2.

### Fase 2 — Cita de cotejo
- [Cita de cotejo (loop completo)](phase2_appointment_loop.md) 🏛️👤 ⤵ engine — cola de 5 cubos, el 5.º «Liberaciones pendientes» (antes «Encuesta sin liberar»; desde 2026-10-01 también cubre el no adeudo de biblioteca).
- [Reemplazo de un documento en la cita de cotejo](xcut_cotejo_document_replacement.md) 🏛️👤 (2026-10-15) ⤵ compone Documentos, la cita y el expediente — la jefatura de SE pide (permiso propio `titulatec.document.api.request_replacement`) que el egresado vuelva a subir un documento de la fase 1 estando en la fase 2, sin regresar de fase ni tocar el congelado del dictamen; `Document.replacement_requested_at`, modo reemplazo en Documentos del alumno, compuerta que bloquea LIBERAR la fase 2 (no agendar), versión de documento que continúa tras borrar y despliegue (`tt20261015a` + `titulatec init-reemplazo-docs`).
- [El egresado agenda su propia cita](phase2_student_self_booking.md) 👤🏛️ ⤵ engine — desde 2026-09-16: el encargado publica su espacio como «Agendable» (o «Abierto sin cita») y el egresado elige franja, la cancela a tiempo, y el encargado se entera **por su tablero** con el distintivo «El alumno agendó».
- [Información para el alumno de un requisito de cotejo](phase2_school_services_requirement_info.md) 🏛️👤 — la jefa escribe una nota enriquecida por requisito (editor Quill, sanitizada con `utils/rich_text.py`); el alumno la abre con el botón «i» en su cita.
- [Liberación GTV de la encuesta de egresados](phase2_tech_management_survey_release.md) 🛠️👤 — Gestión Tecnológica y Vinculación revisa lo que el egresado ya envió y decide si libera el requisito de cotejo `graduate_survey` o le deja observaciones; el egresado no vuelve a tocar la encuesta desde el sistema (salvo una constancia previa revocada, que se borra y contesta), lo resuelve con GTV (contacto D12).
- [No adeudo de biblioteca: Biblioteca → Caja](phase2_library_clearance.md) 📚💰🏛️👤 (2026-10-01) — Biblioteca revisa en FIFO a todo inscrito y registra si debe; el egresado paga adeudo + donación voluntaria de libro en Caja, sin cita; donde la convocatoria lo exige, ni agenda ni es agendado sin el no adeudo liberado (`ClearanceGate`, candado único junto con la encuesta).

### Fase 3 — Formato B
- [El alumno llena y envía el Formato B](phase3_student_formato_b.md) 👤 (2026-10-21) → [Titulación lo revisa](phase3_titulacion_review_formato_b.md) — 3 pasos con validación en línea (servidor = autoridad), pantalla «Revisa y envía» con casilla de confirmación exigida en servidor, «Tipo de titulación» elegido por el alumno, observaciones por campo con «Corregido ✓» y reenvío al final de la cola.
- [Titulación revisa el Formato B (pestaña «Titulación», FIFO)](phase3_titulacion_review_formato_b.md) 🎓 ⤵ engine (2026-10-21) — 4 pestañas (Por revisar · Con observaciones · Aprobados · Sin enviar), dictamen con observaciones por campo, presencia «quién lo está revisando» (Redis, fail-open), corrección de nombre/carrera del registro, una sola puerta de dictamen (marca `PhaseService.DOOR_KEY`, `open_door`/`_door_guard`), inerte con el corte en 3 y despliegue por `init-titulatec-fase-2`.

### Fase 4 — Asignación de sinodales
- [El departamento académico asigna a los 4 sinodales (pestaña «Sinodales»)](phase4_department_assign_synodals.md) 🔗 ⤵ engine (2026-10-21) — 2 pestañas (Por asignar · Asignados, FIFO con semáforo), 4 selects con los docentes del departamento de la carrera, registro en UNA transacción que aprueba la fase 4 y pasa a la 5 (una sola puerta: `PhaseService.open_door`, la fase 4 no tiene rechazo), sustitución con motivo mientras la fase 5 no termine, oficio PDF al vuelo, avisos best-effort a los sinodales, alcance por departamento (jefe/coordinador; `admin` y la jefatura de la DEP operan todos), inerte con el corte en 3 y despliegue por `init-titulatec-fase-2`.
- [Catálogo de docentes por departamento (pestaña «Docentes»)](xcut_teacher_catalog.md) 🔗 ⤵ alimenta la anterior (2026-10-21) — una cuenta por persona (busca por correo, usuario y nombre; nunca duplica), puesto `docente_{depto}`, perfil único de grado y cédula, contraseña temporal por correo con cambio obligatorio; enmienda de seguridad: el departamento nunca toca credenciales de cuentas con privilegios ni reactiva inactivas; quitar se bloquea con asignaciones vigentes.
- [Carreras por departamento y ajustes del oficio](xcut_program_departments.md) 🛠️ (2026-10-21) — solo `admin`: mapeo carrera → departamento (editable, con nombre oficial) y encabezado/destinatarios del oficio por departamento; el despliegue del DML de la fase 4 (`init-titulatec-fase-2` con 2 archivos, verificaciones y la trampa R-A).

### Fase 5 — Revisión de sinodales
- [Conversación, versiones, votos y liberación automática](phase5_synodal_review.md) 👤🧑‍⚖️🤖 ⤵ engine (2026-10-22) — una conversación por proceso entre el alumno y sus 4 sinodales vigentes (abierta al registrarlos en la fase 4), versiones PDF/Word de hasta 20 MB, mensajes y adjuntos con refresco de ~15 s (sin Socket.IO), votos según la `signature_rule` de la modalidad (`president_only` = solo el Presidente; `all_synodals` = los 4, suplente incluido) con reinicio por versión y reconfirmación del voto que cierra, liberación por la puerta única `ReviewService.vote` → fase 6, conversación de solo lectura tras cerrar, pantalla «Mis revisiones» (Por revisar · En curso · Completados), estado sin conversación en expediente/Sinodales/Titulación, avisos, correos y recordatorios (`titulatec.review_reminders`, 9:15), guarda `assert_participant`, inerte con el corte en 3 y despliegue (`tt20261022c` antes del código → `init-titulatec-fase-2` → recrear worker y beat).

### Fase 6 — Anexo III
- [Vinculación prepara, el alumno recoge, Titulación dictamina](phase6_anexo_iii.md) 🧑‍💼👤🎓🤖 ⤵ engine (v2, 2026-10-29; v1 2026-10-22) — al cerrarse la fase 5 el aviso `ANEXO_READY` («Prepara el Anexo III») llega a vinculación, que imprime el oficial con folio `AIII-AAAAS-NNNN` desde Sinodales («En Anexo III»: Por preparar · Por recoger · En Titulación), recaba la firma y el sello del jefe y lo marca «Listo para recoger» con lugar y horario (`AnexoService.mark_ready`; campana `ANEXO_PICKUP` y correo `anexo_ready`); el alumno solo ve una vista previa con marca de agua, recoge el original, junta las firmas de sus sinodales (`ReviewService.counting_roles`) y sube el escaneo (solo desde `ready`/`observed`/`in_review`); Titulación lo aprueba u observa (puerta única `AnexoService.approve`/`observe` con `expected_version`) y puede pedir **reimpresión** (regresa a vinculación, folio intacto, campana `ANEXO_REPRINT`). Etapa derivada por `AnexoService.stage`/`stage_map` (preparing · reprint · ready · in_review · observed · approved); 116 permisos (`preview.own`, `prepare`; sin `generate.own`); tarjeta del expediente (`AnexoService.empty_label`), EGEL salta la 6, inerte con el corte en 3 y despliegue (`tt20261029a` → `init-titulatec-fase-2` → reiniciar backend y celery).

### Transversales (building blocks)
- [Calendario único de días inhábiles](xcut_non_working_days.md) 🎓 (2026-10-22) ⤵ lo leen la revisión, las bandejas FIFO y el Tablero — pantalla «Días inhábiles» (`titulatec.non_working_day.*`, solo tras `init-titulatec-fase-2`), `business_days(..., holidays=)` en todos los consumidores, regla «calendario vacío = idéntico» y las notas del Tablero.
- [Perfil de titulación por nivel de carrera (licenciatura | posgrado)](engine_process_track.md) 🤖
  (2026-09-30) — `TrackService` traduce `core_programs.level`; de ahí cuelgan el set de documentos
  de fase 1 (3 o 7), el formulario de encuesta y la píldora «Posgrado».
- [Motor de avance de fase: aprobar / rechazar](engine_approve_advance_phase.md) 🤖 — invocado por casi todos.
- [Guarda de fase del alumno: solo la fase en curso se ejecuta](engine_student_phase_lock.md) 👤🤖 — gemela de la anterior: siguientes = informativas, anteriores = inmutables.
- [Alcance por carrera + asignación delegada de encargados](engine_officer_scope.md) 🏛️ — `officer_programs` acota bandeja/kanban/citas; el jefe da de alta encargados.
- [Bandeja administrativa de procesos](xcut_admin_process_inbox.md) 🏛️🎓 ⤵ scope — tabla y kanban del mismo dataset, `idle_days` y filtro de atorados; la lista exige `process.page.list` (guarda propia desde 2026-10-07).
- [Expediente del alumno](xcut_admin_process_expediente.md) 🏛️🎓 ⤵ scope — acordeón de las 9 fases con el historial de cada una; documentos de solo lectura, mover de fase en modal, y el `?from=` que devuelve a la pestaña de origen con sus filtros (Liberados incluida; sin `from`, el regreso depende de lo que el actor puede abrir). Desde 2026-10-07: enlaces a otras pestañas solo si el actor puede abrirlas, y vista **resumida** para el Departamento de Titulación (`process.page.summary`: cabecera + fases previas al corte, sin desglose ni acciones).
- [Correos del proceso al egresado](xcut_student_email_notifications.md) 🤖 (2026-09-28/29; +4 `kind` el 2026-10-01) ⤵ compone casi todos los anteriores — bandeja `titulatec_email_outbox` escrita en la MISMA transacción del evento + despachador Celery cada 5 minutos (agrupado por espera D7, `FOR UPDATE SKIP LOCKED`, reintentos) + barrido diario de 4 recordatorios (cita, documentos, encuesta y, desde 2026-10-01, pago en Caja); catálogo de 15 `kind`, ligas `/itcj/login?next=`, `[TT-MAIL]` en dev sin cuenta Graph, y la bitácora `#exp-correos` que pinta el expediente.
- [Pestaña «Correos»: la bandeja de salida, de solo lectura](xcut_mail_outbox_admin.md) 🛠️ (2026-10-06) ⤵ lee la anterior — solo el rol `admin` (`titulatec.email_outbox.page.list`, `init-outbox-admin`): pendientes, entregados, fallidos y descartados, con búsqueda, tipo y paginación en servidor; sin reintentar ni reenviar.
- [Folios y constancias por lote: numeración, emisión, switch de impresión y PDF](xcut_certificates_batch.md) 🤖📚🛠️ (2026-10-01; folios por semestre 2026-10-05) ⤵ compone no adeudo de biblioteca, liberación GTV y constancias previas — folio atómico por tipo y semestre (`BIB-2026B-0001`), datos congelados, página «Folios» con buscador, backfill de previas y legado; la impresión por lote (WeasyPrint, 3 o 2 por hoja carta) sigue en el código pero apagada por omisión (`TITULATEC_CERTIFICATE_PRINTING`).
- [Constancias previas: liberaciones de antes de este sistema](xcut_prior_clearances.md) 🏛️📚🤖 (2026-10-01, D9) — un egresado que ya traía su liberación de otro semestre no repite el trámite; CLI `import-prior-clearances` + aplicación diferida al inscribirse; desde 2026-10-05 la previa lleva folio del semestre anterior a su registro.
- [Bitácora de auditoría: quién hizo qué, cuándo y con qué antes/después](xcut_audit_log.md) 🤖🛠️ (2026-10-07) — tres fuentes (acción explícita, espejo de `ProcessEvent`, red ORM), tabla inmutable por trigger, pestaña solo lectura para `admin`, purga por CLI y orden de despliegue.
- [Tablero de la jefa de Servicios Escolares: avance, pelota, atorados, carga y ritmo](xcut_reports_dashboard.md) 🏛️ (2026-10-14; desde 2026-10-22 descuenta los [días inhábiles](xcut_non_working_days.md) registrados) ⤵ lee todos los anteriores, solo lectura — 5 pestañas (Panorama · Ritmo · Encargados · Carreras · Atorados) con el estado en la URL; etapa y «quién tiene la pelota» de cada pendiente (vía `ClearanceGate`), días sin movimiento (`TITULATEC_IDLE_*`), ritmo y pronóstico en días hábiles, cola con traslape por encargado (D2), alcance por carrera, presupuesto de consultas y despliegue (`titulatec init-reportes` a la par o antes del código; permiso `titulatec.reports.page.view`, sin migración).
- [Reporte Excel de la encuesta de egresados](xcut_survey_report.md) 🛠️ (2026-10-28) — solo lectura, permiso del CSV (`survey.api.export`): plantillas fijas, columnas y orden a elección, filtros por periodo de respuesta y de egreso, cualquier pregunta de opción, origen y «un registro por egresado»; libro xlsxwriter con Respuestas, Resumen, Distribución, Cruce y Parámetros; la configuración vive en la URL. El CSV crudo no cambia.
- [El alumno consulta el detalle de una fase](xcut_student_phase_detail.md) 👤 — **acordeón en el dashboard** (la pantalla `/fase/{n}` ya no existe: redirige): estado, instrucciones, sub-progreso, CTA y timeline.
- [La jefatura da de alta encargados por carrera](xcut_school_services_manage_officers.md) 🏛️🤖 ⤵ alimenta el alcance — un encargado es un `Position` con rol y carreras; nombrar a una cuenta INACTIVA la reactiva y le restablece la contraseña (9 de 11 usuarios de Servicios Escolares lo estaban), y la pantalla lo dice antes y después.
- [El alumno usa TitulaTec dentro del shell mobile del core](xcut_student_shell_embed.md) 👤 — embebido vs standalone, drawer/rail, notificaciones por Avisos, mini-perfil.
- [Corte a T-soft y bandeja de Liberados](xcut_titulacion_handoff.md) 👤🎓🏛️ ⤵ gemela de las dos
  guardas — de la fase 3 en adelante el proceso deja de operarse aquí (lo sigue el Departamento
  de Titulación en T-soft); la pestaña **Liberados** (solo lectura) muestra a quién ya soltó
  Servicios Escolares (`ProcessPhase(2).status == 'approved'`). Reversible con una sola variable.
  Desde 2026-10-07: el Departamento de Titulación aterriza en Liberados y solo ve eso más el
  expediente resumido; Servicios Escolares (encargados y jefatura) también la ve y exporta; la
  columna Correo es el correo personal del egresado y la modalidad nula dice «Sin elegir».

### Referencias
- [Máquina de estados (proceso + fases + citas + documentos + solicitudes + checks del SII)](00_state_machine.md)
- [Glosario: entidades, tablas, roles, permisos](_glossary.md)
- [Plantilla para un flujo nuevo](_TEMPLATE.md)
- Decisiones de UI: [shell del alumno](../design/student_shell.md) · [animaciones y skeletons](../design/ui_motion.md)

---

## Relación con `plan/`

`plan/` (untracked) = **spec/diseño** (qué construir, decisiones). `docs/flows/` =
**operación/trazabilidad** del código ya construido (cómo funciona hoy, paso a paso).
Si difieren, el código manda → corrige el flow.

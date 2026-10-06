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
| 🎓 | Acción de **Titulaciones / DEP** (`titulatec_titulaciones`) |
| 🛠️ | Acción de **Gestión Tecnológica y Vinculación** (`titulatec_tech_management`, GTV — desde 2026-09-15) |
| 🔗 | Jefe de **Vinculación** (`titulatec_vinculacion`) · 🧑‍⚖️ **Sinodal** (`titulatec_sinodal`) |
| 💻 | Acción de **Centro de Cómputo** (`titulatec_computer_center` — desde 2026-09-24) |
| 📚 | Acción de **Biblioteca** (`titulatec_library`, puesto «Biblioteca · No adeudo» — desde 2026-10-01) |
| 💰 | Acción de **Caja** (`titulatec_cashier`, puesto «Caja» — desde 2026-10-01) |
| 🤖 | Paso automático del sistema (sin humano) |
| ⤵ | Compone/invoca otro flujo |
| ❗ | Camino alterno / error |

---

## Índice de flujos

### Fase 0 — Convocatoria / intake
- [Detalle de convocatoria: 5 sub-pestañas HTMX](phase0_school_services_cohort_detail.md) 🏛️ ⤵ compone las dos altas — el hub por convocatoria: resumen (con la ventana de inscripción, fecha y hora), alumnos, días de cotejo, importar, requisitos.
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
- [El egresado agenda su propia cita](phase2_student_self_booking.md) 👤🏛️ ⤵ engine — desde 2026-09-16: el encargado publica su espacio como «Agendable» (o «Abierto sin cita») y el egresado elige franja, la cancela a tiempo, y el encargado se entera **por su tablero** con el distintivo «El alumno agendó».
- [Información para el alumno de un requisito de cotejo](phase2_school_services_requirement_info.md) 🏛️👤 — la jefa escribe una nota enriquecida por requisito (editor Quill, sanitizada con `utils/rich_text.py`); el alumno la abre con el botón «i» en su cita.
- [Liberación GTV de la encuesta de egresados](phase2_tech_management_survey_release.md) 🛠️👤 — Gestión Tecnológica y Vinculación revisa lo que el egresado ya envió y decide si libera el requisito de cotejo `graduate_survey` o le deja observaciones; el egresado no vuelve a tocar la encuesta desde el sistema (salvo una constancia previa revocada, que se borra y contesta), lo resuelve con GTV (contacto D12).
- [No adeudo de biblioteca: Biblioteca → Caja](phase2_library_clearance.md) 📚💰🏛️👤 (2026-10-01) — Biblioteca revisa en FIFO a todo inscrito y registra si debe; el egresado paga adeudo + donación voluntaria de libro en Caja, sin cita; donde la convocatoria lo exige, ni agenda ni es agendado sin el no adeudo liberado (`ClearanceGate`, candado único junto con la encuesta).

### Fase 3 — Formato B
- [El alumno llena y envía el Formato B](phase3_student_formato_b.md) 👤
- *(revisión de Formato B → ver flujo de revisión, pendiente de documentar)*

### Transversales (building blocks)
- [Perfil de titulación por nivel de carrera (licenciatura | posgrado)](engine_process_track.md) 🤖
  (2026-09-30) — `TrackService` traduce `core_programs.level`; de ahí cuelgan el set de documentos
  de fase 1 (3 o 7), el formulario de encuesta y la píldora «Posgrado».
- [Motor de avance de fase: aprobar / rechazar](engine_approve_advance_phase.md) 🤖 — invocado por casi todos.
- [Guarda de fase del alumno: solo la fase en curso se ejecuta](engine_student_phase_lock.md) 👤🤖 — gemela de la anterior: siguientes = informativas, anteriores = inmutables.
- [Alcance por carrera + asignación delegada de encargados](engine_officer_scope.md) 🏛️ — `officer_programs` acota bandeja/kanban/citas; el jefe da de alta encargados.
- [Bandeja administrativa de procesos](xcut_admin_process_inbox.md) 🏛️🎓 ⤵ scope — tabla y kanban del mismo dataset, `idle_days` y filtro de atorados.
- [Expediente del alumno](xcut_admin_process_expediente.md) 🏛️ ⤵ scope — acordeón de las 9 fases con el historial de cada una; documentos de solo lectura, mover de fase en modal, y el `?from=` que devuelve a la pestaña de origen con sus filtros.
- [Correos del proceso al egresado](xcut_student_email_notifications.md) 🤖 (2026-09-28/29; +4 `kind` el 2026-10-01) ⤵ compone casi todos los anteriores — bandeja `titulatec_email_outbox` escrita en la MISMA transacción del evento + despachador Celery cada 5 minutos (agrupado por espera D7, `FOR UPDATE SKIP LOCKED`, reintentos) + barrido diario de 4 recordatorios (cita, documentos, encuesta y, desde 2026-10-01, pago en Caja); catálogo de 15 `kind`, ligas `/itcj/login?next=`, `[TT-MAIL]` en dev sin cuenta Graph, y la bitácora `#exp-correos` que pinta el expediente.
- [Pestaña «Correos»: la bandeja de salida, de solo lectura](xcut_mail_outbox_admin.md) 🛠️ (2026-10-06) ⤵ lee la anterior — solo el rol `admin` (`titulatec.email_outbox.page.list`, `init-outbox-admin`): pendientes, entregados, fallidos y descartados, con búsqueda, tipo y paginación en servidor; sin reintentar ni reenviar.
- [Folios y constancias por lote: numeración, emisión, switch de impresión y PDF](xcut_certificates_batch.md) 🤖📚🛠️ (2026-10-01; folios por semestre 2026-10-05) ⤵ compone no adeudo de biblioteca, liberación GTV y constancias previas — folio atómico por tipo y semestre (`BIB-2026B-0001`), datos congelados, página «Folios» con buscador, backfill de previas y legado; la impresión por lote (WeasyPrint, 3 o 2 por hoja carta) sigue en el código pero apagada por omisión (`TITULATEC_CERTIFICATE_PRINTING`).
- [Constancias previas: liberaciones de antes de este sistema](xcut_prior_clearances.md) 🏛️📚🤖 (2026-10-01, D9) — un egresado que ya traía su liberación de otro semestre no repite el trámite; CLI `import-prior-clearances` + aplicación diferida al inscribirse; desde 2026-10-05 la previa lleva folio del semestre anterior a su registro.
- [El alumno consulta el detalle de una fase](xcut_student_phase_detail.md) 👤 — **acordeón en el dashboard** (la pantalla `/fase/{n}` ya no existe: redirige): estado, instrucciones, sub-progreso, CTA y timeline.
- [La jefatura da de alta encargados por carrera](xcut_school_services_manage_officers.md) 🏛️🤖 ⤵ alimenta el alcance — un encargado es un `Position` con rol y carreras; nombrar a una cuenta INACTIVA la reactiva y le restablece la contraseña (9 de 11 usuarios de Servicios Escolares lo estaban), y la pantalla lo dice antes y después.
- [El alumno usa TitulaTec dentro del shell mobile del core](xcut_student_shell_embed.md) 👤 — embebido vs standalone, drawer/rail, notificaciones por Avisos, mini-perfil.
- [Corte a T-soft y bandeja de Liberados](xcut_titulacion_handoff.md) 👤🎓 ⤵ gemela de las dos
  guardas — de la fase 3 en adelante el proceso deja de operarse aquí (lo sigue el Departamento
  de Titulación en T-soft); la pestaña **Liberados** (solo lectura) muestra a quién ya soltó
  Servicios Escolares (`ProcessPhase(2).status == 'approved'`). Reversible con una sola variable.

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

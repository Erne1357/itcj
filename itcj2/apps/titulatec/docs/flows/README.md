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
- **No dupliques** la máquina de estados ni el glosario: enlázalos.
- Convención de nombre: `{faseOrScope}_{actor}_{accion}.md` en minúsculas-kebab.
  - `phaseN_...` para flujos atados a una fase del proceso.
  - `engine_...` / `xcut_...` para piezas transversales reutilizables (building blocks).
- Los diagramas son **mermaid** (`sequenceDiagram` / `stateDiagram`); GitHub y VS Code
  los renderizan. La **tabla de pasos** es la fuente de verdad textual.

## Leyenda

| Símbolo | Significado |
|---|---|
| 👤 | Acción del **alumno** (rol `student`, mobile) |
| 🏛️ | Acción de **Servicios Escolares** (`titulatec_school_services`) |
| 🎓 | Acción de **Titulaciones / DEP** (`titulatec_titulaciones`) |
| 🔗 | Jefe de **Vinculación** (`titulatec_vinculacion`) · 🧑‍⚖️ **Sinodal** (`titulatec_sinodal`) |
| 🤖 | Paso automático del sistema (sin humano) |
| ⤵ | Compone/invoca otro flujo |
| ❗ | Camino alterno / error |

---

## Índice de flujos

### Fase 0 — Convocatoria / intake
- [Servicios Escolares importa alumnos por CSV](phase0_school_services_import_csv.md) 🏛️🤖

### Fase 1 — Documentos iniciales
- [El alumno sube sus documentos iniciales](phase1_student_upload_initial_docs.md) 👤
- [Servicios Escolares / Titulaciones revisa los documentos](phase1_admin_review_initial_docs.md) 🏛️🎓 ⤵ engine

### Fase 2 — Cita de cotejo
- [Cita de cotejo (loop completo)](phase2_appointment_loop.md) 🏛️👤 ⤵ engine

### Fase 3 — Formato B
- [El alumno llena y envía el Formato B](phase3_student_formato_b.md) 👤
- *(revisión de Formato B → ver flujo de revisión, pendiente de documentar)*

### Transversales (building blocks)
- [Motor de avance de fase: aprobar / rechazar](engine_approve_advance_phase.md) 🤖 — invocado por casi todos.
- [Alcance por carrera + asignación delegada de encargados](engine_officer_scope.md) 🏛️ — `officer_programs` acota bandeja/kanban/citas; el jefe da de alta encargados.
- [El alumno consulta el detalle de una fase](xcut_student_phase_detail.md) 👤 — estado, instrucciones, CTA y timeline.
- [El alumno usa TitulaTec dentro del shell mobile del core](xcut_student_shell_embed.md) 👤 — embebido vs standalone, drawer/rail, notificaciones por Avisos, mini-perfil.

### Referencias
- [Máquina de estados (fases + citas + documentos)](00_state_machine.md)
- [Glosario: entidades, tablas, roles, permisos](_glossary.md)
- [Plantilla para un flujo nuevo](_TEMPLATE.md)

---

## Relación con `plan/`

`plan/` (untracked) = **spec/diseño** (qué construir, decisiones). `docs/flows/` =
**operación/trazabilidad** del código ya construido (cómo funciona hoy, paso a paso).
Si difieren, el código manda → corrige el flow.

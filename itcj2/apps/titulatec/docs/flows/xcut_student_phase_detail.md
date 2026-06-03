# El alumno consulta el detalle de una fase (transversal)

> **Objetivo:** que el alumno vea, por fase, su estado, qué debe hacer, el acceso a la
> acción correspondiente y el historial de eventos.

| | |
|---|---|
| **Actor(es)** | 👤 Alumno (`student`) |
| **Permiso(s)** | `process.page.my` / `process.api.read.own` |
| **Trigger** | Tocar una fase en la lista del dashboard |
| **Precondiciones** | Tiene un `TitulationProcess` activo |
| **Estado final** | — (vista de lectura; no muta nada) |

## Ruta en la app (UI)

1. `/titulatec/student/dashboard` → lista "El proceso (9 fases)"; la fase actual va marcada **Actual**.
2. Toca una fila → `GET /titulatec/student/fase/{n}`.
3. Ve: encabezado (icono + nombre + `estado_pill`), instrucción, motivo de rechazo si aplica,
   **CTA** al módulo (si la fase lo soporta) o un estado read-only, y el **historial** de eventos.

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint | Datos | Notas |
|---|---|---|---|---|---|---|
| 1 | 👤 | dashboard | abrir fase | `GET /titulatec/student/fase/{n}` | `PhaseDefinition[n]`, `ProcessPhase`, `ProcessEvent` (phase_number=n) | n∈0..8 |

## Reglas de presentación

- **CTA** (`_PHASE_CTA`): `initial_docs`→documentos · `review_appointment`→cita · `format_b`→formato B.
  Se muestra solo si la fase está soportada y su `status` ∉ {`pending`,`skipped`}.
- **Fases no soportadas / futuras**: read-only. `pending` → "se habilitará cuando llegues";
  `in_progress/in_review` sin CTA → "en proceso por {responsable}"; `skipped` → "no aplica";
  `approved` → "fase completada".
- **Instrucciones** por código de fase: `_PHASE_HELP`. **Responsable**: `_RESPONSIBLE_LABEL`.
- **Timeline**: `ProcessEvent` de esa fase con etiqueta legible (`_EVENT_LABELS`) + fecha.
- Estados visuales vía [máquina de estados](00_state_machine.md); pills vía `estado_pill`.

## Flujos relacionados

- Desde aquí el alumno entra a: [documentos](phase1_student_upload_initial_docs.md),
  [cita](phase2_appointment_loop.md), [Formato B](phase3_student_formato_b.md).

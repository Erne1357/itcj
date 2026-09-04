# Guarda de fase del alumno: solo la fase en curso se ejecuta

> **Objetivo:** que el alumno solo pueda *ejecutar* la fase que le toca. Las siguientes
> se **leen** (informativas), las anteriores quedan **cerradas e inmutables**.
> **Building block** que invocan las 10 rutas de fase del alumno ⤵.

| | |
|---|---|
| **Actor(es)** | 👤 Alumno (`student`) — 🤖 lógica |
| **Permiso(s)** | Ninguno nuevo. Es **ortogonal** al permiso: el rol `student` tiene los 21 y aun así solo actúa en su fase |
| **Trigger** | Toda ruta de `pages/student.py` atada a una fase (10 de las 13) |
| **Precondiciones** | El alumno tiene un `TitulationProcess` (sin proceso la guarda no opina) |
| **Estado final** | Sin cambios: la guarda corta **antes** de escribir |

## La regla, en una línea

`n == process.current_phase` **y** `process.status == 'active'` **y** `n` está en el catálogo
de fases. Es la **gemela** de [`PhaseService.assert_can_transition`](engine_approve_advance_phase.md#guarda-de-transición-desde-2026-09)
(el lado del admin) leída desde el otro extremo: aquélla protege el **dictamen**, ésta la
**ejecución**.

Decisión del usuario (2026-09-02), que es literalmente lo que promete el acordeón:

| Relación con `current_phase` | Qué puede el alumno | Copy del acordeón (`student/dashboard.html:219,221`) |
|---|---|---|
| **Anterior** | Leer. Nada más. **Inmutable** | «Fase cerrada · ya no requiere acción» |
| **Actual** | Ejecutar | (sale en grande en la tarjeta «Tu proceso», con su CTA) |
| **Siguiente** | Leer la ficha completa: `desc`, «qué vas a necesitar», quién hace qué | «Se habilitará cuando llegues a esta fase» |

> **La fase `rejected` NO es un caso aparte.** `PhaseService.reject_phase` deja
> `process.current_phase = n`, así que mirar `current_phase` —y no el `status` de la fase—
> ya deja pasar la corrección y el reenvío del alumno. Una guarda escrita sobre el `status`
> habría cerrado el único camino de corrección del proceso.

## Dónde vive

```
services/phase_service.py
  ├─ phase_number_for_code(db, code)   código de fase → número, DESDE EL CATÁLOGO
  ├─ _student_action_error(db, ...)    las tres reglas → mensaje o None
  ├─ can_student_act(db, ...)          bool   (lo usan las PÁGINAS)
  └─ assert_student_can_act(db, ...)   raise ValueError (lo usan las MUTACIONES)

pages/student.py
  ├─ _phase_of(db, code)               atajo a phase_number_for_code
  ├─ _phase_guard(...)      -> 400 + X-Tt-Error   mutaciones y parciales HTMX
  └─ _phase_guard_page(...) -> 302 al acordeón    páginas completas

services/format_b_service.py
  └─ submit(db, fb, process)           reaplica la guarda en el punto de mutación
```

Vive en el **service** y no repetida en cada ruta por lo mismo que su gemela: hay 10
llamadores y el siguiente la hereda gratis. `FormatBService.submit` la vuelve a exigir
dentro (igual que `approve_phase` con `assert_can_transition`) porque es un punto de
mutación de fase, no solo un endpoint.

## Qué fase guarda cada ruta

El número **sale del catálogo `titulatec_phase_definitions`**, nunca de un literal — la
misma política que `PhaseService.phase_range` y `ImportService`.

| Ruta | Método | Fase | De dónde sale el número | Respuesta fuera de fase |
|---|---|---|---|---|
| `/student/documents` | GET | 1 | code `initial_docs` | **302** → `/student/dashboard?fase=1` |
| `/student/documents/{type_code}` | POST | la del **tipo** | `DocumentType.phase_number` | 400 + `X-Tt-Error` |
| `/student/documents/{type_code}` | DELETE | la del **tipo** | `DocumentType.phase_number` | 400 + `X-Tt-Error` |
| `/student/formato-b` | GET | 3 | code `format_b` | **302** → `?fase=3` |
| `/student/formato-b/step/{n}` | GET | 3 | code `format_b` | 400 + `X-Tt-Error` |
| `/student/formato-b/step/{n}` | POST | 3 | code `format_b` | 400 + `X-Tt-Error` |
| `/student/cita` | GET | 2 | code `review_appointment` | **302** → `?fase=2` |
| `/student/cita/confirmar` | POST | 2 | code `review_appointment` | 400 + `X-Tt-Error` |
| `/student/cita/solicitar-cambio` | POST | 2 | code `review_appointment` | 400 + `X-Tt-Error` |
| `/student/phase/1/submit` | POST | 1 | code `initial_docs` | 400 + `X-Tt-Error` |

Las 3 rutas del alumno **sin** fase, y por qué: `GET /student/dashboard` (es el acordeón
informativo de las 9 — el destino del 302), `GET /student/perfil` (identidad + resumen) y
`GET /student/fase/{n}` (compat de notificaciones viejas, que ya redirige al acordeón).

> **La fase de un documento la manda el TIPO, no la URL.** `DocumentService.save` escribe
> `phase_number=dtype.phase_number`, así que guardar por el tipo cierra de paso un agujero
> que no estaba en el reporte: subir o borrar `anexo_iii` (fase 6), `ine` /
> `residency_proof` (fase 7) o `final_project` / `presentation` (fase 8) desde la fase 1.

## Los dos canales de respuesta, y por qué

**Mutaciones y parciales HTMX → `400` + header `X-Tt-Error`.** Es el canal de error de la
app (`student/documents.html:54-56` ya lo convierte en toast). **400 y no 409**: los 14
`X-Tt-Error` del árbol viajan en 400 —incluida la guarda gemela del admin, fijada por
`test_phase_guard.py`— mientras que el `409` pelado ya significa otra cosa en *estas mismas
rutas*: «no tienes proceso». Reusar 409 haría indistinguibles dos condiciones distintas
sobre la misma URL.

**Páginas completas → `302` a `/student/dashboard?fase={N}`.** El alumno que llega por un
enlace viejo —una notificación que sigue viva en `core_notifications`, un marcador, el
historial del shell— tiene que aterrizar donde **se le explica** la fase. Eso es justo el
acordeón: `_phases_ctx` emite `desc` / «qué vas a necesitar» / «quién hace qué» de las 9
fases y `_cta_for` no pinta ninguna acción fuera de la actual, así que **ya es** la vista
de solo lectura — no hace falta una segunda plantilla que se desincronice. Un `404` sería
un callejón sin salida y además mentiría: la página existe, no es su turno. Mismo
mecanismo, mismo 302 y mismo motivo que [`/student/fase/{n}`](xcut_student_phase_detail.md)
(un 301/308 lo cachearía el navegador para siempre).

Y al revés: los parciales **no** usan 302 porque htmx sigue el redirect de forma
transparente y metería el dashboard entero dentro de `#formato-b-body`.

## Mensajes

Van **sin acentos**, igual que los de `_transition_error` y por el mismo motivo: viajan en
`X-Tt-Error`, y ahí Starlette escribe latin-1 pero su TestClient lee UTF-8 — un byte >127
tumba el request entero en cualquier test de ruta que caiga en este camino.

| Regla | Mensaje |
|---|---|
| `n` es un entero del catálogo | `Fase no reconocida: esta accion no corresponde a ninguna fase de tu proceso.` / `Fase {n} fuera del proceso: no existe en el catalogo de fases.` |
| `process.status == 'active'` | `Tu proceso ya no admite cambios (estado: {status}).` |
| `n == current_phase` (anterior) | `La fase NN ya esta cerrada: no requiere accion y no admite cambios.` |
| `n == current_phase` (siguiente) | `La fase NN se habilitara cuando llegues a ella (vas en la fase MM).` |

## Qué pasaba antes (2026-09-02)

Las 13 rutas del alumno estaban gateadas **solo por permiso**, y el rol `student` tiene los
21 permisos de la app: no había **ni una** comprobación de `current_phase` en todo
`pages/student.py`. Reproducido en dev:

| Exploit | Efecto |
|---|---|
| `GET /student/formato-b` desde la fase 1 | 200 — y **creaba** la fila `titulatec_format_b` (`get_or_create` hace `commit`) |
| `POST /student/formato-b/step/1` desde la fase 1 | 200, guardaba datos de la fase 3 |
| `POST /student/formato-b/step/3` desde la fase 1 | 200 → fase 3 `in_review` + `FormatB.submitted` con `current_phase=1`: **entraba en la cola de Titulaciones sin pasar las fases 1 y 2** |
| `POST /student/phase/1/submit` con la fase 1 ya aprobada | 204 → la fase volvía de `approved` a `in_review` y **reabría** la cola de Servicios Escolares |
| `DELETE /student/documents/curp` desde la fase 2 | 200 → borraba fila **y fichero** (`storage.delete_document_file`) de evidencia ya dictaminada |
| `POST/DELETE /student/documents/{tipo de otra fase}` | subía y borraba documentos de las fases 6, 7 y 8 desde la fase 1 |

Todo ello contradiciendo lo que la UI le promete al alumno en el acordeón. Cubierto por
`tests/fastapi/titulatec/test_student_phase_guard.py` (60 tests), que incluye un test
**estructural**: cualquier ruta nueva del alumno que no invoque la guarda —o no entre en la
lista de exentas con su justificación— sale en rojo. El modo de fallo del olvido sería
**abierto**, que es exactamente el defecto que documenta.

## Caminos alternos / errores ❗

- **Sin proceso** → la guarda no opina; queda el contrato previo (409 en las mutaciones, o
  el estado vacío «Sin proceso activo» en las páginas).
- **Sin catálogo de fases**, o `DocumentType.phase_number` en `NULL` → **falla cerrado**:
  no se puede actuar. `phase_number_for_code` devolviendo `None` es una respuesta legítima.
- **Proceso `completed` / `cancelled` / `on_hold`** → ninguna acción del alumno, ni sobre
  su propia fase. Misma tercera regla que la guarda del admin.
- **Fase `rejected`** → sigue abierta: es el caso de corrección, ver arriba.

## Flujos relacionados

- ⇄ Gemela: [motor de avance de fase](engine_approve_advance_phase.md) — la guarda del admin.
- → Cierra: [documentos iniciales](phase1_student_upload_initial_docs.md),
  [cita de cotejo](phase2_appointment_loop.md), [Formato B](phase3_student_formato_b.md).
- 🖥️ La vista de solo lectura a la que redirige: [acordeón de fases](xcut_student_phase_detail.md).
- 📐 Reglas de transición: [máquina de estados](00_state_machine.md).

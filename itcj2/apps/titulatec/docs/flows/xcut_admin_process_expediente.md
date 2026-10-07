# Expediente del alumno (admin)

**Ruta:** `/titulatec/admin/processes/{process_id}` · **Fecha:** 2026-09-03
**Quién:** Servicios Escolares (encargado y jefatura), Titulaciones (vista completa) ·
Departamento de Titulación (vista **resumida**, desde 2026-10-07 — ver abajo).

Sustituye al «detalle de proceso», que era una pila de cuatro tarjetas fijas y
decía **cómo está** el proceso sin decir **qué le pasó**.

---

## Para qué existe

`ProcessEvent` guarda once tipos de suceso con actor y payload desde que existen
`phase_service` y `appointment_service`. Ninguna pantalla del personal leía uno
solo: para saber si un alumno ya había faltado a su cita, o por qué se le rechazó
una fase, había que ir a la base de datos. El expediente es esa lectura.

---

## Recorrido

```
Procesos / Documentos / Citas / Convocatorias / Liberados / Correos
   └─ «Abrir» | «Expediente» | «Ver expediente»
        ?from=<URL canónica de esa pestaña, con sus filtros>
          │
          ▼
GET /titulatec/admin/processes/{id}?fase=N&doc=CODE&from=…        (pages/admin.py:2281)
  require_page_app("titulatec",
                   perms=_PROCESS_FULL_VIEW_PERMS + _PROCESS_SUMMARY_PERMS)
  assert_process_in_scope(db, user_id, process_id)       ← 404, no 403
  cached_perms → _vista_completa(perms)?
    sí → _detail_ctx(...)                                ← consultas por lote
         render admin/process_detail.html → _exp_shell.html
    no → _summary_ctx(...)                               ← vista RESUMIDA (D7)
         render admin/process_summary.html
```

Guardas (`pages/admin.py:48-60`, 2026-10-07):

| Constante | Códigos | Para qué |
|---|---|---|
| `_PROCESS_FULL_VIEW_PERMS` | `process.page.detail`, `process.page.list`, `dashboard.admin`, `dashboard.school_services`, `dashboard.titulaciones` | vista COMPLETA. `process.api.read.all` NO está: es alcance de datos, no una página (revisado en DML y BD: ningún rol dependía de él para ver el expediente) |
| `_PROCESS_SUMMARY_PERMS` | `process.page.summary` | vista RESUMIDA (Departamento de Titulación) |
| `_PROCESS_VIEW_PERMS` | la suma de las dos | guarda del expediente; también la usa `mail_admin._process_opener` («la MISMA regla que el expediente») |

### Zonas

| Id | Qué es |
|---|---|
| `#exp-head` | Regresar · folio · nombre · control · correo · carrera · modalidad · progreso · «Mover de fase» |
| `#exp-fases` | acordeón de las 9 fases (`tt-acc`), la actual abierta |
| `#exp-otros` | movimientos sin fase; **no se pinta si está vacío** |
| `#exp-correos` | bitácora de correos al egresado, solo lectura, colapsable y cerrada por omisión; **no se pinta si está vacía** — ver abajo |
| `#exp-modal-fase` | modal de mover de fase — **fuera** del shell, ver abajo |

### Contenido por fase

| Fase | Qué enseña |
|---|---|
| 0 · Convocatoria | convocatoria, carrera, modalidad, folio, enlace a la convocatoria (solo con `cohort.page.list`) |
| 1 · Documentos | los 3 documentos **de solo lectura** + visor (`?doc=`) + «Dictaminar en la bandeja» (solo si puede abrir Documentos) |
| 2 · Cita de cotejo | cita actual, solicitud de cambio del alumno, enlace a Citas (solo si puede abrir Citas) |
| 3 · Formato B | bloque trasladado **literal** del detalle anterior |
| 4–8 | dicen que la fase todavía no está en la app |

Debajo de cada una, su **Historial**: los `ProcessEvent` de esa fase con actor,
fecha larga y el detalle que traiga el payload.

---

## Decisiones y por qué

### Los documentos no se dictaminan aquí

Había **dos** endpoints para dictaminar el mismo documento con reglas distintas:
el de la bandeja (`pages/documents.py`) exige motivo al rechazar y auto-avanza la
fase cuando quedan los tres aprobados; el del detalle no hacía ninguna de las dos.
Se borró `POST /processes/{id}/documents/{type}/review`; queda el de la bandeja.

### Mover de fase exige motivo al rechazar

Sin él, al alumno le llegaba «Fase rechazada» a secas en su panel y tenía que
venir a preguntar. Se valida en el servidor (400 + `X-Tt-Error`) y en el cliente,
que además pone el foco en el campo.

### `?from=` se valida en el servidor

Es una URL que llega del cliente y acaba dentro de un `href`: sin validar, es un
redirector abierto con la marca de la escuela. `_back_ctx` (`pages/admin.py:1491`)
exige el prefijo `/titulatec/admin/`, rechaza `//` (que el navegador lee como
externa), `..` y la barra invertida. Etiquetas por prefijo en `_BACK_LABELS`
(`:1388`; «Liberados» desde 2026-10-07).

Lo que no pasa (o no llega) cae al regreso por OMISIÓN, que desde el 2026-10-07
depende de lo que el actor puede abrir (`_back_por_omision`, `:1479`, con
`cached_perms`): **Procesos** solo si puede abrir la lista; si no, y puede
Liberados, **Liberados** (Titulación); si no, el **inicio** de la app
(`/titulatec/`, que el landing resuelve a su pantalla). Antes caía siempre a
Procesos, que a Titulación le habría contestado 403.

### Los enlaces a otras pestañas solo si el actor puede abrirlas (2026-10-07)

«Ver la convocatoria» (fase 0), «Dictaminar en la bandeja» (fase 1) y «Gestionar
la cita» (fase 2) salen de `can_open`, que arma `_detail_ctx` con
`_tabs_abiertas(cached_perms(...))` (`pages/admin.py:87`). `_TAB_PERMS` (`:78`)
apunta a la guarda REAL de cada ruta destino —la misma lista, importada, no una
copia—: `_COHORT_PERMS`, `documents._VIEW_PERMS`, `appointments._VIEW_PERMS`
(más `_PROCESS_LIST_PERMS` y `handoff_admin._LIST` para el regreso). Un enlace
que contesta 403 es peor que no estar: el encargado de carrera, por ejemplo, no
ve «Ver la convocatoria» (no tiene `cohort.page.list`).

### Vista RESUMIDA para el Departamento de Titulación (2026-10-07, D7)

Quien tiene `process.page.summary` y NINGÚN código de vista completa ve
`admin/process_summary.html` (`#exp-resumen`), que arma `_summary_ctx`
(`pages/admin.py:1914`):

* **Cabecera:** alumno, número de control, carrera, convocatoria, modalidad (o
  «Sin elegir»), correo —el PERSONAL con la resolución de
  `StudentMail.contact_email` y, sin él, el institucional; lo mismo que pinta
  Liberados— y la píldora de estado del proceso.
* **Fases ANTERIORES al corte** (`PhaseService._handoff_phase()`, hoy 3): número,
  nombre, estado y fecha («Se cerró el …» o «Empezó el …»). Las fases desde el
  corte ni se consultan ni se pintan.
* **Nada del desglose:** ni documentos ni visor, ni historial, ni cita,
  requisitos, biblioteca o encuesta, ni la bitácora de correos, ni acciones, ni
  enlaces a otras pestañas. `_summary_ctx` ni siquiera los lee.
* **Regresar:** solo acepta un `from` de Liberados (con sus filtros); cualquier
  otro cae al regreso por omisión (Liberados para Titulación).
* **Acciones (`/processes/{id}/...`) → 403** para quien solo tiene el resumen,
  aunque su set conserve el permiso de la acción (Titulación guarda el dictamen
  dormido de fases 3-8): `_exigir_vista_completa` (`:98`) va justo después de
  `assert_process_in_scope` en las 7 rutas, ANTES de escribir nada, porque todas
  responden el expediente ENTERO.

Auditoría de sub-rutas con `{process_id}` para un actor solo-resumen (set de
Titulación, D8):

| Ruta | Guarda | Resultado |
|---|---|---|
| `GET /processes/{id}` | vista completa ∪ resumen | 200 resumido |
| `POST /processes/{id}/phase/{n}/approve` · `/reject` · `/format-b/review` · `/cancelar` | su permiso + `_exigir_vista_completa` | 403 (antes 200: aprobaba la fase 2) |
| `POST /processes/{id}/requisitos/{rid}` · `/no-adeudo-previo` · `/deshacer` | su permiso (no lo tiene) + `_exigir_vista_completa` | 403 |
| `GET /documents/{id}/document/{code}` · `GET /appointments/{id}/document/{code}` | `document.api.read.all` (ya no lo tiene) | 403 |
| resto de `POST /appointments/{id}/...` (agendar, atender, requisitos, previa…) | `appointment.*` / `requirement.mark` / `library_clearance.api.prior` | 403 |
| `POST /appointments/{id}/fase2/aprobar` · `/rechazar` | `process.api.approve_phase` / `reject_phase` | **sigue abierta** (pendiente, fuera de `pages/admin.py`) |
| `POST /documents/{id}/document/review` | `document.api.approve` / `reject` | **sigue abierta** (pendiente, fuera de `pages/admin.py`) |

### El documento abierto es estado de servidor (`?doc=`)

Idiomorph conserva el nodo del `<iframe>` pero **sincroniza sus atributos**, y
`src` es uno: con el documento en el DOM, aprobar una fase lo recargaba desde
cero. Mismo motivo y misma solución que en Citas.

### El modal vive FUERA del shell

Medido en Chromium a 1280×900: dentro de `#exp-shell` el `.modal-dialog` salía de
1630 px y su mitad inferior quedaba fuera de la ventana. La causa **no** es
`.tt-admin` (que a ≥992 no lleva transform, que es lo que dice el comentario de
`base.html`) sino `#tt-admin-content`: lleva `tt-anim-in` con
`animation-fill-mode: both`, así que al terminar conserva
`transform: matrix(1,0,0,1,0,0)` —identidad, pero transform al fin— y eso crea
bloque contenedor para los descendientes `position: fixed`. El `height:100%` del
`.modal` pasaba a resolverse contra los 1686 px del contenido.

Como el modal no entra al swap, su contenido dependiente de la fase (nombre y las
dos URL) se copia al abrirlo desde los `data-*` del botón que lo dispara.

### El acordeón recuerda lo desplegado

Las acciones devuelven el expediente **entero**. El estado de lo abierto vive en
`admin/expediente.js`, no en el DOM: Idiomorph borra cualquier `data-*` que la
respuesta no traiga, y sin memoria el revisor perdía en cada acción todo lo que
había desplegado para comparar.

### La bitácora de correos (spec 2026-09-28-titulatec-correos-notificaciones §7)

Zona `#exp-correos`, al final del shell, después de `#exp-otros`. Lee
`titulatec_email_outbox` (motor de la Parte C del spec: cada evento del
proceso que debe avisar al egresado por correo — dictamen de documentos,
avance/rechazo de fase, resultado de GTV, cita de cotejo, recordatorios —
deja ahí una fila que un despachador periódico envía) con
`StudentMail.history(db, process_id)`, **una sola consulta**, más nuevas
primero. Decisiones:

* **Solo lectura, sin reenviar (D11).** El personal necesita saber qué se
  mandó, cuándo, a dónde y si falló — no repetir el envío desde aquí.
* **Una entrada por CORREO, no por aviso (ruling 21, 2026-09-29).**
  `pages/admin.py::_bitacora_correos` junta las filas de un mismo grupo
  (`group_key` no nulo: `docs:{pid}`, `cita:{pid}`) con el mismo `status` y
  el mismo `sent_at` —el despachador marca así a toda la unidad que sale en
  un correo— en UNA entrada con «N avisos agrupados», bajo el id de la fila
  más reciente del grupo. La fecha es la de ENVÍO si salió; si no, la de alta
  del aviso más reciente. El conteo del encabezado cuenta correos, no filas.
  Antes, tres dictámenes que salieron en un solo correo se leían como tres
  correos.
* **`subject` cae al nombre del tipo** (`StudentMail.KIND_LABELS[kind]`)
  mientras la fila no se ha enviado: el despachador solo llena `subject` al
  entregar, y una fila `pending`/`failed`/`no_recipient` no tiene uno propio
  todavía.
* **`sent_to` no se resuelve aquí.** Solo se llena al enviar; una fila que
  aún no salió enseña «—» en vez de adivinar el correo del alumno.
* **Colapsable y cerrada por omisión, SIN memoria entre swaps** — a
  diferencia del acordeón de fases (arriba), que sí la recuerda. La lista de
  correos no cambia con las acciones del expediente, así que no hay nada que
  el usuario pierda al re-renderizarse cerrada. Por eso `admin/expediente.js`
  la engancha con una delegación de clic APARTE (`#exp-correos
  [data-tt-acc]`): la delegación de fases está acotada a `#exp-fases` (su Set
  `abiertas` es de números de fase), así que un botón fuera de esa sección no
  la disparaba.
* **No se pinta si el proceso no tiene ninguna fila** — mismo patrón que
  `#exp-otros`: el `{% if correos %}` envuelve la sección entera en
  `_exp_shell.html`, así que un proceso sin correos no deja ni el `<section>`
  vacío en el DOM.

---

## Eventos que escribe la app

| Evento | Lo escribe | Fase | Payload |
|---|---|---|---|
| `process_created` | `import_service.import_rows` | 0 | `source` (`csv`\|`manual`), `folio` |
| `document_uploaded` | `DocumentService.save` | la del tipo | `type_code`, `original_name`, `version` |
| `document_approved` / `document_rejected` | `DocumentService.review` | la del documento | `type_code`, `note` |
| `document_deleted` | `DocumentService.delete` | la del documento | `type_code` |
| `phase_approved` / `phase_rejected` / `process_completed` | `PhaseService` | la de la fase | `reason` |
| `appointment_*` (7 tipos) | `AppointmentService` | 2 | `scheduled_at`, `window_id`, `reason` |

Los cinco primeros **son nuevos del 2026-09-03**. Antes de esa fecha no hay
ningún evento de documento ni de alta: el historial de un alumno que subió su
acta la semana pasada empieza vacío en la fase 1.

---

## Lo que este flujo NO hace

* No conserva versiones anteriores de un documento. `storage.save_document`
  sobreescribe por nombre fijo (`{control}_{ETIQUETA}.{ext}` desde 2026-09-28, antes
  `{type_code}.{ext}`); la bitácora dice que hubo
  una v2, pero la v1 ya no existe en disco. Decisión explícita del 2026-09-03.
* No toca nada de la fase 3 en adelante mientras el trabajo sea la parte de
  Servicios Escolares (fases 0 a 2).
* No hay chat ni sinodales: modelo y tabla existen, pantalla no.

---

## Qué lo cubre

`tests/fastapi/titulatec/test_expediente_proceso.py`: los cinco
eventos nuevos, las 9 fases, el deep-link `?fase=`, los documentos sin dictamen,
el censo que confirma que la ruta borrada no volvió, el `?from=` válido (Liberados
incluido) y los cinco maliciosos, el regreso por omisión según lo que el actor
puede abrir, los enlaces de las cuatro pestañas y los que se ocultan sin permiso,
y que la página no hace una consulta por documento.

`tests/fastapi/titulatec/test_titulacion_liberados.py` (2026-10-07): la vista
resumida (cabecera, solo fases previas al corte, sin desglose, regreso a
Liberados), quién ve la completa (`page.detail` gana, `read.all` no cuenta) y las
7 acciones del expediente + los 2 visores de archivo en 403 para Titulación, sin
escribir nada.

`tests/fastapi/titulatec/test_expediente_mail.py` (8 pruebas, Task 10 del spec
2026-09-28-titulatec-correos-notificaciones): la zona no se pinta sin filas,
los cinco estados con su etiqueta (`sent`/`pending`/`failed`/`no_recipient`/
`obsolete`) y el motivo visible en el fallido, el asunto cae al nombre del
tipo sin enviar todavía, el destinatario vacío enseña «—», el orden más nuevo
primero, ids estables por fila (`exp-mail-{id}`), el alcance por carrera
(404) y que leerla es una sola consulta sin importar cuántas filas haya.

A mano, en Chromium: `scrollWidth <= innerWidth` a 390/768/1280/1920, contraste
≥4.5 en los doce textos de la vista, el modal entero dentro de la ventana, el
acordeón sobreviviendo a un swap y «abrir una fase no mueve nada de lo de
arriba».

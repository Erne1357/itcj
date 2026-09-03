# Expediente del alumno (admin)

**Ruta:** `/titulatec/admin/processes/{process_id}` · **Fecha:** 2026-09-03
**Quién:** Servicios Escolares (encargado y jefatura), Titulaciones.

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
Procesos / Documentos / Citas / Convocatorias
   └─ «Abrir» | «Expediente» | «Ver expediente»
        ?from=<URL canónica de esa pestaña, con sus filtros>
          │
          ▼
GET /titulatec/admin/processes/{id}?fase=N&doc=CODE&from=…
  require_page_app("titulatec", perms=_PROCESS_VIEW_PERMS)
  assert_process_in_scope(db, user_id, process_id)       ← 404, no 403
  _detail_ctx(...)                                       ← consultas por lote
  render admin/process_detail.html → _exp_shell.html
```

### Zonas

| Id | Qué es |
|---|---|
| `#exp-head` | Regresar · folio · nombre · control · correo · carrera · modalidad · progreso · «Mover de fase» |
| `#exp-fases` | acordeón de las 9 fases (`tt-acc`), la actual abierta |
| `#exp-otros` | movimientos sin fase; **no se pinta si está vacío** |
| `#exp-modal-fase` | modal de mover de fase — **fuera** del shell, ver abajo |

### Contenido por fase

| Fase | Qué enseña |
|---|---|
| 0 · Convocatoria | convocatoria, carrera, modalidad, folio, enlace a la convocatoria |
| 1 · Documentos | los 3 documentos **de solo lectura** + visor (`?doc=`) + «Dictaminar en la bandeja» |
| 2 · Cita de cotejo | cita actual, solicitud de cambio del alumno, enlace a Citas |
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
redirector abierto con la marca de la escuela. `_back_ctx` exige el prefijo
`/titulatec/admin/`, rechaza `//` (que el navegador lee como externa), `..` y la
barra invertida. Lo que no pasa cae a Procesos.

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
  sobreescribe por nombre fijo (`{type_code}.{ext}`); la bitácora dice que hubo
  una v2, pero la v1 ya no existe en disco. Decisión explícita del 2026-09-03.
* No toca nada de la fase 3 en adelante mientras el trabajo sea la parte de
  Servicios Escolares (fases 0 a 2).
* No hay chat ni sinodales: modelo y tabla existen, pantalla no.

---

## Qué lo cubre

`tests/fastapi/titulatec/test_expediente_proceso.py` (39 pruebas): los cinco
eventos nuevos, las 9 fases, el deep-link `?fase=`, los documentos sin dictamen,
el censo que confirma que la ruta borrada no volvió, el `?from=` válido y los
cinco maliciosos, los enlaces de las cuatro pestañas, y que la página no hace una
consulta por documento.

A mano, en Chromium: `scrollWidth <= innerWidth` a 390/768/1280/1920, contraste
≥4.5 en los doce textos de la vista, el modal entero dentro de la ventana, el
acordeón sobreviviendo a un swap y «abrir una fase no mueve nada de lo de
arriba».

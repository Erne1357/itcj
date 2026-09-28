# El alumno sube sus documentos iniciales (Fase 1)

> **Objetivo:** el alumno carga los 3 documentos iniciales y envía la fase 1 a revisión.

| | |
|---|---|
| **Actor(es)** | 👤 Alumno (`graduate`) |
| **Permiso(s)** | `document.api.read.own` (ver) · `...upload.own` · `...delete.own` · `process.api.advance` (enviar) |
| **Trigger** | El alumno toca **«Ir a documentos»** en la tarjeta «Tu proceso» del dashboard (el CTA solo existe si la fase 1 es su fase actual, [acordeón de fases](xcut_student_phase_detail.md)), o entra por el menú del alumno (drawer/rail) |
| **Precondiciones** | Tiene un `TitulationProcess` activo (creado en [import CSV](phase0_school_services_import_csv.md)); **la fase 1 es su `current_phase`** (`in_progress` o `rejected`). **Se valida** en [`PhaseService.assert_student_can_act`](engine_student_phase_lock.md) |
| **Estado final** | 3 `Document` subidos (`review_status=pending`) + fase 1 → `in_review` |

Documentos requeridos (`DocumentType.code`): `birth_certificate`, `high_school_cert`, `curp`.

## Ruta en la app (UI)

1. Dashboard alumno `/titulatec/student/dashboard` → **columna A, tarjeta «Tu proceso»** →
   botón «Ir a documentos». Desde 2026-09-02 **ese es el camino principal**: no hay pantalla
   intermedia de fase, y el CTA lo pinta **solo** la fase actual ([acordeón](xcut_student_phase_detail.md)).
   Alternativas: menú del alumno (drawer/rail) → **Documentos**, o directo
   `/titulatec/student/documents`. Chrome: ver [integración en el shell](xcut_student_shell_embed.md).
2. Por cada documento: tarjeta dropzone (parcial `partials/document_slot.html`).
   Tocar → seleccionar archivo (cámara/galería/PDF) → sube solo (HTMX `change`).
   La casilla dice el tope: «PDF de hasta 2 MB. Si pesa más (hasta 20 MB), lo comprimimos
   automáticamente.» — texto de `storage.pdf_upload_hint()`, con los números de la config
   (`TITULATEC_MAX_PDF_SIZE` / `TITULATEC_MAX_PDF_UPLOAD_SIZE`), nunca escritos en la plantilla.
   El mismo par de números sale en la tarjeta de la fase del acordeón (`_PHASE_INFO` +
   `_with_pdf_limits`, `pages/student.py`).
3. Cuando los 3 están subidos, se habilita **"Enviar a revisión"**.

## Secuencia

```mermaid
sequenceDiagram
    actor U as 👤 Alumno
    participant FE as Navegador (HTMX)
    participant API as pages/student.py
    participant SVC as DocumentService
    participant ST as utils/storage.py
    participant DB as Postgres
    U->>FE: elige archivo en el dropzone
    FE->>API: POST /titulatec/student/documents/{type_code}  (multipart)
    API->>API: archivo.size > 20 MB? → error SIN leer el cuerpo
    API->>SVC: run_in_threadpool(save, db, process, type_code, raw, ...)
    SVC->>ST: save_document(...) (comprime img / PDF > 2 MB → pdf_compress)
    ST-->>SVC: {file_path, mime, size (del archivo GUARDADO)}
    SVC->>DB: UPSERT Document (review_status=pending, version++)
    SVC-->>API: doc
    API-->>FE: parcial document_slot.html (estado actualizado)
    U->>FE: "Enviar a revisión"
    FE->>API: POST /titulatec/student/phase/1/submit
    API->>DB: ProcessPhase[1].status = in_review
    API-->>FE: 204 (reload)
```

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Notif |
|---|---|---|---|---|---|---|---|
| 1 | 👤 | `/student/documents` | ver slots | `GET /student/documents` | `DocumentService.get_document` ×3 | — | — |
| 2 | 👤 | dropzone | subir/re-subir | `POST /student/documents/{type_code}` | `DocumentService.save` (en el threadpool) → `storage.save_document` → `pdf_compress.compress_pdf` si pasa de 2 MB | `titulatec_documents` UPSERT (`review_status=pending`, `version`++, `size_bytes` = lo guardado, `original_name` = el nombre que subió el alumno), archivo en `instance/.../{period}/{control}/documents/{control}_{ETIQUETA}.{ext}` | `ProcessEvent(document_uploaded)` |
| 3 | 👤 | botón ✕ | eliminar | `DELETE /student/documents/{type_code}` | `DocumentService.delete` | borra fila + archivo | — |
| 4 | 👤 | botón enviar | enviar fase | `POST /student/phase/1/submit` | (inline) valida 3 docs | `ProcessPhase[1].status=in_review` | — |

## Tamaño y compresión (desde 2026-09-28)

Dos topes en `itcj2/config.py`, ambos por `.env` (reiniciar los procesos backend):

| Config | Valor | Qué es |
|---|---|---|
| `TITULATEC_MAX_PDF_SIZE` | 2 MB | lo que pesa el archivo **guardado** |
| `TITULATEC_MAX_PDF_UPLOAD_SIZE` | 20 MB | lo máximo que se **recibe** para intentar comprimir |

`storage.save_document`, rama `pdf`, en este orden:

1. extensión `.pdf`;
2. `> 20 MB` → `StorageError` «Tu PDF pesa {X} MB; el máximo que aceptamos es {N} MB.» (la ruta
   ya lo comprobó con `UploadFile.size` **antes de leer el cuerpo**; `save_document` lo repite
   sobre los bytes);
3. número de control alfanumérico (si no, `StorageError`: no se inventa un nombre);
4. `<= 2 MB` → se guarda **intacto** (mismos bytes);
5. `> 2 MB` → `utils/pdf_compress.compress_pdf(raw, target_bytes=2 MB)`: pasadas (150 dpi, JPEG
   q75) → (110, q60) → (96, q50) sobre las **imágenes** de cada página (tope en píxeles = lado
   mayor de la página × dpi; más `compress_content_streams` y compactar objetos), gana la primera
   que cabe. `None` → «Tu PDF pesa {X} MB y aun comprimido supera {L} MB; escanéalo en menor
   resolución o en blanco y negro.»; ilegible/cifrado → «No pudimos leer tu PDF; vuelve a
   generarlo o escanéalo de nuevo.».

Todo se valida **antes** de crear la carpeta: un error no deja nada en disco ni en BD. Una
imagen que pypdf/Pillow no pueden decodificar (CCITT, JBIG2, máscaras raras) se deja como está;
las bitonales (modo `1`) también, porque en CCITT/Flate ya pesan menos que un JPEG. Limitación
conocida: si la página mide lo mismo que la imagen a 72 dpi (algunos convertidores
«imagen → PDF»), ninguna pasada la reduce y el PDF sale como «aun comprimido supera».

La compresión es CPU (segundos en un PDF de 20 MB): por eso la ruta llama `DocumentService.save`
con `run_in_threadpool`.

## Nombre en disco (desde 2026-09-28)

`{control}_{ETIQUETA}.{ext}` (`storage.document_filename`): `ACTA` (`birth_certificate`),
`CERTIFICADO` (`high_school_cert`), `CURP` (`curp`) y, para cualquier otro tipo, el código en
mayúsculas (`INE`, `ANEXO_III`, `EGEL_PROOF`…). El control viene de `core_users` vía
`DocumentService._storage_keys` y solo se usa si casa `^[A-Za-z0-9]+$`. Al resubir se borra
cualquier versión previa del mismo tipo, con el nombre viejo (`{type_code}.*`) o con el nuevo en
otra extensión. Los archivos anteriores al cambio se renombran con
`python -m itcj2.cli.main titulatec rename-documents [--dry-run]` (ver
[revisión de documentos](phase1_school_services_review_docs.md) para el nombre de descarga).

## Estado resultante

- 3 filas en `titulatec_documents` con `review_status=pending`.
- `ProcessPhase[1].status = in_review` → aparece en la bandeja admin para revisión.

## Caminos alternos / errores ❗

- Archivo inválido (extensión, tamaño, PDF que no baja de 2 MB, PDF ilegible, control con
  caracteres raros) → `StorageError`; el endpoint responde **200** con el parcial del slot y el
  `error` pintado dentro de la casilla, más `X-Tt-Error` (percent-codificado con `_hdr`, lo
  decodifica `student/errors.js`). Es 200 a propósito: htmx 2 no hace swap en un 4xx, y el error
  vive en el slot. No hay toast (ese canal es de `htmx:responseError`). No se guarda nada.
- Faltan documentos al enviar → `400` + `X-Tt-Error: "Faltan documentos por subir."`.
- Re-subir un doc ya aprobado/rechazado lo vuelve a `pending` (sobreescribe versión).
- **Fuera de la fase 1** ([guarda de fase](engine_student_phase_lock.md)): `GET
  /student/documents` responde `302` a `/student/dashboard?fase=1` (el acordeón, que sí
  explica la fase) y los tres pasos 2-4 devuelven `400` + `X-Tt-Error`. Los tres son los
  que antes dejaban **reabrir la fase 1 ya aprobada** y **borrar un documento aprobado**
  —fila y fichero— desde la fase 2.
- El paso 2 guarda por el **tipo**, no por la URL: subir un `DocumentType` de otra fase
  (`anexo_iii`, `ine`, `final_project`…) también da `400`.
- Fase 1 `rejected` → sigue abierta: es el camino de corrección y reenvío.

## Flujos relacionados

- ← Previo: [import CSV](phase0_school_services_import_csv.md) (crea el proceso).
- ⤵ Siguiente: [revisión admin de docs iniciales](phase1_admin_review_initial_docs.md).
- 🖥️ Entrada y seguimiento: [acordeón de fases del dashboard](xcut_student_phase_detail.md) — de
  ahí sale el CTA, y ahí se ve el avance documento a documento (aprobado / por corregir / en
  revisión / sin subir) sin abrir esta pantalla.

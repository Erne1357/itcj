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
    API->>DB: lecturas (tipo, proceso, guarda de fase, control) y commit: cierra la transacción
    API->>ST: run_in_threadpool(prepare_document, raw, control, file_kind) (valida + comprime; sin disco ni BD)
    ST-->>API: PreparedDocument (bytes a guardar)
    API->>SVC: run_in_threadpool(save, db, process, type_code, ..., prepared=...)
    SVC->>ST: write_document(prepared, ...) (temporal + os.replace; luego borra versiones viejas)
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
| 2 | 👤 | dropzone | subir/re-subir | `POST /student/documents/{type_code}` | `storage.prepare_document` (en el threadpool, sin transacción abierta; `pdf_compress.compress_pdf` si pasa de 2 MB) → `DocumentService.save(..., prepared=...)` (en el threadpool) → `storage.write_document` | `titulatec_documents` UPSERT (`review_status=pending`, `version`++, `size_bytes` = lo guardado, `original_name` = el nombre que subió el alumno), archivo en `instance/.../{period}/{control}/documents/{control}_{ETIQUETA}.{ext}` | `ProcessEvent(document_uploaded)` |
| 3 | 👤 | botón ✕ | eliminar | `DELETE /student/documents/{type_code}` | `DocumentService.delete` | borra fila + archivo | — |
| 4 | 👤 | botón enviar | enviar fase | `POST /student/phase/1/submit` | (inline) valida 3 docs | `ProcessPhase[1].status=in_review` | — |

## Tamaño y compresión (desde 2026-09-28)

Dos topes en `itcj2/config.py`, ambos por `.env` (reiniciar los procesos backend):

| Config | Valor | Qué es |
|---|---|---|
| `TITULATEC_MAX_PDF_SIZE` | 2 MB | lo que pesa el archivo **guardado** |
| `TITULATEC_MAX_PDF_UPLOAD_SIZE` | 20 MB | lo máximo que se **recibe** para intentar comprimir |

`storage.prepare_document`, rama `pdf`, en este orden (`save_document` = `prepare_document` +
`write_document`, para quien no necesite separarlos):

1. extensión `.pdf`;
2. `> 20 MB` → `StorageError` «Tu PDF pesa {X} MB; el máximo que aceptamos es {N} MB.» (la ruta
   ya lo comprobó con `UploadFile.size` **antes de leer el cuerpo**; `prepare_document` lo repite
   sobre los bytes);
3. número de control alfanumérico (si no, `StorageError`: no se inventa un nombre);
4. `<= 2 MB` → se guarda **intacto** (mismos bytes);
5. `> 2 MB` → `utils/pdf_compress.compress_pdf(raw, target_bytes=2 MB)`: pasadas (150 dpi, JPEG
   q75, tope 1754 px) → (110, q60, 1286 px) → (96, q50, 1123 px) sobre las **imágenes** de cada
   página (más `compress_content_streams` y compactar objetos), gana la primera que cabe. `None` →
   «Tu PDF pesa {X} MB y aun comprimido supera {L} MB; escanéalo en menor resolución o en blanco y
   negro.»; ilegible/cifrado, o un resultado con otro número de páginas → «No pudimos leer tu PDF;
   vuelve a generarlo o escanéalo de nuevo.».

`{X}` va con un decimal redondeado **hacia arriba** (20 MB + 1 byte = «20.1»): lo que pasa del
tope nunca se lee igual al tope.

En cada pasada, cada imagen:

- se **reduce** si su lado largo pasa del MENOR de dos límites: lado mayor de la página
  (pulgadas) × dpi, y el **tope absoluto** de la pasada (≈ lado largo de un A4 a esos dpi). El
  tope absoluto es por los «foto → PDF» (iPhone «Crear PDF», Vista Previa, img2pdf, apps de
  escaneo), que hacen la página del tamaño de la foto a 72 dpi (~42×56″): el límite de la
  página solo nunca los tocaba (revisión 2026-09-28, R1; medido: una foto de 3000×4000 px en
  un PDF de 5.69 MB queda en 0.19 MB a 1315×1754 px);
- se **recodifica** en JPEG a la calidad de la pasada aunque ya quepa, salvo que ya sea un JPEG
  a esa calidad o menor (la calidad se estima de su tabla de cuantización, sin decodificarlo):
  así bajan los escaneos guardados sin pérdida (Flate) o en JPEG q95. Si el JPEG nuevo no pesa
  menos que la imagen original, se queda la original;
- **bitonal** (1 bit, máscaras, CCITT/JBIG2): nunca se toca, en JPEG crecería;
- **de paleta** (`/ColorSpace` `/Indexed`, también por referencia indirecta): nunca se toca.
  pypdf 6.19 decodifica NEGRA una `/Indexed` con `/ASCIIHexDecode` (así escribe Pillow el modo
  P), y como el JPEG negro pesa menos, se aceptaba en silencio (medido: 16.81 → 0.01 MB, todo
  negro). Si por no tocarla el PDF no cabe, se rechaza con el mensaje de siempre (ronda 2);
- que se **decodifica de un solo color** (`getextrema` sin variación en ningún canal) con un
  stream original de más de 4 KB (`UNIFORM_SUSPECT_BYTES`): se deja la original. Una imagen lisa
  de verdad se comprime a casi nada, así que eso delata una mala lectura (ronda 2);
- que declara más de 50 MP (`MAX_IMAGE_PIXELS` de `pdf_compress`): se deja como está sin
  decodificarla. Los JPEG se decodifican ya reducidos (`Image.draft`), no a tamaño completo;
- que pypdf/Pillow no pueden decodificar: se deja como está, sin abortar el resto.

Todo se valida **antes** de crear la carpeta: un error de validación no deja nada en disco ni en
BD.

La compresión es CPU (segundos en un PDF de 20 MB): la ruta corre `prepare_document` y
`DocumentService.save` con `run_in_threadpool`. Y la corre **sin transacción abierta**: antes de
leer el cuerpo hace `commit()` de la transacción de lectura (no hay nada pendiente), así la
conexión no queda «idle in transaction» — con PgBouncer transaccional, un backend fijado —
mientras se comprime; `DocumentService.save(..., prepared=...)` solo escribe el archivo y la fila
en una transacción corta. (Sigue abierta, si hubo *cache miss* de authz, la sesión propia de
`require_page_app`/`get_db`, que se cierra al terminar la petición: es del core, no de esta ruta.)

Escritura (`storage.write_document`): a un temporal en la misma carpeta y `os.replace` al nombre
final (atómico: quien lea ve el archivo anterior completo o el nuevo completo); las versiones
viejas del mismo tipo se borran **después** de escribir la nueva. Si la escritura falla, lo
anterior queda en su lugar.

## Nombre en disco (desde 2026-09-28)

`{control}_{ETIQUETA}.{ext}` (`storage.document_filename`): `ACTA` (`birth_certificate`),
`CERTIFICADO` (`high_school_cert`), `CURP` (`curp`) y, para cualquier otro tipo, el código en
mayúsculas (`INE`, `ANEXO_III`, `EGEL_PROOF`…). El control viene de `core_users` vía
`DocumentService._storage_keys` y solo se usa si casa `^[A-Za-z0-9]+$`; el `type_code`, si casa
`^[a-z0-9_]+$`. El nombre final se une a la carpeta con `safe_join`. Al resubir se borra
cualquier versión previa del mismo tipo, con el nombre viejo (`{type_code}.*`) o con el nuevo en
otra extensión — después de escribir la nueva. Los archivos anteriores al cambio se renombran con
`python -m itcj2.cli.main titulatec rename-documents [--dry-run]`, que nunca pisa un destino
(`os.link` + `unlink`: uno que aparezca a última hora cuenta como conflicto) y que ante
cualquier fallo — también Ctrl-C — deshace los renombres del lote sin commitear y sale con 1.
Cuenta `ya_bien` solo si el archivo con el nombre esperado existe en disco; una fila que ya dice
el nombre nuevo sin archivo sale en `faltantes` (lo que deja un lote deshecho tras un commit «en
duda») (ver
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

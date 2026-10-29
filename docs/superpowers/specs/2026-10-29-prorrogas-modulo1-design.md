# Prórrogas · Módulo 1 (vista de secretaría) — Diseño

- **Fecha:** 2026-10-29 · **Rama:** `feature/core-prorrogas` · **Estado:** borrador para revisión
- **App:** `itcj2/apps/prorrogas_tec/` (key `prorrogas_tec`, páginas `/prorrogas`, API `/api/prorrogas/v2`)
- **Diseño visual:** [`docs/design/prorrogas/secretaria-final.dc.html`](../../design/prorrogas/secretaria-final.dc.html) (proyecto de Claude Design "Prorrogas Module UI Design"); la barra superior es su componente `TopNav` (§8.1).
- **Proceso actual (AS-IS):** diagramas `.drawio` de actividad, secuencia, estados y flujo en `C:\Users\Deigo\Desktop\Prorrogas\ProcesoActual\`.
- **Antecedentes reales:** `C:\Users\Deigo\Desktop\Prorrogas\Antecedentes\` (3 cartas compromiso y el Excel `Prórrogas.xlsx`).

---

## 1. Objetivo

Llevar el proceso de prórroga de pago de inscripción —hoy en papel, oficios a mano y un Excel— al sistema,
empezando por la **secretaria de la Subdirección Académica**, que es quien opera todo el proceso.

**Éxito:** la secretaria procesa una prórroga de principio a fin en la app —invitación, solicitud, decisión,
plan de pagos, carta compromiso firmada por el estudiante, registro de los recibos de Caja y seguimiento de
adeudos— **sin el Excel**, y consulta estadísticas que hoy no tiene.

## 2. Alcance

**Dentro del módulo 1**

- Rol `secretaria` y sus cuatro vistas: **Estadísticas**, **QR y solicitudes**, **Estudiantes**, **Documentos**.
- Un **lado del estudiante mínimo**. Es necesario porque el estudiante entra por QR, llena la solicitud y firma
  en la app. Tiene tres pantallas: *Unirse*, *Solicitud* y *Mi prórroga*.
- Motor de documentos: plantillas `.docx` por año que el sistema llena y convierte a PDF (6 formatos, §6).
- Firma electrónica del estudiante dentro de la app (§7).
- Correos desde `agendatec@cdjuarez.tecnm.mx` y avisos dentro de la plataforma.
- Importación del Excel histórico (§11).

**Fuera (módulos siguientes)**

- Vistas de **Jefes** y **Admin**. La firma digital del Director ("AUTORIZA") vive ahí; en el módulo 1 el
  Director firma en papel.
- Pagos en línea o integración con Cajas/SII. El pago sigue siendo **presencial en Cajas**.
- Bloqueo automático en Centro de Cómputo: sigue siendo un aviso manual con la lista que exporta la secretaria.
- Recordatorios programados (Celery). "Recordar" es una acción manual.
- Alta de semestres: la hace admin en core (`core_academic_periods`).

## 3. Actores, roles y permisos

| Actor | Rol en `prorrogas_tec` | Qué hace |
|---|---|---|
| Estudiante | `student` | Se une por invitación, solicita, firma, consulta su prórroga |
| Secretaria | `secretaria` (nuevo) | Todo el proceso |
| Admin de plataforma | `admin` | Recibe los mismos permisos que la secretaria (las páginas no tienen bypass de admin global) |
| Caja | — (fuera del sistema) | Cobra y emite el recibo con folio |
| Centro de Cómputo | — (fuera del sistema) | Bloquea/desbloquea con la lista que le manda la secretaria |

Las API usan `require_perms("prorrogas_tec", [...])` y las páginas `require_page_app("prorrogas_tec", perms=[...])`.
Códigos, con formato `prorrogas_tec.{módulo}.{api|page}.{acción}`:

| Código | Rol | Entrega |
|---|---|---|
| `prorrogas_tec.secretaria.page.view` | secretaria, admin | Plan 1 |
| `prorrogas_tec.templates.api.read` · `.upload` | secretaria, admin | Plan 1 |
| `prorrogas_tec.invitations.api.create` | secretaria, admin | Plan 2 |
| `prorrogas_tec.requests.api.read.all` · `.decide` | secretaria, admin | Plan 2 |
| `prorrogas_tec.student.page.view` | student | Plan 2 |
| `prorrogas_tec.requests.api.create.own` · `.read.own` · `.cancel.own` | student | Plan 2 |
| `prorrogas_tec.documents.api.sign.own` | student | Plan 2 |
| `prorrogas_tec.plans.api.manage` | secretaria, admin | Plan 3 |
| `prorrogas_tec.payments.api.record` · `.void` | secretaria, admin | Plan 3 |
| `prorrogas_tec.students.api.remind` · `.export` | secretaria, admin | Plan 3 |
| `prorrogas_tec.stats.api.read` | secretaria, admin | Plan 4 |

`database/DML/` está en `.gitignore`: los permisos se siembran con `python -m itcj2.cli.main prorrogas init-prorrogas`
y viajan al servidor por `scp`. Un test de contrato ata los códigos que exige el código con los que siembra el DML.

## 4. Proceso nuevo (TO-BE)

1. **Invitación.** El estudiante llega a la Subdirección. La secretaria le muestra el **QR** (cambia cada 5 min) o,
   si no trae celular, lo **invita a mano** por número de control y el enlace le llega a su correo institucional.
2. **Unirse.** El estudiante abre el enlace. Si no tiene sesión, la página de *Unirse* le pide número de control y
   NIP. Al entrar recibe el rol `student` en la app y pasa a la solicitud.
3. **Solicitud.** Elige el número de plazos (1 a 3), escribe el motivo, confirma su carrera y **firma con el dedo**.
   El sistema genera el **Formato de solicitud** ya firmado y la solicitud aparece en *Solicitudes*.
4. **Decisión.** La secretaria revisa el PDF y **acepta** (comentario opcional) o **rechaza** (motivo obligatorio).
   Se genera la **Carta de aceptación** o la **Carta de rechazo** y el estudiante recibe correo y aviso.
   El rechazo termina el proceso.
5. **Plan de pagos.** La solicitud aceptada aparece en *Estudiantes* como **Sin plan**. Con el estudiante enfrente,
   la secretaria captura el **monto total** (varía: inscripción completa, media por residencias, beca) y de
   **1 a 3 parcialidades** con monto y fecha. Al confirmar se genera la **Carta compromiso** de 1, 2 o 3 pagos.
6. **Firma de la carta compromiso.** El estudiante la firma en *Mi prórroga*. La secretaria imprime la carta firmada
   por el estudiante para la firma del Director y la manda a Servicios Administrativos, como hoy.
7. **Pagos.** El estudiante paga en Cajas y lleva el recibo. La secretaria registra **folio, fecha y monto**.
   La situación se recalcula sola.
8. **Seguimiento.** *Estudiantes* muestra quién está **Atrasado**. **Recordar** le manda correo y aviso.
9. **Bloqueo.** En reinscripción la secretaria **exporta la lista de adeudos** para Centro de Cómputo. Si un
   estudiante de esa lista liquida después, aparece **"Avisar desbloqueo"** hasta que la secretaria lo marca como
   avisado (camino de desbloqueo del AS-IS). Quien liquida a tiempo nunca aparece en la lista.

## 5. Reglas de negocio

- **Semestre de la solicitud:** el renglón de `core_academic_periods` con `start_date ≤ hoy ≤ end_date` al crearla.
  Si no hay ninguno, no se pueden crear solicitudes (`no_hay_semestre`). "Hoy" es hora de Ciudad Juárez (`db_now()`).
- **Una solicitud abierta por estudiante por semestre** (estado `pendiente` o `aceptada`). Tras un rechazo o una
  cancelación se le puede invitar de nuevo.
- **Plazos:** el estudiante pide de 1 a 3; la secretaria puede fijar otro número (1 a 3) en el plan.
- **Monto:** solo la secretaria. Total > 0. La suma de las parcialidades debe ser igual al total.
  Reparto por omisión en **pesos enteros con el sobrante en los primeros pagos**
  ($3,650 en 3 → $1,217 · $1,217 · $1,216); los centavos, si los hay, van al último. Se puede editar.
- **Fechas del plan:** estrictamente ascendentes, desde hoy hasta el `end_date` del semestre.
- **Replantear:** mientras no esté liquidada, la secretaria puede rehacer el plan. Cada confirmación genera una nueva
  versión de la carta compromiso (la anterior queda como sustituida) y pide una nueva firma del estudiante.
- **Recibos:** folio de Caja obligatorio (hasta 40 caracteres) y **único entre recibos vigentes**. Monto > 0 y
  **sin sobrepago** (≤ saldo). Fecha de pago ≤ hoy. Un error se corrige **anulando** el recibo con motivo; nunca
  se borra.
- **Aplicación de pagos:** los recibos vigentes se aplican en orden a la parcialidad pendiente más antigua (FIFO).
  Así un pago parcial o el pago de dos parcialidades juntas no necesitan casos especiales.
- **Situación** (calculada al leer, con la fecha de hoy): `sin_plan` (aceptada sin plan) · `liquidada` (pagado ≥
  total) · `atrasada` (alguna parcialidad con fecha < hoy no cubierta) · `al_corriente` (lo demás).
  En la vista, los filtros "Con adeudo" y "Al corriente" usan `atrasada` y `al_corriente`.
- **Cumplimiento** (para estadísticas, por parcialidad vencida): *a tiempo* si quedó cubierta con recibos de fecha
  ≤ su vencimiento; *tarde* si se cubrió después; *sin pago* si sigue sin cubrir.
- **Recordar:** correo + aviso. Como máximo una vez cada 24 h por estudiante (`ya_recordado`).
- **Correo del estudiante:**
  - `^\d{8}$` (licenciatura) → `L{control}@cdjuarez.tecnm.mx`.
  - `^M\d{8}$` (maestría) → `{control}@cdjuarez.tecnm.mx` (el número de control ya trae la M).
  - Doctorado (`D…`), reingreso (`B…`) y cualquier otro formato → la secretaria lo captura. Si la cuenta ya existe
    con `email`, se propone ese.
- **Invitaciones:**
  - El QR es un token firmado, válido 5 min y **multiuso** (puede haber fila).
  - La invitación manual es de **un solo uso** y vale **48 h**.
  - **Solo la invitación manual crea cuentas.** Si el número de control no existe, la secretaria captura apellidos,
    nombre(s), carrera y correo. La cuenta nace sin NIP y el enlace lleva a *Crea tu NIP*.
  - El QR exige una cuenta existente; si no hay, la página le dice que pida la invitación manual.

## 6. Documentos

### 6.1 Formatos

| Tipo (`doc_type`) | Se genera cuando… | Firma en la app |
|---|---|---|
| `formato_solicitud` | El estudiante envía la solicitud | Estudiante (al enviar) |
| `carta_aceptacion` | La secretaria acepta | — |
| `carta_rechazo` | La secretaria rechaza | — |
| `carta_compromiso_1` / `_2` / `_3` | La secretaria confirma un plan de 1, 2 o 3 pagos | Estudiante (después). El Director firma en papel |

### 6.2 Marcadores

Se escriben en Word como `{{nombre}}`: minúsculas, dígitos y `_`, con espacios opcionales dentro de las llaves.

**Comunes a todos los formatos**

| Marcador | Ejemplo |
|---|---|
| `fecha` | `13/enero/2026` (fecha de generación) |
| `folio` | `PR-00012` |
| `nombre` | `PAYAN FLORES ITZEL GUADALUPE` (apellidos y nombre(s), en mayúsculas) |
| `no_control` | `22111670` |
| `carrera` | `Licenciatura en Administración` |
| `semestre` | `enero – junio 2026` |

**Propios de cada formato**

| Formato | Marcadores |
|---|---|
| `formato_solicitud` | `fecha_solicitud`, `plazos_solicitados`, `motivo`, `correo`, `firma_estudiante`, `firma_estudiante_leyenda` |
| `carta_aceptacion` | `comentario`, `plazos_solicitados` |
| `carta_rechazo` | `motivo_rechazo` |
| `carta_compromiso_N` | `monto_total`, `pagoI_monto` y `pagoI_fecha` para I = 1…N, `firma_estudiante`, `firma_estudiante_leyenda` |

Formatos de los valores: `monto_total` y `pagoI_monto` → `$3,150.00`; `pagoI_fecha` → `26 de febrero de 2026`.

**Obligatorios** (sin ellos, la plantilla se rechaza al subirla):

| Formato | Obligatorios |
|---|---|
| `formato_solicitud` | `nombre`, `no_control`, `motivo`, `plazos_solicitados`, `firma_estudiante` |
| `carta_aceptacion` | `nombre`, `no_control` |
| `carta_rechazo` | `nombre`, `no_control`, `motivo_rechazo` |
| `carta_compromiso_N` | `nombre`, `no_control`, `monto_total`, `firma_estudiante`, `pagoI_fecha` para I = 1…N y, si N ≥ 2, `pagoI_monto` |

- `firma_estudiante` es una **imagen**: se sustituye por el trazo de la firma (1.6 cm de alto). Sin firma queda vacío.
- `firma_estudiante_leyenda` → `Firmado electrónicamente por {nombre} el 13/01/2026 10:42 · folio PR-00012`
  (vacío si no hay firma).

### 6.3 Plantillas

- Solo `.docx`, máximo 5 MB, año entre 2020 y 2100.
- Al subir se rechazan: marcadores desconocidos (por ejemplo, la errata `{{nombr}}`), obligatorios faltantes y
  archivos que no son `.docx` válidos.
- **Cuál se usa** para un formato y un año (el año de la fecha de generación, hora de Ciudad Juárez), en este orden:
  1. La más reciente subida para ese año.
  2. Si no hay, la más reciente del año anterior más cercano.
  3. Si no hay, la **plantilla del sistema** incluida en el repo.
- Los nombres de los funcionarios (Director, Subdirectores) son **texto fijo** de la plantilla. Si cambian, la
  secretaria sube la del año.
- Las plantillas del sistema de la carta compromiso salen de las tres cartas reales de Antecedentes, cambiando los
  datos del estudiante por marcadores. La de 2 pagos además gana la frase del semestre que ya traen las otras dos
  (`…como concepto de inscripción para el semestre {{semestre}}, para el (la) estudiante…`). La de 1 pago dice
  `de la carrera de {{carrera}}`, igual que las otras.
- Los PDF generados **se guardan** y no se regeneran: un documento firmado no puede cambiar. Solo al firmar se vuelve
  a producir el PDF, con los **mismos valores congelados** más la firma.

### 6.4 Texto de los formatos nuevos (plantillas del sistema)

Usan el membrete de la carta de 1 pago. La primera línea va alineada a la derecha, el cuerpo justificado y el cierre
centrado. Una línea vacía separa cada párrafo.

**`carta_aceptacion`**

```
Ciudad Juárez, Chihuahua, {{fecha}}
{{nombre}}
No. de control {{no_control}} · {{carrera}}
PRESENTE
Por medio de la presente se le informa que su solicitud de prórroga de pago de inscripción del semestre {{semestre}}, registrada con el folio {{folio}}, ha sido ACEPTADA.
Para continuar, acuda a la Subdirección Académica para acordar el monto y las fechas de sus pagos; con ello se emitirá su carta compromiso de pago.
{{comentario}}
A T E N T A M E N T E
Excelencia en Educación Tecnológica®
SUBDIRECCIÓN ACADÉMICA
```

**`carta_rechazo`**

```
Ciudad Juárez, Chihuahua, {{fecha}}
{{nombre}}
No. de control {{no_control}} · {{carrera}}
PRESENTE
Por medio de la presente se le informa que su solicitud de prórroga de pago de inscripción del semestre {{semestre}}, registrada con el folio {{folio}}, no fue autorizada por el siguiente motivo:
{{motivo_rechazo}}
Si su situación cambia, puede acudir nuevamente a la Subdirección Académica.
A T E N T A M E N T E
Excelencia en Educación Tecnológica®
SUBDIRECCIÓN ACADÉMICA
```

**`formato_solicitud`**

```
Ciudad Juárez, Chihuahua, {{fecha_solicitud}}
JEOVANNY RAFAEL RODRÍGUEZ MEJÍA
SUBDIRECTOR ACADÉMICO
PRESENTE
Quien suscribe, {{nombre}}, con número de control {{no_control}}, estudiante de {{carrera}}, solicito de la manera más atenta una prórroga para cubrir el pago de inscripción del semestre {{semestre}} en {{plazos_solicitados}} pago(s), por el siguiente motivo:
{{motivo}}
Correo de contacto: {{correo}}
A T E N T A M E N T E
{{firma_estudiante}}
{{nombre}}
{{firma_estudiante_leyenda}}
Folio {{folio}}
```

## 7. Firma electrónica del estudiante

- El estudiante **traza su firma** en un recuadro (dedo o mouse) y confirma: *"Firmo este documento"*. Se guarda un PNG
  de hasta 200 KB.
- Se registra la evidencia: quién, fecha y hora, IP, navegador y **SHA-256 del PDF resultante**. El PDF lleva la
  imagen en `{{firma_estudiante}}` y la leyenda en `{{firma_estudiante_leyenda}}`.
- Es una **firma electrónica simple** (consentimiento con sesión autenticada + evidencia), no e.firma (FIEL).
  Si basta para la institución lo decide la Subdirección. El diseño deja lista la misma mecánica para que el Director
  firme "AUTORIZA" desde la vista de Jefes en el siguiente módulo.

## 8. Vistas

### 8.1 Secretaría (`/prorrogas/secretaria/…`)

**Barra superior (`TopNav`)**

- Barra de 60 px, fondo `#1A130E`.
- A la izquierda, el logo y "Prórrogas".
- Al centro, las pestañas **Estadísticas · QR y solicitudes · Estudiantes · Documentos**. La activa lleva subrayado
  de 4 px `#F27340`.
- A la derecha, el nombre de la usuaria y "Secretaría · Subdirección Académica".

**Paleta y tipografía**

- Colores: `#1A130E` (tinta), `#F7F7F2` (papel), `#652F2A` (vino), `#6799E0` (azul), `#F27340` (naranja),
  `#c4541f` (alerta), fondo `#e9e6e0`.
- Fuentes: Roboto (títulos), Open Sans (texto), IBM Plex Mono (cifras).

| Pestaña | Contenido (adaptado del diseño) |
|---|---|
| **Estadísticas** (`/estadisticas`) | Por año escolar: solicitudes por carrera (dona), % aceptadas/rechazadas, línea de tiempo semanal/mensual. KPIs: pendientes (y antigüedad de la más vieja), tiempo promedio de respuesta, monto total prorrogado, **plazos promedio solicitados** (sustituye "días solicitados"). Cumplimiento: a tiempo / tarde / sin pago. Detalle por carrera y **Exportar** (CSV). **Cambios contra el diseño:** sin las marcas fijas de parcialidades ni de reinscripción en la línea de tiempo (ahora las fechas son por estudiante). |
| **QR y solicitudes** (`/solicitudes`) | QR con cuenta regresiva y **Regenerar**. Modo **Sin celular**: número de control → correo (§5) y, si la cuenta no existe, nombre y carrera. Contadores "Se unieron hoy" e "Invitaciones manuales". Tabla de **pendientes**: nombre, control, correo, recibida, **plazos solicitados** (sustituye "Monto"). Al abrir una, se ven el PDF del Formato de solicitud, el comentario y **Rechazar / Aceptar prórroga**. |
| **Estudiantes** (`/estudiantes`) | Por semestre, con búsqueda y filtros Todos / Con adeudo / Al corriente (más Sin plan y Liquidada). Columnas: control, nombre, **pagos (de 1 a 3 parcialidades)**, faltantes, Recordar. **Exportar adeudos** (lista de bloqueo). Al hacer clic en un renglón se abre el **expediente** lateral: plan de pagos (crear/replantear), registrar/anular recibos, documentos (descargar/imprimir), historial y "Avisar desbloqueo". |
| **Documentos** (`/documentos`) | Por año: los 6 formatos con la plantilla en uso (subida, heredada de otro año o del sistema). **Subir plantilla para {año}** (tipo + archivo), **Descargar** (para editarla en Word), **Vista previa** (PDF con datos de ejemplo) y la lista de marcadores válidos de cada formato. |

### 8.2 Estudiante (`/prorrogas/estudiante/…`)

Pantallas pensadas primero para celular:

- **Unirse** (`/prorrogas/unirse`): entrar con el token, con un login propio si no hay sesión.
- **Crea tu NIP**: solo para cuentas nuevas creadas por invitación manual.
- **Solicitud**: plazos, motivo de 20 a 1000 caracteres, carrera y firma.
- **Mi prórroga**: estado, documentos, botón **Firmar** si hay una carta compromiso pendiente, parcialidades y
  recibos.

## 9. Modelo de datos

Reemplaza el esquema del fork. La rama no está fusionada y esas tablas no existen en producción: el alta inicial
`917f7193` solo está en `main..HEAD`.

| Tabla | Columnas clave |
|---|---|
| `prorrogas_templates` *(Plan 1)* | `doc_type`, `year`, `original_name`, `file_path`, `size_bytes`, `sha256`, `placeholders` (JSON), `uploaded_by_id`, `uploaded_at` |
| `prorrogas_requests` | `origin` (`app`/`excel`), `import_ref` (único), `student_id` (nulo solo si `origin='excel'`), `period_id`, `period_label`, `status` (`pendiente`/`aceptada`/`rechazada`/`cancelada`), `requested_terms`, `reason`. Copia congelada: `control_number`, `student_name`, `program_name`, `program_level`, `email`. Decisión: `decided_by_id`, `decided_at`, `decision_comment`. Plan: `total_amount`, `plan_confirmed_at/_by_id`. Bloqueo: `block_exported_at`, `unblock_notified_at`. Además `last_reminded_at` y fechas. Índice único parcial: `(student_id, period_id)` donde `status IN ('pendiente','aceptada') AND origin='app'` |
| `prorrogas_installments` | `request_id`, `number` (1–3), `amount`, `due_date`. Único `(request_id, number)` |
| `prorrogas_payments` | `request_id`, `origin`, `folio`, `paid_on`, `amount`, `recorded_by_id/_at`, `voided_at/_by_id`, `void_reason`. Único parcial `folio` donde `folio IS NOT NULL AND voided_at IS NULL` |
| `prorrogas_documents` | `request_id`, `doc_type`, `version`, `template_id`, `context` (JSON congelado), `file_path`, `sha256`, `generated_at/_by_id`, `signed_at`, `superseded_at` |
| `prorrogas_signatures` | `document_id`, `signer_id`, `image_path`, `signed_at`, `ip`, `user_agent`, `pdf_sha256` |
| `prorrogas_invitations` | `control_number`, `email`, `token_sha256` (único), `expires_at`, `created_by_id`, `user_created`, `used_at`, `used_by_id` |
| `prorrogas_joins` | `user_id`, `via` (`qr`/`invitacion`), `invitation_id`, `issued_by_id`, `joined_at` |
| `prorrogas_events` | `request_id` (nulo en eventos sin solicitud), `actor_id`, `event_type` (conjunto cerrado), `payload` (JSON), `created_at` |

Los estados son `String` + tupla en Python (convención de TitulaTec), no ENUM de Postgres. Se eliminan
`prorrogas_period_config`, `prorrogas_payments_options`, `prorrogas_notifications`, los viejos
`prorrogas_requests`/`prorrogas_payments` y sus dos ENUM. Los avisos usan `core_notifications` vía
`NotificationService`.

## 10. Integraciones

- **Correo:** Microsoft Graph con `app_key="prorrogas_tec"`. Se conecta una vez en `/itcj/config/email` con la cuenta
  `agendatec@cdjuarez.tecnm.mx`; si TitulaTec se reconecta, Prórrogas no se entera. Se envía con el mismo patrón que
  `titulatec/services/email_helper.py` (best-effort, nunca rompe la operación; en desarrollo registra el enlace en
  el log). Plantillas de correo en `templates/prorrogas_tec/email/`.
- **Avisos:** `NotificationService.create(db, user_id, "prorrogas_tec", type, title, body, data={"url": …})`.
- **PDF:** LibreOffice (ya en `Dockerfile.fastapi`). La conversión se mueve de helpdesk a
  `itcj2/core/utils/docx_pdf.py` para compartirla.
- **QR:** `qrcode-generator@1.4.4` desde jsdelivr, en el navegador (sin dependencia nueva de Python).

## 11. Importación del Excel histórico (Plan 4)

`python -m itcj2.cli.main prorrogas import-excel RUTA.xlsx [--dry-run] [--report RUTA.csv]`

- **Hojas:** una por semestre (`Inscripción Enero - Junio 2026`, … `Enero Junio 2024`). Se importan **todas como
  históricas**: `origin='excel'`, `status='aceptada'`, `period_id` si existe el semestre en core y si no
  `period_label`. `student_id` se liga por número de control cuando la cuenta existe.
- **Columnas** (hojas 2025–2026): `FECHA`, `No. De Control`, `NOMBRE`, `CARRERA`, y por cada mes la terna
  *fecha · importe · bandera*. La bandera `1` es **pagado** y genera un recibo con `paid_on` = fecha de vencimiento y
  folio vacío; `0` o vacío es no pagado. El total es la suma de los importes.
- **Normaliza:**
  - fechas seriales de Excel y fechas en texto (`12 de enero de 2026`)
  - importes en texto (`$1,550,00`, `$3,.000.00`)
  - renglones de continuación sin número de control (se suman al estudiante anterior)
- **Formato viejo:** las dos hojas de 2024 tienen otro formato (`Enero Junio 2024` trae "fecha + importe" en una
  celda) y se interpretan con sus propias reglas.
- **No adivina:** lo que no se puede interpretar sin adivinar (dos fechas en una celda, importes ilegibles) **se omite
  y va al reporte** con hoja, renglón y motivo.
- **Idempotente:** `import_ref = "{hoja}#{renglón}"` es único y re-ejecutar no duplica.

## 12. Qué pasa con el código actual

Se reemplaza lo que el diseño nuevo no usa:

- la ventana de admisión
- el catálogo `payments_options`
- las páginas y APIs de admin del fork
- `api/admin/request.py`
- los `import` copiados de AgendaTec
- los `print()`
- los modelos con nombres fuera de convención

Con eso se cierran los puntos 1–9 de `docs/PENDIENTES.md`. Se conserva:

- el paquete y sus prefijos de URL
- la entrada en el escritorio
- el CLI `init-prorrogas` (gana los DML nuevos)

## 13. Pruebas

- **Dónde:** `tests/fastapi/prorrogas_tec/`, contra Postgres real dentro del contenedor (patrón de
  `tests/fastapi/titulatec/conftest.py`).
- **Cómo se corren:**
  `docker compose -f docker/compose/docker-compose.dev.yml exec backend pytest tests/fastapi/prorrogas_tec -q`.
- **Sin LibreOffice:** las pruebas de conversión a PDF real se saltan si no hay LibreOffice; las rutas que
  convierten se prueban parchando `docx_to_pdf`.
- **Contrato de permisos:** los códigos en `api/` y `pages/` deben existir en `database/DML/prorrogas_tec/` (se salta
  si la carpeta no está, como en CI).

## 14. Entregas

| Plan | Contenido | Resultado demostrable |
|---|---|---|
| **1 — Base y Documentos** | Rol `secretaria`; shell de 4 pestañas; motor `.docx`→PDF; plantillas por año (subir, listar, descargar, vista previa); 6 plantillas del sistema | La secretaria entra, administra sus plantillas y ve cada formato en PDF con datos de ejemplo |
| **2 — Invitación, solicitud y decisión** | Esquema nuevo; QR e invitación manual (con alta de cuentas); lado del estudiante; Solicitudes; cartas de aceptación/rechazo; correo y avisos | Un estudiante entra por QR, solicita y firma; la secretaria acepta o rechaza |
| **3 — Estudiantes y pagos** | Expediente; plan; carta compromiso y su firma; recibos; situación; Recordar; lista de bloqueo y avisos de desbloqueo | Una prórroga completa, de la aceptación a la liquidación, sin Excel |
| **4 — Estadísticas e histórico** | Vista de Estadísticas; importación del Excel | Estadísticas con 2024–2026 |

## 15. Decisiones tomadas por omisión (revisar)

1. **Firma:** trazo + evidencia (§7); no e.firma. El Director firma en papel hasta el módulo de Jefes.
2. **Duración de las invitaciones:** QR de 5 min multiuso; invitación manual de 48 h y un solo uso.
3. **Cuentas nuevas:** solo con invitación manual.
4. **Correo de maestría:** `{control}@…` con la M incluida (`M23111966@cdjuarez.tecnm.mx`). Confirmado el 2026-10-29.
5. **Recibos:** sin sobrepagos; el folio de Caja es único entre recibos vigentes.
6. **Recordar:** una vez cada 24 h por estudiante.
7. **Estadísticas:** sin marcas fijas en la línea de tiempo; "plazos promedio" en lugar de "días solicitados".
8. **Esquema del fork:** se reemplaza (no se migran datos; no hay datos en producción).
9. **Texto de las cartas nuevas:** el de §6.4. La secretaria puede reemplazarlo subiendo sus propias plantillas.

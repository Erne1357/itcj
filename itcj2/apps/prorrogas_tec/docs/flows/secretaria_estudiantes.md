# Secretaría · Estudiantes (plan de pagos, recibos y lista de adeudos)

> **Objetivo:** que la secretaria vea a los estudiantes con prórroga aceptada, confirme o replantee su plan de pagos, registre los recibos de Caja, recuerde el pago y entregue al centro de cómputo la lista de bloqueo (y avise cuando se desbloquea).

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`) |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.view` · API: leer lista, expediente y reparto con `prorrogas_tec.requests.api.read.all`; plan `prorrogas_tec.plans.api.manage`; recibos `prorrogas_tec.payments.api.record` y `…payments.api.void`; recordar `prorrogas_tec.students.api.remind`; exportar y avisar desbloqueo `prorrogas_tec.students.api.export` |
| **Disparador** | Una solicitud queda `aceptada` (llega a la lista **sin plan**) o el estudiante paga en Caja |
| **Precondiciones** | `init-prorrogas` corrido (trae los permisos del Plan 3); LibreOffice para generar la carta compromiso |
| **Estado final** | Solicitud con plan, recibos vigentes y situación `liquidada`; el centro de cómputo ya tiene la lista y el estudiante sabe que se desbloqueó |

## Ruta en la app (UI)

Escritorio → Prórrogas → `/prorrogas/secretaria/estudiantes` → pestaña **Estudiantes** (`static/js/secretaria/estudiantes.js`). Todas las rutas de API cuelgan de `/api/prorrogas/v2/estudiantes`.

## Situación

Se calcula al leer (`services/account.py`), nunca se guarda:

| Situación | Cuándo |
|---|---|
| `sin_plan` | Aceptada sin plan confirmado |
| `liquidada` | Pagado ≥ total |
| `atrasada` | Alguna parcialidad vigente con fecha < hoy y no cubierta |
| `al_corriente` | Lo demás |

**Hoy** = `db_now().date()` (hora de Ciudad Juárez). Filtros de la vista: `todos`, `con_adeudo` (= `atrasada`), `al_corriente`, `sin_plan`, `liquidada`. La lista calcula la cuenta de todas las aceptadas del semestre en Python y luego filtra y pagina (`# shortcut`: pasar a SQL si un semestre supera ~2000 solicitudes).

Los recibos vigentes cubren en orden FIFO la parcialidad vigente más vieja; solo importa la **suma** de lo pagado. Estado de cada parcialidad, en este orden: `pagada`, `vencida` (fecha < hoy y no cubierta), `parcial`, `pendiente`.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Secretaria | Selector de semestre | Semestres con aceptadas; preselecciona el vigente | `GET …/estudiantes/periodos` | `StudentsService.periodos` | — |
| 2 | Secretaria | Tabla y filtros | Busca por control o nombre (`q`), filtra, pagina (`page`, `per_page` máx. 100); trae conteos por situación | `GET …/estudiantes?period_id=&q=&filtro=&page=&per_page=` | `StudentsService.listar` | — |
| 3 | Secretaria | Clic en una fila | Expediente: estudiante, cuenta, recibos (con anulados), carta, plan, bloqueo, recordatorio e historial | `GET …/estudiantes/{id}` | `StudentsService.expediente` | — (solo `aceptada`; si no, 404) |
| 4 | Secretaria | Formulario de plan | Pide el reparto sugerido (el servidor lo calcula, no el JS) | `GET …/estudiantes/reparto?total=&n=` | `PlanService.reparto` | — |
| 5 | Secretaria | **Confirmar plan** / **Replantear** | Envía `{total, parcialidades:[{monto, fecha}]}` | `POST …/estudiantes/{id}/plan` | `PlanService.confirm` | Parcialidades en `prorrogas_installments`, `total_amount`, `plan_confirmed_at/by`; carta `carta_compromiso_{N}` nueva (y las de otro N sustituidas); evento `plan_confirmado`; aviso `carta_lista` al estudiante |
| 6 | Secretaria | **Registrar recibo** | Folio de Caja, fecha y monto | `POST …/estudiantes/{id}/recibos` | `PaymentService.record` | Fila en `prorrogas_payments`; evento `recibo_registrado` |
| 7 | Secretaria | **Anular** | Motivo obligatorio; el recibo nunca se borra | `POST …/estudiantes/{id}/recibos/{payment_id}/anular` `{motivo}` | `PaymentService.void` | `voided_at/by`, `void_reason`; evento `recibo_anulado` |
| 8 | Secretaria | **Recordar** | Recordatorio de pago al estudiante | `POST …/estudiantes/{id}/recordar` | `StudentsService.remind` | `last_reminded_at`; evento `recordatorio_enviado`; aviso y correo `recordatorio` |
| 9 | Secretaria | **Exportar adeudos** | Descarga el `.xlsx` del semestre elegido | `POST …/estudiantes/adeudos.xlsx` `{period_id}` | `StudentsService.export_adeudos` | `block_exported_at` (solo si estaba vacío) en cada solicitud listada; evento `lista_bloqueo_exportada` |
| 10 | Secretaria | **Avisar desbloqueo** | Marca que ya se avisó al centro de cómputo | `POST …/estudiantes/{id}/desbloqueo-avisado` | `StudentsService.mark_unblock` | `unblock_notified_at`; evento `desbloqueo_avisado` |

Los pasos 5 a 8 y 10 responden con el expediente actualizado. Las rutas fijas (`periodos`, `reparto`, `adeudos.xlsx`) van antes de `/{request_id}`. El PDF de la carta se abre en una pestaña nueva con la ruta de PDF de la secretaria (Plan 2); "imprimir" es imprimir desde el navegador.

## Reglas del plan

- Solo una solicitud `aceptada`; el total debe ser > 0 y **igual a la suma de las parcialidades vigentes**.
- De 1 a 3 parcialidades vigentes, con fechas estrictamente ascendentes, desde hoy y hasta el `end_date` del semestre de la solicitud (`plan.fecha_limite` del expediente).
- Montos en `Decimal`, cadenas con dos decimales en el JSON (`"3650.00"`); la entrada acepta número o cadena, sin más de 2 decimales, comas, NaN ni ≤ 0. Reparto por omisión: $3,650 en 3 → $1,217 · $1,217 · $1,216.
- **Replantear** (misma ruta, cuando ya hay plan): se conservan las parcialidades `pagada`; las demás reciben `superseded_at`. Las nuevas se numeran después de las conservadas; conservadas + nuevas ≤ 3 y nuevas ≥ 1. El total no puede ser menor a lo pagado y las fechas nuevas van después de la última conservada. Una parcialidad pagada a medias se sustituye y su dinero cubre la primera nueva. No se replantea una solicitud `liquidada`. `plan.puede_replantear` es falso si está liquidada o si hoy pasó el fin del semestre.
- La carta es `carta_compromiso_{N}` (N = parcialidades vigentes), lista todas y lleva `monto_total`, `pago{I}_monto` y `pago{I}_fecha`. El estudiante la firma desde Mi prórroga ([estudiante_solicitud.md](estudiante_solicitud.md)); firmar nunca bloquea nada.
- Anular un recibo después de un replanteo deja sin cubrir la parcialidad conservada que cubría: la situación se recalcula y se puede replantear otra vez.

## Reglas de los recibos

- Requieren plan y solicitud `aceptada`.
- Folio de Caja: `strip()`, de 1 a 40 caracteres, **único entre los recibos vigentes de todas las solicitudes** (índice único parcial `uq_prorrogas_payments_folio_vigente`); un folio anulado se puede volver a usar.
- Monto ≤ saldo (sin sobrepago). Fecha de pago entre la fecha de creación de la solicitud y hoy.
- Anular pide motivo de 5 a 500 caracteres después de `strip()`.
- Plan, recibo, firma, recordar y desbloqueo toman primero el candado de fila de la solicitud (`FOR UPDATE`); dos recibos a la vez se serializan y el segundo que excede el saldo da `sobrepago`.

## Recordar, lista de adeudos y desbloqueo

- **Recordar:** solo con plan y saldo > 0, una vez cada 24 h por solicitud (`last_reminded_at`). `recordatorio.puede` y `puede_recordar` en la lista lo anticipan.
- **Lista de adeudos (§16.1):** las `atrasada` del semestre elegido al momento de exportar. Hoja `Adeudos` con título, semestre, fecha, línea del criterio y total; tabla desde la fila 7 con 10 columnas (No. de control, Nombre, Carrera, Correo, Folio de la prórroga, Monto total, Pagado, Saldo, Parcialidades vencidas, Vencida desde), encabezados congelados y filtro. Sin adeudos trae una fila "Sin estudiantes con adeudo". Es `POST` porque cambia `block_exported_at`; el JS arma la descarga con un `Blob`.
- **Avisar desbloqueo (§16.2):** solo si la solicitud tiene `block_exported_at`, está `liquidada` y `unblock_notified_at` está vacío (`bloqueo.avisar_desbloqueo`); en la lista, `avisar_desbloqueo`.

## Caminos alternos / errores ❗

Todos salen como `{"error", "message", …}` en la raíz del JSON; la UI muestra `message`.

| Código | Cuándo | HTTP |
|---|---|---|
| `filtro_invalido` | El filtro de la lista no es uno de los cinco | 400 |
| `monto_invalido` | Monto o total ≤ 0, con más de 2 decimales, con comas, NaN o infinito | 400 |
| `plazos_invalidos` | Menos de 1 o más de 3 parcialidades (contando las conservadas), o `n` del reparto fuera de 1–3 | 400 |
| `suma_no_cuadra` | Las parcialidades no suman el total | 400 |
| `fechas_invalidas` | Fuera de orden, antes de hoy, después del fin del semestre o antes de la última parcialidad pagada | 400 |
| `total_menor_que_pagado` | Replantear con un total menor a lo ya pagado | 400 |
| `folio_invalido` | Folio vacío o de más de 40 caracteres | 400 |
| `fecha_invalida` | Fecha de pago futura o anterior a la solicitud | 400 |
| `sobrepago` | El monto excede el saldo | 400 |
| `motivo_requerido` | Anular con motivo de menos de 5 o más de 500 caracteres | 400 |
| `no_encontrada` | La solicitud no existe o no está `aceptada` | 404 |
| `recibo_no_encontrado` | El recibo no existe o es de otra solicitud | 404 |
| `periodo_no_encontrado` | Exportar con un semestre inexistente | 404 |
| `no_aceptada` | Plan o recibo sobre una solicitud que no está `aceptada` | 409 |
| `ya_liquidada` | Replantear una prórroga liquidada | 409 |
| `sin_plan` | Recibo o recordatorio sin plan confirmado | 409 |
| `folio_duplicado` | Ya hay un recibo vigente con ese folio (también si pierde la carrera del índice) | 409 |
| `ya_anulado` | El recibo ya estaba anulado | 409 |
| `sin_saldo` | Recordar sin saldo pendiente | 409 |
| `ya_recordado` | Se recordó hace menos de 24 h | 409 |
| `no_aplica` | Avisar desbloqueo sin lista exportada, sin liquidar o ya avisado | 409 |
| `pdf_no_disponible` | LibreOffice falló al generar la carta; el plan no se guarda y se puede reintentar | 503 |

## Flujos relacionados

- Lado del estudiante: [estudiante_solicitud.md](estudiante_solicitud.md).
- Antes: [secretaria_solicitudes.md](secretaria_solicitudes.md) (aceptar la solicitud).
- Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md` §16.

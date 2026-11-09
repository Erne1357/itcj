# Caja · cobrar los pagos del plan (saldar, anular y ver el recibo)

> **Objetivo:** que Caja busque al estudiante, vea cuánto le falta, marque como pagado el siguiente pago con el folio de su recibo (o anule el último si se equivocó) y consulte la referencia bancaria y el recibo escaneado que subió el alumno.

| | |
|---|---|
| **Actores** | Caja (rol `caja`), admin global (escritura, para emergencias). El `admin` de la app no recibe nada de Caja |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.caja` · API: leer `prorrogas_tec.caja.api.read`; saldar `prorrogas_tec.payments.api.record`; anular `prorrogas_tec.payments.api.void` |
| **Disparador** | El alumno llega a pagar a Caja, o Caja revisa quién tiene un pago por cobrar |
| **Precondiciones** | `init-prorrogas` corrido con `09_insert_caja.sql` (crea el rol `caja`, los dos permisos nuevos y le quita a `secretaria` el cobro) y migración `pr20261109b`; la solicitud debe estar `aceptada`, con semestre de core y con plan confirmado |
| **Estado final** | Recibo vigente en `prorrogas_payments` con el folio de Caja (o anulado con su motivo); la cuenta del alumno se recalcula al leer |

## Ruta en la app (UI)

Escritorio o celular → Prórrogas → `/prorrogas/secretaria/caja` (`static/js/secretaria/caja.js`). Para el rol `caja` la única pestaña se llama **Estudiantes**; el admin global la ve como **Caja**. Las rutas de API cuelgan de `/api/prorrogas/v2/caja`.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Caja | Selector de semestre | Semestres con aceptadas; sin elegir, busca en todos | `GET …/caja/semestres` | `StudentsService.periodos` | — |
| 2 | Caja | Lista **Por cobrar** | Quienes tienen un pago pendiente, con filtro (`todos`, `con_adeudo`, `al_corriente`), orden (`urgente`, `proximo`, `saldo`, `nombre`), semestre y página (8 por página); trae conteos por filtro | `GET …/caja?semestre=&filtro=&orden=&page=` | `CajaService.listar` | — |
| 3 | Caja | Buscador (300 ms de pausa) | Por No. de control o nombre, sin acentos ni mayúsculas, en todos los semestres si no elige uno. Ignora filtro, orden y página, trae hasta 50 (`MAX_RESULTADOS`) ordenados por nombre y `conteos` va en `null`. Aquí sí salen los alumnos sin plan y los liquidados | `GET …/caja?q=&semestre=` | `CajaService.listar` | — |
| 4 | Caja | Clic en un alumno | Detalle: datos, total, pagado, saldo y cada pago con su estado, lo que falta por cobrar, días de vencido, recibo que lo cubrió, si el alumno subió su recibo escaneado y si se puede anular | `GET …/caja/{id}` | `CajaService.detalle` | — |
| 5 | Caja | **Abrir PDF** (referencia) | Referencia bancaria que subió el alumno, solo lectura, en otra pestaña | `GET …/caja/{id}/referencia.pdf` | `referencia_pdf_response` | — |
| 6 | Caja | **Ver recibo** | Recibo escaneado de ese pago, en otra pestaña | `GET …/caja/{id}/parcialidades/{numero}/recibo.pdf` | `ReceiptScanService.read` | — |
| 7 | Caja | **Saldar pago** | Folio y fecha del pago (no hay monto: se cobra completo lo que falta del pago); envía `{numero, folio, fecha}` | `POST …/caja/{id}/saldar` | `PaymentService.settle_next` → `record` | Fila en `prorrogas_payments`; evento `recibo_registrado`. Responde con el detalle actualizado |
| 8 | Caja | **Anular recibo** | Motivo de 5 a 500 caracteres; el recibo nunca se borra; envía `{motivo}` | `POST …/caja/{id}/recibos/{payment_id}/anular` | `PaymentService.void` | `voided_at/by`, `void_reason`; evento `recibo_anulado`. Responde con el detalle actualizado |

La lista, el detalle y los PDF piden `caja.api.read`; saldar y anular piden además su permiso propio. `/semestres` va antes de `/{request_id}` en el router. Todo texto del servidor entra a la pantalla con `textContent`.

## Universo y reglas

- **Universo:** solo solicitudes `aceptada` con semestre de core (`period_id` no nulo). Las históricas del Excel sin semestre quedan fuera; las históricas con semestre aparecen y se cobran. Una solicitud fuera del universo responde `no_encontrada`, también en saldar y anular.
- **Por cobrar:** la lista solo trae a quien tiene un siguiente pago (`proxima`); `con_adeudo` es quien tiene ese pago vencido. Un alumno sin plan o liquidado solo aparece buscándolo.
- **Pago completo, en orden:** Caja solo salda el **siguiente** pago (el `numero` debe ser el de `proxima`); no hay abonos. Si recibos anteriores o del Excel ya cubrieron parte, se cobra solo lo que falta.
- **Folio:** obligatorio, único, `strip()` y mayúsculas, de 1 a 40 caracteres; único entre los recibos vigentes de todas las solicitudes (un folio anulado se puede reusar). Fecha entre la creación de la solicitud y hoy.
- **Solo el último:** se anula únicamente el último recibo vigente (por fecha de pago e id). En el detalle, `anulable` es verdadero solo en el pago que ese recibo cubre. Un recibo viejo que cubre un pago a medias no muestra **Anular** (ver `PENDIENTES.md`, R5).
- **Sin firma de por medio:** Caja cobra aunque el alumno no haya firmado su carta compromiso.
- **Recibo escaneado:** lo sube el alumno ([estudiante_solicitud.md](estudiante_solicitud.md)); Caja no lo valida y puede cobrar sin él. La secretaria es quien avisa una inconsistencia ([secretaria_estudiantes.md](secretaria_estudiantes.md)).
- Saldar y anular toman primero el candado de fila de la solicitud (`FOR UPDATE`); dos cobros a la vez se serializan.

## Caminos alternos / errores ❗

Todos salen como `{"error", "message", …}` en la raíz del JSON; la UI muestra `message`. Un cuerpo mal formado (por ejemplo, `numero` que no es entero) lo rechaza FastAPI con 422 antes del servicio.

| Código | Cuándo | HTTP |
|---|---|---|
| `filtro_invalido` | El filtro de la lista no es `todos`, `con_adeudo` ni `al_corriente` | 400 |
| `orden_invalido` | El orden no es `urgente`, `proximo`, `saldo` ni `nombre` | 400 |
| `folio_invalido` | Folio vacío o de más de 40 caracteres | 400 |
| `fecha_invalida` | Fecha de pago futura o anterior a la solicitud | 400 |
| `motivo_requerido` | Anular con motivo de menos de 5 o más de 500 caracteres | 400 |
| `no_encontrada` | La solicitud no existe, no está `aceptada` o no tiene semestre (en saldar, anular y detalle); también en los PDF cuando no hay referencia o recibo | 404 |
| `recibo_no_encontrado` | Anular un recibo que no existe o es de otra solicitud | 404 |
| `no_aceptada` | Saldar sobre una solicitud que ya no está `aceptada` (carrera con otra operación) | 409 |
| `sin_semestre` | Saldar o anular una prórroga del Excel sin semestre de core (carrera con otra operación) | 409 |
| `sin_plan` | Saldar sin plan confirmado | 409 |
| `pago_cambio` | El `numero` ya no es el siguiente por cobrar (otro cobro o anulación entre medias); hay que revisar el detalle | 409 |
| `folio_duplicado` | Ya hay un recibo vigente con ese folio (también si pierde la carrera del índice `uq_prorrogas_payments_folio_vigente`) | 409 |
| `ya_anulado` | El recibo ya estaba anulado | 409 |
| `no_es_el_ultimo` | Anular un recibo que no es el último vigente | 409 |

## Flujos relacionados

- Antes: [secretaria_estudiantes.md](secretaria_estudiantes.md) (confirmar el plan) y [estudiante_solicitud.md](estudiante_solicitud.md) (referencia y recibo escaneado).

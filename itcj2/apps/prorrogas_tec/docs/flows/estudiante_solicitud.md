# Estudiante · unirse y solicitar la prórroga

> **Objetivo:** que el estudiante que se presentó en persona se una al módulo (QR o invitación), llene su solicitud con firma en pantalla y siga su estado hasta recibir la carta.

| | |
|---|---|
| **Actores** | Estudiante (rol `student`) |
| **Permisos** | Página: `prorrogas_tec.student.page.view` · API: `prorrogas_tec.requests.api.read.own`, `…create.own`, `…cancel.own`, `prorrogas_tec.documents.api.sign.own` |
| **Disparador** | La secretaria le muestra el QR o le envía una invitación |
| **Precondiciones** | Cuenta con sesión; un periodo de Prórrogas abierto hoy ([Configuración](secretaria_configuracion.md)); **una unión** (`prorrogas_joins`) dentro de ese periodo (puerta de acceso) y ninguna solicitud suya de ese semestre |
| **Estado final** | Solicitud `pendiente` con su `formato_solicitud` firmado; después `aceptada` o `rechazada` con su carta; si es aceptada y la secretaria confirma el plan, la carta compromiso queda firmada por el estudiante |

## Ruta en la app (UI)

QR: `/prorrogas/unirse?t=…` (sin sesión, primero `/itcj/login?next=`) → pantalla **Unirse a Prórrogas** (Aceptar) → `/prorrogas/estudiante/solicitud` (formulario) → `/prorrogas/estudiante` (**Mi prórroga**).
Invitación: `/prorrogas/unirse/invitacion/{token}` (no crea cuentas: sin sesión va al login; sin NIP, a Centro de Cómputo) → pantalla Aceptar.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Estudiante | Escanea el QR | Sin sesión va directo a `/itcj/login?next=` y regresa; con sesión ve su nombre y número de control y le pregunta si acepta entrar (un QR vencido o una cuenta sin número de control ven el error sin el botón) | `GET /prorrogas/unirse?t=` | `invitation_service.read_qr`, `.joinable_student` | — |
| 1a | Estudiante | Unirse a Prórrogas | **Aceptar y continuar**: se une y pasa a la solicitud (el QR se vuelve a validar) | `POST /prorrogas/unirse` (`t` en el formulario) | `read_qr`, `join` | Fila en `prorrogas_joins` (`via=qr`) |
| 1b | Estudiante | Enlace del correo | Alternativa: invitación manual; solo la cuenta invitada puede usarla | `GET/POST /prorrogas/unirse/invitacion/{token}` | `validate_invitation`, `consume_invitation` | Login con credenciales institucionales; pantalla Aceptar (GET pregunta, POST une); invitación marcada usada; unión (`via=invitacion`) |
| 2 | Estudiante | Solicitud | Ve si puede solicitar, su semestre y su carrera | `GET /api/prorrogas/v2/estudiante/estado` | `RequestService.access`, `.mine` | — |
| 3 | Estudiante | **Enviar solicitud** | Pagos (1 o 2; antes 1–3), motivo (20–1000), carrera y firma | `POST …/estudiante/solicitudes` | `parse_signature`, `RequestService.create`, `DocumentService.generate` | `prorrogas_requests` (`pendiente`), `formato_solicitud` firmado con IP y agente, evento `solicitud_creada` |
| 4 | Estudiante | Mi prórroga | Ve estado, comentario y documentos; descarga los PDF | `GET …/estudiante/solicitudes/{id}/documentos/{doc}.pdf` | — | — |
| 5 | Estudiante | **Cancelar** | Solo mientras está `pendiente` | `POST …/estudiante/solicitudes/{id}/cancelar` | `RequestService.cancel` | `status=cancelada`, evento `solicitud_cancelada` |
| 6 | Estudiante | Mi prórroga | Una vez aceptada, ve su **plan** (total, pagado, saldo, situación, próxima parcialidad y cada parcialidad con su estado) y sus **recibos** vigentes (folio, fecha, monto) | `GET …/estudiante/estado` | `account.cuenta_json` | — |
| 7 | Estudiante | **Firmar carta compromiso** | Aviso `carta_lista` (plataforma y correo) cuando la secretaria confirma o replantea el plan; dibuja su firma en el lienzo (`static/js/estudiante/firma.js`, compartido con la solicitud) y envía | `POST …/estudiante/solicitudes/{id}/documentos/{doc_id}/firmar` `{firma}` | `parse_signature`, `DocumentService.sign` | Nueva versión de la carta con la firma, IP y agente; sustituye a la anterior; evento `documento_firmado`. No bloquea nada. Responde con la solicitud (mismos campos que `/estado`) |

La firma vuelve a llenar la carta desde el contexto congelado del documento (`doc.context`) y con la misma plantilla con que se generó, nunca desde la cuenta viva: el PDF firmado dice lo que el estudiante revisó. Cada replanteo genera una carta nueva y sustituye la anterior; una carta sustituida ya no se firma.

### Campos nuevos de `/estado`

Cada elemento de `solicitudes` trae, además de lo de la solicitud:

| Campo | Contenido |
|---|---|
| `cuenta` | `total`, `pagado`, `saldo` (cadenas con dos decimales; `null` sin plan), `situacion` (`sin_plan`, `al_corriente`, `atrasada`, `liquidada`), `faltantes`, `vencida_desde`, `proxima` y `parcialidades` (`numero`, `monto`, `fecha`, `cubierto`, `estado`: `pagada`, `vencida`, `parcial`, `pendiente`) |
| `recibos` | Recibos vigentes (los anulados no salen): `folio`, `fecha`, `monto` |
| `por_firmar` | `id` de la carta compromiso vigente sin firmar, o `null` |
| `documentos[].firmado` | Si el documento ya lleva la firma del estudiante |

Una sola solicitud por estudiante y semestre, aunque se rechace o se cancele (también cuenta la importada del Excel de ese semestre): lo garantiza el índice único `uq_prorrogas_requests_semestre`.

## Caminos alternos / errores ❗

La UI muestra `message`. En las páginas de unirse el QR inválido o vencido muestra "pide un código nuevo" sin unir al estudiante.

| Código | Cuándo | HTTP |
|---|---|---|
| `qr_invalido` / `qr_expirado` | QR alterado / de más de 5 min | 400 / 410 |
| `invitacion_invalida` / `invitacion_usada` / `invitacion_expirada` | Enlace desconocido / ya usado / de más de 48 h | 404 / 409 / 410 |
| `invitacion_de_otra_cuenta` | Se abre con otra cuenta; la invitación no se consume | 403 |
| `cuenta_sin_numero_de_control` | Una cuenta de personal escanea el QR o intenta solicitar | 403 |
| `sin_acceso` | Sin unión dentro del periodo | 403 |
| `no_hay_semestre` | Ningún periodo de Prórrogas admite solicitudes hoy (sin configurar, por abrir o cerrado) | 409 |
| `ya_solicito` | Ya tiene una solicitud de este semestre, en cualquier estado (doble envío incluido) | 409 |
| `plazos_invalidos` / `motivo_invalido` / `carrera_invalida` | Datos fuera de rango | 400 |
| `firma_vacia` / `firma_muy_grande` / `firma_invalida` | PNG sin trazos, de más de 200 000 bytes o 2000×2000 px, o ilegible (también al firmar la carta) | 400 |
| `no_cancelable` | Cancelar una solicitud que ya no está `pendiente` | 409 |
| `no_encontrada` | La solicitud o el documento no son suyos (también al firmar) | 404 |
| `documento_no_vigente` | Firmar una carta que un replanteo ya sustituyó | 409 |
| `no_firmable` | Firmar un documento que no es una carta compromiso | 409 |
| `ya_firmado` | La carta ya está firmada (dos firmas a la vez: pasa una, por el candado de fila) | 409 |
| `pdf_no_disponible` | LibreOffice falló: no queda solicitud (o no queda firmada la carta) y puede reintentar | 503 |

## Flujos relacionados

- Lado de la secretaria: [secretaria_solicitudes.md](secretaria_solicitudes.md) y, para el plan y los recibos, [secretaria_estudiantes.md](secretaria_estudiantes.md).
- Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md` §5, §7, §16.

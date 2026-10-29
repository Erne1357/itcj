# Estudiante · unirse y solicitar la prórroga

> **Objetivo:** que el estudiante que se presentó en persona se una al módulo (QR o invitación), llene su solicitud con firma en pantalla y siga su estado hasta recibir la carta.

| | |
|---|---|
| **Actores** | Estudiante (rol `student`) |
| **Permisos** | Página: `prorrogas_tec.student.page.view` · API: `prorrogas_tec.requests.api.read.own`, `…create.own`, `…cancel.own` |
| **Disparador** | La secretaria le muestra el QR o le envía una invitación |
| **Precondiciones** | Cuenta con sesión; un semestre vigente; **una unión** (`prorrogas_joins`) dentro del semestre y posterior al último cambio (`updated_at`: creada, cancelada o decidida) de su última solicitud de ese semestre (puerta de acceso) |
| **Estado final** | Solicitud `pendiente` con su `formato_solicitud` firmado; después `aceptada` o `rechazada` con su carta |

## Ruta en la app (UI)

QR: `/prorrogas/unirse?t=…` → `/prorrogas/estudiante/solicitud` (formulario) → `/prorrogas/estudiante` (**Mi prórroga**).
Invitación: `/prorrogas/unirse/invitacion/{token}` (solo una cuenta que nació de una invitación crea aquí su NIP de 4 dígitos) → mismo formulario.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Estudiante | Escanea el QR | Se une al módulo (sin sesión ve cómo entrar y un botón a `/itcj/login?next=`; una cuenta sin número de control no se une) | `GET /prorrogas/unirse?t=` | `invitation_service.read_qr`, `.join` | Fila en `prorrogas_joins` (`via=qr`) |
| 1b | Estudiante | Enlace del correo | Alternativa: invitación manual; solo la cuenta invitada puede usarla | `GET/POST /prorrogas/unirse/invitacion/{token}` | `validate_invitation`, `set_initial_nip`, `consume_invitation` | NIP inicial si la cuenta es nueva; invitación marcada usada; unión (`via=invitacion`) |
| 2 | Estudiante | Solicitud | Ve si puede solicitar, su semestre y su carrera | `GET /api/prorrogas/v2/estudiante/estado` | `RequestService.access`, `.mine` | — |
| 3 | Estudiante | **Enviar** | Plazos (1–3), motivo (20–1000), carrera y firma | `POST …/estudiante/solicitudes` | `parse_signature`, `RequestService.create`, `DocumentService.generate` | `prorrogas_requests` (`pendiente`), `formato_solicitud` firmado con IP y agente, evento `solicitud_creada` |
| 4 | Estudiante | Mi prórroga | Ve estado, comentario y documentos; descarga los PDF | `GET …/estudiante/solicitudes/{id}/documentos/{doc}.pdf` | — | — |
| 5 | Estudiante | **Cancelar** | Solo mientras está `pendiente` | `POST …/estudiante/solicitudes/{id}/cancelar` | `RequestService.cancel` | `status=cancelada`, evento `solicitud_cancelada` |

Una sola solicitud abierta por estudiante (`pendiente` o `aceptada`): lo garantiza el índice único `uq_prorrogas_requests_abierta`. Para pedir otra tras cancelar o ser rechazado hay que volver a unirse **después** de la cancelación o la decisión.

## Caminos alternos / errores ❗

La UI muestra `message`. En las páginas de unirse el QR inválido o vencido muestra "pide un código nuevo" sin unir al estudiante.

| Código | Cuándo | HTTP |
|---|---|---|
| `qr_invalido` / `qr_expirado` | QR alterado / de más de 5 min | 400 / 410 |
| `invitacion_invalida` / `invitacion_usada` / `invitacion_expirada` | Enlace desconocido / ya usado / de más de 48 h | 404 / 409 / 410 |
| `invitacion_de_otra_cuenta` | Se abre con otra cuenta; la invitación no se consume | 403 |
| `cuenta_con_nip` / `nip_invalido` / `nip_no_coincide` | Crear NIP: la cuenta ya tiene / no son 4 dígitos / no coinciden | 409 / 400 / 400 |
| `cuenta_sin_invitacion_de_alta` | Crear NIP en una cuenta sin NIP que no nació de una invitación (la página le pide entrar con su NIP o pedir ayuda) | 403 |
| `cuenta_sin_numero_de_control` | Una cuenta de personal escanea el QR o intenta solicitar | 403 |
| `sin_acceso` | No hay unión posterior al último cambio de su última solicitud del semestre | 403 |
| `no_hay_semestre` | Ningún período no archivado cubre hoy | 409 |
| `solicitud_abierta` | Ya tiene una `pendiente`/`aceptada` (doble envío incluido) | 409 |
| `plazos_invalidos` / `motivo_invalido` / `carrera_invalida` | Datos fuera de rango | 400 |
| `firma_vacia` / `firma_muy_grande` / `firma_invalida` | PNG sin trazos, de más de 200 000 bytes o 2000×2000 px, o ilegible | 400 |
| `no_cancelable` | Cancelar una solicitud que ya no está `pendiente` | 409 |
| `pdf_no_disponible` | LibreOffice falló: no queda solicitud y puede reintentar | 503 |

## Flujos relacionados

- Lado de la secretaria: [secretaria_solicitudes.md](secretaria_solicitudes.md).
- Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md` §5, §7.

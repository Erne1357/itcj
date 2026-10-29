# Secretaría · QR y solicitudes (dar acceso y decidir)

> **Objetivo:** que la secretaria dé acceso al módulo a quien se presenta en persona (QR o invitación manual) y acepte o rechace las solicitudes pendientes, con la carta correspondiente.

| | |
|---|---|
| **Actores** | Secretaria (rol `secretaria`), admin de la app (rol `admin`) |
| **Permisos** | Página: `prorrogas_tec.secretaria.page.view` · API: `prorrogas_tec.invitations.api.create`, `prorrogas_tec.requests.api.read.all`, `prorrogas_tec.requests.api.decide` |
| **Disparador** | Un estudiante llega a la Subdirección a pedir su prórroga |
| **Precondiciones** | `init-prorrogas` corrido; un semestre en `core_academic_periods` que cubra hoy (no `ARCHIVED`) para que el estudiante pueda solicitar; LibreOffice para generar las cartas |
| **Estado final** | La solicitud pasa de `pendiente` a `aceptada` o `rechazada`, con su carta (`carta_aceptacion` / `carta_rechazo`) y un aviso al estudiante |

## Ruta en la app (UI)

Escritorio → Prórrogas → `/prorrogas/secretaria` (redirige a) `/prorrogas/secretaria/solicitudes` → pestaña **QR y solicitudes**.

## Pasos

| # | Actor | UI | Acción | Endpoint | Service · método | Efecto en BD |
|---|---|---|---|---|---|---|
| 1 | Secretaria | Panel **Código QR** | Se genera el QR al abrir la pestaña (y al pulsar **Regenerar código** o llegar a 0:00) | `POST /api/prorrogas/v2/invitaciones/qr` | `invitation_service.issue_qr` | — (JWT HS256, 5 min, multiuso; se dibuja en el navegador con `qrcode-generator@1.4.4`) |
| 2 | Secretaria | Panel **Sin celular** | Escribe el número de control | `GET …/invitaciones/alumno?control=` | `invitation_service.lookup` | — |
| 3 | Secretaria | **Enviar invitación** | Confirma correo (y nombre/carrera si no hay cuenta) | `POST …/invitaciones` | `invitation_service.invite` | Crea la cuenta si falta (rol `student`), fila en `prorrogas_invitations` (solo sha256 del token, 48 h, un uso), evento `invitacion_enviada`; se guarda y después sale el correo. **Sin aviso en la plataforma**: sin el buzón conectado la invitación no le llega a nadie. La respuesta trae `enviado`; si es `false`, la UI avisa que el correo no salió |
| 4 | Secretaria | Contadores | Ver "Se unieron hoy" (personas distintas) e "Invitaciones manuales" (últimas 3); se refrescan cada 20 s | `GET …/invitaciones/hoy` | `invitation_service.today_summary` | — |
| 5 | Secretaria | Tabla de pendientes | Lista pendientes, la más nueva primero; se refresca cada 20 s con la pestaña visible (no con el modal abierto) | `GET …/solicitudes` | `RequestService.pending` | — |
| 6 | Secretaria | Clic en una fila | Abre el modal con el PDF del formato de solicitud (`<iframe>`) | `GET …/solicitudes/{id}/documentos/{doc}.pdf` | `DocumentService.read_pdf` | — |
| 7 | Secretaria | **Aceptar prórroga** / **Rechazar** | Decide; el comentario es obligatorio al rechazar | `POST …/solicitudes/{id}/decision` `{aceptar, comentario}` | `RequestService.decide` | `status`, `decided_by_id`, `decided_at`, `decision_comment`; documento nuevo; evento `solicitud_aceptada` / `solicitud_rechazada`; aviso en la plataforma y correo al estudiante |

Al terminar, la UI muestra un aviso y quita la fila. La decisión toma un candado de fila (`FOR UPDATE`): con dos secretarias sobre la misma solicitud gana una y hay una sola carta.

## Caminos alternos / errores ❗

Todos salen como `{"error", "message", …}` en la raíz del JSON; la UI muestra `message`.

| Código | Cuándo | HTTP |
|---|---|---|
| `control_invalido` | El número de control no cumple `^[A-Za-z]?\d{8}$` | 400 |
| `correo_requerido` / `correo_invalido` | Falta el correo (formato de control sin correo institucional) o no es válido | 400 |
| `datos_requeridos` / `carrera_invalida` | La cuenta no existe y faltan nombres, apellido paterno o carrera | 400 |
| `motivo_requerido` | Se rechaza sin comentario | 400 |
| `comentario_muy_largo` | El comentario pasa de 1000 caracteres | 400 |
| `no_encontrada` | La solicitud o el documento no existen | 404 |
| `ya_resuelta` | Otra secretaria ya decidió; la UI muestra el mensaje y quita la fila | 409 |
| `pdf_no_disponible` | LibreOffice falló al generar la carta; la solicitud sigue `pendiente` y se puede reintentar | 503 |

Si la librería del QR no carga (sin red al CDN), la pestaña muestra el enlace como texto.

## Flujos relacionados

- Lado del estudiante: [estudiante_solicitud.md](estudiante_solicitud.md).
- Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md` §5, §7, §8.

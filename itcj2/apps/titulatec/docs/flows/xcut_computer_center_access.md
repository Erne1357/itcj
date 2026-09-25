# Accesos de Centro de Cómputo (NIP en dos pasos, 2026-09-24)

> **Objetivo:** que Centro de Cómputo (CC), no Servicios Escolares (SE), sea quien teclea el NIP
> de una cuenta nueva de titulación. SE sigue aprobando/rechazando; una solicitud **sin cuenta**
> que SE aprueba ya no crea el usuario de una vez: pasa a la bandeja **Accesos** de CC, que le da
> el NIP (o la devuelve con nota). El alumno no se entera del paso intermedio: sigue sin correo
> hasta que su acceso queda listo.

| | |
|---|---|
| **Actor(es)** | 🏛️ Servicios Escolares (aprueba, en la bandeja de [Solicitudes](xcut_public_enrollment.md)) · 💻 Centro de Cómputo (da el NIP, devuelve, reasigna — bandeja **Accesos**, este flujo) · 🤖 correo |
| **Permiso(s)** | Un código por ruta, la lista es OR: `titulatec.enrollment_access.page.list` (ver la bandeja) · `titulatec.enrollment_access.api.grant` (dar acceso / aprobar en modo alterno / reenviar liga en modo alterno / reasignar NIP) · `titulatec.enrollment_access.api.return` (devolver a SE, solo modo oficial) · `titulatec.enrollment_access.api.reject` (rechazar, solo modo alterno). Los 4 se conceden a `titulatec_computer_center`, y solo a él. |
| **Trigger** | SE aprueba una solicitud **sin cuenta** (modo oficial) → `awaiting_access`. |
| **Precondiciones** | La solicitud está `awaiting_access` (dar acceso/devolver) o, en modo alterno, en cualquier estado revisable. `cohort.status == 'open'` (D5: las fechas `opens_at`/`closes_at` no cuentan aquí — solo el formulario público las mira). |
| **Sub-flujos** | continúa a [Inscripción pública](xcut_public_enrollment.md) cuando SE aprueba sin cuenta (modo oficial) · ⤵ `ImportService.import_rows` vía `_create_account` (mismo alta que el CSV y la bandeja de Solicitudes) |
| **Estado final** | `converted` con `access_granted_at`/`access_granted_by_id` (acceso dado con NIP) · `approved` (D10: apareció una cuenta, se manda liga en su lugar) · `pending_review` con `return_note` (CC devuelve) · `rejected` (CC cancela, solo modo alterno). |

## Los dos modos, y quién ve qué

Todo lo decide `EnrollmentRequestService.reviewer_mode()`, que lee
`TITULATEC_ENROLLMENT_REVIEWER` (`school_services` | `computer_center`; default
`school_services`) — cambiarlo exige variable de entorno **y reinicio**, no hay toggle en
caliente. `reviewer_label()` da el nombre («Servicios Escolares» / «Centro de Cómputo») que
usan los textos públicos y los correos (`email_helper.py` pasa `revisor` al contexto de la
plantilla).

| | Modo **oficial** (`school_services`, por omisión) | Modo **alterno** (`computer_center`) |
|---|---|---|
| Quién aprueba/rechaza | SE, en [Solicitudes](xcut_public_enrollment.md) | CC, en **esta** bandeja (Solicitudes queda de solo lectura) |
| Quién da el NIP | CC, aquí | CC, en el mismo paso que aprueba (como el flujo previo al 2026-09-24) |
| Solicitudes queda… | Con formularios (Aprobar / Rechazar) | **Solo lectura**: KPIs, "por año", pestañas — sin un solo `<form>`. Sus 3 POST responden `400 X-Tt-Error "En este modo la revisión la hace Centro de Cómputo."` **antes** de abrir sesión (`_alternate_mode_block`), así que ni un POST directo sin la UI cuela |
| Pestañas de Accesos | **Por dar acceso** · **Con acceso** · **Devueltas** | **Por revisar** · **Liga enviada** · **Inscritas** · **Rechazadas** · **Todas** (mismas 5 de Solicitudes) |
| Acciones de Accesos | Dar acceso (NIP) · Devolver a SE (nota) · Reasignar NIP (D8) | Aprobar (NIP o liga, con selector de carrera) · Rechazar (motivo) · Reenviar liga · Dar acceso (a las `awaiting_access` que quedaron de antes de cambiar de modo) · Reasignar NIP (D8) |

**CC no tiene alcance por carrera en ningún modo**: su bandeja ve TODAS las solicitudes (mismo
patrón que la bandeja de GTV, `survey_reviews_admin.py`) — nunca llama a `officer_programs`.

**Cambiar de modo no migra nada.** Si hay filas `awaiting_access` cuando alguien cambia a
`computer_center`, esas filas no desaparecen: la pestaña **Por revisar** del modo alterno las
incluye explícitamente («sobrantes», `_tab_query`, `pages/access_admin.py:148-152`) y «Dar
acceso» sobre ellas sigue siendo `grant_access` (nunca `approve`, que ya no las acepta — devuelve
`_MSG_IN_ACCESS`, «Ya está en Centro de Cómputo para su acceso.»).

## Ruta en la app (UI)

1. 🏛️ SE aprueba una solicitud **sin cuenta** en `/titulatec/admin/solicitudes` (modo oficial:
   botón «Aprobar y pasar a Cómputo», sin campo de NIP) → la fila desaparece de «Por revisar» y
   aparece en la pestaña nueva **«En Cómputo»** de Solicitudes con «En Centro de Cómputo desde
   dd/mm/aaaa hh:mm» + botón **Cancelar solicitud**. Detalle del lado de SE:
   [`xcut_public_enrollment.md`](xcut_public_enrollment.md).
2. 💻 Menú admin **Accesos** (`/titulatec/admin/accesos`, ícono `bi-key`) — solo lo ve quien
   tiene `titulatec.enrollment_access.page.list`. Pestaña **Por dar acceso** (FIFO por
   `reviewed_at`, la hora en que SE aprobó — no `created_at`).
3. 💻 Fila → **¿Tiene cuenta HOY?** (`grant_access` lo revisa otra vez contra `core_users`, D10):
   - **No** → campo NIP (4 dígitos, sin `value`: nunca se pinta) → **Dar acceso**.
   - **Sí** (apareció por CSV/alta manual entre la aprobación de SE y ahora) → la fila avisa
     antes «Ya tiene cuenta: se enviará liga»; el mismo botón (con NIP o sin él, se ignora) emite
     la liga de activación en vez de crear la cuenta.
   - Alternativa: **Devolver a Servicios Escolares** → nota obligatoria (≤2000 caracteres) → la
     solicitud vuelve a «Por revisar» de SE con «Devuelta por Centro de Cómputo: {nota}».
   - La fila sale de la pestaña, así que la respuesta 200 trae un aviso `X-Tt-Notice` (toast del
     listener de `titulatec-utils.js`, `pages/access_admin.py::_grant_notice`): «Acceso dado ·
     folio X · correo enviado»; si `access_mail_unsent`, aviso ámbar «Acceso dado (folio X), pero
     el correo no salió: dicta el NIP o reasígnalo en Con acceso» («Inscritas» en el alterno); D10
     «Ya tenía cuenta: se envió la liga» (ámbar si la liga no salió). **Reasignar NIP** avisa igual:
     «NIP reasignado · correo enviado», «NIP reasignado; no se envió correo» (casilla `no_mail`) o
     ámbar «…el correo no salió: díctalo por teléfono». Ningún aviso lleva el NIP.
4. 💻 Pestaña **Con acceso** — filas `access_granted_at` no nulo (`converted` con NIP, `approved`
   por D10, o una `rejected` que SE canceló después de que CC ya había actuado). Si el correo con
   usuario + NIP no salió, la fila lleva la píldora ámbar «correo no enviado»
   (`access_mail_unsent`) y, mientras la cuenta no haya entrado (`must_change_password=True`) y
   sea la que creó ESTA solicitud, el botón **«Reasignar NIP y reenviar»** (D8): NIP nuevo →
   reescribe la contraseña y reenvía el correo.
5. 💻 Pestaña **Devueltas** — filas `returned_at` no nulo, sin acciones (SE ya la retomó o
   decidió qué hacer).
6. 👤 Correo «Ya tienes acceso» (usuario + NIP, personal) — **exactamente igual** que antes del
   2026-09-24 salvo el texto, que ya no dice «Servicios Escolares te dio de alta» (queda neutro,
   porque en modo oficial fue CC quien tecleó el NIP).
7. **Modo alterno** — la misma URL (`/titulatec/admin/accesos`), pero CC ve las 5 pestañas de
   revisión de Solicitudes: aprueba (con carrera, NIP si no hay cuenta / liga si la hay), rechaza
   con motivo, reenvía la liga y, si quedaron `awaiting_access` de antes de activar el modo, las
   atiende con «Dar acceso» igual que en el oficial.

## Secuencia (modo oficial)

```mermaid
sequenceDiagram
    actor SE as 🏛️ Servicios Escolares
    actor CC as 💻 Centro de Cómputo
    participant B as pages/requests_admin.py
    participant A as pages/access_admin.py
    participant S as EnrollmentRequestService
    participant DB as Postgres
    participant R as Redis
    participant M as Correo (Graph)
    SE->>B: POST /admin/solicitudes/{id}/aprobar (fila sin cuenta)
    B->>S: approve()
    S->>DB: lock + refresh · awaiting_access (SIN correo) · COMMIT
    Note over CC: la fila aparece en /admin/accesos<br/>«Por dar acceso», FIFO por reviewed_at
    CC->>A: POST /admin/accesos/{id}/dar-acceso (nip)
    A->>S: grant_access()
    S->>DB: lock + refresh
    alt sigue sin cuenta
        S->>DB: SAVEPOINT · core_users (hash_nip, role_id graduate) · import_rows (roles graduate) · perfil · converted · access_granted_*
        S->>DB: COMMIT
        S->>R: invalida el caché de authz de los roles nuevos
        S->>M: usuario + NIP → correo personal (_mail_access); sella access_sent_at si sale
    else D10: apareció cuenta (CSV / alta manual)
        S->>DB: sha256(token), vence en 21 días · approved · access_granted_* (NIP se ignora)
        S->>DB: COMMIT
        S->>R: SETEX tt:enroll:tok:<sha256> (claro, 21 días)
        S->>M: liga de activación → correo personal (envío lo sella verify_sent_at, no access_sent_at)
    end
```

Si el correo con usuario + NIP no sale (`access_sent_at` queda NULL), la fila cae en «Con acceso»
con «correo no enviado» y CC puede reasignar:

```mermaid
sequenceDiagram
    actor CC as 💻 Centro de Cómputo
    participant A as pages/access_admin.py
    participant S as EnrollmentRequestService
    participant DB as Postgres
    participant M as Correo (Graph)
    CC->>A: POST /admin/accesos/{id}/reasignar-nip (nip nuevo)
    A->>S: reassign_nip()
    S->>DB: lock + refresh · can_reassign_nip() + señal positiva _request_created_account()
    S->>DB: password_hash = hash_nip(nip) · access_granted_* resellados · access_sent_at = NULL
    S->>DB: ProcessEvent(enrollment_access_reset) SIN el NIP · COMMIT
    S->>M: usuario + NIP nuevo → correo personal (_mail_access); sella access_sent_at si sale
```

## Pasos detallados

| # | Actor | UI / dónde | Acción | Endpoint | Service · método | Efecto en BD | Eventos / Correo |
|---|---|---|---|---|---|---|---|
| 1 | 🏛️ | Solicitudes, fila sin cuenta | Aprobar y pasar a Cómputo | `POST /titulatec/admin/solicitudes/{id}/aprobar` | `EnrollmentRequestService.approve` | solicitud → `awaiting_access`, `reviewed_by_id/at` | — (sin correo) |
| 2 | 💻 | Accesos, «Por dar acceso» | Ver la bandeja | `GET /titulatec/admin/accesos[/body]?status=&cohort_id=` | `_body_ctx` (sin alcance por carrera) | (lectura; `access_unsent`, `can_reassign`, `account_inactive` por fila) | — |
| 3a | 💻 | fila, sin cuenta HOY | Dar acceso (NIP) | `POST /titulatec/admin/accesos/{id}/dar-acceso` | `grant_access` | `core_users` ← usuario = control, `hash_nip(nip)`, `must_change_password`, `role_id = graduate`; `core_user_app_roles` ← `graduate` en `itcj`/`titulatec`; `titulatec_processes` + 9 fases; `core_student_profile`; solicitud → `converted`, `access_granted_by_id/at` | `ProcessEvent(enrollment_self_service, activation=nip_personal_email)` sin NIP; caché de authz invalidado tras el commit; `send_enrollment_approved` → **personal**; sella `access_sent_at` si sale |
| 3b | 💻 | fila, **con cuenta HOY** (D10) | Dar acceso → enviar liga | `POST /titulatec/admin/accesos/{id}/dar-acceso` | `grant_access` | solicitud → `approved`; `verify_token_hash`, `verify_expires_at` (+21 días), `verify_sent_to`, `verify_send_count = 1`; `access_granted_by_id/at` (CC sí actuó); **`access_sent_at` NUNCA se toca aquí** — el envío de esta liga lo cuenta `verify_sent_at`; claro en Redis. La cuenta no se toca ni se reactiva (invariante 1) | `send_verify_enrollment` → **personal**; si sale, `verify_sent_at` |
| 4 | 💻 | fila | Devolver a Servicios Escolares | `POST /titulatec/admin/accesos/{id}/devolver` | `return_to_review` | solicitud → `pending_review`, `returned_by_id/at`, `return_note` (≤2000, obligatoria) | — (sin correo) |
| 5 | 💻 | Con acceso, correo no salió | Reasignar NIP | `POST /titulatec/admin/accesos/{id}/reasignar-nip` | `reassign_nip` | `core_users.password_hash = hash_nip(nip)`; `access_granted_by_id/at` reescritos; `access_sent_at` → NULL hasta que salga | `ProcessEvent(enrollment_access_reset)` sin NIP; `send_enrollment_approved` → personal; sella `access_sent_at` si sale |
| 6 (solo alterno) | 💻 | Por revisar | Aprobar | `POST /titulatec/admin/accesos/{id}/dar-acceso` | `approve` (sobre `pending_review`/legado) o `grant_access` (sobre una `awaiting_access` sobrante) | igual que el paso 3a/3b, pero disparado por CC en un solo clic | igual que 3a/3b |
| 7 (solo alterno) | 💻 | fila | Rechazar | `POST /titulatec/admin/accesos/{id}/rechazar` | `reject` | → `rejected`, `review_note`, `reviewed_by_id/at`, token a NULL | `send_enrollment_rejected` → personal, firmado por `reviewer_label()` = «Centro de Cómputo» |
| 8 (solo alterno) | 💻 | Liga enviada | Reenviar liga | `POST /titulatec/admin/accesos/{id}/reenviar` | `resend_link` | hash y vencimiento nuevos (+21 días), `verify_send_count + 1` | `send_verify_enrollment` → personal |

## Predicados del servicio (no se re-derivan en la página)

- **`access_mail_unsent(req)`** (D8, «correo no enviado» del NIP) — puro, sin BD. Verdadero solo
  si `req.status == "converted"` **y** `req.access_granted_at` no es nulo **y**
  `req.verify_token_hash` es nulo (sin liga viva/gastada) **y** `req.access_sent_at` es nulo.
  **No basta «`access_granted_at` lleno y `access_sent_at` nulo»**: la rama con liga de
  `grant_access` (D10) sella `access_granted_*` y nunca `access_sent_at` (su envío lo cuenta
  `verify_sent_at`), y una fila que `verify()` devolvió a `pending_review` tras fallar la
  revalidación conserva el sello de `access_granted_*` sin ser «correo no enviado». Es el
  **único** predicado de esa marca; la bandeja lo consume, nunca lo reconstruye a mano
  (`pages/access_admin.py:205`).
- **`can_reassign_nip(req, user)`** — condición NECESARIA (no suficiente) para pintar el botón
  «Reasignar NIP»: `status == "converted"`, `access_granted_at` no nulo, `verify_token_hash` nulo,
  y la cuenta de HOY (`user`) sigue con `must_change_password=True` (no ha entrado). No exige
  «correo no enviado» por sí sola — la página combina `can_reassign = access_unsent and
  can_reassign_nip(r, u)` porque D8 es el remedio de ESE correo, no un botón siempre visible.
  Bajo el lock, `reassign_nip()` repite esta condición y además exige la señal POSITIVA
  `_request_created_account(db, req, proc)`: sin ella, una cuenta que llegó por D10 (nace
  también con `must_change_password=True` y dueña de un proceso) podría reasignarse por error —
  es la defensa concreta del invariante 1 («sobre una cuenta que NO creó la solicitud jamás se
  escribe credencial»).

## Estado resultante

- Acceso dado sin cuenta: `titulatec_enrollment_requests.status = converted`,
  `access_granted_by_id/at`, `converted_process_id`. Cuenta nueva con `must_change_password=True`
  y `role_id = graduate`. Siguiente paso natural: el alumno
  [sube sus documentos iniciales](phase1_student_upload_initial_docs.md).
- Acceso dado con D10: `status = approved`, liga de 21 días al correo personal — desde aquí el
  flujo es idéntico al de [Inscripción pública](xcut_public_enrollment.md) con cuenta.
- Devuelta: `status = pending_review`, `returned_by_id/at`, `return_note` — vuelve a la bandeja de
  SE, que puede volver a aprobar o rechazar.
- Reasignado: mismo `status = converted`, `password_hash` nuevo, `access_sent_at` limpio hasta
  que el reenvío salga.

## Caminos alternos / errores ❗

**Dar acceso** (400 con `X-Tt-Error`, invariante: `(False, motivo)` no deja nada escrito y el NIP
nunca sale — ni log, ni header, ni `ProcessEvent.payload`):
«La solicitud ya no existe.» · «Esa solicitud ya no está esperando acceso.» (`_MSG_NOT_AWAITING`:
alguien ya le dio acceso, la devolvió o SE la rechazó/reaprobó) · «Esa convocatoria está cerrada.»
(D5) · «El número de control o el nombre no tienen formato válido.» · «El NIP debe ser exactamente
4 dígitos.» (solo sin cuenta) · «Esa persona ya tiene un proceso en otra convocatoria.» · «Esa
cuenta no tiene contraseña; dala de alta desde la convocatoria y rechaza esta solicitud.» (rama
D10) · «No pudimos completar el acceso; intenta de nuevo.» (excepción con `rollback`,
`pages/access_admin.py`, patrón de `requests_admin.approve`).
Inexistente → **404 liso, sin `X-Tt-Error`** (todas las rutas de esta bandeja).

**Devolver** (solo modo oficial; en el alterno → 400 «En este modo Centro de Cómputo revisa las
solicitudes: ya no se devuelven a Servicios Escolares.»): «Escribe el motivo de la devolución.»
(vacío) · «El motivo de la devolución no puede pasar de 2000 caracteres.» (se **rechaza**, nunca
se recorta en silencio) · «Esa solicitud ya no está esperando acceso.» (ya no es `awaiting_access`
cuando llega el POST — doble clic o ya la tomó otra pestaña).

**Rechazar / Reenviar liga** (solo modo alterno; en el oficial → 400 «En este modo rechazar y
reenviar la liga son de Servicios Escolares.»): rechazar exige motivo no vacío («Escribe el motivo
del rechazo: es lo que la persona lee.») y una solicitud no resuelta («Esa solicitud ya se
resolvió.»); reenviar exige `approved` («Solo se reenvía la liga de solicitudes aprobadas.»).

**Reasignar NIP** (D8, ambos modos): «El NIP debe ser exactamente 4 dígitos.» · «Solo se reasigna
el NIP de una cuenta que creó esta solicitud y todavía no ha entrado.» (`_MSG_NOT_REASSIGNABLE`:
cubre las tres condiciones de `can_reassign_nip` MÁS la señal positiva
`_request_created_account` — cualquiera que falle da el mismo mensaje, a propósito: no hay que
distinguirle a CC POR QUÉ no puede, solo que no puede).

**Fuera de modo, sin pasar por la UI**: cada ruta corta con 400 + `X-Tt-Error` **antes** de tocar
la BD (`_mode_block`/`_alternate_mode_block`), así que un POST directo desde afuera de la
plantilla no aprueba, rechaza, devuelve ni reenvía nada que su modo no permita.

## Limitaciones conocidas ⚠

1. **Cambiar de modo dos veces seguidas puede dejar filas «huérfanas» de UI, no de datos.** Una
   `awaiting_access` nacida en oficial y nunca atendida sigue siendo perfectamente resoluble en
   cualquiera de los dos modos (paso 3/6); lo único que cambia es en qué pestaña aparece.
2. **El riesgo aceptado de [Inscripción pública](xcut_public_enrollment.md#riesgo-aceptado-y-contención)
   sigue vigente**: la liga (rama D10 o con cuenta) viaja al correo que tecleó el solicitante.
   Esta bandeja sostiene la contención 4 («el oficial ve el aviso de a dónde va la liga antes de
   aprobar») con el mismo aviso de identidad que Solicitudes, con el correo a la vista, en toda fila
   que manda una liga: la D10 del modo oficial (SE aprobó cuando no había cuenta y nunca lo vio) y
   «Aprobar y enviar liga» del alterno (CC es el único revisor). La D10 sin contraseña no ofrece
   «Enviar liga» (siempre daría 400): dice «devuélvela a Servicios Escolares».
3. **D2 no es un caso de este flujo, es organigrama**: `head_comp_center` recibe el rol `admin`
   de titulatec **vía su puesto** (no por esta bandeja); con `admin` ve TODO el menú, no solo
   Accesos.

## Flujos relacionados

- ← [Inscripción pública con revisión previa](xcut_public_enrollment.md) — de dónde llega la
  solicitud y qué hace SE antes de que CC la vea.
- → [El alumno sube sus documentos iniciales](phase1_student_upload_initial_docs.md) — lo
  siguiente tras recibir el NIP.
- ← [Máquina de estados](00_state_machine.md#estado-de-una-solicitud-de-auto-inscripción-enrollmentrequeststatus) · [Glosario](_glossary.md)

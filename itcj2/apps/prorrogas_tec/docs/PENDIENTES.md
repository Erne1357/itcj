# Prórrogas · Pendientes

Lista viva de lo que le falta a la app. Lo más nuevo va primero.

---

# Módulo 1 (vista de secretaría) · pendientes vivos

Se actualiza conforme avanza el módulo. Spec: `docs/superpowers/specs/2026-10-29-prorrogas-modulo1-design.md`.
Cuando un punto se resuelve, se marca **[hecho]** con la fecha y el commit.

## Para ti (requieren a una persona)

| # | Pendiente | Por qué importa | Qué hacer |
|---|---|---|---|
| H1 | Revisar a ojo las 6 cartas generadas (Plan 1, Task 5, Step 6) | No hubo forma de ver los PDF desde la sesión. Lo más delicado: la firma del estudiante sobre su nombre no debe desalinear la columna del Director en las cartas compromiso | Abrir `instance/tmp/preview/ejemplo-*.pdf` (llenas con datos de ejemplo). Si algo se ve mal, corregir el `.docx` en `documents/defaults/` con Word |
| H2 | Conectar el buzón `agendatec@cdjuarez.tecnm.mx` para la app **Prórrogas** | Sin eso, una invitación manual no le llega a nadie: no tiene aviso en la plataforma (la pantalla avisa que el correo no salió). Solo las decisiones dejan además un aviso en la plataforma | `/itcj/config/email` → app Prórrogas → iniciar sesión con la cuenta (OAuth) |
| H3 | Confirmar las decisiones del Plan 2 | Cambian cómo entra el estudiante | Ver "Decisiones de este plan" en `docs/superpowers/plans/2026-10-29-prorrogas-plan2-invitacion-solicitud-decision.md` |

## Técnicos (diferidos de la revisión final del Plan 1, 2026-10-29)

| # | Pendiente | Efecto | Arreglo propuesto |
|---|---|---|---|
| T1 | Documentos no ofrece el año siguiente, y el año que se selecciona por omisión es el más nuevo, no el actual | En diciembre no se puede preparar el membrete del año que entra desde la pantalla (la API sí lo acepta) | `TemplateService.years` incluye `año actual + 1`; `documentos.js` selecciona el año actual |
| T2 | Si el archivo de una plantilla falta en disco, descargarla, verla o generar con ella da 500 | Pasa tras una restauración o un borrado manual de `instance/` | Mapear `FileNotFoundError` a 404 `plantilla_no_encontrada` y registrarlo en el log |
| T3 | No hay tope de descompresión al abrir un `.docx` subido | Un `.docx` de 5 MB puede crecer a gigas en memoria (solo lo suben roles de confianza) | Sumar `ZipFile(...).infolist()` y rechazar si pasa de un tope antes de `docx.Document()` |
| T4 | `InvalidDocx` solo cubre abrir el archivo; un error al recorrerlo da 500 al subir | Un `.docx` raro (p. ej. un encabezado que apunta a una parte que no existe) da error genérico | Envolver todo el escaneo de `find_placeholders` / `find_malformed` |
| T5 | Faltan las fuentes **Noto Sans** y **Montserrat** en la imagen (`docker/backend/Dockerfile.fastapi`) | LibreOffice sustituye la fuente y el acomodo de la carta puede cambiar (ligado a H1) | Agregar `fonts-noto-core` y `fonts-montserrat` al Dockerfile y reconstruir |
| T6 | Las plantillas del sistema conservan en sus metadatos (`docProps/core.xml`) los nombres "olivia" e "Iliana Esmeralda Sagarnaga Razcón" | Nombres de personal dentro de archivos del repo | El builder también limpia `author` y `last_modified_by`; regenerar y commitear los 6 `.docx` |
| T7 | Vista previa con `anio=0` usa el año actual en vez de rechazarlo | Menor | `if anio is None` en `api/templates.py` |
| T8 | Detalles: el ejemplo `{{así}}` de la página Documentos no es un marcador válido; el docstring de `fill_docx` sobre la firma vacía es impreciso; la lista de marcadores solo se ve en el diálogo de subida | Cosmético / claridad | Cambiar el ejemplo por `{{nombre}}`, corregir el docstring, mostrar los marcadores también en cada tarjeta |

## Del fork, todavía en el árbol (resuelto por el Plan 2, Task 1)

| # | Pendiente | Nota |
|---|---|---|
| F1 | **[hecho 2026-10-29, Plan 2 Task 1]** La vista de admin vieja (`/prorrogas/admin/*`, copia de AgendaTec) sigue abriéndose si alguien escribe la URL | Desde `f24ba11` nadie aterriza ahí; el Plan 2 la elimina con el resto del código del fork (puntos 1–7 de abajo) |
| F2 | **[hecho 2026-10-29, Plan 2 Task 1]** Prueba roja preexistente `tests/fastapi/observability/test_json_logging.py::test_no_app_log_extra_uses_a_context_id_key` | La causa es `services/request_service.py` del fork (`extra={"request_id": …}`); desaparece al borrarlo |
| F3 | Los 12 permisos viejos del fork (`01`/`02` del DML) | Decidido: se dejan los códigos viejos (Task 1 retiró el código que los pedía). Pero `02` sí tiene efecto: en cada `init-prorrogas` da al rol `admin` todos los permisos de la app, así que con `05` el admin de la app también recibe `student.page.view` y `requests.api.create.own`. Pendiente para ti: limitar `02` a sus códigos o retirarlo (DML no versionado) |

## Solo de desarrollo

- Cuenta de prueba `secretaria.prorrogas` / `Prorrogas#2026` (rol `secretaria`). Se recrea con `docker compose -f docker/compose/docker-compose.dev.yml exec backend python instance/tmp/create_test_secretary.py`. No va a producción.

---

# Herencia del fork (estado al 2026-09-01)

Estado al **2026-09-01**, día en que la app se importó del fork donde estuvo
congelada desde junio. Lo de abajo es lo que le falta para estar al nivel del
resto de las apps del repo (la referencia es `titulatec`).

Ordenado por lo que más duele si se olvida.

---

## 1. Autorización: hay guard, pero es de brocha gorda

> **[obsoleto 2026-10-29]** Los routers y páginas del fork con guard por rol se eliminaron en Plan 2 Task 1. El código nuevo usa `require_perms` / `require_page_app` con permisos granulares (`04`/`05` del DML).

**Estado actual.** La app llegó con los `require_*` **comentados**: los seis
endpoints de `api/periods.py`, los cuatro de `api/requests.py` y las tres páginas
de `pages/admin.py` respondían a cualquiera **sin sesión**. Eso incluía crear y
borrar ventanas de admisión, y listar y editar todas las solicitudes y pagos de
todos los alumnos.

Se cerró con un guard **a nivel de router** —`require_roles("prorrogas_tec",
["admin"])` en la API y `require_page_roles(...)` en las páginas— para no tener
que inventar el árbol de permisos antes de que la app esté terminada. Va en el
router y no en cada firma a propósito: **un endpoint nuevo nace cerrado**.

**Lo que falta.** Cambiar a `require_perms` con los permisos granulares, que ya
están sembrados por `database/DML/prorrogas_tec/01_insert_permissions.sql` (12) y
asignados a roles por el `02`:

| Endpoint | Permiso que le toca |
|---|---|
| `GET /periods`, `GET /periods/{id}`, `GET /periods/academic-periods` | `prorrogas_tec.periods.api.read` |
| `POST/PATCH/DELETE /periods` | `prorrogas_tec.periods.api.manage` |
| `GET /request` | `prorrogas_tec.requests.api.read.all` |
| `PATCH /request/{id}` | `prorrogas_tec.requests.api.update` |
| `GET /request/{id}/payments` | `prorrogas_tec.payments.api.read` |
| `PATCH /request/payments/{id}` | `prorrogas_tec.payments.api.update` |
| páginas admin `home` / `requests` / `periods` | `prorrogas_tec.dashboard.page.view` / `.requests.page.list` / `.periods.page.list` |

Como los permisos ya están en la BD, el cambio **no necesita otra corrida de DML
en producción**: es solo código.

**Ojo con `require_roles` vs `require_perms`.** El primero NO lo bypasea el admin
global del JWT. Al migrar a `require_perms`, un admin de plataforma pasará aunque
no tenga el rol de la app — que es lo esperado, pero es un cambio de
comportamiento, no un detalle.

---

## 2. `api/admin/request.py` es código muerto con permisos ajenos

> **[obsoleto 2026-10-29]** El archivo se borró con el resto del fork (Plan 2 Task 1); las solicitudes las sirven `api/requests_admin.py` y `api/student.py` con permisos propios.

Cuatro endpoints (`admin_list_requests`, `admin_change_request_status`,
`admin_get_request_detail`, `admin_create_request`) que **`router.py` no incluye**:
no están montados, no aparecen en el OpenAPI, no se pueden llamar.

Y si se montaran tal cual, exigirían permisos de **AgendaTec**:

```python
ReadPerm   = require_perms("agendatec", ["agendatec.requests.api.read.all"])
UpdatePerm = require_perms("agendatec", ["agendatec.requests.api.update.all"])
CreatePerm = require_perms("agendatec", ["agendatec.requests.api.create.all"])
```

Eso cruza las dos apps en las dos direcciones: un administrador de prórrogas
necesitaría permisos de AgendaTec para trabajar, y un administrador de AgendaTec
entraría a las solicitudes de prórrogas. **No montar este archivo sin cambiar esos
tres permisos primero.**

Decidir: montarlo con permisos propios, o borrarlo si `api/requests.py` ya cubre lo
que hace (parece que sí, al menos para listar y actualizar).

---

## 3. Acoplamiento con AgendaTec por copiar-pegar

> **[obsoleto 2026-10-29]** `api/requests.py` se borró con el fork (Plan 2 Task 1); ya no hay imports de AgendaTec.

`api/requests.py` importa nueve símbolos de AgendaTec y **no usa ninguno** — cada
uno aparece exactamente una vez en el archivo, la del `import`:

`Appointment`, `TimeSlot`, `Coordinator`, `ProgramCoordinator`,
`ChangeRequestStatusBody`, `AdminCreateRequestBody`, `parse_range_from_params`,
`period_service`, `create_notification`.

Son herencia de que el archivo nació como copia de
`agendatec/api/admin/requests.py`. Borrarlos: hoy hacen que un cambio en AgendaTec
pueda romper el import de Prórrogas sin ninguna razón.

Lo mismo en `static/images/help-desk.png`, copiado de helpdesk y sin referenciar
desde ningún template de esta app.

---

## 4. La nav enseña enlaces que el guard rechaza

> **[obsoleto 2026-10-29]** La nav y las páginas de admin del fork se eliminaron (Plan 2 Task 1); la secretaria y el estudiante tienen sus propias vistas con su guard.

`pages/nav.py::_get_prorrogas_navigation` recibe `user_permissions` y **no lo usa**:

```python
return [item for item in full_nav]
```

Cada item ya trae su `permission` con el código correcto; falta el filtro. Hoy un
usuario sin permisos ve los tres enlaces de administración y se come un 403 al
hacer clic.

---

## 5. El gate de la ventana de admisión es inconsistente

> **[obsoleto 2026-10-29]** `pages/student.py` y la ventana de admisión del fork ya no existen; el acceso lo decide la unión por QR o invitación (`RequestService.access`).

En `pages/student.py`, `/student/new_request` y `/student/close` consultan
`_is_window_open()`, pero en `/student/home` la comprobación está **comentada**:

```python
# if not _is_window_open():
#     return RedirectResponse("/prorrogas/student/close", status_code=302)
```

Resultado: con la ventana cerrada el alumno entra al home igual y solo se entera al
intentar crear la solicitud. Decidir si el home debe redirigir o si el gate vive
solo en el punto de creación — pero que sea una decisión, no un comentario olvidado.

---

## 6. `services/period_service.py`

> **[obsoleto 2026-10-29]** `period_service.py` se borró (Plan 2 Task 1); el semestre sale de `core_academic_periods` y el reloj es `db_now()`.

- **Cinco `print()` de depuración** (`VALOR DE NOW`, `ID:`, `Inicio:`, `Fin:`,
  `No existe un periodo activo`) que escriben a stdout en cada consulta de ventana.
  Cambiar por `logger.debug` o quitar.
- **`datetime.now()` naive contra columnas aware.** `get_active_period()` compara
  con `student_admission_start` / `student_admission_deadline`, que son
  `DateTime(timezone=True)`. El proceso corre en **UTC** dentro del contenedor, así
  que la ventana se desplaza 6–7 h según el horario de verano — el mismo bug que
  AgendaTec ya arregló con `now_app()` (`apps/agendatec/helpers.py`). El módulo ya
  tiene `_get_tz()` y lo usa en los `updated_at`; falta usarlo aquí.

---

## 7. Convenciones de nombre de los modelos

> **[resuelto 2026-10-29]** Los modelos nuevos son `ProrrogaRequest`, `ProrrogaDocument`, `ProrrogaInvitation`, etc.; los del fork se eliminaron.

CLAUDE.md §3.5 pide `CamelCase` singular. Los modelos traen:

| Actual | Debería ser |
|---|---|
| `Request_pro` | `ProrrogaRequest` |
| `Payments_pro` | `ProrrogaPayment` |
| `Payments_options` | `ProrrogaPaymentOption` |
| `Notifications` | `ProrrogaNotification` |

Y hay un typo en el `back_populates`: `Payments_options.resquests` ↔
`Request_pro.paid_options`. Funciona (los dos extremos dicen `resquests`), pero se
lee mal en cada query.

Renombrar es mecánico pero toca ~20 sitios; hacerlo en un commit propio, no
mezclado con features.

---

## 8. Sin tests

> **[resuelto 2026-10-29]** El código del fork se eliminó (Plan 2 Task 1) y lo nuevo tiene pruebas en `tests/fastapi/prorrogas_tec/`.

Cero. La referencia es `tests/fastapi/titulatec/` y `tests/fastapi/directory/`.
Lo mínimo, en este orden:

1. **Guards** — que anónimo reciba 401/302 y un alumno 403 en todo `/admin`. Es lo
   que este commit acaba de arreglar y lo que más barato se vuelve a romper.
2. **Ventana de admisión** — abierta/cerrada/sin período configurado. Congelar el
   reloj: ver `freeze_app_clock` en `tests/fastapi/agendatec/conftest.py`, que
   existe justo porque estos tests dependen de la hora.
3. **Alta de solicitud** — que el alumno solo vea y cancele lo suyo.

---

## 9. Sin `docs/flows/`

> **[resuelto 2026-10-29]** Existen `flows/secretaria_documentos.md`, `flows/secretaria_solicitudes.md` y `flows/estudiante_solicitud.md`. El seguimiento de parcialidades (`admin_track_payments`) llegará con el Plan 3.

La convención del repo (ver `apps/titulatec/docs/flows/README.md`) es documentar
cada flujo: UI → endpoint → service → BD → eventos. Los tres que valen para esta
app:

- `student_create_request.md` — el alumno pide la prórroga.
- `admin_resolve_request.md` — administración aprueba/rechaza.
- `admin_track_payments.md` — seguimiento de parcialidades.

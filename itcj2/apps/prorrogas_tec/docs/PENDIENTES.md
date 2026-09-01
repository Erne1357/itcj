# Prórrogas · Pendientes

Estado al **2026-09-01**, día en que la app se importó del fork donde estuvo
congelada desde junio. Lo de abajo es lo que le falta para estar al nivel del
resto de las apps del repo (la referencia es `titulatec`).

Ordenado por lo que más duele si se olvida.

---

## 1. Autorización: hay guard, pero es de brocha gorda

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

`pages/nav.py::_get_prorrogas_navigation` recibe `user_permissions` y **no lo usa**:

```python
return [item for item in full_nav]
```

Cada item ya trae su `permission` con el código correcto; falta el filtro. Hoy un
usuario sin permisos ve los tres enlaces de administración y se come un 403 al
hacer clic.

---

## 5. El gate de la ventana de admisión es inconsistente

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

La convención del repo (ver `apps/titulatec/docs/flows/README.md`) es documentar
cada flujo: UI → endpoint → service → BD → eventos. Los tres que valen para esta
app:

- `student_create_request.md` — el alumno pide la prórroga.
- `admin_resolve_request.md` — administración aprueba/rechaza.
- `admin_track_payments.md` — seguimiento de parcialidades.

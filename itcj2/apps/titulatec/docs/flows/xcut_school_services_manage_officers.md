# La jefatura da de alta encargados por carrera

> **Objetivo:** que el jefe de Servicios Escolares reparta las carreras entre su personal, y
> que quien quede de encargado **pueda entrar de verdad al sistema**.
>
> ⤵ Compone [el alcance por carrera](engine_officer_scope.md), que es lo que este alta
> alimenta: sin `ProgramPosition`, el encargado no ve a ningún alumno.

| | |
|---|---|
| **Actor** | 🏛️ Jefatura de Servicios Escolares (`titulatec.officers.api.manage`), o el rol `admin` de la app |
| **Pantalla** | `/titulatec/admin/officers` (pestaña **Encargados**) |
| **Rutas** | `GET ""` · `POST ""` (alta) · `POST /{position_id}` (editar) · `POST /{position_id}/deactivate` |
| **Service** | `OfficerService` (`services/officer_service.py`) |
| **Tablas** | `core_positions`, `core_user_positions`, `core_position_app_roles`, `core_program_positions`, **`core_users`** |
| **Precondiciones** | El actor gestiona un departamento: puesto `head_%`/`subdirector_%`/`director`, o el rol `admin` en titulatec (respaldo a Servicios Escolares, `_managed_department_id`) |

---

## Ruta en la app (UI)

1. 🏛️ **Nuevo encargado** (plegado en cuanto existe alguno, abierto cuando la lista está
   vacía) → nombre + usuarios + carreras → **Crear encargado**.
2. 🏛️ Cada encargado es una tarjeta con dos renglones rotulados, **Usuarios** y **Carreras**,
   más **Editar** (edición en línea) y **Quitar**.
3. 🤖 Al guardar, si entre los usuarios elegidos había cuentas inactivas, se reactivan y la
   pantalla lo confirma nombrándolas.

---

## Qué es un «encargado» por dentro

No hay tabla propia. Un encargado es un **`Position` del departamento** con tres cosas
colgando:

```
core_positions  (code = se_officer_<hex8>, department_id = el del jefe, allows_multiple)
   ├── core_position_app_roles  → rol `titulatec_school_services` en la app titulatec
   ├── core_user_positions      → sus ocupantes
   └── core_program_positions   → las carreras que atiende
```

El prefijo `se_officer_` es la **marca de propiedad**: `get_owned_position` solo deja editar
y desactivar puestos que creó esta app. Los puestos compartidos del mismo departamento
(`secretary_school_services`, `head_school_services`, `aux_school_services`, los de división)
cumplen el conjunto amplio y **no se tocan** — colgarles carreras ampliaría en silencio el
alcance de su ocupante, y colgarles usuarios les arrastraría sus `PositionAppRole` en TODAS
las apps. Detalle en [`engine_officer_scope.md`](engine_officer_scope.md) y en la cabecera de
`test_officers_authz.py`.

---

## La reactivación de cuentas (2026-09-17)

### El problema

En Servicios Escolares hay **11 usuarios y 9 tienen `core_users.is_active = false`**: son los
`aux_school_services`, dados de alta en una campaña de inventario de helpdesk y desactivados
desde entonces. `auth_service.py:45` filtra `is_active=True` al iniciar sesión.

Resultado: nombrar encargado a uno de ellos producía un **encargado muerto**. Salía en la
lista, tenía el rol y su alcance por carrera, y no podía entrar. La pantalla no daba ninguna
señal: `department_user_ids` filtra por `UserPosition.is_active`, nunca por `User.is_active`.

### Qué hace ahora

`OfficerService.activate_users(db, user_ids, *, department_id, actor_id)` corre **antes** de
asignar el puesto, en el alta y en la edición. Para cada usuario que esté en el departamento
gestionado **y** tenga la cuenta apagada:

| Campo | Queda en |
|---|---|
| `is_active` | `True` |
| `password_hash` | `hash_nip(DEFAULT_PASSWORD)` |
| `must_change_password` | `True` |

Devuelve la lista de a quiénes tocó, que es lo que pinta la tarjeta de confirmación.

### Las cuatro reglas que lo acotan

1. **Solo el propio departamento.** El conjunto permitido es el mismo `department_user_ids`
   que ya validan `create_officer` y `set_users`. Un `user_id` escrito a mano que no esté ahí
   se ignora en silencio y no se activa. Esta es **la** frontera que impide que un permiso de
   titulatec toque identidad del core a lo ancho del instituto.
2. **Una cuenta ya activa no se toca**, ni su `is_active` ni su contraseña. Sin esto, editar
   un encargado para agregarle una carrera le habría reseteado la contraseña a todos sus
   ocupantes.
3. **En `update`, después de la guarda de propiedad**, nunca antes: no se escribe en
   `core_users` hasta saber que el puesto es de esta app y de este departamento. Un
   `position_id` ajeno devuelve 404 sin haber reactivado a nadie.
4. **Se registra en log** con el actor y los ids afectados.

### Por qué restablecer la contraseña no deja una credencial conocida

`core/api/users.py::password_state` compara el hash contra `DEFAULT_PASSWORD` y devuelve
`must_change=True`: quien tenga exactamente esa contraseña recibe la pantalla de cambio
obligatorio al entrar. La constante vive en `core/utils/security.py` junto a `hash_nip`
(tenía dos copias literales, en `core/api/users.py` y `core/api/users_admin.py`).

**Medido en dev el 2026-09-17:** las 9 cuentas inactivas ya tenían `tecno#2K` y
`must_change_password=True`, así que el restablecimiento no le quita a nadie una contraseña
que estuviera usando. La decisión de restablecer siempre es del usuario, tomada sabiendo que
en general sí invalida la anterior.

### Cómo se dice en pantalla

- **Antes de guardar:** cada fila inactiva del selector lleva la pastilla «Inactiva», el
  contador dice «2 de 11 · 1 se reactivará», y sobre el botón aparece el aviso ámbar «Se
  reactivará 1 cuenta y su contraseña quedará en `tecno#2K`. Tendrá que cambiarla al entrar.»
  (el plural lo ajusta `officers.js`).
- **Después:** tarjeta verde con **los nombres**, no un «3 cuentas» mudo.
- **Siempre:** en la tarjeta del encargado, un ocupante cuya cuenta se apagó *después* sale
  con pastilla roja y el texto «· sin acceso».

---

## Rediseño de la pantalla (2026-09-17)

Medido antes: usuarios y carreras se elegían en dos `<select multiple size="3">` — tres
renglones visibles de 11 usuarios y de 25 carreras, Ctrl+click obligatorio y el cuarto nombre
cortado por la mitad. En la tarjeta, usuarios y carreras iban revueltos en la misma fila de
pastillas y **solo el color** decía cuál era cuál.

| Pieza | Qué es ahora |
|---|---|
| Selector | `.tt-picker`: casillas de 44 px, buscador (sin acentos, Esc limpia), contador vivo, scroll propio de 5 filas y media. Lo ya elegido **nunca** se esconde al filtrar |
| Alta | `<details>` plegado cuando ya hay encargados: con los dos selectores abiertos mide ~470 px y empujaba la lista fuera de la pantalla |
| Tarjeta | Dos renglones `<dt>/<dd>` rotulados, y **Editar** en línea |
| Edición | `POST /admin/officers/{id}`, que **existía con tests desde siempre y ninguna plantilla llamaba**: no había forma de corregir una asignación sin borrar el encargado y rehacerlo |
| Confirmar borrado | `hx-confirm` con el formato «Título\|Cuerpo» → modal compartido vía `htmx:confirm` (el `confirm()` nativo está prohibido) |

JS en `static/js/admin/officers.js`: una sola carga desde `base_admin.html`, delegación en
`document`, sin `data-tt-bound` (Idiomorph lo borraría). La pantalla funciona sin él: las
casillas se marcan, el formulario envía y la respuesta del servidor vuelve a decir lo que pasó.

---

## Caminos alternos / errores ❗

| Situación | Respuesta |
|---|---|
| Actor sin departamento gestionado | `GET`: tarjeta «Sin departamento». `POST`: 400 con `X-Tt-Error` |
| Alta sin nombre | 400 con `X-Tt-Error` |
| Usuario fuera del departamento | `ValueError` → 400 con `X-Tt-Error`, sin escribir nada (tampoco reactiva) |
| `position_id` que esta app no creó | **404** (no 403: el id es enumerable y no se confirma que exista), sin reactivar a nadie |

---

## Cobertura

- `tests/fastapi/titulatec/test_officers_reactivacion.py` — 14 tests: servicio (reactiva,
  no toca a los activos, no sale del departamento, sin departamento no escribe), rutas (alta,
  edición, 404 antes de escribir) y marcado (sin `<select>`, rótulos, formulario de edición,
  sin CSS/JS inline).
- `tests/fastapi/titulatec/test_officers_authz.py` — los dos conjuntos de aceptación.
- `tests/e2e/titulatec/admin-officers.spec.js` — 6 specs con sembrado propio: filtro,
  contador, aviso con su plural, alta que reactiva (verificada en BD), edición en línea y el
  invariante de no-desborde.

---

## Flujos relacionados

- ⤵ [Alcance por carrera del encargado](engine_officer_scope.md) — lo que este alta alimenta.
- ⤵ [Inscripción pública con revisión previa](xcut_public_enrollment.md) — el otro punto donde
  esta app reactiva una cuenta existente.

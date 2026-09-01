# ITCJ E2E (Playwright)

End-to-end suite for ITCJ, covering **helpdesk** (HTMX-boosted navigation
migration: head-support CSS injection, teardown safety, nav active-state,
removed/redirected routes, inventory/tickets pilots), **core config**
(`/itcj/config` — HTMX+idiomorph shell, ConfigPage registry, org tree,
authz/permissions, notifications/presence, DB-driven app badges) and
**agendatec** (split de horarios con cita reservada + scope por carrera, con
escenario sembrado y limpiado dentro del contenedor).

`playwright.config.js` usa `testDir: __dirname`, así que **cada subcarpeta con
`*.spec.js` entra a la corrida completa automáticamente**; no hay lista de apps
que mantener en la config.

This is an **isolated Node project**. It does NOT touch the existing pytest suite.

## Prerequisites

- The dockerized stack is up and serving at `http://localhost:8080`
  (`itcj-nginx-1` → `itcj-backend-1`, plus postgres/redis).
- Docker CLI available on PATH (used to mint the auth token inside the
  `itcj-backend-1` container).
- Node 18+ (developed against Node 24).

## Install

```bash
cd tests/e2e
npm install
npx playwright install chromium
```

## Run

```bash
cd tests/e2e
npx playwright test                            # whole suite (helpdesk + core + agendatec)
npx playwright test helpdesk/                  # only helpdesk specs
npx playwright test core/                      # only core config specs
npx playwright test agendatec/                 # only agendatec specs
npx playwright test helpdesk/nav.spec.js       # one file
npx playwright test --headed                   # watch the browser
npx playwright show-report                     # open the HTML report
```

## Authentication (how it works)

`global-setup.js` runs once before the suite:

1. It mints a JWT **inside** the backend container via
   `docker exec itcj-backend-1 python -c "<inline script>"`. The selection is
   **dual on purpose**: the script finds the first active user that holds
   BOTH the `helpdesk.dashboard.admin` **permission** (so the helpdesk nav
   populates) AND the DB **role** `admin` in the app `itcj` (so `/itcj/config`
   pages render — `_ADMIN_PAGE = Depends(require_page_roles("itcj", ["admin"]))`
   in `core/pages/config.py:40` checks `user_roles_in_app` via `authz_cache`,
   which the JWT `role` claim does **not** bypass). If no
   user satisfies both criteria, setup fails fast with a clear message (grant
   the `itcj` admin role to your helpdesk admin user and retry). It prints
   **only** the signed token to stdout; the `SECRET_KEY` never leaves the
   container and this runner never reads it.
2. Node captures the token (never logged) and writes a Playwright
   `storageState` with the `itcj_token` cookie to `.auth/state.json`.
3. It verifies the cookie is accepted against **both** surfaces: `GET
   /help-desk/` and `GET /itcj/config` must each return `200` (not a `302` to
   login / a role-gate). If either fails, setup fails with a targeted message.

`playwright.config.js` points every test at that `storageState`, so tests are
authenticated without driving the login UI.

### Overrides (env vars)

| Var | Default | Purpose |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:8080` | App base URL |
| `E2E_BACKEND_CONTAINER` | `itcj-backend-1` | Container used to mint the token |

### Core helpers

`core/_helpers.js` is the core-suite counterpart of `helpdesk/_helpers.js`:

- `gotoCore(page, path)` — full navigation to a `/itcj/config...` path; waits
  for the shell (`[data-cfg-page], .config-sidebar` — dual selector: pre-F2
  classic sidebar as fallback, post-F2 HTMX shell via `#cfgMain
  data-cfg-page="..."`) and marks `window.__booted` so nav-morph specs can
  detect an unexpected full reload.
- `mintTokenFor` — re-exported from `../helpdesk/_helpers.js` (mints a token
  for an arbitrary `userId`, used to spin up a **second** authenticated
  session, e.g. for presence/multi-session specs).

## Specs — helpdesk

| File | What it checks |
|---|---|
| `helpdesk/active-highlight.spec.js` | Server-side `active` highlight on the current nav item + `has-active` group. |
| `helpdesk/assign-tickets-pilot.spec.js` | Pilot — assign-tickets page: server-side components + show/hide (BS5, de-jQuery). |
| `helpdesk/deleted-routes.spec.js` | `technician/my-assignments` & `technician/team` → 404; `admin/categories` → `config#categorias`; `admin/inventory/categories` → `config#inv-cat`. |
| `helpdesk/department-pilot.spec.js` | Migración — department_head dashboard: lista server-side + HTMX. |
| `helpdesk/documents-pilot.spec.js` | Migración — documents: server-side + HTMX + Alpine bulk-select. |
| `helpdesk/goToTicketDetail.spec.js` | Boosting away from `my-tickets` does **not** throw `Cannot delete property 'goToTicketDetail'` or any `pageerror`. |
| `helpdesk/htmx-css.spec.js` | Boosting `home → stats` injects `css/admin/stats.css` into `<head>` (head-support) with **no full reload**. |
| `helpdesk/intertab-morph.spec.js` | Inter-tab morph (`hd_boost` + `HelpdeskPage.navigate`): ticket_card → detalle, dashboard → crear, back/forward, HX-Request fragment vs. full page. |
| `helpdesk/inventory-assignment-pilot.spec.js` | Pilot — inventory/assignment: BS5 de-jQuery island + tokens; modal open/close; boosted internal nav. |
| `helpdesk/inventory-campaigns-pilot.spec.js` | Pilot — inventory/campaigns: server-side render, HTMX filter, fragment vs. full page, BS5 modals. |
| `helpdesk/inventory-groups-pilot.spec.js` | Pilot — inventory/groups: server-side render, HTMX filter, fragment vs. full page, "Crear Grupo" BS5 modal. |
| `helpdesk/inventory-items-pilot.spec.js` | Pilot — inventory/items + pending: server-side + HTMX + Alpine, BS5 "Acciones Rápidas" modal, tab switching. |
| `helpdesk/inventory-reports-pilot.spec.js` | Pilot — inventory/reports + verification + dashboard: BS5 shell, charts canvas, HTMX filters, "Verificar" modal. |
| `helpdesk/inventory-retirement-pilot.spec.js` | Pilot — inventory/retirement: server-side render, HTMX filter, confirmation BS5 modal. |
| `helpdesk/jquery-removed.spec.js` | Cierre E-G: jQuery eliminado (`window.jQuery`/`$` undefined), modales BS5 nativos sin shim, nav boost/morph intacta. |
| `helpdesk/my-tickets-pilot.spec.js` | Migración — my-tickets: server-side components + HTMX, Alpine loaded. |
| `helpdesk/nav.spec.js` | "Dashboard Admin" lives inside the **Gestión** dropdown; no stray top-level "Dashboard" item. |
| `helpdesk/scope-inventory.spec.js` | Scope por sub-departamento en el inventario: un jefe anclado en un sub-depto ve su subárbol pero no una rama hermana (`helpdesk.inventory.api.read.subtree`). |
| `helpdesk/secretary-pilot.spec.js` | Migración — secretary dashboard: lista server-side + HTMX. |
| `helpdesk/smoke.spec.js` | Key pages return 200 + render a non-empty `<main data-hd-page>`. Secretary/Department dashboards are role/position-gated (200 or 403), never 5xx. |
| `helpdesk/technician-pilot.spec.js` | Migración — technician dashboard: 4 listas server-side + HTMX (En Espera / historial / asignados). |
| `helpdesk/tickets-list-pilot.spec.js` | Pilot — tickets-list: server-side components + HTMX filter + fragment vs. full page. |
| `helpdesk/warehouse-pilot.spec.js` | Pilot — warehouse (products/entries/movements): server-side + HTMX filters, "Nuevo Producto" BS5 modal. |

## Specs — core

| File | What it checks |
|---|---|
| `core/badge-consistency.spec.js` | C8 (F7): el badge de app (color/icono DB-driven) es idéntico entre apps tab, permissions header y profile; editar el color vía UI propaga a la users list. |
| `core/config-index.spec.js` | Config index (módulo piloto): los módulos se cargan vía el registry `ConfigPage`; sin estilos inline (clases extraídas resuelven). |
| `core/config-nav.spec.js` | Config shell — navegación morph: hx-boost sin recarga, CSS por-página vía head-support, back/forward (`htmx:historyRestore`), modal abierto se limpia en cualquier navegación. |
| `core/config-notify.spec.js` | F6: el shell de config abre una conexión `/notify` presence-only (para que los admins configurando cuenten como "en línea"); sobrevive a la navegación morph. |
| `core/config-org.spec.js` | F5 — organización: árbol interactivo (expandir/buscar), crear sub-departamento nivel 4, confirmación fuerte en oficiales (D4), department/position detail, badge `.subtree` scope-aware, warning de puesto sin ancla. |
| `core/config-roles.spec.js` | Config roles (piloto ConfigPage): crear/eliminar rol vía modales del registry; validación de nombre. |
| `core/config-shell.spec.js` | Config shell — `ConfigShell`/`ConfigUtils`: sin handlers inline, toasts, sidebar móvil/tablet, tokens de color, badges compartidos (C8), controller `ConfigPage` (register/navigate/page). |
| `core/config-system.spec.js` | Config apps/permissions/themes/tasks/email — ConfigPage + envelope flip: color/icono (C4), scope badges (C8), CRUD por modal, cronstrue self-host, paginación top-level. |
| `core/config-users.spec.js` | Users list + user detail: presupuesto de requests (≤3), filtro por app en servidor, búsqueda con `q=`, badge de app con color de BD, apps tab con cache batch, permisos por puesto bajo demanda. |
| `core/mobile-app-card.spec.js` | Mobile app card (F7): el fondo del icono de la tarjeta viene de `core_apps.color` (DB-driven badge). |
| `core/presence.spec.js` | F6: el widget "En Línea" refleja presencia real derivada de `/notify` — abrir una segunda sesión (`mintTokenFor`) sube el conteo. |
| `core/profile-badges.spec.js` | Profile (F7): el tile de app y las notificaciones sembradas usan el color DB-driven de `core_apps` (hex inline). |
| `core/smoke.spec.js` | Panel principal renderiza el shell; página de usuarios renderiza la tabla. |
| `core/socketio-local.spec.js` | Socket.IO vendored (sin CDN): responde 200 desde nginx; helpdesk define `window.io` sin requests a `cdn.socket.io`. |
| `core/user-detail-request-budget.spec.js` | Regresión BUG A: `user_detail` carga con ≤3 fetch/XHR a `/api/core/v2/*` (batch de asignaciones, no N+1 por app). |
| `core/users-create-student.spec.js` | Regresión BUG B: crear un estudiante desde el modal `#newUserModal` dispara el POST y muestra la fila (sin bloquear por `required` oculto). |

## Specs — agendatec

Esta suite **no usa el `storageState` global** (es un admin de helpdesk y no
sirve aquí): `agendatec/split-scope.spec.js:26` declara
`test.use({ storageState: undefined })` y arma sus propios contextos a partir de
los tokens que devuelve el sembrado. `agendatec/_helpers.js` corre Python
**dentro** del contenedor (`docker exec -i <E2E_BACKEND_CONTAINER> python -c`)
para crear el escenario — coordinador con varias carreras, alumno, rango con
cita reservada — y lo borra en `afterAll`; todo lo que crea lleva el marcador
`E2E_AGENDATEC` (`_helpers.js:25`) para poder limpiarlo sin tocar datos reales.
Exporta `seedScenario`, `cleanupScenario`, `stateFor` y `E2E_TAG`.

| File | What it checks |
|---|---|
| `agendatec/split-scope.spec.js` | Pantalla de horarios del coordinador (multi-select de carreras, duración personalizada, rechazo en cliente fuera de 5-60); split sobre un rango **con cita reservada** (cancelar el modal no aplica nada / confirmar muestra al alumno afectado y le acorta la cita); split desalineado (15→10 con cita en 09:15 respeta su hora); scope por carrera en la vista del alumno. |

## Specs — titulatec (PENDIENTE)

**No existe `tests/e2e/titulatec/` todavía.** Queda planeado, y la app lo pide
más que ninguna otra: TitulaTec es **pages-only HTMX** (`itcj2/apps/titulatec/api/`
y `schemas/` están vacíos), su superficie HTTP entera son parciales Jinja
servidos desde `pages/*.py`, y la navegación de admin es un **morph de
`#tt-admin-content`**, no del `<body>`. Nada de eso se cubre con tests de API.

Cuando se escriba, dos cosas la separan de las suites existentes:

- **El token global no sirve.** TitulaTec autoriza 100% con
  `require_page_app("titulatec", perms=[...])`, que **no tiene bypass de admin
  global**: resuelve contra BD. Hará falta mintear tokens por rol
  (`titulatec_school_services_head`, `titulatec_school_services`,
  `titulatec_titulaciones`, `titulatec_vinculacion`, `titulatec_sinodal`,
  `student`), al estilo de `agendatec/_helpers.js`.
- **Hay un segundo eje de authz**: el alcance por carrera
  (`scope_service.officer_programs` → `"ALL" | set[int]`), que necesita un
  encargado con `ProgramPosition` sembrado para poder verificarse.

Además, el menú de admin es data-driven por permiso (`_ADMIN_NAV` /
`admin_nav_items()` en `itcj2/apps/titulatec/pages/nav.py`), así que una spec de
navegación tiene que afirmar sobre las entradas que ese rol sí ve, no sobre una
lista fija.

## Notes

- `.auth/` and `node_modules/` are gitignored (see `.gitignore`).
- **`package.json` sigue diciendo `"name": "itcj-helpdesk-e2e"`** (y su
  `description` habla solo del helpdesk) para una suite que hoy cubre helpdesk,
  core y agendatec. Es solo el nombre del paquete Node privado — nada lo
  resuelve por nombre, así que renombrarlo es cosmético y queda como pendiente
  anotado, no hecho aquí.
- Las tablas de specs de arriba **no son un inventario completo**: hoy hay 37
  `*.spec.js` en `helpdesk/` y la tabla lista 22. Las de `core/` (16) y
  `agendatec/` (1) sí están completas. Al agregar una spec, agregar también su
  renglón.
- Secretary/Department dashboards require an **organizational position**
  (`department_head` role / a current department) that the global-admin token
  does not carry, so they legitimately return `403` for this token. The smoke
  spec accepts `200` or `403` for those, and never a 5xx.
- Core specs that mutate data (apps/roles/permissions/themes/departments/etc.)
  are self-cleaning: they create `e2e_*`-prefixed rows via the UI and remove
  them via `docker exec ... python -c` in `afterAll`/`finally` blocks.

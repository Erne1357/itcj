# Helpdesk E2E (Playwright)

End-to-end suite for the ITCJ **helpdesk** app, focused on the HTMX-boosted
navigation migration (head-support CSS injection, teardown safety, nav
active-state, removed/redirected routes).

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
npx playwright test                 # whole suite
npx playwright test helpdesk/nav.spec.js   # one file
npx playwright test --headed        # watch the browser
npx playwright show-report          # open the HTML report
```

## Authentication (how it works)

`global-setup.js` runs once before the suite:

1. It mints a JWT **inside** the backend container via
   `docker exec itcj-backend-1 python -c "<inline script>"`. The script finds the
   first active user holding `helpdesk.dashboard.admin` (so the nav populates),
   then prints **only** the token (`itcj2.middleware._encode_jwt`,
   `role="admin"` → global-admin bypass). The `SECRET_KEY` never leaves the
   container; this runner never reads it.
2. Node captures the token (never logged) and writes a Playwright
   `storageState` with the `itcj_token` cookie to `.auth/state.json`.
3. It verifies the cookie is accepted: `GET /help-desk/` must return `200`
   (not a `302` to login). If it doesn't, setup fails with a clear message.

`playwright.config.js` points every test at that `storageState`, so tests are
authenticated without driving the login UI.

### Overrides (env vars)

| Var | Default | Purpose |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:8080` | App base URL |
| `E2E_BACKEND_CONTAINER` | `itcj-backend-1` | Container used to mint the token |

## Specs

| File | What it checks |
|---|---|
| `helpdesk/nav.spec.js` | "Dashboard Admin" lives inside the **Gestión** dropdown (→ `/help-desk/admin/home`); no stray top-level "Dashboard". |
| `helpdesk/htmx-css.spec.js` | Boosting `home → stats` injects `css/admin/stats.css` into `<head>` (head-support) with **no full reload**. |
| `helpdesk/goToTicketDetail.spec.js` | Boosting away from `my-tickets` does **not** throw `Cannot delete property 'goToTicketDetail'` or any `pageerror`. |
| `helpdesk/active-highlight.spec.js` | Server-side `active` highlight on the current nav item + `has-active` group. |
| `helpdesk/deleted-routes.spec.js` | `technician/my-assignments` & `technician/team` → 404; `admin/categories` → `config#categorias`; `admin/inventory/categories` → `config#inv-cat`. |
| `helpdesk/smoke.spec.js` | Key pages return 200 + render a non-empty `<main data-hd-page>`. Secretary/Department dashboards are role/position-gated (200 or 403). |

## Notes

- `.auth/` and `node_modules/` are gitignored (see `.gitignore`).
- Secretary/Department dashboards require an **organizational position**
  (`department_head` role / a current department) that the global-admin token
  does not carry, so they legitimately return `403` for this token. The smoke
  spec accepts `200` or `403` for those, and never a 5xx.

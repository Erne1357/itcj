// @ts-check
/**
 * Helpers E2E de la app **adhoc** ("Calidad"). Molde: tests/e2e/helpdesk/_helpers.js.
 *
 * SHELL
 * -----
 * `adhoc` no usa el marcador `data-*-page` de helpdesk/core: su layout
 * (itcj2/apps/adhoc/templates/adhoc/base_adhoc.html) expone un único
 * `<main class="adhoc-page" id="adhoc-main">`. Ese es el selector de shell.
 *
 * `window.__booted`
 * -----------------
 * SÍ aplica: el nav (`partials/_nav.html`), la rejilla del panel
 * (`panel/panel.html`) y la de configuración (`panel/config.html`) llevan
 * `hx-boost="true"`, así que la navegación entre secciones la hace HTMX sin
 * recargar el documento. El marcador que instalan `gotoAdhoc`/`gotoAdhocAs`
 * sobrevive a un swap boosted y se pierde en un full reload, que es
 * exactamente el detector que usan las otras suites.
 *
 * LIMPIEZA
 * --------
 * Convención del repo: todo lo que crea un spec lleva el prefijo `e2e_` y se
 * borra en `afterAll` con `docker exec ... python -c`. `cleanupAdhoc()` hace
 * ese barrido completo en el orden que exigen las FKs sin `ondelete`
 * (`adhoc_tasks.flow_step_id` y `adhoc_documents.current_step_id` son
 * RESTRICT: hay que soltarlas antes de borrar pasos o flujos).
 */
const path = require('path');
const { expect, request: pwRequest } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { mintTokenFor } = require('../helpdesk/_helpers');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';
const STORAGE_STATE = path.join(__dirname, '..', '.auth', 'state.json');

/** Selector del shell de adhoc (base_adhoc.html). */
const ADHOC_SHELL = 'main#adhoc-main';

/** Prefijo obligatorio de todo dato creado por la suite. */
const E2E = 'e2e_';

/** Años reservados para los specs de indicadores (fuera de cualquier dato real). */
const E2E_YEAR_MIN = 2090;
const E2E_YEAR_MAX = 2099;

/**
 * Ejecuta Python DENTRO del contenedor backend y devuelve su stdout.
 * `execFileSync` evita el shell, así que no hace falta `MSYS_NO_PATHCONV=1`
 * (no hay ninguna ruta que MSYS pueda reescribir) ni comillas.
 * @param {string} src
 * @returns {string}
 */
function runPy(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', src], {
    stdio: ['ignore', 'pipe', 'inherit'],
    encoding: 'utf8',
    timeout: 120_000,
  });
}

/**
 * Ejecuta SQL en la BD real y devuelve las filas como array de arrays.
 * Para asertar estado que la UI no enseña literalmente (p. ej. el status
 * canónico de una incidencia: 'Cerrada', no 'Completado').
 * @param {string} sql  una sola sentencia SELECT
 * @returns {any[][]}
 */
function dbRows(sql) {
  const src = [
    'import json',
    'from itcj2.database import SessionLocal',
    'from sqlalchemy import text',
    'db = SessionLocal()',
    'try:',
    `    rows = db.execute(text(${JSON.stringify(sql)})).fetchall()`,
    '    print(json.dumps([[str(c) if c is not None else None for c in r] for r in rows]))',
    'finally:',
    '    db.close()',
  ].join('\n');
  return JSON.parse(runPy(src).trim() || '[]');
}

/**
 * Borra TODO lo que la suite pudo crear. Idempotente: se puede llamar en
 * `beforeAll` (para limpiar restos de una corrida abortada) y en `afterAll`.
 *
 * El orden importa:
 *   1. Las tareas antes que sus padres y que los pasos de flujo
 *      (`adhoc_tasks.flow_step_id` no tiene `ondelete`).
 *   2. Soltar `current_step_id`/`flow_id` de los documentos e2e antes de
 *      borrar el flujo (misma razón).
 *   3. Los años de indicadores arrastran indicadores y trackings por cascada.
 * Los assignees/comentarios/aprobaciones de tarea sí son `ondelete CASCADE`.
 */
function cleanupAdhoc() {
  const stmts = [
    // -- tareas de padres e2e (documentos, incidencias, eventos) y sueltas --
    `DELETE FROM adhoc_tasks t USING adhoc_documents d
       WHERE t.document_id = d.id AND d.title LIKE '${E2E}%'`,
    `DELETE FROM adhoc_tasks t USING adhoc_incidents i
       WHERE t.incident_id = i.id AND i.title LIKE '${E2E}%'`,
    `DELETE FROM adhoc_tasks t USING adhoc_program_events p
       WHERE t.program_id = p.id AND p.title LIKE '${E2E}%'`,
    `DELETE FROM adhoc_tasks WHERE description LIKE '%${E2E}%'`,
    // -- documentos: soltar las FK RESTRICT antes de tocar el flujo --
    `UPDATE adhoc_documents SET current_step_id = NULL, flow_id = NULL
       WHERE title LIKE '${E2E}%'`,
    `DELETE FROM adhoc_documents WHERE title LIKE '${E2E}%'`,
    // -- incidencias y eventos de programa --
    `DELETE FROM adhoc_incidents WHERE title LIKE '${E2E}%'`,
    `DELETE FROM adhoc_program_events WHERE title LIKE '${E2E}%'`,
    // -- flujos e2e (pasos y validadores caen por cascada) --
    `DELETE FROM adhoc_approval_flows WHERE name LIKE '${E2E}%'`,
    // -- indicadores: el año arrastra indicadores y trackings --
    `DELETE FROM adhoc_indicator_years
       WHERE year BETWEEN ${E2E_YEAR_MIN} AND ${E2E_YEAR_MAX}`,
    // -- catálogos de solo-nombre + áreas y procesos --
    `DELETE FROM adhoc_document_categories WHERE name LIKE '${E2E}%'`,
    `DELETE FROM adhoc_document_classifications WHERE name LIKE '${E2E}%'`,
    `DELETE FROM adhoc_incident_categories WHERE name LIKE '${E2E}%'`,
    `DELETE FROM adhoc_program_categories WHERE name LIKE '${E2E}%'`,
    `DELETE FROM adhoc_processes WHERE name LIKE '${E2E}%'`,
    `DELETE FROM adhoc_areas WHERE name LIKE '${E2E}%'`,
  ];

  const src = [
    'from itcj2.database import SessionLocal',
    'from sqlalchemy import text',
    'db = SessionLocal()',
    'try:',
    `    for s in ${JSON.stringify(stmts)}:`,
    '        db.execute(text(s))',
    '    db.commit()',
    'finally:',
    '    db.close()',
  ].join('\n');
  runPy(src);
}

/**
 * Carga una página de adhoc (navegación completa) y espera el shell.
 * Instala `window.__booted` para que los tests de navegación boosted detecten
 * un full reload (que borraría el marcador).
 * @param {import('@playwright/test').Page} page
 * @param {string} urlPath
 */
async function gotoAdhoc(page, urlPath) {
  await page.goto(urlPath, { waitUntil: 'domcontentloaded' });
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  await page.evaluate(() => {
    /** @type {any} */ (window).__booted = true;
  });
}

/**
 * Igual que `gotoAdhoc` pero AUTENTICADO COMO otro usuario: mintea un JWT con
 * `role:''` (sin bypass de admin global) para el id dado y pisa la cookie del
 * storageState en este contexto.
 * @param {import('@playwright/test').Page} page
 * @param {number|string} userId
 * @param {string} urlPath
 */
async function gotoAdhocAs(page, userId, urlPath) {
  await loginAs(page, userId);
  await gotoAdhoc(page, urlPath);
}

/**
 * Pisa la cookie `itcj_token` del contexto por la de otro usuario, SIN navegar.
 * Útil cuando lo que se prueba es una llamada de API (`page.request` comparte
 * el almacén de cookies del contexto).
 * @param {import('@playwright/test').Page} page
 * @param {number|string} userId
 */
async function loginAs(page, userId) {
  const token = mintTokenFor(userId);
  await page.context().addCookies([
    {
      name: 'itcj_token',
      value: token,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
    },
  ]);
}

/**
 * Id del usuario con el que corre el storageState del global-setup.
 *
 * Se LEE DEL PROPIO TOKEN (claim `sub`), no se re-deriva con una query: el
 * criterio de selección del global-setup (primer usuario activo con
 * `helpdesk.dashboard.admin` **y** rol de BD `admin` en `itcj`) no coincide con
 * "el primer admin de adhoc por id", y cualquier spec que asigne tareas a un
 * usuario distinto del de la cookie vería un tablero vacío. Solo se decodifica
 * el payload (no se verifica la firma): el secreto nunca sale del contenedor.
 */
function adminUserId() {
  const state = JSON.parse(require('fs').readFileSync(STORAGE_STATE, 'utf8'));
  const cookie = (state.cookies || []).find((c) => c.name === 'itcj_token');
  if (!cookie) throw new Error(`No hay cookie itcj_token en ${STORAGE_STATE}`);
  const payload = JSON.parse(
    Buffer.from(cookie.value.split('.')[1], 'base64').toString('utf8')
  );
  const uid = parseInt(payload.sub, 10);
  if (!uid) throw new Error('El token del storageState no trae un `sub` usable');
  return uid;
}

/**
 * Otro usuario activo con acceso a adhoc, distinto de `excludeId`. Sirve para
 * probar el 403 de "no asignado" con un actor que SÍ tiene el permiso
 * `adhoc.tasks.api.workflow` (si no lo tuviera, el 403 vendría de
 * `require_perms` y no probaría nada).
 * @param {number} excludeId
 */
function otherAdhocUserId(excludeId) {
  const rows = dbRows(
    "SELECT u.id FROM core_users u JOIN core_user_app_roles r ON r.user_id = u.id " +
      "JOIN core_apps a ON a.id = r.app_id JOIN core_roles ro ON ro.id = r.role_id " +
      `WHERE a.key = 'adhoc' AND ro.name = 'admin' AND u.is_active AND u.id <> ${parseInt(excludeId, 10)} ` +
      'ORDER BY u.id LIMIT 1'
  );
  if (!rows.length) throw new Error('Hace falta un segundo usuario con acceso a adhoc');
  return parseInt(rows[0][0], 10);
}

/**
 * Envuelve `page.request` con la base de la API de adhoc y lanza si la
 * respuesta no es la esperada, con el cuerpo en el mensaje (los errores de la
 * app llegan como `{"error": "texto", "status": N}`).
 * @param {import('@playwright/test').Page} page
 */
function api(page) {
  const BASE = '/api/adhoc/v2';
  async function call(method, path, options, expected) {
    const res = await page.request.fetch(BASE + path, { method, ...(options || {}) });
    const body = await res.text();
    if (expected && !expected.includes(res.status())) {
      throw new Error(`${method} ${path} -> ${res.status()} (esperado ${expected}): ${body}`);
    }
    let json = null;
    try {
      json = JSON.parse(body);
    } catch (_) {
      /* respuesta no-JSON: el caller mira `status` */
    }
    return { status: res.status(), body: json, text: body };
  }
  return {
    get: (p, expected = [200]) => call('GET', p, {}, expected),
    post: (p, data, expected = [200, 201]) => call('POST', p, { data }, expected),
    postForm: (p, form, expected = [200, 201]) => call('POST', p, { multipart: form }, expected),
    put: (p, data, expected = [200]) => call('PUT', p, { data }, expected),
    patch: (p, data, expected = [200]) => call('PATCH', p, { data }, expected),
    del: (p, expected = [200]) => call('DELETE', p, {}, expected),
    raw: call,
  };
}

/**
 * Contexto de API independiente de cualquier `page`, con la cookie de admin del
 * `global-setup`. Sirve para montar fixtures en `beforeAll` (donde el fixture
 * `request` de Playwright, que es test-scoped, no está disponible) sin abrir un
 * navegador. Hay que cerrarlo con `.dispose()`.
 */
async function newApiContext() {
  const ctx = await pwRequest.newContext({ baseURL: BASE_URL, storageState: STORAGE_STATE });
  const BASE = '/api/adhoc/v2';
  async function call(method, p, options, expected) {
    const res = await ctx.fetch(BASE + p, { method, ...(options || {}) });
    const body = await res.text();
    if (expected && !expected.includes(res.status())) {
      throw new Error(`${method} ${p} -> ${res.status()} (esperado ${expected}): ${body}`);
    }
    let json = null;
    try {
      json = JSON.parse(body);
    } catch (_) {
      /* no-JSON */
    }
    return { status: res.status(), body: json, text: body };
  }
  return {
    get: (p, expected = [200]) => call('GET', p, {}, expected),
    post: (p, data, expected = [200, 201]) => call('POST', p, { data }, expected),
    postForm: (p, form, expected = [200, 201]) => call('POST', p, { multipart: form }, expected),
    put: (p, data, expected = [200]) => call('PUT', p, { data }, expected),
    patch: (p, data, expected = [200]) => call('PATCH', p, { data }, expected),
    del: (p, expected = [200]) => call('DELETE', p, {}, expected),
    page: (p) => ctx.get(p, { maxRedirects: 0 }),
    dispose: () => ctx.dispose(),
  };
}

/**
 * Instala un espía sobre `window.confirm` / `alert` / `prompt` ANTES de que
 * cargue ningún script de la página. Los diálogos nativos están PROHIBIDOS en
 * la app (plan §6.3: el legacy tenía 14). Devuelve un lector del contador.
 * @param {import('@playwright/test').Page} page
 */
async function trapNativeDialogs(page) {
  await page.addInitScript(() => {
    /** @type {any} */ (window).__nativeDialogs = [];
    for (const name of ['confirm', 'alert', 'prompt']) {
      // @ts-ignore
      const original = window[name];
      // @ts-ignore
      window[name] = function (...args) {
        /** @type {any} */ (window).__nativeDialogs.push({ name, args });
        // No se delega en el original: bloquearía el runner.
        return name === 'confirm' ? true : undefined;
      };
      void original;
    }
  });
  // Red de seguridad: si algo abriera un diálogo real, Playwright lo
  // auto-descarta, pero lo registramos para que el test pueda fallar.
  page.on('dialog', (d) => {
    // @ts-ignore
    page.__sawRealDialog = true;
    d.dismiss().catch(() => {});
  });
  return async () => page.evaluate(() => /** @type {any} */ (window).__nativeDialogs || []);
}

module.exports = {
  ADHOC_SHELL,
  E2E,
  E2E_YEAR_MIN,
  E2E_YEAR_MAX,
  gotoAdhoc,
  gotoAdhocAs,
  loginAs,
  mintTokenFor,
  runPy,
  dbRows,
  cleanupAdhoc,
  adminUserId,
  otherAdhocUserId,
  api,
  newApiContext,
  trapNativeDialogs,
};

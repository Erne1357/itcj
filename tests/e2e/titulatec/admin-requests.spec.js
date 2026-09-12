// @ts-check
/**
 * Bandeja de solicitudes — criterio 10 del spec, completo.
 *
 * LA BANDEJA SE ALCANZA DESDE EL MENÚ, no tecleando la URL. Es deliberado: la
 * fila de `_ADMIN_NAV` (`pages/nav.py:95-103`) es lo único que hace la página
 * descubrible, `admin_nav_items` filtra con `perms & need` (que es OR), y un
 * código inexistente ahí NO da 403 — esconde la pestaña para siempre, en
 * silencio. Tecleando la URL, esa clase de fallo pasaría desapercibida.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState: undefined`
 * (RULING R1 / ver el encabezado de `_helpers.js`): en Playwright 1.61 un
 * `undefined` es un no-op (`node_modules/playwright/lib/index.js:324-325`:
 * `if (storageState !== void 0) options.storageState = storageState;`), así
 * que el contexto de esta suite heredaría el storageState global del proyecto
 * — un admin de HELPDESK — en vez de quedar sin sesión. `require_page_app` no
 * tiene bypass de admin global (`itcj2/dependencies.py:104-139`): ese usuario
 * recibiría `PageForbidden` en cualquier página de titulatec de todas formas,
 * pero la declaración correcta es la de esta línea, no la del brief.
 */
const { test, expect } = require('@playwright/test');
const {
  seedScenario, cleanupScenario, stateFor, seedPendingRequest, processFolioFor,
} = require('./_helpers');

let ctx;
let reqId;

test.beforeAll(() => {
  ctx = seedScenario();
  reqId = seedPendingRequest(ctx);
});
test.afterAll(() => { cleanupScenario(ctx); });

// El storageState global es un admin de HELPDESK y require_page_app no tiene
// bypass de admin global: recibiría PageForbidden en toda página de titulatec.
test.use({ storageState: { cookies: [], origins: [] } });

test('las dos filas nuevas del menú admin existen y llevan a su bandeja', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  await page.goto('/titulatec/admin/processes', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#ttSide')).toBeVisible();

  const solicitudes = page.locator('#ttSide a[hx-get="/titulatec/admin/solicitudes"]');
  const encuestas = page.locator('#ttSide a[hx-get="/titulatec/admin/encuestas"]');
  await expect(solicitudes, 'falta la fila "Solicitudes" en _ADMIN_NAV').toBeVisible();
  await expect(encuestas, 'falta la fila "Encuestas" en _ADMIN_NAV').toBeVisible();

  await solicitudes.click();
  // hx-push-url="true" en cada item del menú (base_admin.html:54).
  await page.waitForURL('**/titulatec/admin/solicitudes');
  // La fila se localiza por SU formulario de aprobación: la bandeja de la Tarea
  // 22 lo pinta siempre visible y no hay control de despliegue que abrir.
  await expect(
    page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqId}/aprobar"]`)
  ).toBeVisible();

  await c.close();
});

test('aprobar capturando el NIP crea el proceso y lo muestra en la bandeja', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  await page.goto('/titulatec/admin/processes', { waitUntil: 'domcontentloaded' });
  await page.locator('#ttSide a[hx-get="/titulatec/admin/solicitudes"]').click();
  await page.waitForURL('**/titulatec/admin/solicitudes');

  const form = page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqId}/aprobar"]`);
  await expect(form).toBeVisible();

  // El NIP es obligatorio y de 4 dígitos (D15).
  await form.locator('[name="nip"]').fill('7788');
  await form.locator('[name="program_id"]').selectOption(String(ctx.programId));

  const post = page.waitForResponse(
    (r) => r.request().method() === 'POST'
        && new URL(r.url()).pathname === `/titulatec/admin/solicitudes/${reqId}/aprobar`
  );
  await form.getByRole('button', { name: 'Aprobar' }).click();
  expect((await post).status()).toBe(200);

  // El folio se lee de la BASE, no de una copia inventada aquí: así la
  // aserción de pantalla no depende de la redacción de la bandeja.
  const folio = processFolioFor(ctx, '29990777');
  expect(folio, 'la aprobación no creó el proceso').toMatch(/^TT-/);
  await expect(page.getByText(folio)).toBeVisible();

  await c.close();
});

test('el NIP nunca viaja de vuelta al navegador', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  await page.goto('/titulatec/admin/solicitudes', { waitUntil: 'domcontentloaded' });
  const html = await page.content();
  expect(html, 'el NIP capturado no puede quedar renderizado en la bandeja')
    .not.toContain('7788');

  await c.close();
});

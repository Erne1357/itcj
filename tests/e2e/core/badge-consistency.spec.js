// @ts-check
/**
 * Task 5 (F7) — barrido C8: badge de app idéntico en apps tab, permissions
 * header y profile tile; y propagación del color editado vía UI a la
 * users list. Cierra los residuales que F3 no cubrió (permissions.html
 * subtitle, tasks.js catálogo, email.html icono).
 *
 * ─── POR QUÉ EL COLOR CANÓNICO SE GUARDA EN UN HOOK ────────────────────────
 * El segundo caso EDITA el color de helpdesk en la BD de desarrollo, que es
 * compartida. Antes leía el color al empezar el test y lo restauraba en un
 * `finally` del propio test, y esa combinación tiene un fallo desagradable:
 * cuando Playwright agota el timeout del test, ABORTA el cuerpo, así que el
 * `finally` no llega a correr y la BD se queda con el violeta de prueba. La
 * siguiente corrida leía ESE violeta como "canónico" y lo restauraba tal cual:
 * un timeout —un pico de carga, nada más— dejaba el color mal para siempre y
 * sin avisar.
 *
 * Ahora el valor se lee en `beforeAll` y se restaura en `afterAll`. Los hooks
 * de Playwright SÍ corren después de un test que agota su tiempo, así que el
 * peor caso pasa de "la BD queda mutada" a "un caso rojo".
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function hexToRgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function py(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8',
    timeout: 60_000,
  }).trim();
}

function helpdeskColor() {
  return py(
    [
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.app import App',
      'db = SessionLocal()',
      "a = db.query(App).filter_by(key='helpdesk').first()",
      "print(a.color or '#6c757d')",
      'db.close()',
    ].join('\n')
  );
}

function fijarHelpdeskColor(hex) {
  py(
    [
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.app import App',
      'from itcj2.core.services.app_style_cache import invalidate_app_styles',
      'db = SessionLocal()',
      "a = db.query(App).filter_by(key='helpdesk').first()",
      `a.color = '${hex}' if a else None`,
      'db.commit(); db.close(); invalidate_app_styles()',
    ].join('\n')
  );
}

test.describe('C8: identical app badge across config tabs (F7)', () => {
  /** El color canónico de la BD, leído UNA vez antes de tocar nada. */
  let CANONICO = '';

  test.beforeAll(() => {
    CANONICO = helpdeskColor();
    expect(CANONICO, 'helpdesk no tiene fila en core_apps').toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  test.afterAll(() => {
    // Corre incluso si un caso agotó su tiempo: la BD compartida nunca se queda
    // con el color de prueba.
    if (CANONICO) fijarHelpdeskColor(CANONICO);
  });

  test('apps tab, permissions header and profile share the same computed color', async ({ page }) => {
    const expected = hexToRgb(CANONICO);

    // 1) apps tab
    await gotoCore(page, '/itcj/config/apps');
    const appsBadge = page
      .locator('.app-badge[data-app-key="helpdesk"], tr[data-app-key="helpdesk"] .app-badge')
      .first();
    await expect(appsBadge).toBeVisible();
    expect(await appsBadge.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(expected);

    // 2) permissions header (child view of apps)
    await gotoCore(page, '/itcj/config/apps/helpdesk/permissions');
    const headerBadge = page.locator('.app-badge').first();
    await expect(headerBadge).toBeVisible();
    expect(await headerBadge.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(expected);

    // 3) profile tile (Task 2 markup)
    await page.goto('/itcj/profile', { waitUntil: 'domcontentloaded' });
    await page.click('#permissions-tab');
    const tile = page.locator('#permissions .app-icon[data-app-key="helpdesk"]');
    await expect(tile).toBeVisible();
    expect(await tile.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(expected);
  });

  test('editar el color de una app VÍA UI propaga al badge de la users list (spec §4(5))', async ({ page }) => {
    const NEW_COLOR = '#7b2ff7';
    const NEW_RGB = hexToRgb(NEW_COLOR);

    // 1) editar el color de helpdesk VÍA UI en el apps tab (flujo edit→propaga)
    await gotoCore(page, '/itcj/config/apps');
    await page.locator('tr[data-app-key="helpdesk"] .edit-app-btn').click();
    await expect(page.locator('#editAppModal')).toBeVisible();
    await page.locator('#editAppColor').fill(NEW_COLOR);

    // Timeout explícito y mensaje con el status: un `ok()` pelado convierte un
    // 4xx en "esperaba true, recibí false" y deja adivinando.
    const patchResp = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/authz/apps/helpdesk') && r.request().method() === 'PATCH',
      { timeout: 15_000 }
    );
    await page.locator('#editAppForm button[type="submit"]').click();
    const resp = await patchResp;
    expect(resp.status(), `PATCH del color respondió ${resp.status()}`).toBeLessThan(400);
    await expect(page.locator('#editAppModal')).toBeHidden();

    // la fila del apps tab refleja el color nuevo sin reload (re-render de apps.js)
    const appsBadge = page.locator('tr[data-app-key="helpdesk"] .app-badge').first();
    await expect
      .poll(() => appsBadge.evaluate((el) => getComputedStyle(el).backgroundColor), { timeout: 10_000 })
      .toBe(NEW_RGB);

    // 2) el color propaga a la users list (badge C8, misma columna App.color)
    // Filtrar por app=helpdesk: garantiza >=1 fila con el badge visible
    // (el listado sin filtro pagina y puede no traer ningún usuario helpdesk en la página 1).
    await gotoCore(page, '/itcj/config/users');
    const filterResp = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/users?') && r.url().includes('app=helpdesk'),
      { timeout: 15_000 }
    );
    await page.selectOption('#appFilter', 'helpdesk');
    await filterResp;
    const usersBadge = page.locator('.app-badge[data-app-key="helpdesk"]').first();
    await expect(
      usersBadge,
      'la lista filtrada por helpdesk no trajo ninguna fila con badge'
    ).toBeVisible();
    expect(await usersBadge.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(NEW_RGB);
  });
});

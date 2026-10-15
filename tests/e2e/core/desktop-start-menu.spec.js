// @ts-check
/**
 * Menú inicio + buscador del escritorio (/itcj/dashboard) — Task 4.
 * Captura: `E2E_CAPTURE=1 npx playwright test core/desktop-start-menu.spec.js`
 * escribe desktop-start-menu.png en .playwright-mcp/images/core/.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SHOTS = path.join(__dirname, '..', '..', '..', '.playwright-mcp', 'images', 'core');
const CAPTURE = !!process.env.E2E_CAPTURE;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* iframe sin storage */ }
  });
});

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

const windowOf = (page, key) => page.locator(`.app-window[data-app-id="${key}"]`);

test('clic en el botón de inicio abre y cierra el menú; aria-expanded sincronizado', async ({ page }) => {
  await gotoDesktop(page);
  const btn = page.locator('.start-button');
  await expect(page.locator('#startMenu')).toBeHidden();
  await btn.click();
  await expect(page.locator('#startMenu')).toBeVisible();
  await expect(btn).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#startMenuApps .start-app')).toHaveCount(5);
  await expect(page.locator('#startMenuUser')).toContainText(/\S/);
  await btn.click();
  await expect(page.locator('#startMenu')).toBeHidden();
  await expect(btn).toHaveAttribute('aria-expanded', 'false');
});

test('la tarjeta de usuario abre la ventana de perfil con un clic', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuUser').click();
  await expect(windowOf(page, 'profile')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('una app de la cuadrícula abre su ventana y cierra el menú', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuApps .start-app[data-app="directory"]').click();
  await expect(windowOf(page, 'directory')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('configuración abre la ventana settings', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuSettings').click();
  await expect(windowOf(page, 'settings')).toBeVisible();
});

test('buscador: "titu" da un resultado y Enter abre TitulaTec; sin acentos', async ({ page }) => {
  await gotoDesktop(page);
  const search = page.locator('#taskbarSearch');
  await expect(search).toHaveAttribute('placeholder', 'Buscar aplicaciones…');
  await search.click();
  await search.fill('titu');
  await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
  await expect(page.locator('#startMenuResults [role="option"]')).toContainText('TitulaTec');
  await search.press('Enter');
  await expect(windowOf(page, 'titulatec')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();

  // "Configuración" se encuentra aunque se escriba con mayúsculas y sin acento.
  await search.click();
  await search.fill('CONFIGURACION');
  await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
  await search.fill('zzzz');
  await expect(page.locator('#startMenuEmpty')).toBeVisible();
});

test('buscador: flechas mueven la selección y Esc cierra', async ({ page }) => {
  await gotoDesktop(page);
  const search = page.locator('#taskbarSearch');
  await search.click();
  await search.fill('e'); // varias coincidencias
  const opts = page.locator('#startMenuResults [role="option"]');
  expect(await opts.count()).toBeGreaterThan(1);
  await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');
  await search.press('ArrowDown');
  await expect(opts.nth(1)).toHaveAttribute('aria-selected', 'true');
  await search.press('ArrowUp');
  await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');
  await search.press('Escape');
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('Ctrl+K enfoca el buscador y abre el modo búsqueda; clic fuera cierra', async ({ page }) => {
  await gotoDesktop(page);
  await page.keyboard.press('Control+k');
  await expect(page.locator('#taskbarSearch')).toBeFocused();
  await expect(page.locator('#startMenu')).toBeVisible();
  await expect(page.locator('#startMenuSearch')).toBeVisible();
  await page.mouse.click(300, 200);
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('cerrar sesión: POST al logout, limpia sesión y va a /itcj/login', async ({ page }) => {
  let called = 0;
  // No invalidar el JWT compartido de la suite.
  await page.route('**/api/core/v2/auth/logout', (route) => {
    called += 1;
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
  });
  // La cookie sigue viva (logout simulado) y el /itcj/login real redirigiría de vuelta al
  // escritorio: se sirve una página vacía del mismo origen para poder leer su sessionStorage.
  await page.route(/\/itcj\/login(\?|$)/, (route) => {
    if (!route.request().isNavigationRequest()) return route.continue();
    return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>login</title>' });
  });
  await gotoDesktop(page);

  // Con una ventana abierta la sesión del escritorio queda guardada.
  const sessionKey = 'itcj.desktop.session.v1:' + await page.evaluate(() => window.ItcjDesktop.user.id);
  await page.evaluate(() => window.ItcjDesktop.wm.open('directory'));
  await expect(windowOf(page, 'directory')).toBeVisible();
  await page.waitForFunction((k) => !!sessionStorage.getItem(k), sessionKey);

  await page.locator('.start-button').click();
  await Promise.all([
    page.waitForRequest((r) => r.isNavigationRequest() && new URL(r.url()).pathname === '/itcj/login'),
    page.locator('#startMenuLogout').click(),
  ]);
  expect(called).toBe(1);
  await page.waitForURL(/\/itcj\/login$/);
  expect(await page.evaluate((k) => sessionStorage.getItem(k), sessionKey)).toBeNull();
});

test('captura del menú abierto', async ({ page }) => {
  test.skip(!CAPTURE, 'solo con E2E_CAPTURE=1');
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await expect(page.locator('#startMenu')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, 'desktop-start-menu.png') });
});

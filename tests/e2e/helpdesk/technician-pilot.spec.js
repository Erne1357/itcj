// @ts-check
// Migración del dashboard de técnico: las 4 listas (asignados/en progreso/equipo/
// historial) pasan a fragmentos server-side (un endpoint ?tab=). Role-gated → se
// autentica como un técnico real. Los modales de acción leen data-* del botón.
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/technician/dashboard';
const TECH_USER_ID = 8275; // usuario con rol tech_soporte

test.describe('migración — technician dashboard (4 listas server-side + HTMX)', () => {
  test('render server-side: la pestaña "En Espera" usa #hd-tab-queue + macros', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);

    const queue = page.locator('#hd-tab-queue');
    await expect(queue).toBeVisible();
    const cards = queue.locator('.hd-ticket-card');
    if (await cards.count() > 0) {
      await expect(cards.first()).toBeVisible();
    } else {
      await expect(queue.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('historial: filtro por HTMX recarga #hd-tab-history sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);
    await page.click('#history-tab');
    await expect(page.locator('#hd-tab-history')).toBeVisible();

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes('tab=resolved') && r.request().method() === 'GET'
    );
    await page.selectOption('#historyFilter', 'all');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
    expect(await resp.text()).not.toContain('<html');
  });

  test('petición HTMX (HX-Request) a ?tab=assigned devuelve fragmento, no la página', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);

    const frag = await page.request.get(PAGE + '?tab=assigned', { headers: { 'HX-Request': 'true' }, maxRedirects: 0 });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-ticket-card') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PAGE, { maxRedirects: 0 });
    expect(await full.text()).toContain('<html');
  });
});

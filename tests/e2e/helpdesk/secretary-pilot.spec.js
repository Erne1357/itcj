// @ts-check
// Migración del dashboard de secretaría: la lista de tickets del depto pasa a
// componentes server-side + HTMX. La página es role-gated (requiere depto) → se
// autentica como un usuario secretaría real (no el admin del storageState).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/secretary/';
const SECRETARY_USER_ID = 7689; // usuario con rol secretaría + departamento

test.describe('migración — secretary dashboard (lista server-side + HTMX)', () => {
  test('render server-side: la pestaña Tickets usa #hd-tickets-results + macros', async ({ page }) => {
    await gotoHelpdeskAs(page, SECRETARY_USER_ID, PAGE);

    const results = page.locator('#hd-tickets-results');
    await expect(results).toBeVisible();
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PAGE);

    const cards = results.locator('.hd-ticket-card');
    if (await cards.count() > 0) {
      await expect(cards.first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('filtro HTMX: cambiar estado dispara hx-get a la misma URL, push-url, sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, SECRETARY_USER_ID, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes('/help-desk/secretary') && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'CLOSED');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('CLOSED');
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
    expect(await resp.text()).not.toContain('<html');
  });

  test('petición HTMX (HX-Request) devuelve fragmento; sin header, la página', async ({ page }) => {
    await gotoHelpdeskAs(page, SECRETARY_USER_ID, PAGE);

    const frag = await page.request.get(PAGE, { headers: { 'HX-Request': 'true' }, maxRedirects: 0 });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-ticket-card') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PAGE, { maxRedirects: 0 });
    expect(await full.text()).toContain('<html');
  });
});

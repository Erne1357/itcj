// @ts-check
// Migración de user/my-tickets al patrón de componentes server-side + HTMX
// (réplica del piloto admin/tickets-list). Valida render server-side con macros,
// filtro por HTMX (misma URL, push-url, sin full reload) y fragmento por HX-Request.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/user/my-tickets';

test.describe('migración — my-tickets (componentes server-side + HTMX)', () => {
  test('render server-side: usa .hd-ticket-card / .hd-empty-state (no el viejo render JS)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const results = page.locator('#hd-tickets-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta a la MISMA url de la página por HTMX.
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PAGE);

    const cards = results.locator('.hd-ticket-card');
    const cardCount = await cards.count();
    if (cardCount > 0) {
      await expect(cards.first()).toBeVisible();
      await expect(results.locator('.badge').first()).toBeVisible();
      // La clase legacy divergente NO debe usarse en el render nuevo.
      await expect(results.locator('.ticket-card:not(.hd-ticket-card)')).toHaveCount(0);
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('filtro HTMX: cambiar estado dispara hx-get a la misma URL, empuja URL, sin full reload', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'CLOSED');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('CLOSED');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('petición HTMX (header HX-Request) a la misma URL devuelve fragmento, no la página', async ({ request }) => {
    const frag = await request.get(PAGE + '?status=PENDING', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-ticket-card') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await request.get(PAGE, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });

  test('Alpine.js está cargado (reactividad de cliente disponible)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await expect.poll(() => page.evaluate(() => typeof window.Alpine !== 'undefined')).toBe(true);
  });
});

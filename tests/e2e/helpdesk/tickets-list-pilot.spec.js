// @ts-check
// Piloto de arquitectura de componentes server-side + HTMX sobre admin/tickets-list.
// Valida: render server-side con macros (.hd-ticket-card/.hd-badge/.hd-empty-state),
// filtro por HTMX (hx-get al partial, push-url, sin full reload) y fragmento puro.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

// NB: no usar el nombre `URL` (sombrearía el constructor global URL en Node).
const PAGE = '/help-desk/admin/tickets-list';
// Misma URL sirve página o fragmento (según header HX-Request, patrón canónico).
const PARTIAL = '/help-desk/admin/tickets-list';

test.describe('pilot — tickets-list (componentes server-side + HTMX)', () => {
  test('render server-side: usa .hd-ticket-card / .hd-empty-state (no el viejo render JS)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const results = page.locator('#hd-tickets-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta al endpoint partial por HTMX.
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PARTIAL);

    // Contenido renderizado por el server: tarjetas nuevas o empty-state nuevo.
    const cards = results.locator('.hd-ticket-card');
    const cardCount = await cards.count();
    if (cardCount > 0) {
      await expect(cards.first()).toBeVisible();
      // Badge unificado presente (Bootstrap sólido, mismo estilo que toda la app).
      await expect(results.locator('.badge').first()).toBeVisible();
      // La clase legacy divergente NO debe usarse en el render nuevo.
      await expect(results.locator('.ticket-card.status-PENDING, .badge-priority-ALTA')).toHaveCount(0);
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('filtro HTMX: cambiar estado dispara hx-get al partial, empuja URL, sin full reload', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PARTIAL) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'CLOSED');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('CLOSED');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo / sin base).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('petición HTMX (header HX-Request) a la misma URL devuelve fragmento, no la página', async ({ request }) => {
    // Con HX-Request → fragmento.
    const frag = await request.get(PARTIAL + '?status=PENDING', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-ticket-card') || fragBody.includes('hd-empty-state')).toBeTruthy();

    // Sin el header → página completa (documento).
    const full = await request.get(PARTIAL, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });
});

// @ts-check
// Migración de admin/documents a componentes server-side + HTMX + Alpine bulk-select.
// Valida: render server-side de filas con badges de macro, filtro HTMX (misma URL),
// fragmento por HX-Request, y selección masiva reactiva con Alpine (count + botón).
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/documents';

test.describe('migración — documents (server-side + HTMX + Alpine bulk-select)', () => {
  test('render server-side: lista con filas + badges de macro (no el getStatusBadge divergente)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const results = page.locator('#hd-tickets-results');
    await expect(results).toBeVisible();
    await expect(page.locator('#hd-docs-filter-form')).toHaveAttribute('hx-get', PAGE);

    const rows = results.locator('.hd-doc-row');
    const count = await rows.count();
    if (count > 0) {
      await expect(rows.first()).toBeVisible();
      await expect(rows.first().locator('.badge').first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('filtro HTMX: cambiar estado dispara hx-get a la misma URL, sin full reload', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'CLOSED');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('CLOSED');
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    const body = await resp.text();
    expect(body).not.toContain('<html');
  });

  test('petición HTMX (HX-Request) a la misma URL devuelve fragmento, no la página', async ({ request }) => {
    const frag = await request.get(PAGE, { headers: { 'HX-Request': 'true' }, maxRedirects: 0 });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-doc-row') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await request.get(PAGE, { maxRedirects: 0 });
    expect(await full.text()).toContain('<html');
  });

  test('Alpine bulk-select: marcar checkbox habilita "Generar" y actualiza el contador', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);

    const firstCb = page.locator('.hd-doc-cb').first();
    const cbCount = await page.locator('.hd-doc-cb').count();
    test.skip(cbCount === 0, 'No hay tickets de Soporte para ejercitar la selección');

    // Estado inicial: botón Generar deshabilitado.
    await expect(page.locator('#btnGenerate')).toBeDisabled();

    await firstCb.check();
    // Reactividad Alpine: el botón se habilita y el contador refleja la selección.
    await expect(page.locator('#btnGenerate')).toBeEnabled();
    await expect(page.locator('#selectionCount')).toContainText('seleccionado');

    await firstCb.uncheck();
    await expect(page.locator('#btnGenerate')).toBeDisabled();
  });
});

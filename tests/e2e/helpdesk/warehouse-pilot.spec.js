// @ts-check
// Migración de warehouse (products/entries/movements) a componentes server-side
// + HTMX. Valida CONTRATOS ESTRUCTURALES (no datos concretos de BD):
//   · contenedor server-side #hd-<view>-results,
//   · el form de filtros lleva hx-get (misma URL) + hx-target + hx-push-url,
//   · HX-Request (sin boost) devuelve un FRAGMENTO (sin <html>),
//   · un filtro dispara hx-get a la misma URL, empuja la URL y NO recarga,
//   · un modal BS5 (Nuevo Producto) abre/cierra sin jQuery.
// Se autentica con el storageState admin por defecto (role=admin → bypass del
// require_warehouse_page), igual que el smoke.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const VIEWS = [
  { name: 'products', path: '/help-desk/warehouse/products', results: '#hd-products-results' },
  { name: 'entries', path: '/help-desk/warehouse/entries', results: '#hd-entries-results' },
  { name: 'movements', path: '/help-desk/warehouse/movements', results: '#hd-movements-results' },
];

test.describe('pilot — warehouse (componentes server-side + HTMX)', () => {
  for (const v of VIEWS) {
    test(`${v.name}: contenedor server-side + form de filtros HTMX`, async ({ page }) => {
      await gotoHelpdesk(page, v.path);

      const results = page.locator(v.results);
      await expect(results).toBeVisible();

      // El form de filtros apunta a la MISMA URL por HTMX y reemplaza el contenedor.
      const form = page.locator('#hd-filter-form');
      await expect(form).toHaveAttribute('hx-get', v.path);
      await expect(form).toHaveAttribute('hx-target', v.results);
      await expect(form).toHaveAttribute('hx-push-url', 'true');

      // El contenido es render server-side: tabla o estado vacío por macro (NO spinner).
      const hasTable = await results.locator('table').count();
      const hasEmpty = await results.locator('.hd-empty-state').count();
      expect(hasTable + hasEmpty).toBeGreaterThan(0);
    });

    test(`${v.name}: HX-Request (no boost) devuelve fragmento; sin header, página completa`, async ({ page }) => {
      await gotoHelpdesk(page, v.path);

      const frag = await page.request.get(v.path, {
        headers: { 'HX-Request': 'true' },
        maxRedirects: 0,
      });
      expect(frag.status()).toBe(200);
      const fragBody = await frag.text();
      expect(fragBody).not.toContain('<html');
      expect(fragBody).not.toContain('base_helpdesk');

      const full = await page.request.get(v.path, { maxRedirects: 0 });
      expect(full.status()).toBe(200);
      expect(await full.text()).toContain('<html');
    });
  }

  test('products: cambiar filtro dispara hx-get a la misma URL, empuja URL, sin full reload', async ({ page }) => {
    const PATH = '/help-desk/warehouse/products';
    await gotoHelpdesk(page, PATH);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PATH) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStock', 'ok');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('stock')).toBe('ok');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo).
    const body = await resp.text();
    expect(body).not.toContain('<html');
  });

  test('movements: cambiar filtro de tipo dispara hx-get, empuja ?type, sin full reload', async ({ page }) => {
    const PATH = '/help-desk/warehouse/movements';
    await gotoHelpdesk(page, PATH);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PATH) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterType', 'ENTRY');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    await expect.poll(() => new URL(page.url()).searchParams.get('type')).toBe('ENTRY');
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
    expect(await resp.text()).not.toContain('<html');
  });

  test('modal Nuevo Producto (BS5) abre y cierra sin jQuery', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/warehouse/products');

    const modal = page.locator('#productModal');
    await expect(modal).toBeHidden();

    // Botón del encabezado (data-bs-toggle/target → bootstrap.Modal, BS5).
    await page.getByRole('button', { name: /Nuevo Producto/ }).first().click();
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    // Cierre por el botón BS5 .btn-close.
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });
});

// @ts-check
// Migración de inventory/groups a componentes server-side + HTMX (isla BS4 → BS5).
// Valida: grid server-side con macros (.hd-group-card / .hd-empty-state, NO el
// render JS viejo .group-card), filtro por HTMX (hx-get a la misma URL, push-url,
// sin full reload), fragmento puro por HX-Request, y el modal Crear (BS5) abre/cierra.
// La página es role-gated (perm helpdesk.inventory_groups.page.list) → se autentica
// como admin real (no el bypass del storageState).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/inventory/groups';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('pilot — inventory/groups (componentes server-side + HTMX, BS5)', () => {
  test('render server-side: usa .hd-group-card / .hd-empty-state (no el viejo render JS)', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const results = page.locator('#hd-groups-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta a la misma URL por HTMX.
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PAGE);

    const cards = results.locator('.hd-group-card');
    if (await cards.count() > 0) {
      await expect(cards.first()).toBeVisible();
      // Badge de Bootstrap presente (tema de la app, no paleta nueva).
      await expect(results.locator('.badge').first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
    // La clase legacy del render JS viejo NO debe usarse.
    await expect(results.locator('.group-card')).toHaveCount(0);
  });

  test('filtro HTMX: cambiar tipo dispara hx-get a la misma URL, empuja URL, sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterType', 'CLASSROOM');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('type')).toBe('CLASSROOM');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo / sin base).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('petición HTMX (HX-Request) devuelve fragmento; sin header, la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const frag = await page.request.get(PAGE + '?type=CLASSROOM', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-group-card') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PAGE, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });

  test('modal Crear Grupo (BS5) abre y cierra sin jQuery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const modal = page.locator('#groupModal');
    await expect(modal).toBeHidden();

    // Botón del encabezado (onclick openCreateGroupModal → bootstrap.Modal.show()).
    await page.getByRole('button', { name: /Crear Grupo/ }).first().click();
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    // Cierre por el botón BS5 .btn-close.
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });
});

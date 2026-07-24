// @ts-check
// Migración de inventory/campaigns a BS5 + componentes server-side (de-jQuery).
// Valida CONTRATOS estructurales (no datos concretos de BD):
//  - la lista rinde el contenedor server-side #hd-campaigns-results (tabla con
//    filas .hd-row-link, no el render JS viejo #campaigns-tbody),
//  - el form de filtros lleva hx-get + hx-target + hx-push-url,
//  - un GET con HX-Request (sin HX-Boosted) devuelve el FRAGMENTO (sin <html>),
//  - cambiar un filtro dispara hx-get a la misma URL, empuja la URL, sin recarga,
//  - los modales del detalle son BS5 (btn-close/data-bs-dismiss, 0 jQuery) y
//    abren/cierran sin jQuery.
// La página es role-gated (perm helpdesk.inventory.campaign.page.list) → se
// autentica como admin real (no el bypass del storageState).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/inventory/campaigns';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('pilot — inventory/campaigns (BS5 + componentes server-side)', () => {
  test('render server-side: contenedor #hd-campaigns-results (sin el render JS viejo)', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const results = page.locator('#hd-campaigns-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta a la misma URL por HTMX y comparte estado en la URL.
    const form = page.locator('#hd-filter-form');
    await expect(form).toHaveAttribute('hx-get', PAGE);
    await expect(form).toHaveAttribute('hx-target', '#hd-campaigns-results');
    await expect(form).toHaveAttribute('hx-push-url', 'true');
    await expect(page.locator('#filterStatus')).toBeVisible();

    // Tabla server-side con filas .hd-row-link, o estado vacío (según BD).
    const rows = results.locator('tr.hd-row-link');
    if (await rows.count() > 0) {
      await expect(rows.first()).toBeVisible();
      // Badge de estado = clase Bootstrap (tema de la app, no paleta nueva).
      await expect(results.locator('.badge').first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }

    // El render client-side viejo (tbody con id / loading row) ya NO existe.
    await expect(page.locator('#campaigns-tbody')).toHaveCount(0);
    await expect(page.locator('#loading-row')).toHaveCount(0);
    await expect(page.locator('#pagination-container')).toHaveCount(0);
  });

  test('filtro HTMX: cambiar estado dispara hx-get a la misma URL, empuja URL, sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'VALIDATED');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('VALIDATED');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo / sin base).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('petición HTMX (HX-Request) devuelve fragmento; sin header, la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const frag = await page.request.get(PAGE + '?status=VALIDATED', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-row-link') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PAGE, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });

  test('detalle: modales BS5 abren y cierran sin jQuery', async ({ page }) => {
    // El template del detalle rinde los modales siempre (independiente de los datos),
    // así que probamos su contrato BS5 con un id fijo — sin asumir filas en BD.
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE + '/1');

    // Ningún atributo BS4 en toda la página (modales migrados a BS5).
    await expect(page.locator('[data-toggle], [data-dismiss], .modal .close')).toHaveCount(0);

    const modal = page.locator('#modal-move-item');
    await expect(modal.locator('.btn-close')).toHaveCount(1);
    await expect(modal.locator('[data-bs-dismiss="modal"]')).toHaveCount(2);

    await expect(modal).toBeHidden();
    // Abre/cierra vía la API de Bootstrap 5 (sin jQuery).
    await page.evaluate(() => {
      const el = document.getElementById('modal-move-item');
      bootstrap.Modal.getOrCreateInstance(el).show();
    });
    await expect(modal).toBeVisible();
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });
});

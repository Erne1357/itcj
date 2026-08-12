// @ts-check
// Filtros nuevos (panel "Más filtros" + chips) y exportación a Excel de
// /help-desk/inventory/items. Complementa inventory-items-pilot.spec.js (que
// ya cubre el render server-side base) con: apertura del panel colapsable +
// push de params vía HTMX, un chip removible individualmente, y la descarga
// real del botón Exportar (ancla <a href>, sin blob) — usa el evento
// `download` de Playwright. Páginas role-gated → se autentica como admin real.
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/inventory/items';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('inventory/items — panel "Más filtros" + exportar Excel', () => {
  test('el panel "Más filtros" abre y un select nuevo empuja el param a la URL', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const moreBtn = page.locator('#btnMoreFilters');
    await expect(moreBtn).toBeVisible();
    const panel = page.locator('#hdMoreFilters');
    await expect(panel).not.toHaveClass(/show/);

    await moreBtn.click();
    await expect(panel).toHaveClass(/show/);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterWarranty', 'expiring');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro nuevo en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('warranty')).toBe('expiring');

    // La respuesta es un FRAGMENTO puro (mismo contrato que los 4 filtros originales).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('un chip de filtro activo se puede quitar individualmente', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, `${PAGE}?brand=dell`);

    const chip = page.locator('#hd-active-chips [data-chip-remove="brand"]');
    await expect(chip).toBeVisible();
    // El panel se abrió solo porque venía un filtro activo por URL.
    await expect(page.locator('#hdMoreFilters')).toHaveClass(/show/);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await chip.click();
    await waitPartial;

    await expect(page.locator('#filterBrand')).toHaveValue('');
    await expect(page.locator('#hd-active-chips [data-chip-remove="brand"]')).toHaveCount(0);
  });

  test('botón Exportar: <a href> real (sin blob) que descarga un .xlsx con los params del form', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    await page.selectOption('#filterStatus', 'ACTIVE');
    await page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');

    const exportLink = page.locator('#btn-export-xlsx');
    await expect(exportLink).toHaveAttribute('href', /\/inventory\/items\/export\.xlsx/);
    await expect(exportLink).toHaveAttribute('href', /status=ACTIVE/);

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      exportLink.click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/);

    // El click en un <a href> de descarga NO navega fuera de la lista.
    expect(page.url()).toContain(PAGE);
  });
});

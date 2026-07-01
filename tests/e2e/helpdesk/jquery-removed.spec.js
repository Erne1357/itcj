// @ts-check
// Chunk 9 (cierre bloque E-G) — eliminación de jQuery + barrido CSS final.
// Contrato estructural (no depende de datos de BD):
//   1. jQuery NO está en el runtime: window.jQuery/window.$ undefined y sin
//      <script> de jquery en el DOM (shim shared/base.js + CDN base_helpdesk.html
//      eliminados).
//   2. Los modales de inventory ahora dependen de Bootstrap 5 NATIVO: el shim
//      jQuery que interceptaba data-dismiss / backdrop se fue → BS5 debe abrir,
//      cerrar por el botón .btn-close (data-bs-dismiss) y limpiar su backdrop
//      sin ese shim (si estuviera roto, quedaría un .modal-backdrop pegado).
//   3. La navegación boost/morph sigue funcionando (jQuery nunca fue dependencia
//      del nav): un marcador de "carga viva" sobrevive a HelpdeskPage.navigate().
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk, gotoHelpdeskAs } = require('./_helpers');

const GROUPS = '/help-desk/inventory/groups';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('cierre E-G — jQuery eliminado, modales BS5 nativos, nav intacta', () => {
  test('jQuery NO está cargado: window.jQuery/$ undefined y sin <script> jquery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, GROUPS);

    const state = await page.evaluate(() => ({
      hasJQuery: typeof window.jQuery !== 'undefined',
      hasDollar: typeof window.$ !== 'undefined',
      jquerySrcs: Array.from(document.scripts)
        .map((s) => s.src)
        .filter((src) => /jquery/i.test(src)),
    }));

    expect(state.hasJQuery).toBe(false);
    expect(state.hasDollar).toBe(false);
    expect(state.jquerySrcs).toEqual([]);
  });

  test('modal BS5 (Crear Grupo) abre/cierra por .btn-close y limpia backdrop SIN shim jQuery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, GROUPS);

    const modal = page.locator('#groupModal');
    await expect(modal).toBeHidden();

    // Abre (onclick → bootstrap.Modal.getOrCreateInstance(el).show()).
    await page.getByRole('button', { name: /Crear Grupo/ }).first().click();
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);
    await expect(page.locator('.modal-backdrop')).toHaveCount(1); // BS5 montó el backdrop

    // Cierre por el botón BS5 .btn-close (data-bs-dismiss="modal") — lo interceptaba
    // el shim jQuery; ahora es 100% nativo.
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
    // BS5 limpió el backdrop por sí mismo (sin el shim no quedan overlays pegados).
    await expect(page.locator('.modal-backdrop')).toHaveCount(0);
  });

  test('nav boost/morph sigue viva tras quitar jQuery (HelpdeskPage.navigate sin recarga)', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/tickets-list');

    // Marca de carga viva: una recarga completa la perdería (window nuevo).
    const id = 'hd-' + Math.random().toString(36).slice(2);
    await page.evaluate((v) => { window.__hdLoadId = v; }, id);

    await page.evaluate(() => window.HelpdeskPage.navigate('/help-desk/user/create'));

    await expect(page).toHaveURL(/\/help-desk\/user\/create$/);
    expect(await page.evaluate(() => window.__hdLoadId)).toBe(id); // morfea, no recarga
    await expect(page.locator('main[data-hd-page="user_create_ticket"]')).toBeAttached();
  });
});

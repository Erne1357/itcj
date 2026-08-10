// @ts-check
// Rediseño de /help-desk/admin/home (franja KPI + banda "Requiere atención" +
// riel de acciones permanente + actividad reciente). Ver
// itcj2/apps/helpdesk/services/admin_dashboard_service.py y
// itcj2/apps/helpdesk/templates/helpdesk/admin/home.html.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

test.describe('admin/home — rediseño', () => {
  test('franja KPI con sus 6 métricas', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const kpiIds = ['#kpiTotal', '#kpiPending', '#kpiToday', '#kpiSatisfaction', '#kpiResolution', '#kpiSla'];
    for (const id of kpiIds) {
      await expect(page.locator(id)).toBeVisible();
    }
  });

  test('riel de acciones permanente (Tickets / Inventario / Reportes)', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const tiles = page.locator('main[data-hd-page="admin_home"] a.hd-action-tile');
    // 3 (tickets) + 3 (inventario) + 4 (reportes) = 10 tiles, siempre presentes.
    await expect(tiles).toHaveCount(10);

    // Ninguno degrada a href="#" (la clave inválida de url_for era justo el bug
    // de los 2 botones de inventario).
    const hrefs = await tiles.evaluateAll((els) => els.map((el) => el.getAttribute('href')));
    for (const href of hrefs) {
      expect(href).not.toBe('#');
      expect(href, `href vacío/nulo en un tile del riel: ${JSON.stringify(hrefs)}`).toBeTruthy();
    }
  });

  test('banda "Requiere atención" aparece con filas o cae al estado vacío', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const card = page.locator('main[data-hd-page="admin_home"] .hd-attention-card');
    await expect(card).toBeVisible();

    const rows = card.locator('.hd-attention-row');
    const emptyState = card.locator('.hd-empty-state');
    const rowCount = await rows.count();
    const emptyCount = await emptyState.count();

    // Exactamente una de las dos representaciones debe estar presente.
    expect(rowCount > 0 || emptyCount > 0).toBe(true);
    expect(rowCount > 0 && emptyCount > 0).toBe(false);
  });

  test('los dos botones de inventario ya no son href="#"', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const verInventario = page.locator('main[data-hd-page="admin_home"] a[href="/help-desk/inventory/items"]');
    const registrarEquipo = page.locator('main[data-hd-page="admin_home"] a[href="/help-desk/inventory/items/create"]');
    await expect(verInventario).toHaveCount(1);
    await expect(registrarEquipo).toHaveCount(1);
  });

  test('el botón Actualizar existe y no rompe la navegación', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const navEntriesBefore = await page.evaluate(() => performance.getEntriesByType('navigation').length);

    const refreshBtn = page.locator('#hdHomeRefreshBtn');
    await expect(refreshBtn).toBeVisible();
    await refreshBtn.click();

    // El morph re-renderiza el KPI strip; sigue visible tras el refresh.
    await expect(page.locator('#kpiTotal')).toBeVisible();

    const navEntriesAfter = await page.evaluate(() => performance.getEntriesByType('navigation').length);
    expect(navEntriesAfter, 'Actualizar no debe disparar un reload completo').toBe(navEntriesBefore);
  });

  test('contratos preservados: data-hd-page, hx-boost en tickets-list y assign-tickets, href exacto de stats', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    await expect(page.locator('main[data-hd-page="admin_home"]')).toBeVisible();

    const ticketsListLink = page.locator('a[href*="tickets-list"]').first();
    await expect(ticketsListLink).toHaveAttribute('hx-boost', 'true');

    const assignLink = page.locator('a[href*="assign-tickets"]').first();
    await expect(assignLink).toHaveAttribute('hx-boost', 'true');

    // Puede haber más de un enlace a Stats (nav + riel de acciones); el contrato
    // real (htmx-css.spec.js:39-42) solo exige que exista AL MENOS uno con href
    // exacto (sin query) y hx-boost, vía `.first()`.
    const statsLink = page.locator('a[hx-boost="true"][href="/help-desk/admin/stats"]').first();
    await expect(statsLink).toHaveCount(1);
  });
});

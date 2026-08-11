// @ts-check
// Panel "Más filtros": la elección del usuario manda sobre el default del server.
//
// El servidor renderiza el panel abierto cuando hay algún filtro avanzado activo
// (`more_open`), lo cual es correcto como estado INICIAL. El bug era que lo
// reimponía en CADA render completo: el usuario lo colapsaba y al siguiente
// refresh o navegación boosteada volvía a abrirse solo, así que parecía que el
// botón de colapsar no servía. Ahora la preferencia explícita se recuerda por
// página (shared/base.js: restoreFilterPanel).
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGINAS = [
  { nombre: 'inventario', url: '/help-desk/inventory/items', filtroAvanzado: 'warranty=expired', filtroBasico: 'filterStatus', valor: 'ACTIVE' },
  { nombre: 'tickets-list', url: '/help-desk/admin/tickets-list', filtroAvanzado: 'sort=oldest', filtroBasico: 'filterStatus', valor: 'CLOSED' },
];

for (const p of PAGINAS) {
  test.describe(`panel "Más filtros" — ${p.nombre}`, () => {
    test('un filtro avanzado activo lo abre en la primera visita', async ({ page }) => {
      await gotoHelpdesk(page, `${p.url}?${p.filtroAvanzado}`);
      const panel = page.locator('#hdMoreFilters');
      test.skip((await panel.count()) === 0, 'esta vista no tiene panel de filtros avanzados');
      await expect(panel).toHaveClass(/show/);
    });

    test('colapsarlo se respeta tras cambiar de filtro y tras recargar', async ({ page }) => {
      await gotoHelpdesk(page, `${p.url}?${p.filtroAvanzado}`);
      const panel = page.locator('#hdMoreFilters');
      test.skip((await panel.count()) === 0, 'esta vista no tiene panel de filtros avanzados');
      await expect(panel).toHaveClass(/show/);

      await page.locator('#btnMoreFilters').click();
      await expect(panel).not.toHaveClass(/show/);

      // Cambiar un filtro básico dispara HTMX + push-url.
      await page.selectOption(`#${p.filtroBasico}`, p.valor);
      await page.waitForTimeout(1200);
      await expect(panel).not.toHaveClass(/show/);

      // Recarga boosteada: es AQUÍ donde volvía a abrirse solo.
      await page.evaluate(() => window.HelpdeskPage.refresh());
      await page.waitForTimeout(1800);
      await expect(page.locator('#hdMoreFilters')).not.toHaveClass(/show/);
    });

    test('volver a abrirlo también se recuerda', async ({ page }) => {
      await gotoHelpdesk(page, p.url);
      const panel = page.locator('#hdMoreFilters');
      test.skip((await panel.count()) === 0, 'esta vista no tiene panel de filtros avanzados');

      await page.locator('#btnMoreFilters').click();
      await expect(panel).toHaveClass(/show/);

      await page.evaluate(() => window.HelpdeskPage.refresh());
      await page.waitForTimeout(1800);
      await expect(page.locator('#hdMoreFilters')).toHaveClass(/show/);
    });
  });
}

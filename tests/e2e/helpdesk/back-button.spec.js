// @ts-check
// Botón "Volver" de las páginas de detalle (ticket e ítem de inventario).
//
// Antes había DOS implementaciones divergentes sobre el mismo contrato de ids
// (#backButton / #backButtonText / #backButtonContainer): un switch de ocho casos
// en ticket_detail.js —cuatro apuntando a rutas 404— y una heurística de
// document.referrer en item_detail.js que dejaba el botón oculto en entrada
// directa. Ambas viven ahora en pages/origins.py + HelpdeskUtils.initBackButton.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const TICKETS_LIST = '/help-desk/admin/tickets-list';
const ITEMS_LIST = '/help-desk/inventory/items';

/** Primer ticket enlazado desde la lista de admin, o null si no hay datos. */
async function firstTicketId(page) {
  await gotoHelpdesk(page, TICKETS_LIST);
  const card = page.locator('#hd-tickets-results a[href*="/help-desk/user/tickets/"]').first();
  if ((await card.count()) === 0) return null;
  const href = await card.getAttribute('href');
  const m = href && href.match(/\/help-desk\/user\/tickets\/(\d+)/);
  return m ? m[1] : null;
}

/** Primer ítem enlazado desde la lista de inventario, o null si no hay datos. */
async function firstItemId(page) {
  await gotoHelpdesk(page, ITEMS_LIST);
  const link = page.locator('#hd-items-results a[href*="/help-desk/inventory/items/"]').first();
  if ((await link.count()) === 0) return null;
  const href = await link.getAttribute('href');
  const m = href && href.match(/\/help-desk\/inventory\/items\/(\d+)/);
  return m ? m[1] : null;
}

test.describe('botón Volver — registro de orígenes', () => {
  test('el registro se serializa en el shell y cubre los orígenes clave', async ({ page }) => {
    await gotoHelpdesk(page, TICKETS_LIST);
    const origins = await page.evaluate(() => {
      const el = document.getElementById('hd-origins');
      return el ? JSON.parse(el.textContent || '{}') : null;
    });
    expect(origins).not.toBeNull();
    for (const slug of ['my_tickets', 'technician', 'admin_tickets_list', 'stats', 'analysis', 'inventory_items']) {
      expect(origins[slug], `falta el origen ${slug}`).toBeTruthy();
      expect(origins[slug].url).toMatch(/^\/help-desk\//);
      expect(origins[slug].label).toBeTruthy();
    }
  });

  test('ninguna URL del registro es una de las cuatro rutas que estaban rotas', async ({ page }) => {
    await gotoHelpdesk(page, TICKETS_LIST);
    const urls = await page.evaluate(() => {
      const el = document.getElementById('hd-origins');
      return Object.values(JSON.parse(el.textContent || '{}')).map((o) => o.url);
    });
    for (const rota of [
      '/help-desk/user/tickets',
      '/help-desk/user/dashboard',
      '/help-desk/department/tickets',
      '/help-desk/secretary/dashboard',
    ]) {
      expect(urls, `${rota} es 404 y seguía en el registro`).not.toContain(rota);
    }
  });

  test('cada página declara su propio slug de origen', async ({ page }) => {
    for (const [path, slug] of [
      [TICKETS_LIST, 'admin_tickets_list'],
      ['/help-desk/admin/stats', 'stats'],
      ['/help-desk/admin/analysis', 'analysis'],
      [ITEMS_LIST, 'inventory_items'],
    ]) {
      await gotoHelpdesk(page, path);
      await expect(page.locator('main[data-hd-page]')).toHaveAttribute('data-hd-origin', slug);
    }
  });
});

test.describe('botón Volver — detalle de ticket', () => {
  for (const [from, url, label] of [
    ['admin_tickets_list', '/help-desk/admin/tickets-list', 'Lista de Tickets'],
    ['technician', '/help-desk/technician/dashboard', 'Panel de Técnicos'],
    ['my_tickets', '/help-desk/user/my-tickets', 'Mis Tickets'],
    ['stats', '/help-desk/admin/stats', 'Estadísticas'],
    ['analysis', '/help-desk/admin/analysis', 'Análisis'],
  ]) {
    test(`?from=${from} apunta a ${url}`, async ({ page }) => {
      const id = await firstTicketId(page);
      test.skip(!id, 'sin tickets en la BD de prueba');
      await gotoHelpdesk(page, `/help-desk/user/tickets/${id}?from=${from}`);
      const back = page.locator('#backButton');
      await expect(back).toHaveAttribute('href', url);
      await expect(page.locator('#backButtonText')).toHaveText(label);
      await expect(back).toBeVisible();
    });
  }

  test('sin ?from cae al default y el botón sigue visible', async ({ page }) => {
    const id = await firstTicketId(page);
    test.skip(!id, 'sin tickets en la BD de prueba');
    await page.goto(`/help-desk/user/tickets/${id}`, { waitUntil: 'domcontentloaded' });
    const back = page.locator('#backButton');
    await expect(back).toBeVisible();
    await expect(back).toHaveAttribute('href', /^\/help-desk\//);
    // El bug original: href="#" o display:none dejaban al usuario sin salida.
    await expect(back).not.toHaveAttribute('href', '#');
  });

  test('el alias histórico secretary_dashboard sigue resolviendo', async ({ page }) => {
    const id = await firstTicketId(page);
    test.skip(!id, 'sin tickets en la BD de prueba');
    await gotoHelpdesk(page, `/help-desk/user/tickets/${id}?from=secretary_dashboard`);
    await expect(page.locator('#backButton')).toHaveAttribute('href', '/help-desk/secretary/');
  });

  test('volver desde la lista navega por morph y deja UNA sola entrada de historia', async ({ page }) => {
    await gotoHelpdesk(page, TICKETS_LIST);
    const card = page.locator('#hd-tickets-results a[href*="/help-desk/user/tickets/"]').first();
    test.skip((await card.count()) === 0, 'sin tickets en la BD de prueba');

    await card.click();
    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+/);
    await expect(page.locator('main[data-hd-page]')).toHaveAttribute('data-hd-page', 'user_ticket_detail');

    await page.locator('#backButton').click();
    await expect(page).toHaveURL(new RegExp(TICKETS_LIST.replace(/\//g, '\\/')));
    await expect(page.locator('main[data-hd-page]')).toHaveAttribute('data-hd-page', 'admin_tickets_list');
    // Sin recarga completa: el marcador de gotoHelpdesk sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
    // Y sin push extra: un solo back regresa al detalle.
    await page.goBack();
    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+/);
  });
});

test.describe('botón Volver — detalle de ítem de inventario', () => {
  test('desde la lista de inventario vuelve a la lista', async ({ page }) => {
    await gotoHelpdesk(page, ITEMS_LIST);
    const link = page.locator('#hd-items-results a[href*="/help-desk/inventory/items/"]').first();
    test.skip((await link.count()) === 0, 'sin ítems en la BD de prueba');

    await link.click();
    await expect(page).toHaveURL(/\/help-desk\/inventory\/items\/\d+/);
    const back = page.locator('#backButton');
    await expect(back).toBeVisible({ timeout: 15_000 });
    await expect(back).toHaveAttribute('href', ITEMS_LIST);
  });

  test('en entrada directa el botón se muestra con el default (antes quedaba oculto)', async ({ page }) => {
    const id = await firstItemId(page);
    test.skip(!id, 'sin ítems en la BD de prueba');
    await page.goto(`/help-desk/inventory/items/${id}`, { waitUntil: 'domcontentloaded' });
    const back = page.locator('#backButton');
    await expect(back).toBeVisible({ timeout: 15_000 });
    await expect(back).toHaveAttribute('href', ITEMS_LIST);
  });

  test('?from=inventory_verification vuelve a verificación', async ({ page }) => {
    const id = await firstItemId(page);
    test.skip(!id, 'sin ítems en la BD de prueba');
    await page.goto(`/help-desk/inventory/items/${id}?from=inventory_verification`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#backButton')).toHaveAttribute('href', '/help-desk/inventory/verification', {
      timeout: 15_000,
    });
  });
});

test.describe('enlaces que estaban muertos', () => {
  test('los dos botones de inventario del home ya no son href="#"', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');
    const main = page.locator('main[data-hd-page]');
    await expect(main.locator('a[href="/help-desk/inventory/items"]').first()).toHaveCount(1);
    await expect(main.locator('a[href="/help-desk/inventory/items/create"]').first()).toHaveCount(1);
    // Ningún enlace de contenido debe quedar en "#": es cómo degrada url_for con
    // una clave inválida, y por eso estos dos botones no hacían nada.
    expect(await main.locator('a[href="#"]:not([data-bs-toggle])').count()).toBe(0);
  });

  test('las 3 tarjetas de Reportes de Inventario apuntan a rutas reales', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/inventory/reports');
    const main = page.locator('main');
    for (const path of [
      '/help-desk/inventory/reports/warranty',
      '/help-desk/inventory/reports/maintenance',
      '/help-desk/inventory/reports/lifecycle',
    ]) {
      await expect(main.locator(`a[href="${path}"]`)).toHaveCount(1);
    }
  });
});

// @ts-check
// Chunk 1 — navegación morph en enlaces/botones INTER-pestaña.
//   Templates: filtro Jinja hd_boost(url) → los <a href> de CONTENIDO
//     (ticket_card, "Crear mi primer ticket", "Ver Detalle") llevan hx-boost.
//   JS: window.HelpdeskPage.navigate(url) → los redirects/quick-view morfean
//     igual que la navbar en vez de recargar.
//
// Cada caso valida el contrato del morph: la navegación NO es recarga completa
// (un marcador window.__hdLoadId puesto en la carga SOBREVIVE al click; una
// recarga lo borraría), la URL cambia (push-url) y aparece el contenido nuevo.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

// Marca de "carga viva": si ocurre una recarga completa se pierde (window nuevo).
async function markLoad(page) {
  const id = 'hd-' + Math.random().toString(36).slice(2);
  await page.evaluate((v) => { window.__hdLoadId = v; }, id);
  return id;
}
const liveId = (page) => page.evaluate(() => window.__hdLoadId);

test.describe('inter-tab morph — hd_boost + HelpdeskPage.navigate', () => {
  test('ticket_card → detalle: hx-boost, morfea (sin recarga), URL cambia, aparece el detalle', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/tickets-list');
    const id = await markLoad(page);

    // La tarjeta (macro compartido de las 7 vistas) ahora es un enlace boosteado.
    const card = page.locator('#hd-tickets-results a.hd-ticket-card[hx-boost="true"]').first();
    await expect(card).toHaveCount(1);
    expect(await card.getAttribute('href')).toMatch(/\/help-desk\/user\/tickets\/\d+/);

    await card.click();

    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+/);
    expect(await liveId(page)).toBe(id);                                 // sin recarga completa
    await expect(page.locator('main[data-hd-page="user_ticket_detail"]')).toBeAttached();
  });

  test('dashboard(my-tickets) → crear: el botón "Nuevo Ticket" del header morfea (sin recarga)', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/user/my-tickets');
    const id = await markLoad(page);

    // Botón "Nuevo Ticket" del header_actions — siempre presente (independiente del nº de tickets).
    // Se usa .first() para tomar el primero en DOM (el del navbar) en caso de que el
    // empty-state también tenga uno con hx-boost; así el test es determinista.
    const link = page.locator(
      'a[href="/help-desk/user/create"][hx-boost="true"]'
    ).first();
    await expect(link).toBeVisible();

    await link.click();

    await expect(page).toHaveURL(/\/help-desk\/user\/create$/);
    expect(await liveId(page)).toBe(id);                                 // sin recarga completa
    await expect(page.locator('main[data-hd-page="user_create_ticket"]')).toBeAttached();
  });

  test('HelpdeskPage.navigate() (JS): morfea + push-url; back/forward sin recarga', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/tickets-list');
    const id = await markLoad(page);

    // Navegación disparada desde JS (contraparte de los redirects/quick-view migrados).
    await page.evaluate(() => window.HelpdeskPage.navigate('/help-desk/user/create'));
    await expect(page).toHaveURL(/\/help-desk\/user\/create$/);
    expect(await liveId(page)).toBe(id);                                 // morfea, no recarga
    await expect(page.locator('main[data-hd-page="user_create_ticket"]')).toBeAttached();

    // Back: un solo push → una sola vuelta a tickets-list, por morph (restore = swap).
    await page.evaluate(() => history.back());
    await expect(page).toHaveURL(/\/help-desk\/admin\/tickets-list$/);
    expect(await liveId(page)).toBe(id);                                 // restore no recarga
    await expect(page.locator('main[data-hd-page="admin_tickets_list"]')).toBeAttached();

    // Forward: vuelve a crear.
    await page.evaluate(() => history.forward());
    await expect(page).toHaveURL(/\/help-desk\/user\/create$/);
    await expect(page.locator('main[data-hd-page="user_create_ticket"]')).toBeAttached();
  });

  test('petición HX-Request+HX-Boosted a una página con rama-fragmento devuelve la PÁGINA completa', async ({ request }) => {
    // navigate() envía HX-Boosted:true → el endpoint "misma URL, 2 representaciones"
    // (p.ej. my-tickets) debe devolver el documento completo, no el fragmento; así el
    // morph del <body> recibe la página entera (nav incluida).
    const boosted = await request.get('/help-desk/user/my-tickets', {
      headers: { 'HX-Request': 'true', 'HX-Boosted': 'true' },
      maxRedirects: 0,
    });
    expect(boosted.status()).toBe(200);
    expect(await boosted.text()).toContain('<html');

    // Sin HX-Boosted (solo HX-Request) sigue devolviendo el fragmento (filtros/paginación).
    const frag = await request.get('/help-desk/user/my-tickets', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    expect(await frag.text()).not.toContain('<html');
  });
});

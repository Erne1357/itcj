// @ts-check
// Modal de resumen de ticket enlazado desde /help-desk/admin/stats (tab
// Calificaciones): la tarjeta de un comentario reciente es clickeable (mouse
// y teclado) y abre #ticketSummaryModal con el folio correcto; "Abrir ticket"
// navega al detalle con ?from=stats sin recarga completa.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/stats';

/**
 * Navega a la página Y espera a que `stats.js` termine de cargar y corra su
 * init() (que engancha los listeners de tabs).
 *
 * `gotoHelpdesk` solo espera a que `main[data-hd-page]` sea visible —eso pasa
 * en cuanto llega el HTML del server—, NO a que termine la cadena async de
 * módulos de la página (Chart.js CDN + ticket-summary.js + stats.js, ver
 * HD_PAGE_MODULES en pages/nav.py). Si se hace clic en un tab ANTES de que
 * termine esa cadena, Bootstrap sí cambia las clases CSS del tab (su propio
 * manejador interno), pero el listener `shown.bs.tab` de stats.js —el que
 * dispara loadRatings()— todavía no existe y el evento se pierde.
 *
 * `loadPeriods()` (que dispara `GET /stats/global`) es la PRIMERA línea de
 * `init()`, antes de enganchar cualquier listener de tab — esperar esa
 * respuesta es prueba de que init() ya corrió y los listeners ya existen.
 */
async function gotoStatsReady(page) {
  const waitGlobal = page.waitForResponse(
    (r) => r.url().includes('/api/help-desk/v2/stats/global') && r.request().method() === 'GET',
    { timeout: 20_000 },
  );
  await gotoHelpdesk(page, PAGE);
  await waitGlobal;
}

async function openRatingsTab(page) {
  const waitResp = page.waitForResponse(
    (r) => r.url().includes('/stats/ratings-detail') && r.request().method() === 'GET',
    { timeout: 20_000 },
  );
  await page.click('#tab-rating-link');
  await expect(page.locator('#tab-rating')).toHaveClass(/active/);
  const resp = await waitResp;
  expect(resp.ok()).toBeTruthy();
  // renderComments() reemplaza el spinner inicial por las tarjetas (o el
  // mensaje de "sin comentarios") — esperar a que deje de estar cargando.
  await expect(page.locator('#recentComments')).not.toContainText('Cargando...', { timeout: 10_000 });
}

async function waitModalLoaded(page) {
  await expect(page.locator('#ticketSummaryModal')).toHaveClass(/show/, { timeout: 5_000 });
  await expect(page.locator('#ticketSummaryLoading')).toBeHidden({ timeout: 10_000 });
}

test.describe('stats — enlazar comentario de calificación a su ticket', () => {
  test('click en la tarjeta de comentario abre el modal con el folio correcto', async ({ page }) => {
    await gotoStatsReady(page);
    await openRatingsTab(page);

    const card = page.locator('#recentComments .rating-comment-card').first();
    test.skip((await card.count()) === 0, 'Sin comentarios de calificación en la BD de prueba');

    const refText = await card.locator('.ticket-ref').innerText();
    const folio = refText.split('·')[0].trim();

    await card.click();
    await waitModalLoaded(page);
    await expect(page.locator('#ticketSummaryNumber')).toHaveText(folio);
    await expect(page.locator('#ticketSummaryContent')).toBeVisible();
  });

  test('la tarjeta es accesible por teclado: foco + Enter abre el modal', async ({ page }) => {
    await gotoStatsReady(page);
    await openRatingsTab(page);

    const card = page.locator('#recentComments .rating-comment-card').first();
    test.skip((await card.count()) === 0, 'Sin comentarios de calificación en la BD de prueba');

    await expect(card).toHaveAttribute('role', 'button');
    await expect(card).toHaveAttribute('tabindex', '0');

    await card.focus();
    await page.keyboard.press('Enter');
    await waitModalLoaded(page);
  });

  test('"Abrir ticket" navega al detalle con ?from=stats, sin recarga completa', async ({ page }) => {
    await gotoStatsReady(page);
    await openRatingsTab(page);

    const card = page.locator('#recentComments .rating-comment-card').first();
    test.skip((await card.count()) === 0, 'Sin comentarios de calificación en la BD de prueba');

    await card.click();
    await waitModalLoaded(page);

    await page.click('#ticketSummaryOpenBtn');
    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+\?from=stats$/);
    await expect(page.locator('main[data-hd-page="user_ticket_detail"]')).toBeAttached();
    // Sin recarga completa: el marcador de gotoHelpdesk sobrevive al morph.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
  });

  test('"Abrir en pestaña nueva" sigue disponible junto al enlace nuevo', async ({ page }) => {
    await gotoStatsReady(page);
    await openRatingsTab(page);

    const card = page.locator('#recentComments .rating-comment-card').first();
    test.skip((await card.count()) === 0, 'Sin comentarios de calificación en la BD de prueba');

    await card.click();
    await waitModalLoaded(page);

    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.click('#ticketSummaryNewTabBtn'),
    ]);
    await popup.waitForLoadState('domcontentloaded');
    expect(popup.url()).toMatch(/\/help-desk\/user\/tickets\/\d+/);
    await popup.close();
  });
});

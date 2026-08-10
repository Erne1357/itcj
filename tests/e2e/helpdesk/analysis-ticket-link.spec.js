// @ts-check
// Modal de resumen de ticket enlazado desde /help-desk/admin/analysis: el
// folio de la tabla de outliers y el de la tabla drill-down de un clúster
// abren #ticketSummaryModal; "Abrir ticket" navega al detalle con
// ?from=analysis sin recarga completa.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/analysis';

/**
 * Navega a la página Y espera la respuesta de red de outliers (pestaña activa
 * por defecto: `loadCurrentTab()` la dispara al FINAL de `init()`, así que
 * esta respuesta también es prueba de que init() ya corrió y enganchó los
 * demás listeners — el de la pestaña Clustering y el botón #runKmeans
 * incluidos). El listener se registra ANTES de `gotoHelpdesk` para no perder
 * la respuesta si llega mientras la navegación aún resuelve.
 */
async function gotoAnalysisAndWaitOutliers(page) {
  const waitResp = page.waitForResponse(
    (r) => r.url().includes('/stats/analysis/outliers') && r.request().method() === 'GET',
    { timeout: 20_000 },
  );
  await gotoHelpdesk(page, PAGE);
  const resp = await waitResp;
  expect(resp.ok()).toBeTruthy();
  await expect(page.locator('#outlierTableBody')).not.toContainText('Cargando outliers', { timeout: 10_000 });
}

async function waitModalLoaded(page) {
  await expect(page.locator('#ticketSummaryModal')).toHaveClass(/show/, { timeout: 5_000 });
  await expect(page.locator('#ticketSummaryLoading')).toBeHidden({ timeout: 10_000 });
}

test.describe('analysis — enlazar tickets de outliers a su detalle', () => {
  test('el folio de la tabla de outliers abre el modal con el folio correcto', async ({ page }) => {
    await gotoAnalysisAndWaitOutliers(page);

    const folioBtn = page.locator('#outlierTableBody button').first();
    test.skip((await folioBtn.count()) === 0, 'Sin outliers en la BD de prueba');

    const folio = (await folioBtn.innerText()).trim();
    await folioBtn.click();

    await waitModalLoaded(page);
    await expect(page.locator('#ticketSummaryNumber')).toHaveText(folio);
  });

  test('"Abrir ticket" desde outliers navega con ?from=analysis, sin recarga completa', async ({ page }) => {
    await gotoAnalysisAndWaitOutliers(page);

    const folioBtn = page.locator('#outlierTableBody button').first();
    test.skip((await folioBtn.count()) === 0, 'Sin outliers en la BD de prueba');

    await folioBtn.click();
    await waitModalLoaded(page);

    await page.click('#ticketSummaryOpenBtn');
    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+\?from=analysis$/);
    await expect(page.locator('main[data-hd-page="user_ticket_detail"]')).toBeAttached();
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
  });
});

test.describe('analysis — enlazar tickets de un clúster (drill-down) a su detalle', () => {
  test('una fila de la tabla drill-down de un clúster abre el modal', async ({ page }) => {
    // Reutiliza el mismo gate de "init() ya corrió" que outliers (ver arriba):
    // el listener de #runKmeans también se engancha dentro de init().
    await gotoAnalysisAndWaitOutliers(page);

    await page.click('#analysisTabs a[href="#tab-clustering"]');
    await expect(page.locator('#tab-clustering')).toHaveClass(/active/);

    const waitKmeans = page.waitForResponse(
      (r) => r.url().includes('/stats/analysis/kmeans') && r.request().method() === 'GET',
      { timeout: 20_000 },
    );
    await page.click('#runKmeans');
    const kmeansResp = await waitKmeans;
    expect(kmeansResp.ok()).toBeTruthy();
    await expect(page.locator('#kmeansStatus')).not.toHaveText('', { timeout: 10_000 });

    const viewBtn = page.locator('#clusterCards button', { hasText: 'Ver tickets' }).first();
    test.skip((await viewBtn.count()) === 0, 'Sin clústeres con datos suficientes en la BD de prueba');
    await viewBtn.click();

    const rowBtn = page.locator('#clusterDetailBody button').first();
    test.skip((await rowBtn.count()) === 0, 'Clúster sin tickets');
    const folio = (await rowBtn.innerText()).trim();
    await rowBtn.click();

    await waitModalLoaded(page);
    await expect(page.locator('#ticketSummaryNumber')).toHaveText(folio);
  });
});

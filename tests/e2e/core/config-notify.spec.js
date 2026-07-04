// @ts-check
/**
 * F6: el shell de config abre una conexión /notify presence-only, para que
 * los admins viendo /itcj/config cuenten en el widget "En Línea".
 */
const { test, expect } = require('@playwright/test');
const { gotoCore } = require('./_helpers');

test('el shell de config conecta /notify', async ({ page }) => {
  await gotoCore(page, '/itcj/config');
  await expect
    .poll(
      () => page.evaluate(() => !!(window.__notifySocket && window.__notifySocket.connected)),
      { timeout: 10_000 }
    )
    .toBe(true);
});

test('la conexión sobrevive a la navegación morph entre páginas', async ({ page }) => {
  await gotoCore(page, '/itcj/config');
  await expect
    .poll(() => page.evaluate(() => !!(window.__notifySocket && window.__notifySocket.connected)), { timeout: 10_000 })
    .toBe(true);
  const sockId = await page.evaluate(() => window.__notifySocket.id);
  // navegar a otra pestaña del shell (boost island) y volver
  await page.click('.config-sidebar a[href*="/itcj/config/users"]');
  await page.waitForSelector('[data-cfg-page="users"]', { timeout: 10_000 });
  const sockIdAfter = await page.evaluate(() => window.__notifySocket && window.__notifySocket.id);
  expect(sockIdAfter).toBe(sockId); // mismo socket: no se recreó ni se cerró
});

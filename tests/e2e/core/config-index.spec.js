// @ts-check
/**
 * F2 — piloto index: el módulo active-users se carga vía data-cfg-modules
 * (controller), NO via extra_js, y el widget queda montado.
 */
const { test, expect } = require('@playwright/test');
const { gotoCore } = require('./_helpers');

test.describe('config index — módulo piloto', () => {
  test('los módulos del index se cargan vía el registry', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /active-users\.js/);
    // el controller inyecta los <script> en <head> (loader secuencial)
    await expect
      .poll(async () => page.evaluate(() =>
        Array.from(document.head.querySelectorAll('script'))
          .some((s) => (s.src || '').includes('js/config/active-users.js'))
      ), { timeout: 8_000 })
      .toBe(true);
    await expect(page.locator('#active-users-total')).toBeVisible();
    // y NO queda ningún <script src> de página dentro del body (regla extra_js vacío)
    const bodyPageScripts = await page.evaluate(() =>
      Array.from(document.body.querySelectorAll('script[src]'))
        .filter((s) => s.src.includes('active-users.js') || s.src.includes('cdn.socket.io')).length
    );
    expect(bodyPageScripts).toBe(0);
  });
});

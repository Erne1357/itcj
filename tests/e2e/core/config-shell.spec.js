// @ts-check
/**
 * F2 — shell del panel config: ConfigShell (sidebar/iframe) + ConfigUtils
 * (toasts/escapeHtml). Los handlers viven DELEGADOS en document (morph-safe);
 * el template ya no tiene onclick inline.
 */
const { test, expect } = require('@playwright/test');
const { gotoCore } = require('./_helpers');

test.describe('config shell — ConfigShell/ConfigUtils', () => {
  test('sin handlers inline y con helpers globales', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    expect(await page.locator('[onclick]').count()).toBe(0);
    const api = await page.evaluate(() => ({
      shell: typeof window.ConfigShell,
      utils: typeof window.ConfigUtils,
      esc: window.ConfigUtils && window.ConfigUtils.escapeHtml('<a b="c">&\''),
      legacy: typeof window.showSuccess === 'function' && typeof window.showError === 'function',
    }));
    expect(api.shell).toBe('object');
    expect(api.utils).toBe('object');
    expect(api.esc).toBe('&lt;a b=&quot;c&quot;&gt;&amp;&#039;');
    expect(api.legacy).toBe(true);
  });

  test('ConfigUtils.showToast muestra el toast de error del shell', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    await page.evaluate(() => window.ConfigUtils.showToast('boom', 'error'));
    await expect(page.locator('#errorToast')).toHaveClass(/show/);
    await expect(page.locator('#errorMessage')).toHaveText('boom');
  });

  test('móvil (375px): toggle abre el sidebar y el overlay lo cierra', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await gotoCore(page, '/itcj/config');
    await page.locator('#normalMobileToggle').click();
    await expect(page.locator('#configSidebar')).toHaveClass(/open/);
    await expect(page.locator('#sidebarOverlay')).toHaveClass(/show/);
    await page.locator('#sidebarOverlay').click();
    await expect(page.locator('#configSidebar')).not.toHaveClass(/open/);
  });
});

test.describe('config shell — controller ConfigPage (C2)', () => {
  test('expone register/navigate/page y lee la página actual', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const api = await page.evaluate(() => ({
      reg: typeof (window.ConfigPage && window.ConfigPage.register),
      nav: typeof (window.ConfigPage && window.ConfigPage.navigate),
      page: window.ConfigPage && window.ConfigPage.page,
    }));
    expect(api.reg).toBe('function');
    expect(api.nav).toBe('function');
    expect(api.page).toBe('index');
  });

  test('navigate() a página NO migrada hace fallback duro (recarga completa)', async ({ page }) => {
    await gotoCore(page, '/itcj/config'); // gotoCore instala window.__booted
    await page.evaluate(() => window.ConfigPage.navigate('/itcj/config/users'));
    await page.waitForURL(/\/itcj\/config\/users/);
    // una recarga completa borra el marker
    expect(await page.evaluate(() => window.__booted === true)).toBe(false);
    await expect(page.locator('#cfgMain[data-cfg-page="users"]')).toBeAttached();
  });
});

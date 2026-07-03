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

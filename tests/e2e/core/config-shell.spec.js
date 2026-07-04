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

test.describe('config shell — sidebar tablet (≤992px)', () => {
  test('tablet (900px): toggle visible y el sidebar expande con click, no con hover', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await gotoCore(page, '/itcj/config');

    const toggle = page.locator('#normalMobileToggle');
    await expect(toggle).toBeVisible(); // HOY FALLA: el toggle solo aparece ≤768px

    const width = () =>
      page.locator('#configSidebar').evaluate((el) => Math.round(el.getBoundingClientRect().width));
    expect(await width()).toBe(60);   // rail colapsado

    await toggle.click();
    await expect(page.locator('#configSidebar')).toHaveClass(/open/);
    await expect.poll(width, { timeout: 3_000 }).toBe(280); // expandido (transición 0.2s)
    // labels visibles al expandir
    await expect(page.locator('.config-nav-link span').first()).toBeVisible();

    await toggle.click();
    await expect(page.locator('#configSidebar')).not.toHaveClass(/open/);
  });
});

test.describe('config shell — tokens y avatares dedupe', () => {
  test('--app-primary es alias de --config-primary y el avatar del sidebar conserva su look', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const probe = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      const avatar = document.querySelector('.config-sidebar-user .user-avatar');
      const acs = avatar ? getComputedStyle(avatar) : null;
      return {
        appPrimary: cs.getPropertyValue('--app-primary').trim(),
        configPrimary: cs.getPropertyValue('--config-primary').trim(),
        avatarW: acs ? acs.width : null,
        avatarBg: acs ? acs.backgroundImage : null,
        avatarRadius: acs ? acs.borderRadius : null,
      };
    });
    // HOY FALLA: --app-primary es #6366f1 (indigo), no el azul config
    expect(probe.appPrimary.replace(/\s/g, '')).not.toBe('#6366f1');
    // el alias debe RESOLVER al valor de --config-primary (var() o literal)
    expect(
      probe.appPrimary === probe.configPrimary ||
      probe.appPrimary.includes('--config-primary')
    ).toBe(true);
    // el avatar del sidebar no pierde su definición al deduplicar
    expect(probe.avatarW).toBe('36px');
    expect(probe.avatarBg).toContain('linear-gradient');
    expect(probe.avatarRadius).toBe('50%');
  });
});

test.describe('config shell — estados hidden sin style inline', () => {
  test('elementos de estado siguen ocultos tras migrar a .cfg-hidden', async ({ page }) => {
    await gotoCore(page, '/itcj/config/users');
    await expect(page.locator('#staffFields')).toBeHidden();
    await expect(page.locator('#appAssignmentPanel')).toBeHidden();
    const inline = await page.evaluate(() =>
      document.querySelectorAll('#cfgMain [style], .modal [style]').length);
    expect(inline).toBe(0); // HOY FALLA: 4 style= en users.html

    await gotoCore(page, '/itcj/config/system/tasks');
    await expect(page.locator('#runsPagination')).toBeHidden();
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

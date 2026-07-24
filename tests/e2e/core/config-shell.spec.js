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
    // style= con SOLO custom properties (--*) es legítimo por contrato C8
    // (app-badge usa style="--app-badge-color: ..."); se prohíbe todo estilo inline real.
    const inline = await page.evaluate(() =>
      Array.from(document.querySelectorAll('#cfgMain [style], .modal [style]'))
        .filter((el) => {
          const s = el.style;
          for (let i = 0; i < s.length; i++) {
            if (!s[i].startsWith('--')) return true; // declaración real → violación
          }
          return s.length === 0 && el.getAttribute('style').trim() !== ''; // atributo raro no parseado
        }).length);
    expect(inline).toBe(0);

    await gotoCore(page, '/itcj/config/system/tasks');
    await expect(page.locator('#runsPagination')).toBeHidden();
  });
});

test.describe('config shell — badges compartidos (C8)', () => {
  test('scope-badge y app-badge resuelven con sus colores', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const probe = await page.evaluate(() => {
      const mk = (cls, colorVar) => {
        const el = document.createElement('span');
        el.className = cls;
        if (colorVar) el.style.setProperty('--app-badge-color', colorVar);
        document.body.appendChild(el);
        const cs = getComputedStyle(el);
        const out = { display: cs.display, bg: cs.backgroundColor };
        el.remove();
        return out;
      };
      return {
        subtree: mk('scope-badge scope-subtree'),
        own: mk('scope-badge scope-own'),
        app: mk('app-badge', '#ff5722'),
        appFallback: mk('app-badge'),
      };
    });
    expect(probe.subtree.display).toBe('inline-block');
    expect(probe.subtree.bg).toBe('rgb(111, 66, 193)');   // --config-purple
    expect(probe.own.bg).toBe('rgb(13, 202, 240)');       // --config-info
    expect(probe.app.bg).toBe('rgb(255, 87, 34)');        // var por-instancia
    expect(probe.appFallback.bg).toBe('rgb(108, 117, 125)'); // fallback #6c757d
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

  test('navigate() a URL fuera del registry hace fallback duro (recarga completa)', async ({ page }) => {
    // F5 cerró la migración de las 12 páginas de config (incluidas
    // department_detail y position_detail): ya no hay una página DENTRO de
    // /itcj/config que quede fuera de CONFIG_PAGE_MODULES. El caso vigente de
    // fallback duro es un destino fuera de la whitelist de config por
    // completo: /itcj/profile (página real del core, ajena al shell).
    await gotoCore(page, '/itcj/config'); // gotoCore instala window.__booted
    await page.evaluate(() => window.ConfigPage.navigate('/itcj/profile'));
    await page.waitForURL(/\/itcj\/profile/);
    // una recarga completa borra el marker
    expect(await page.evaluate(() => window.__booted === true)).toBe(false);
    await expect(page.locator('#profileTabs')).toBeAttached();
  });
});

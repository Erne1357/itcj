// @ts-check
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

/**
 * Central bug of the HTMX migration: when navigating via hx-boost (body morph),
 * the destination page's per-page CSS (declared in its {% block extra_css %})
 * must be injected into <head> by the head-support extension. Without
 * head-support, that CSS never enters the document on boosted navigation, so
 * the page looks unstyled until a full reload.
 *
 * We start at /help-desk/admin/home (full load), then boost-navigate to
 * /help-desk/admin/stats and assert:
 *   (a) the URL changed,
 *   (b) NO full navigation occurred (window.__booted survives — a reload clears it),
 *   (c) the stats CSS link (css/admin/stats.css) is now present in <head>.
 */
test.describe('htmx head-support — per-page CSS on boosted navigation', () => {
  test('stats CSS is injected into <head> after boosting to stats (no full reload)', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    // Sanity: stats CSS is NOT present on the home page yet.
    const statsCssBefore = await page.evaluate(() =>
      Array.from(document.head.querySelectorAll('link[rel="stylesheet"]'))
        .some((l) => (l.getAttribute('href') || '').includes('css/admin/stats.css'))
    );
    expect(statsCssBefore).toBe(false);

    // Baseline number of REAL navigations recorded by the browser. A genuine
    // full reload appends a new PerformanceNavigationTiming entry; a boosted
    // (morph) navigation does not. (page.on('load') is NOT reliable here: htmx
    // fires a 'load' on the same document during settle even without a reload.)
    const navEntriesBefore = await page.evaluate(
      () => performance.getEntriesByType('navigation').length
    );
    expect(navEntriesBefore).toBe(1);

    // Find a boosted link to Stats inside the Reportes dropdown (or anywhere).
    const statsLink = page
      .locator('a[hx-boost="true"][href="/help-desk/admin/stats"]')
      .first();
    await expect(statsLink).toHaveCount(1);

    // Trigger the boosted navigation. Dispatch the click directly via JS so we
    // don't depend on the dropdown being visually open.
    await statsLink.dispatchEvent('click');

    // (a) URL changed to stats.
    await expect(page).toHaveURL(/\/help-desk\/admin\/stats$/, { timeout: 10_000 });

    // Wait for the boosted content + head-support to settle.
    await page.locator('main[data-hd-page="admin_stats"]').waitFor({ state: 'attached', timeout: 10_000 });

    // (c) stats CSS now present in <head> (injected by head-support).
    await expect
      .poll(
        async () =>
          page.evaluate(() =>
            Array.from(document.head.querySelectorAll('link[rel="stylesheet"]'))
              .some((l) => (l.getAttribute('href') || '').includes('css/admin/stats.css'))
          ),
        { timeout: 8_000, message: 'stats.css was not injected into <head> by head-support' }
      )
      .toBe(true);

    // (b) No full reload happened, proven two ways:
    //   - the window.__booted marker (set after the initial load) survived; a
    //     real reload would have cleared it.
    //   - the browser recorded NO new navigation timing entry (still 1).
    const stillBooted = await page.evaluate(() => window.__booted === true);
    expect(stillBooted, 'window.__booted should survive a boosted (morph) navigation').toBe(true);

    const navEntriesAfter = await page.evaluate(
      () => performance.getEntriesByType('navigation').length
    );
    expect(navEntriesAfter, 'a boosted navigation must not append a navigation timing entry').toBe(1);
  });
});

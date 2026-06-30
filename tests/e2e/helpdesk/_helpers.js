// @ts-check
const { expect } = require('@playwright/test');

/**
 * Load a helpdesk page (full navigation) and wait until the HTMX/idiomorph
 * stack is settled and the <main data-hd-page> is present.
 * Installs a window.__booted marker so boosted-navigation tests can assert that
 * no full page reload happened afterwards (a reload would clear the marker).
 */
async function gotoHelpdesk(page, urlPath) {
  await page.goto(urlPath, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-hd-page]')).toBeVisible();
  await page.evaluate(() => {
    // @ts-ignore
    window.__booted = true;
  });
}

/**
 * Open a navbar dropdown by its visible label (desktop navbar). Returns the
 * <li.nav-item.dropdown> locator so callers can query items inside it.
 */
function navDropdown(page, label) {
  return page
    .locator('#navbarContent li.nav-item.dropdown')
    .filter({ has: page.locator('a.dropdown-toggle', { hasText: label }) });
}

module.exports = { gotoHelpdesk, navDropdown };

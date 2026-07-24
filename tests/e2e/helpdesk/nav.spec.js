// @ts-check
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk, navDropdown } = require('./_helpers');

/**
 * Fix under test: "Dashboard Admin" lives INSIDE the "Gestión" dropdown and
 * points at the admin home endpoint. There must be NO standalone top-level
 * "Dashboard" nav item outside Gestión.
 *
 * Real endpoint (verified against templates.py ENDPOINT_MAP / pages/admin.py):
 *   helpdesk_pages.admin_pages.home -> /help-desk/admin/home
 */
test.describe('navbar — Gestión dropdown', () => {
  test('contains a "Dashboard Admin" item linking to admin home', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    const gestion = navDropdown(page, 'Gestión');
    await expect(gestion).toHaveCount(1);

    // The "Dashboard Admin" link inside Gestión.
    const dashAdmin = gestion.locator('a.dropdown-item', { hasText: 'Dashboard Admin' });
    await expect(dashAdmin).toHaveCount(1);
    await expect(dashAdmin).toHaveAttribute('href', '/help-desk/admin/home');
  });

  test('has NO standalone top-level "Dashboard" item outside Gestión', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/home');

    // Top-level navbar links that are NOT dropdown toggles and NOT dropdown items.
    const topLevelLinks = page.locator(
      '#navbarContent > ul.navbar-nav > li.nav-item > a.nav-link:not(.dropdown-toggle)'
    );
    const count = await topLevelLinks.count();
    for (let i = 0; i < count; i++) {
      const text = ((await topLevelLinks.nth(i).innerText()) || '').trim();
      // A bare "Dashboard" top-level entry would be the regression.
      expect(text).not.toBe('Dashboard');
      expect(text).not.toBe('Dashboard Admin');
    }
  });
});

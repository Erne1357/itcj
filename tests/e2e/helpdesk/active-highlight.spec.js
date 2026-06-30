// @ts-check
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk, navDropdown } = require('./_helpers');

/**
 * Fix under test: server-side active-state highlighting. On a given page, the
 * matching nav entry must carry the `active` class, and its parent dropdown
 * group must be marked active (group_active -> sidebar .has-active).
 *
 * We use /help-desk/admin/stats: its nav item ("Estadísticas") lives in the
 * "Reportes" dropdown and should be highlighted.
 */
test.describe('nav active highlight (server-side)', () => {
  test('the matching dropdown item is .active on its page', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/stats');

    // The Estadísticas item inside Reportes should be active.
    const reportes = navDropdown(page, 'Reportes');
    await expect(reportes).toHaveCount(1);

    const statsItem = reportes.locator('a.dropdown-item', { hasText: 'Estadísticas' });
    await expect(statsItem).toHaveCount(1);
    await expect(statsItem).toHaveClass(/\bactive\b/);
    await expect(statsItem).toHaveAttribute('href', '/help-desk/admin/stats');
  });

  test('at least one nav entry is highlighted active on a content page', async ({ page }) => {
    await gotoHelpdesk(page, '/help-desk/admin/stats');

    // Some navbar link OR sidebar item must carry .active (server rendered).
    const activeNav = page.locator('#navbarContent a.dropdown-item.active, #navbarContent a.nav-link.active');
    expect(await activeNav.count()).toBeGreaterThan(0);

    // And the owning sidebar group should be flagged has-active for the same path.
    const activeGroup = page.locator('.app-sidebar-group.has-active');
    expect(await activeGroup.count()).toBeGreaterThan(0);
  });
});

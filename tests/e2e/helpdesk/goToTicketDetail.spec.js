// @ts-check
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

/**
 * Fix under test: the my_tickets module's destroy()/teardown on boosted
 * navigation must not throw the historical regression:
 *   "Uncaught TypeError: Cannot delete property 'goToTicketDetail' of [object Window]"
 * (deleting a non-configurable global during teardown).
 *
 * This file has two assertions:
 *   1. Even under an immediate boost-away (worst case for teardown), the
 *      specific `Cannot delete property 'goToTicketDetail'` error must NOT
 *      appear — this is the targeted fix and it must hold.
 *   2. Under normal (human-paced) navigation, leaving my-tickets must produce
 *      NO uncaught pageerror at all.
 *
 * NOTA: tras la migración a componentes server-side + HTMX, my_tickets ya no
 * rinde la lista en JS (sin loadMyTickets/showErrorState ni el viejo
 * `#ticketsList`). El render lo hace el server; el contenedor es
 * `#hd-tickets-results`. La race histórica del fetch inicial desapareció con eso.
 */
test.describe('teardown — my-tickets boosted navigation', () => {
  test('immediate boost-away never throws "Cannot delete property goToTicketDetail"', async ({ page }) => {
    /** @type {string[]} */
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(e.message || String(e)));

    await gotoHelpdesk(page, '/help-desk/user/my-tickets');
    await expect(page.locator('main[data-hd-page="user_my_tickets"]')).toBeAttached();

    // Boost away immediately (worst case for the destroy()/teardown path).
    const target = page.locator('a[hx-boost="true"][href="/help-desk/user/create"]').first();
    await expect(target).toHaveCount(1);
    await target.dispatchEvent('click');

    await expect(page).toHaveURL(/\/help-desk\/user\/create$/, { timeout: 10_000 });
    await page.waitForTimeout(500);

    const offending = errors.filter((m) => /Cannot delete property ['"]?goToTicketDetail/.test(m));
    expect(offending, `offending: ${JSON.stringify(offending)}`).toHaveLength(0);
  });

  test('paced navigation away from my-tickets produces no pageerror', async ({ page }) => {
    /** @type {string[]} */
    const pageErrors = [];
    page.on('pageerror', (e) => pageErrors.push(e.message || String(e)));

    await gotoHelpdesk(page, '/help-desk/user/my-tickets');
    await expect(page.locator('main[data-hd-page="user_my_tickets"]')).toBeAttached();

    // Wait for the initial ticket load to settle (the empty-state or cards render),
    // i.e. mimic a real user reading the page before navigating away.
    // Tras la migración a componentes server-side el contenedor es #hd-tickets-results.
    await page.locator('#hd-tickets-results').waitFor({ state: 'attached', timeout: 10_000 });
    await page.waitForTimeout(1500);

    const target = page.locator('a[hx-boost="true"][href="/help-desk/user/create"]').first();
    await target.dispatchEvent('click');
    await expect(page).toHaveURL(/\/help-desk\/user\/create$/, { timeout: 10_000 });
    await expect(page.locator('main[data-hd-page="user_create_ticket"]')).toBeAttached();
    await page.waitForTimeout(500);

    expect(pageErrors, `pageerrors: ${JSON.stringify(pageErrors)}`).toHaveLength(0);
  });
});

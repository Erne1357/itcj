// @ts-check
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

/**
 * Smoke: key helpdesk pages load (HTTP 200) and render a non-empty
 * <main data-hd-page>. Routes verified against templates.py ENDPOINT_MAP and
 * the pages/* routers.
 *
 * NOTE on secretary/department dashboards: those are gated by an organizational
 * position (department_head role / a current department), NOT by the global
 * admin bypass. A minted global-admin token without those positions gets 403 by
 * design, so they are asserted separately as role-gated (see below), not as 200.
 */

// Pages that a helpdesk admin can open (status 200 + rendered <main>).
const PAGES_200 = [
  { name: 'admin home', path: '/help-desk/admin/home', hd: 'admin_home' },
  { name: 'admin tickets-list', path: '/help-desk/admin/tickets-list', hd: 'admin_tickets_list' },
  { name: 'admin stats', path: '/help-desk/admin/stats', hd: 'admin_stats' },
  { name: 'admin analysis', path: '/help-desk/admin/analysis', hd: 'admin_analysis' },
  { name: 'admin documents', path: '/help-desk/admin/documents', hd: 'admin_documents' },
  { name: 'admin config', path: '/help-desk/admin/config', hd: 'admin_config' },
  { name: 'admin assign-tickets', path: '/help-desk/admin/assign-tickets', hd: 'admin_assign_tickets' },
  { name: 'inventory dashboard', path: '/help-desk/inventory/dashboard', hd: 'inventory_dashboard' },
  { name: 'technician dashboard', path: '/help-desk/technician/dashboard', hd: 'technician_dashboard' },
  { name: 'create ticket', path: '/help-desk/user/create', hd: 'user_create_ticket' },
  { name: 'my tickets', path: '/help-desk/user/my-tickets', hd: 'user_my_tickets' },
];

// Role/position-gated dashboards: a global admin without the org position gets 403.
const PAGES_ROLE_GATED = [
  { name: 'secretary dashboard', path: '/help-desk/secretary/' },
  { name: 'department dashboard', path: '/help-desk/department/' },
];

test.describe('smoke — key pages render', () => {
  for (const p of PAGES_200) {
    test(`${p.name} loads (200) and renders main`, async ({ page }) => {
      const resp = await page.goto(p.path, { waitUntil: 'domcontentloaded' });
      expect(resp, `no response for ${p.path}`).not.toBeNull();
      expect(resp.status(), `${p.path} status`).toBe(200);

      const main = page.locator('main[data-hd-page]');
      await expect(main).toBeVisible();

      // data-hd-page should match the expected key (sanity that the right
      // template rendered, not e.g. an error page).
      await expect(main).toHaveAttribute('data-hd-page', p.hd);

      // <main> should not be empty.
      const text = ((await main.innerText()) || '').trim();
      expect(text.length, `${p.path} main is empty`).toBeGreaterThan(0);
    });
  }

  for (const p of PAGES_ROLE_GATED) {
    test(`${p.name} is reachable or role-gated (200 or 403), never 5xx`, async ({ request }) => {
      const res = await request.get(p.path, { maxRedirects: 0 });
      // 200 if the admin happens to satisfy the org gate, 403 if not — both are
      // valid; what must NOT happen is a server error or a broken route (404/5xx).
      expect([200, 403], `${p.path} status ${res.status()}`).toContain(res.status());
    });
  }
});

// @ts-check
const { test, expect } = require('@playwright/test');

/**
 * Fix under test: routes removed or collapsed into other pages.
 *
 * Removed (must 404 — there is no technician my-assignments/team route):
 *   /help-desk/technician/my-assignments
 *   /help-desk/technician/team
 *
 * Redirected (legacy bookmarks -> Config tabs):
 *   /help-desk/admin/categories            -> 302 .../admin/config#categorias
 *   /help-desk/admin/inventory/categories  -> 302 .../admin/config#inv-cat
 *
 * Uses request.get with maxRedirects:0 so redirects are observed, not followed.
 * The authenticated cookie comes from storageState (request shares it).
 */
test.describe('deleted / redirected routes', () => {
  test('technician/my-assignments returns 404', async ({ request }) => {
    const res = await request.get('/help-desk/technician/my-assignments', { maxRedirects: 0 });
    expect([404, 405]).toContain(res.status());
  });

  test('technician/team returns 404', async ({ request }) => {
    const res = await request.get('/help-desk/technician/team', { maxRedirects: 0 });
    expect([404, 405]).toContain(res.status());
  });

  test('admin/categories redirects to config#categorias', async ({ request }) => {
    const res = await request.get('/help-desk/admin/categories', { maxRedirects: 0 });
    expect([301, 302, 303, 307, 308]).toContain(res.status());
    const loc = res.headers()['location'] || '';
    expect(loc).toContain('/help-desk/admin/config');
    expect(loc).toContain('categorias');
  });

  test('admin/inventory/categories redirects to config#inv-cat', async ({ request }) => {
    const res = await request.get('/help-desk/admin/inventory/categories', { maxRedirects: 0 });
    expect([301, 302, 303, 307, 308]).toContain(res.status());
    const loc = res.headers()['location'] || '';
    expect(loc).toContain('/help-desk/admin/config');
    expect(loc).toContain('inv-cat');
  });
});

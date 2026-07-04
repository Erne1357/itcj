// @ts-check
/**
 * D9: el cliente socket.io se sirve LOCAL (vendored); ninguna página debe
 * tocar cdn.socket.io. Regresión cross-app: helpdesk es la superficie que
 * más depende de sockets (base template + FAB).
 */
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('../helpdesk/_helpers');

test.describe('socket.io local (sin CDN)', () => {
  test('el vendored responde 200 desde nginx', async ({ request }) => {
    const res = await request.get('/static/core/js/vendor/socket.io.min.js');
    expect(res.status()).toBe(200);
    expect((await res.text()).length).toBeGreaterThan(10_000);
  });

  test('helpdesk define window.io sin requests a cdn.socket.io', async ({ page }) => {
    const cdnHits = [];
    page.on('request', (req) => {
      if (req.url().includes('cdn.socket.io')) cdnHits.push(req.url());
    });
    await gotoHelpdesk(page, '/help-desk/admin/home');
    await expect
      .poll(() => page.evaluate(() => typeof window.io), { timeout: 10_000 })
      .toBe('function');
    expect(cdnHits).toEqual([]);
  });
});

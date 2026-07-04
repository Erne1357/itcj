// @ts-check
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function hexToRgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function appColor(key) {
  const src = [
    'from itcj2.database import SessionLocal',
    'from itcj2.core.models.app import App',
    'db = SessionLocal()',
    `a = db.query(App).filter_by(key='${key}').first()`,
    "print((a.color or '#6c757d') if a else '#6c757d')",
    'db.close()',
  ].join('\n');
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  }).trim();
}

test.describe('mobile app card — DB-driven badge (F7)', () => {
  test('el fondo del icono de la tarjeta viene de core_apps.color', async ({ page }) => {
    const expected = hexToRgb(appColor('helpdesk'));
    await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });
    const icon = page.locator('.mobile-app-card[data-app-key="helpdesk"] .mobile-app-card-icon');
    await expect(icon).toBeVisible();
    const bg = await icon.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe(expected);
  });
});

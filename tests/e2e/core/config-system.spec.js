// @ts-check
/**
 * F3 — smokes de las páginas de sistema bajo ConfigPage: carga vía morph +
 * CRUD principal. Cada describe es self-cleaning por UI; afterAll limpia
 * residuos por docker exec (patrón scope-inventory.spec.js / config-roles.spec.js).
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

// ---------------------------------------------------------------- apps
const APP_KEY = 'e2e_app_' + Date.now().toString(36);

const CLEAN_APPS_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.app import App
db = SessionLocal()
try:
    for a in db.query(App).filter(App.key.like('e2e_app_%')).all():
        db.delete(a)
    db.commit()
finally:
    db.close()
`;

test.describe('config apps — ConfigPage + color/icono (C4)', () => {
  test.afterAll(() => {
    try {
      execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', CLEAN_APPS_PY],
        { encoding: 'utf8', timeout: 60_000 });
    } catch (_) { /* best-effort */ }
  });

  test('carga vía morph y expone módulo en el registry', async ({ page }) => {
    await gotoCore(page, '/itcj/config/apps');
    await expect(page.locator('#cfgMain[data-cfg-page="apps"]')).toBeAttached();
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /apps\.js/);
  });

  test('crear app con color/icono re-renderiza la fila sin recargar', async ({ page }) => {
    await gotoCore(page, '/itcj/config/apps');
    await page.locator('button[data-bs-target="#createAppModal"]').click();
    await expect(page.locator('#createAppModal')).toBeVisible();
    await page.fill('#appKey', APP_KEY);
    await page.fill('#appName', 'E2E App');
    await page.fill('#appIcon', 'bi-rocket');
    // preview del badge refleja el icono escrito
    await expect(page.locator('#appBadgePreviewIcon')).toHaveClass(/bi-rocket/);
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/authz/apps') && r.request().method() === 'POST'
    );
    await page.locator('#createAppForm button[type="submit"]').click();
    expect((await respPromise).ok()).toBeTruthy();
    await expect(page.locator('#createAppModal')).toBeHidden();
    const row = page.locator(`tr[data-app-key="${APP_KEY}"]`);
    await expect(row).toBeVisible();
    await expect(row.locator('.app-badge .bi-rocket')).toBeVisible();

    // eliminar por UI
    await row.locator('.delete-app-btn').click();
    await expect(page.locator('#deleteAppModal')).toBeVisible();
    await page.locator('#confirmDeleteApp').click();
    await expect(page.locator(`tr[data-app-key="${APP_KEY}"]`)).toHaveCount(0);
  });
});

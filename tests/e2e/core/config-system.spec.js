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

// ---------------------------------------------------------------- permissions
const PERM_CODE = 'e2e.test.api.read.subtree';

const CLEAN_PERMS_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
db = SessionLocal()
try:
    app = db.query(App).filter_by(key='helpdesk').first()
    if app:
        for p in db.query(Permission).filter(Permission.app_id == app.id,
                                              Permission.code.like('e2e.test.%')).all():
            db.delete(p)
        db.commit()
finally:
    db.close()
`;

test.describe('config permissions — ConfigPage + scope badges (C8)', () => {
  test.afterAll(() => {
    try {
      execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', CLEAN_PERMS_PY],
        { encoding: 'utf8', timeout: 60_000 });
    } catch (_) { /* best-effort */ }
  });

  test('carga vía morph, data-app-key en cfgMain', async ({ page }) => {
    await gotoCore(page, '/itcj/config/apps/helpdesk/permissions');
    await expect(page.locator('#cfgMain[data-cfg-page="permissions"]')).toBeAttached();
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-app-key', 'helpdesk');
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /permissions\.js/);
  });

  test('crear permiso .subtree muestra scope badge y aparece en asignación por rol', async ({ page }) => {
    await gotoCore(page, '/itcj/config/apps/helpdesk/permissions');
    await page.locator('button[data-bs-target="#createPermModal"]').click();
    await page.fill('#permCode', PERM_CODE);
    await page.fill('#permName', 'E2E Test Subtree');
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/perms') && r.request().method() === 'POST'
    );
    await page.locator('#createPermForm button[type="submit"]').click();
    expect((await respPromise).ok()).toBeTruthy();
    const row = page.locator(`tr[data-perm-code="${PERM_CODE}"]`);
    await expect(row).toBeVisible();
    await expect(row.locator('.scope-badge.scope-subtree')).toBeVisible();

    // eliminar por UI
    await row.locator('.delete-perm-btn').click();
    await expect(page.locator('#deletePermModal')).toBeVisible();
    await page.locator('#confirmDeletePerm').click();
    await expect(page.locator(`tr[data-perm-code="${PERM_CODE}"]`)).toHaveCount(0);
  });
});

// ---------------------------------------------------------------- themes
const THEME_NAME = 'e2e_theme_' + Date.now().toString(36);

const CLEAN_THEMES_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.theme import Theme
db = SessionLocal()
try:
    for t in db.query(Theme).filter(Theme.name.like('e2e_theme_%')).all():
        db.delete(t)
    db.commit()
finally:
    db.close()
`;

test.describe('config themes — ConfigPage + flip envelope', () => {
  test.afterAll(() => {
    try {
      execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', CLEAN_THEMES_PY],
        { encoding: 'utf8', timeout: 60_000 });
    } catch (_) { /* best-effort */ }
  });

  test('carga vía morph y lista temas (envelope success)', async ({ page }) => {
    await gotoCore(page, '/itcj/config/themes');
    await expect(page.locator('#cfgMain[data-cfg-page="themes"]')).toBeAttached();
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /themes\.js/);
    // el grid de temas se pobló desde GET /themes (success:true, .data)
    await expect(page.locator('#themesContainer')).toBeVisible();
  });

  test('crear y eliminar tema por modal', async ({ page }) => {
    await gotoCore(page, '/itcj/config/themes');
    await page.locator('button[data-bs-target="#themeModal"]').first().click();
    await expect(page.locator('#themeModal')).toBeVisible();
    await page.fill('#themeName', THEME_NAME);
    const createResp = page.waitForResponse(
      (r) => r.url().endsWith('/api/core/v2/themes') && r.request().method() === 'POST'
    );
    await page.locator('#themeForm button[type="submit"]').click();
    expect((await createResp).ok()).toBeTruthy();
    await expect(page.locator('#themeModal')).toBeHidden();
    const card = page.locator(`.theme-card:has-text("${THEME_NAME}")`).first();
    await expect(card).toBeVisible();

    // eliminar por UI (botón de basura -> modal confirm)
    await card.locator('button[title="Eliminar"]').click();
    await expect(page.locator('#deleteThemeModal')).toBeVisible();
    await page.locator('#confirmDeleteTheme').click();
    await expect(page.locator(`.theme-card:has-text("${THEME_NAME}")`)).toHaveCount(0);
  });
});

// ---------------------------------------------------------------- tasks
test.describe('config tasks — ConfigPage + flip envelope + cronstrue self-host', () => {
  test('carga vía morph, cronstrue vendored, catálogo desde envelope success', async ({ page }) => {
    await gotoCore(page, '/itcj/config/system/tasks');
    await expect(page.locator('#cfgMain[data-cfg-page="tasks"]')).toBeAttached();
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /cronstrue\.min\.js/);
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /tasks\.js/);
    // cronstrue se sirve local (no CDN) y quedó global
    await expect
      .poll(() => page.evaluate(() => typeof window.cronstrue), { timeout: 8_000 })
      .toBe('object');
    const usedCdn = await page.evaluate(() =>
      Array.from(document.querySelectorAll('script[src]'))
        .some((s) => s.src.includes('cdn.jsdelivr.net') && s.src.includes('cronstrue')));
    expect(usedCdn).toBe(false);
    // el catálogo se renderizó (o mensaje vacío) desde GET /tasks/definitions (success:true)
    await expect(page.locator('#tab-catalog table tbody')).toBeVisible();
  });

  test('historial: la paginación consume total_pages top-level', async ({ page }) => {
    await gotoCore(page, '/itcj/config/system/tasks');
    const runsResp = page.waitForResponse((r) => r.url().includes('/api/core/v2/tasks/runs'));
    await page.locator('[data-bs-target="#tab-history"]').click();
    const body = await (await runsResp).json();
    expect(body.success).toBe(true);
    expect(body).toHaveProperty('total_pages');
    expect(body).not.toHaveProperty('meta');
    await expect(page.locator('#tab-history table tbody')).toBeVisible();
  });
});

// ---------------------------------------------------------------- email
test.describe('config email — ConfigPage + API C3', () => {
  test('carga vía morph y consulta estado por la API nueva', async ({ page }) => {
    const statusReq = page.waitForRequest((r) =>
      r.url().includes('/api/core/v2/email/status'));
    await gotoCore(page, '/itcj/config/email');
    await expect(page.locator('#cfgMain[data-cfg-page="email"]')).toBeAttached();
    await expect(page.locator('#cfgMain')).toHaveAttribute('data-cfg-modules', /email\.js/);
    // el refresh de estado pega a la API C3 (no a la ruta vieja de páginas)
    const req = await statusReq;
    expect(req.url()).toContain('/api/core/v2/email/status');
  });
});

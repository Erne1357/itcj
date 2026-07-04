// @ts-check
/**
 * E2E F4: users list — presupuesto de requests, filtro app real, q canónico
 * (sobrevive full reload), badge de app con color de BD.
 * Seed/cleanup con docker exec (patrón scope-inventory.spec.js).
 * Task 3 agrega el describe de user_detail a este mismo archivo.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const BUDGET = 3; // spec §3.7: <=3 fetch/XHR a /api/core/v2/* por carga

const SEED_PY = `
import json, sys
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
from itcj2.core.models.app import App
from itcj2.core.models.role import Role
from itcj2.core.models.user_app_role import UserAppRole

db = SessionLocal()
try:
    role = db.query(Role).filter_by(name='staff').first() or db.query(Role).first()
    app = App(key='e2ecfgbadge', name='E2E CFG Badge', is_active=True,
              color='#123456', icon_class='bi-bug')
    db.add(app); db.flush()
    u_in = User(first_name='E2ECFGF', last_name='CONAPP', username='e2ecfg_conapp', is_active=True)
    u_out = User(first_name='E2ECFGF', last_name='SINAPP', username='e2ecfg_sinapp', is_active=True)
    db.add_all([u_in, u_out]); db.flush()
    db.add(UserAppRole(user_id=u_in.id, app_id=app.id, role_id=role.id))
    db.commit()
    sys.stdout.write(json.dumps({'app_key': app.key, 'in_id': u_in.id, 'out_id': u_out.id}))
finally:
    db.close()
`;

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
from itcj2.core.models.app import App
from itcj2.core.models.user_app_role import UserAppRole

db = SessionLocal()
try:
    app = db.query(App).filter_by(key='e2ecfgbadge').first()
    if app:
        for uar in db.query(UserAppRole).filter_by(app_id=app.id).all():
            db.delete(uar)
    for u in db.query(User).filter(User.username.like('e2ecfg_%')).all():
        for uar in db.query(UserAppRole).filter_by(user_id=u.id).all():
            db.delete(uar)
        db.delete(u)
    if app:
        db.delete(app)
    db.commit()
finally:
    db.close()
`;

function pyInContainer(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  });
}

/** @type {{app_key: string, in_id: number, out_id: number}} */
let seed;

test.beforeAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* nada que limpiar */ }
  seed = JSON.parse(pyInContainer(SEED_PY).trim());
  if (!seed.in_id) throw new Error('seed no devolvió ids');
});

test.afterAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* best-effort */ }
});

test.describe('users list', () => {
  test('carga con <=3 fetch/XHR a /api/core/v2/*', async ({ page }) => {
    /** @type {string[]} */
    const apiCalls = [];
    page.on('request', (req) => {
      const t = req.resourceType();
      if ((t === 'fetch' || t === 'xhr') && req.url().includes('/api/core/v2/')) {
        apiCalls.push(`${req.method()} ${new URL(req.url()).pathname}`);
      }
    });

    await gotoCore(page, '/itcj/config/users');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    expect(
      apiCalls.length,
      `presupuesto excedido (${apiCalls.length} > ${BUDGET}):\n${apiCalls.join('\n')}`
    ).toBeLessThanOrEqual(BUDGET);
  });

  test('filtro por app filtra en servidor', async ({ page }) => {
    await gotoCore(page, '/itcj/config/users');

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/users?') && r.url().includes('app=e2ecfgbadge')
    );
    await page.selectOption('#appFilter', 'e2ecfgbadge');
    const resp = await respPromise;
    expect(resp.ok()).toBeTruthy();

    const rows = page.locator('#usersTable tbody tr[data-user-id]');
    await expect(rows.filter({ hasText: 'CONAPP' })).toHaveCount(1);
    await expect(rows.filter({ hasText: 'SINAPP' })).toHaveCount(0);
    expect(page.url()).toContain('app=e2ecfgbadge');
  });

  test('búsqueda usa q y sobrevive el full reload', async ({ page }) => {
    await gotoCore(page, '/itcj/config/users');

    await page.fill('#searchUsers', 'e2ecfg_sinapp');
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/users?') && r.url().includes('q=e2ecfg_sinapp')
    );
    await page.locator('#searchButton').click();
    await respPromise;

    const rows = page.locator('#usersTable tbody tr[data-user-id]');
    await expect(rows.filter({ hasText: 'SINAPP' })).toHaveCount(1);
    expect(page.url()).toContain('q=e2ecfg_sinapp');

    // full reload: la page route lee q → el filtro NO se pierde (unificación)
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#usersTable tbody tr[data-user-id]').filter({ hasText: 'SINAPP' })).toHaveCount(1);
    await expect(page.locator('#usersTable tbody tr[data-user-id]').filter({ hasText: 'CONAPP' })).toHaveCount(0);
  });

  test('badge de app usa el color de BD (C4/C8)', async ({ page }) => {
    await gotoCore(page, '/itcj/config/users?q=e2ecfg_conapp');

    const badge = page.locator(`#userApps_${seed.in_id} .app-badge`, { hasText: 'e2ecfgbadge' });
    await expect(badge).toBeVisible();
    // El color viaja como custom property --app-badge-color (C8), no como clase bg-{app}
    await expect(badge).toHaveAttribute('style', /--app-badge-color:\s*#123456/);
    // La clase hardcoded vieja ya no se emite
    await expect(page.locator(`#userApps_${seed.in_id} .bg-e2ecfgbadge`)).toHaveCount(0);
  });
});

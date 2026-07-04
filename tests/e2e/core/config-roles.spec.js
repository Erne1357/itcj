// @ts-check
/**
 * F2 — piloto roles: CRUD por modal bajo el patrón ConfigPage.
 * Crea un rol e2e_role_<ts> por UI y lo elimina por UI (self-cleaning);
 * afterAll limpia residuos vía docker exec (patrón scope-inventory.spec.js).
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const ROLE_NAME = 'e2e_role_' + Date.now().toString(36);

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.role import Role
db = SessionLocal()
try:
    for r in db.query(Role).filter(Role.name.like('e2e_role_%')).all():
        db.delete(r)
    db.commit()
finally:
    db.close()
`;

test.afterAll(() => {
  try {
    execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', CLEAN_PY], {
      encoding: 'utf8', timeout: 60_000,
    });
  } catch (_) { /* best-effort */ }
});

test.describe('config roles — piloto ConfigPage', () => {
  test('crear y eliminar rol vía modales (módulo del registry)', async ({ page }) => {
    await gotoCore(page, '/itcj/config/roles');
    await expect(page.locator('#cfgMain[data-cfg-page="roles"]')).toBeAttached();

    // crear
    await page.locator('button[data-bs-target="#createRoleModal"]').click();
    await expect(page.locator('#createRoleModal')).toBeVisible();
    await page.fill('#roleName', ROLE_NAME);
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/api/core/v2/authz/roles') && r.request().method() === 'POST'
    );
    await page.locator('#createRoleForm button[type="submit"]').click();
    const resp = await respPromise;
    expect(resp.ok()).toBeTruthy();
    await expect(page.locator('#createRoleModal')).toBeHidden();
    // qualify con `div`: el botón .delete-role-btn también lleva data-role-name
    // (el handler de borrado lee btn.dataset.roleName), así que el selector
    // desnudo casaría 2 nodos y rompería el strict-mode de Playwright.
    await expect(page.locator(`div[data-role-name="${ROLE_NAME}"]`)).toBeVisible();

    // eliminar (delegación document → AppModal.confirm, sin modal bespoke)
    await page.locator(`div[data-role-name="${ROLE_NAME}"] [data-bs-toggle="dropdown"]`).click();
    await page.locator(`div[data-role-name="${ROLE_NAME}"] .delete-role-btn`).click();
    const confirmDialog = page.locator('.modal.show', { hasText: 'Eliminar rol' });
    await expect(confirmDialog).toBeVisible();
    await confirmDialog.getByRole('button', { name: 'Eliminar' }).click();
    await expect(page.locator(`div[data-role-name="${ROLE_NAME}"]`)).toHaveCount(0);
  });

  test('validación del nombre marca is-invalid', async ({ page }) => {
    await gotoCore(page, '/itcj/config/roles');
    await page.locator('button[data-bs-target="#createRoleModal"]').click();
    await page.fill('#roleName', 'Nombre Inválido!');
    await expect(page.locator('#roleName')).toHaveClass(/is-invalid/);
  });
});

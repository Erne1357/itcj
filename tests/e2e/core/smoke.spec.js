// @ts-check
/**
 * Smoke del panel /itcj/config con el harness core (gotoCore, contrato C9).
 * Valida que el storageState del global-setup (criterio dual de Task 1)
 * renderiza el shell de configuración — NO el login (302) ni la página 403.
 */
const { test, expect } = require('@playwright/test');
const { gotoCore, CORE_SHELL } = require('./_helpers');

test.describe('core config — smoke', () => {
  test('panel principal renderiza el shell', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    await expect(page).toHaveURL(/\/itcj\/config/);
    await expect(page.locator(CORE_SHELL).first()).toBeVisible();
  });

  test('página de usuarios renderiza la tabla', async ({ page }) => {
    await gotoCore(page, '/itcj/config/users');
    await expect(page.locator('#usersTable')).toBeVisible();
  });
});

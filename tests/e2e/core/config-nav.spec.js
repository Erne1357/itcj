// @ts-check
/**
 * F2 — contrato de navegación del shell config (spec e2e 1 y 8):
 *   · morph inter-página sin full reload (window.__marker sobrevive; una
 *     recarga real lo borra y agrega una entrada de navigation timing)
 *   · CSS por-página inyectado por head-support en navegación boosted
 *   · back/forward via htmx:historyRestore re-activa la página sin recargar
 *   · navegar con modal abierto NO deja .modal-backdrop ni body.modal-open
 *     (ambas rutas: ConfigPage.navigate() y link boosteado del sidebar)
 */
const { test, expect } = require('@playwright/test');
const { gotoCore } = require('./_helpers');

async function markLoad(page) {
  const id = 'cfg-' + Math.random().toString(36).slice(2);
  await page.evaluate((v) => { /** @type {any} */ (window).__marker = v; }, id);
  return id;
}
const liveMarker = (page) => page.evaluate(() => /** @type {any} */ (window).__marker);
const navEntries = (page) =>
  page.evaluate(() => performance.getEntriesByType('navigation').length);

test.describe('config shell — navegación morph', () => {
  test('index → roles con hx-boost: morfea sin recarga y el sidebar llega activo', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const id = await markLoad(page);
    expect(await navEntries(page)).toBe(1);

    const link = page.locator('a[hx-boost="true"][href="/itcj/config/roles"]').first();
    await expect(link).toHaveCount(1);
    await link.dispatchEvent('click');

    await expect(page).toHaveURL(/\/itcj\/config\/roles$/);
    await expect(page.locator('#cfgMain[data-cfg-page="roles"]')).toBeAttached();
    expect(await liveMarker(page)).toBe(id);       // sin recarga completa
    expect(await navEntries(page)).toBe(1);        // ni entrada de navegación nueva
    // active server-rendered: llega en el body morfeado
    await expect(page.locator('a.config-nav-link[href="/itcj/config/roles"]')).toHaveClass(/active/);
  });

  test('CSS por-página: roles.css entra al <head> vía head-support', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const hasRolesCss = () => page.evaluate(() =>
      Array.from(document.head.querySelectorAll('link[rel="stylesheet"]'))
        .some((l) => (l.getAttribute('href') || '').includes('css/config/system/roles.css')));
    expect(await hasRolesCss()).toBe(false);

    await page.locator('a[hx-boost="true"][href="/itcj/config/roles"]').first().dispatchEvent('click');
    await expect(page.locator('#cfgMain[data-cfg-page="roles"]')).toBeAttached();
    await expect
      .poll(hasRolesCss, { timeout: 8_000, message: 'roles.css no fue inyectado por head-support' })
      .toBe(true);
  });

  test('back/forward (htmx:historyRestore) re-activa páginas sin recargar', async ({ page }) => {
    await gotoCore(page, '/itcj/config');
    const id = await markLoad(page);
    await page.locator('a[hx-boost="true"][href="/itcj/config/roles"]').first().dispatchEvent('click');
    await expect(page).toHaveURL(/\/itcj\/config\/roles$/);

    await page.evaluate(() => history.back());
    await expect(page).toHaveURL(/\/itcj\/config$/);
    expect(await liveMarker(page)).toBe(id);       // restore = swap, no reload
    await expect(page.locator('#cfgMain[data-cfg-page="index"]')).toBeAttached();

    await page.evaluate(() => history.forward());
    await expect(page).toHaveURL(/\/itcj\/config\/roles$/);
    expect(await liveMarker(page)).toBe(id);
    await expect(page.locator('#cfgMain[data-cfg-page="roles"]')).toBeAttached();
  });

  test('ConfigPage.navigate() con modal abierto: morfea y limpia backdrop', async ({ page }) => {
    await gotoCore(page, '/itcj/config/roles');
    const id = await markLoad(page);
    await page.locator('button[data-bs-target="#createRoleModal"]').click();
    await expect(page.locator('#createRoleModal')).toBeVisible();
    await expect(page.locator('.modal-backdrop')).toHaveCount(1);

    await page.evaluate(() => window.ConfigPage.navigate('/itcj/config'));
    await expect(page).toHaveURL(/\/itcj\/config$/);
    expect(await liveMarker(page)).toBe(id);       // roles→index: ambas migradas → morph
    await expect(page.locator('.modal-backdrop')).toHaveCount(0);
    const bodyState = await page.evaluate(() => ({
      modalOpen: document.body.classList.contains('modal-open'),
      overflow: document.body.style.overflow || '',
    }));
    expect(bodyState.modalOpen).toBe(false);
    expect(bodyState.overflow).toBe('');
  });

  test('link boosteado con modal abierto: también limpia backdrop', async ({ page }) => {
    await gotoCore(page, '/itcj/config/roles');
    await page.locator('button[data-bs-target="#createRoleModal"]').click();
    await expect(page.locator('#createRoleModal')).toBeVisible();

    // dispatch directo: el backdrop taparía un click físico sobre el sidebar
    await page.locator('a[hx-boost="true"][href="/itcj/config"]').first().dispatchEvent('click');
    await expect(page).toHaveURL(/\/itcj\/config$/);
    await expect(page.locator('.modal-backdrop')).toHaveCount(0);
    expect(await page.evaluate(() => document.body.classList.contains('modal-open'))).toBe(false);
  });
});

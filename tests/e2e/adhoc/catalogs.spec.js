// @ts-check
/**
 * catalogs — CRUD completo de un catálogo de solo-nombre (categorías de
 * documento), que es la macro `catalog_page()` + `shared/catalog-crud.js`
 * compartida por las cuatro pantallas de catálogo (plan §6.5).
 *
 * Se verifica alta MASIVA (con deduplicación), edición EN LÍNEA y borrado con
 * el **modal de confirmación de Bootstrap**, más las dos cosas que el legacy
 * hacía mal en esta misma pantalla:
 *
 *  1. Ni un solo `window.confirm` / `alert` / `prompt` nativo (el legacy tenía
 *     14 en toda la app; el borrado de catálogo era uno de ellos). El espía se
 *     instala con `addInitScript`, o sea ANTES de que corra un solo script de
 *     la página.
 *  2. Un nombre repetido ya no tumba el lote entero: se reporta como omitido
 *     (el legacy insertaba en bloque contra un UNIQUE y el `IntegrityError`
 *     revertía todo, respondiendo con un redirect "exitoso").
 */
const { test, expect } = require('@playwright/test');
const { E2E, gotoAdhoc, cleanupAdhoc, trapNativeDialogs } = require('./_helpers');

const PAGE = '/adhoc/documentos/categorias';
const TABLE = '#adhoc-catalog-document-categories';
const MODAL = '#adhoc-catalog-modal-document-categories';

const NAMES = [`${E2E}cat_alfa`, `${E2E}cat_beta`, `${E2E}cat_gamma`];
const RENAMED = `${E2E}cat_alfa_renombrada`;

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => cleanupAdhoc());
test.afterAll(() => cleanupAdhoc());

/** Fila del catálogo por nombre exacto de la celda `name`. */
function rowByName(page, name) {
  return page.locator(`${TABLE} tbody tr[data-id]`).filter({
    has: page.locator(`td[data-adhoc-cell="name"]:text-is("${name}")`),
  });
}

test('alta masiva de tres categorías', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, PAGE);
  await expect(page.locator('[data-adhoc-catalog]')).toBeVisible();

  await page.locator('[data-adhoc-catalog-new]').click();
  const modal = page.locator(MODAL);
  await expect(modal).toBeVisible();

  await modal.locator('[data-adhoc-catalog-qty]').selectOption('3');
  const inputs = modal.locator('[data-adhoc-new-name]');
  await expect(inputs).toHaveCount(3);
  for (let i = 0; i < NAMES.length; i++) await inputs.nth(i).fill(NAMES[i]);

  const created = page.waitForResponse(
    (r) => r.url().includes('/document-categories') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-catalog-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(201);
  expect((await resp.json()).total).toBe(3);

  for (const name of NAMES) await expect(rowByName(page, name)).toHaveCount(1);
  await expect(modal).not.toBeVisible();

  expect(await readDialogs()).toEqual([]);
  // @ts-ignore
  expect(page.__sawRealDialog).toBeFalsy();
});

test('un nombre repetido se omite, no tumba el lote', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, PAGE);

  await page.locator('[data-adhoc-catalog-new]').click();
  const modal = page.locator(MODAL);
  await expect(modal).toBeVisible();
  await modal.locator('[data-adhoc-catalog-qty]').selectOption('2');

  const inputs = modal.locator('[data-adhoc-new-name]');
  await inputs.nth(0).fill(NAMES[0]); // ya existe
  await inputs.nth(1).fill(`${E2E}cat_delta`); // nueva

  const created = page.waitForResponse(
    (r) => r.url().includes('/document-categories') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-catalog-save]').click();
  const body = await (await created).json();
  expect(body.total).toBe(1);
  expect(body.skipped_count).toBe(1);

  await expect(rowByName(page, `${E2E}cat_delta`)).toHaveCount(1);
  await expect(rowByName(page, NAMES[0])).toHaveCount(1); // sigue habiendo UNA

  expect(await readDialogs()).toEqual([]);
});

test('edición en línea de una categoría', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, PAGE);

  // El locator por nombre deja de resolver en cuanto empieza la edición (la
  // celda cambia su texto por un <input>), así que se ancla por `data-id`.
  await expect(rowByName(page, NAMES[0])).toHaveCount(1);
  const id = await rowByName(page, NAMES[0]).getAttribute('data-id');
  const row = page.locator(`${TABLE} tbody tr[data-id="${id}"]`);

  await row.locator('[data-adhoc-action="edit"]').click();

  const input = row.locator('[data-adhoc-edit-input]');
  await expect(input).toBeVisible();
  await expect(input).toHaveValue(NAMES[0]);
  await input.fill(RENAMED);

  const patched = page.waitForResponse(
    (r) => r.url().includes('/document-categories/') && r.request().method() === 'PATCH'
  );
  await row.locator('[data-adhoc-action="save"]').click();
  expect((await patched).status()).toBe(200);

  await expect(rowByName(page, RENAMED)).toHaveCount(1);
  await expect(rowByName(page, NAMES[0])).toHaveCount(0);

  expect(await readDialogs()).toEqual([]);
});

test('borrado con el modal de confirmación (cancelar no borra, confirmar sí)', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, PAGE);

  const row = rowByName(page, NAMES[1]);
  await expect(row).toHaveCount(1);

  // — cancelar —
  await row.locator('[data-adhoc-action="delete"]').click();
  let dialog = page.locator('.modal.show').filter({
    has: page.locator('[data-adhoc-role="confirm"]'),
  });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Eliminar categoría');
  await expect(dialog).toContainText(NAMES[1]);
  await dialog.getByRole('button', { name: 'Cancelar' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(rowByName(page, NAMES[1])).toHaveCount(1);

  // — confirmar —
  await rowByName(page, NAMES[1]).locator('[data-adhoc-action="delete"]').click();
  dialog = page.locator('.modal.show').filter({
    has: page.locator('[data-adhoc-role="confirm"]'),
  });
  await expect(dialog).toBeVisible();

  const deleted = page.waitForResponse(
    (r) => r.url().includes('/document-categories/') && r.request().method() === 'DELETE'
  );
  await dialog.locator('[data-adhoc-role="confirm"]').click();
  expect((await deleted).status()).toBe(200);

  await expect(rowByName(page, NAMES[1])).toHaveCount(0);
  await expect(rowByName(page, NAMES[2])).toHaveCount(1); // las demás siguen

  // NINGÚN diálogo nativo en todo el CRUD.
  expect(await readDialogs()).toEqual([]);
  // @ts-ignore
  expect(page.__sawRealDialog).toBeFalsy();
});

test('el JS de adhoc no invoca diálogos nativos ni siquiera al cargar', async ({ page }) => {
  // Barrido de las cuatro pantallas de catálogo: comparten el mismo módulo,
  // así que si una resucitara confirm() lo haría en todas.
  const readDialogs = await trapNativeDialogs(page);
  for (const url of [
    '/adhoc/documentos/categorias',
    '/adhoc/documentos/clasificaciones',
    '/adhoc/incidencias/categorias',
    '/adhoc/programas/categorias',
  ]) {
    await gotoAdhoc(page, url);
    await expect(page.locator('[data-adhoc-catalog]')).toBeVisible();
    expect(await readDialogs(), `${url} abrió un diálogo nativo`).toEqual([]);
  }
});

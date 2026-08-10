// @ts-check
// Verificación de inventario — bloque de asignación a usuario (nuevo).
// El modal de verificar (#modal-verify) ahora también permite confirmar/cambiar
// la asignación a usuario del equipo (además de ubicación/estado/marca/modelo/
// series/grupo/specs), con la opción de crear un usuario inactivo en el acto.
// Ver api/inventory/verification.py::verify_item + verification.js.
// Aserciones deterministas: si la BD de prueba no tiene equipos (o el
// departamento del primero no tiene usuarios), el test se salta en vez de
// asumir datos.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const VERIF_PAGE = '/help-desk/inventory/verification';

test.describe('verification — asignación a usuario en el modal Verificar', () => {

  /** Abre la página, hace click en el botón "Verificar" de la primera fila y
   * espera a que el select de asignación termine de cargar (habilitado).
   * Retorna el locator del select, o null si no hay filas para probar. */
  async function openVerifyModalOnFirstRow(page) {
    await gotoHelpdesk(page, VERIF_PAGE);

    const results = page.locator('#hd-verif-results');
    const verifyBtn = results.locator('[data-action="verify"]').first();
    if ((await verifyBtn.count()) === 0) return null;

    const itemId = await verifyBtn.getAttribute('data-item-id');
    await verifyBtn.click();

    const modal = page.locator('#modal-verify');
    await expect(modal).toBeVisible();

    const select = page.locator('#verif-assigned-user');
    await expect(select).toBeVisible();
    await expect(select).toBeEnabled({ timeout: 8000 });

    return { select, itemId };
  }

  test('el modal muestra el bloque "Asignado a" con el valor actual preseleccionado', async ({ page }) => {
    const ctx = await openVerifyModalOnFirstRow(page);
    test.skip(ctx === null, 'Sin equipos en la BD de prueba para verificar');

    const { select, itemId } = ctx;
    const selectedValue = await select.inputValue();

    const itemResp = await page.request.get(`/api/help-desk/v2/inventory/items/${itemId}`);
    expect(itemResp.status()).toBe(200);
    const itemJson = await itemResp.json();
    const expected = itemJson.data.assigned_to_user_id ? String(itemJson.data.assigned_to_user_id) : '';
    expect(selectedValue).toBe(expected);
  });

  test('cambiar la asignación agrega "asignación" al aviso "Se actualizará…"', async ({ page }) => {
    const ctx = await openVerifyModalOnFirstRow(page);
    test.skip(ctx === null, 'Sin equipos en la BD de prueba para verificar');

    const { select } = ctx;
    const currentValue = await select.inputValue();
    const options = await select.locator('option').all();
    let targetValue = null;
    for (const opt of options) {
      const v = await opt.getAttribute('value');
      if (v !== currentValue) { targetValue = v; break; }
    }
    test.skip(targetValue === null, 'El departamento del equipo no tiene otro usuario para probar el cambio');

    await select.selectOption(targetValue);

    const alert = page.locator('#changes-alert');
    await expect(alert).toBeVisible();
    await expect(page.locator('#changes-msg')).toContainText('asignación');
  });

  test('el botón "Crear usuario inactivo" aparece (admin del storageState, tiene el permiso)', async ({ page }) => {
    const ctx = await openVerifyModalOnFirstRow(page);
    test.skip(ctx === null, 'Sin equipos en la BD de prueba para verificar');

    await expect(page.locator('#btn-create-inactive-user')).toBeVisible();
    await expect(page.locator('#createInactiveUserModal')).toBeAttached();
    await expect(page.locator('#createInactiveUserModal')).toBeHidden();
  });

  test('la tabla de resultados incluye la columna "Asignado a"', async ({ page }) => {
    await gotoHelpdesk(page, VERIF_PAGE);

    const results = page.locator('#hd-verif-results');
    const hasTable = (await results.locator('#verif-table').count()) > 0;
    test.skip(!hasTable, 'Sin equipos en la BD de prueba (tabla vacía)');

    await expect(results.locator('#verif-table thead th', { hasText: 'Asignado a' })).toHaveCount(1);
  });
});

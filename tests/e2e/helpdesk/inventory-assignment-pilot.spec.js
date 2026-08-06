// @ts-check
// Migración de inventory/assignment a Bootstrap 5 (isla de-jQuery + tokens).
// assign_equipment y my_equipment NO tienen lista simple paginada → se conservan
// como islas (fetch client-side), pero se de-jQuery-zaron por completo: los modales
// usan bootstrap.Modal (BS5), las tabs son nativas (data-bs-toggle), y no queda
// ningún atributo BS4 (data-toggle/dismiss/target) ni estilo inline.
// Aserciones DETERMINISTAS (no dependen de datos de BD): el shell server-side, los
// modales (siempre en el DOM), los enlaces internos boosteables, y abrir/cerrar un
// modal BS5. Ambas páginas son role-gated → se autentica como admin real (sin bypass).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const ASSIGN_PAGE = '/help-desk/inventory/assign';
const MY_EQUIPMENT_PAGE = '/help-desk/inventory/my-equipment';
const ITEMS_PAGE = '/help-desk/inventory/items';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('pilot — inventory/assignment (isla BS5 de-jQuery + tokens)', () => {

  // ────────────────────────────── assign_equipment ──────────────────────────────
  test('assign: shell server-side + 0 atributos BS4 + enlace interno boosteable', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, ASSIGN_PAGE);

    // Página correcta (controller HelpdeskPage).
    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_assignment_assign_equipment'
    );

    // Los 3 modales están en el DOM (server-rendered) y ocultos.
    for (const id of ['#assignModal', '#unassignModal', '#selectGroupEquipmentModal']) {
      await expect(page.locator(id)).toBeAttached();
      await expect(page.locator(id)).toBeHidden();
    }

    // Cero atributos BS4 en toda la página (shell BS5 nativo incluido).
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);

    // El enlace "Inventario" de la propia página apunta a una migrada → lleva
    // hx-boost. Se acota a <main> porque el navbar (desktop + móvil) también
    // enlaza ahí desde que el item "Ver Inventario" dejó de estar muerto.
    await expect(
      page.locator(`main[data-hd-page] a[href="${ITEMS_PAGE}"]`)
    ).toHaveAttribute('hx-boost', 'true');
  });

  test('assign: modal BS5 abre y cierra sin jQuery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, ASSIGN_PAGE);

    const modal = page.locator('#assignModal');
    await expect(modal).toBeHidden();

    // Apertura via API de Bootstrap 5 (determinista, sin depender de datos).
    await page.evaluate(() => {
      bootstrap.Modal.getOrCreateInstance(document.getElementById('assignModal')).show();
    });
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    // Cierre por el botón BS5 .btn-close (data-bs-dismiss).
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });

  test('assign: navegación interna (Inventario) es boost, sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, ASSIGN_PAGE);

    await page.locator(`main[data-hd-page] a[href="${ITEMS_PAGE}"]`).click();

    // Morph hacia la página de items (migrada) sin recargar el documento.
    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_items_items_list'
    );
    await expect.poll(() => new URL(page.url()).pathname).toBe(ITEMS_PAGE);

    // El marcador sobrevive → no hubo navegación completa (full reload lo borraría).
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);
  });

  // ─────────────────────────────── my_equipment ────────────────────────────────
  test('my-equipment: shell server-side + 0 atributos BS4 + tabs BS5 + enlace boosteable', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, MY_EQUIPMENT_PAGE);

    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_assignment_my_equipment'
    );

    // Modal de detalle en el DOM y oculto.
    await expect(page.locator('#equipmentDetailModal')).toBeAttached();
    await expect(page.locator('#equipmentDetailModal')).toBeHidden();

    // Cero atributos BS4; las tabs del modal usan data-bs-toggle (BS5).
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);
    await expect(page.locator('#equipmentTabs a[data-bs-toggle="tab"]')).toHaveCount(4);

    // El botón "Crear Ticket" (empty state) apunta a una página migrada → hx-boost.
    await expect(page.locator('#empty-state a[href="/help-desk/user/create"]')).toHaveAttribute('hx-boost', 'true');
  });

  test('my-equipment: modal de detalle BS5 abre y cierra sin jQuery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, MY_EQUIPMENT_PAGE);

    const modal = page.locator('#equipmentDetailModal');
    await expect(modal).toBeHidden();

    await page.evaluate(() => {
      bootstrap.Modal.getOrCreateInstance(document.getElementById('equipmentDetailModal')).show();
    });
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });
});

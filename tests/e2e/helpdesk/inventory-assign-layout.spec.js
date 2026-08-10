// @ts-check
// Layout de inventory/assignment/assign_equipment: el panel izquierdo (Usuarios)
// se estiraba junto al derecho (Equipos) por el h-100 compartido dentro de un
// .row sin align-items-start, y los 3 contenedores del panel derecho
// (#assigned-equipment-list, #individual-equipment-list, #groups-list) no
// tenían tope de altura → doble scroll (página + lista). Fix: ambos paneles
// son position:sticky + max-height: calc(100vh - --hd-sticky-top), con el tope
// de cada lista recalculado en JS (assign_equipment.js::applyAssignLayout).
// También se corrigió el desfase visual del selector de depto vs los botones
// del header, y el parpadeo de página completa al pulsar "Actualizar"
// (refreshData ya no llama showLoading()/hideLoading()).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const ASSIGN_PAGE = '/help-desk/inventory/assign';
const ADMIN_USER_ID = 7676;    // admin real (roles vía BD, sin bypass) — mismo user que el pilot
// department_head con departamento propio (22 — Recursos Materiales y Servicios,
// 7 posiciones activas + 38 equipos de inventario): a diferencia del admin (que
// no tiene dpto propio y depende de qué depto caiga primero al ordenar
// alfabéticamente vía el selector cross-dept), este usuario SIEMPRE aterriza en
// un departamento con datos reales — necesario para los tests de layout que
// requieren un usuario seleccionable en #users-list.
const DEPT_HEAD_USER_ID = 7649;

test.use({ viewport: { width: 1920, height: 1080 } });

test.describe('assign_equipment — layout sin doble scroll (1920x1080)', () => {

  // loadInitialData() es async (me-scope → user/me/department → users/equipment/
  // groups/categories en paralelo): #main-content sigue d-none un momento
  // después de que <main data-hd-page> ya está visible. Sin esta espera,
  // isVisible() se ejecuta demasiado pronto y todo se reporta como "sin datos".
  async function waitForMainContent(page) {
    return page.locator('#main-content').waitFor({ state: 'visible', timeout: 8000 })
      .then(() => true)
      .catch(() => false);
  }

  // Helper: navega, espera a que #main-content se revele (hay departamento de
  // inventario para este usuario) y selecciona el primer usuario de la lista.
  // Si no hay datos (departamento sin usuarios, o el usuario de prueba no
  // tiene dpto de inventario), la llamada retorna null y el test que la usa
  // debe hacer test.skip().
  async function gotoAndSelectFirstUser(page) {
    await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
    const mainVisible = await waitForMainContent(page);
    if (!mainVisible) return null;

    const userCards = page.locator('#users-list .user-card');
    const count = await userCards.count();
    if (count === 0) return null;

    await userCards.first().click();
    await expect(page.locator('#user-equipment-section')).not.toHaveClass(/d-none/);
    // Deja un frame para que applyAssignLayout() (síncrono, pero disparado
    // justo tras el render) termine de aplicar los max-height inline.
    await page.waitForTimeout(100);
    return count;
  }

  test('contratos base siguen verdes tras el retoque de layout', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, ASSIGN_PAGE);

    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_assignment_assign_equipment'
    );
    for (const id of ['#assignModal', '#unassignModal', '#selectGroupEquipmentModal']) {
      await expect(page.locator(id)).toBeAttached();
      await expect(page.locator(id)).toBeHidden();
    }
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);
    await expect(
      page.locator('main[data-hd-page] a[href="/help-desk/inventory/items"]')
    ).toHaveAttribute('hx-boost', 'true');
  });

  test('con un usuario seleccionado, ninguna lista obliga a scrollear la página', async ({ page }) => {
    const count = await gotoAndSelectFirstUser(page);
    test.skip(count === null, 'Usuario de prueba sin datos de inventario (sin depto o sin usuarios)');

    // 1) La página completa cabe en el viewport: no hace falta un segundo
    //    scroll para llegar al final de ninguna de las dos tarjetas.
    const overflow = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      innerHeight: window.innerHeight,
    }));
    expect(overflow.scrollHeight).toBeLessThanOrEqual(overflow.innerHeight + 4);

    // 2) Cada lista con contenido scrollea DENTRO de sí misma (overflow-y
    //    scrolleable) y su borde inferior cae dentro del viewport.
    const viewportH = await page.evaluate(() => window.innerHeight);
    for (const id of ['#users-list', '#assigned-equipment-list', '#individual-equipment-list']) {
      const info = await page.locator(id).evaluate((el) => ({
        overflowY: getComputedStyle(el).overflowY,
        bottom: el.getBoundingClientRect().bottom,
      }));
      expect(['auto', 'scroll']).toContain(info.overflowY);
      expect(info.bottom).toBeLessThanOrEqual(viewportH + 4);
    }
  });

  test('los 3 contenedores del panel derecho tienen tope de altura (no ilimitado)', async ({ page }) => {
    const count = await gotoAndSelectFirstUser(page);
    test.skip(count === null, 'Usuario de prueba sin datos de inventario (sin depto o sin usuarios)');

    for (const id of ['#assigned-equipment-list', '#individual-equipment-list', '#groups-list']) {
      const maxHeight = await page.locator(id).evaluate((el) => getComputedStyle(el).maxHeight);
      expect(maxHeight, `${id} debe tener un max-height finito`).not.toBe('none');
    }
  });

  test('el header no desfasa: selector de depto y botones comparten línea base', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, ASSIGN_PAGE);

    // Se fuerza visible el selector (algunos usuarios no tienen permiso
    // cross-dept y el wrapper queda d-none) para medir el caso reportado
    // de forma determinista, sin depender de los permisos del usuario de prueba.
    await page.evaluate(() => {
      document.getElementById('dept-selector-wrapper')?.classList.remove('d-none');
    });

    const tops = await page.evaluate(() => {
      const rectTop = (el) => el.getBoundingClientRect().top;
      return {
        wrapper: rectTop(document.getElementById('dept-selector-wrapper')),
        select: rectTop(document.getElementById('dept-selector')),
        refresh: rectTop(document.getElementById('btn-refresh-assign')),
        inventario: rectTop(document.querySelector('main[data-hd-page] a[href="/help-desk/inventory/items"]')),
      };
    });

    expect(Math.abs(tops.wrapper - tops.refresh)).toBeLessThanOrEqual(4);
    expect(Math.abs(tops.select - tops.refresh)).toBeLessThanOrEqual(4);
    expect(Math.abs(tops.refresh - tops.inventario)).toBeLessThanOrEqual(4);
  });

  test('"Actualizar" no vacía #main-content ni parpadea la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
    const mainVisible = await waitForMainContent(page);
    test.skip(!mainVisible, 'Usuario de prueba sin datos de inventario (sin depto)');

    // Se retrasa una de las llamadas que dispara refreshData() para poder
    // observar el estado "a medio refresh" sin condición de carrera.
    await page.route('**/api/core/v2/departments/*/users*', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.continue();
    });

    const refreshBtn = page.locator('#btn-refresh-assign');
    await refreshBtn.click();

    // A medio refresh: el contenido sigue montado (nunca se cae a
    // #loading-state) y el feedback es el spinner local del botón.
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page.locator('#loading-state')).toBeHidden();
    await expect(refreshBtn).toBeDisabled();
    await expect(refreshBtn.locator('.hd-btn-spinner')).toBeVisible();

    // Al terminar: el botón se reactiva y el contenido nunca se desmontó.
    await expect(refreshBtn).toBeEnabled({ timeout: 5000 });
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page.locator('#loading-state')).toBeHidden();
  });
});

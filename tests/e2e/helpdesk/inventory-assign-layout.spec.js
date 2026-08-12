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

    // 2) Cada panel scrollea DENTRO de su propia región y su borde inferior
    //    cae dentro del viewport. Es UNA región por panel: cuando eran dos
    //    apiladas (asignados + disponibles) competían por el alto del mismo
    //    panel y la de abajo acababa recortada por su overflow:hidden.
    const viewportH = await page.evaluate(() => window.innerHeight);
    for (const id of ['#users-list', '#equip-panel > .card-body']) {
      const info = await page.locator(id).evaluate((el) => ({
        overflowY: getComputedStyle(el).overflowY,
        bottom: el.getBoundingClientRect().bottom,
      }));
      expect(['auto', 'scroll']).toContain(info.overflowY);
      expect(info.bottom).toBeLessThanOrEqual(viewportH + 4);
    }
  });

  // Este test exigia antes que las 3 listas internas tuvieran max-height propio.
  // Ese era justamente el diseno que rompia la vista: tres topes calculados
  // contra el viewport dentro de un panel ya recortado a una caja menor. El
  // contrato correcto es el contrario: el tope lo tiene el PANEL, y adentro
  // reparte flexbox.
  test('el tope de altura vive en el panel, no en cada lista interna', async ({ page }) => {
    const count = await gotoAndSelectFirstUser(page);
    test.skip(count === null, 'Usuario de prueba sin datos de inventario (sin depto o sin usuarios)');

    for (const id of ['#users-panel', '#equip-panel']) {
      const maxHeight = await page.locator(id).evaluate((el) => getComputedStyle(el).maxHeight);
      expect(maxHeight, `${id} debe tener un max-height finito`).not.toBe('none');
      expect(parseFloat(maxHeight)).toBeGreaterThan(0);
    }

    // Y ningun panel puede esconder contenido inalcanzable tras su overflow:hidden.
    const inalcanzable = await page.evaluate(() => ({
      izq: (() => { const e = document.querySelector('#users-panel'); return e.scrollHeight - e.clientHeight; })(),
      der: (() => { const e = document.querySelector('#equip-panel'); return e.scrollHeight - e.clientHeight; })(),
    }));
    expect(inalcanzable.izq).toBe(0);
    expect(inalcanzable.der).toBe(0);
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

// En móvil las dos columnas se apilan. Ambos paneles siguen siendo sticky, así
// que hay que confirmar que ninguno se "pega" encima del otro ni deja la lista
// más alta que el viewport (el tope se calcula en vivo, y en el flujo apilado
// las posiciones naturales son muy distintas a las de desktop).
test.describe('assign_equipment — apilado en móvil (390x844)', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('ningún panel excede el viewport ni tapa al otro', async ({ page }) => {
    await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
    await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 });

    const firstUser = page.locator('#users-list .user-card').first();
    test.skip((await firstUser.count()) === 0, 'sin usuarios en el departamento de prueba');
    await firstUser.click();
    await expect(page.locator('#user-equipment-section')).toBeVisible();

    const boxes = await page.evaluate(() => {
      const pick = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { top: r.top, height: r.height, maxHeight: getComputedStyle(el).maxHeight };
      };
      return {
        users: pick('#users-panel'),
        equip: pick('#equip-panel'),
        viewport: window.innerHeight,
      };
    });

    expect(boxes.users).not.toBeNull();
    expect(boxes.equip).not.toBeNull();
    // Ningún panel más alto que la ventana: si lo fuera, volvería el doble scroll.
    expect(boxes.users.height).toBeLessThanOrEqual(boxes.viewport);
    expect(boxes.equip.height).toBeLessThanOrEqual(boxes.viewport);
    // Apilados: el de equipos empieza por debajo del de usuarios, no encima.
    expect(boxes.equip.top).toBeGreaterThanOrEqual(boxes.users.top);
  });

  test('los paneles conservan tope finito al apilarse', async ({ page }) => {
    await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
    await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 });

    // El tope vive en el panel; #users-list ya solo declara flex:1 + min-height:0
    // y hereda el alto que le deja su panel.
    const maxH = await page.evaluate(() => {
      const el = document.querySelector('#users-panel');
      return el ? getComputedStyle(el).maxHeight : null;
    });
    expect(maxH).not.toBe('none');
    expect(parseFloat(maxH)).toBeGreaterThan(0);
  });
});

// Regresión del reporte del 2026-08-11: los topes de las listas se calculaban
// contra el fondo del VIEWPORT, pero las listas viven dentro de un panel ya
// recortado a una caja menor con overflow:hidden — así que los topes lo
// rebasaban y el panel se comía el resto. Medido antes del arreglo: 56px de
// contenido inalcanzable en el panel derecho, la lista de disponibles con su
// borde en 884 contra un panel que acaba en 844, y 5 equipos asignados
// amontonados en un cajón fijo de 220px.
test.describe('assign_equipment — nada queda recortado dentro de los paneles', () => {
  for (const alto of [1080, 900, 700]) {
    test(`viewport ${alto}px: ningún panel esconde contenido inalcanzable`, async ({ page }) => {
      await page.setViewportSize({ width: 1920, height: alto });
      await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
      await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 });

      const primerUsuario = page.locator('#users-list .user-card').first();
      test.skip((await primerUsuario.count()) === 0, 'sin usuarios en el departamento de prueba');
      await primerUsuario.click();
      await expect(page.locator('#user-equipment-section')).toBeVisible();

      const medidas = await page.evaluate(() => {
        const inalcanzable = (sel) => {
          const el = document.querySelector(sel);
          return el ? el.scrollHeight - el.clientHeight : null;
        };
        const desborde = (panelSel, hijoSel) => {
          const p = document.querySelector(panelSel);
          const h = document.querySelector(hijoSel);
          if (!p || !h) return null;
          return Math.round(h.getBoundingClientRect().bottom - p.getBoundingClientRect().bottom);
        };
        return {
          inalcanzableIzq: inalcanzable('#users-panel'),
          inalcanzableDer: inalcanzable('#equip-panel'),
          desbordeListaUsuarios: desborde('#users-panel', '#users-list'),
          desbordeCuerpoEquipos: desborde('#equip-panel', '#equip-panel > .card-body'),
        };
      });

      // El panel recorta con overflow:hidden, así que cualquier excedente es
      // contenido que el usuario NO puede alcanzar de ninguna forma.
      expect(medidas.inalcanzableIzq).toBe(0);
      expect(medidas.inalcanzableDer).toBe(0);
      // Y ningún hijo puede sobresalir por debajo del panel que lo contiene.
      expect(medidas.desbordeListaUsuarios).toBeLessThanOrEqual(1);
      expect(medidas.desbordeCuerpoEquipos).toBeLessThanOrEqual(1);
    });
  }

  test('el panel de equipos tiene UN solo área scrolleable, no dos compitiendo', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 900 });
    await gotoHelpdeskAs(page, DEPT_HEAD_USER_ID, ASSIGN_PAGE);
    await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 });

    const primerUsuario = page.locator('#users-list .user-card').first();
    test.skip((await primerUsuario.count()) === 0, 'sin usuarios en el departamento de prueba');
    await primerUsuario.click();
    await expect(page.locator('#user-equipment-section')).toBeVisible();

    const scrolls = await page.evaluate(() => {
      const scrolleable = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        return ['auto', 'scroll'].includes(getComputedStyle(el).overflowY);
      };
      return {
        cuerpo: scrolleable('#equip-panel > .card-body'),
        asignados: scrolleable('#assigned-equipment-list'),
        individuales: scrolleable('#individual-equipment-list'),
        grupos: scrolleable('#groups-list'),
      };
    });

    expect(scrolls.cuerpo).toBe(true);
    // Las listas internas ya no scrollean por su cuenta: eran ellas las que
    // competían por el alto del panel y acababan recortadas.
    expect(scrolls.asignados).toBe(false);
    expect(scrolls.individuales).toBe(false);
    expect(scrolls.grupos).toBe(false);
  });
});

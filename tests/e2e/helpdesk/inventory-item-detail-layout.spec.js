// @ts-check
// Rediseño de item_detail (sidebar sticky col-lg-4 + contenido principal col-lg-8).
// Antes: 4 tarjetas a media anchura (col-lg-6) + chips de specs desperdiciaban
// la mayoría de su superficie en pares clave/valor de una línea, y los tabs
// —el contenido con más profundidad real— quedaban hasta el fondo de la
// página. Ver docs/superpowers/critiques/2026-08-10-inventory-item-detail.md.
//
// Este spec NO reemplaza inventory-items-pilot.spec.js (contratos de tabs
// básicos) ni back-button.spec.js (botón Volver) — cubre específicamente el
// layout nuevo: sidebar sticky de verdad, información clave sin scroll en
// desktop, apilado sin overflow horizontal bajo lg, y cero atributos BS4.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const ITEMS_LIST = '/help-desk/inventory/items';

/** Navega al primer ítem de inventario disponible, o null si no hay datos. */
async function gotoFirstItemDetail(page) {
  await gotoHelpdesk(page, ITEMS_LIST);
  const link = page.locator('#hd-items-results a[href^="/help-desk/inventory/items/"]').first();
  if ((await link.count()) === 0) return null;
  const href = await link.getAttribute('href');
  await gotoHelpdesk(page, href);
  await expect(page.locator('#main-content')).toBeVisible({ timeout: 15000 });
  return href;
}

test.describe('item_detail — layout sidebar sticky + contenido principal', () => {
  test('la sidebar es sticky de verdad: position:sticky y decelera contra el scroll (no se comporta como static)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    const href = await gotoFirstItemDetail(page);
    test.skip(!href, 'sin ítems en la BD de prueba');

    const sidebar = page.locator('#hd-item-sidebar');
    await expect(sidebar).toBeVisible();

    const position = await sidebar.evaluate((el) => getComputedStyle(el).position);
    expect(position).toBe('sticky');

    // El ítem "al azar" (el primero de la lista) puede traer poco contenido
    // (sin tickets/historial, pocas specs) — ahí la columna principal es más
    // corta que la sidebar y el "carril" de scroll dentro de la fila es casi
    // nulo, así que un sticky CORRECTO tampoco alcanza a mostrar una meseta
    // visible (no hay de dónde: no es un bug, es geometría). Para probar el
    // mecanismo real de forma determinista (no la casualidad del seed),
    // inyectamos un spacer temporal en la columna principal que garantiza
    // carril de sobra, sin tocar el layout real de la página.
    await page.evaluate(() => {
      const main = document.querySelector('.col-lg-8');
      const spacer = document.createElement('div');
      spacer.id = 'hd-test-spacer';
      spacer.style.height = '2000px';
      main.appendChild(spacer);
    });

    // Firma de un sticky ROTO (ancestro con overflow != visible, o degradado
    // a static/relative): su top relativo al viewport decrece EXACTAMENTE
    // 1:1 con el scroll de la página, sin frenarse nunca. Firma de un sticky
    // que SÍ funciona: en algún tramo del recorrido se "frena" (decelera)
    // porque llegó a su offset fijo.
    const scrollable = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
    const step = Math.max(100, Math.floor(scrollable / 8));
    const samples = [];
    for (let y = 0; y <= scrollable; y += step) {
      await page.evaluate((yy) => window.scrollTo(0, yy), y);
      await page.waitForTimeout(80);
      samples.push({ y, top: await sidebar.evaluate((el) => el.getBoundingClientRect().top) });
    }

    let decelerated = false;
    for (let i = 1; i < samples.length; i++) {
      const dScroll = samples[i].y - samples[i - 1].y;
      const dTop = samples[i - 1].top - samples[i].top; // positivo = sube junto con el scroll normal
      if (dScroll > 0 && dTop < dScroll * 0.5) { decelerated = true; break; }
    }
    expect(decelerated).toBe(true);

    // Bonus: una vez con carril de sobra, el top pinneado debe acercarse al
    // offset declarado en CSS (96px) — no quedarse arbitrariamente alto.
    const pinnedTop = Math.min(...samples.map((s) => s.top).filter((t) => t >= 0));
    expect(pinnedTop).toBeLessThanOrEqual(120);

    await page.evaluate(() => document.getElementById('hd-test-spacer')?.remove());
  });

  test('1920x1080: identidad, estado y garantía visibles sin scrollear', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    const href = await gotoFirstItemDetail(page);
    test.skip(!href, 'sin ítems en la BD de prueba');

    // Cabecera: estado + candado/depto/asignado (badges) sin scroll.
    await expect(page.locator('#status-badge-container .badge').first()).toBeInViewport();

    // Sidebar: Garantía e Identidad (nombre de card renovado) sin scroll.
    await expect(page.locator('#warranty-card')).toBeInViewport();
    await expect(page.locator('#general-info')).toBeInViewport();

    await page.screenshot({ path: '../../.playwright-mcp/images/helpdesk/item-detail-after-1920.png', fullPage: false });
  });

  test('contratos de tabs siguen verdes (history-tab / history-content / specs-content)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    const href = await gotoFirstItemDetail(page);
    test.skip(!href, 'sin ítems en la BD de prueba');

    const historyTab = page.locator('#history-tab');
    await expect(historyTab).toHaveAttribute('data-bs-toggle', 'tab');

    await historyTab.click();
    await expect(page.locator('#history-content')).toHaveClass(/active/);
    await expect(page.locator('#specs-content')).not.toHaveClass(/active/);

    // main[data-hd-page] no cambió de identidad con el rediseño.
    await expect(page.locator('main[data-hd-page]')).toHaveAttribute('data-hd-page', 'inventory_items_item_detail');
  });

  test('bajo lg (390x844) todo se apila sin scroll horizontal', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const href = await gotoFirstItemDetail(page);
    test.skip(!href, 'sin ítems en la BD de prueba');

    // Sticky se desactiva bajo lg (position vuelve a static — el layout se apila).
    const position = await page.locator('#hd-item-sidebar').evaluate((el) => getComputedStyle(el).position);
    expect(position).not.toBe('sticky');

    const overflowX = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    );
    expect(overflowX).toBe(true);

    await page.screenshot({ path: '../../.playwright-mcp/images/helpdesk/item-detail-after-mobile.png', fullPage: true });
  });

  test('cero atributos Bootstrap 4 en la vista', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    const href = await gotoFirstItemDetail(page);
    test.skip(!href, 'sin ítems en la BD de prueba');

    const bs4Count = await page.evaluate(() => {
      const main = document.querySelector('main[data-hd-page]');
      if (!main) return -1;
      return main.querySelectorAll('[data-toggle], [data-dismiss], [data-target]').length;
    });
    expect(bs4Count).toBe(0);
  });
});

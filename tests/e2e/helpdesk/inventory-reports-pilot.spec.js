// @ts-check
// Chunk 7 — inventory/reports + verification + dashboard a BS5.
//   · reports  = isla de reportes (tablas client-side): de-jQuery + BS5, enlace
//     "Ir a Verificar" morph (hd_boost). Sin atributos BS4.
//   · verification = receta HTMX (fragmento server-side + filtros + paginación) +
//     modales BS5 (de-jQuery). Contrato de fragmento por HX-Request.
//   · dashboard = charts island (Chart.js) BS5; enlaces internos boosteables.
// Aserciones DETERMINISTAS (no dependen de datos de BD): shell server-side, el
// contrato del fragmento (HX-Request → sin <html>), el form de filtros HTMX,
// abrir/cerrar un modal BS5 y la ausencia total de atributos BS4.
// Páginas role-gated → se autentica como admin real (sin bypass del storageState).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const REPORTS_PAGE = '/help-desk/inventory/reports';
const VERIF_PAGE = '/help-desk/inventory/verification';
const DASHBOARD_PAGE = '/help-desk/inventory/dashboard';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('pilot — inventory/reports + verification + dashboard (BS5)', () => {

  // ─────────────────────────────────── reports ───────────────────────────────────
  test('reports: shell server-side, tabs BS5, enlace "Ir a Verificar" boosteable, 0 atributos BS4', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, REPORTS_PAGE);

    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_reports_reports'
    );

    // Las 6 pestañas usan la API de tabs de Bootstrap 5 (data-bs-toggle).
    await expect(page.locator('#reportTabs button[data-bs-toggle="tab"]')).toHaveCount(6);

    // El enlace "Ir a Verificar" (contenido, dentro de <main>) apunta a una página
    // migrada → lleva hx-boost. (Scope a main: navbar/sidebar también enlazan ahí.)
    await expect(page.locator(`main a[href="${VERIF_PAGE}"]`)).toHaveAttribute('hx-boost', 'true');

    // Cero atributos BS4 en toda la página.
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);
  });

  // ──────────────────────────────── verification ─────────────────────────────────
  test('verification: render server-side con #hd-verif-results + form de filtros HTMX', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, VERIF_PAGE);

    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_reports_verification'
    );

    const results = page.locator('#hd-verif-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta a la misma URL por HTMX (misma URL, 2 representaciones).
    const form = page.locator('#hd-filter-form');
    await expect(form).toHaveAttribute('hx-get', VERIF_PAGE);
    await expect(form).toHaveAttribute('hx-target', '#hd-verif-results');
    await expect(form).toHaveAttribute('hx-push-url', 'true');

    // Tabla server-side o estado vacío (sin asumir datos de BD).
    const hasTable = await results.locator('#verif-table').count() > 0;
    if (!hasTable) {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }

    // Cero atributos BS4 (los modales del flujo de escaneo son BS5).
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);
  });

  test('verification: HX-Request devuelve el FRAGMENTO; sin header, la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, VERIF_PAGE);

    const frag = await page.request.get(VERIF_PAGE + '?status_filter=never', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody).not.toContain('base_helpdesk');
    expect(fragBody.includes('verif-table') || fragBody.includes('hd-empty-state')).toBeTruthy();
    // El fragmento trae las stats OOB para actualizar las tarjetas fuera del target.
    expect(fragBody).toContain('hx-swap-oob');

    const full = await page.request.get(VERIF_PAGE, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });

  test('verification: filtro HTMX empuja la URL sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, VERIF_PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(VERIF_PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus_filter', 'never');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    await expect.poll(() => new URL(page.url()).searchParams.get('status_filter')).toBe('never');
    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    const body = await resp.text();
    expect(body).not.toContain('<html');
  });

  test('verification: modal Verificar (BS5) abre y cierra sin jQuery', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, VERIF_PAGE);

    const modal = page.locator('#modal-verify');
    await expect(modal).toBeHidden();

    // Apertura via API de Bootstrap 5 (determinista, sin depender de datos).
    await page.evaluate(() => {
      bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-verify')).show();
    });
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });

  // ─────────────────────────────────── dashboard ─────────────────────────────────
  test('dashboard: shell server-side, canvas de charts presentes, enlaces boosteables, 0 atributos BS4', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, DASHBOARD_PAGE);

    await expect(page.locator('main[data-hd-page]')).toHaveAttribute(
      'data-hd-page', 'inventory_dashboard'
    );

    // Charts island: los canvas de Chart.js están en el DOM server-side.
    await expect(page.locator('#categoryChart')).toBeAttached();
    await expect(page.locator('#statusChart')).toBeAttached();

    // Enlaces internos de contenido (Registrar / Ver Inventario) → hx-boost.
    // (Scope a main: navbar/sidebar también enlazan a esas páginas.)
    await expect(page.locator('main a[href="/help-desk/inventory/items/create"]')).toHaveAttribute('hx-boost', 'true');
    await expect(page.locator('main a[href="/help-desk/inventory/items"]')).toHaveAttribute('hx-boost', 'true');

    // Cero atributos BS4.
    await expect(page.locator('[data-toggle], [data-dismiss], [data-target]')).toHaveCount(0);
  });
});

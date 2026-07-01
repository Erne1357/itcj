// @ts-check
// Migración de inventory/items a componentes server-side + HTMX + Alpine (isla BS4 → BS5).
// Valida: tabla server-side con macros (#hd-items-results, NO el render JS viejo
// #items-table oculto), filtro por HTMX (hx-get a la misma URL, push-url, sin full
// reload), fragmento puro por HX-Request, modal BS5 (quick actions) abre/cierra, y
// —si hay equipos— un cambio de pestaña en item_detail bajo BS5.
// Páginas role-gated → se autentica como admin real (no el bypass del storageState).
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/inventory/items';
const ADMIN_USER_ID = 7676; // admin real (roles vía BD, sin bypass)

test.describe('pilot — inventory/items (componentes server-side + HTMX + Alpine, BS5)', () => {
  test('render server-side: #hd-items-results con macros (no el render JS viejo)', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const results = page.locator('#hd-items-results');
    await expect(results).toBeVisible();

    // El form de filtros apunta a la misma URL por HTMX.
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PAGE);

    // Contenido server-rendered: o tabla con checkboxes Alpine, o empty_state.
    const rows = results.locator('tbody tr');
    if (await rows.count() > 0) {
      await expect(results.locator('.hd-item-cb').first()).toBeVisible();
      await expect(results.locator('.badge').first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }

    // La tabla vieja construida por JS (id="items-table" dentro de #table-container) NO existe.
    await expect(page.locator('#items-table')).toHaveCount(0);
  });

  test('filtro HTMX: cambiar estado dispara hx-get a la misma URL, empuja URL, sin full reload', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const waitPartial = page.waitForResponse(
      (r) => r.url().includes(PAGE) && r.request().method() === 'GET'
    );
    await page.selectOption('#filterStatus', 'ACTIVE');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    // hx-push-url reflejó el filtro en la URL (estado compartible / back-forward).
    await expect.poll(() => new URL(page.url()).searchParams.get('status')).toBe('ACTIVE');

    // No hubo navegación completa: el marcador window.__booted sobrevive.
    expect(await page.evaluate(() => window.__booted === true)).toBe(true);

    // La respuesta es un FRAGMENTO (sin documento completo / sin base).
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
  });

  test('petición HTMX (HX-Request) devuelve fragmento; sin header, la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const frag = await page.request.get(PAGE + '?status=ACTIVE', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    // El fragmento contiene o la tabla (hd-item-cb) o el empty_state.
    expect(fragBody.includes('hd-item-cb') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PAGE, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });

  test('modal BS5 (Acciones Rápidas) abre y cierra sin jQuery — si hay equipos', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const trigger = page.locator('#hd-items-results [data-action="quick-actions"]').first();
    // Deterministic: solo ejercemos el modal si hay al menos un equipo.
    if (await trigger.count() === 0) {
      test.info().annotations.push({ type: 'note', description: 'sin equipos: modal no ejercido' });
      return;
    }

    const modal = page.locator('#quickActionsModal');
    await expect(modal).toBeHidden();
    await trigger.click();
    await expect(modal).toBeVisible();
    await expect(modal).toHaveClass(/show/);

    // Cierre por el botón BS5 .btn-close.
    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();
  });

  test('item_detail (isla BS5): cambio de pestaña con data-bs-toggle="tab" — si es alcanzable', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PAGE);

    const firstDetailLink = page.locator('#hd-items-results tbody tr td a[href^="/help-desk/inventory/items/"]').first();
    if (await firstDetailLink.count() === 0) {
      test.info().annotations.push({ type: 'note', description: 'sin equipos: item_detail no alcanzable' });
      return;
    }
    const href = await firstDetailLink.getAttribute('href');
    await gotoHelpdeskAs(page, ADMIN_USER_ID, href);

    // El detalle carga por API; esperamos a que el contenido principal sea visible.
    await expect(page.locator('#main-content')).toBeVisible({ timeout: 15000 });

    // Las pestañas usan BS5 (data-bs-toggle="tab").
    const historyTab = page.locator('#history-tab');
    await expect(historyTab).toHaveAttribute('data-bs-toggle', 'tab');

    await historyTab.click();
    await expect(page.locator('#history-content')).toHaveClass(/active/);
    await expect(page.locator('#specs-content')).not.toHaveClass(/active/);
  });
});

const PENDING = '/help-desk/inventory/pending';

test.describe('pilot — inventory/pending (componentes server-side + HTMX + Alpine, BS5)', () => {
  test('render server-side: #hd-pending-results + form HTMX a la misma URL', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PENDING);

    const results = page.locator('#hd-pending-results');
    await expect(results).toBeVisible();
    await expect(page.locator('#hd-filter-form')).toHaveAttribute('hx-get', PENDING);

    const rows = results.locator('tbody tr');
    if (await rows.count() > 0) {
      await expect(results.locator('.hd-item-cb').first()).toBeVisible();
    } else {
      await expect(results.locator('.hd-empty-state')).toBeVisible();
    }
  });

  test('petición HTMX (HX-Request) devuelve fragmento; sin header, la página completa', async ({ page }) => {
    await gotoHelpdeskAs(page, ADMIN_USER_ID, PENDING);

    const frag = await page.request.get(PENDING + '?sort=oldest', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const fragBody = await frag.text();
    expect(fragBody).not.toContain('<html');
    expect(fragBody.includes('hd-item-cb') || fragBody.includes('hd-empty-state')).toBeTruthy();

    const full = await page.request.get(PENDING, { maxRedirects: 0 });
    expect(full.status()).toBe(200);
    expect(await full.text()).toContain('<html');
  });
});

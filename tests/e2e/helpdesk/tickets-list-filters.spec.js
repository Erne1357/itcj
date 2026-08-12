// @ts-check
// Filtros nuevos de admin/tickets-list: técnico asignado, categoría, depto. del
// solicitante, rango de fechas y orden — dentro del panel colapsable "Más
// filtros" (los 4 originales status/area/priority/search siguen siempre
// visibles, ver tickets-list-pilot.spec.js). Plantilla: tickets-list-pilot.spec.js.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/tickets-list';

test.describe('tickets-list — filtros nuevos (técnico/categoría/depto/fechas/orden)', () => {
  test('panel "Más filtros" arranca cerrado sin filtros activos', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    const panel = page.locator('#hdMoreFilters');
    // Bootstrap .collapse sin .show es display:none — "cerrado" es "hidden", no ausente del DOM.
    await expect(panel).toBeHidden();
    await expect(panel).not.toHaveClass(/show/);
    await expect(page.locator('#btnMoreFilters')).toHaveAttribute('aria-expanded', 'false');
  });

  test('panel "Más filtros" arranca abierto cuando la URL trae un filtro extra activo', async ({ page }) => {
    await gotoHelpdesk(page, PAGE + '?sort=oldest');
    const panel = page.locator('#hdMoreFilters');
    await expect(panel).toHaveClass(/show/);
    await expect(page.locator('#btnMoreFilters')).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('#filterSort')).toHaveValue('oldest');
  });

  test('botón "Más filtros" lo abre manualmente (Bootstrap collapse)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    const panel = page.locator('#hdMoreFilters');
    await expect(panel).not.toHaveClass(/show/);
    await page.click('#btnMoreFilters');
    await expect(panel).toHaveClass(/show/);
  });

  test('filtro técnico "Sin asignar": empuja ?technician=unassigned y devuelve fragmento', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    const waitPartial = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.selectOption('#filterTechnician', 'unassigned');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);

    await expect.poll(() => new URL(page.url()).searchParams.get('technician')).toBe('unassigned');
    const body = await resp.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');

    // Chip activo, quitable individualmente.
    const chip = page.locator('#hd-active-chips [data-chip-remove="technician"]');
    await expect(chip).toBeVisible();
  });

  test('filtro técnico "Cola de Desarrollo": enruta a team:desarrollo', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');
    const waitPartial = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.selectOption('#filterTechnician', 'team:desarrollo');
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);
    await expect.poll(() => new URL(page.url()).searchParams.get('technician')).toBe('team:desarrollo');
  });

  test('filtro de orden: cada variante empuja ?sort= y devuelve fragmento', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    for (const value of ['oldest', 'priority', 'stale']) {
      const waitPartial = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
      await page.selectOption('#filterSort', value);
      const resp = await waitPartial;
      expect(resp.status()).toBe(200);
      await expect.poll(() => new URL(page.url()).searchParams.get('sort')).toBe(value);
    }
  });

  test('rango de fechas: llenar Desde/Hasta empuja start/end y devuelve fragmento', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    const waitStart = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.fill('#filterStart', '2026-01-01');
    await waitStart;
    await expect.poll(() => new URL(page.url()).searchParams.get('start')).toBe('2026-01-01');

    const waitEnd = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.fill('#filterEnd', '2026-01-31');
    const resp = await waitEnd;
    expect(resp.status()).toBe(200);
    await expect.poll(() => new URL(page.url()).searchParams.get('end')).toBe('2026-01-31');

    await expect(page.locator('#hd-active-chips [data-chip-remove="start"]')).toBeVisible();
    await expect(page.locator('#hd-active-chips [data-chip-remove="end"]')).toBeVisible();
  });

  test('combinación de filtros: técnico + orden + fechas se acumulan en la URL', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterTechnician', 'unassigned'),
    ]);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterSort', 'oldest'),
    ]);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.fill('#filterStart', '2026-01-01'),
    ]);

    await expect.poll(() => {
      const params = new URL(page.url()).searchParams;
      return [params.get('technician'), params.get('sort'), params.get('start')];
    }).toEqual(['unassigned', 'oldest', '2026-01-01']);

    // Un chip por filtro activo.
    await expect(page.locator('#hd-active-chips [data-chip-remove="technician"]')).toBeVisible();
    await expect(page.locator('#hd-active-chips [data-chip-remove="sort"]')).toBeVisible();
    await expect(page.locator('#hd-active-chips [data-chip-remove="start"]')).toBeVisible();
  });

  test('chip: quitar un filtro individualmente lo limpia sin tocar los demás', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterTechnician', 'unassigned'),
    ]);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterSort', 'oldest'),
    ]);

    const waitPartial = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.click('#hd-active-chips [data-chip-remove="technician"]');
    await waitPartial;

    await expect.poll(() => new URL(page.url()).searchParams.get('technician')).toBe('');
    await expect.poll(() => new URL(page.url()).searchParams.get('sort')).toBe('oldest'); // intacto
    await expect(page.locator('#filterTechnician')).toHaveValue('');
    await expect(page.locator('#hd-active-chips [data-chip-remove="technician"]')).toHaveCount(0);
  });

  test('"Limpiar" resetea también los filtros nuevos (selects y fechas)', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    await page.click('#btnMoreFilters');

    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterTechnician', 'unassigned'),
    ]);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.selectOption('#filterSort', 'oldest'),
    ]);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET'),
      page.fill('#filterStart', '2026-01-01'),
    ]);

    const waitClear = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    await page.click('#btnClearFilters');
    await waitClear;

    await expect(page.locator('#filterTechnician')).toHaveValue('');
    await expect(page.locator('#filterSort')).toHaveValue('');
    await expect(page.locator('#filterStart')).toHaveValue('');
    await expect(page.locator('#filterEnd')).toHaveValue('');
    await expect(page.locator('#filterStatus')).toHaveValue('');
    await expect(page.locator('#hd-active-chips .hd-filter-chip')).toHaveCount(0);
  });

  test('petición HTMX directa con category/req_department como query params responde 200 y fragmento', async ({ request }) => {
    const frag = await request.get(PAGE + '?category=999999&req_department=999999', {
      headers: { 'HX-Request': 'true' },
      maxRedirects: 0,
    });
    expect(frag.status()).toBe(200);
    const body = await frag.text();
    expect(body).not.toContain('<html');
    expect(body).not.toContain('base_helpdesk');
    // IDs inexistentes → 0 resultados, pero el fragmento sigue siendo válido (empty state).
    expect(body.includes('hd-ticket-card') || body.includes('hd-empty-state')).toBeTruthy();
  });

  test('búsqueda libre sigue funcionando (solo texto, sin id) y devuelve fragmento', async ({ page }) => {
    await gotoHelpdesk(page, PAGE);
    const waitPartial = page.waitForResponse((r) => r.url().includes(PAGE) && r.request().method() === 'GET');
    // htmx dispara con `keyup` real (no con el evento sintético de fill()).
    await page.locator('#searchInput').pressSequentially('zzz-no-debería-matchear-nada-zzz', { delay: 20 });
    const resp = await waitPartial;
    expect(resp.status()).toBe(200);
    await expect(page.locator('#hd-tickets-results')).toContainText(/No hay tickets/i);
  });
});

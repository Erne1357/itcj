// @ts-check
/**
 * indicators — año → ficha de indicador con sus **cuatro** umbrales → rejilla
 * de seguimiento por colores.
 *
 * Los cuatro umbrales son cuatro columnas de verdad (`planned_white/red/
 * yellow/green`). El legacy los empaquetaba en un solo string `"b-r-a-v"` que
 * desempaquetaba con `.split('-')`, así que cualquier umbral con guion
 * (`"1-2 días"`, `"-5%"`) corrompía las cuatro celdas: por eso este spec usa a
 * propósito valores CON guion.
 *
 * Del seguimiento se verifica lo que el legacy no garantizaba: que el color
 * elegido se **persiste** (upsert por `(indicator_id, period_index)` sobre el
 * UNIQUE nuevo) y sigue ahí tras recargar la página.
 */
const { test, expect } = require('@playwright/test');
const {
  E2E,
  E2E_YEAR_MIN,
  gotoAdhoc,
  cleanupAdhoc,
  newApiContext,
  trapNativeDialogs,
} = require('./_helpers');

const YEAR = E2E_YEAR_MIN + 1;
const PROCESS_NAME = `${E2E}proceso_indicadores`;
const OBJECTIVE = `${E2E}reducir el tiempo de respuesta`;
/** Umbrales CON guion: el formato "b-r-a-v" del legacy se rompía con ellos. */
const THRESHOLDS = {
  planned_white: 'Base 0-100',
  planned_red: '< 70%',
  planned_yellow: '70-85%',
  planned_green: '> 85%',
};

const ctx = { processId: 0, yearId: 0, indicatorId: 0 };

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  cleanupAdhoc();
  const api = await newApiContext();
  try {
    // Un proceso es requisito de la ficha (`process_id` NOT NULL) y no hay
    // ninguno sembrado: se crea aquí porque es montaje, no lo que se prueba.
    const proc = await api.post(
      '/processes',
      { items: [{ name: PROCESS_NAME, color: '#4834d4' }] },
      [200, 201]
    );
    ctx.processId = proc.body.data[0].id;
  } finally {
    await api.dispose();
  }
});

test.afterAll(() => {
  cleanupAdhoc();
});

test('alta de un año del tablero desde la UI', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, '/adhoc/indicadores');

  await page.locator('[data-adhoc-years-new]').click();
  const modal = page.locator('#adhoc-years-modal');
  await expect(modal).toBeVisible();

  const input = modal.locator('[data-adhoc-years-input]');
  await expect(input).toHaveCount(1);
  await input.fill(String(YEAR));

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/adhoc/v2/indicator-years') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-years-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(201);
  ctx.yearId = (await resp.json()).data[0].id;

  const row = page.locator('#adhoc-indicator-years tbody tr', { hasText: String(YEAR) });
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute('data-id', String(ctx.yearId));

  expect(await readDialogs()).toEqual([]);
});

test('alta de un indicador con sus cuatro umbrales', async ({ page }) => {
  expect(ctx.yearId).toBeGreaterThan(0);
  await gotoAdhoc(page, `/adhoc/indicadores/${ctx.yearId}/tablero`);

  await page.locator('[data-adhoc-board-new]').click();
  const modal = page.locator('#adhoc-board-modal');
  await expect(modal).toBeVisible();

  const form = modal.locator('[data-adhoc-board-form="0"]');
  await form.locator('[data-adhoc-field="process_id"]').selectOption(String(ctx.processId));
  await form.locator('[data-adhoc-field="frequency"]').selectOption('Mensual');
  await form.locator('[data-adhoc-field="responsible"]').fill(`${E2E}responsable`);
  await form.locator('[data-adhoc-field="objective"]').fill(OBJECTIVE);
  for (const [key, value] of Object.entries(THRESHOLDS)) {
    await form.locator(`[data-adhoc-field="${key}"]`).fill(value);
  }

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/adhoc/v2/indicators') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-board-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(201);
  ctx.indicatorId = (await resp.json()).data[0].id;

  const row = page.locator('#adhoc-indicator-board tbody tr', { hasText: OBJECTIVE });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText(PROCESS_NAME);
  await expect(row).toContainText('Mensual');

  // Los cuatro umbrales viajaron enteros, cada uno en su propia columna.
  const chips = row.locator('.adhoc-board-planned-chip');
  await expect(chips).toHaveCount(4);
  await expect(chips.nth(0)).toHaveText(THRESHOLDS.planned_white);
  await expect(chips.nth(1)).toHaveText(THRESHOLDS.planned_red);
  await expect(chips.nth(2)).toHaveText(THRESHOLDS.planned_yellow);
  await expect(chips.nth(3)).toHaveText(THRESHOLDS.planned_green);
});

test('la rejilla de seguimiento guarda el color y persiste tras recargar', async ({ page }) => {
  expect(ctx.indicatorId).toBeGreaterThan(0);
  await gotoAdhoc(page, `/adhoc/indicadores/${ctx.yearId}/seguimiento`);

  const card = page.locator(`[data-adhoc-tracking-card="${ctx.indicatorId}"]`);
  await expect(card).toBeVisible();

  // Frecuencia mensual → 12 periodos (TRACKING_PERIODS_BY_FREQUENCY).
  const inputs = card.locator('[data-adhoc-tracking-input]');
  await expect(inputs).toHaveCount(12);

  const cells = [
    { period: 1, value: '92%', color: 'verde', cls: 'adhoc-state-green' },
    { period: 2, value: '65%', color: 'rojo', cls: 'adhoc-state-red' },
    { period: 3, value: '78%', color: 'amarillo', cls: 'adhoc-state-yellow' },
  ];

  for (const cell of cells) {
    const input = card.locator(`[data-adhoc-tracking-input][data-adhoc-period="${cell.period}"]`);
    const select = card.locator(`[data-adhoc-tracking-color][data-adhoc-period="${cell.period}"]`);

    await input.fill(cell.value);
    const saved = page.waitForResponse(
      (r) => r.url().includes('/indicator-trackings') && r.request().method() === 'PUT'
    );
    await select.selectOption(cell.color);
    expect((await saved).status()).toBe(200);

    await expect(input).toHaveClass(new RegExp(cell.cls));
  }

  await expect(card.locator(`[data-adhoc-saved="${ctx.indicatorId}"]`)).toBeVisible();

  // — el color persiste tras un reload completo —
  await page.reload({ waitUntil: 'domcontentloaded' });
  const reloaded = page.locator(`[data-adhoc-tracking-card="${ctx.indicatorId}"]`);
  await expect(reloaded).toBeVisible();

  for (const cell of cells) {
    const input = reloaded.locator(
      `[data-adhoc-tracking-input][data-adhoc-period="${cell.period}"]`
    );
    const select = reloaded.locator(
      `[data-adhoc-tracking-color][data-adhoc-period="${cell.period}"]`
    );
    await expect(input).toHaveValue(cell.value);
    await expect(input).toHaveClass(new RegExp(cell.cls));
    await expect(select).toHaveValue(cell.color);
  }

  // Y el upsert es idempotente: repetir la misma celda no duplica filas
  // (UniqueConstraint (indicator_id, period_index), bug #17 del legacy).
  const again = await page.request.put('/api/adhoc/v2/indicator-trackings', {
    data: { indicator_id: ctx.indicatorId, period_index: 1, real_value: '95%', color: 'verde' },
  });
  expect(again.status()).toBe(200);
  const list = await page.request.get(
    `/api/adhoc/v2/indicators?year_id=${ctx.yearId}`
  );
  expect(list.status()).toBe(200);
  const indicator = (await list.json()).data.find((i) => i.id === ctx.indicatorId);
  const periods = indicator.trackings.map((t) => t.period_index);
  expect(new Set(periods).size).toBe(periods.length);
});

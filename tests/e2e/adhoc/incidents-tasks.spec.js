// @ts-check
/**
 * incidents-tasks — incidencia → tareas → asignación de responsables →
 * workflow que **cierra** la incidencia.
 *
 * El asserto central es de vocabulario: al aprobar la última tarea la
 * incidencia debe quedar en **'Cerrada'**, no en `'Completado'`. El legacy
 * escribía `'Completado'` en incidencias y en eventos de programa por igual, y
 * la UI de incidencias no reconocía ese valor (plan §2.5).
 *
 * Todo el recorrido va por la UI: modal de alta de `work-items.js`, modal de
 * alta de `tasks.js`, pantalla `/adhoc/asignaciones` y modal de workflow del
 * tablero.
 */
const { test, expect } = require('@playwright/test');
const {
  E2E,
  ADHOC_SHELL,
  gotoAdhoc,
  cleanupAdhoc,
  adminUserId,
  dbRows,
  trapNativeDialogs,
} = require('./_helpers');

const INCIDENT_TITLE = `${E2E}incidencia_workflow`;
const TASK_A = `${E2E}tarea_correctiva_A`;
const TASK_B = `${E2E}tarea_correctiva_B`;

const ctx = { adminId: 0, incidentId: 0, taskA: 0 };

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  cleanupAdhoc();
  ctx.adminId = adminUserId();
});

test.afterAll(() => {
  cleanupAdhoc();
});

/**
 * Ejecuta una acción de workflow sobre una tarea desde el tablero, guardando
 * antes el comentario obligatorio.
 * @param {import('@playwright/test').Page} page
 * @param {number} taskId
 * @param {'terminar'|'aprobar'|'rechazar'} accion
 * @param {string} comment
 */
async function runWorkflow(page, taskId, accion, comment) {
  await gotoAdhoc(page, '/adhoc/dashboard');

  const card = page.locator(`[data-adhoc-task="${taskId}"]`);
  await expect(card).toBeVisible();
  await card.click();

  const modal = page.locator('#adhoc-wf-modal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#adhoc-wf-parent-type')).toHaveText('Incidencia');

  await modal.locator('[data-adhoc-wf-comment-new]').click();
  await modal.locator('#adhoc-wf-comment-text').fill(comment);
  const commentSaved = page.waitForResponse(
    (r) => r.url().includes('/comments') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-wf-comment-save]').click();
  expect((await commentSaved).status()).toBe(200);

  const button = modal.locator(`[data-adhoc-wf-action="${accion}"]`);
  await expect(button).toBeVisible();
  await button.click();

  const confirm = page.locator('.adhoc-modal.is-open [data-adhoc-role="confirm"]');
  await expect(confirm).toBeVisible();
  const done = page.waitForResponse(
    (r) => r.url().includes('/workflow-action') && r.request().method() === 'POST'
  );
  await confirm.click();
  const resp = await done;
  expect(resp.status(), await resp.text()).toBe(200);

  await page.waitForTimeout(1800); // dashboard.js recarga a los 1.2 s
  await page.waitForLoadState('domcontentloaded');
}

test('alta de incidencia desde la UI', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, '/adhoc/incidencias');
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();

  await page.locator('[data-adhoc-work-new]').click();
  const modal = page.locator('#adhoc-work-modal');
  await expect(modal).toBeVisible();

  await modal.locator('[data-adhoc-field="title"]').fill(INCIDENT_TITLE);
  await modal.locator('[data-adhoc-field="folio"]').fill(`${E2E}INC-01`);
  await modal.locator('[data-adhoc-field="priority"]').selectOption('Alta');
  // El responsable es el propio admin: así el tablero le muestra la tarea
  // cuando pase a revisión (rama `tareas_revisor_inc` de get_dashboard_tasks).
  await modal.locator('[data-adhoc-field="responsible_id"]').selectOption(String(ctx.adminId));

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/adhoc/v2/incidents') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-work-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(201);
  ctx.incidentId = (await resp.json()).data[0].id;

  const row = page.locator('#adhoc-table-incidents tbody tr', { hasText: INCIDENT_TITLE });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('No Iniciada');
  await expect(row).toContainText('Alta');

  expect(await readDialogs()).toEqual([]);
});

test('alta de dos tareas para la incidencia', async ({ page }) => {
  expect(ctx.incidentId).toBeGreaterThan(0);
  await gotoAdhoc(page, `/adhoc/incidencias/${ctx.incidentId}/tareas`);

  await page.locator('#adhoc-tasks-qty').selectOption('2');
  await page.locator('[data-adhoc-tasks-new]').click();
  const modal = page.locator('#adhoc-tasks-modal');
  await expect(modal).toBeVisible();

  const blocks = modal.locator('[data-adhoc-record]');
  await expect(blocks).toHaveCount(2);
  await blocks.nth(0).locator('[data-adhoc-field="description"]').fill(TASK_A);
  await blocks.nth(1).locator('[data-adhoc-field="description"]').fill(TASK_B);

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/adhoc/v2/tasks') && r.request().method() === 'POST'
  );
  await modal.locator('[data-adhoc-tasks-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(200);

  const rows = page.locator('#adhoc-table-tasks tbody tr[data-id]');
  await expect(rows).toHaveCount(2);
  const rowA = page.locator('#adhoc-table-tasks tbody tr', { hasText: TASK_A });
  await expect(rowA).toContainText('Sin asignar');
  await expect(rowA).toContainText('Pendiente');

  ctx.taskA = parseInt(
    /** @type {string} */ (await rowA.getAttribute('data-id')),
    10
  );
  expect(ctx.taskA).toBeGreaterThan(0);
});

test('asignación de responsables desde /adhoc/asignaciones', async ({ page }) => {
  expect(ctx.taskA).toBeGreaterThan(0);
  await gotoAdhoc(page, `/adhoc/incidencias/${ctx.incidentId}/tareas`);

  const rowA = page.locator('#adhoc-table-tasks tbody tr', { hasText: TASK_A });
  await rowA.locator('[data-adhoc-task-action="assign"]').click();

  await page.waitForURL(/\/adhoc\/asignaciones\?action=assign&task_id=/);
  await expect(page.locator('#adhoc-assign-picker')).toBeVisible();

  const check = page.locator(
    `#adhoc-assign-picker input[data-adhoc-picker-check][value="${ctx.adminId}"]`
  );
  await expect(check).toHaveCount(1);
  await check.check();

  const saved = page.waitForResponse(
    (r) => r.url().includes(`/tasks/${ctx.taskA}/assignees`) && r.request().method() === 'PUT'
  );
  await page.locator('[data-adhoc-assign-save]').click();
  expect((await saved).status()).toBe(200);

  // La pantalla vuelve sola a la lista de tareas (page_data.return_to).
  await page.waitForURL(new RegExp(`/adhoc/incidencias/${ctx.incidentId}/tareas`));
  const backRow = page.locator('#adhoc-table-tasks tbody tr', { hasText: TASK_A });
  await expect(backRow).not.toContainText('Sin asignar');
});

test('el workflow cierra la incidencia (estatus "Cerrada", no "Completado")', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);

  // 1) El ejecutor termina la tarea → pasa a revisión.
  await runWorkflow(page, ctx.taskA, 'terminar', `${E2E}trabajo terminado`);
  let detail = await page.request.get(`/api/adhoc/v2/tasks/${ctx.taskA}/workflow`);
  expect((await detail.json()).data.task.status).toBe('En Revisión');

  // 2) El validador aprueba → la tarea se completa y la incidencia se cierra.
  await runWorkflow(page, ctx.taskA, 'aprobar', `${E2E}validacion de eficacia`);
  detail = await page.request.get(`/api/adhoc/v2/tasks/${ctx.taskA}/workflow`);
  expect((await detail.json()).data.task.status).toBe('Completada');

  const rows = dbRows(
    `SELECT status, real_date FROM adhoc_incidents WHERE id = ${ctx.incidentId}`
  );
  expect(rows[0][0]).toBe('Cerrada');
  expect(rows[0][1]).not.toBeNull(); // real_date = date.today(), no un datetime

  // Y la lista lo enseña así.
  await gotoAdhoc(page, '/adhoc/incidencias');
  const row = page.locator('#adhoc-table-incidents tbody tr', { hasText: INCIDENT_TITLE });
  await expect(row).toContainText('Cerrada');

  expect(await readDialogs()).toEqual([]);
});

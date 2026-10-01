// @ts-check
/**
 * documents-flow — el corazón de la app: el flujo de aprobación documental.
 *
 *   alta de documento → iniciar flujo → aprobar paso 1 → aprobar paso 2
 *   → el documento queda **Aprobado**
 *
 * Todo el camino se recorre por la UI real (modales de Bootstrap del panel de
 * documentos y modal de workflow del tablero); solo el montaje del flujo con
 * sus dos pasos y sus validadores se hace por API, que es configuración previa
 * y no lo que este spec valida.
 *
 * Cubre además el agujero #6 del legacy ("cualquiera aprobaba cualquier
 * documento"): un usuario CON el permiso `adhoc.tasks.api.workflow` pero que NO
 * está entre los asignados de la tarea recibe **403**.
 */
const { test, expect } = require('@playwright/test');
const {
  E2E,
  ADHOC_SHELL,
  gotoAdhoc,
  loginAs,
  cleanupAdhoc,
  newApiContext,
  adminUserId,
  otherAdhocUserId,
  trapNativeDialogs,
} = require('./_helpers');

const DOC_TITLE = `${E2E}documento_flujo`;
const FLOW_NAME = `${E2E}flujo_documental`;
const STEP_1 = `${E2E}paso_revision`;
const STEP_2 = `${E2E}paso_autorizacion`;

/** Estado compartido entre los tests (corren en serie). */
const ctx = {
  adminId: 0,
  otherId: 0,
  flowId: 0,
  stepIds: /** @type {number[]} */ ([]),
  documentId: 0,
  taskStep1: 0,
  taskStep2: 0,
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  cleanupAdhoc();
  ctx.adminId = adminUserId();
  ctx.otherId = otherAdhocUserId(ctx.adminId);

  const api = await newApiContext();
  try {
    const flow = await api.post('/approval-flows', { name: FLOW_NAME }, [200, 201]);
    ctx.flowId = flow.body.data.id;

    const steps = await api.put(`/approval-flows/${ctx.flowId}/steps`, {
      steps: [
        { name: STEP_1, days_limit: 3, step_order: 1 },
        { name: STEP_2, days_limit: 3, step_order: 2 },
      ],
    });
    ctx.stepIds = steps.body.data.map((s) => s.id);
    expect(ctx.stepIds).toHaveLength(2);

    // El admin es el validador de LOS DOS pasos: así un mismo navegador puede
    // recorrer el flujo entero, que es lo que este spec quiere demostrar.
    for (const stepId of ctx.stepIds) {
      await api.put(`/approval-flows/steps/${stepId}/validators`, { user_ids: [ctx.adminId] });
    }
  } finally {
    await api.dispose();
  }
});

test.afterAll(() => {
  cleanupAdhoc();
});

/**
 * Aprueba una tarea desde el modal de workflow del tablero: abre la tarjeta,
 * guarda el comentario obligatorio y confirma la acción.
 * @param {import('@playwright/test').Page} page
 * @param {number} taskId
 * @param {string} comment
 */
async function approveFromDashboard(page, taskId, comment) {
  await gotoAdhoc(page, '/adhoc/dashboard');

  const card = page.locator(`[data-adhoc-task="${taskId}"]`);
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute('data-adhoc-task-status', 'En Revisión');
  await card.click();

  const modal = page.locator('#adhoc-wf-modal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#adhoc-wf-status')).toHaveText('En Revisión');

  // Regla de calidad del SGC: sin comentario no hay acción (el legacy devolvía
  // success:false con HTTP 200 y la UI seguía adelante).
  await modal.locator('[data-adhoc-wf-comment-new]').click();
  const form = modal.locator('#adhoc-wf-comment-form');
  await expect(form).toBeVisible();
  await form.locator('#adhoc-wf-comment-text').fill(comment);

  const commentSaved = page.waitForResponse(
    (r) => r.url().includes('/comments') && r.request().method() === 'POST'
  );
  await form.locator('[data-adhoc-wf-comment-save]').click();
  expect((await commentSaved).status()).toBe(200);
  await expect(modal.locator('#adhoc-wf-comments')).toContainText(comment);

  const approve = modal.locator('[data-adhoc-wf-action="aprobar"]');
  await expect(approve).toBeVisible();
  await approve.click();

  // AdhocUtils.confirmDialog: overlay propio creado al vuelo (el del legacy),
  // NUNCA window.confirm.
  const confirm = page.locator('.adhoc-modal.is-open [data-adhoc-role="confirm"]');
  await expect(confirm).toBeVisible();

  const actionDone = page.waitForResponse(
    (r) => r.url().includes('/workflow-action') && r.request().method() === 'POST'
  );
  await confirm.click();
  const resp = await actionDone;
  expect(resp.status(), await resp.text()).toBe(200);

  // dashboard.js recarga la página 1.2 s después de la acción; se espera a que
  // el reload ocurra para no pisarlo con la siguiente navegación.
  await page.waitForTimeout(1800);
  await page.waitForLoadState('domcontentloaded');
}

test('alta de documento e inicio del flujo de aprobación (UI)', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await gotoAdhoc(page, '/adhoc/documentos/panel');
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();

  // — alta —
  await page.locator('[data-adhoc-doc-new]').click();
  const docModal = page.locator('#adhoc-doc-modal');
  await expect(docModal).toBeVisible();
  await docModal.locator('#adhoc-doc-title-1').fill(DOC_TITLE);
  await docModal.locator('#adhoc-doc-code-1').fill(`${E2E}COD-01`);

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/adhoc/v2/documents') && r.request().method() === 'POST'
  );
  await docModal.locator('[data-adhoc-doc-save]').click();
  const createdResp = await created;
  expect(createdResp.status(), await createdResp.text()).toBe(200);
  ctx.documentId = (await createdResp.json()).data[0].id;

  const row = page.locator('#adhoc-doc-panel-table tbody tr', { hasText: DOC_TITLE });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('Borrador');

  // — inicio del flujo —
  await row.locator('[data-adhoc-doc-action="start-flow"]').click();
  const flowModal = page.locator('#adhoc-doc-flow-modal');
  await expect(flowModal).toBeVisible();
  await expect(flowModal.locator('[data-adhoc-flow-doc]')).toContainText(DOC_TITLE);
  await flowModal.locator('#adhoc-doc-flow-select').selectOption(String(ctx.flowId));

  const started = page.waitForResponse(
    (r) => r.url().includes('/start-flow') && r.request().method() === 'POST'
  );
  await flowModal.locator('[data-adhoc-flow-start]').click();
  const startedResp = await started;
  expect(startedResp.status(), await startedResp.text()).toBe(200);

  await expect(row).toContainText('En Revisión');

  // — el flujo creó una tarea por paso —
  const tasks = await page.request.get(
    `/api/adhoc/v2/tasks?parent_type=document&parent_id=${ctx.documentId}`
  );
  expect(tasks.status()).toBe(200);
  const rows = (await tasks.json()).data;
  expect(rows).toHaveLength(2);
  const byStep = new Map(rows.map((t) => [t.flow_step_id, t]));
  ctx.taskStep1 = byStep.get(ctx.stepIds[0]).id;
  ctx.taskStep2 = byStep.get(ctx.stepIds[1]).id;
  expect(byStep.get(ctx.stepIds[0]).status).toBe('En Revisión');
  expect(byStep.get(ctx.stepIds[1]).status).toBe('En Espera');

  // Ni un solo diálogo nativo en todo el recorrido (el legacy tenía 14).
  expect(await readDialogs()).toEqual([]);
});

test('un usuario NO asignado recibe 403 al ejecutar la acción de workflow', async ({ page }) => {
  expect(ctx.taskStep1).toBeGreaterThan(0);

  // Este usuario TIENE `adhoc.tasks.api.workflow` (rol admin de la app), así que
  // el 403 no puede venir de require_perms: viene de la comprobación de
  // asignación que el legacy no hacía (bug #6).
  await loginAs(page, ctx.otherId);

  const res = await page.request.post(
    `/api/adhoc/v2/tasks/${ctx.taskStep1}/workflow-action`,
    { data: { accion: 'aprobar' } }
  );
  expect(res.status()).toBe(403);
  const body = await res.json();
  expect(String(body.error)).toContain('No estás asignado');

  // Y la tarea sigue intacta.
  const detail = await page.request.get(`/api/adhoc/v2/tasks/${ctx.taskStep1}/workflow`);
  expect(detail.status()).toBe(200);
  expect((await detail.json()).data.task.status).toBe('En Revisión');
});

test('aprobar el paso 1 pasa el turno al paso 2', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);
  await approveFromDashboard(page, ctx.taskStep1, `${E2E}visto bueno del paso 1`);

  const tasks = await page.request.get(
    `/api/adhoc/v2/tasks?parent_type=document&parent_id=${ctx.documentId}`
  );
  const byId = new Map((await tasks.json()).data.map((t) => [t.id, t]));
  expect(byId.get(ctx.taskStep1).status).toBe('Completada');
  expect(byId.get(ctx.taskStep2).status).toBe('En Revisión');

  const doc = await page.request.get(`/api/adhoc/v2/documents/${ctx.documentId}`);
  const detail = (await doc.json()).data;
  expect(detail.status).toBe('En Revisión');
  expect(detail.current_step.name).toBe(STEP_2);

  expect(await readDialogs()).toEqual([]);
});

test('aprobar el paso 2 deja el documento Aprobado', async ({ page }) => {
  await approveFromDashboard(page, ctx.taskStep2, `${E2E}autorizacion final`);

  const doc = await page.request.get(`/api/adhoc/v2/documents/${ctx.documentId}`);
  const detail = (await doc.json()).data;
  expect(detail.status).toBe('Aprobado');
  expect(detail.approval_date).not.toBeNull();

  // Y se ve así en el panel.
  await gotoAdhoc(page, '/adhoc/documentos/panel');
  const row = page.locator('#adhoc-doc-panel-table tbody tr', { hasText: DOC_TITLE });
  await expect(row).toContainText('Aprobado');
});

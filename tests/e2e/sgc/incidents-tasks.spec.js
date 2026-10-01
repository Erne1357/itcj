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
 * alta de `tasks.js`, pantalla `/sgi/sgc/asignaciones` y modal de workflow del
 * tablero.
 */
const { test, expect } = require('@playwright/test');
const {
  E2E,
  SGC_SHELL,
  gotoSgc,
  cleanupSgc,
  adminUserId,
  dbRows,
  runPy,
  trapNativeDialogs,
} = require('./_helpers');

const INCIDENT_TITLE = `${E2E}incidencia_workflow`;
const TASK_A = `${E2E}tarea_correctiva_A`;
const TASK_B = `${E2E}tarea_correctiva_B`;

const ctx = { adminId: 0, incidentId: 0, taskA: 0 };

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  cleanupSgc();
  ctx.adminId = adminUserId();
});

test.afterAll(() => {
  cleanupSgc();
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
  await gotoSgc(page, '/sgi/sgc/dashboard');

  const card = page.locator(`[data-sgi-task="${taskId}"]`);
  await expect(card).toBeVisible();
  await card.click();

  const modal = page.locator('#sgi-wf-modal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#sgi-wf-parent-type')).toHaveText('Incidencia');

  await modal.locator('[data-sgi-wf-comment-new]').click();
  await modal.locator('#sgi-wf-comment-text').fill(comment);
  const commentSaved = page.waitForResponse(
    (r) => r.url().includes('/comments') && r.request().method() === 'POST'
  );
  await modal.locator('[data-sgi-wf-comment-save]').click();
  expect((await commentSaved).status()).toBe(200);

  const button = modal.locator(`[data-sgi-wf-action="${accion}"]`);
  await expect(button).toBeVisible();
  await button.click();

  const confirm = page.locator('.sgi-modal.is-open [data-sgi-role="confirm"]');
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
  await gotoSgc(page, '/sgi/sgc/incidencias');
  await expect(page.locator(SGC_SHELL)).toBeVisible();

  await page.locator('[data-sgi-work-new]').click();
  const modal = page.locator('#sgi-work-modal');
  await expect(modal).toBeVisible();

  await modal.locator('[data-sgi-field="title"]').fill(INCIDENT_TITLE);
  await modal.locator('[data-sgi-field="folio"]').fill(`${E2E}INC-01`);
  await modal.locator('[data-sgi-field="priority"]').selectOption('Alta');
  // El responsable es el propio admin: así el tablero le muestra la tarea
  // cuando pase a revisión (rama `tareas_revisor_inc` de get_dashboard_tasks).
  await modal.locator('[data-sgi-field="responsible_id"]').selectOption(String(ctx.adminId));

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/sgi/v2/sgc/incidents') && r.request().method() === 'POST'
  );
  await modal.locator('[data-sgi-work-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(201);
  ctx.incidentId = (await resp.json()).data[0].id;

  const row = page.locator('#sgi-table-incidents tbody tr', { hasText: INCIDENT_TITLE });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText('No Iniciada');
  await expect(row).toContainText('Alta');

  expect(await readDialogs()).toEqual([]);
});

test('alta de dos tareas para la incidencia', async ({ page }) => {
  expect(ctx.incidentId).toBeGreaterThan(0);
  await gotoSgc(page, `/sgi/sgc/incidencias/${ctx.incidentId}/tareas`);

  await page.locator('#sgi-tasks-qty').selectOption('2');
  await page.locator('[data-sgi-tasks-new]').click();
  const modal = page.locator('#sgi-tasks-modal');
  await expect(modal).toBeVisible();

  const blocks = modal.locator('[data-sgi-record]');
  await expect(blocks).toHaveCount(2);
  await blocks.nth(0).locator('[data-sgi-field="description"]').fill(TASK_A);
  await blocks.nth(1).locator('[data-sgi-field="description"]').fill(TASK_B);

  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/sgi/v2/sgc/tasks') && r.request().method() === 'POST'
  );
  await modal.locator('[data-sgi-tasks-save]').click();
  const resp = await created;
  expect(resp.status(), await resp.text()).toBe(200);

  const rows = page.locator('#sgi-table-tasks tbody tr[data-id]');
  await expect(rows).toHaveCount(2);
  const rowA = page.locator('#sgi-table-tasks tbody tr', { hasText: TASK_A });
  await expect(rowA).toContainText('Sin asignar');
  await expect(rowA).toContainText('Pendiente');

  ctx.taskA = parseInt(
    /** @type {string} */ (await rowA.getAttribute('data-id')),
    10
  );
  expect(ctx.taskA).toBeGreaterThan(0);
});

test('asignación de responsables desde /sgi/sgc/asignaciones', async ({ page }) => {
  expect(ctx.taskA).toBeGreaterThan(0);
  await gotoSgc(page, `/sgi/sgc/incidencias/${ctx.incidentId}/tareas`);

  const rowA = page.locator('#sgi-table-tasks tbody tr', { hasText: TASK_A });
  await rowA.locator('[data-sgi-task-action="assign"]').click();

  await page.waitForURL(/\/sgi/sgc\/asignaciones\?action=assign&task_id=/);
  await expect(page.locator('#sgi-assign-picker')).toBeVisible();

  const check = page.locator(
    `#sgi-assign-picker input[data-sgi-picker-check][value="${ctx.adminId}"]`
  );
  await expect(check).toHaveCount(1);
  await check.check();

  const saved = page.waitForResponse(
    (r) => r.url().includes(`/tasks/${ctx.taskA}/assignees`) && r.request().method() === 'PUT'
  );
  await page.locator('[data-sgi-assign-save]').click();
  expect((await saved).status()).toBe(200);

  // La pantalla vuelve sola a la lista de tareas (page_data.return_to).
  await page.waitForURL(new RegExp(`/sgi/sgc/incidencias/${ctx.incidentId}/tareas`));
  const backRow = page.locator('#sgi-table-tasks tbody tr', { hasText: TASK_A });
  await expect(backRow).not.toContainText('Sin asignar');
});

test('el workflow cierra la incidencia (estatus "Cerrada", no "Completado")', async ({ page }) => {
  const readDialogs = await trapNativeDialogs(page);

  // 1) El ejecutor termina la tarea → pasa a revisión.
  await runWorkflow(page, ctx.taskA, 'terminar', `${E2E}trabajo terminado`);
  let detail = await page.request.get(`/api/sgi/v2/sgc/tasks/${ctx.taskA}/workflow`);
  expect((await detail.json()).data.task.status).toBe('En Revisión');

  // 2) El validador aprueba → la tarea se completa y la incidencia se cierra.
  await runWorkflow(page, ctx.taskA, 'aprobar', `${E2E}validacion de eficacia`);
  detail = await page.request.get(`/api/sgi/v2/sgc/tasks/${ctx.taskA}/workflow`);
  expect((await detail.json()).data.task.status).toBe('Completada');

  const rows = dbRows(
    `SELECT status, real_date FROM sgc_incidents WHERE id = ${ctx.incidentId}`
  );
  expect(rows[0][0]).toBe('Cerrada');
  expect(rows[0][1]).not.toBeNull(); // real_date = date.today(), no un datetime

  // Y la lista lo enseña así.
  await gotoSgc(page, '/sgi/sgc/incidencias');
  const row = page.locator('#sgi-table-incidents tbody tr', { hasText: INCIDENT_TITLE });
  await expect(row).toContainText('Cerrada');

  expect(await readDialogs()).toEqual([]);
});

/**
 * Inserta un `SgcIncidentFile` con `file_path = NULL` directamente en BD:
 * un registro migrado del SGC legacy sin binario en el servidor del
 * proveedor (51 de los 351 reales). La API de subida siempre escribe un
 * archivo de verdad, así que este es el único camino para fabricar el caso
 * `is_available: false` que la UI tiene que enseñar sin ofrecer descarga.
 * @param {number} incidentId
 * @param {string} originalName
 * @returns {number} id del archivo insertado
 */
function insertUnavailableIncidentFile(incidentId, originalName) {
  const src = [
    'import json',
    'from itcj2.database import SessionLocal',
    'from itcj2.apps.sgi.sgc.models.incidents import SgcIncidentFile',
    'db = SessionLocal()',
    'try:',
    '    row = SgcIncidentFile(',
    `        incident_id=${incidentId},`,
    '        file_path=None,',
    `        original_name=${JSON.stringify(originalName)},`,
    "        mime_type='application/pdf',",
    '        size_bytes=None,',
    '    )',
    '    db.add(row)',
    '    db.commit()',
    '    db.refresh(row)',
    '    print(json.dumps({"id": row.id}))',
    'finally:',
    '    db.close()',
  ].join('\n');
  return JSON.parse(runPy(src).trim()).id;
}

// `.serial`: la segunda prueba depende del adjunto que sube la primera (sigue
// visible con su enlace de descarga tras insertar el registro sin binario).
/**
 * ¿Sigue en el disco del backend el directorio de adjuntos de una incidencia?
 * Devuelve la cadena que imprime Python: 'True' o 'False'.
 *
 * Se pregunta por `upload_service.resolve_dir` y no por una ruta escrita a
 * mano: es el mismo helper con el que la app decide dónde guarda, así que si
 * el contrato de la ruta cambiara, la comprobación cambia con él.
 * @param {number} incidentId
 * @returns {string}
 */
function enDisco(incidentId) {
  return runPy([
    'from itcj2.apps.sgi.sgc.services import upload_service',
    `print(upload_service.resolve_dir('incidents', ${incidentId}).is_dir())`,
  ].join('\n')).trim();
}

test.describe.serial('adjuntos de la incidencia (351 reales migrados del SGC legacy, algunos sin binario)', () => {
  const UPLOADED_NAME = `${E2E}adjunto_disponible.pdf`;
  const MISSING_NAME = `${E2E}adjunto_sin_binario.pdf`;

  test('el icono de la fila abre el modal, sube un adjunto y lo lista', async ({ page }) => {
    const readDialogs = await trapNativeDialogs(page);
    expect(ctx.incidentId).toBeGreaterThan(0);

    await gotoSgc(page, '/sgi/sgc/incidencias');
    const row = page.locator('#sgi-table-incidents tbody tr', { hasText: INCIDENT_TITLE });
    await expect(row).toBeVisible();

    // El icono de archivos es una ACCIÓN DE FILA (igual que "duplicar" en
    // programas), no una columna: incidencias no tiene página de detalle a la
    // que enlazar, y `GET /incidents` no trae un `files_count` por fila con el
    // que pintar un contador de verdad.
    const filesBtn = row.locator('[data-sgi-row-action="files"]');
    await expect(filesBtn).toBeVisible();

    const listed = page.waitForResponse(
      (r) => r.url().includes(`/incidents/${ctx.incidentId}/files`) && r.request().method() === 'GET'
    );
    await filesBtn.click();

    const modal = page.locator('#sgi-files-modal');
    await expect(modal).toBeVisible();
    await expect(modal.locator('[data-sgi-files-title]')).toContainText(INCIDENT_TITLE);
    expect((await listed).status()).toBe(200);
    await expect(modal.locator('.sgi-files-empty')).toContainText('no tiene archivos adjuntos');

    await modal.locator('[data-sgi-files-input]').setInputFiles({
      name: UPLOADED_NAME,
      mimeType: 'application/pdf',
      buffer: Buffer.from('contenido de prueba e2e'),
    });
    const uploaded = page.waitForResponse(
      (r) => r.url().includes(`/incidents/${ctx.incidentId}/files`) && r.request().method() === 'POST'
    );
    await modal.locator('[data-sgi-files-upload]').click();
    expect((await uploaded).status()).toBe(201);

    const item = modal.locator('.sgi-files-item', { hasText: UPLOADED_NAME });
    await expect(item).toBeVisible();
    // Disponible: enlace de descarga por ID, nunca por nombre.
    const link = item.locator('a[href*="/download"]');
    await expect(link).toHaveCount(1);
    await expect(link).toHaveAttribute(
      'href', new RegExp(`/api/sgi/v2/sgc/incidents/files/\\d+/download$`)
    );

    expect(await readDialogs()).toEqual([]);
  });

  test('un adjunto sin binario se enseña sin ofrecer descarga', async ({ page }) => {
    expect(ctx.incidentId).toBeGreaterThan(0);
    insertUnavailableIncidentFile(ctx.incidentId, MISSING_NAME);

    await gotoSgc(page, '/sgi/sgc/incidencias');
    const row = page.locator('#sgi-table-incidents tbody tr', { hasText: INCIDENT_TITLE });

    const listed = page.waitForResponse(
      (r) => r.url().includes(`/incidents/${ctx.incidentId}/files`) && r.request().method() === 'GET'
    );
    await row.locator('[data-sgi-row-action="files"]').click();
    expect((await listed).status()).toBe(200);

    const modal = page.locator('#sgi-files-modal');
    const item = modal.locator('.sgi-files-item', { hasText: MISSING_NAME });
    await expect(item).toBeVisible();

    // Ni rastro de un enlace de descarga: el backend respondería 404 con este
    // registro (`file_path IS NULL`), así que la UI no lo ofrece.
    await expect(item.locator('a[href*="/download"]')).toHaveCount(0);

    // En su lugar, el icono apagado con el motivo — mismo criterio que
    // `.sgi-file-none` en documents/document-list.js.
    const unavailable = item.locator('.sgi-file-none');
    await expect(unavailable).toHaveCount(1);
    await expect(unavailable).toHaveAttribute('title', /sin archivo/i);

    // El adjunto disponible de la prueba anterior sigue mostrando su enlace:
    // la ausencia de descarga es por archivo, no por incidencia entera.
    const available = modal.locator('.sgi-files-item', { hasText: UPLOADED_NAME });
    await expect(available.locator('a[href*="/download"]')).toHaveCount(1);
  });

  // Va el ÚLTIMO del archivo a propósito: llama a `cleanupSgc()`, que es
  // justo lo que se prueba, y deja la incidencia de este describe borrada.
  test('el barrido del harness se lleva también el fichero del disco', async () => {
    expect(ctx.incidentId).toBeGreaterThan(0);

    // El SQL crudo de `cleanupSgc` arrastra `sgc_incident_files` por
    // CASCADE pero NO el disco, así que cada corrida dejaba un
    // `e2e_adjunto_disponible.pdf` huérfano en
    // `instance/apps/sgi/sgc/incidents/{id}/`. Eran 15 acumulados, uno por
    // corrida: la basura que el guard nuevo de `IncidentService.delete` viene a
    // evitar, reintroducida por el propio harness al saltarse el service.
    expect(enDisco(ctx.incidentId), 'la prueba anterior no dejó nada en disco').toBe('True');

    cleanupSgc();

    expect(
      enDisco(ctx.incidentId),
      'cleanupSgc borró la fila pero dejó el directorio del adjunto en disco'
    ).toBe('False');
  });
});

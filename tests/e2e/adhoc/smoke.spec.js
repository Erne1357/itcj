// @ts-check
/**
 * smoke — las 30 URLs de página de `adhoc` (plan §4: 26 rutas, de las cuales
 * `/adhoc/reportes/{tipo}` son 5) responden 200 con el usuario admin del
 * global-setup y renderizan contenido dentro del shell `main#adhoc-main`.
 *
 * Cinco de esas URLs llevan un id en la ruta, así que el spec crea sus propios
 * datos (flujo con 2 pasos, incidencia, evento de programa, año de indicadores
 * y una tarea) con prefijo `e2e_` y los borra en `afterAll`.
 *
 * Las rutas se assertean como `expect([200, 403]).toContain(status)` — patrón
 * de `helpdesk/smoke.spec.js` — para no acoplar el test a qué permisos tiene
 * hoy la organización real; el 200 es lo esperado con el admin y el 403 es la
 * página de error de la app, no un 404/500. Un 404 o un 500 sí revientan.
 */
const { test, expect } = require('@playwright/test');
const {
  ADHOC_SHELL,
  E2E,
  E2E_YEAR_MIN,
  gotoAdhoc,
  cleanupAdhoc,
  newApiContext,
} = require('./_helpers');

/** Ids creados en beforeAll para las URLs paramétricas. */
const ids = {
  flow: 0,
  incident: 0,
  program: 0,
  year: 0,
  task: 0,
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  cleanupAdhoc(); // restos de una corrida abortada
  const api = await newApiContext();
  try {
    const flow = await api.post('/approval-flows', { name: `${E2E}flujo_smoke` }, [200, 201]);
    ids.flow = flow.body.data.id;
    await api.put(`/approval-flows/${ids.flow}/steps`, {
      steps: [
        { name: `${E2E}paso_1`, days_limit: 3, step_order: 1 },
        { name: `${E2E}paso_2`, days_limit: 3, step_order: 2 },
      ],
    });

    const inc = await api.post('/incidents', { items: [{ title: `${E2E}incidencia_smoke` }] }, [201]);
    ids.incident = inc.body.data[0].id;

    const prog = await api.postForm(
      '/program-events',
      { payload: JSON.stringify({ events: [{ title: `${E2E}evento_smoke` }] }) },
      [201]
    );
    ids.program = prog.body.data[0].id;

    const year = await api.post('/indicator-years', { years: [E2E_YEAR_MIN] }, [201]);
    ids.year = year.body.data[0].id;

    const task = await api.post(
      '/tasks',
      {
        parent_type: 'incident',
        parent_id: ids.incident,
        tasks: [{ description: `${E2E}tarea_smoke` }],
      },
      [200, 201]
    );
    ids.task = task.body.data[0].id;
  } finally {
    await api.dispose();
  }
});

test.afterAll(() => {
  cleanupAdhoc();
});

test('la raíz /adhoc redirige al tablero', async ({ page }) => {
  const res = await page.request.get('/adhoc/', { maxRedirects: 0 });
  expect(res.status()).toBe(302);
  expect(res.headers()['location']).toContain('/adhoc/dashboard');
});

test('las 29 páginas restantes responden y renderizan contenido', async ({ page }) => {
  const routes = [
    '/adhoc/dashboard',
    '/adhoc/panel',
    '/adhoc/panel/procesos',
    '/adhoc/panel/areas',
    '/adhoc/panel/usuarios',
    '/adhoc/panel/configuracion',
    '/adhoc/panel/correo',
    '/adhoc/documentos',
    '/adhoc/documentos/panel',
    '/adhoc/documentos/categorias',
    '/adhoc/documentos/clasificaciones',
    '/adhoc/documentos/flujos',
    `/adhoc/documentos/flujos/${ids.flow}/pasos`,
    '/adhoc/incidencias',
    '/adhoc/incidencias/categorias',
    `/adhoc/incidencias/${ids.incident}/tareas`,
    '/adhoc/programas',
    '/adhoc/programas/categorias',
    `/adhoc/programas/${ids.program}/tareas`,
    // La pantalla de asignación exige el id de su destino en la query: sin él
    // responde 400 a propósito (el legacy renderizaba un formulario que al
    // guardar decía "no se detectó el origen").
    `/adhoc/asignaciones?action=assign&task_id=${ids.task}`,
    '/adhoc/indicadores',
    `/adhoc/indicadores/${ids.year}/tablero`,
    `/adhoc/indicadores/${ids.year}/seguimiento`,
    '/adhoc/reportes',
    '/adhoc/reportes/area_usuarios',
    '/adhoc/reportes/usuarios_tareas',
    '/adhoc/reportes/usuarios_documentos',
    '/adhoc/reportes/documentos_usuarios',
    '/adhoc/reportes/documentos_notas',
  ];
  expect(routes).toHaveLength(29); // + la raíz = las 30 URLs del plan §4

  const failures = [];
  for (const route of routes) {
    const res = await page.goto(route, { waitUntil: 'domcontentloaded' });
    const status = res ? res.status() : 0;
    if (![200, 403].includes(status)) {
      failures.push(`${route} -> ${status}`);
      continue;
    }
    if (status !== 200) continue;
    const shell = page.locator(ADHOC_SHELL);
    if ((await shell.count()) !== 1) {
      failures.push(`${route} -> 200 pero sin ${ADHOC_SHELL}`);
      continue;
    }
    const text = (await shell.innerText()).trim();
    if (text.length === 0) failures.push(`${route} -> 200 pero el shell está vacío`);
  }
  expect(failures, `Rutas rotas:\n${failures.join('\n')}`).toEqual([]);
});

test('el nav de la app navega con hx-boost (sin full reload)', async ({ page }) => {
  await gotoAdhoc(page, '/adhoc/dashboard');

  const nav = page.locator('nav.adhoc-nav[hx-boost="true"]');
  await expect(nav).toBeVisible();

  const link = nav.locator('a.adhoc-nav-link[href="/adhoc/documentos"]');
  await expect(link).toBeVisible();
  await link.click();

  await expect(page).toHaveURL(/\/adhoc\/documentos$/);
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  // El marcador sobrevive: HTMX cambió el contenido, el documento no se recargó.
  expect(await page.evaluate(() => /** @type {any} */ (window).__booted === true)).toBe(true);
});

test('un anónimo es redirigido al login, no a la página', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const res = await ctx.request.get('/adhoc/dashboard', { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(res.headers()['location']).toContain('/itcj/login');
  } finally {
    await ctx.close();
  }
});

test('la API de adhoc no responde 200 sin cookie', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    for (const url of [
      '/api/adhoc/v2/documents',
      '/api/adhoc/v2/incidents',
      '/api/adhoc/v2/tasks/mine',
      '/api/adhoc/v2/indicator-years',
    ]) {
      const res = await ctx.request.get(url, { maxRedirects: 0 });
      expect(res.status(), `${url} respondió ${res.status()} sin cookie`).not.toBe(200);
    }
  } finally {
    await ctx.close();
  }
});

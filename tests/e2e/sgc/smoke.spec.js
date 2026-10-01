// @ts-check
/**
 * smoke — las 30 URLs de página de `sgc` (plan §4: 26 rutas, de las cuales
 * `/sgi/sgc/reportes/{tipo}` son 5) responden 200 con el usuario admin del
 * global-setup y renderizan contenido dentro del shell `main#sgi-main`.
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
  SGC_SHELL,
  E2E,
  E2E_YEAR_MIN,
  gotoSgc,
  cleanupSgc,
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
  cleanupSgc(); // restos de una corrida abortada
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
  cleanupSgc();
});

test('la raíz /sgi/sgc redirige al tablero', async ({ page }) => {
  const res = await page.request.get('/sgi/sgc/', { maxRedirects: 0 });
  expect(res.status()).toBe(302);
  expect(res.headers()['location']).toContain('/sgi/sgc/dashboard');
});

test('las 29 páginas restantes responden y renderizan contenido', async ({ page }) => {
  const routes = [
    '/sgi/sgc/dashboard',
    '/sgi/sgc/panel',
    '/sgi/sgc/panel/procesos',
    '/sgi/sgc/panel/areas',
    '/sgi/sgc/panel/usuarios',
    '/sgi/sgc/panel/configuracion',
    '/sgi/sgc/panel/correo',
    '/sgi/sgc/documentos',
    '/sgi/sgc/documentos/panel',
    '/sgi/sgc/documentos/categorias',
    '/sgi/sgc/documentos/clasificaciones',
    '/sgi/sgc/documentos/flujos',
    `/sgi/sgc/documentos/flujos/${ids.flow}/pasos`,
    '/sgi/sgc/incidencias',
    '/sgi/sgc/incidencias/categorias',
    `/sgi/sgc/incidencias/${ids.incident}/tareas`,
    '/sgi/sgc/programas',
    '/sgi/sgc/programas/categorias',
    `/sgi/sgc/programas/${ids.program}/tareas`,
    // La pantalla de asignación exige el id de su destino en la query: sin él
    // responde 400 a propósito (el legacy renderizaba un formulario que al
    // guardar decía "no se detectó el origen").
    `/sgi/sgc/asignaciones?action=assign&task_id=${ids.task}`,
    '/sgi/sgc/indicadores',
    `/sgi/sgc/indicadores/${ids.year}/tablero`,
    `/sgi/sgc/indicadores/${ids.year}/seguimiento`,
    '/sgi/sgc/reportes',
    '/sgi/sgc/reportes/area_usuarios',
    '/sgi/sgc/reportes/usuarios_tareas',
    '/sgi/sgc/reportes/usuarios_documentos',
    '/sgi/sgc/reportes/documentos_usuarios',
    '/sgi/sgc/reportes/documentos_notas',
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
    const shell = page.locator(SGC_SHELL);
    if ((await shell.count()) !== 1) {
      failures.push(`${route} -> 200 pero sin ${SGC_SHELL}`);
      continue;
    }
    const text = (await shell.innerText()).trim();
    if (text.length === 0) failures.push(`${route} -> 200 pero el shell está vacío`);
  }
  expect(failures, `Rutas rotas:\n${failures.join('\n')}`).toEqual([]);
});

test('el nav de la app navega con hx-boost (sin full reload)', async ({ page }) => {
  await gotoSgc(page, '/sgi/sgc/dashboard');

  // El `hx-boost` ya no vive en el <nav>: lo declara la caja que se intercambia
  // (#sgi-root en base_sgc.html) y lo heredan TODOS los enlaces de la app,
  // no solo los cuatro de la barra. Ver navigation-integrity.spec.js.
  await expect(page.locator('#sgi-root[hx-boost="true"]')).toBeAttached();

  const nav = page.locator('nav.sgi-nav');
  await expect(nav).toBeVisible();

  const link = nav.locator('a.sgi-nav-link[href="/sgi/sgc/documentos"]');
  await expect(link).toBeVisible();
  await link.click();

  await expect(page).toHaveURL(/\/sgi/sgc\/documentos$/);
  await expect(page.locator(SGC_SHELL)).toBeVisible();
  // El marcador sobrevive: HTMX cambió el contenido, el documento no se recargó.
  expect(await page.evaluate(() => /** @type {any} */ (window).__booted === true)).toBe(true);
});

test('un anónimo es redirigido al login, no a la página', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const res = await ctx.request.get('/sgi/sgc/dashboard', { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    expect(res.headers()['location']).toContain('/itcj/login');
  } finally {
    await ctx.close();
  }
});

test('la API de sgc no responde 200 sin cookie', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    for (const url of [
      '/api/sgi/v2/sgc/documents',
      '/api/sgi/v2/sgc/incidents',
      '/api/sgi/v2/sgc/tasks/mine',
      '/api/sgi/v2/sgc/indicator-years',
    ]) {
      const res = await ctx.request.get(url, { maxRedirects: 0 });
      expect(res.status(), `${url} respondió ${res.status()} sin cookie`).not.toBe(200);
    }
  } finally {
    await ctx.close();
  }
});

// @ts-check
/**
 * Ciclo de vida del JS de página bajo el intercambio con idiomorph.
 *
 * `{% block extra_js %}` vive DENTRO de `#adhoc-root`, así que los módulos de
 * sección entran y salen con la pantalla. Con `morph:outerHTML`, idiomorph
 * empareja nodo a nodo, y para un `<script>` sin `id` el emparejamiento es por
 * POSICIÓN: al pasar de una pantalla con un módulo a otra con otro módulo,
 * reescribe el `src` del mismo nodo. **Un `<script>` ya ejecutado no se vuelve
 * a ejecutar porque le cambien el `src`**, así que la pantalla de destino se
 * pinta y se queda muerta.
 *
 * Y al revés: viniendo de una pantalla SIN módulos (el panel), el `<script>`
 * entra como nodo nuevo y sí se ejecuta — así que el mismo par de pantallas se
 * comporta distinto según por dónde hayas pasado antes. `work/work-items.js`
 * lo tiene documentado por escrito: "a veces se re-ejecuta y a veces no".
 *
 * Los casos de aquí recorren los dos caminos y comprueban que el módulo de
 * destino QUEDA VIVO, no que el HTML llegó (eso ya lo cubre boosted-head).
 */
const { test, expect } = require('@playwright/test');
const { gotoAdhoc, ADHOC_SHELL, newApiContext, cleanupAdhoc, E2E } = require('./_helpers');

// Dos casos dependen de poder abrir el alta de un catálogo. Antes hacían
// `test.skip` si el botón no estaba, lo que confundía DOS cosas distintas: que
// el usuario de prueba no tenga permiso (motivo legítimo para saltar) y que la
// pantalla esté muerta (que es justo el defecto que el caso persigue). Ahora se
// comprueba el permiso UNA vez, contra la API, y si lo hay el caso es
// obligatorio.
let PUEDE_CREAR = false;

test.beforeAll(async () => {
  await cleanupAdhoc();
  const api = await newApiContext();
  try {
    const alta = await api.post(
      '/document-categories',
      { items: [{ name: `${E2E}cat_ciclo_de_vida` }] },
      [200, 201, 403]
    );
    PUEDE_CREAR = alta.status !== 403;
  } finally {
    await api.dispose();
  }
});

test.afterAll(() => cleanupAdhoc());

test.use({ viewport: { width: 1600, height: 900 } });

/** Navega por un enlace y espera a que HTMX asiente el intercambio. */
async function navegar(page, selector) {
  await page.click(selector);
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  await page.waitForTimeout(900);
}

/** Namespaces que cada módulo publica en `window` al inicializarse. */
const vivos = (page) =>
  page.evaluate(() => {
    const out = {};
    for (const k of Object.keys(window)) {
      if (/^Adhoc[A-Z]/.test(k)) out[k] = true;
    }
    return out;
  });

test.describe('el módulo de la pantalla de destino queda vivo', () => {
  test('catálogo de colores → usuarios (un módulo por otro, misma posición)', async ({ page }) => {
    // Los dos son pantallas con EXACTAMENTE un <script> de módulo, así que es
    // el caso donde idiomorph reescribe el src en vez de reemplazar el nodo.
    await gotoAdhoc(page, '/adhoc/panel/areas');
    await expect(page.locator('[data-adhoc-color-catalog]')).toBeAttached();

    await navegar(page, 'a.adhoc-back');
    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/usuarios"]');

    // Si users.js no corrió, la tabla se queda con su fila de "sin registros"
    // aunque la API tenga usuarios, y el selector de rol no responde.
    await expect(page.locator('[data-adhoc-users]')).toBeAttached();
    expect(
      await vivos(page),
      'AdhocPanelUsers no se publicó: users.js no llegó a correr'
    ).toHaveProperty('AdhocPanelUsers');
  });

  test('documentos → tablero de tareas (dos módulos por uno)', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/documentos');
    expect(await vivos(page)).toHaveProperty('AdhocDocumentList');

    await navegar(page, '.adhoc-nav-link[href="/adhoc/dashboard"]');
    expect(await vivos(page), 'dashboard.js no llegó a correr').toHaveProperty('AdhocDashboard');
  });

  test('de un catálogo a otro, compartiendo el mismo módulo', async ({ page }) => {
    // Las cinco pantallas de catálogo cargan el MISMO shared/catalog-crud.js.
    // Idiomorph conserva ese <script> (mismo id, mismo src) y NO lo re-ejecuta:
    // el módulo tiene que reengancharse por `htmx:afterSettle`, no por volver a
    // ejecutarse. Lo que sí se sustituye es la <section>, cuyo id lleva el
    // recurso; si no lo llevara, los listeners del catálogo anterior seguirían
    // colgados del mismo nodo y cada acción se dispararía dos veces.
    await gotoAdhoc(page, '/adhoc/panel/configuracion');
    await navegar(page, 'a[href="/adhoc/documentos/categorias"]');
    await expect(page.locator('[data-adhoc-catalog]')).toHaveAttribute(
      'data-adhoc-resource',
      'document-categories'
    );

    // El "Volver" de un catalogo lleva a SU seccion (/adhoc/documentos), no a
    // configuracion: para llegar al segundo catalogo se pasa por la barra.
    await navegar(page, '.adhoc-nav-link[href="/adhoc/panel"]');
    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/configuracion"]');
    await navegar(page, 'a[href="/adhoc/documentos/clasificaciones"]');

    const seccion = page.locator('[data-adhoc-catalog]');
    await expect(seccion, 'la sección es la de la pantalla nueva').toHaveAttribute(
      'data-adhoc-resource',
      'document-classifications'
    );

    // Prueba viva: el botón de alta abre SU modal. Si catalog-crud no reenganchó
    // la sección nueva, el clic no hace nada; si quedaron listeners del catálogo
    // anterior, abriría el modal equivocado.
    test.skip(!PUEDE_CREAR, 'el usuario de prueba no tiene permiso de alta en catálogos');
    const alta = page.locator('[data-adhoc-catalog-new]');
    await expect(alta, 'el usuario puede crear pero el botón de alta no se pintó').toBeVisible();
    await alta.click();
    await expect(page.locator('[data-adhoc-catalog-modal="document-classifications"]')).toBeVisible();
    await expect(page.locator('[data-adhoc-catalog-modal="document-categories"]')).toHaveCount(0);
  });
});

test.describe('nada se acumula al ir y venir', () => {
  test('los callbacks de onReady no crecen sin límite', async ({ page }) => {
    // Cada re-ejecución de un módulo llamaba a `AdhocUtils.onReady()` otra vez y
    // el registro anterior nunca se retiraba: `htmx:afterSettle` acababa
    // recorriendo callbacks de pantallas por las que ya no estás, con closures
    // que apuntan a nodos que ya no existen.
    await gotoAdhoc(page, '/adhoc/panel');
    const antes = await page.evaluate(() => window.AdhocUtils.debugRegistros().length);

    for (let i = 0; i < 3; i++) {
      await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/areas"]');
      await navegar(page, 'a.adhoc-back');
      await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/usuarios"]');
      await navegar(page, 'a.adhoc-back');
    }

    const despues = await page.evaluate(() => window.AdhocUtils.debugRegistros().length);
    expect(
      despues,
      `los registros de onReady pasaron de ${antes} a ${despues} en 12 navegaciones`
    ).toBeLessThanOrEqual(antes + 4);
  });

  test('un modal abierto no deja el fondo bloqueado al navegar', async ({ page }) => {
    // El nodo del modal se va con el intercambio, así que `closeModal()` nunca
    // corre y el `<body>` se queda con la clase de bloqueo (o con el
    // `overflow:hidden` + `padding-right` en línea que pone Bootstrap): la
    // pantalla siguiente aparece sin poder desplazarse.
    await gotoAdhoc(page, '/adhoc/panel/configuracion');
    await navegar(page, 'a[href="/adhoc/documentos/categorias"]');

    test.skip(!PUEDE_CREAR, 'el usuario de prueba no tiene permiso de alta en catálogos');
    const alta = page.locator('[data-adhoc-catalog-new]');
    await expect(alta, 'el usuario puede crear pero el botón de alta no se pintó').toBeVisible();
    await alta.click();
    await expect(page.locator('[data-adhoc-catalog-modal="document-categories"]')).toBeVisible();

    // Con el modal abierto el velo tapa la barra, así que la única navegación
    // que un usuario puede lanzar de verdad es la del botón atrás. Es además el
    // camino que más se da: abrir el alta, cambiar de idea y volver.
    await page.goBack();
    await expect(page.locator(ADHOC_SHELL)).toBeVisible();
    await page.waitForTimeout(900);

    const estado = await page.evaluate(() => ({
      clases: document.body.className,
      overflow: document.body.style.overflow,
      padding: document.body.style.paddingRight,
      velos: document.querySelectorAll('.modal-backdrop').length,
      abiertos: document.querySelectorAll('.modal.show, .adhoc-modal.is-open').length,
    }));

    expect(estado.clases, 'el body se quedó con la clase de bloqueo').not.toMatch(/modal-open/);
    expect(estado.overflow, 'el body se quedó sin scroll').not.toBe('hidden');
    expect(estado.velos, 'quedó un velo huérfano').toBe(0);
    expect(estado.abiertos, 'quedó un modal abierto de la pantalla anterior').toBe(0);
  });
});

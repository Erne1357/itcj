// @ts-check
// Regresion: con hx-boost, HTMX sustituye solo el <body>. Sin la extension
// head-support, el <link> del bloque `extra_css` de la pagina destino NUNCA
// llega y el <head> se queda con el CSS de la ultima pagina cargada a pulso.
//
// Sintomas que producia y que ninguna otra prueba detectaba, porque el HTML era
// correcto y los endpoints respondian 200:
//   - el tablero de tareas se veia sin estilo al volver desde el panel;
//   - el modal de "Añadir Nuevo(s)" en Procesos parecia no abrir, cuando en
//     realidad abria invisible porque sus estilos viven en la hoja de la pagina.
const { test, expect } = require('@playwright/test');
const { gotoAdhoc } = require('./_helpers');

/** Hojas de /static/adhoc/ presentes en el <head>, sin el sufijo ?v=. */
const hojas = (page) =>
  page.evaluate(() =>
    Array.from(document.querySelectorAll('link[rel=stylesheet]'))
      .map((l) => (l.getAttribute('href') || '').split('?')[0])
      .filter((h) => h.includes('/static/adhoc/'))
      .sort()
  );

/** Navega por un enlace boosted y espera a que HTMX asiente el intercambio. */
async function navegar(page, href) {
  await Promise.all([
    page.waitForFunction((h) => location.pathname === h, href, { timeout: 10000 }),
    page.click(`a[href="${href}"]`),
  ]);
  await page.waitForTimeout(400);
}

test('la hoja de cada pagina se carga al navegar con hx-boost', async ({ page }) => {
  // Referencia: como se ve Procesos cargado a pulso.
  await gotoAdhoc(page, '/adhoc/panel/procesos');
  const directo = await hojas(page);
  expect(directo.some((h) => h.includes('color-catalog.css')), 'la carga directa debe traer su hoja').toBe(true);

  // El mismo destino, alcanzado navegando: debe traer exactamente las mismas hojas.
  await gotoAdhoc(page, '/adhoc/panel');
  await navegar(page, '/adhoc/panel/procesos');
  expect(await hojas(page)).toEqual(directo);
});

test('el tablero trae su hoja cuando se llega navegando desde otra pagina', async ({ page }) => {
  // Referencia primero, en su propia visita.
  await gotoAdhoc(page, '/adhoc/dashboard');
  const referencia = await hojas(page);

  // Clave: la carga completa es de OTRA pagina, asi que la hoja del tablero no
  // esta en el <head> de partida. Empezar por el propio tablero no prueba nada:
  // su hoja ya estaria puesta desde el principio y el fallo pasa desapercibido.
  await gotoAdhoc(page, '/adhoc/panel');
  await navegar(page, '/adhoc/panel/procesos');
  await navegar(page, '/adhoc/panel');
  await navegar(page, '/adhoc/dashboard');

  expect(await hojas(page), 'el tablero llego sin su hoja').toEqual(referencia);
});

test('el modal de alta abre tambien cuando se llega navegando', async ({ page }) => {
  await gotoAdhoc(page, '/adhoc/panel');
  await navegar(page, '/adhoc/panel/procesos');

  const boton = page.locator('[data-adhoc-catalog-new]');
  if ((await boton.count()) === 0) test.skip(true, 'el usuario de prueba no tiene permiso de alta');

  await boton.click();
  const modal = page.locator('[data-adhoc-color-modal="new"]');
  await expect(modal).toBeVisible();
});

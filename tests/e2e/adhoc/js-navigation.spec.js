// @ts-check
/**
 * La navegación fluida tiene que llegar también donde empieza el JavaScript.
 *
 * `hx-boost` cubre todo `<a href>` que venga en el HTML servido, pero no cubre
 * nada de lo que hace el JS — y las transiciones centrales del flujo de trabajo
 * son todas por JS:
 *
 *   · la fila de un año → su tablero o su seguimiento   (indicators/years.js)
 *   · una incidencia o un evento → sus tareas           (work/work-items.js)
 *   · una tarea → /adhoc/asignaciones                   (work/tasks.js)
 *   · asignaciones → volver                             (work/assignments.js)
 *   · tras aprobar o rechazar → recarga del tablero     (dashboard/dashboard.js)
 *
 * El ciclo tarea → asignación → vuelta encadenaba TRES recargas duras seguidas
 * dentro de una app que por lo demás navega con morph.
 *
 * También se cubre aquí el indicador de carga: no había ninguno, y al quitar el
 * "flashazo" de la recarga el usuario se quedó sin señal de que algo pasaba.
 * Tiene que aparecer solo si la respuesta tarda; en una red rápida no debe
 * llegar a verse.
 */
const { test, expect } = require('@playwright/test');
const {
  gotoAdhoc,
  ADHOC_SHELL,
  newApiContext,
  cleanupAdhoc,
  E2E,
  E2E_YEAR_MIN,
} = require('./_helpers');

/** Año del rango reservado (2090-2099) que `cleanupAdhoc()` barre al terminar. */
const ANIO = E2E_YEAR_MIN + 3;

// Incidencias de la suite del ATRAS (al final del archivo). El listado pagina
// de 25 en 25 EN EL SERVIDOR, asi que para comprobar que el pager responde hace
// falta que haya mas de una pagina, y para comprobar que el filtro responde
// hace falta una fila que se pueda aislar por titulo. Con los datos reales de
// la base eso saldria o no segun cuantas incidencias hubiera ese dia, que es
// justo lo que no puede decidir si un caso de regresion pasa.
const TITULO_UNICO = `${E2E}atras_solo_esta_incidencia`;
const LOTE_ATRAS = [{ title: TITULO_UNICO }].concat(
  Array.from({ length: 26 }, (_, i) => ({
    title: `${E2E}atras_lote_${String(i + 1).padStart(2, '0')}`,
  }))
);

// El tablero de indicadores necesita un año para tener filas. Antes los dos
// casos hacían `test.skip` si no había ninguno — y en una base recién sembrada
// eso son dos casos en verde que no prueban nada. Se crea aquí y se borra al
// final, como el resto de la suite de adhoc.
test.beforeAll(async () => {
  await cleanupAdhoc();
  const api = await newApiContext();
  try {
    await api.post('/indicator-years', { years: [ANIO] }, [200, 201]);
    await api.post('/incidents', { items: LOTE_ATRAS }, [200, 201]);
  } finally {
    await api.dispose();
  }
});

test.afterAll(() => cleanupAdhoc());

test.use({ viewport: { width: 1600, height: 900 } });

/** true si NO hubo recarga completa desde el último `gotoAdhoc`. */
const sinRecarga = (page) => page.evaluate(() => !!(/** @type {any} */ (window).__booted));

async function asentar(page) {
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  await page.waitForTimeout(700);
}

test.describe('AdhocUtils.navigate', () => {
  test('existe y navega sin recargar el documento', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');

    await page.evaluate(() => window.AdhocUtils.navigate('/adhoc/panel/usuarios'));
    await asentar(page);

    await expect(page).toHaveURL(/\/adhoc\/panel\/usuarios$/);
    expect(await sinRecarga(page), 'navigate() recargó el documento').toBe(true);
    await expect(page.locator('[data-adhoc-users]')).toBeAttached();
  });

  test('deja entrada en el historial y el atrás funciona', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');
    await page.evaluate(() => window.AdhocUtils.navigate('/adhoc/panel/areas'));
    await asentar(page);
    await expect(page).toHaveURL(/\/adhoc\/panel\/areas$/);

    await page.goBack();
    await asentar(page);
    await expect(page).toHaveURL(/\/adhoc\/panel$/);
    await expect(page.locator('a.adhoc-tile[href="/adhoc/panel/areas"]')).toBeVisible();
  });

  test('trae la hoja de estilos de la pantalla de destino', async ({ page }) => {
    // Mismo contrato que un enlace boosted: head-support tiene que actuar.
    await gotoAdhoc(page, '/adhoc/panel');
    await page.evaluate(() => window.AdhocUtils.navigate('/adhoc/panel/usuarios'));
    await asentar(page);

    const hojas = await page.evaluate(() =>
      Array.from(document.querySelectorAll('link[rel=stylesheet]'))
        .map((l) => (l.getAttribute('href') || '').split('?')[0])
        .filter((h) => h.includes('/static/adhoc/'))
    );
    expect(hojas.some((h) => h.includes('panel/users.css'))).toBe(true);
    expect(hojas.some((h) => h.includes('panel/panel.css'))).toBe(false);
  });

  test('apaga el indicador de carga al terminar', async ({ page }) => {
    // Regresion: navigate() fabrica un <a> y le hace clic. Si ese nodo se retira
    // ANTES de que llegue la respuesta, `htmx:afterRequest` se emite sobre un
    // nodo ya desconectado, no burbujea hasta `document`, y el contador del
    // indicador nunca baja: la barra se queda encendida para el resto de la
    // sesion y tapa el borde superior de todas las pantallas.
    await gotoAdhoc(page, '/adhoc/panel');
    await page.evaluate(() => window.AdhocUtils.navigate('/adhoc/panel/areas'));
    await asentar(page);

    expect(
      await page.evaluate(() => document.body.classList.contains('adhoc-loading')),
      'el <body> se quedo marcado como cargando'
    ).toBe(false);
    expect(
      await page.evaluate(() => Number(getComputedStyle(document.getElementById('adhoc-progress')).opacity))
    ).toBeLessThan(0.05);
  });

  test('no deja anclas de navegacion sueltas en el DOM', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');
    for (const destino of ['/adhoc/panel/areas', '/adhoc/panel', '/adhoc/panel/usuarios']) {
      await page.evaluate((u) => window.AdhocUtils.navigate(u), destino);
      await asentar(page);
    }
    expect(await page.locator('[data-adhoc-nav]').count(), 'quedaron anclas de navigate()').toBe(0);
  });
});

test.describe('las transiciones del flujo de trabajo son fluidas', () => {
  test('la fila de un año abre su tablero sin recargar', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/indicadores');

    const fila = page.locator('tr[data-id]', { hasText: String(ANIO) }).first();
    await expect(fila, `no apareció la fila del año ${ANIO} que crea beforeAll`).toBeVisible();

    await fila.click();
    await asentar(page);

    await expect(page).toHaveURL(/\/adhoc\/indicadores\/\d+\/(tablero|seguimiento)$/);
    expect(await sinRecarga(page), 'la fila del año recargó la página').toBe(true);
  });

  test('el año se puede abrir en otra pestaña (es un enlace de verdad)', async ({ page }) => {
    // Una fila con `role="link"` y un salto por JS no se puede abrir con
    // Ctrl+clic, no enseña el destino en la barra de estado y no se anuncia
    // como enlace. La primera celda tiene que llevar un <a href> real.
    await gotoAdhoc(page, '/adhoc/indicadores');

    const fila = page.locator('tr[data-id]', { hasText: String(ANIO) }).first();
    await expect(fila, `no apareció la fila del año ${ANIO} que crea beforeAll`).toBeVisible();

    const enlace = fila.locator('a[href]').first();
    await expect(enlace, 'la fila del año no tiene ningún enlace real').toHaveCount(1);
    expect(await enlace.getAttribute('href')).toMatch(/\/adhoc\/indicadores\/\d+\//);
  });

  test('no queda ningún salto duro por JS en los módulos', async ({ page }) => {
    // Guarda estructural: si alguien vuelve a escribir `window.location.href`
    // para una ruta de /adhoc, este caso lo caza sin depender de que haya datos.
    await gotoAdhoc(page, '/adhoc/dashboard');

    const MODULOS = [
      'js/indicators/years.js',
      'js/work/work-items.js',
      'js/work/tasks.js',
      'js/work/assignments.js',
      'js/dashboard/dashboard.js',
    ];

    const culpables = [];
    for (const modulo of MODULOS) {
      const res = await page.request.get(`/static/adhoc/${modulo}`);
      expect(res.status(), `${modulo} no se sirve`).toBe(200);
      const fuente = await res.text();
      const lineas = fuente.split('\n');
      lineas.forEach((linea, i) => {
        if (linea.trim().startsWith('*') || linea.trim().startsWith('//')) return; // comentarios
        if (/location\.(href\s*=|assign\(|replace\(|reload\()/.test(linea)) {
          culpables.push(`${modulo}:${i + 1} ${linea.trim().slice(0, 80)}`);
        }
      });
    }
    expect(culpables, `saltos duros que quedan:\n  ${culpables.join('\n  ')}`).toEqual([]);
  });
});

test.describe('indicador de carga', () => {
  test('existe en el shell y arranca invisible', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');

    const barra = page.locator('#adhoc-progress');
    await expect(barra, 'no hay barra de progreso en el shell').toHaveCount(1);
    expect(await barra.evaluate((el) => getComputedStyle(el).opacity)).toBe('0');
  });

  test('NO se ve en una navegación rápida', async ({ page }) => {
    // Es el requisito explícito: si la respuesta llega rápido, el indicador no
    // debe llegar a aparecer, o parpadearía en cada clic y estorbaría.
    await gotoAdhoc(page, '/adhoc/panel');

    const opacidades = [];
    const muestreo = setInterval(() => {}, 0);
    clearInterval(muestreo);

    await page.click('a.adhoc-tile[href="/adhoc/panel/usuarios"]');
    for (let i = 0; i < 6; i++) {
      opacidades.push(
        await page.evaluate(() => {
          const el = document.getElementById('adhoc-progress');
          return el ? Number(getComputedStyle(el).opacity) : 0;
        })
      );
      await page.waitForTimeout(40);
    }
    await asentar(page);

    expect(
      Math.max(...opacidades),
      `la barra se vio en una navegación rápida (opacidades: ${opacidades.join(', ')})`
    ).toBeLessThan(0.05);
  });

  test('SÍ se ve cuando la respuesta tarda', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');

    // Se retrasa la respuesta de la pantalla de destino a propósito.
    await page.route('**/adhoc/panel/usuarios', async (route) => {
      await new Promise((r) => setTimeout(r, 1200));
      await route.continue();
    });

    await page.click('a.adhoc-tile[href="/adhoc/panel/usuarios"]');
    await page.waitForTimeout(700); // pasado el retardo del indicador

    const visible = await page.evaluate(() => {
      const el = document.getElementById('adhoc-progress');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { opacidad: Number(cs.opacity), ancho: el.getBoundingClientRect().width };
    });
    expect(visible, 'no hay barra de progreso').not.toBeNull();
    expect(visible.opacidad, 'la barra no apareció con la respuesta lenta').toBeGreaterThan(0.5);

    await asentar(page);
    // Y al terminar se retira.
    await expect
      .poll(async () =>
        page.evaluate(() => {
          const el = document.getElementById('adhoc-progress');
          return el ? Number(getComputedStyle(el).opacity) : 0;
        })
      )
      .toBeLessThan(0.05);
  });
});


// ============================================================================
// EL BOTÓN ATRÁS
// ============================================================================
//
// Los tres casos de "atrás" que ya existían —dos aquí arriba y uno en
// `navigation-integrity.spec.js`— navegan SIEMPRE a `/adhoc/panel`, que es una
// rejilla de tarjetas y un `<a>`: no tiene un solo módulo de JS. Comprobaban
// que el HTML se pintaba, y el HTML se pinta SIEMPRE porque sale del caché de
// historial de HTMX (`body.cloneNode(true).innerHTML` guardado en
// localStorage). Por eso llevaban toda la vida del proyecto en verde encima de
// un defecto que dejaba MUERTA cada lista de la app en cuanto pulsabas atrás:
// `restoreHistory()` no emite `htmx:afterSettle` —solo `htmx:historyRestore`—,
// que era el único evento al que `adhoc-utils.js` ataba los `onReady`; y las
// marcas `data-adhoc-*-bound` volvían PUESTAS desde el caché, así que aunque el
// módulo se re-ejecutara salía por su propia guarda de idempotencia.
//
// Estos casos hacen el viaje cotidiano de verdad —lista de incidencias → tareas
// de una incidencia → ATRÁS— y luego USAN la pantalla. Que el HTML esté no
// prueba nada; lo que se comprueba es que el pager mueve la tabla, que escribir
// en el filtro cambia las filas y que los modales abren.

/** Filas pintadas por `work/work-items.js` en la lista de incidencias. */
const FILAS = '#adhoc-table-incidents-body tr[data-id]';

/** La sección que el módulo marca con `data-adhoc-work-bound` al montarse. */
const SECCION = '#adhoc-page-work-incident';

/**
 * El viaje cotidiano: panel → lista de incidencias → tareas de la primera →
 * ATRÁS.
 *
 * SE ENTRA POR EL PANEL A PROPÓSITO, no con un `goto` directo a la lista: HTMX
 * solo restaura del caché las entradas de historial que empujó él mismo
 * (`popstate` con `state.htmx`). Cargando la lista a pulso, la entrada la crea
 * el navegador y el ATRÁS ni siquiera intenta restaurar: cambia la URL y deja
 * la pantalla anterior puesta. Eso es otro defecto, pero no es el que estos
 * casos persiguen — y además NO es el camino del usuario, que llega a la lista
 * por la tarjeta del panel.
 *
 * Antes de salir sella las filas ya pintadas con `data-e2e-huella`. Ese
 * atributo VIAJA en el caché del historial (es un atributo, y el caché es
 * `innerHTML`), así que al volver está de nuevo ahí; solo desaparece si el
 * módulo se remontó y `render()` reconstruyó el `<tbody>`. Es la diferencia
 * exacta entre "pintado" y "vivo".
 */
async function idaYVuelta(page) {
  await gotoAdhoc(page, '/adhoc/panel');
  await page.click('a.adhoc-tile[href="/adhoc/incidencias"]');
  await expect(page).toHaveURL(/\/adhoc\/incidencias$/);
  await expect(page.locator(FILAS).first(), 'la lista no llegó a pintarse').toBeVisible();

  await page.evaluate((sel) => {
    document.querySelectorAll(sel).forEach((tr) => tr.setAttribute('data-e2e-huella', '1'));
  }, FILAS);

  await page.locator(FILAS).first().locator('[data-adhoc-row-action="tasks"]').click();
  await expect(page).toHaveURL(/\/adhoc\/incidencias\/\d+\/tareas$/);
  await asentar(page);

  await page.goBack();
  await expect(page).toHaveURL(/\/adhoc\/incidencias$/);
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  // Si el ATRÁS hubiera recargado el documento, los módulos arrancarían solos y
  // estos casos pasarían sin probar nada: el defecto vive precisamente en la
  // restauración desde el caché, así que hay que exigirla.
  expect(
    await sinRecarga(page),
    'el ATRÁS recargó el documento entero: no hubo restauración del caché y el caso no prueba nada'
  ).toBe(true);
  // Margen para el remontaje y para la carga que dispara.
  await page.waitForTimeout(900);
}

test.describe('tras el ATRÁS la lista sigue VIVA, no solo pintada', () => {
  test('las filas se vuelven a pintar (no son las del caché)', async ({ page }) => {
    await idaYVuelta(page);

    await expect(
      page.locator('[data-e2e-huella]'),
      'las filas son las mismas que se guardaron en el caché: el módulo no volvió a montarse'
    ).toHaveCount(0);
    await expect(page.locator(FILAS).first()).toBeVisible();
    await expect(
      page.locator(SECCION),
      'la sección no quedó marcada como montada'
    ).toHaveAttribute('data-adhoc-work-bound', '1');
  });

  test('el pager responde y la tabla CAMBIA de contenido', async ({ page }) => {
    await idaYVuelta(page);

    const info = page.locator('[data-adhoc-work-pageinfo]');
    const paginas = Number(((await info.innerText()).match(/de\s+(\d+)/) || [])[1] || 0);
    expect(
      paginas,
      `hacen falta al menos 2 páginas para probar el pager (el beforeAll siembra ${LOTE_ATRAS.length} incidencias)`
    ).toBeGreaterThan(1);
    await expect(info).toHaveText(/^Página 1 de /);

    // La identidad de la fila es su `data-id`, no el folio: el folio es
    // OPCIONAL en `adhoc_incidents` y con los datos reales del SGC hay páginas
    // enteras cuya celda pinta el guion largo del vacío, así que comparándolo
    // la página 1 y la 2 salen "iguales" aunque la tabla sí se haya movido.
    const ids = () => page.locator(FILAS).evaluateAll((trs) =>
      trs.map((tr) => tr.getAttribute('data-id'))
    );
    const antes = await ids();
    expect(antes.length, 'la página 1 llegó vacía').toBeGreaterThan(0);

    await page.click('[data-adhoc-work-page="next"]');

    // No basta con que el botón exista: la tabla tiene que MOVERSE.
    await expect(info, 'el pager no hizo nada: la paginación está muerta').toHaveText(
      /^Página 2 de /
    );
    await expect
      .poll(ids, { message: 'la página 2 trae exactamente las mismas filas' })
      .not.toEqual(antes);
  });

  test('escribir en el filtro cambia las filas', async ({ page }) => {
    await idaYVuelta(page);

    const filas = page.locator(FILAS);
    await expect(filas).toHaveCount(25); // per_page del servidor

    await page.fill('#adhoc-work-f-search', TITULO_UNICO);
    await expect(filas, 'el filtro no filtró nada: el listener de búsqueda no existe').toHaveCount(
      1
    );
    await expect(filas.first().locator('[data-adhoc-cell="title"]')).toContainText(TITULO_UNICO);

    // Y "Limpiar" deshace el filtro, que es otro listener distinto.
    await page.click('[data-adhoc-work-clear]');
    await expect(filas, '"Limpiar" no repuso la lista').toHaveCount(25);
    await expect(page.locator('#adhoc-work-f-search')).toHaveValue('');
  });

  test('el alta abre su modal', async ({ page }) => {
    await idaYVuelta(page);

    const modal = page.locator('#adhoc-work-modal');
    await expect(modal).toBeHidden();

    await page.click('[data-adhoc-work-new]');
    await expect(modal, 'el botón de añadir no abrió nada').toBeVisible();
    await expect(
      modal.locator('[data-adhoc-record]'),
      'el modal abrió vacío: el formulario lo pinta el módulo'
    ).toHaveCount(1);
  });

  test('el clic en una fila abre su edición', async ({ page }) => {
    await idaYVuelta(page);

    const modal = page.locator('#adhoc-work-modal');
    await expect(modal).toBeHidden();

    const celda = page.locator(FILAS).first().locator('[data-adhoc-cell="title"]');
    const titulo = (await celda.innerText()).trim();
    await celda.click();

    await expect(modal, 'el clic en la fila no abrió la edición').toBeVisible();
    await expect(
      modal.locator('[data-adhoc-work-delete]'),
      'se abrió el alta en vez de la edición'
    ).toBeVisible();
    // El formulario llega relleno con la fila en la que se hizo clic.
    await expect(modal.locator('[data-adhoc-field="title"]')).toHaveValue(titulo);
  });
});

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
const { gotoAdhoc, ADHOC_SHELL, newApiContext, cleanupAdhoc, E2E_YEAR_MIN } = require('./_helpers');

/** Año del rango reservado (2090-2099) que `cleanupAdhoc()` barre al terminar. */
const ANIO = E2E_YEAR_MIN + 3;

// El tablero de indicadores necesita un año para tener filas. Antes los dos
// casos hacían `test.skip` si no había ninguno — y en una base recién sembrada
// eso son dos casos en verde que no prueban nada. Se crea aquí y se borra al
// final, como el resto de la suite de adhoc.
test.beforeAll(async () => {
  await cleanupAdhoc();
  const api = await newApiContext();
  try {
    await api.post('/indicator-years', { years: [ANIO] }, [200, 201]);
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

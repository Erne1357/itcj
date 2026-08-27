// @ts-check
/**
 * Integridad de la navegación de Calidad (adhoc).
 *
 * Esta suite existe porque `boosted-head.spec.js` solo cubre el `<head>`: las
 * hojas de cada página SÍ llegan al navegar. Lo que NADIE cubría es el `<body>`,
 * y ahí estaban los tres fallos que reportó el dueño del producto:
 *
 *   1. `<body class>` NO se actualiza en una navegación boosted.
 *      `hx-boost` apunta a `body` con swap `innerHTML`: cambia los HIJOS, jamás
 *      el atributo `class` del propio `<body>`. Consecuencias medidas:
 *        · llegar a /adhoc/panel navegando NO aplica `adhoc-panel-page`, así que
 *          la misma URL se ve distinta según cómo llegaste;
 *        · salir de una página `adhoc-wide` deja el contenedor al 98 % en la
 *          siguiente (1568 px en vez de 1200 px a 1600 px de viewport).
 *      Eso es "los estilos se quedan de otra pestaña".
 *
 *   2. Idiomorph estaba declarado (`hx-ext="morph"`) y cargado, pero NINGÚN
 *      elemento pedía `hx-swap="morph"`, así que nunca corría: cada navegación
 *      destruía y reconstruía el `<body>` entero.
 *
 *   3. Solo la barra de 4 tarjetas llevaba `hx-boost`. Todo lo demás —el botón
 *      "Volver al Panel", las tarjetas internas, los saltos por JS— recargaba
 *      el documento completo (el "flashazo").
 *
 *   4. Cada navegación re-ejecutaba los `<script>` del `<body>` y los módulos
 *      volvían a engancharse a `document`, que sobrevive al swap. Medido:
 *      15 listeners de `click` en la carga inicial, 94 tras seis navegaciones.
 *
 * El detector de "no hubo recarga" es `window.__booted`, que instala
 * `gotoAdhoc()` y que solo un full reload borra.
 */
const { test, expect } = require('@playwright/test');
const { gotoAdhoc, ADHOC_SHELL } = require('./_helpers');

/** Ancho de viewport fijo: los asertos de contenedor son en píxeles. */
const VIEWPORT = { width: 1600, height: 900 };

/** Clase estructural de la caja; no dice nada de la página. */
const CLASES_DEL_SHELL = ['adhoc-root'];

/**
 * Clases de página presentes en la caja que se intercambia (#adhoc-root),
 * sin la estructural. Ahí es donde `{% block body_class %}` las escribe.
 */
const clasesDePagina = (page) =>
  page.evaluate((shell) => {
    const root = document.getElementById('adhoc-root');
    if (!root) throw new Error('no hay #adhoc-root: el shell no se renderizo');
    return Array.from(root.classList)
      .filter((c) => !shell.includes(c))
      .sort();
  }, CLASES_DEL_SHELL);

/** Ancho renderizado del contenedor central. */
const anchoContenedor = (page) =>
  page.evaluate(() => {
    const c = document.querySelector('.adhoc-main-container');
    return c ? Math.round(c.getBoundingClientRect().width) : null;
  });

/** Navega por un enlace y espera a que HTMX asiente el intercambio. */
async function navegar(page, selector) {
  await page.click(selector);
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  await page.waitForTimeout(500);
}

/** true si NO hubo recarga completa desde el último `gotoAdhoc`. */
const sinRecarga = (page) => page.evaluate(() => !!(/** @type {any} */ (window).__booted));

test.use({ viewport: VIEWPORT });

test.describe('la caja intercambiada refleja la página en la que estás', () => {
  test('llegar navegando deja las mismas clases de página que entrar directo', async ({ page }) => {
    // Referencia: /adhoc/panel cargado a pulso.
    await gotoAdhoc(page, '/adhoc/panel');
    const referencia = await clasesDePagina(page);
    expect(referencia, 'el panel declara body_class="adhoc-panel-page"').toContain('adhoc-panel-page');

    // El mismo destino, alcanzado con hx-boost desde otra sección.
    await gotoAdhoc(page, '/adhoc/dashboard');
    await navegar(page, '.adhoc-nav-link[href="/adhoc/panel"]');

    expect(await sinRecarga(page), 'la nav debe navegar sin recargar').toBe(true);
    expect(await clasesDePagina(page), 'el panel llegó sin sus clases de página').toEqual(referencia);
  });

  test('salir de una página ancha NO deja el contenedor ancho en la siguiente', async ({ page }) => {
    // Referencia estrecha: el tablero. Antes se usaba /adhoc/documentos, pero
    // esa pantalla pasó a `adhoc-wide`: pedía una tabla de min-width 1200px
    // dentro de un contenedor de 1200px con 48px de padding a cada lado, así
    // que desbordaba 90px a CUALQUIER resolución. El tablero son tarjetas, no
    // una tabla, y se queda estrecho de verdad.
    await gotoAdhoc(page, '/adhoc/dashboard');
    const estrecho = await anchoContenedor(page);
    expect(await clasesDePagina(page), 'el tablero no declara body_class').toEqual([]);

    // /adhoc/documentos/panel sí es ancha (`adhoc-wide`, 98 %).
    await gotoAdhoc(page, '/adhoc/documentos/panel');
    expect(await clasesDePagina(page)).toContain('adhoc-wide');
    expect(await anchoContenedor(page)).toBeGreaterThan(estrecho);

    // Al volver al tablero navegando, el ancho tiene que ser el estrecho.
    await navegar(page, '.adhoc-nav-link[href="/adhoc/dashboard"]');
    expect(await sinRecarga(page)).toBe(true);
    expect(await clasesDePagina(page), 'adhoc-wide se quedó pegada').toEqual([]);
    expect(await anchoContenedor(page), 'el contenedor siguió ancho').toBe(estrecho);
  });

  test('la fila de navegación se ve igual en el panel llegues como llegues', async ({ page }) => {
    // El tamaño de las tarjetas de la barra superior es lo que el usuario ve
    // "cambiar de tipografía": en /adhoc/panel la hoja de la página las repinta.
    const caja = () =>
      page.evaluate(() => {
        const a = document.querySelector('.adhoc-nav-link');
        if (!a) return null;
        const cs = getComputedStyle(a);
        const icono = a.querySelector('.adhoc-nav-icon');
        return {
          alto: Math.round(a.getBoundingClientRect().height),
          padding: cs.padding,
          textAlign: cs.textAlign,
          icono: icono ? getComputedStyle(icono).fontSize : null,
        };
      });

    await gotoAdhoc(page, '/adhoc/panel');
    const directo = await caja();

    await gotoAdhoc(page, '/adhoc/dashboard');
    await navegar(page, '.adhoc-nav-link[href="/adhoc/panel"]');
    expect(await caja(), 'la barra se ve distinta según cómo llegaste al panel').toEqual(directo);
  });
});

test.describe('toda navegación interna es fluida', () => {
  test('"Volver al Panel" no recarga el documento', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel/usuarios');
    await navegar(page, 'a.adhoc-back');

    await expect(page).toHaveURL(/\/adhoc\/panel$/);
    expect(await sinRecarga(page), '"Volver al Panel" recargó la página entera').toBe(true);
  });

  test('las tarjetas del panel y el volver hacen un ciclo completo sin recargar', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');
    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/areas"]');
    await navegar(page, 'a.adhoc-back');
    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/usuarios"]');
    await navegar(page, 'a.adhoc-back');

    await expect(page).toHaveURL(/\/adhoc\/panel$/);
    expect(await sinRecarga(page), 'alguna de las cuatro navegaciones recargó').toBe(true);
  });

  test('el botón atrás del navegador restaura la página anterior', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/panel');
    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/areas"]');
    await expect(page).toHaveURL(/\/adhoc\/panel\/areas$/);

    await page.goBack();
    await expect(page.locator(ADHOC_SHELL)).toBeVisible();
    await expect(page).toHaveURL(/\/adhoc\/panel$/);
    await expect(page.locator('a.adhoc-tile[href="/adhoc/panel/areas"]')).toBeVisible();
    expect(await clasesDePagina(page), 'el atrás dejó las clases de la otra página').toContain(
      'adhoc-panel-page'
    );
  });

  test('idiomorph corre de verdad en las navegaciones boosted', async ({ page }) => {
    // Sin `hx-swap="morph"` la extensión está cargada pero nunca se usa, y el
    // swap es un innerHTML destructivo. La huella de que el morph corrió es que
    // un nodo del shell que existe en las dos páginas SOBREVIVE al intercambio.
    await gotoAdhoc(page, '/adhoc/panel');
    await page.evaluate(() => {
      const nav = document.querySelector('.adhoc-nav');
      if (nav) /** @type {any} */ (nav).__marca = 'viva';
    });

    await navegar(page, 'a.adhoc-tile[href="/adhoc/panel/areas"]');

    const sobrevive = await page.evaluate(() => {
      const nav = document.querySelector('.adhoc-nav');
      return !!(nav && /** @type {any} */ (nav).__marca === 'viva');
    });
    expect(sobrevive, 'el swap destruyó la barra en vez de morphearla').toBe(true);
  });
});

test.describe('la sesión no se degrada al navegar', () => {
  /** Nº de listeners de un tipo sobre `document`, vía CDP. */
  async function listenersDeDocumento(page, tipo) {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Runtime.enable');
    await cdp.send('DOM.enable');
    const { result } = await cdp.send('Runtime.evaluate', { expression: 'document' });
    const { listeners } = await cdp.send('DOMDebugger.getEventListeners', {
      objectId: result.objectId,
    });
    await cdp.detach();
    return listeners.filter((l) => l.type === tipo).length;
  }

  test('los listeners globales no se acumulan navegación tras navegación', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/dashboard');
    const inicial = await listenersDeDocumento(page, 'click');

    const vuelta = ['/adhoc/panel', '/adhoc/documentos', '/adhoc/dashboard'];
    for (const destino of vuelta) {
      await navegar(page, `.adhoc-nav-link[href^="${destino}"]`);
    }

    const despues = await listenersDeDocumento(page, 'click');
    expect(
      despues,
      `los listeners de click pasaron de ${inicial} a ${despues} tras 3 navegaciones`
    ).toBeLessThanOrEqual(inicial);
  });
});

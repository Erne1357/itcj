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

/**
 * Nº de listeners de un tipo sobre `document`, vía CDP.
 *
 * Vive a nivel de módulo (antes estaba dentro del describe de aquí abajo)
 * porque el bloque del ATRÁS, al final del archivo, mide lo mismo: los
 * listeners que se duplicaban al restaurar del historial.
 */
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

test.describe('la sesión no se degrada al navegar', () => {
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

// ============================================================================
// EL ATRÁS TIENE QUE MONTAR, NO SOLO REPINTAR
// ============================================================================
//
// El caso de aquí arriba ("el botón atrás del navegador restaura la página
// anterior") comprueba que el HTML llega, y el HTML llega SIEMPRE: sale del
// caché de historial de HTMX, que es `body.cloneNode(true).innerHTML` guardado
// en localStorage. Lo que no comprobaba nadie —ni él ni los dos de
// `js-navigation.spec.js`— es que los módulos VUELVAN A ARRANCAR, y por eso el
// defecto vivió toda la vida del proyecto: `restoreHistory()` no emite
// `htmx:afterSettle`, que era el único evento al que `adhoc-utils.js` ataba los
// `onReady`, y las marcas `data-adhoc-*-bound` volvían PUESTAS desde el caché.
//
// Las cuatro pantallas elegidas son deliberadamente de módulos distintos: un
// catálogo (`shared/catalog-crud.js`), la de usuarios (`panel/users.js`), la
// lista de documentos (`documents/documents.js`) y la de incidencias
// (`work/work-items.js`). El defecto no era de una pantalla: era del shell.

/**
 * Vigila las marcas `data-adhoc-*-bound` de TODO el documento.
 *
 * Es la firma de un montaje: quince módulos escriben la suya sobre su nodo raíz
 * al arrancar (`root.dataset.adhocXxxBound = '1'`), y `adhoc-utils.js` las
 * borra al restaurar del historial para que la marca que vuelve del caché no
 * les cierre la puerta. Si tras el ATRÁS no hubo NI UNA escritura, ningún
 * módulo arrancó: la pantalla es HTML pintado y nada más.
 *
 * Se observa `<html>` con `subtree`, así que también cubre los nodos que HTMX
 * crea al reponer el `<body>`. El vigía vive en `window`, que sobrevive a la
 * restauración porque no hay recarga de documento.
 */
async function vigilarMarcas(page) {
  await page.evaluate(() => {
    const w = /** @type {any} */ (window);
    w.__marcas = [];
    w.__vigia = new MutationObserver((cambios) => {
      for (const c of cambios) {
        const nombre = c.attributeName || '';
        if (!/^data-adhoc-.+-bound$/.test(nombre)) continue;
        w.__marcas.push({ nombre, puesta: /** @type {Element} */ (c.target).hasAttribute(nombre) });
      }
    });
    w.__vigia.observe(document.documentElement, { subtree: true, attributes: true });
  });
  return async () => page.evaluate(() => /** @type {any} */ (window).__marcas || []);
}

/**
 * Viajes de ida y vuelta. La IDA tiene que ser boosted: HTMX solo restaura del
 * caché las entradas de historial que empujó él (`popstate` con `state.htmx`),
 * así que una pantalla cargada a pulso no se restaura nunca.
 */
const VIAJES = [
  {
    pantalla: 'el catálogo de áreas',
    desde: '/adhoc/panel',
    ida: 'a.adhoc-tile[href="/adhoc/panel/areas"]',
    fuera: 'a.adhoc-back',
    url: /\/adhoc\/panel\/areas$/,
  },
  {
    pantalla: 'la pantalla de usuarios',
    desde: '/adhoc/panel',
    ida: 'a.adhoc-tile[href="/adhoc/panel/usuarios"]',
    fuera: 'a.adhoc-back',
    url: /\/adhoc\/panel\/usuarios$/,
  },
  {
    pantalla: 'la lista de documentos',
    desde: '/adhoc/dashboard',
    ida: '.adhoc-nav-link[href="/adhoc/documentos"]',
    fuera: '.adhoc-nav-link[href="/adhoc/dashboard"]',
    url: /\/adhoc\/documentos$/,
  },
  {
    pantalla: 'la lista de incidencias',
    desde: '/adhoc/panel',
    ida: 'a.adhoc-tile[href="/adhoc/incidencias"]',
    fuera: 'a.adhoc-back',
    url: /\/adhoc\/incidencias$/,
  },
];

test.describe('el ATRÁS vuelve a MONTAR los módulos', () => {
  for (const viaje of VIAJES) {
    test(`${viaje.pantalla} vuelve viva del historial`, async ({ page }) => {
      await gotoAdhoc(page, viaje.desde);
      await navegar(page, viaje.ida);
      await expect(page).toHaveURL(viaje.url);

      // Se sale por otro enlace boosted: así la entrada de la pantalla la
      // empujó HTMX y el ATRÁS la restaura del caché.
      await navegar(page, viaje.fuera);
      const leerMarcas = await vigilarMarcas(page);

      await page.goBack();
      await expect(page).toHaveURL(viaje.url);
      await expect(page.locator(ADHOC_SHELL)).toBeVisible();
      expect(
        await sinRecarga(page),
        'el ATRÁS recargó el documento: sin restauración del caché el caso no prueba nada'
      ).toBe(true);
      await page.waitForTimeout(900);

      const marcas = await leerMarcas();
      expect(
        marcas.filter((m) => m.puesta).map((m) => m.nombre),
        'ningún módulo se declaró montado tras el ATRÁS: la pantalla volvió pintada pero muerta'
      ).not.toEqual([]);
    });
  }

  test('htmx llega a emitir htmx:historyRestore', async ({ page }) => {
    // Es el ÚNICO evento del que puede colgar el remontaje (`restoreHistory()`
    // no emite `beforeSwap` ni `afterSettle`), así que si no llega a emitirse
    // no hay arreglo posible en `adhoc-utils.js` que valga.
    await gotoAdhoc(page, '/adhoc/panel');
    await page.evaluate(() => {
      /** @type {any} */ (window).__restauraciones = 0;
      document.addEventListener('htmx:historyRestore', () => {
        /** @type {any} */ (window).__restauraciones++;
      });
    });
    await navegar(page, 'a.adhoc-tile[href="/adhoc/incidencias"]');
    await navegar(page, 'a.adhoc-back');

    await page.goBack();
    await expect(page).toHaveURL(/\/adhoc\/incidencias$/);
    await page.waitForTimeout(900);

    expect(
      await page.evaluate(() => /** @type {any} */ (window).__restauraciones),
      'HTMX no emitió htmx:historyRestore: restoreHistory() se rompió a mitad'
    ).toBeGreaterThan(0);
  });

  test('ningún <form> de dentro de #adhoc-root se queda sin action', async ({ page }) => {
    // Guarda estructural, y la causa raíz del caso de arriba.
    //
    // `#adhoc-root` lleva `hx-boost="true"`, que TODO descendiente hereda —los
    // modales incluidos, que viven en `{% block modals %}`, dentro de la caja.
    // Al procesar un <form> boosted, htmx 2.0.3 hace (`boostElement`,
    // minificado como `ft`):
    //
    //     o = getAttribute(t, "action");
    //     if (r === "get" && o.includes("?")) { ... }
    //
    // Sin `action`, `o` es `null` y eso es un TypeError. En una navegación
    // normal la excepción se queda en el procesado del nodo y el intercambio
    // termina igual; en la RESTAURACIÓN es fatal, porque `restoreHistory()`
    // inserta y procesa los nodos DENTRO de la misma función que después emite
    // `htmx:historyRestore`: la excepción sube y ese evento no se emite nunca.
    // Resultado: un `<form>` sin `action` deja MUERTA su pantalla cada vez que
    // el usuario pulsa ATRÁS.
    //
    // El arreglo es de una línea por plantilla (`action="{{ request.url.path }}"`
    // o `hx-boost="false"` en el propio <form>), pero tiene que quedar cazado:
    // el próximo <form> que alguien añada sin `action` reabre el defecto.
    const PANTALLAS = [
      '/adhoc/dashboard',
      '/adhoc/documentos',
      '/adhoc/documentos/panel',
      '/adhoc/incidencias',
      '/adhoc/programas',
      '/adhoc/indicadores',
      '/adhoc/panel',
      '/adhoc/panel/usuarios',
      '/adhoc/panel/areas',
    ];

    const culpables = [];
    for (const url of PANTALLAS) {
      await gotoAdhoc(page, url);
      const sinAction = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#adhoc-root form:not([action])'))
          .filter((f) => f.closest('[hx-boost="false"]') === null)
          .map((f) => f.outerHTML.slice(0, 80))
      );
      for (const f of sinAction) culpables.push(`${url}  ${f}`);
    }

    // La página de tareas de un expediente es la otra con <form> propio y no
    // tiene URL fija: se saca de la primera fila de la lista de incidencias.
    await gotoAdhoc(page, '/adhoc/incidencias');
    const primera = page.locator('#adhoc-table-incidents-body tr[data-id]').first();
    await expect(primera).toBeVisible();
    const urlTareas = `/adhoc/incidencias/${await primera.getAttribute('data-id')}/tareas`;
    await gotoAdhoc(page, urlTareas);
    const enTareas = await page.evaluate(() =>
      Array.from(document.querySelectorAll('#adhoc-root form:not([action])'))
        .filter((f) => f.closest('[hx-boost="false"]') === null)
        .map((f) => f.outerHTML.slice(0, 80))
    );
    for (const f of enTareas) culpables.push(`${urlTareas}  ${f}`);

    expect(
      culpables,
      `<form> boosted sin action (htmx revienta al restaurar y se lleva por delante el ATRÁS):\n  ${culpables.join(
        '\n  '
      )}`
    ).toEqual([]);
  });
});

// ============================================================================
// EL ATRÁS NO PUEDE DUPLICAR EL RUNTIME
// ============================================================================
//
// Los casos de arriba comprueban que tras el ATRÁS la pantalla vuelve VIVA.
// Estos comprueban lo contrario: que no vuelve viva DOS veces.
//
// HTMX guarda y repone el historial sobre el "elemento de historial", que es el
// que lleve `hx-history-elt` o, si nadie lo lleva —el caso de esta app—,
// `document.body`. Repone con `swapInnerHTML`, y eso vuelve a CREAR cada
// <script> del fragmento, o sea a EJECUTARLO (`htmx.config.allowScriptTags`).
//
// Mientras los <script> de la base vivieron al principio del <body>, cada ATRÁS
// creaba una copia entera de HTMX, de Bootstrap, de AdhocUtils y de
// table-filter.js. Medido en Chromium con tres idas y vueltas:
//
//   · los listeners de `document` pasaban de 43 a 118, con 4 juegos de
//     `htmx:beforeSwap` / `htmx:afterSettle` / `htmx:historyRestore` y 4 de los
//     `input`/`search`/`change`/`click` del filtrado de tablas — cada tecla
//     pulsada en un filtro recorría el filtrado cuatro veces;
//   · y con dos runtimes de HTMX vivos, el segundo ATRÁS guardaba el DOM de la
//     pantalla ACTUAL bajo la URL de la ANTERIOR (`currentPathForHistory` de la
//     copia vieja), dejando esa URL corrupta en localStorage para el resto de la
//     sesión: volvías a /adhoc/documentos y veías el tablero.
//
// La cura es que esos <script> vivan en el <head>, fuera del elemento de
// historial. Estos casos son su prueba de regresión por el efecto, no por la
// forma; la forma la vigila
// tests/fastapi/adhoc/test_template_conventions.py (regla 12).

/** Ida y vuelta boosted entre dos entradas de la barra de navegación. */
async function ciclo(page, ida, vuelta) {
  await navegar(page, `.adhoc-nav-link[href^="${ida}"]`);
  await page.goBack();
  await expect(page.locator(ADHOC_SHELL)).toBeVisible();
  await page.waitForTimeout(700);
  await expect(page).toHaveURL(new RegExp(`${vuelta}$`));
}

test.describe('el ATRÁS no duplica el runtime', () => {
  test('htmx, AdhocUtils y table-filter siguen siendo los MISMOS objetos', async ({ page }) => {
    // Un sello sobre el objeto: si el <script> se re-ejecutara, `window.htmx`
    // sería otro objeto y el sello no estaría. Es la comprobación directa de
    // "no hay copias", sin depender de contar listeners.
    await gotoAdhoc(page, '/adhoc/documentos');
    await page.evaluate(() => {
      const w = /** @type {any} */ (window);
      w.htmx.__e2eSello = 'uno';
      w.AdhocUtils.__e2eSello = 'uno';
      w.AdhocTableFilter.__e2eSello = 'uno';
    });

    for (let i = 0; i < 3; i++) await ciclo(page, '/adhoc/dashboard', '/adhoc/documentos');

    const sellos = await page.evaluate(() => {
      const w = /** @type {any} */ (window);
      return {
        htmx: w.htmx && w.htmx.__e2eSello,
        utils: w.AdhocUtils && w.AdhocUtils.__e2eSello,
        filtro: w.AdhocTableFilter && w.AdhocTableFilter.__e2eSello,
      };
    });
    expect(
      sellos,
      'algún <script> de la base se re-ejecutó al restaurar del historial: ' +
        'volvió a caer dentro del <body> (el elemento de historial de HTMX)'
    ).toEqual({ htmx: 'uno', utils: 'uno', filtro: 'uno' });
  });

  test('los listeners de document no crecen con cada ATRÁS', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/documentos');

    // Un ciclo DE CALENTAMIENTO antes de tomar la referencia. Es obligatorio y
    // no es cosmético: la primera visita al tablero trae módulos que la lista de
    // documentos no había cargado nunca (`work/workflow-modal.js` y
    // `dashboard/dashboard.js` cuelgan de `document` dos `click` y un `keydown`),
    // y esos son un alta legítima, no una duplicación. Midiendo desde antes de
    // pisar el tablero, el caso confundiría "he visitado una pantalla nueva" con
    // "me he registrado otra vez", que es justo lo que viene a distinguir.
    await ciclo(page, '/adhoc/dashboard', '/adhoc/documentos');

    const inicial = {};
    for (const tipo of ['click', 'input', 'change', 'search']) {
      inicial[tipo] = await listenersDeDocumento(page, tipo);
    }

    for (let i = 0; i < 3; i++) await ciclo(page, '/adhoc/dashboard', '/adhoc/documentos');

    for (const tipo of ['click', 'input', 'change', 'search']) {
      const despues = await listenersDeDocumento(page, tipo);
      expect(
        despues,
        `los listeners de '${tipo}' sobre document pasaron de ${inicial[tipo]} a ` +
          `${despues} tras 3 idas y vueltas: alguien se re-registró en cada ATRÁS`
      ).toBeLessThanOrEqual(inicial[tipo]);
    }
  });

  test('el SEGUNDO ATRÁS restaura la pantalla correcta, no la de al lado', async ({ page }) => {
    // El caché de historial se envenenaba a partir del segundo ciclo: con dos
    // runtimes de HTMX vivos, el `saveCurrentPageToHistory()` del viejo escribía
    // el DOM del dashboard bajo la clave `/adhoc/documentos`.
    await gotoAdhoc(page, '/adhoc/documentos');
    await expect(page.locator('[data-adhoc-documents]')).toHaveCount(1);

    for (let ciclos = 1; ciclos <= 2; ciclos++) {
      await ciclo(page, '/adhoc/dashboard', '/adhoc/documentos');
      await expect(
        page.locator('[data-adhoc-documents]'),
        `tras el ATRÁS nº ${ciclos} la URL es /adhoc/documentos pero en pantalla ` +
          'hay otra cosa: el caché de historial quedó corrupto'
      ).toHaveCount(1);
      await expect(page.locator('[data-adhoc-table-body] tr').first()).toBeVisible();
    }
  });
});

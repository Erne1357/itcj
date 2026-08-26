// @ts-check
/**
 * Contrato visual de Calidad (adhoc).
 *
 * Asertos sobre estilo COMPUTADO, no capturas: una captura falla por
 * cualquier cosa (una fila más, otra fuente instalada, el antialias del
 * runner) y no dice qué se rompió. Aquí cada caso nombra la regla que vigila.
 *
 * Todo lo que hay aquí sale de la auditoría de 84 hallazgos y de las
 * decisiones del dueño del producto:
 *
 *   · el título de página es UNO en las 30 pantallas: 24px/600, icono violeta;
 *   · la barra de navegación mide lo mismo en todas, /adhoc/panel incluido;
 *   · ningún control queda invisible por una guerra de especificidad;
 *   · el color de un icono de acción no se pierde al pasar el ratón;
 *   · el contraste de las acciones irreversibles del SGC cumple WCAG AA.
 */
const { test, expect } = require('@playwright/test');
const { gotoAdhoc } = require('./_helpers');

test.use({ viewport: { width: 1600, height: 900 } });

/** Contraste WCAG 2.x entre dos colores CSS resueltos por el navegador. */
async function contraste(page, primerPlano, fondo) {
  return page.evaluate(
    ([fg, bg]) => {
      const canal = (c) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      const luminancia = (rgb) => {
        const [r, g, b] = rgb;
        return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
      };
      const parse = (valor) => {
        const m = String(valor).match(/-?[\d.]+/g);
        if (!m) throw new Error(`color no parseable: ${valor}`);
        return [Number(m[0]), Number(m[1]), Number(m[2])];
      };
      const l1 = luminancia(parse(fg));
      const l2 = luminancia(parse(bg));
      const [claro, oscuro] = l1 > l2 ? [l1, l2] : [l2, l1];
      return Math.round(((claro + 0.05) / (oscuro + 0.05)) * 100) / 100;
    },
    [primerPlano, fondo]
  );
}

test.describe('el título de página es uno solo', () => {
  // Una por familia de plantilla: la macro page_header(), las dos pantallas que
  // escribían su propio markup y las raíces que tenían bloque de excepción.
  const PANTALLAS = [
    '/adhoc/panel',
    '/adhoc/panel/usuarios',
    '/adhoc/panel/areas',
    '/adhoc/panel/correo',
    '/adhoc/panel/configuracion',
    '/adhoc/documentos/panel',
    '/adhoc/documentos/flujos',
    '/adhoc/reportes',
  ];

  for (const ruta of PANTALLAS) {
    test(`${ruta} lo pinta a 24px/600 con el icono violeta`, async ({ page }) => {
      await gotoAdhoc(page, ruta);

      const titulo = page.locator('h1.adhoc-page-title').first();
      await expect(titulo, `${ruta} no emite h1.adhoc-page-title`).toBeVisible();

      const estilo = await titulo.evaluate((el) => {
        const cs = getComputedStyle(el);
        const i = el.querySelector('i');
        const ics = i ? getComputedStyle(i) : null;
        return {
          fontSize: cs.fontSize,
          fontWeight: cs.fontWeight,
          iconoFontSize: ics && ics.fontSize,
          iconoColor: ics && ics.color,
        };
      });

      expect(estilo.fontSize, `${ruta}: tamaño del título`).toBe('24px');
      expect(estilo.fontWeight, `${ruta}: peso del título`).toBe('600');
      if (estilo.iconoFontSize) {
        expect(estilo.iconoFontSize, `${ruta}: tamaño del icono`).toBe('21.6px');
        expect(estilo.iconoColor, `${ruta}: color del icono`).toBe('rgb(72, 52, 212)');
      }
    });
  }

  test('no queda ninguna pantalla sin <h1>', async ({ page }) => {
    const sinH1 = [];
    for (const ruta of PANTALLAS) {
      await gotoAdhoc(page, ruta);
      if ((await page.locator('h1').count()) === 0) sinH1.push(ruta);
    }
    expect(sinH1, `pantallas sin <h1>:\n${sinH1.join('\n')}`).toEqual([]);
  });
});

test('la barra de navegación mide lo mismo en todas las pantallas', async ({ page }) => {
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
        iconoMargen: icono ? getComputedStyle(icono).marginBottom : null,
      };
    });

  await gotoAdhoc(page, '/adhoc/dashboard');
  const referencia = await caja();
  expect(referencia, 'no hay barra de navegación en el tablero').not.toBeNull();

  for (const ruta of ['/adhoc/panel', '/adhoc/documentos', '/adhoc/panel/usuarios']) {
    await gotoAdhoc(page, ruta);
    expect(await caja(), `la barra cambia en ${ruta}`).toEqual(referencia);
  }
});

test('el botón muerto de "Ayuda" ya no está en la cabecera', async ({ page }) => {
  await gotoAdhoc(page, '/adhoc/dashboard');
  await expect(page.locator('.adhoc-btn-ayuda')).toHaveCount(0);
  await expect(page.locator('a[href="#"]'), 'quedan enlaces sin destino').toHaveCount(0);
});

test('el botón de guardar de la edición en línea se ve', async ({ page }) => {
  // Guerra de especificidad real: `.adhoc-catalog .adhoc-actions .adhoc-btn-icon`
  // (0,3,0) quita el fondo de `.btn-primary` (0,1,0) pero no su `color`, así que
  // el check quedaba blanco sobre fila blanca en las cuatro pantallas de catálogo.
  await gotoAdhoc(page, '/adhoc/documentos/categorias');

  const editar = page.locator('[data-adhoc-action="edit"]').first();
  if ((await editar.count()) === 0) test.skip(true, 'no hay filas de catálogo que editar');
  await editar.click();

  const guardar = page.locator('[data-adhoc-action="save"]').first();
  await expect(guardar).toBeVisible();

  const { color, fondo } = await guardar.evaluate((el) => {
    const cs = getComputedStyle(el);
    let padre = el.parentElement;
    let fondo = 'rgba(0, 0, 0, 0)';
    while (padre && fondo === 'rgba(0, 0, 0, 0)') {
      fondo = getComputedStyle(padre).backgroundColor;
      padre = padre.parentElement;
    }
    return { color: cs.color, fondo };
  });

  expect(await contraste(page, color, fondo), `el check "Guardar" es ${color} sobre ${fondo}`)
    .toBeGreaterThanOrEqual(3);
});

test('los iconos de acción conservan su color al pasar el ratón', async ({ page }) => {
  // Se mide sobre botones SINTÉTICOS con las clases que emite work-items.js, y
  // el :hover se fuerza por CDP. Depender de que existan incidencias en la base
  // convertía el caso en un `skip` silencioso — que es justo como este defecto
  // sobrevivió a una suite de 6198 líneas.
  //
  // DOS TRAMPAS, las dos pisadas al escribir esto:
  //   · `DOM.getDocument` sin `depth: -1` no baja el árbol completo y el nodeId
  //     no resuelve contra el nodo que interesa;
  //   · `.adhoc-icon-btn` tiene `transition: .2s`, así que leer el color justo
  //     después de forzar el pseudo devuelve el valor de PARTIDA y el caso pasa
  //     en vacío. Hay que esperar a que la transición termine.
  //
  // El caso se autovalida: `adhoc-icon-primary` (la variante por defecto) SÍ
  // debe teñirse de lila, y eso demuestra que la sonda detecta cambios de color.
  await gotoAdhoc(page, '/adhoc/incidencias');

  const cdp = await page.context().newCDPSession(page);
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');

  /** Color en reposo y con :hover asentado, para un botón con esas clases. */
  async function colores(variante) {
    await page.evaluate((v) => {
      const previo = document.getElementById('probe-icono');
      if (previo) previo.remove();
      const fila = document.createElement('div');
      fila.id = 'probe-icono';
      fila.className = 'adhoc-actions';
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'adhoc-icon-btn ' + v;
      b.textContent = 'x';
      fila.appendChild(b);
      const main = document.querySelector('#adhoc-main');
      if (main) main.appendChild(fila);
    }, variante);

    const sel = '#probe-icono button';
    const reposo = await page.locator(sel).evaluate((el) => getComputedStyle(el).color);

    const { root } = await cdp.send('DOM.getDocument', { depth: -1 });
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: sel });
    expect(nodeId, `no se resolvió el nodo de ${variante}`).toBeTruthy();

    await cdp.send('CSS.forcePseudoState', { nodeId, forcedPseudoClasses: ['hover'] });
    await page.waitForTimeout(400); // la transición es de .2s
    const encima = await page.locator(sel).evaluate((el) => getComputedStyle(el).color);
    await cdp.send('CSS.forcePseudoState', { nodeId, forcedPseudoClasses: [] });

    return { reposo, encima };
  }

  // Control negativo: la variante por defecto SÍ cambia (se tiñe de lila).
  const defecto = await colores('adhoc-icon-primary');
  expect(
    defecto.encima,
    'la sonda no detecta cambios de color: el resto del caso no probaría nada'
  ).not.toBe(defecto.reposo);

  // Lo que se vigila: las variantes con color propio lo conservan.
  const perdidos = [];
  for (const variante of ['adhoc-icon-task', 'adhoc-icon-doc', 'adhoc-icon-trash']) {
    const { reposo, encima } = await colores(variante);
    if (encima !== reposo) perdidos.push(variante + ': ' + reposo + ' -> ' + encima);
  }

  await page.evaluate(() => {
    const probe = document.getElementById('probe-icono');
    if (probe) probe.remove();
  });
  await cdp.detach();

  expect(perdidos, 'iconos que pierden su color al pasar el raton: ' + perdidos.join(' | ')).toEqual([]);
});

test('las acciones irreversibles del SGC cumplen contraste AA', async ({ page }) => {
  await gotoAdhoc(page, '/adhoc/dashboard');

  // Se miden sobre botones sintéticos: las clases son las mismas que usa el
  // modal de workflow, y así el caso no depende de que haya tareas abiertas.
  const medidas = await page.evaluate(() => {
    const caja = document.createElement('div');
    caja.style.position = 'absolute';
    caja.style.left = '-9999px';
    document.body.appendChild(caja);
    const clases = ['btn-success', 'btn-danger', 'btn-warning', 'btn-primary', 'btn-secondary'];
    const out = {};
    for (const c of clases) {
      const b = document.createElement('button');
      b.className = `btn ${c}`;
      b.textContent = 'x';
      caja.appendChild(b);
      const cs = getComputedStyle(b);
      out[c] = { color: cs.color, fondo: cs.backgroundColor };
    }
    caja.remove();
    return out;
  });

  const fallan = [];
  for (const [clase, { color, fondo }] of Object.entries(medidas)) {
    const ratio = await contraste(page, color, fondo);
    if (ratio < 4.5) fallan.push(`${clase}: ${ratio}:1 (${color} sobre ${fondo})`);
  }
  expect(fallan, `variantes por debajo de AA:\n${fallan.join('\n')}`).toEqual([]);
});

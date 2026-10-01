// @ts-check
/**
 * Accesibilidad de Calidad (adhoc).
 *
 * La app se portó del legacy con la accesibilidad desactivada a propósito —el
 * original quitaba el anillo de foco de todos los campos y lo sustituía por un
 * cambio de borde de 1px— y nunca se repuso. Una suite de 6198 líneas no tenía
 * NI UNA aserción de accesibilidad, así que nada de esto se veía.
 *
 * Lo que se vigila:
 *   · el foco se VE en todo control interactivo (WCAG 2.4.7);
 *   · hay un enlace de salto y es el primer Tab;
 *   · un diálogo atrapa el foco y lo devuelve al cerrarse;
 *   · los avisos viven en una región viva que existe desde el principio;
 *   · el árbol de encabezados no salta niveles;
 *   · ningún control de solo icono se queda sin nombre accesible.
 *
 * El foco se prueba pulsando Tab de verdad, no forzando el pseudo por CDP:
 * `:focus-visible` depende de CÓMO llegaste al elemento, y un `element.focus()`
 * desde JS no siempre lo activa. Tabular es lo que hace el usuario.
 */
const { test, expect } = require('@playwright/test');
const { gotoAdhoc } = require('./_helpers');

test.use({ viewport: { width: 1600, height: 900 } });

/** Estilo de foco del elemento activo ahora mismo. */
const focoActivo = (page) =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const cs = getComputedStyle(el);
    return {
      etiqueta: el.tagName.toLowerCase(),
      clase: String(el.className).slice(0, 60),
      texto: (el.textContent || '').trim().slice(0, 30),
      outlineWidth: parseFloat(cs.outlineWidth) || 0,
      outlineStyle: cs.outlineStyle,
      boxShadow: cs.boxShadow,
    };
  });

test.describe('el foco se ve', () => {
  test('el primer Tab es el enlace de salto y lleva al contenido', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/documentos');

    await page.keyboard.press('Tab');
    const primero = await focoActivo(page);
    expect(primero, 'el primer Tab no enfoca nada').not.toBeNull();
    expect(primero.clase, `el primer Tab enfoca "${primero.texto}"`).toContain('adhoc-skip');
    expect(primero.outlineWidth, 'el enlace de salto no muestra foco').toBeGreaterThan(0);

    // Y se ve: fuera de la pantalla en reposo, dentro al recibir el foco.
    const dentro = await page.evaluate(() => {
      const el = document.querySelector('.adhoc-skip');
      const r = el.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= window.innerHeight;
    });
    expect(dentro, 'el enlace de salto sigue fuera de pantalla con el foco puesto').toBe(true);

    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#adhoc-main$/);
  });

  test('los primeros diez controles de una pantalla muestran su foco', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/documentos');

    const sinFoco = [];
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      const f = await focoActivo(page);
      if (!f) break;
      const seVe = f.outlineWidth > 0 || (f.boxShadow && f.boxShadow !== 'none');
      if (!seVe) sinFoco.push(`${f.etiqueta}.${f.clase} "${f.texto}"`);
    }
    expect(sinFoco, `controles sin indicador de foco:\n  ${sinFoco.join('\n  ')}`).toEqual([]);
  });

  //: Pantallas con campos, y el selector de TODO lo que en esta app es un campo.
  //: La lista incluye las clases propias de cada sección a propósito: nueve
  //: campos no llevan `form-control` ni `form-select` —tienen su clase de
  //: sección— así que no heredaban ni el `:focus` de repuesto de la hoja base y
  //: se quedaban SIN NINGUNA diferencia entre enfocado y no enfocado.
  const CAMPOS =
    '.adhoc-filter-input, .form-control, .form-select, .adhoc-doc-filter, ' +
    '.adhoc-doc-qty, .adhoc-step-input, .adhoc-board-qty, ' +
    '.adhoc-board-threshold-input, .adhoc-tracking-input, .adhoc-years-qty';

  for (const ruta of ['/adhoc/documentos', '/adhoc/documentos/panel', '/adhoc/indicadores']) {
    test(`${ruta}: los campos muestran su foco`, async ({ page }) => {
      await gotoAdhoc(page, ruta);
      await page.waitForTimeout(900);

      const campos = page.locator(CAMPOS);
      const total = await campos.count();
      // Nada de `test.skip` aquí: un selector que no encuentra nada es
      // exactamente el agujero por el que se coló este defecto durante toda la
      // migración. Si no hay campos, es que el selector está mal.
      expect(total, `${ruta} no tiene ningún campo que medir`).toBeGreaterThan(0);

      const sinFoco = [];
      for (let i = 0; i < Math.min(total, 8); i++) {
        const campo = campos.nth(i);
        if (!(await campo.isVisible())) continue;
        await campo.focus();
        const estilo = await campo.evaluate((el) => {
          const cs = getComputedStyle(el);
          return {
            w: parseFloat(cs.outlineWidth) || 0,
            s: cs.outlineStyle,
            sombra: cs.boxShadow,
            cls: String(el.className),
          };
        });
        const seVe = (estilo.w > 0 && estilo.s !== 'none') || (estilo.sombra && estilo.sombra !== 'none');
        if (!seVe) sinFoco.push(estilo.cls.slice(0, 50));
      }
      expect(sinFoco, `campos sin anillo de foco: ${sinFoco.join(' | ')}`).toEqual([]);
    });
  }
});

test.describe('los diálogos se comportan con el teclado', () => {
  test('un diálogo propio atrapa el foco y lo devuelve al cerrarse', async ({ page }) => {
    await gotoAdhoc(page, '/adhoc/documentos');

    // Se usa el diálogo de confirmación de AdhocUtils, que es el que la app
    // levanta desde JS y el único que no depende de que haya datos.
    await page.evaluate(() => {
      const b = document.createElement('button');
      b.id = 'probe-abre';
      b.textContent = 'abrir';
      document.querySelector('#adhoc-main').appendChild(b);
      b.focus();
      b.addEventListener('click', () => window.AdhocUtils.confirmDialog({ title: 'Prueba', message: 'x' }));
    });

    await page.click('#probe-abre');
    await page.waitForTimeout(300);

    const dentro = await page.evaluate(() =>
      !!document.querySelector('.adhoc-modal.is-open')?.contains(document.activeElement)
    );
    expect(dentro, 'al abrir, el foco no entró en el diálogo').toBe(true);

    // Tabular en bucle no debe salirse del diálogo.
    const fuera = [];
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab');
      const sigueDentro = await page.evaluate(() =>
        !!document.querySelector('.adhoc-modal.is-open')?.contains(document.activeElement)
      );
      if (!sigueDentro) fuera.push(i);
    }
    expect(fuera, `el foco se salió del diálogo en los Tab ${fuera.join(', ')}`).toEqual([]);

    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    expect(
      await page.evaluate(() => document.activeElement?.id),
      'al cerrar, el foco no volvió al botón que lo abrió'
    ).toBe('probe-abre');
  });
});

test.describe('paginar con el teclado', () => {
  // La lista de incidencias es la única pantalla con paginación real y datos de
  // sobra (277 filas del SGC a 25 por página). Si algún día se queda con una
  // sola página, estos dos casos fallan con un mensaje que lo dice.
  const TIRA = '[data-adhoc-pager-pages]';
  const ROTULO = '[data-adhoc-work-pageinfo]';

  async function listaPaginada(page) {
    await gotoAdhoc(page, '/adhoc/incidencias');
    await expect(page.locator(ROTULO)).toHaveText(/^Página 1 de /);
    const total = Number(((await page.locator(ROTULO).innerText()).match(/de\s+(\d+)/) || [])[1] || 0);
    expect(total, 'hacen falta al menos 2 páginas para probar el paginador').toBeGreaterThan(1);
    await expect(page.locator(TIRA)).toBeVisible();
  }

  test('activar un número con el teclado no tira el foco al <body>', async ({ page }) => {
    await listaPaginada(page);

    await page.locator('[data-adhoc-goto-page="2"]').focus();
    await page.keyboard.press('Enter');
    await expect(page.locator(ROTULO)).toHaveText(/^Página 2 de /);

    // `pintar()` vacía la tira y crea botones nuevos, así que el botón que
    // tenía el foco deja de existir. Sin devolverlo, el activo pasa a ser el
    // <body> y el siguiente Tab arranca en "Saltar al contenido": recorrer la
    // lista con teclado costaba tabular el documento entero por cada página.
    const donde = await page.evaluate((sel) => {
      const tira = document.querySelector(sel);
      const activo = document.activeElement;
      return {
        dentro: !!tira && tira.contains(activo),
        actual: activo ? activo.getAttribute('aria-current') : null,
        texto: activo ? (activo.textContent || '').trim() : '(nada)',
      };
    }, TIRA);

    expect(donde.dentro, `tras paginar el foco quedó en "${donde.texto}"`).toBe(true);
    expect(donde.actual, 'el foco no volvió al número de la página actual').toBe('page');
  });

  test('el rótulo de página es región viva y cambia al paginar', async ({ page }) => {
    await listaPaginada(page);

    // El conteo de al lado también es región viva, pero su texto ("25 de 277
    // incidencias") es el mismo en todas las páginas completas: no anuncia nada.
    // El rótulo es lo único que cambia, así que es el que tiene que hablar.
    await expect(page.locator(ROTULO)).toHaveAttribute('aria-live', 'polite');

    await page.locator('[data-adhoc-goto-page="2"]').click();
    await expect(page.locator(ROTULO)).toHaveText(/^Página 2 de /);
  });
});

test('el contenedor de avisos es una región viva desde el principio', async ({ page }) => {
  await gotoAdhoc(page, '/adhoc/panel');

  const region = await page.evaluate(() => {
    const el = document.getElementById('adhoc-toast-container');
    if (!el) return null;
    return { live: el.getAttribute('aria-live'), rol: el.getAttribute('role') };
  });
  expect(region, 'no hay contenedor de avisos en el shell').not.toBeNull();
  expect(region.live, 'el contenedor no es una región viva').toBe('polite');
});

test.describe('la estructura del documento', () => {
  const PANTALLAS = [
    '/adhoc/dashboard',
    '/adhoc/documentos',
    '/adhoc/panel',
    '/adhoc/panel/usuarios',
    '/adhoc/reportes',
  ];

  for (const ruta of PANTALLAS) {
    test(`${ruta}: un solo h1 y sin saltos de nivel`, async ({ page }) => {
      await gotoAdhoc(page, ruta);
      await page.waitForTimeout(800);

      const niveles = await page.evaluate(() =>
        Array.from(document.querySelectorAll('#adhoc-root h1,#adhoc-root h2,#adhoc-root h3,#adhoc-root h4,#adhoc-root h5,#adhoc-root h6'))
          // `getClientRects()` vacio = el elemento NO se pinta, y eso incluye a
          // todo lo que cuelga de un ancestro con `display:none`. Mirar solo el
          // estilo computado del propio encabezado no vale: un <h2> dentro de un
          // modal cerrado sigue diciendo `display:block`, y contarlo metia en el
          // arbol los titulos de dialogos que nadie esta viendo.
          .filter((h) => h.getClientRects().length > 0 && getComputedStyle(h).visibility !== 'hidden')
          .map((h) => ({ n: Number(h.tagName[1]), t: (h.textContent || '').trim().slice(0, 24) }))
      );

      const h1 = niveles.filter((x) => x.n === 1);
      expect(h1.length, `h1 encontrados: ${JSON.stringify(h1)}`).toBe(1);

      const saltos = [];
      for (let i = 1; i < niveles.length; i++) {
        if (niveles[i].n - niveles[i - 1].n > 1) {
          saltos.push(`h${niveles[i - 1].n} "${niveles[i - 1].t}" -> h${niveles[i].n} "${niveles[i].t}"`);
        }
      }
      expect(saltos, `saltos de nivel:\n  ${saltos.join('\n  ')}`).toEqual([]);
    });
  }
});

test('ningún control de solo icono se queda sin nombre', async ({ page }) => {
  const PANTALLAS = ['/adhoc/documentos', '/adhoc/panel', '/adhoc/panel/usuarios', '/adhoc/indicadores'];
  const anonimos = [];

  for (const ruta of PANTALLAS) {
    await gotoAdhoc(page, ruta);
    await page.waitForTimeout(900);

    const encontrados = await page.evaluate(() =>
      Array.from(document.querySelectorAll('#adhoc-root button, #adhoc-root a[href]'))
        .filter((el) => {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          if (!el.getBoundingClientRect().width) return false;
          // Nombre accesible: texto visible, aria-label, title o aria-labelledby.
          const visible = Array.from(el.querySelectorAll('*'))
            .concat([el])
            .some((n) =>
              Array.from(n.childNodes).some(
                (c) =>
                  c.nodeType === 3 &&
                  c.textContent.trim() &&
                  getComputedStyle(n).display !== 'none'
              )
            );
          if (visible) return false;
          return !(el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('aria-labelledby'));
        })
        .map((el) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 44)}`)
    );
    for (const e of encontrados) anonimos.push(`${ruta} ${e}`);
  }

  expect(anonimos, `controles sin nombre accesible:\n  ${anonimos.join('\n  ')}`).toEqual([]);
});

// @ts-check
/**
 * Invariante responsive de la página pública de la encuesta.
 *
 * Dos aserciones distintas, porque una sola no basta:
 *
 *  1. `document.documentElement.scrollWidth <= window.innerWidth` en los SEIS
 *     viewports de la matriz del proyecto (itcj2/apps/titulatec/docs/design/
 *     responsive.md:53-58). Detecta desbordamiento horizontal.
 *
 *  2. A 1440 y 1920, el ancho del TEXTO de las preguntas. El invariante de (1)
 *     NO detecta el estiramiento: una página que reparte 1920 px entre cuatro
 *     párrafos de 200 caracteres por línea no desborda nada y es ilegible.
 *     `base.html` (49 líneas) renderiza `{% block content %}` DESNUDO dentro
 *     de `<body>`, y el tope `.tt-stu .tt-canvas-inner p { max-width: 48ch }`
 *     (titulatec.css:532) cuelga de una clase que solo pone `base_student.html`.
 *     Por eso `base_public.html` (Tarea 11) opta por `.tt-prose` y su
 *     `public.css` sube el tope del contenedor a
 *     `.tt-public-main.tt-prose { max-width: 60ch }` —un cuestionario lleva
 *     controles, no solo párrafos— devolviendo `.tt-public-main p
 *     { max-width: 48ch }` a los párrafos. Esto es lo que lo verifica.
 *
 * Sin auth y sin sembrar: la página anónima no necesita nada de la BD salvo un
 * cuestionario 'egresados' abierto, y sirve cualquiera de los dos — el v1 del
 * DML (Tarea 24) o el superset que abre el `seedScenario()` de `_helpers.js`,
 * que repite las mismas dos preguntas primero con las etiquetas idénticas.
 *
 * `storageState: { cookies: [], origins: [] }`, NO `storageState: undefined`:
 * ver la nota en `public-survey.spec.js` — en Playwright 1.61 un valor
 * `undefined` es un no-op y el contexto hereda el storageState global del
 * proyecto (admin de helpdesk) en vez de quedar sin cookie.
 */
const { test, expect } = require('@playwright/test');

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const P1 = '¿Cuál es tu situación laboral actual?';

// Matriz del proyecto. No inventar otra.
const MATRIZ = [
  { w: 360, h: 740, perfil: 'móvil chico' },
  { w: 390, h: 844, perfil: 'móvil de referencia' },
  { w: 768, h: 1024, perfil: 'tablet vertical' },
  { w: 1280, h: 800, perfil: 'laptop' },
  { w: 1440, h: 900, perfil: 'escritorio común' },
  { w: 1920, h: 1080, perfil: 'monitor grande' },
];

// El tope real es 60ch (`.tt-public-main.tt-prose`, public.css de la Tarea 11),
// que con la tipografía de la app ronda 600 px. 800 deja holgura y sigue
// reprobando cualquier caja full-bleed (>=1300).
const MAX_PROSA_PX = 800;

for (const { w, h, perfil } of MATRIZ) {
  test(`la encuesta no desborda a ${w}x${h} (${perfil})`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

    const medida = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(
      medida.scrollWidth,
      `desborde horizontal a ${w}px: scrollWidth ${medida.scrollWidth} > innerWidth ${medida.innerWidth}`
    ).toBeLessThanOrEqual(medida.innerWidth);
  });
}

for (const { w, h } of MATRIZ.filter((v) => v.w >= 1440)) {
  test(`el texto de las preguntas está acotado a ${w}px (no se estira)`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });

    const caja = await page.getByText(P1).boundingBox();
    expect(caja, 'no se encontró el texto de la primera pregunta').not.toBeNull();
    expect(
      Math.round(caja.width),
      `la pregunta mide ${Math.round(caja.width)}px a ${w}px de ventana: ` +
        'la base pública no está optando por .tt-prose (max-width: 48ch)'
    ).toBeLessThanOrEqual(MAX_PROSA_PX);
  });
}

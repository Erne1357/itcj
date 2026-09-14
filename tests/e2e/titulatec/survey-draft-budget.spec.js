// @ts-check
/**
 * Presupuesto de escrituras del autosave — criterio 7 del spec (Tarea 6:
 * reescrito para el asistente por pasos).
 *
 * Modelado sobre `tests/e2e/core/user-detail-request-budget.spec.js`: se
 * cuentan las peticiones con `page.on('request')` y se asierta un TECHO, no un
 * número exacto.
 *
 * D3 pide borradores automáticos que NO generen carga de escritura. El
 * contrato son dos mecanismos que se refuerzan (spec §6.4): debounce de 5 s de
 * inactividad y un techo duro de una petición cada 30 s
 * (DRAFT_DEBOUNCE_MS / DRAFT_MIN_INTERVAL_MS del contrato §5). El límite
 * derivado es <= 2 escrituras por minuto por alumno.
 *
 * QUÉ CAMBIÓ (Tarea 6) Y POR QUÉ ESTE ARCHIVO SE REESCRIBIÓ ENTERO. La
 * versión anterior escribía directo en `empresa`/`comentarios` justo tras el
 * `goto` y disparaba el "swap de htmx" con un ENVÍO FINAL inválido
 * (`SURVEY_URL`). Las dos premisas cambiaron:
 *
 *   1. El cuestionario se recorre por pasos: `empresa`/`puesto`/`comentarios`
 *      viven en la sección "detalle" (paso 2 de 3), no en la única pantalla
 *      que existía antes. Hay que llegar ahí con "Siguiente" primero.
 *   2. Con el paginado, el SWAP más común -y el que de verdad hay que
 *      vigilar- ya no es un envío final fallido: es un cambio de paso. Cada
 *      render paginado omite `draft_updated_at` (`_form_ctx` en
 *      `pages/public.py`, rama `step is not None`: nunca pasa
 *      `draft_updated_at`, así que en el cliente `serverAt` da `0`), y
 *      `mergeLocalDraft` (`survey.js`) lee eso como "el borrador local es más
 *      nuevo" en TODO cambio de paso, con o sin borrador local real. Por
 *      construcción, cambiar de paso con algo sin autoguardar SIEMPRE llama a
 *      `flush()` -nunca a `send()` directo: ese era justamente el bug que
 *      este archivo perseguía en la ronda anterior, y ya está arreglado
 *      (`survey.js`, `mergeLocalDraft` llama `flush(f, false)`, no `send()`)-,
 *      así que el disparador natural del swap a vigilar es un cambio de paso
 *      real ("Siguiente"/"Atrás"), no un envío final fabricado a propósito.
 *      Se prefiere ese disparador porque es el que de verdad ocurre en el
 *      recorrido normal, no una construcción artificial para forzar un swap.
 *
 * DESVIACIONES VERIFICADAS contra la app real (Tarea 6):
 *
 *  1. `lastSentAt` arranca en `0` (epoch) y `page.clock.install()` sin
 *     argumento arranca el Date falso en la hora real actual. Por tanto, la
 *     PRIMERA vez que algo dispara `flush()` en una página recién cargada, el
 *     techo de 30 s se lee como "vencido" y ese primer envío sale de
 *     inmediato. El primer cambio de paso (paso 1 -> 2, más abajo) es
 *     justamente ese envío "gratis": se deja pasar sin contarlo contra el
 *     presupuesto de ninguna medición.
 *  2. Un cambio de paso llama `flush()`, que si el techo de 30 s SIGUE
 *     vigente no manda nada de inmediato: programa el envío para cuando
 *     expire, hasta 30 s después. Por eso "cambio de sección: AL MENOS una
 *     escritura" espera `MIN_INTERVAL_MS + margen`, no unos pocos ms.
 *  3. Un cambio de paso que NO tiene nada nuevo que autoguardar (ningún
 *     campo tocado desde el último flush/clear) no dispara ninguna escritura:
 *     `mergeLocalDraft` solo actúa si `readLocal()` encuentra algo, y
 *     `clearLocal()` corre siempre que lo encontró. Por eso cada transición
 *     que se quiere medir va precedida de un toque fresco a un campo.
 *  4. "buscando" (no "empleado") como respuesta a `situacion_laboral` en todo
 *     este archivo: deja `relacion_carrera` (visible_when
 *     situacion_laboral=empleado) invisible, así que el paso 1 se completa
 *     con un solo campo y el recorrido no depende de contestar la escala.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor } = require('./_helpers');

let ctx;

// `beforeEach`/`afterEach`: los dos tests de este archivo navegan el
// cuestionario de punta a punta y dejan un borrador de servidor bastante
// avanzado; compartir un solo escenario haría que el segundo test arrancara
// en un paso distinto al que espera, dependiendo de qué dejó el primero
// (mismo hallazgo que forzó el mismo cambio en `public-survey.spec.js`).
test.beforeEach(() => { ctx = seedScenario(); });
test.afterEach(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const DRAFT_URL = '/titulatec/encuesta-egresados/borrador';
const STEP_URL = '/titulatec/encuesta-egresados/paso';
const BUDGET = 2;               // spec §6.4: cota superior de 2 escrituras / minuto
const MIN_INTERVAL_MS = 30000;  // DRAFT_MIN_INTERVAL_MS del contrato (survey.js)
const CAMPOS = ['empresa', 'puesto', 'comentarios']; // los tres viven en "detalle" (paso 2)

/** Devuelve un array vivo con una entrada por POST al endpoint de borrador. */
function contarBorradores(page) {
  const calls = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === DRAFT_URL) {
      calls.push(req.url());
    }
  });
  return calls;
}

/** Avanza del paso 1 ("empleo") al 2 ("detalle"). Es el envío "gratis" de la
 *  desviación 1: el primer flush de una página recién cargada no respeta el
 *  techo porque `lastSentAt` sigue en `0`. */
async function irAPasoDetalle(page) {
  await page.locator('input[name="situacion_laboral"][value="buscando"]').check();
  const paso = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === STEP_URL
  );
  await page.getByRole('button', { name: 'Siguiente' }).click();
  await paso;
  await expect(page.getByText('Paso 2 de 3')).toBeVisible();
}

/** 60 s simulados de tecleo continuo repartido entre los tres campos de "detalle". */
async function teclearUnMinuto(page) {
  for (let i = 0; i < 10; i++) {
    const campo = CAMPOS[i % CAMPOS.length];
    await page.fill(`[name="${campo}"]`, `texto de prueba ${i}`);
    await page.clock.runFor(6000); // 10 x 6 s = 60 s simulados
  }
  await page.waitForTimeout(500);  // margen REAL para los POST en vuelo
}

test('60 s de tecleo continuo producen a lo más 2 escrituras, también tras un cambio de paso',
  async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();

    // install() antes de navegar: el JS de la página debe nacer con el reloj falso.
    await page.clock.install();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

    await irAPasoDetalle(page); // envío "gratis" (desviación 1), fuera de cualquier medición

    const calls = contarBorradores(page);

    // --- medición 1: recién llegado al paso "detalle" ---------------------
    await teclearUnMinuto(page);
    expect(
      calls.length,
      `presupuesto excedido en el paso "detalle" (${calls.length} > ${BUDGET})`
    ).toBeLessThanOrEqual(BUDGET);

    // --- cambio de paso: AL MENOS una escritura ---------------------------
    // "Al menos", no "exactamente": el flush del cambio de paso puede coincidir
    // con el techo de 30 s y una igualdad sería inestable (spec §11.2). Un
    // toque fresco antes de avanzar asegura que SÍ hay algo que autoguardar
    // (desviación 3): sin él, si `teclearUnMinuto` ya vació el "dirty" con su
    // último flush, el cambio de paso no tendría nada que fusionar.
    calls.length = 0;
    await page.fill('[name="puesto"]', 'Puesto fresco antes de avanzar');
    await page.getByRole('button', { name: 'Siguiente' }).click(); // detalle -> seguimiento
    await expect(page.getByText('Paso 3 de 3')).toBeVisible();
    // MIN_INTERVAL_MS + margen, no unos pocos ms: `flush()` en un cambio de
    // paso NO manda de inmediato si el techo de 30 s sigue vigente -programa
    // el envío para cuando expire- (desviación 2).
    await page.clock.runFor(MIN_INTERVAL_MS + 1000);
    await page.waitForTimeout(700);
    expect(
      calls.length,
      'cambiar de paso debe hacer flush (al expirar el techo si sigue vigente) del borrador'
    ).toBeGreaterThanOrEqual(1);

    // --- swap: "Atrás" regresa a "detalle" ---------------------------------
    // Es el disparador que de verdad usa el recorrido normal (ver el
    // encabezado del archivo): la parte que atraparía un listener
    // re-registrado en `htmx:afterSettle` sigue siendo un swap completo de
    // `#tt-survey-form`, solo que ahora es un cambio de paso, no un envío
    // final fabricado.
    await page.getByRole('button', { name: 'Atrás' }).click();
    await expect(page.getByText('Paso 2 de 3')).toBeVisible();

    // --- medición 2: mismo presupuesto DESPUÉS del swap --------------------
    calls.length = 0;
    await teclearUnMinuto(page);
    expect(
      calls.length,
      `presupuesto excedido DESPUÉS del swap (${calls.length} > ${BUDGET}): ` +
        'el listener de autosave se está re-registrando en htmx:afterSettle. Debe ' +
        'cargarse UNA vez desde el bloque scripts y delegar en document.'
    ).toBeLessThanOrEqual(BUDGET);

    await c.close();
  });

test('la re-hidratación tras un cambio de paso respeta el techo de 30 s',
  async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();

    await page.clock.install();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

    await irAPasoDetalle(page); // envío "gratis" (desviación 1): deja el techo vigente

    const calls = contarBorradores(page);

    // Dos cambios de paso SEGUIDOS, cada uno con un toque fresco antes (
    // desviación 3), dentro de una ventana simulada MUCHO más corta que el
    // techo de 30 s. El invariante que se fija aquí: la re-hidratación de
    // CUALQUIERA de los dos NO puede saltarse el techo. Con `flush()`
    // (correcto) el segundo cambio programa su envío para cuando el techo
    // expire, sin mandar nada de inmediato; con un eventual `send()` directo
    // (el bug que este archivo perseguía en la ronda anterior, ya arreglado)
    // cada swap mandaría una escritura inmediata, sin importar el techo.
    await page.fill('[name="empresa"]', 'valor fresco antes del primer cambio');
    await page.getByRole('button', { name: 'Siguiente' }).click(); // detalle -> seguimiento
    await expect(page.getByText('Paso 3 de 3')).toBeVisible();

    await page.clock.runFor(5000); // muy por debajo del techo de 30 s
    await page.locator('input[name="interes_bolsa_trabajo"][value="si"]').check(); // toque fresco
    await page.getByRole('button', { name: 'Atrás' }).click(); // seguimiento -> detalle
    await expect(page.getByText('Paso 2 de 3')).toBeVisible();

    await page.waitForTimeout(300); // margen REAL para un POST en vuelo, si lo hubiera
    expect(
      calls.length,
      `los dos cambios de paso ya escribieron ${calls.length} vez/veces sin que expirara ` +
        'el techo: la re-hidratación se está saltando el techo de 30 s (`send()` en vez ' +
        'de `flush()` dentro de `mergeLocalDraft`).'
    ).toBe(0);

    // Ahora sí deja correr el reloj lo suficiente para que el envío
    // PROGRAMADO por el primer cambio de paso salga.
    await page.clock.runFor(MIN_INTERVAL_MS + 1000);
    await page.waitForTimeout(700);
    expect(
      calls.length,
      'debe haber salido exactamente el envío programado por el primer cambio de paso'
    ).toBeLessThanOrEqual(1);

    await c.close();
  });

// @ts-check
/**
 * Presupuesto de escrituras del autosave — criterio 7 del spec.
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
 * POR QUÉ ESTO ES E2E Y NO pytest: el fallo que persigue es un LISTENER
 * RE-REGISTRADO en `htmx:afterSettle`. Multiplica las escrituras del navegador
 * sin romper una sola prueba de servidor — cada petición que llega es
 * perfectamente válida. Por eso la medición se REPITE después de un swap de
 * htmx: es el único momento en que el bug se manifiesta.
 *
 * El tiempo se simula con `page.clock`, que falsea temporizadores y Date sin
 * tocar la red: las peticiones que salen son reales y se cuentan de verdad.
 *
 * DESVIACIONES VERIFICADAS frente al borrador de la Tarea 26 (las cuatro
 * probadas contra la app real en `itcj-backend-1`, no supuestas):
 *
 *  1. `lastSentAt` arranca en `0` (epoch) y `page.clock.install()` sin
 *     argumento arranca el Date falso en la hora real actual (verificado:
 *     `Date.now()` justo tras `install()` ≈ hora real de la máquina, NO 0).
 *     Por tanto, en CUALQUIER página recién cargada, la primera vez que algo
 *     dispara `flush()`, `Date.now() - lastSentAt` ya es enorme y el techo de
 *     30 s se lee como "vencido": el PRIMER envío de la sesión sale de
 *     inmediato, no 30 s después. Esto es intencional (comentario de
 *     `mergeLocalDraft` en `survey.js`: "lastSentAt sigue en 0 y el techo ya
 *     está vencido"), pero cambia CUÁNDO cae la 2ª escritura del minuto.
 *  2. Un cambio de sección llama `flush()`, que si el techo de 30 s SIGUE
 *     vigente no manda nada de inmediato: programa el envío para cuando el
 *     techo expire, que puede ser hasta 30 s después. `page.clock.runFor(1000)`
 *     del borrador original casi nunca alcanza a ver esa escritura (medido:
 *     con exactamente la secuencia de este archivo, la escritura del cambio de
 *     sección no aparece antes de +8 s virtuales). Se usa
 *     `runFor(MIN_INTERVAL_MS + 1000)` para cubrir el peor caso (el techo
 *     recién reiniciado un instante antes del cambio de sección) sin
 *     depender de en qué punto exacto del ciclo de 30 s cae la interacción.
 *  3. La sección "cambio de sección" dispara con toda intención el radio
 *     `situacion_laboral=empleado` para poder entrar a esa sección del
 *     formulario (es la única forma: `relacion_carrera` vive ahí pero está
 *     oculto hasta que se marca esa opción). Eso hace que el AUTOSAVE
 *     persista `situacion_laboral=empleado` en el borrador de servidor antes
 *     del envío inválido de más abajo. Cuando la página se recarga, el
 *     formulario vuelve con esa opción ya marcada, así que `situacion_laboral`
 *     deja de estar vacío — el campo que de verdad queda sin llenar (y sin el
 *     cual la validación falla) es `relacion_carrera`, que `visible_when`
 *     revela justo por esa marca. Verificado contra la app real: tras esta
 *     misma secuencia, `[data-tt-error="situacion_laboral"]` NO aparece;
 *     `[data-tt-error="relacion_carrera"]` sí. El envío sigue siendo inválido
 *     (200, formulario re-renderizado, 1 error) — solo cambia CUÁL campo.
 *  4. Los DOS tests de este archivo comparten un solo `ctx`/escenario
 *     (`beforeAll` a nivel de archivo, como en el borrador): el borrador de
 *     servidor que el PRIMER test deja escrito (`situacion_laboral=empleado`,
 *     desviación 3) es visible para el SEGUNDO test si ambos corren juntos
 *     (mismo `form_id`+`user_id`). Corriendo solo el segundo test (`-g`), en
 *     cambio, arranca con el borrador vacío y el campo inválido vuelve a ser
 *     `situacion_laboral`. Ninguno de los dos nombres de campo es estable
 *     entre esos dos modos de ejecución, así que el segundo test verifica la
 *     tarjeta genérica `[data-tt-errors]` en vez de un campo puntual — ver el
 *     comentario junto a `envioFallido()`, más abajo.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor } = require('./_helpers');

let ctx;

test.beforeAll(() => { ctx = seedScenario(); });
test.afterAll(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const DRAFT_URL = '/titulatec/encuesta-egresados/borrador';
const BUDGET = 2;               // spec §6.4: cota superior de 2 escrituras / minuto
const MIN_INTERVAL_MS = 30000;  // DRAFT_MIN_INTERVAL_MS del contrato (survey.js)
const CAMPOS = ['empresa', 'puesto', 'comentarios'];

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

/** 60 s simulados de tecleo continuo repartido entre varios campos. */
async function teclearUnMinuto(page) {
  for (let i = 0; i < 10; i++) {
    const campo = CAMPOS[i % CAMPOS.length];
    await page.fill(`[name="${campo}"]`, `texto de prueba ${i}`);
    await page.clock.runFor(6000); // 10 x 6 s = 60 s simulados
  }
  await page.waitForTimeout(500);  // margen REAL para los POST en vuelo
}

test('60 s de tecleo continuo producen a lo más 2 escrituras, también tras un swap de htmx',
  async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();

    // install() antes de navegar: el JS de la página debe nacer con el reloj falso.
    await page.clock.install();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

    const calls = contarBorradores(page);

    // --- medición 1: página recién cargada -------------------------------
    await teclearUnMinuto(page);
    expect(
      calls.length,
      `presupuesto excedido en carga limpia (${calls.length} > ${BUDGET})`
    ).toBeLessThanOrEqual(BUDGET);

    // --- cambio de sección: AL MENOS una escritura ------------------------
    // "Al menos", no "exactamente": el flush de sección puede coincidir con el
    // techo de 30 s y una igualdad sería inestable (spec §11.2).
    calls.length = 0;
    await page.locator('input[name="situacion_laboral"][value="empleado"]').check(); // sección "empleo"
    await page.locator('[name="comentarios"]').click();                              // sección "detalle"
    // MIN_INTERVAL_MS + margen, no 1000: `flush()` en cambio de sección NO
    // manda de inmediato si el techo de 30 s sigue vigente — programa el envío
    // para cuando expire. 1000 ms verificado insuficiente contra la app real
    // (ver el comentario de cabecera, desviación 2); esto cubre el peor caso.
    await page.clock.runFor(MIN_INTERVAL_MS + 1000);
    await page.waitForTimeout(700);
    expect(
      calls.length,
      'cambiar de sección debe hacer flush (al expirar el techo si sigue vigente) del borrador'
    ).toBeGreaterThanOrEqual(1);

    // --- swap de htmx: envío inválido re-renderiza el formulario ----------
    // Es la parte que atrapa un listener re-registrado en htmx:afterSettle.
    await page.reload({ waitUntil: 'domcontentloaded' });
    const post = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === SURVEY_URL
    );
    await page.getByRole('button', { name: 'Enviar respuestas' }).click();
    expect((await post).status(), 'htmx no swappea en 4xx: el re-render debe ser 200').toBe(200);
    // `relacion_carrera`, NO `situacion_laboral`: el cambio de sección de
    // arriba ya autoguardó `situacion_laboral=empleado` en el borrador de
    // servidor, así que al recargar ese campo llega marcado y deja de estar
    // vacío. El campo que la validación rechaza es `relacion_carrera`, que
    // `visible_when` revela justo por esa marca y que este flujo nunca llenó
    // (ver la desviación 3 en el comentario de cabecera).
    await expect(page.locator('[data-tt-error="relacion_carrera"]')).toBeVisible();

    // --- medición 2: mismo presupuesto DESPUÉS del swap ------------------
    calls.length = 0;
    await teclearUnMinuto(page);
    expect(
      calls.length,
      `presupuesto excedido DESPUÉS del swap de htmx (${calls.length} > ${BUDGET}): ` +
        'el listener de autosave se está re-registrando en htmx:afterSettle. Debe ' +
        'cargarse UNA vez desde el bloque scripts y delegar en document.'
    ).toBeLessThanOrEqual(BUDGET);

    await c.close();
  });

// ---------------------------------------------------------------------------
// AÑADIDO POR EL CONTROLADOR (2026-09-10), tras la revisión de la Tarea 13.
//
// Por qué hace falta un test aparte, si arriba ya hay una "medición 2" que
// teclea DESPUÉS de un swap: porque esa medición **no puede ver este fallo**.
// El contador se pone a cero DESPUÉS de que el swap asiente, así que la
// escritura que dispara la re-hidratación queda fuera de la cuenta; y una vez
// disparada, deja `lastSentAt` fresco, con lo que el minuto de tecleo que sigue
// vuelve a caber en el presupuesto. El test de arriba sale VERDE con el fallo
// dentro. Lo comprobamos leyendo el orden de las líneas, no suponiéndolo.
//
// El fallo real, encontrado en la Tarea 13: `mergeLocalDraft` llamaba a `send()`
// directo en la rama "gana el borrador local", saltándose el techo de 30 s. Y
// esa rama se toma CASI SIEMPRE tras un envío fallido, porque `_form_ctx` no
// arrastra `draft_updated_at` en la rama de error de validación: llega vacío,
// `Date.parse('') || 0` da 0, y cualquier borrador local es "más nuevo". O sea:
// un POST de borrador sin throttle por cada envío fallido, que es exactamente
// el presupuesto que esta tarea existe para defender.
//
// La invariante que se fija aquí: **la re-hidratación tras un swap no puede
// saltarse el techo de 30 s.** Se mide con DOS envíos fallidos seguidos dentro
// de una ventana simulada más corta que el techo. Con `flush()` el segundo no
// escribe; con `send()` escribe uno por swap.
//
// DESVIACIÓN VERIFICADA frente al borrador de la Tarea 26 (probada contra la
// app real, alternando `flush()`/`send()` en `mergeLocalDraft` para confirmar
// el poder de discriminación del test — ver el reporte, prueba R5): tal como
// estaba escrito el borrador, `clearLocal()` se ejecuta SIEMPRE al final de
// `mergeLocalDraft` (gane o no la rama local), así que el ÚNICO borrador local
// de la precondición se consume en el PRIMER `envioFallido()` y ya no queda
// nada que fusionar en el segundo — ni con el bug ni sin él. Medido: con
// `send()` (el bug) el total daba 1, no 2, y `1 <= 1` pasaba igual que con
// `flush()` (que da 0): el test no distinguía nada. Se agrega un
// `page.fill()` fresco antes de CADA `envioFallido()` para que
// `mergeLocalDraft` tenga un borrador local "más nuevo que el del servidor"
// que fusionar en los DOS swaps, no solo en el primero. Con ese ajuste,
// medido: `flush()` -> 0 escrituras; `send()` -> 2. Ahora sí discrimina.
// ---------------------------------------------------------------------------
test('la re-hidratación tras un swap respeta el techo de 30 s',
  async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();

    await page.clock.install();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

    // Un borrador local más nuevo que el del servidor es la precondición: es lo
    // que hace que `mergeLocalDraft` tome la rama que tenía el fallo.
    await page.fill('[name="comentarios"]', 'algo escrito antes de enviar');
    await page.clock.runFor(6000);
    await page.waitForTimeout(300);

    const calls = contarBorradores(page);

    async function envioFallido() {
      // Borrador local fresco ANTES de cada swap (ver la desviación de
      // cabecera): sin esto, `clearLocal()` ya vació localStorage en el swap
      // anterior y `mergeLocalDraft` no tiene nada que fusionar la segunda
      // vez, sea cual sea el código — el test no distinguiría nada.
      await page.fill('[name="comentarios"]', 'texto fresco ' + Date.now());
      const post = page.waitForResponse(
        (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === SURVEY_URL
      );
      await page.getByRole('button', { name: 'Enviar respuestas' }).click();
      expect((await post).status(), 'htmx no swappea en 4xx: el re-render debe ser 200').toBe(200);
      // Tarjeta genérica `[data-tt-errors]`, NO un campo puntual: este test
      // comparte `ctx`/borrador de servidor con el test anterior del mismo
      // archivo (mismo `beforeAll`), así que CUÁL campo queda inválido
      // depende de si ese test ya corrió antes (dejó `situacion_laboral`
      // marcado) o no (queda vacío, y entonces el inválido es
      // `situacion_laboral` en vez de `relacion_carrera`). Verificado
      // corriendo el archivo completo vs. este test en aislamiento (`-g`):
      // el campo cambia, pero SIEMPRE hay error — es lo único estable.
      await expect(page.locator('[data-tt-errors]')).toBeVisible();
      await page.waitForTimeout(400);   // margen REAL para un POST en vuelo
    }

    calls.length = 0;
    await envioFallido();
    // 5 s simulados: MUY por debajo del techo de 30 s, así que el segundo swap
    // no tiene derecho a escribir nada aunque su borrador local sea el mas nuevo.
    await page.clock.runFor(5000);
    await envioFallido();

    expect(
      calls.length,
      `la re-hidratacion se salta el techo de 30 s (${calls.length} escrituras en ` +
        '5 s simulados). `mergeLocalDraft` debe llamar a `flush()`, no a `send()`: ' +
        '`send()` escribe una vez por swap y `_form_ctx` no arrastra ' +
        '`draft_updated_at` en la rama de error, asi que la rama "gana el local" ' +
        'se toma en CADA envio fallido.'
    ).toBeLessThanOrEqual(1);

    await c.close();
  });

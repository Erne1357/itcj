// @ts-check
/**
 * Encuesta de egresados — camino de ENTRADA con sesión y recorrido por pasos
 * (Tarea 6 del plan `2026-09-14-titulatec-encuesta-egresados`).
 *
 * REESCRITURA COMPLETA. La versión anterior de este archivo probaba "se
 * contesta sin sesión": abría `SURVEY_URL` como anónimo contra lo que hubiera
 * abierto en dev y esperaba el formulario completo en una sola pantalla. Las
 * Tareas 1-5 de este plan cambiaron las dos premisas de esa prueba:
 *
 *   1. `_requiere_sesion` (`pages/public.py`) hace que un formulario con
 *      `is_anonymous=False` -que es como se siembra AHORA el `egresados` real
 *      (`titulatec load-survey-2026-09`, 63 campos/7 secciones) y también el
 *      escenario sintético de `_helpers.js`- redirija al login ANTES de
 *      pintar nada. Un GET anónimo contra ese formulario ya no ve un banner:
 *      ve un 302.
 *   2. El cuestionario se recorre por PASOS (uno por sección), no en una sola
 *      pantalla: no hay ya un único envío con todos los campos visibles a la
 *      vez salvo en el re-render de un envío final fallido.
 *
 * Este archivo pasa a cubrir, en ese orden, lo que pide el brief de la Tarea
 * 6: (a) sin sesión, la encuesta manda al login con un `next` que apunta de
 * vuelta a sí misma; (b) tras autenticarse, ese `next` regresa a la encuesta
 * -ya con la sección 1 prellenada y editable-; (c) desde ahí, el mecanismo de
 * pasos: adelante estricto (bloquea sin el obligatorio, re-pinta con error
 * inline, nunca un 400 mudo), atrás libre a cualquier paso YA VISITADO vía el
 * indicador -incluido un salto NO adyacente, que es lo único que de verdad
 * distingue el indicador de un botón "Atrás"-, y ese avance acotado en el
 * SERVIDOR (una petición forjada no puede saltarse la validación).
 *
 * SINTÉTICO, no el instrumento real (decisión de la Tarea 6, ver el reporte):
 * el inciso (a) no necesita sembrar nada -corre contra lo que ya esté abierto
 * en dev, igual que la versión anterior de este archivo, porque el redirect
 * no depende de qué formulario sea, solo de que no sea anónimo-, pero (b) y
 * (c) sí necesitan iniciar sesión de verdad (control_number/NIP reales) y
 * recorrer más de dos pasos -el salto NO adyacente del indicador exige TRES-,
 * así que usan `seedScenario()`. Recorrer las 7 secciones/63 campos reales
 * para probar el MECANISMO de paginado (que es lo que cambió, no el
 * contenido del cuestionario) sería lento y frágil sin aportar nada que el
 * escenario sintético de tres secciones no cubra ya; el instrumento real es
 * quien manda en `responsive.spec.js`, que es donde el tamaño de verdad
 * importa.
 *
 * `storageState: { cookies: [], origins: [] } }`, NUNCA `storageState:
 * undefined`: en Playwright 1.61 un valor `undefined` es un no-op
 * (`node_modules/playwright/lib/index.js`, `_combinedContextOptions`: solo
 * sobreescribe cuando el valor resuelto es distinto de `undefined`), así que
 * el contexto heredaría el `storageState` global del proyecto (admin de
 * helpdesk, `.auth/state.json`) en vez de quedar sin cookie -y
 * `require_page_app`/`_requiere_sesion` no tienen bypass de admin global-.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor, E2E_NIP } = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const STEP_URL = '/titulatec/encuesta-egresados/paso';

// ---------------------------------------------------------------------------
// (a) Sin sesión: manda al login con `next`. Sin seedScenario(): el redirect
// no depende de CUÁL formulario esté abierto, solo de que no sea anónimo -y
// tanto el real como el del escenario se siembran con `is_anonymous=False`-.
// Igual que la versión anterior de este archivo, basta con que exista
// CUALQUIER 'egresados' abierto en dev.
// ---------------------------------------------------------------------------
test.describe('sin sesión', () => {
  test('la encuesta manda al login con next de vuelta a sí misma (302, no un 400/200 mudo)', async ({ page }) => {
    // `maxRedirects: 0` es lo que deja ver el 302 real y su `Location`: un
    // `page.goto` normal SIGUE el redirect y solo se ve la página final.
    const res = await page.request.get(SURVEY_URL, { maxRedirects: 0 });
    expect(res.status(), 'un formulario no-anónimo sin sesión debe redirigir, no pintar nada').toBe(302);
    const location = res.headers()['location'];
    expect(location, 'el next debe apuntar de vuelta a la propia encuesta').toBe(
      `/itcj/login?next=${SURVEY_URL}`
    );
  });

  test('la navegación real del navegador aterriza en el login con ese next', async ({ page }) => {
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    expect(page.url(), 'el navegador debe seguir el redirect hasta el login').toContain('/itcj/login');
    expect(page.url()).toContain(`next=${SURVEY_URL}`);
  });
});

// ---------------------------------------------------------------------------
// (b) y (c): con sesión real (login por control_number/NIP) contra el
// escenario sintético de tres secciones.
// ---------------------------------------------------------------------------
test.describe('con sesión: entra por el login y recorre los pasos', () => {
  let ctx;

  // `beforeEach`/`afterEach`, NO `beforeAll`/`afterAll`: el borrador vive en
  // servidor por (form_id, user_id) y estos cuatro tests comparten el MISMO
  // alumno sembrado. Con un solo escenario para todo el bloque, lo que un
  // test autoguarda (cualquier avance de paso dispara un flush: ver
  // `mergeLocalDraft` en `survey.js`, que en modo paginado siempre ve
  // `draft_updated_at=""` y por tanto el borrador local "más nuevo") queda
  // ahí para el SIGUIENTE test -que ya no arranca en el paso 1, sino donde
  // `_start_step` decida según lo que el anterior dejó escrito-. Medido: sin
  // este aislamiento, "completa los tres pasos y envía" arrancaba en el
  // paso 3 (todo lo demás ya satisfecho por un test previo) y nunca
  // encontraba `situacion_laboral`. Un escenario nuevo por test es más lento
  // pero elimina ese acoplamiento por completo.
  test.beforeEach(() => { ctx = seedScenario(); });
  test.afterEach(() => { cleanupScenario(ctx); });

  test('el next del login regresa a la encuesta con la sección 1 prellenada y editable', async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('anon') });
    const page = await c.newPage();

    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    expect(page.url()).toContain(`/itcj/login?next=${SURVEY_URL}`);

    await page.fill('#control_number', ctx.studentControl);
    await page.fill('#nip', E2E_NIP);
    await page.click('#btnLogin');

    // Sin `?next=` válido, `auth.js` mandaría a /itcj/m/ (home por rol) y la
    // encuesta se perdería: esto es lo que Tarea 14/2 existen para evitar.
    await page.waitForURL('**' + SURVEY_URL);
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
    await expect(page.getByText('Paso 1 de 3')).toBeVisible();

    // Ya no es anónimo: el banner persistente de "no acredita" desaparece.
    await expect(page.locator('[data-tt-anon-notice]')).toHaveCount(0);

    // Sección 1 prellenada desde `User.full_name` (Tarea 4) y EDITABLE, no de
    // solo lectura: el alumno sembrado es "<TAG> ALUMNO".
    const nombre = page.locator('[name="nombre_completo"]');
    await expect(nombre).toHaveValue(/ALUMNO/);
    await expect(nombre).toBeEditable();
    await nombre.fill('Nombre Corregido Por El Alumno');
    await expect(nombre).toHaveValue('Nombre Corregido Por El Alumno');

    await c.close();
  });

  test('adelante es estricto: sin el obligatorio no avanza y re-pinta con error inline (200, no un 400 mudo)', async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Paso 1 de 3')).toBeVisible();

    // `nombre_completo` ya viene prellenado (Tarea 4): el único obligatorio
    // que de verdad falta en el paso 1 es `situacion_laboral`.
    const paso = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === STEP_URL
    );
    await page.getByRole('button', { name: 'Siguiente' }).click();
    // htmx no swappea en 4xx (spec 6.1): un 400 aquí dejaría la pantalla muda.
    expect((await paso).status()).toBe(200);

    await expect(page.getByText('Paso 1 de 3')).toBeVisible();
    await expect(page.locator('[data-tt-error="situacion_laboral"]')).toBeVisible();
    await expect(
      page.locator('[data-tt-field="situacion_laboral"] [aria-invalid="true"]')
    ).toBeAttached();

    await c.close();
  });

  test('atrás es libre al indicador -incluido un salto NO adyacente-, y el avance queda acotado en el servidor', async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });

    // Paso 1 -> 2: "buscando" deja `relacion_carrera` (visible_when
    // situacion_laboral=empleado) invisible, así que el mini-schema del paso 1
    // queda satisfecho con un solo campo.
    await page.locator('input[name="situacion_laboral"][value="buscando"]').check();
    await page.getByRole('button', { name: 'Siguiente' }).click();
    await expect(page.getByText('Paso 2 de 3')).toBeVisible();

    // Paso 2 -> 3: "detalle" no tiene obligatorios, Siguiente no encuentra nada que objetar.
    await page.getByRole('button', { name: 'Siguiente' }).click();
    await expect(page.getByText('Paso 3 de 3')).toBeVisible();
    // Último paso visible: el botón ya es el envío final, no "Siguiente".
    await expect(page.getByRole('button', { name: 'Enviar respuestas' })).toBeVisible();

    // El indicador de progreso ofrece los DOS pasos ya visitados como
    // controles reales (<button>); el salto al paso 1 desde el 3 es NO
    // ADYACENTE -salta el 2 sin pasar por su validación (aquí no hay nada que
    // validar, pero el mecanismo es el mismo)-, que es justo lo que distingue
    // al indicador de un simple botón "Atrás".
    await page.locator('.tt-steps-item.is-done .tt-steps-link', { hasText: 'Situación laboral' }).click();
    await expect(page.getByText('Paso 1 de 3')).toBeVisible();
    // Lo contestado sigue ahí: el estado del recorrido es el propio
    // `submitted`, no una sesión de servidor que el salto pudiera resetear.
    await expect(page.locator('input[name="situacion_laboral"][value="buscando"]')).toBeChecked();

    // Acotado en el SERVIDOR: una petición forjada que dice estar en el paso 1
    // ("tt_step=0") y pide saltar al paso 3 ("tt_goto=2", 0-indexado) sin
    // haberlo validado no debe moverse -ni siquiera con sesión válida-. Un
    // control de UI real nunca ofrece ese botón (el paso 3 aún no es
    // "is-done" desde el paso 1), así que esto prueba el límite del lado del
    // servidor, no el del cliente.
    const forjado = await page.request.post(STEP_URL, {
      form: { tt_step: '0', tt_goto: '2', nombre_completo: 'x', situacion_laboral: 'buscando' },
    });
    expect(forjado.status(), 'un avance forjado tampoco debe ser un 400/500 mudo').toBe(200);
    const html = await forjado.text();
    expect(html, 'un tt_goto por delante del paso actual debe ignorarse, no moverse').toContain('Paso 1 de 3');

    await c.close();
  });

  test('completa los tres pasos y envía: tarjeta de gracias, credita el requisito, sin redirect', async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    const urlAntes = page.url();

    await page.locator('input[name="situacion_laboral"][value="estudiando"]').check();
    await page.getByRole('button', { name: 'Siguiente' }).click();
    await expect(page.getByText('Paso 2 de 3')).toBeVisible();

    await page.getByRole('button', { name: 'Siguiente' }).click();
    await expect(page.getByText('Paso 3 de 3')).toBeVisible();

    const envio = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === SURVEY_URL
    );
    await page.getByRole('button', { name: 'Enviar respuestas' }).click();
    expect((await envio).status()).toBe(200);

    await expect(page.locator('#tt-survey-thanks')).toBeVisible();
    // Con sesión, el crédito del requisito NO es el genérico "anonymous" del
    // camino público sin sesión (spec §6.7/D-crédito).
    const credito = await page.locator('#tt-survey-thanks').getAttribute('data-tt-credit');
    expect(credito).not.toBe('anonymous');
    expect(page.url(), 'el envío swappea, no redirige').toBe(urlAntes);

    await c.close();
  });
});

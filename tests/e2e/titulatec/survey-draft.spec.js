// @ts-check
/**
 * Borradores de la encuesta — criterios 5 y 6 del spec (Tarea 6: reescrito
 * para sesión + paginado por pasos).
 *
 * Dos caminos distintos, igual que antes:
 *  · CON sesión: el borrador va al servidor (una fila por form+usuario, UPDATE
 *    en sitio) y sobrevive a un cambio de paso y a una recarga limpia.
 *  · SIN sesión: el borrador vive solo en localStorage, y al iniciar sesión
 *    desde el banner el usuario debe REGRESAR A LA ENCUESTA (no al home por
 *    rol) con lo capturado intacto.
 *
 * QUÉ CAMBIÓ (Tarea 6). El escenario de `_helpers.js` siembra el formulario
 * con `is_anonymous=False` (como el `egresados` real): un visitante SIN
 * sesión contra ese formulario ya no ve el banner ni el formulario -
 * `_requiere_sesion` lo manda al login ANTES de pintar nada-, así que el
 * camino "sin sesión" de este archivo dejó de ser alcanzable tal cual estaba
 * escrito. Ese camino sigue existiendo en la app para cualquier formulario
 * que declare `is_anonymous=True` (el propio código lo dice:
 * `pages/public.py:_requiere_sesion`, "un formulario futuro... los sigue
 * usando tal cual"), así que en vez de borrar la cobertura se usa
 * `setFormAnonymous(ctx, true)` -añadido a `_helpers.js` en esta tarea- para
 * voltear ESE flag en el formulario ya sembrado, sin tocar nada de lo que
 * `survey-draft-budget.spec.js` ya usa de él. Es indiferente para el test
 * CON sesión: `_requiere_sesion(form) and user is None` nunca es cierto si
 * hay `user`.
 *
 * El formulario también pasó de una sola pantalla a un asistente por pasos:
 * `empresa`/`comentarios` viven en la sección "detalle" (paso 2 de 3), no en
 * la única pantalla que existía antes. Cada test navega ahí primero.
 *
 * `beforeEach`/`afterEach`, NO `beforeAll`/`afterAll`: los dos tests
 * comparten el mismo formulario/alumno si usaran un solo escenario, y el
 * borrador que uno autoguarda (cualquier cambio de paso dispara un flush -
 * ver `mergeLocalDraft` en `survey.js`, que en modo paginado siempre ve
 * `draft_updated_at=""`, o sea "el local es más nuevo"-) contaminaría el paso
 * de arranque (`_start_step`) del otro. Un escenario nuevo por test cuesta
 * unos segundos más y elimina ese acoplamiento.
 *
 * `storageState: { cookies: [], origins: [] } }`, NUNCA `storageState:
 * undefined` (ver el encabezado de `_helpers.js` y `public-survey.spec.js`):
 * en Playwright 1.61 un `undefined` es un no-op y el contexto heredaría el
 * storageState global del proyecto (admin de helpdesk, sin bypass en
 * `require_page_app`/`_requiere_sesion`). Ninguno de los dos tests de abajo
 * usa el `page` de la fixture por defecto (cada uno abre su propio
 * `browser.newContext(...)`), así que esta línea es defensiva por convención
 * de carpeta, no funcionalmente necesaria hoy — se deja de cualquier forma
 * para no ser la excepción.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, setFormAnonymous, stateFor, E2E_NIP } = require('./_helpers');

let ctx;

test.beforeEach(() => { ctx = seedScenario(); });
test.afterEach(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const DRAFT_URL = '/titulatec/encuesta-egresados/borrador';
const STEP_URL = '/titulatec/encuesta-egresados/paso';

test('con sesión: lo escrito sobrevive a un cambio de paso y a una recarga', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  // Reloj falso, instalado ANTES de navegar (igual que `survey-draft-budget.
  // spec.js`): el cambio de paso de abajo deja el techo de 30 s vigente -ver
  // el comentario junto a `guardado`, más abajo-, y sin fingir el tiempo esta
  // prueba tendría que esperar hasta 30 s reales entre dos POST.
  await page.clock.install();
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
  await expect(page.getByText('Paso 1 de 3')).toBeVisible();

  // "buscando" deja `relacion_carrera` (visible_when situacion_laboral=
  // empleado) invisible: el único obligatorio del paso 1 que falta -
  // `nombre_completo` ya viene prellenado (Tarea 4)- es `situacion_laboral`.
  await page.locator('input[name="situacion_laboral"][value="buscando"]').check();
  const paso = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === STEP_URL
  );
  await page.getByRole('button', { name: 'Siguiente' }).click();
  await paso;
  await expect(page.getByText('Paso 2 de 3')).toBeVisible();

  // Ese cambio de paso YA disparó un flush (`mergeLocalDraft` en `survey.js`
  // ve `draft_updated_at=""` en todo render paginado, o sea "el local es más
  // nuevo") y dejó `lastSentAt` fresco con el techo de 30 s vigente. El
  // debounce de 5 s de este tecleo vuelve a llamar `flush()`, pero como el
  // techo sigue vigente NO manda de inmediato: programa el envío para cuando
  // expire (mismo comportamiento que documenta `survey-draft-budget.spec.js`,
  // desviación 2). `runFor` avanza el reloj falso sin esperar de verdad.
  const guardado = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === DRAFT_URL
  );
  await page.fill('[name="empresa"]', 'Fábrica de Tornillos del Norte');
  await page.fill('[name="comentarios"]', 'Sigo en la misma empresa desde 2027.');
  await page.clock.runFor(35_000); // debounce (5 s) + techo de 30 s, con margen
  // 204, no 200: la ruta de borrador (Tarea 13) responde 204 en TODOS sus
  // caminos, con sesión y sin ella. Por eso el 204 solo no confirma nada: la
  // escritura real la confirma `X-Tt-Draft-Saved: 1`, que es lo que lleva la
  // nota de la cabecera a «Guardado hh:mm» (2026-09-15).
  const respuesta = await guardado;
  expect(respuesta.status()).toBe(204);
  expect(respuesta.headers()['x-tt-draft-saved']).toBe('1');
  await expect(page.locator('[data-tt-save-text]')).toHaveText(/^Guardado \d{2}:\d{2}$/);

  await page.reload({ waitUntil: 'domcontentloaded' });
  // `_start_step` NO repone "el último paso que viste": repone el PRIMER paso
  // con un obligatorio VISIBLE sin contestar, o el ÚLTIMO si ya no queda
  // ninguno (`pages/public.py:_start_step`). "detalle" no tiene obligatorios
  // y "seguimiento" tampoco, así que con el paso 1 ya satisfecho la recarga
  // aterriza en el paso 3, no en el 2 donde se escribió -eso es el
  // comportamiento correcto, no una regresión de esta prueba-. Lo escrito
  // sigue viajando (oculto, en `other_fields`) y el paso 2 sigue siendo "ya
  // visitado": el atrás libre del indicador (Tarea 3, ronda 2) lo recupera
  // visible, que es lo que se verifica a continuación.
  await expect(page.getByText('Paso 3 de 3')).toBeVisible();
  await page.locator('.tt-steps-item.is-done .tt-steps-link', { hasText: 'Detalle de tu empleo' }).click();
  await expect(page.getByText('Paso 2 de 3')).toBeVisible();
  await expect(page.locator('[name="empresa"]')).toHaveValue('Fábrica de Tornillos del Norte');
  await expect(page.locator('[name="comentarios"]')).toHaveValue('Sigo en la misma empresa desde 2027.');

  await c.close();
});

test('anónimo (formulario is_anonymous=True): iniciar sesión desde el banner regresa a la encuesta con lo capturado', async ({ browser }) => {
  // Sin este volteo, `_requiere_sesion` mandaría a este visitante al login
  // ANTES de pintar nada (el formulario del escenario nace `is_anonymous=
  // False`, como el real): no habría banner, ni formulario, ni nada que
  // capturar en localStorage.
  setFormAnonymous(ctx, true);

  const c = await browser.newContext({ storageState: stateFor('anon') });
  const page = await c.newPage();
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
  await expect(page.getByText(/no quedará en tu expediente de titulación/i)).toBeVisible();
  // Sin sesión no hay guardado de servidor que anunciar: no hay nota de guardado.
  await expect(page.locator('[data-tt-save]')).toHaveCount(0);

  // Sin sesión no se escribe NADA en la base: el borrador es solo localStorage.
  let escrituras = 0;
  page.on('request', (r) => {
    if (r.method() === 'POST' && new URL(r.url()).pathname === DRAFT_URL) escrituras += 1;
  });

  await page.fill('[name="nombre_completo"]', 'Anónimo De Prueba');
  await page.locator('input[name="situacion_laboral"][value="buscando"]').check();
  await page.waitForTimeout(6500); // más que el debounce (5s), para dar oportunidad
  expect(escrituras, 'un anónimo no puede generar escrituras de borrador').toBe(0);

  await page.getByRole('link', { name: /iniciar sesión y continuar/i }).click();
  await page.waitForURL(/\/itcj\/login\?/);
  // NO %2F: `login_url` la arma el servidor con un f-string sin urlencode
  // (`pages/public.py`, `SURVEY_LOGIN_URL`), así que el href literal ya trae
  // `next=/titulatec/encuesta-egresados` con barras crudas.
  expect(page.url()).toContain(`next=${SURVEY_URL}`);

  await page.fill('#control_number', ctx.studentControl);
  await page.fill('#nip', E2E_NIP);
  await page.click('#btnLogin');

  // Sin ?next=, auth.js mandaría a /itcj/m/ y lo capturado se perdería.
  await page.waitForURL('**' + SURVEY_URL);
  await expect(page.locator('[name="nombre_completo"]')).toHaveValue('Anónimo De Prueba');
  await expect(
    page.locator('input[name="situacion_laboral"][value="buscando"]')
  ).toBeChecked();
  // Ya con sesión, desaparece el aviso de que no acredita y aparece la nota de guardado.
  await expect(page.getByText(/no quedará en tu expediente de titulación/i)).toBeHidden();
  await expect(page.locator('[data-tt-save]')).toBeVisible();

  await c.close();
});

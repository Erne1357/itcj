// @ts-check
/**
 * Borradores de la encuesta — criterios 5 y 6 del spec.
 *
 * Dos caminos distintos:
 *  · CON sesión: el borrador va al servidor (una fila por form+usuario, UPDATE
 *    en sitio) y sobrevive a una recarga limpia.
 *  · SIN sesión: el borrador vive solo en localStorage, y al iniciar sesión
 *    desde el banner el usuario debe REGRESAR A LA ENCUESTA (no al home por
 *    rol) con lo capturado intacto. Eso depende del `?next=` validado que la
 *    Tarea 14 añadió a /itcj/login: antes de este trabajo `next=` no existía
 *    en itcj2/ y un alumno caía siempre en /itcj/m/.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState: undefined`
 * (ver el encabezado de `_helpers.js` y `public-survey.spec.js`): en
 * Playwright 1.61 un `undefined` es un no-op y el contexto heredaría el
 * storageState global del proyecto (admin de helpdesk, sin bypass en
 * `require_page_app`). Ninguno de los dos tests de abajo usa el `page` de la
 * fixture por defecto (cada uno abre su propio `browser.newContext(...)`), así
 * que esta línea es defensiva por convención de carpeta, no funcionalmente
 * necesaria hoy — se deja de cualquier forma para no ser la excepción.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor, E2E_NIP } = require('./_helpers');

let ctx;

test.beforeAll(() => { ctx = seedScenario(); });
test.afterAll(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const DRAFT_URL = '/titulatec/encuesta-egresados/borrador';

test('con sesión: lo escrito sobrevive a una recarga', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();

  const guardado = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === DRAFT_URL
  );
  await page.fill('[name="empresa"]', 'Fábrica de Tornillos del Norte');
  await page.fill('[name="comentarios"]', 'Sigo en la misma empresa desde 2027.');
  // Debounce de 5 s (DRAFT_DEBOUNCE_MS), en tiempo REAL (esta spec no instala
  // page.clock: un solo debounce de 5 s es barato de esperar de verdad, y así
  // se evita mezclar reloj falso con la navegación de login del segundo test).
  // El primer envío no topa con el techo de 30 s porque no hay escritura previa
  // (`lastSentAt` arranca en 0: ver `DRAFT_MIN_INTERVAL_MS` en `survey.js`).
  // 204, no 200: la ruta de borrador (Tarea 13, Produces) responde 204 en
  // TODOS sus caminos de éxito, con sesión y sin ella.
  expect((await guardado).status()).toBe(204);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('[name="empresa"]')).toHaveValue('Fábrica de Tornillos del Norte');
  await expect(page.locator('[name="comentarios"]')).toHaveValue('Sigo en la misma empresa desde 2027.');

  await c.close();
});

test('anónimo: iniciar sesión desde el banner regresa a la encuesta con lo capturado', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('anon') });
  const page = await c.newPage();
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });

  // Sin sesión no se escribe NADA en la base: el borrador es solo localStorage.
  let escrituras = 0;
  page.on('request', (r) => {
    if (r.method() === 'POST' && new URL(r.url()).pathname === DRAFT_URL) escrituras += 1;
  });

  await page.locator('input[name="situacion_laboral"][value="empleado"]').check();
  await page.fill('[name="empresa"]', 'Maquiladora Anónima');
  await page.waitForTimeout(6500); // más que el debounce, para dar oportunidad
  expect(escrituras, 'un anónimo no puede generar escrituras de borrador').toBe(0);

  await page.getByRole('link', { name: /iniciar sesión y continuar/i }).click();
  await page.waitForURL(/\/itcj\/login\?/);
  // NO %2F: `login_url` la arma el servidor con un f-string sin urlencode
  // (`pages/public.py:_form_ctx`, `"login_url": f"/itcj/login?next={SURVEY_URL}"`),
  // así que el href literal ya trae `next=/titulatec/encuesta-egresados` con
  // barras crudas. `/` es un carácter válido de `query` en RFC 3986 y ni el
  // navegador ni Playwright lo re-escapan al navegar: verificado contra la
  // página real (`curl` al HTML: `href="/itcj/login?next=/titulatec/encuesta-egresados"`)
  // y contra `page.url()` tras un clic real en Chromium 1.61 — nunca aparece
  // `%2F`. El brief original asertaba la forma escapada; con eso la spec
  // fallaría siempre contra una app correcta.
  expect(page.url()).toContain('next=/titulatec/encuesta-egresados');

  await page.fill('#control_number', ctx.studentControl);
  await page.fill('#nip', E2E_NIP);
  await page.click('#btnLogin');

  // Sin ?next=, auth.js:49 mandaría a /itcj/m/ y la encuesta se perdería.
  await page.waitForURL('**/titulatec/encuesta-egresados');
  await expect(page.locator('[name="empresa"]')).toHaveValue('Maquiladora Anónima');
  await expect(
    page.locator('input[name="situacion_laboral"][value="empleado"]')
  ).toBeChecked();
  // Ya con sesión, desaparece el aviso de que no acredita.
  await expect(page.getByText(/no quedará en tu expediente de titulación/i)).toBeHidden();

  await c.close();
});

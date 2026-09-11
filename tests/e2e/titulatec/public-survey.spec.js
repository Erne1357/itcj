// @ts-check
/**
 * Encuesta de egresados — camino ANÓNIMO completo (criterios 1 y 2 del spec).
 *
 * `storageState: undefined` a propósito y sin sembrar nada: la ruta pública se
 * define por OMITIR la dependencia de autorización (spec §2.1 — no hay
 * allowlist, ni decorador, ni prefijo exento), así que la prueba de que es
 * pública es justamente entrar sin cookie. El storageState global (admin de
 * helpdesk) no sirve aquí: `require_page_app` no tiene bypass de admin global.
 *
 * Depende de que haya un cuestionario 'egresados' ABIERTO en la base de dev, y
 * sirve cualquiera de los dos: el v1 que siembra la Tarea 24
 * (`titulatec load-survey-2026-09`) o el superset que abre el `seedScenario()`
 * de `_helpers.js`, que repite esas dos preguntas primero con las etiquetas
 * idénticas justo para que esta spec funcione contra ambos. Si falla con "no
 * hay formulario abierto", corre ese comando antes.
 *
 * `storageState: { cookies: [], origins: [] }`, NO `storageState: undefined`:
 * en Playwright 1.61 la fixture `storageState` solo se sobreescribe cuando el
 * valor resuelto es distinto de `undefined`
 * (`node_modules/playwright/lib/index.js`, `_combinedContextOptions`:
 * `if (storageState !== void 0) options.storageState = storageState;`), así
 * que pasar `undefined` es un no-op y el contexto hereda el `storageState`
 * global del proyecto (`.auth/state.json`, admin de helpdesk) — verificado
 * aquí mismo: con `undefined` la página cargaba autenticada como ese admin y
 * el primer test fallaba porque el banner anónimo nunca se renderizaba.
 */
const { test, expect } = require('@playwright/test');

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';
const P1 = '¿Cuál es tu situación laboral actual?';
const P2 = '¿Qué tanto se relaciona tu empleo con tu carrera?';

test('carga sin cookie y muestra el aviso de que no acredita', async ({ page }) => {
  const res = await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
  expect(res.status(), 'la ruta pública no puede redirigir al login').toBe(200);

  await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
  await expect(page.getByText(P1)).toBeVisible();

  // Criterio 2: el aviso es PERSISTENTE, no un toast.
  await expect(
    page.getByText(/no quedará en tu expediente de titulación/i)
  ).toBeVisible();
  await expect(
    page.getByRole('link', { name: /iniciar sesión y continuar/i })
  ).toBeVisible();
});

test('la pregunta condicional solo aparece al marcar "Trabajando"', async ({ page }) => {
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });

  // visible_when: {"situacion_laboral": "empleado"}
  await expect(page.getByText(P2)).toBeHidden();
  await page.locator('input[name="situacion_laboral"][value="empleado"]').check();
  await expect(page.getByText(P2)).toBeVisible();
});

test('un envío incompleto re-renderiza el formulario con error inline, no un 400 mudo', async ({ page }) => {
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });

  const post = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === SURVEY_URL
  );
  await page.getByRole('button', { name: 'Enviar respuestas' }).click();
  // htmx NO swappea en 4xx: un 400 aquí dejaría la pantalla muda (spec §6.1).
  expect((await post).status()).toBe(200);

  await expect(page.locator('[data-tt-error="situacion_laboral"]')).toBeVisible();
  // `situacion_laboral` es un radio: T12 pone `aria-invalid` en el
  // `role="radiogroup"`, no en cada <input>. Es la decisión ARIA correcta para
  // un campo agrupado, así que el locator se ancla en el envoltorio `.tt-q`,
  // que ya lleva `data-tt-field="{{ f.key }}"`.
  await expect(
    page.locator('[data-tt-field="situacion_laboral"] [aria-invalid="true"]')
  ).toBeAttached();
});

test('envío válido: tarjeta de gracias, sin redirect', async ({ page }) => {
  await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
  const urlAntes = page.url();

  await page.locator('input[name="situacion_laboral"][value="empleado"]').check();
  await page.locator('input[name="relacion_carrera"][value="4"]').check();

  const post = page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === SURVEY_URL
  );
  await page.getByRole('button', { name: 'Enviar respuestas' }).click();
  expect((await post).status()).toBe(200);

  await expect(page.locator('#tt-survey-thanks')).toBeVisible();
  await expect(page.locator('#tt-survey-thanks[data-tt-credit]')).toHaveCount(1);
  await expect(page.getByText(P1)).toBeHidden();
  expect(page.url(), 'el envío swappea, no redirige').toBe(urlAntes);
});

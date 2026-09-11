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
 *
 * LIMPIEZA DE LA RESPUESTA SINTÉTICA (Task 25 ronda 1, hallazgo 3)
 * -----------------------------------------------------------------
 * Esta spec NO llama a `seedScenario()` — corre a propósito contra lo que ya
 * esté abierto (ver arriba) — así que la respuesta que escribe el test
 * "envío válido" no lleva ningún marcador E2E_TAG: entra por la ruta
 * anónima y el validador descarta cualquier llave JSON que el `schema` no
 * declare, así que no hay forma de "etiquetarla" en el payload. Es
 * indistinguible de una respuesta real. `titulatec_survey_responses`
 * alimenta el inbox de oficiales y el export CSV de la campaña real de
 * encuesta de egresados, así que dejar esa fila sesga en silencio la
 * estadística que la campaña existe para medir, y no se autocorrige: cada
 * corrida futura (CI, o quien re-verifique la spec) suma una más.
 *
 * El `beforeAll` captura, ANTES de que corra ningún test, (a) el id del
 * formulario 'egresados' actualmente abierto y (b) el propio reloj de
 * Postgres (`NOW()::timestamp`, NO `Date.now()` de Node: `submitted_at` es
 * `TIMESTAMP WITHOUT TIME ZONE` y el servidor corre en
 * America/Ciudad_Juarez, no UTC — comparar contra un ISO-8601 de Node
 * quedaría 6 h desfasado y el `afterAll` no borraría nada). El `afterAll`
 * borra solo las respuestas de ESE formulario con `submitted_at >=` esa
 * marca. `playwright.config.js` fija `workers: 1` y `fullyParallel: false`
 * (ejecución en serie, sin escritura concurrente de otro archivo), así que
 * el corte por marca de tiempo identifica exactamente lo que esta spec
 * escribió — ninguna otra spec de esta carpeta hace POST a esta ruta.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

test.use({ storageState: { cookies: [], origins: [] } });

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const SURVEY_URL = '/titulatec/encuesta-egresados';
const P1 = '¿Cuál es tu situación laboral actual?';
const P2 = '¿Qué tanto se relaciona tu empleo con tu carrera?';

/** Corre Python dentro del contenedor y devuelve su stdout (idéntico a `_helpers.js`). */
function runInContainer(py, { timeout = 60_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

let limpieza = null; // { formId, startedAt } — null si beforeAll no llegó a correr

test.beforeAll(() => {
  const out = runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    form_id = db.execute(text(
        "SELECT id FROM titulatec_survey_forms WHERE code = 'egresados' AND status = 'open'"
    )).scalar()
    started_at = db.execute(text("SELECT NOW()::timestamp")).scalar()
    print(f"{form_id}|{started_at.isoformat()}")
finally:
    db.close()
`).trim();
  const [formId, startedAt] = out.split('|');
  limpieza = { formId: parseInt(formId, 10), startedAt };
});

test.afterAll(() => {
  // Defensivo: si `beforeAll` no llegó a capturar el punto de corte, no hay
  // nada seguro que borrar (mejor una fila sintética de más que arriesgar un
  // DELETE sin acotar).
  if (!limpieza || !limpieza.formId || !limpieza.startedAt) return;
  runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text(
        "DELETE FROM titulatec_survey_answers WHERE response_id IN "
        "(SELECT id FROM titulatec_survey_responses WHERE form_id = :f AND submitted_at >= :ts)"),
        {"f": ${limpieza.formId}, "ts": "${limpieza.startedAt}"})
    result = db.execute(text(
        "DELETE FROM titulatec_survey_responses WHERE form_id = :f AND submitted_at >= :ts"),
        {"f": ${limpieza.formId}, "ts": "${limpieza.startedAt}"})
    db.commit()
    print(f"public-survey.spec.js afterAll: borradas {result.rowcount} respuesta(s) sintética(s) (form ${limpieza.formId}, >= ${limpieza.startedAt})")
finally:
    db.close()
`);
});

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

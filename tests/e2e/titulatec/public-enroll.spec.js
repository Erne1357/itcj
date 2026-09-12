// @ts-check
/**
 * Auto-inscripción pública — ventana, validación visible y honeypot.
 *
 * El escenario cierra TODA convocatoria abierta de dev y deja exactamente una
 * (ver `_helpers.js`): `CohortService.public_enrollment_cohort` FALLA CERRADO
 * con más de una abierta (503, spec §6.6) y hasta este trabajo toda
 * convocatoria nacía `status='open'` con fechas NULL, así que en dev el
 * predicado era verdadero para todas.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState: undefined`
 * (RULING R1 / ver el encabezado de `_helpers.js` y `public-survey.spec.js`):
 * en Playwright 1.61 un `undefined` es un no-op
 * (`node_modules/playwright/lib/index.js:324-325`:
 * `if (storageState !== void 0) options.storageState = storageState;`), así
 * que el contexto heredaría el storageState global del proyecto
 * (`.auth/state.json`, admin de HELPDESK) en vez de quedar sin sesión.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { seedScenario, cleanupScenario, setCohortStatus } = require('./_helpers');

let ctx;

test.beforeAll(() => { ctx = seedScenario(); });
test.afterAll(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const ENROLL_URL = '/titulatec/inscripcion';

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

/** Corre Python dentro del contenedor (mismo mecanismo que `_helpers.js` y
 * `public-survey.spec.js`; no está exportado por `_helpers.js`, así que cada
 * spec que necesita una consulta ad hoc trae su propia copia mínima). */
function runInContainer(py, { timeout = 60_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

/** Cuántas `EnrollmentRequest` existen para un número de control (finding 2,
 * ronda 1 de revisión de la Tarea 27). */
function enrollmentRequestCountFor(controlNumber) {
  const out = runInContainer(`
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    n = db.execute(text(
        "SELECT count(*) FROM titulatec_enrollment_requests WHERE control_number = :cn"),
        {"cn": "${controlNumber}"}).scalar()
    print(n)
finally:
    db.close()
`).trim();
  return parseInt(out, 10);
}

test.describe('ventana abierta', () => {
  test.beforeAll(() => { setCohortStatus(ctx, 'open'); });

  test('muestra el formulario, sin nombrar la convocatoria', async ({ page }) => {
    const res = await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    expect(res.status()).toBe(200);

    await expect(page.locator('main[data-tt-page="public_enroll"]')).toBeVisible();
    await expect(page.locator('[name="control_number"]')).toBeVisible();
    await expect(page.locator('[name="contact_email"]')).toBeVisible();
    await expect(page.locator('[name="phone"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enviar solicitud' })).toBeVisible();
  });

  test('el honeypot existe y queda fuera de la pantalla', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    // NO se aserta `toBeHidden()`: para Playwright «visible» es «caja no vacía
    // y `visibility` normal», así que el 1x1 en `left:-9999px` que E3 exige le
    // sale VISIBLE. La trampa se comprueba por POSICIÓN. Prohibido "arreglar"
    // esto con `display:none` en `.tt-public-hp`: los bots descartan lo que está
    // oculto por display y la trampa dejaría de atrapar nada.
    const trampa = page.locator('input[name="website"]');
    await expect(trampa, 'falta el campo trampa (E3)').toBeAttached();
    const box = await trampa.boundingBox();
    expect(box, 'el honeypot debe existir en el layout').not.toBeNull();
    expect(box.x + box.width, 'el honeypot debe quedar fuera de la pantalla').toBeLessThan(0);
    await expect(page.locator('.tt-public-hp[aria-hidden="true"]')).toBeAttached();
  });

  test('un envío rechazado renderiza texto VISIBLE, no un 400 mudo', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    // Control fuera de CONTROL_NUMBER_RE = ^(\d{8}|[A-Za-z]\d{7,9})$
    await page.fill('[name="control_number"]', '123');
    await page.fill('[name="first_name"]', 'Juan');
    await page.fill('[name="last_name"]', 'Pérez');
    await page.fill('[name="phone"]', '6560000000');
    await page.fill('[name="contact_email"]', 'juan.perez@example.com');

    const post = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ENROLL_URL
    );
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    // htmx NO swappea en 4xx: un 400 dejaría la pantalla exactamente igual y
    // el usuario no sabría qué pasó (spec §6.1, riesgo 4).
    expect((await post).status()).toBe(200);

    await expect(page.locator('[data-tt-error="control_number"]')).toBeVisible();
    await expect(page.locator('[name="control_number"][aria-invalid="true"]')).toBeVisible();
    // El servidor conserva lo capturado al re-renderizar.
    await expect(page.locator('[name="first_name"]')).toHaveValue('Juan');
  });

  test('el honeypot lleno devuelve la tarjeta genérica y no escribe nada', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    // A propósito NO se llena `program_id`: `pages/public.py:878-882` exige
    // `program_id` o `program_text`, así que si el corto-circuito de la trampa
    // desapareciera del todo, este envío caería en la validación normal y
    // re-renderizaría `enroll_form.html` con `errors.program_id` — un parcial
    // que NO trae ningún `data-tt-notice` (ese atributo solo lo pinta
    // `notice_card.html`). Por eso la aserción de abajo no es vacua: si la
    // trampa dejara de disparar, no habría NINGÚN `[data-tt-notice]` en la
    // página, ni "generic" ni ningún otro valor del vocabulario cerrado.
    await page.fill('[name="control_number"]', '29990888');
    await page.fill('[name="first_name"]', 'Bot');
    await page.fill('[name="last_name"]', 'Automático');
    await page.fill('[name="phone"]', '6560000001');
    await page.fill('[name="contact_email"]', 'bot@example.com');
    await page.locator('input[name="website"]').fill('http://spam.example', { force: true });

    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    // `notice_key` del `_ENROLL_CARD` de la Tarea 19: la MISMA tarjeta que ven
    // el alta buena y el control inexistente (E8, tres ramas indistinguibles).
    await expect(page.locator('[data-tt-notice="generic"]')).toBeVisible();

    // Lo anterior prueba "se ve la tarjeta correcta"; NO prueba "no escribió
    // nada" (finding 2, ronda 1 de revisión). Un regresivo que moviera el
    // corto-circuito de la trampa a DESPUÉS de
    // `EnrollmentRequestService.create(...)` -- sin tocar el valor de
    // retorno ni la tarjeta-- dejaría esta prueba en verde mientras el bot
    // escribe basura en la bandeja del oficial. Se lee directo de la base,
    // no del `EnrollmentRequestService` (mismo criterio que `processFolioFor`
    // en `admin-requests.spec.js`: la aserción de pantalla no depende de
    // cómo esté hecha la escritura).
    expect(enrollmentRequestCountFor('29990888'), 'la trampa no debe escribir en la tabla')
      .toBe(0);
  });
});

test.describe('ventana cerrada', () => {
  test.beforeAll(() => { setCohortStatus(ctx, 'closed'); });
  test.afterAll(() => { setCohortStatus(ctx, 'open'); });

  test('muestra la tarjeta de cierre en vez del formulario', async ({ page }) => {
    const res = await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    expect(res.status(), 'la ruta pública sigue respondiendo 200, no 403 ni 503').toBe(200);

    await expect(page.locator('[data-tt-notice="closed"]')).toBeVisible();
    await expect(page.locator('[name="control_number"]')).toHaveCount(0);
  });

  test('no desborda a 360 ni a 1920 con la tarjeta de cierre', async ({ page }) => {
    for (const [w, h] of [[360, 740], [1920, 1080]]) {
      await page.setViewportSize({ width: w, height: h });
      await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('[data-tt-notice="closed"]')).toBeVisible();
      const m = await page.evaluate(() => ({
        s: document.documentElement.scrollWidth, i: window.innerWidth,
      }));
      expect(m.s, `desborde a ${w}px: ${m.s} > ${m.i}`).toBeLessThanOrEqual(m.i);
    }
  });
});

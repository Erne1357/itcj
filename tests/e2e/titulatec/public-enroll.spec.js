// @ts-check
/**
 * Auto-inscripción pública — ventana, validación visible, honeypot y revisión previa.
 *
 * Desde 2026-09-15 toda solicitud pasa por la bandeja de Servicios Escolares:
 * el alta no manda correo ni emite liga, y la tarjeta dice «Recibimos tu
 * solicitud». El correo personal se teclea dos veces (`contact_email_confirm`).
 *
 * El escenario cierra TODA convocatoria abierta de dev y deja exactamente una
 * (ver `_helpers.js`): `CohortService.public_enrollment_cohort` FALLA CERRADO
 * con más de una abierta (503, spec §6.6).
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
const TARJETA_TITULO = 'Recibimos tu solicitud';
const TARJETA_CUERPO = 'Servicios Escolares la revisará. Si se aprueba, te llegará un correo '
  + 'con tu acceso. Revisa también la carpeta de correo no deseado.';

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

/** Cuántas `EnrollmentRequest` existen para un número de control. */
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

/** Estado de la última solicitud de un número de control, o `null`. */
function enrollmentRequestStateFor(controlNumber) {
  const out = runInContainer(`
import json
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    row = db.execute(text(
        "SELECT status, verify_token_hash IS NOT NULL FROM titulatec_enrollment_requests "
        "WHERE control_number = :cn ORDER BY id DESC LIMIT 1"),
        {"cn": "${controlNumber}"}).first()
    print(json.dumps({"status": row[0], "hasToken": bool(row[1])} if row else None))
finally:
    db.close()
`).trim();
  return JSON.parse(out);
}

/**
 * Número de control nuevo en cada corrida. El límite por número de control es
 * de 3 envíos al día en Redis y el borrado del escenario no lo toca: con uno
 * fijo, la cuarta corrida del día vería «Demasiados intentos».
 */
function controlNuevo() {
  return `2999${2000 + Math.floor(Math.random() * 5000)}`;
}

/** Llena el formulario completo con datos válidos; `over` pisa campos. */
async function llenarFormulario(page, over = {}) {
  const datos = {
    control_number: controlNuevo(),
    first_name: 'Juan',
    last_name: 'Pérez',
    phone: '6560000000',
    contact_email: 'juan.perez@example.com',
    contact_email_confirm: 'juan.perez@example.com',
    ...over,
  };
  for (const [campo, valor] of Object.entries(datos)) {
    await page.fill(`[name="${campo}"]`, valor);
  }
  await page.locator('[name="program_id"]').selectOption(String(ctx.programId));
  return datos;
}

function esperarPost(page) {
  return page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ENROLL_URL
  );
}

test.describe('ventana abierta', () => {
  test.beforeAll(() => { setCohortStatus(ctx, 'open'); });

  test('muestra el formulario con la confirmación del correo, sin nombrar la convocatoria', async ({ page }) => {
    const res = await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    expect(res.status()).toBe(200);

    await expect(page.locator('main[data-tt-page="public_enroll"]')).toBeVisible();
    await expect(page.locator('[name="control_number"]')).toBeVisible();
    await expect(page.locator('[name="contact_email"]')).toBeVisible();
    await expect(page.locator('[name="contact_email_confirm"]')).toBeVisible();
    await expect(page.getByLabel('Confirma tu correo personal')).toBeVisible();
    await expect(page.locator('[name="phone"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enviar solicitud' })).toBeVisible();
    await expect(page.getByText('Servicios Escolares revisará tu solicitud')).toBeVisible();
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
    await llenarFormulario(page, { control_number: '123' });

    const post = esperarPost(page);
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    // htmx NO swappea en 4xx: un 400 dejaría la pantalla exactamente igual y
    // el usuario no sabría qué pasó (spec §6.1, riesgo 4).
    expect((await post).status()).toBe(200);

    await expect(page.locator('[data-tt-error="control_number"]')).toBeVisible();
    await expect(page.locator('[name="control_number"][aria-invalid="true"]')).toBeVisible();
    // El servidor conserva lo capturado al re-renderizar.
    await expect(page.locator('[name="first_name"]')).toHaveValue('Juan');
  });

  test('si los dos correos no coinciden, el error sale en la confirmación y no se escribe nada', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    const { control_number: control } = await llenarFormulario(page, {
      contact_email: 'juan.perez@example.com',
      contact_email_confirm: 'juan.peres@example.com',
    });

    const post = esperarPost(page);
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    expect((await post).status()).toBe(200);

    const error = page.locator('[data-tt-error="contact_email_confirm"]');
    await expect(error).toBeVisible();
    await expect(error).toHaveText('Los dos correos no coinciden.');
    await expect(page.locator('[name="contact_email_confirm"][aria-invalid="true"]')).toBeVisible();
    await expect(page.locator('[data-tt-notice]')).toHaveCount(0);
    expect(enrollmentRequestCountFor(control), 'un correo mal confirmado no escribe').toBe(0);
  });

  test('un alta válida dice «Recibimos tu solicitud» y queda en revisión, sin liga', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    const { control_number: control } = await llenarFormulario(page, {
      contact_email_confirm: 'JUAN.PEREZ@example.com',   // se compara sin mayúsculas
    });

    const post = esperarPost(page);
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    expect((await post).status()).toBe(200);

    const tarjeta = page.locator('[data-tt-notice="generic"]');
    await expect(tarjeta).toBeVisible();
    await expect(tarjeta).toContainText(TARJETA_TITULO);
    await expect(tarjeta).toContainText(TARJETA_CUERPO);
    expect(enrollmentRequestStateFor(control), 'la solicitud espera la revisión, sin liga')
      .toEqual({ status: 'pending_review', hasToken: false });
  });

  test('el honeypot lleno devuelve la tarjeta genérica y no escribe nada', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    // A propósito NO se elige carrera: `enroll_submit` exige `program_id` o
    // `program_text`, así que si el corto-circuito de la trampa desapareciera,
    // este envío caería en la validación normal y re-renderizaría el formulario
    // con `errors.program_id` — un parcial SIN `data-tt-notice`. Por eso la
    // aserción de abajo no es vacua.
    await page.fill('[name="control_number"]', '29990888');
    await page.fill('[name="first_name"]', 'Bot');
    await page.fill('[name="last_name"]', 'Automático');
    await page.fill('[name="phone"]', '6560000001');
    await page.fill('[name="contact_email"]', 'bot@example.com');
    await page.fill('[name="contact_email_confirm"]', 'bot@example.com');
    await page.locator('input[name="website"]').fill('http://spam.example', { force: true });

    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    // La MISMA tarjeta que ven el alta buena, la solicitud repetida y quien ya
    // tiene proceso (E8, ramas indistinguibles).
    const tarjeta = page.locator('[data-tt-notice="generic"]');
    await expect(tarjeta).toBeVisible();
    await expect(tarjeta).toContainText(TARJETA_TITULO);

    // Lo anterior prueba "se ve la tarjeta correcta"; NO prueba "no escribió
    // nada". Se lee directo de la base.
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

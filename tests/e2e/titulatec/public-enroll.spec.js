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
const { seedScenario, cleanupScenario, setCohortStatus, E2E_TAG } = require('./_helpers');

let ctx;

test.beforeAll(() => { ctx = seedScenario(); });
test.afterAll(() => { cleanupScenario(ctx); });

test.use({ storageState: { cookies: [], origins: [] } });

const ENROLL_URL = '/titulatec/inscripcion';
const TARJETA_TITULO = 'Recibimos tu solicitud';
const TARJETA_CUERPO = 'Servicios Escolares la revisará. Si se aprueba, te llegará un correo '
  + 'con tu acceso. Revisa también la carpeta de correo no deseado.';

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

// Matriz de viewports del proyecto (`docs/design/responsive.md`). No inventar otra.
const MATRIZ = [
  { w: 360, h: 740, perfil: 'movil chico' },
  { w: 390, h: 844, perfil: 'movil de referencia' },
  { w: 768, h: 1024, perfil: 'tablet vertical' },
  { w: 1280, h: 800, perfil: 'laptop' },
  { w: 1440, h: 900, perfil: 'escritorio comun' },
  { w: 1920, h: 1080, perfil: 'monitor grande' },
];

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
  // «¿Ya acreditaste el inglés?» es obligatoria y viene SIN marcar
  // (2026-09-17): sin elegir, el navegador no deja enviar. Por omisión «Sí».
  const { has_english: ingles = '1', ...resto } = over;
  await page.check(`[name="has_english"][value="${ingles}"]`);
  const datos = {
    control_number: controlNuevo(),
    first_name: 'Juan',
    last_name: 'Pérez',
    phone: '6560000000',
    contact_email: 'juan.perez@example.com',
    contact_email_confirm: 'juan.perez@example.com',
    ...resto,
  };
  for (const [campo, valor] of Object.entries(datos)) {
    await page.fill(`[name="${campo}"]`, valor);
  }
  await page.locator('[name="program_id"]').selectOption(String(ctx.programId));
  return datos;
}

/**
 * Apaga la validación NATIVA del formulario (`novalidate`) para el envío que
 * sigue.
 *
 * Por qué hace falta (2026-09-17): desde `ce057fd2` el formulario declara
 * `required` en «¿Ya acreditaste el inglés?» y `pattern="[A-Za-z]?[0-9]{8}"`
 * en el número de control. htmx NO dispara la petición si el formulario es
 * inválido, así que los dos tests que prueban las defensas del SERVIDOR
 * -rechazo con texto visible y corto-circuito de la trampa- se quedaban sin
 * POST que esperar y fallaban por la razón equivocada.
 *
 * Apagarla no debilita la prueba: la refleja. Un bot que llena la trampa hace
 * POST directo y no respeta ni `required` ni `pattern`, y la validación del
 * servidor existe precisamente para ese cliente. Lo que se ejerce aquí es esa
 * segunda línea, no la primera.
 */
async function sinValidacionNativa(page) {
  await page.evaluate(() => {
    document.getElementById('tt-enroll-form').setAttribute('novalidate', '');
  });
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

    // Control fuera de CONTROL_NUMBER_RE = ^[A-Za-z]?\d{8}$
    await llenarFormulario(page, { control_number: '123' });
    // Ese mismo formato lo exige ya el `pattern` del input, así que sin esto
    // htmx ni siquiera manda la petición y lo que se probaría es la validación
    // del NAVEGADOR, no la del servidor, que es la que este test cubre.
    await sinValidacionNativa(page);

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
    // A propósito tampoco se contesta «¿Ya acreditaste el inglés?», que es
    // `required`: un bot no contesta lo que no entiende. Sin apagar la
    // validación nativa el envío ni saldría, y el corto-circuito de la trampa
    // -que vive en el servidor- se quedaría sin ejercer.
    await sinValidacionNativa(page);

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

/* ===========================================================================
   Rediseño 2026-09-17: la tarjeta de cierre dice CUÁNDO abre, y las dos ramas
   de la pantalla (formulario y aviso) cumplen la matriz de seis viewports.

   Los dos bloques de abajo mueven la VENTANA de la convocatoria del escenario
   (`opens_at`/`closes_at`), no solo su `status` como hace `setCohortStatus`.
   Cada uno la restaura en su `afterAll` a lo que siembra `_helpers.js`
   (`opens_at = hoy - 1`, `closes_at = hoy + 30`), que es de lo que dependen
   todos los demás bloques de este archivo.
   =========================================================================== */

/** Fija la ventana de la convocatoria del escenario en días RELATIVOS a hoy.
 *  `null` escribe NULL (sin tope), que es como están las convocatorias viejas. */
function setCohortWindow(ctx, { abreEnDias, cierraEnDias, status = 'open' }) {
  const expr = (d) => (d === null ? 'None' : `date.today() + timedelta(days=${d})`);
  runInContainer(`
from datetime import date, timedelta
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text("UPDATE titulatec_cohorts SET status=:s, opens_at=:o, closes_at=:c WHERE id=:id"),
               {"s": "${status}", "o": ${expr(abreEnDias)}, "c": ${expr(cierraEnDias)},
                "id": ${ctx.cohortId}})
    db.commit()
finally:
    db.close()
`);
}

test.describe('ventana cerrada: dice cuándo abre', () => {
  // `status='open'` con `opens_at` en el futuro es el caso REAL del 2026-09-17:
  // `is_public_enrollment_open` la considera cerrada -y hace bien- pero la
  // fecha ya está decidida. Antes la página mandaba a «consultar las fechas».
  test.beforeAll(() => { setCohortWindow(ctx, { abreEnDias: 11, cierraEnDias: 20 }); });
  test.afterAll(() => { setCohortWindow(ctx, { abreEnDias: -1, cierraEnDias: 30 }); });

  test('muestra la fecha de apertura, la cuenta regresiva y el cierre', async ({ page }) => {
    const res = await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
    expect(res.status()).toBe(200);

    const tarjeta = page.locator('[data-tt-notice="closed"]');
    await expect(tarjeta).toBeVisible();
    await expect(page.locator('[name="control_number"]')).toHaveCount(0);

    // La fecha viaja también legible por máquina, no solo formateada.
    const fecha = tarjeta.locator('time.tt-enroll-closed-date');
    await expect(fecha).toBeVisible();
    const iso = await fecha.getAttribute('datetime');
    const esperado = new Date(Date.now() + 11 * 864e5).toISOString().slice(0, 10);
    expect(iso, 'el <time> no lleva la fecha de apertura en ISO').toBe(esperado);

    await expect(tarjeta).toContainText('Faltan 11 días');
    await expect(tarjeta).toContainText('Abre de nuevo el');
    await expect(tarjeta, 'no dice hasta cuándo se podrá enviar').toContainText('para enviar tu solicitud');
    // El nombre de la convocatoria NUNCA sale a la vista pública.
    await expect(tarjeta).not.toContainText(E2E_TAG);
  });

  test('no desborda en los seis viewports de la matriz', async ({ page }) => {
    for (const { w, h } of MATRIZ) {
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

test.describe('ventana cerrada SIN fecha decidida', () => {
  // Sin ninguna convocatoria `open` con `opens_at` futuro no hay nada que
  // prometer, y la tarjeta cae al texto de siempre. Es el caso que protege de
  // inventarle una fecha al egresado.
  test.beforeAll(() => {
    setCohortWindow(ctx, { abreEnDias: null, cierraEnDias: null, status: 'closed' });
  });
  test.afterAll(() => { setCohortWindow(ctx, { abreEnDias: -1, cierraEnDias: 30 }); });

  test('no inventa fecha: manda con Servicios Escolares', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    const tarjeta = page.locator('[data-tt-notice="closed"]');
    await expect(tarjeta).toBeVisible();
    await expect(tarjeta).toContainText('Consulta las fechas con Servicios Escolares');
    await expect(tarjeta.locator('time.tt-enroll-closed-date')).toHaveCount(0);
  });
});

test.describe('formulario: layout y objetivos táctiles', () => {
  test.beforeAll(() => { setCohortStatus(ctx, 'open'); });

  test('no desborda en los seis viewports de la matriz', async ({ page }) => {
    for (const { w, h } of MATRIZ) {
      await page.setViewportSize({ width: w, height: h });
      await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('#tt-enroll-form')).toBeVisible();
      const m = await page.evaluate(() => ({
        s: document.documentElement.scrollWidth, i: window.innerWidth,
      }));
      expect(m.s, `desborde a ${w}px: ${m.s} > ${m.i}`).toBeLessThanOrEqual(m.i);
    }
  });

  test('a 390 todo control mide 44 px y el campo va a 16 px', async ({ page }) => {
    // 16 px NO es cosmético: por debajo, iOS hace zoom al enfocar y deja la
    // página desplazada. 44 px es el objetivo táctil del contrato responsive.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    const medidas = await page.evaluate(() => {
      const vis = [...document.querySelectorAll('.tt-opt, .tt-field, .tt-enroll-submit')]
        .filter((e) => e.getBoundingClientRect().height > 0);
      return {
        n: vis.length,
        minAlto: Math.min(...vis.map((e) => Math.round(e.getBoundingClientRect().height))),
        fsCampo: parseFloat(getComputedStyle(document.querySelector('.tt-field')).fontSize),
      };
    });
    expect(medidas.n, 'no se midió ningún control').toBeGreaterThan(8);
    expect(medidas.minAlto, 'hay un control por debajo de 44 px').toBeGreaterThanOrEqual(44);
    expect(medidas.fsCampo, 'el campo bajó de 16 px: iOS hará zoom').toBeGreaterThanOrEqual(16);
  });

  test('a 1440 el panel de contexto va al lado y el formulario no queda angosto', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    const cajas = await page.evaluate(() => {
      const r = (sel) => {
        const e = document.querySelector(sel);
        const b = e.getBoundingClientRect();
        return { x: Math.round(b.x), w: Math.round(b.width), bottom: Math.round(b.bottom) };
      };
      return { aside: r('.tt-enroll-aside'), form: r('#tt-enroll-form') };
    });
    // Dos columnas: el panel termina antes de que empiece el formulario.
    expect(cajas.aside.x + cajas.aside.w,
      'el panel no está a la izquierda del formulario').toBeLessThanOrEqual(cajas.form.x);
    // Y el formulario dejó de ser la columna angosta de 60ch (~636 px con el
    // panel al lado sería estrechar, no ensanchar): al menos 560 px útiles.
    expect(cajas.form.w, 'el formulario sigue angosto en escritorio').toBeGreaterThanOrEqual(560);
  });

  test('el panel no nombra la convocatoria y sí dice cuándo cierra', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    const aside = page.locator('.tt-enroll-aside');
    await expect(aside).toBeVisible();
    await expect(aside).toContainText('Cierra el');
    await expect(aside).toContainText('Ten a la mano');
    await expect(aside).not.toContainText(E2E_TAG);
  });

  // 2026-09-21: convertido -ya no existe "mi carrera no aparece" que probar-,
  // no borrado. El caso de raíz se eliminó: esa opción dejaba la solicitud sin
  // `program_id`, invisible para todo encargado de carrera (el alcance filtra
  // por `program_id`, ver `docs/flows/engine_officer_scope.md`). Lo que este
  // test prueba ahora es justo lo que un navegador real puede probar y pytest
  // no -la API de constraint validation del DOM-, así que no es redundante con
  // `test_enrollment_public.py`: ese archivo cubre la validación del SERVIDOR
  // (sin carrera, `__other__` por POST directo, id inventado), no si el
  // NAVEGADOR bloquea el envío antes de llegar a htmx.
  test('carrera obligatoria: ya no hay "mi carrera no aparece", y sin elegirla el navegador bloquea el envío', async ({ page }) => {
    await page.goto(ENROLL_URL, { waitUntil: 'domcontentloaded' });

    await expect(page.locator('option[value="__other__"]')).toHaveCount(0);
    await expect(page.locator('[data-tt-enroll="program-text-wrap"]')).toHaveCount(0);
    await expect(page.locator('[name="program_text"]')).toHaveCount(0);
    await expect(page.getByText(
      'De no encontrar tu carrera exacta, elige la que más se apegue a la que cursaste.'
    )).toBeVisible();

    const select = page.locator('#tt-program');
    await expect(select).toHaveAttribute('required', '');

    // Capa 1: el navegador. Se llena TODO -incluida una carrera válida, vía
    // `llenarFormulario`- y luego se deja el <select> sin elegir a propósito:
    // htmx no manda nada si el formulario es inválido (por eso el resto de
    // este archivo APAGA la validación nativa para poder probar la del
    // servidor, ver `sinValidacionNativa` arriba). No se espera una petición
    // con un plazo -nunca se prueba un negativo con un timeout-: se lee
    // directo la API de constraint validation, que es determinista.
    await llenarFormulario(page);
    await select.selectOption('');
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    expect(await select.evaluate((el) => el.validity.valueMissing),
      'el navegador debió marcar el <select> como inválido').toBe(true);
    await expect(page.locator('[data-tt-notice]'),
      'con el envío bloqueado por el navegador no debe aparecer ninguna tarjeta').toHaveCount(0);

    // Capa 2: el servidor, que es el contrato de verdad -el `required` del
    // HTML no protege nada ante un POST directo-.
    await sinValidacionNativa(page);
    const post = esperarPost(page);
    await page.getByRole('button', { name: 'Enviar solicitud' }).click();
    expect((await post).status()).toBe(200);
    await expect(page.locator('[data-tt-error="program_id"]')).toBeVisible();
    await expect(page.locator('[name="program_id"][aria-invalid="true"]')).toBeVisible();
    await expect(page.getByText('Elige tu carrera de la lista.')).toBeVisible();
  });
});

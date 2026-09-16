// @ts-check
/**
 * Auto-agendado de la cita de cotejo — el PRIMER E2E de citas de esta app.
 * (spec `2026-09-15-titulatec-autoagenda-cotejo` §10, Tarea 8.)
 *
 * Hasta hoy `tests/e2e/titulatec/` tenía specs de encuesta y de liberaciones,
 * pero NINGUNA abría `/titulatec/admin/appointments` ni `/titulatec/student/cita`.
 * Todo el auto-agendado estaba cubierto solo por `pytest`, que no atraviesa el
 * navegador: no ve el swap de htmx, no ve si el distintivo del tablero se pinta,
 * y no ve si la rejilla de franjas desborda la pantalla del egresado.
 *
 * EL RECORRIDO, en el orden en que se declara (los tests de este archivo
 * comparten escenario y corren EN ORDEN — `fullyParallel: false`, `workers: 1`):
 *
 *   1. El encargado publica un espacio como «Agendable» desde su editor.
 *   2. La vista de agendado del egresado no desborda en los 6 viewports.
 *   3. El egresado ve ese espacio y agenda una franja.
 *   4. El encargado ve «El alumno agendó» en el asiento de su tablero (D11:
 *      no hay notificación ni correo, así que ese distintivo ES el aviso).
 *
 * POR QUÉ EL PASO 2 VA ANTES DEL 3 Y NO DESPUÉS.
 * El invariante responsive se mide sobre «la vista nueva del alumno», que es la
 * rejilla de franjas (cara 2 de §7). En cuanto agenda, `eligibility` devuelve
 * `tiene_cita`, `can_book` pasa a falso y esa rejilla **deja de existir** — el
 * panel se queda con la tarjeta de la cita. Medida después del paso 3, la
 * aserción seguiría en verde midiendo una pantalla que ya no es la que dice
 * medir: verde y vacía, el peor resultado posible.
 *
 * LO QUE ESTE ARCHIVO NO PRUEBA, y dónde sí está cubierto:
 * las reglas de elegibilidad (§3), las ventanas de tiempo de D8, el tope de D9 y
 * el IDOR del `window_id` viven en `tests/fastapi/titulatec/`
 * (`test_self_booking_eligibility.py`, `test_self_booking_routes.py`,
 * `test_self_booking_offer.py`). Repetirlas en un navegador las haría más lentas
 * y más frágiles sin cubrir un solo camino nuevo. Aquí solo va lo que únicamente
 * el navegador puede desmentir.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState: undefined`
 * (ver el encabezado de `_helpers.js`): en Playwright 1.61 un `undefined` es un
 * no-op y el contexto heredaría la cookie del admin de HELPDESK del
 * `global-setup`, que en TitulaTec no abre nada — `require_page_app` no tiene
 * bypass de admin global.
 */
const { test, expect } = require('@playwright/test');
const {
  seedScenario, cleanupScenario, stateFor, seedSurveyReview, seedReviewDay,
  setStudentPhase,
} = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

const CITAS_URL = '/titulatec/admin/appointments';
const CITA_ALUMNO_URL = '/titulatec/student/cita';

// La fase de la cita de cotejo. El escenario nace en la 1 y la guarda del
// alumno mira `current_phase`, así que sin moverlo `GET /student/cita` es un 302.
const FASE_COTEJO = 2;

// MAÑANA, no hoy: la franja tiene que caer a más de
// `TITULATEC_SELF_BOOK_MIN_LEAD_MINUTES` (60 min) de `db_now()` para que la
// oferta la incluya, y cancelarla exige más de 2 h de margen (D8). Con el día de
// hoy, este archivo pasaría o fallaría según la hora a la que se corriera —el
// peor tipo de test intermitente—: a las 08:30 la franja de las 09:00 no se
// ofrece, y a las 10:00 ya pasó.
const MANANA = new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 10);

const ESPACIO = { inicio: '09:00', fin: '11:00', minutos: '30', cupo: '1',
                  lugar: 'Edificio A · E2E' };

// La misma matriz que el resto del proyecto (`docs/design/responsive.md`).
// No inventar otra.
const MATRIZ = [
  { w: 360, h: 740, perfil: 'móvil chico' },
  { w: 390, h: 844, perfil: 'móvil de referencia' },
  { w: 768, h: 1024, perfil: 'tablet vertical' },
  { w: 1280, h: 800, perfil: 'laptop' },
  { w: 1440, h: 900, perfil: 'escritorio común' },
  { w: 1920, h: 1080, perfil: 'monitor grande' },
];

let ctx;

test.beforeAll(() => {
  ctx = seedScenario();
  // Regla 3 de §3: sin `SurveyReview` el egresado no pasa de «Primero envía la
  // encuesta de egresados», y `AppointmentService.create` lo rechazaría de todos
  // modos con `SurveyNotSubmitted` (guarda dura, aplica también al encargado).
  // Se siembra en vez de recorrer el asistente de la encuesta en el navegador:
  // ese mecanismo ya lo cubre `public-survey.spec.js`.
  seedSurveyReview(ctx);
  setStudentPhase(ctx, FASE_COTEJO);
  seedReviewDay(ctx, MANANA);
});

test.afterAll(() => { cleanupScenario(ctx); });

/** Espera la respuesta de un POST a `ruta` (patrón de `admin-releases.spec.js`). */
function esperarPost(page, ruta) {
  return page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ruta
  );
}

test('el encargado publica un espacio como «Agendable»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('officer') });
  const page = await c.newPage();

  // Directo a la sub-vista Espacios del día sembrado. El `?date=` explícito
  // evita depender de `_default_day`, que elige «dónde está el trabajo» y podría
  // aterrizar en otro día de la convocatoria.
  await page.goto(`${CITAS_URL}?v=espacios&date=${MANANA}`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#appt-spaces')).toBeVisible();

  // Parte de CERO: si el escenario dejara un espacio colgando, el resto del
  // archivo estaría midiendo datos de otra corrida.
  await expect(page.locator('#appt-space-list')).toContainText('Todavía no abres espacios');

  await page.getByRole('link', { name: 'Abrir un espacio' }).click();
  const editor = page.locator('#appt-space-editor');
  await expect(editor.locator('#esp-start')).toBeVisible();

  await editor.locator('#esp-start').fill(ESPACIO.inicio);
  await editor.locator('#esp-end').fill(ESPACIO.fin);
  await editor.locator('#esp-slot').selectOption(ESPACIO.minutos);
  await editor.locator('#esp-cap').fill(ESPACIO.cupo);
  await editor.locator('#esp-loc').fill(ESPACIO.lugar);

  // Todo espacio NACE privado (D1: publicar es un acto deliberado), así que
  // este check es el acto que esta prueba existe para ejercer. Se verifica el
  // estado previo: si el default dejara de ser `private`, el resto del recorrido
  // pasaría sin que nadie hubiera publicado nada.
  await expect(editor.locator('#esp-vis-private')).toBeChecked();
  await editor.locator('#esp-vis-bookable').check();

  const post = esperarPost(page, `${CITAS_URL}/espacios/nuevo`);
  await editor.getByRole('button', { name: 'Guardar espacio' }).click();
  expect((await post).status()).toBe(200);

  // El espacio queda en la lista CON su pastilla de modo: sin ella el encargado
  // no puede distinguir de un vistazo lo publicado de lo privado, que es justo
  // la decisión que quiere poder revisar.
  const lista = page.locator('#appt-space-list');
  await expect(lista).toContainText('Agendable');
  await expect(lista).toContainText(ESPACIO.inicio);
  await expect(lista).toContainText(ESPACIO.lugar);

  // El encargado del escenario SÍ tiene carreras (`ProgramPosition` hacia el
  // `programId`), así que NO debe salir el aviso de «ningún egresado lo verá»
  // (Ruling 14). Es la contraprueba de que el alcance quedó bien sembrado: sin
  // él, el paso 3 fallaría más tarde y por un motivo mucho menos legible.
  await expect(lista).not.toContainText('ningún egresado los verá');

  await c.close();
});

test('la vista de agendado del egresado no desborda en los 6 viewports', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();

  for (const { w, h, perfil } of MATRIZ) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(CITA_ALUMNO_URL, { waitUntil: 'domcontentloaded' });

    // Que de verdad estemos midiendo la rejilla de franjas y no un estado
    // vacío: la tira de días y al menos un botón de franja tienen que estar.
    // La rejilla es el riesgo obvio de desborde (spec §7) — medir la pantalla
    // sin ella sería medir otra cosa.
    await expect(page.locator('#tt-cita-agendar')).toBeVisible();
    await expect(page.locator('#tt-cita-agendar .tt-daychip').first()).toBeVisible();
    await expect(page.locator('#tt-cita-agendar button.tt-slot').first()).toBeVisible();

    const medida = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(
      medida.scrollWidth,
      `desborde horizontal a ${w}px (${perfil}): scrollWidth ${medida.scrollWidth} ` +
        `> innerWidth ${medida.innerWidth}. La tira de días y la rejilla de franjas ` +
        'scrollean DENTRO de su contenedor; el body nunca.'
    ).toBeLessThanOrEqual(medida.innerWidth);
  }

  await c.close();
});

test('el egresado ve el espacio publicado y agenda su cita', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  await page.goto(CITA_ALUMNO_URL, { waitUntil: 'domcontentloaded' });

  // Antes de agendar: sin cita, y con la oferta del encargado a la vista.
  await expect(page.locator('#tt-cita-card')).toContainText('Pendiente de agenda');
  const agendar = page.locator('#tt-cita-agendar');
  await expect(agendar).toBeVisible();
  await expect(agendar).toContainText(ESPACIO.lugar);

  // Una franja es un `<button type="submit" name="slot">`: NO se teclea una
  // hora (D2 del rediseño de 2026-09-03 sigue mandando). Se localiza por su
  // `aria-label` («Agendar el <día> a las 09:00 con <encargado>»), que es lo
  // que de verdad lee quien navega con lector de pantalla.
  const post = esperarPost(page, '/titulatec/student/cita/agendar');
  await agendar.getByRole('button', { name: new RegExp(`a las ${ESPACIO.inicio}`) }).click();
  expect((await post).status()).toBe(200);

  // El POST responde con el PANEL re-renderizado (app pages-only: un POST
  // devuelve el parcial, no JSON).
  const tarjeta = page.locator('#tt-cita-card');
  await expect(tarjeta).toContainText('Tu cita de cotejo');
  await expect(tarjeta).toContainText(ESPACIO.inicio);
  await expect(tarjeta).toContainText(ESPACIO.lugar);

  // D4: con cita vigente ya no puede abrir otra, así que la rejilla desaparece
  // — y §7 prohíbe dejar en su lugar un botón deshabilitado y mudo.
  await expect(page.locator('#tt-cita-agendar')).toHaveCount(0);

  // D8: faltan más de 2 h (la cita es mañana), así que el botón de cancelar sí
  // se ofrece. Lo decide `can_self_cancel`, el MISMO predicado que aplicará el
  // servidor: si divergieran, aquí habría un botón que la ruta va a rechazar.
  await expect(tarjeta.getByRole('button', { name: 'Cancelar mi cita' })).toBeVisible();

  await c.close();
});

test('el encargado ve el distintivo «El alumno agendó» en su tablero', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('officer') });
  const page = await c.newPage();

  // Sub-vista Agenda (la de por omisión) en el día del espacio: ahí vive el
  // tablero de franjas con sus asientos.
  await page.goto(`${CITAS_URL}?date=${MANANA}`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#appt-agenda')).toBeVisible();

  // D11: el encargado NO recibe notificación ni correo de un auto-agendado. Se
  // entera por su tablero, y solo por esto.
  const asiento = page.locator(`#appt-seat-p${ctx.processId}`);
  await expect(asiento).toBeVisible();
  await expect(asiento).toContainText('El alumno agendó');
  await expect(asiento).toContainText(ctx.studentControl);

  await c.close();
});

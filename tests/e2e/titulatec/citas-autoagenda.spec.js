// @ts-check
/**
 * Auto-agendado de la cita de cotejo — el PRIMER E2E de citas de esta app.
 * (spec `2026-09-15-titulatec-autoagenda-cotejo` §10, Tarea 8; ampliado por
 * `2026-09-29-titulatec-cotejo-espacios` §6/§8, Tarea 10, con la encuesta
 * LIBERADA — D1, revierte D2 del 2026-09-15 —, el recorrido «sin horario»
 * —D3-D8— y la vista plegable del alumno con varios encargados —D10—.)
 *
 * Hasta el 2026-09-15 `tests/e2e/titulatec/` tenía specs de encuesta y de
 * liberaciones, pero NINGUNA abría `/titulatec/admin/appointments` ni
 * `/titulatec/student/cita`. Todo el auto-agendado estaba cubierto solo por
 * `pytest`, que no atraviesa el navegador: no ve el swap de htmx, no ve si el
 * distintivo del tablero se pinta, y no ve si la rejilla de franjas o los
 * `<details>` plegables desbordan la pantalla del egresado.
 *
 * EL RECORRIDO, en el orden en que se declara (los tests de este archivo
 * comparten escenario y corren EN ORDEN — `fullyParallel: false`, `workers: 1`):
 *
 *   1. El encargado publica un espacio como «Agendable» desde su editor.
 *   2. La vista de agendado del egresado (día con 3 encargados y 20 franjas)
 *      no desborda en los 6 viewports, y sus plegables (D10) están en su
 *      lugar: solo el primer encargado abierto, «Ver N horas más» presente.
 *   3. El egresado aparta lugar en el espacio SIN HORARIO de hoy (D3/D4).
 *   4. El encargado lo ve numerado en el bloque «Sin horario» de su tablero,
 *      con «El alumno apartó» (D11: mismo distintivo que un auto-agendado).
 *   5. El encargado usa «Atender ahora» (D7) sobre OTRO proceso pendiente —no
 *      el que acaba de apartar lugar, que ya tiene cita viva— y su ficha pasa
 *      a «En proceso» sin que nadie pasara por «Apartarle lugar».
 *
 * POR QUÉ EL PASO 2 VA ANTES DE APARTAR/AGENDAR Y NO DESPUÉS.
 * El invariante responsive se mide sobre «la vista nueva del alumno», que es la
 * rejilla de franjas (cara 2 de §7). En cuanto el egresado tiene una cita viva
 * (franja O sin horario, D3/D4), `eligibility` devuelve `tiene_cita`, `can_book`
 * pasa a falso y esa rejilla **deja de existir** — el panel se queda con la
 * tarjeta de la cita. Medida después de apartar, la aserción seguiría en verde
 * midiendo una pantalla que ya no es la que dice medir: verde y vacía, el peor
 * resultado posible.
 *
 * Y es la razón de que el paso 2 pida `?dia=` MAÑANA explícito en vez de
 * confiar en el día por omisión: con el espacio sin horario de HOY ya
 * sembrado (para el paso 3), HOY ordena ANTES que MAÑANA —`_agenda_ctx`
 * recorre los días de la oferta en orden cronológico— y sería el día que
 * abriría sin pedirlo, con un solo encargado y una sola franja: justo lo
 * opuesto de lo que este paso necesita medir.
 *
 * POR QUÉ EL PASO 3 APARTA EN VEZ DE AGENDAR UNA FRANJA.
 * Un proceso tiene como mucho UNA cita viva (`titulatec_review_appointments`,
 * índice único parcial sobre `is_current`). El egresado de este archivo no
 * puede agendar una franja en MAÑANA Y apartar un lugar sin horario en HOY: la
 * primera reserva apaga `can_book` para la segunda. Esta Tarea (10) es
 * específicamente sobre el recorrido «sin horario», así que es ese el que se
 * ejerce con el actor principal; el mecanismo de franjas en sí —agendar
 * clicando una hora— no cambió en esta spec (más allá de la guarda de
 * encuesta liberada, que el paso 3 ejerce igual: si la encuesta no estuviera
 * liberada, apartar respondería 400 igual que agendar) y sigue íntegro donde
 * ya se probó.
 *
 * LO QUE ESTE ARCHIVO NO PRUEBA, y dónde sí está cubierto:
 * las reglas de elegibilidad (§3), las ventanas de tiempo de D8, el tope de D9,
 * el IDOR del `window_id`, `WindowModeConflict`/`WindowShrinkConflict` del
 * editor y el candado de `add_places` viven en `tests/fastapi/titulatec/`
 * (`test_self_booking_eligibility.py`, `test_self_booking_routes.py`,
 * `test_self_booking_offer.py`, `test_window_visibility.py`,
 * `test_review_window_service.py`). Repetirlas en un navegador las haría más
 * lentas y más frágiles sin cubrir un solo camino nuevo. Aquí solo va lo que
 * únicamente el navegador puede desmentir.
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
  setStudentPhase, tomorrowInContainer, todayInContainer, seedWalkinWindow,
  seedExtraOfficerWindow, seedSecondPendingProcess,
} = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

// Los 5 tests son UN recorrido encadenado sobre el MISMO escenario: el 3
// aparta lugar en el espacio sin horario que ya trae sembrado, el 4 mira la
// fila que crea el 3, y el 5 sienta a un SEGUNDO proceso en ese mismo espacio
// (el 3 ya lo dejó ocupado en 1 lugar). Eso hoy se cumple por el
// `fullyParallel: false` + `workers: 1` del config GLOBAL, que es de otro
// archivo y no sabe de esta dependencia — el día que alguien lo paralelice,
// los tests 2-5 revientan de forma ilegible en vez de saltarse. `mode:
// 'serial'` lo fija AQUÍ y además aborta la cadena al primer fallo, que es lo
// correcto para un recorrido: si nadie publicó el espacio, «el egresado
// agenda» no es un fallo nuevo, es ruido.
test.describe.configure({ mode: 'serial' });

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
//
// Y se deriva del reloj del CONTENEDOR (`tomorrowInContainer`), no del runner:
// quien decide qué días entran en la oferta es `db_now()`, hora local del
// contenedor. Con `new Date()` del host, una zona horaria distinta —o arrancar
// unos minutos antes de medianoche— hace que «mañana» no sea el mismo día para
// los dos, y el día sembrado deja de ser el día ofrecido. Se asigna en
// `beforeAll` porque leerlo exige un `docker exec`.
let MANANA;

// HOY, con el mismo reloj de CONTENEDOR (`todayInContainer`): el espacio SIN
// HORARIO tiene que fechar hoy porque D7 («Atender ahora») exige día ==
// `db_now().date()` del encargado — no cualquier día futuro sirve para ese
// paso del recorrido.
let HOY;

// El «otro pendiente» del paso 5 (D7): un SEGUNDO proceso, sin cita viva, que
// «Atender ahora» sienta directo. Se siembra en `beforeAll` (`docker exec`),
// así que su id no se conoce hasta entonces.
let PROCESS_ID_2;

// De 09:00 a 19:00 en franjas de 30 min = 20 franjas (Tarea 10: «≥20 franjas»
// de la vista plegable del alumno, spec §6/D10 — 12 visibles + «Ver 8 horas
// más»). El inicio se mantiene a las 09:00: el paso 1 (publicado) sigue
// verificando esa hora en la lista de espacios del encargado.
const ESPACIO = { inicio: '09:00', fin: '19:00', minutos: '30', cupo: '1',
                  lugar: 'Edificio A · E2E' };

// Los dos encargados EXTRA de la vista plegable (Tarea 10: «≥3 encargados»,
// spec §6/D10), sembrados directo en BD — el editor del navegador ya lo
// ejerce el paso 1 publicando `ESPACIO`, así que repetirlo dos veces más no
// cubre un camino nuevo. Horarios propios, sin solapar `ESPACIO.inicio`, para
// que ningún día quede con dos encargados en la misma hora.
const ENCARGADO_B = { start: '13:00', end: '13:30' };
const ENCARGADO_C = { start: '15:00', end: '15:30' };

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
  // Primero el reloj del contenedor: todo lo que sigue (los días sembrados y
  // las URLs de los tests) cuelga de estas dos fechas.
  MANANA = tomorrowInContainer();
  HOY = todayInContainer();
  ctx = seedScenario();
  // Regla 3 de §3 (D1, spec 2026-09-29-titulatec-cotejo-espacios-design.md §2
  // — revierte D2 del 2026-09-15): sin `SurveyReview` el egresado no pasa de
  // «Primero envía la encuesta de egresados», y con una `in_review` (lo que
  // sembraba este archivo hasta la Tarea 10) `AppointmentService.create` la
  // rechazaría igual con `SurveyNotReleased` — GTV tiene que haberla LIBERADO,
  // no solo recibida. Se siembra ya `approved` en vez de recorrer el asistente
  // de la encuesta y la bandeja de GTV en el navegador: esos mecanismos ya los
  // cubren `public-survey.spec.js` y `admin-releases.spec.js`.
  seedSurveyReview(ctx, { status: 'approved' });
  setStudentPhase(ctx, FASE_COTEJO);
  seedReviewDay(ctx, MANANA);
  seedReviewDay(ctx, HOY);

  // Vista plegable del alumno (Tarea 10, spec §6/D10): dos encargados MÁS en
  // MAÑANA para llegar a 3 ese día — el que publica el paso 1 vía navegador
  // más estos dos sembrados —, así que `_agenda_ctx` abre solo el primero y
  // pliega los otros dos.
  seedExtraOfficerWindow(ctx, { suffix: 'b', lastName: 'ENCARGADO DOS',
                                dayIso: MANANA, ...ENCARGADO_B });
  seedExtraOfficerWindow(ctx, { suffix: 'c', lastName: 'ENCARGADO TRES',
                                dayIso: MANANA, ...ENCARGADO_C });

  // Recorrido «sin horario» (Tarea 10, spec §3/§4): el espacio SIN HORARIO de
  // HOY del encargado principal, con cupo para el que aparta lugar (paso 3) Y
  // el que «Atender ahora» sienta después (paso 5).
  seedWalkinWindow(ctx, { dayIso: HOY });

  // El «otro pendiente» del paso 5 (D7: «Atender ahora» exige un proceso SIN
  // cita viva; el egresado principal deja de calificar en cuanto aparta lugar
  // en el paso 3).
  PROCESS_ID_2 = seedSecondPendingProcess(ctx);
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
    // `?dia=` MAÑANA explícito: ver «POR QUÉ EL PASO 2…» en la cabecera del
    // archivo — con HOY ya sembrado (el espacio sin horario del paso 3) y
    // ordenando antes que MAÑANA, el día por omisión ya no sirve para medir
    // el escenario cargado (3 encargados, 20 franjas) que este test necesita.
    await page.goto(`${CITA_ALUMNO_URL}?dia=${MANANA}`, { waitUntil: 'domcontentloaded' });

    // Que de verdad estemos midiendo la rejilla de franjas y no un estado
    // vacío: la tira de días y al menos un botón de franja tienen que estar.
    // La rejilla es el riesgo obvio de desborde (spec §7) — medir la pantalla
    // sin ella sería medir otra cosa.
    const agendar = page.locator('#tt-cita-agendar');
    await expect(agendar).toBeVisible();
    await expect(agendar.locator('.tt-daychip').first()).toBeVisible();
    await expect(agendar.locator('button.tt-slot').first()).toBeVisible();

    // D10 (Tarea 10, spec §6): encargados PLEGABLES. El día trae 3 —el que
    // publica el paso 1 más los dos sembrados en `beforeAll`— así que
    // `_agenda_ctx` pliega TODOS salvo el primero (`pocos = len(duenos) <= 2`
    // es falso con 3; con ≤2 los dos irían abiertos y esto no probaría nada).
    // Los tres siguen en el DOM como `<details>` nativo, cero JS: por eso
    // `toHaveCount` no necesita que estén abiertos para contarlos.
    await expect(agendar.locator('details.tt-slotblock')).toHaveCount(3);
    await expect(agendar.locator('details.tt-slotblock[open]')).toHaveCount(1);

    // D10: «Ver N horas más». Con 20 franjas en la ventana del paso 1 (12
    // visibles + 8 de más) es el único de los tres encargados que la ofrece:
    // los otros dos publican una sola franja cada uno y no llegan al corte.
    const verMas = agendar.locator('.tt-cita-more-sum');
    await expect(verMas).toHaveCount(1);
    await expect(verMas).toContainText('Ver 8 horas más');

    const medida = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(
      medida.scrollWidth,
      `desborde horizontal a ${w}px (${perfil}): scrollWidth ${medida.scrollWidth} ` +
        `> innerWidth ${medida.innerWidth}. La tira de días, los encargados ` +
        'plegables y la rejilla de franjas scrollean DENTRO de su contenedor; ' +
        'el body nunca.'
    ).toBeLessThanOrEqual(medida.innerWidth);
  }

  await c.close();
});

test('el egresado aparta lugar en el espacio sin horario', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  // `?dia=` HOY explícito, por la misma razón que el test anterior fija
  // MAÑANA: con los dos días sembrados no hay que confiar en cuál abre por
  // omisión — este test necesita justo el día del espacio sin horario.
  await page.goto(`${CITA_ALUMNO_URL}?dia=${HOY}`, { waitUntil: 'domcontentloaded' });

  // Antes de apartar: sin cita, y con el espacio sin horario del encargado a
  // la vista. Misma tarjeta «Te toca agendar» que un espacio con franjas: D3
  // hace que un `walkin` YA sea agendable, así que no hay una copia aparte de
  // «solo atención sin cita».
  const tarjeta = page.locator('#tt-cita-card');
  await expect(tarjeta).toContainText('Te toca agendar');
  const agendar = page.locator('#tt-cita-agendar');
  await expect(agendar).toBeVisible();
  await expect(agendar).toContainText('Módulo sin horario · E2E');

  // Sin horario (D3/D4): NO hay franjas que elegir —`w.kind == 'sin_horario'`—,
  // así que el botón es «Apartar mi lugar» y no un `button.tt-slot` con hora;
  // el `<form>` solo manda `window_id`, la ruta usa la apertura del espacio.
  const post = esperarPost(page, '/titulatec/student/cita/agendar');
  await agendar.getByRole('button', { name: 'Apartar mi lugar' }).click();
  expect((await post).status()).toBe(200);

  // El POST responde con el PANEL re-renderizado, igual que agendar una
  // franja. «por orden de llegada» es la copia PROPIA de `cita_card.html` en
  // sin horario (D11: `AppointmentService.when` no la trae) — su presencia
  // prueba que la cita quedó como WALKIN y no como una franja convencional.
  await expect(tarjeta).toContainText('Tu cita de cotejo');
  await expect(tarjeta).toContainText('por orden de llegada');
  await expect(tarjeta).toContainText('Módulo sin horario · E2E');

  // D4: con cita vigente ya no puede abrir otra, así que la rejilla desaparece
  // — y §7 prohíbe dejar en su lugar un botón deshabilitado y mudo.
  await expect(page.locator('#tt-cita-agendar')).toHaveCount(0);

  // D5: en sin horario «Cancelar mi lugar» sustituye a «Cancelar mi cita»
  // (mismo botón y `hx-confirm`, texto distinto — `cita_card.html`). El
  // espacio cierra a las 23:55 de HOY, así que sobran más de las 2 h que
  // exige `can_self_cancel`.
  await expect(tarjeta.getByRole('button', { name: 'Cancelar mi lugar' })).toBeVisible();

  await c.close();
});

test('el encargado ve el lugar apartado numerado en su bloque «Sin horario»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('officer') });
  const page = await c.newPage();

  // Sub-vista Agenda (la de por omisión) en el día del espacio sin horario:
  // ahí vive el tablero con su bloque «Sin horario» y la lista numerada.
  await page.goto(`${CITAS_URL}?date=${HOY}`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#appt-agenda')).toBeVisible();

  const bloque = page.locator('section[aria-label^="Espacio sin horario"]');
  await expect(bloque).toBeVisible();
  await expect(bloque).toContainText('1/5'); // 1 ocupado de 5 lugares

  // D11: el encargado NO recibe notificación ni correo de un lugar apartado.
  // Se entera por su tablero -«El alumno apartó»-, igual que con una franja
  // auto-agendada («El alumno agendó»). `o.n` es el orden de apartado (D8):
  // el PRIMERO en apartar es el «1» de la lista.
  const fila = page.locator(`#appt-walkin-row-p${ctx.processId}`);
  await expect(fila).toBeVisible();
  await expect(fila.locator('.n')).toHaveText('1');
  await expect(fila).toContainText('El alumno apartó');
  await expect(fila).toContainText(ctx.studentControl);

  await c.close();
});

test('«Atender ahora» sienta a otro pendiente y su ficha pasa a «En proceso»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('officer') });
  const page = await c.newPage();

  // Ficha del SEGUNDO proceso directamente -«por agendar», sin cita viva-, en
  // el día del espacio sin horario: ahí es donde `_detail_ctx` ofrece
  // `walkins_hoy` (D7: solo espacios sin horario de HOY, del propio
  // encargado, para un proceso sin cita viva). El PRIMER alumno del escenario
  // ya no califica: acaba de apartar su lugar en el test anterior.
  await page.goto(`${CITAS_URL}?v=atender&date=${HOY}&selected=${PROCESS_ID_2}`,
                  { waitUntil: 'domcontentloaded' });
  const ficha = page.locator('#appt-subject');
  await expect(ficha).toContainText('Sin cita todavía');

  const boton = ficha.getByRole('button', { name: /^Atender ahora/ });
  await expect(boton).toBeVisible();

  const post = esperarPost(page, `${CITAS_URL}/${PROCESS_ID_2}/atender-ahora`);
  await boton.click();
  const resp = await post;
  expect(resp.status()).toBe(200);
  // «Cotejo iniciado.» viaja en `X-Tt-Notice` (percent-codificado por `_hdr`),
  // no en el cuerpo: es la MISMA respuesta que cualquier `_accion` con éxito.
  expect(decodeURIComponent(resp.headers()['x-tt-notice'] || '')).toBe('Cotejo iniciado.');

  // D7: `create(..., start_now=True)` deja la cita en `in_progress` de una
  // sola vez -sin pasar por «Apartarle lugar» ni «Iniciar cotejo»-, así que la
  // ficha re-pintada ya no ofrece «Sin cita todavía» y sí «Marcar asistió»,
  // que SOLO se pinta con `status == 'in_progress'` (Review Focus 4 del plan:
  // sigue siendo UNA sola cita, no dos).
  await expect(ficha).not.toContainText('Sin cita todavía');
  await expect(ficha).toContainText('En proceso');
  await expect(ficha.getByRole('button', { name: 'Marcar asistió' })).toBeVisible();

  await c.close();
});

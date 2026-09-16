// @ts-check
/**
 * Bandeja de Liberaciones de GTV — la encuesta de egresados (Tarea 8, spec
 * `2026-09-15-titulatec-liberacion-gtv` §6.3).
 *
 * Gestión Tecnológica y Vinculación (GTV) revisa lo que el egresado ya envió
 * (`SurveyReview`, una fila por proceso) y decide si libera el requisito de
 * cotejo `graduate_survey` o deja observaciones. Este archivo cubre el
 * recorrido real en navegador que las pruebas de `pytest` no alcanzan:
 *
 *   1. GTV ve la solicitud sembrada en «En revisión» y la observa con un motivo.
 *   2. El egresado ve "Con observaciones" -y el motivo- en la fase 2 de su home.
 *   3. GTV libera la solicitud desde «Con observaciones».
 *   4. El egresado ve "Liberada" en la fase 2 de su home.
 *   5. GTV revoca la liberación mientras la fase 2 de ese proceso no está
 *      aprobada -`can_revoke`-, y la solicitud vuelve a «Con observaciones»
 *      con el nuevo motivo.
 *
 * DEFECTO DE PRODUCTO (documentado en `task-8-report.md`, NO corregido aquí):
 * la spec (§6.3) pide `hx-confirm` en Liberar/Revocar, y el markup lo declara
 * -pero en el `<button>`, descendiente del `<form hx-post=...>` que emite la
 * petición-, y htmx 2.0.3 resuelve `hx-confirm` caminando solo hacia
 * ANCESTROS del elemento con `hx-post`, nunca hacia hijos. Hoy Liberar y
 * Revocar se ejecutan SIN NINGUNA confirmación. Detalle y verificación en el
 * docstring de `dispararAccion`, más abajo.
 *
 * No se recorre el asistente público de la encuesta en el navegador para
 * llegar a "En revisión": eso ya lo cubre `public-survey.spec.js` (pasos,
 * prellenado, congelamiento). Aquí la solicitud nace ya sembrada
 * (`seedSurveyReview`, `_helpers.js`) para poder ejercer la bandeja de GTV
 * sin repetir ese mecanismo.
 *
 * GTV no aparece en `_ROLE_DASHBOARD` con este rol SINTÉTICO (mismo caso que
 * "student"/"head" en el resto de la carpeta: el nombre completo con el
 * sufijo `_gtv` no coincide con el literal `"titulatec_tech_management"` que
 * usa `resolve_dashboard_url`), así que este archivo navega DIRECTO a
 * `/titulatec/admin/liberaciones` en vez de partir de "/" -ese redirect es
 * responsabilidad de `resolve_dashboard_url`, ajena a esta bandeja-. A
 * diferencia de `admin-requests.spec.js` (que sí exige llegar por el menú
 * porque "Solicitudes"/"Encuestas" son items ADICIONALES de un rol con más
 * páginas), Liberaciones es la ÚNICA página de GTV: no hay otra pantalla
 * previa donde aterrizar y clickear el menú.
 *
 * Los tests de este archivo corren EN ORDEN (mismo patrón que
 * `admin-requests.spec.js`: `fullyParallel: false`, `workers: 1`) y comparten
 * el escenario y la MISMA solicitud (`reviewId`) de principio a fin.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState:
 * undefined` (ver el encabezado de `_helpers.js`): en Playwright 1.61 un
 * `undefined` es un no-op y heredaría el storageState global del proyecto
 * (admin de HELPDESK) en vez de quedar sin sesión.
 */
const { test, expect } = require('@playwright/test');
const {
  seedScenario, cleanupScenario, stateFor, seedSurveyReview,
} = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

const LIBERACIONES_URL = '/titulatec/admin/liberaciones';
const DASHBOARD_URL = '/titulatec/student/dashboard';
const MOTIVO_OBSERVACION = 'Falta el comprobante de servicio social en tu ventanilla.';
const MOTIVO_REVOCACION = 'Se detectó que aún debe presentarse a Residencias.';

let ctx;
let reviewId;

test.beforeAll(() => {
  ctx = seedScenario();
  reviewId = seedSurveyReview(ctx);
});
test.afterAll(() => { cleanupScenario(ctx); });

/** Espera la respuesta de un POST a `ruta` (mismo patrón que `admin-requests.spec.js`). */
function esperarPost(page, ruta) {
  return page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ruta
  );
}

/**
 * Dispara Liberar/Revocar y espera la petición POST real.
 *
 * DEFECTO DE PRODUCTO DESCUBIERTO POR ESTE E2E (documentado en
 * `task-8-report.md`, NO corregido aquí por instrucción del brief): la spec
 * (§6.3) pide que Liberar/Revocar lleven `hx-confirm`, y
 * `survey_reviews_body.html` sí lo declara -pero en el `<button>`, que es
 * DESCENDIENTE del `<form hx-post=...>` que en realidad emite la petición.
 * htmx 2.0.3 resuelve `hx-confirm` con
 * `getClosestAttributeValue(elt, 'hx-confirm')` donde `elt` es el FORM (el
 * elemento que declara `hx-post`), y esa función solo camina hacia
 * ANCESTROS (`getClosestMatch`/`parentElt` en `htmx.js`), nunca hacia hijos.
 * Resultado verificado con un spec de diagnóstico aparte (`page.on('dialog')`,
 * `page.on('console')`, conteo de `.modal`): `confirmQuestion` sale
 * `undefined`, el puente de `titulatec-utils.js:265` ve `e.detail.question`
 * vacío y hace `return` ANTES de `preventDefault()`, y htmx sigue con la
 * petición DE INMEDIATO -sin `confirm()` nativo ni el modal de
 * `TitulaTecUtils.confirmDialog`-. Este helper prueba el comportamiento REAL
 * de hoy (sin confirmación); el arreglo -mover `hx-confirm` al `<form>`,
 * mismo elemento que `hx-post`- queda pendiente y fuera de esta tarea.
 */
async function dispararAccion(page, boton, ruta) {
  const peticion = esperarPost(page, ruta);
  await boton.click();
  expect((await peticion).status()).toBe(200);
  // Ver el comentario de arriba: hoy NUNCA aparece un modal para esta acción.
  await expect(page.locator('.modal')).toHaveCount(0);
}

test('GTV ve la solicitud sembrada en «En revisión» y la observa con un motivo', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('gtv') });
  const page = await c.newPage();
  await page.goto(LIBERACIONES_URL, { waitUntil: 'domcontentloaded' });

  // «En revisión» es la pestaña por omisión (spec §6.3): la cola de trabajo.
  await expect(page.locator('#tt-rev-tab-in_review[aria-current="true"]')).toBeVisible();
  const fila = page.locator(`#tt-rev-${reviewId}`);
  await expect(fila).toBeVisible();
  await expect(fila).toContainText('En revisión');

  await fila.getByPlaceholder('Motivo').fill(MOTIVO_OBSERVACION);
  const post = esperarPost(page, `/titulatec/admin/liberaciones/${reviewId}/observar`);
  // Observar NO lleva `hx-confirm` (no destruye nada): submit directo.
  await fila.getByRole('button', { name: 'Observar', exact: true }).click();
  expect((await post).status()).toBe(200);

  // El formulario reenvía la pestaña de la que partió («En revisión»): ahí
  // ya no está -pasó a "rejected"-.
  await expect(page.locator('#tt-rev-tab-in_review[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-rev-${reviewId}`)).toHaveCount(0);

  await page.locator('#tt-rev-tab-rejected').click();
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  const filaObservada = page.locator(`#tt-rev-${reviewId}`);
  await expect(filaObservada).toContainText('Con observaciones');
  await expect(filaObservada).toContainText(MOTIVO_OBSERVACION);

  await c.close();
});

test('el egresado ve "Con observaciones" y el motivo en la fase 2 de su home', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });

  // La píldora vive en el botón del acordeón (visible aunque no esté
  // desplegado): `_phases_ctx` la cuelga SOLO de la card `review_appointment`
  // (fase 2), nunca por número a secas.
  const filaFase2 = page.locator('#tt-acc-btn-2');
  await expect(filaFase2).toContainText('Con observaciones');

  // El motivo solo sale en el panel desplegado -excepción deliberada a "Se
  // habilitará cuando llegues a esta fase": la encuesta no está sujeta a la
  // guarda de fase del alumno (spec §6.1), así que se ve aunque la fase 2 no
  // sea la actual (el escenario la deja en `current_phase = 1`).
  await filaFase2.click();
  const panel = page.locator('#tt-acc-panel-2');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Encuesta de egresados');
  await expect(panel).toContainText(MOTIVO_OBSERVACION);

  await c.close();
});

test('GTV libera la solicitud desde «Con observaciones»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('gtv') });
  const page = await c.newPage();
  await page.goto(LIBERACIONES_URL, { waitUntil: 'domcontentloaded' });

  await page.locator('#tt-rev-tab-rejected').click();
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  const fila = page.locator(`#tt-rev-${reviewId}`);
  await expect(fila).toBeVisible();

  await dispararAccion(
    page,
    fila.getByRole('button', { name: 'Liberar', exact: true }),
    `/titulatec/admin/liberaciones/${reviewId}/liberar`
  );

  // Vuelve a pintar «Con observaciones» (de donde partió el formulario): ya no está.
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-rev-${reviewId}`)).toHaveCount(0);

  await page.locator('#tt-rev-tab-approved').click();
  await expect(page.locator('#tt-rev-tab-approved[aria-current="true"]')).toBeVisible();
  const filaLiberada = page.locator(`#tt-rev-${reviewId}`);
  await expect(filaLiberada).toContainText('Liberada por');
  // La fase 2 del proceso sembrado sigue "pending" (no `approved`): `can_revoke`
  // sigue abierto, así que GTV ve el formulario de Revocar y NO la píldora
  // "Fase 2 liberada" (spec §6.3, borde de §8).
  await expect(filaLiberada.getByRole('button', { name: 'Revocar', exact: true })).toBeVisible();
  await expect(filaLiberada.getByText('Fase 2 liberada')).toHaveCount(0);

  await c.close();
});

test('el egresado ve "Liberada" en la fase 2 de su home', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('student') });
  const page = await c.newPage();
  await page.goto(DASHBOARD_URL, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tt-acc-btn-2')).toContainText('Liberada');
  await c.close();
});

test('GTV puede revocar la liberación mientras la fase 2 no esté aprobada', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('gtv') });
  const page = await c.newPage();
  await page.goto(LIBERACIONES_URL, { waitUntil: 'domcontentloaded' });

  await page.locator('#tt-rev-tab-approved').click();
  await expect(page.locator('#tt-rev-tab-approved[aria-current="true"]')).toBeVisible();
  const fila = page.locator(`#tt-rev-${reviewId}`);
  await expect(fila).toBeVisible();
  await fila.getByPlaceholder('Motivo de la revocación').fill(MOTIVO_REVOCACION);

  await dispararAccion(
    page,
    fila.getByRole('button', { name: 'Revocar', exact: true }),
    `/titulatec/admin/liberaciones/${reviewId}/revocar`
  );

  // Vuelve a pintar «Liberadas» (de donde partió el formulario): ya no está.
  await expect(page.locator('#tt-rev-tab-approved[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-rev-${reviewId}`)).toHaveCount(0);

  await page.locator('#tt-rev-tab-rejected').click();
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  const filaRevocada = page.locator(`#tt-rev-${reviewId}`);
  await expect(filaRevocada).toContainText('Con observaciones');
  await expect(filaRevocada).toContainText(MOTIVO_REVOCACION);

  await c.close();
});

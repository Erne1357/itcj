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
 *   3. GTV intenta liberar y CANCELA en el modal -nada cambia, ningún POST-,
 *      luego libera de verdad desde «Con observaciones» (confirma el modal).
 *   4. El egresado ve "Liberada" en la fase 2 de su home.
 *   5. GTV intenta revocar y CANCELA -nada cambia-, luego revoca de verdad
 *      (confirma) mientras la fase 2 de ese proceso no está aprobada
 *      -`can_revoke`-, y la solicitud vuelve a «Con observaciones» con el
 *      nuevo motivo.
 *
 * RONDA DE CORRECCIÓN (2026-09-15): este mismo E2E encontró que Liberar y
 * Revocar se ejecutaban SIN NINGUNA confirmación -`hx-confirm`/
 * `data-tt-confirm-ok` vivían en el `<button>`, descendiente del
 * `<form hx-post=...>` que emite la petición, y htmx 2.0.3 los resuelve
 * caminando solo hacia ANCESTROS del elemento con `hx-post` (nunca hacia
 * hijos), así que nunca se leían-. Se corrigió moviendo ambos atributos al
 * `<form>` en `survey_reviews_body.html`. Los pasos 3 y 5 de arriba ahora
 * prueban las DOS ramas del modal real de `TitulaTecUtils.confirmDialog`
 * (`confirmarAccion` confirma, `cancelarAccion` cancela) — nunca el
 * `confirm()` nativo, que este proyecto prohíbe.
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
 * Dispara Liberar/Revocar y CONFIRMA en el modal real de
 * `TitulaTecUtils.confirmDialog` -PROHIBIDO `confirm()` nativo en este
 * proyecto-: el puente `htmx:confirm` -> `confirmDialog`
 * (`titulatec-utils.js:265`) intercepta el submit, pinta un `.modal` de
 * Bootstrap con dos botones (`[data-tt-action="confirm"|"cancel"]`) y solo
 * dispara la petición real si se acepta. El botón de confirmación real es
 * el del MODAL, con el texto de `data-tt-confirm-ok` ("Liberar"/"Revocar")
 * -el mismo texto que el botón disparador de la fila-, así que hay que
 * escoparlo a `.modal.show` para no chocar en modo estricto con el
 * disparador. `hx-confirm`/`data-tt-confirm-ok` viven en el `<form>`
 * (`survey_reviews_body.html`), nunca en el `<button>` — ver la nota de
 * corrección en el encabezado del archivo.
 */
async function confirmarAccion(page, boton, ruta, textoOk) {
  const peticion = esperarPost(page, ruta);
  await boton.click();
  const modal = page.locator('.modal.show');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: textoOk, exact: true }).click();
  expect((await peticion).status()).toBe(200);
}

/**
 * Dispara Liberar/Revocar y CANCELA en el modal: ningún POST debe salir y
 * el estado de la fila no debe cambiar. El llamador es quien verifica que
 * la fila siga igual después -este helper solo cierra el modal por la vía
 * de "Cancelar" y confirma que el modal desaparece-.
 */
async function cancelarAccion(page, boton) {
  await boton.click();
  const modal = page.locator('.modal.show');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: 'Cancelar', exact: true }).click();
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

test('GTV libera la solicitud desde «Con observaciones» -cancelar no cambia nada, confirmar sí-', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('gtv') });
  const page = await c.newPage();
  let posts = 0;
  page.on('request', (req) => { if (req.method() === 'POST') posts++; });
  await page.goto(LIBERACIONES_URL, { waitUntil: 'domcontentloaded' });

  await page.locator('#tt-rev-tab-rejected').click();
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  const fila = page.locator(`#tt-rev-${reviewId}`);
  await expect(fila).toBeVisible();

  // Cancelar el modal: ningún POST, la fila sigue exactamente igual.
  await cancelarAccion(page, fila.getByRole('button', { name: 'Liberar', exact: true }));
  expect(posts, 'cancelar el modal de Liberar no debe emitir ningún POST').toBe(0);
  await expect(page.locator('#tt-rev-tab-rejected[aria-current="true"]')).toBeVisible();
  await expect(fila).toContainText('Con observaciones');
  await expect(fila).toContainText(MOTIVO_OBSERVACION);

  // Confirmar el modal: ahora sí sale el POST y la solicitud avanza.
  await confirmarAccion(
    page,
    fila.getByRole('button', { name: 'Liberar', exact: true }),
    `/titulatec/admin/liberaciones/${reviewId}/liberar`,
    'Liberar'
  );
  expect(posts, 'confirmar debe emitir EXACTAMENTE un POST (el de cancelar no contó)').toBe(1);

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

test('GTV puede revocar la liberación mientras la fase 2 no esté aprobada -cancelar no cambia nada, confirmar sí-', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('gtv') });
  const page = await c.newPage();
  let posts = 0;
  page.on('request', (req) => { if (req.method() === 'POST') posts++; });
  await page.goto(LIBERACIONES_URL, { waitUntil: 'domcontentloaded' });

  await page.locator('#tt-rev-tab-approved').click();
  await expect(page.locator('#tt-rev-tab-approved[aria-current="true"]')).toBeVisible();
  const fila = page.locator(`#tt-rev-${reviewId}`);
  await expect(fila).toBeVisible();
  // El motivo se escribe UNA sola vez: cancelar no vacía el campo -no hay
  // swap alguno, la fila entera sigue siendo el mismo nodo del DOM-.
  await fila.getByPlaceholder('Motivo de la revocación').fill(MOTIVO_REVOCACION);

  // Cancelar el modal: ningún POST, la fila sigue "Liberada".
  await cancelarAccion(page, fila.getByRole('button', { name: 'Revocar', exact: true }));
  expect(posts, 'cancelar el modal de Revocar no debe emitir ningún POST').toBe(0);
  await expect(page.locator('#tt-rev-tab-approved[aria-current="true"]')).toBeVisible();
  await expect(fila).toContainText('Liberada por');

  // Confirmar el modal: ahora sí sale el POST y la solicitud se revoca.
  await confirmarAccion(
    page,
    fila.getByRole('button', { name: 'Revocar', exact: true }),
    `/titulatec/admin/liberaciones/${reviewId}/revocar`,
    'Revocar'
  );
  expect(posts, 'confirmar debe emitir EXACTAMENTE un POST (el de cancelar no contó)').toBe(1);

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

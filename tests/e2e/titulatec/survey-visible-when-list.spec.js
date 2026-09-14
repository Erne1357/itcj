// @ts-check
/**
 * Fix B1 (`.superpowers/sdd/2026-09-14-titulatec-encuesta-egresados/`):
 * `visible_when` con una LISTA de valores ("alguna de estas"), del lado del
 * CLIENTE.
 *
 * `survey_validator.py::is_visible` ya sabe leer `visible_when` como una
 * lista (pertenencia) o como un escalar (igualdad). `survey.js::applyVisibility`
 * solo sabía igualdad (`values[k] === cond[k]`): contra una lista, un texto
 * nunca es `===` a un arreglo, así que `hidden` quedaba SIEMPRE verdadero y
 * la sección dependiente jamás aparecía -medido sobre el esquema real: 3 de
 * las 4 respuestas de `actividad_actual` dejaban campos obligatorios
 * atrapados, y quien los tenía no podía terminar la encuesta.
 *
 * Este archivo es deliberadamente angosto: solo prueba el MECANISMO de
 * visibilidad con una condición de lista, en el esquema SINTÉTICO de
 * `_helpers.js` (`relacion_carrera`, `visible_when: {"situacion_laboral":
 * ["empleado", "otro"]}` desde el fix B1). No repite lo que ya cubren
 * `public-survey.spec.js` (pasos, sesión, envío) ni `test_survey_steps.py`
 * (la misma semántica del lado del SERVIDOR, con su propio caso de lista).
 *
 * "otro" es el SEGUNDO elemento de la lista, a propósito: si alguien
 * reimplementara esto comparando solo contra `cond[k][0]`, esta prueba lo
 * detectaría igual que detecta el `===` original.
 *
 * `storageState: { cookies: [], origins: [] } }`, NUNCA `storageState:
 * undefined` (ver la nota en `_helpers.js` / `public-survey.spec.js`): un
 * `undefined` hereda la cookie del admin de helpdesk del proyecto global, y
 * `require_page_app`/`_requiere_sesion` no perdonan a ese admin.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor } = require('./_helpers');

test.use({ storageState: { cookies: [], origins: [] } });

const SURVEY_URL = '/titulatec/encuesta-egresados';

test.describe('visible_when con lista (fix B1)', () => {
  let ctx;

  test.beforeEach(() => { ctx = seedScenario(); });
  test.afterEach(() => { cleanupScenario(ctx); });

  test('el campo dependiente solo se muestra cuando el valor marcado pertenece a la lista', async ({ browser }) => {
    const c = await browser.newContext({ storageState: stateFor('student') });
    const page = await c.newPage();
    await page.goto(SURVEY_URL, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('main[data-tt-page="public_survey"]')).toBeVisible();
    await expect(page.getByText('Paso 1 de 3')).toBeVisible();

    const dependiente = page.locator('[data-tt-field="relacion_carrera"]');

    // Recien cargada, sin nada marcado: ninguna condicion se cumple.
    await expect(dependiente).toBeHidden();

    // "buscando" NO esta en ["empleado", "otro"]: sigue oculto. Sin este paso,
    // una implementacion que mostrara el campo ante CUALQUIER valor marcado
    // (en vez de solo los de la lista) pasaria la prueba igual.
    await page.locator('input[name="situacion_laboral"][value="buscando"]').check();
    await expect(dependiente).toBeHidden();

    // "otro" SI esta en la lista -y es su SEGUNDO elemento-: el defecto B1
    // (`values[k] === cond[k]` contra un arreglo, siempre falso) dejaba esto
    // oculto para siempre. Revertir `applyVisibility` a esa comparacion hace
    // fallar esta asercion.
    await page.locator('input[name="situacion_laboral"][value="otro"]').check();
    await expect(dependiente).toBeVisible();

    // Y vuelve a ocultarse al marcar un valor fuera de la lista: no es que
    // el campo se haya quedado "pegado" visible una vez mostrado.
    await page.locator('input[name="situacion_laboral"][value="estudiando"]').check();
    await expect(dependiente).toBeHidden();

    await c.close();
  });
});

// @ts-check
/**
 * Tutorial v2 del escritorio (/itcj/dashboard) — spec «Temas y tutorial» §C.
 *
 * Shepherd 11.2.0 y dashboard_tutorial.js se cargan bajo demanda
 * (desktop/tutorial-loader.js). Este spec cubre:
 *  - recorrido completo de los 14 pasos con las acciones REALES (doble clic,
 *    minimizar, restaurar desde la barra, cerrar, botón de inicio, campana);
 *  - pasivos con `canClickTarget:false`, interactivos sin «Siguiente», indicador
 *    «Paso n de N», sin emojis ni «dashboard» en el texto;
 *  - con la clave no se descarga Shepherd; el botón Tutorial pide confirmación;
 *  - omitir + confirmar deja todo limpio;
 *  - X o Esc a media ventana/menú/panel → «Continuar» reanuda en el paso que
 *    vuelve a abrir lo que se cerró;
 *  - a 820×640 cada popover cabe en pantalla y no tapa su objetivo;
 *  - nada (p. ej. una decoración del tema activo) se pinta encima del popover;
 *  - «Atrás» rehace lo que cada paso necesita (ventana, menú, panel);
 *  - sin errores de consola del escritorio.
 * Pasa con o sin tema activo en la BD (ruling R1 del plan de temas).
 *
 * Capturas: `E2E_CAPTURE=1 npx playwright test core/desktop-tutorial.spec.js`
 * escribe tutorial-*.png en .playwright-mcp/images/core/temas/.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SHOTS = path.join(__dirname, '..', '..', '..', '.playwright-mcp', 'images', 'core', 'temas');
const CAPTURE = !!process.env.E2E_CAPTURE;

const IDS = [
  'welcome', 'desktop-apps', 'open-app', 'window-move', 'window-controls', 'minimize',
  'taskbar-restore', 'close-window', 'search', 'start-open', 'start-menu', 'notifications',
  'notifications-panel', 'done'
];
/** Pasos que avanzan con la acción real (sin «Siguiente»). */
const INTERACTIVE = ['open-app', 'minimize', 'taskbar-restore', 'close-window', 'start-open'];
/** Pasos que solo señalan (objetivo no clicable). */
const PASSIVE = ['desktop-apps', 'window-move', 'window-controls', 'search', 'start-menu', 'notifications-panel'];
const CAPTURE_AT = { welcome: 'welcome', 'window-controls': 'ventana', 'start-menu': 'menu-inicio', 'notifications-panel': 'notificaciones' };

const VISIBLE_STEP = '.shepherd-element[data-shepherd-step-id]:visible';

/**
 * Excepciones, diálogos nativos (prohibidos) y errores de consola del escritorio
 * (documento del escritorio, estáticos del core o sin origen). Un error propio
 * de la app embebida en la ventana demo no es de este spec.
 */
function trackErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.stack || e}`));
  page.on('dialog', (d) => {
    errors.push(`diálogo nativo: ${d.type()} ${d.message()}`);
    d.dismiss().catch(() => {});
  });
  page.on('console', (m) => {
    const where = m.location().url || '';
    if (m.type() === 'error' && (!where || /\/itcj\/dashboard|\/static\/core\//.test(where))) {
      errors.push(`console: ${m.text()} @ ${where}`);
    }
  });
  return errors;
}

/** Fija (o quita) la clave de «tutorial visto» solo en el documento del escritorio. */
async function setCompletedKey(page, completed) {
  await page.addInitScript((done) => {
    if (window.top !== window) return;
    try {
      if (done) localStorage.setItem('dashboard_tutorial_completed', 'true');
      else localStorage.removeItem('dashboard_tutorial_completed');
    } catch (e) { /* sin storage */ }
  }, completed);
}

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

/** Id del paso visible (null si no hay). */
async function currentStepId(page) {
  const loc = page.locator(VISIBLE_STEP);
  if (await loc.count() === 0) return null;
  return loc.first().getAttribute('data-shepherd-step-id');
}

async function expectStep(page, id) {
  await expect(page.locator(`.shepherd-element[data-shepherd-step-id="${id}"]`)).toBeVisible({ timeout: 10_000 });
}

/** Espera a que el paso visible deje de ser `prev` y haya otro (o ninguno si `allowNone`). */
async function waitStepChange(page, prev, allowNone) {
  await expect.poll(async () => {
    const id = await currentStepId(page).catch(() => null);
    if (id === prev) return 'same';
    if (id === null && !allowNone) return 'none';
    return 'changed';
  }, { timeout: 10_000 }).toBe('changed');
}

/** App que usa el tutorial para la demostración: Help Desk si está; si no, la primera. */
async function demoKey(page) {
  return page.evaluate(() => {
    if (document.querySelector('.desktop-icon[data-app="helpdesk"]')) return 'helpdesk';
    const first = document.querySelector('.desktop-icon:not(.is-decorative)');
    return first ? first.getAttribute('data-app') : null;
  });
}

const windowOf = (page, key) => page.locator(`.app-window[data-app-id="${key}"]`);

/** Hace la acción real del paso `id` (la que lo hace avanzar). */
async function act(page, id, key) {
  const step = page.locator(`.shepherd-element[data-shepherd-step-id="${id}"]`);
  switch (id) {
    case 'welcome':
      await step.getByRole('button', { name: 'Comenzar' }).click();
      break;
    case 'open-app':
      await page.locator(`.desktop-icon[data-app="${key}"]`).dblclick();
      await expect(windowOf(page, key)).toBeVisible();
      break;
    case 'minimize':
      await windowOf(page, key).locator('.window-control.minimize').click();
      await expect(windowOf(page, key)).toHaveClass(/is-minimized/);
      break;
    case 'taskbar-restore':
      await page.locator(`.taskbar-app[data-app="${key}"]`).click();
      await expect(windowOf(page, key)).not.toHaveClass(/is-minimized/);
      break;
    case 'close-window':
      await windowOf(page, key).locator('.window-control.close').click();
      await expect(page.locator('.app-window[data-app-id]')).toHaveCount(0);
      break;
    case 'start-open':
      await page.locator('.start-button').click();
      await expect(page.locator('#startMenu')).toBeVisible();
      break;
    case 'notifications':
      await step.getByRole('button', { name: 'Ver notificaciones' }).click();
      await expect(page.locator('#notification-panel')).toBeVisible();
      break;
    case 'done':
      await step.getByRole('button', { name: 'Finalizar' }).click();
      break;
    default:
      await step.getByRole('button', { name: 'Siguiente' }).click();
  }
}

/** Avanza con acciones reales hasta que el paso visible sea `target`. */
async function advanceTo(page, target, key) {
  for (let guard = 0; guard < 20; guard++) {
    const id = await currentStepId(page);
    if (id === target) return;
    await act(page, id, key);
    await waitStepChange(page, id, false);
  }
  throw new Error('no se llegó al paso ' + target);
}

/** El escritorio quedó como antes del tutorial. */
async function expectCleanDesktop(page) {
  await expect(page.locator('.shepherd-element')).toHaveCount(0);
  await expect(page.locator('.shepherd-modal-overlay-container')).toHaveCount(0);
  await expect(page.locator('.app-window[data-app-id]')).toHaveCount(0);
  await expect(page.locator('#startMenu')).toBeHidden();
  await expect(page.locator('#notification-panel')).toBeHidden();
  await expect(page.locator('#dashboardTutorialButton')).toBeEnabled();
  await expect(page.locator('.start-button')).toHaveCSS('pointer-events', 'auto');
  await expect(page.locator('.shepherd-target')).toHaveCount(0);
  const ls = await page.evaluate(() => ({
    done: localStorage.getItem('dashboard_tutorial_completed'),
    mode: localStorage.getItem('dashboard_tutorial_mode_active')
  }));
  expect(ls).toEqual({ done: 'true', mode: null });
}

/**
 * Pulsa «Tutorial» y, en cuanto Bootstrap empieza a mostrar el diálogo de
 * inicio (body.modal-open, antes de que termine el fade), pulsa `buttonId`.
 * Bootstrap ignora hide() a media transición: el tutorial no debe perder ese
 * clic. Devuelve true si de verdad se pulsó mientras el diálogo entraba.
 */
async function clickWhileEntering(page, buttonId) {
  return page.evaluate(async (id) => {
    document.getElementById('dashboardTutorialButton').click();
    for (let i = 0; i < 200 && !document.body.classList.contains('modal-open'); i++) {
      await new Promise((r) => setTimeout(r, 5));
    }
    const modal = document.getElementById('dashboardTutorialStartModal');
    const entering = document.body.classList.contains('modal-open') && !!modal && modal.dataset.ready !== '1';
    document.getElementById(id).click();
    return entering;
  }, buttonId);
}

function rect(box) {
  return { l: box.x, t: box.y, r: box.x + box.width, b: box.y + box.height };
}

/**
 * Nada se pinta encima del popover (título, X y botones). Las decoraciones de
 * los temas llevan pointer-events:none y elementFromPoint las atravesaría: por
 * un instante TODO se vuelve «tocable» para que cuente lo que está pintado.
 */
async function expectNothingAbove(page, id) {
  const covered = await page.locator(VISIBLE_STEP).evaluate((pop) => {
    const style = document.createElement('style');
    style.textContent = '* { pointer-events: auto !important; }';
    document.head.appendChild(style);
    try {
      const parts = Array.from(pop.querySelectorAll('.shepherd-title, .shepherd-cancel-icon, .shepherd-footer .shepherd-button'));
      return parts.filter((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !(hit && pop.contains(hit));
      }).map((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return (el.textContent || el.className).trim() + ' ← ' + (hit ? hit.tagName + '#' + hit.id + '.' + hit.className : 'nada');
      });
    } finally {
      style.remove();
    }
  });
  expect(covered, `${id}: algo tapa el popover`).toEqual([]);
}

test.describe('tutorial del escritorio', () => {
  test('sin la clave aparece solo y se recorre completo con acciones reales', async ({ page }) => {
    test.setTimeout(120_000);
    const errors = trackErrors(page);
    await setCompletedKey(page, false);
    await gotoDesktop(page);
    const key = await demoKey(page);
    expect(key).toBeTruthy();

    await expectStep(page, 'welcome');
    const welcome = page.locator('.shepherd-element[data-shepherd-step-id="welcome"]');
    await expect(welcome.getByRole('button', { name: 'Omitir' })).toBeVisible();
    await expect(welcome.getByRole('button', { name: 'Comenzar' })).toBeVisible();
    await expect(page.locator('#dashboardTutorialButton')).toBeDisabled();
    expect(await page.evaluate(() => localStorage.getItem('dashboard_tutorial_mode_active'))).toBe('true');

    const visited = [];
    for (let guard = 0; guard < 20; guard++) {
      const id = await currentStepId(page);
      if (!id) break;
      visited.push(id);
      const step = page.locator(`.shepherd-element[data-shepherd-step-id="${id}"]`);
      const n = visited.length;

      // Indicador de progreso y texto sin emojis ni «dashboard».
      await expect(step.locator('.dashboard-tutorial-progress')).toHaveText(`Paso ${n} de ${IDS.length}`);
      const text = await step.innerText();
      expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
      expect(text).not.toMatch(/dashboard/i);

      await expectNothingAbove(page, id);
      if (PASSIVE.includes(id)) {
        await expect(page.locator('.shepherd-target.shepherd-target-click-disabled')).toHaveCount(1);
      }
      if (INTERACTIVE.includes(id)) {
        await expect(step.getByRole('button', { name: 'Siguiente' })).toHaveCount(0);
        await expect(page.locator('.shepherd-target.shepherd-target-click-disabled')).toHaveCount(0);
      }
      if (CAPTURE && CAPTURE_AT[id]) {
        await page.waitForTimeout(400);
        await page.screenshot({ path: path.join(SHOTS, `tutorial-${CAPTURE_AT[id]}.png`) });
      }

      await act(page, id, key);
      await waitStepChange(page, id, id === 'done');
    }

    expect(visited).toEqual(IDS);
    await expectCleanDesktop(page);
    expect(errors).toEqual([]);
  });

  test('con la clave no se descarga Shepherd ni el script del tutorial', async ({ page }) => {
    const requested = [];
    page.on('request', (r) => {
      if (/shepherd|dashboard_tutorial\.js/.test(r.url())) requested.push(r.url());
    });
    await setCompletedKey(page, true);
    await gotoDesktop(page);
    await page.waitForTimeout(4000); // cubre el retraso del auto-inicio (1.5 s + idle)
    expect(requested).toEqual([]);
    await expect(page.locator('.shepherd-element')).toHaveCount(0);
  });

  test('el botón Tutorial pide confirmación; omitir + confirmar deja todo limpio', async ({ page }) => {
    test.setTimeout(60_000);
    const errors = trackErrors(page);
    const requested = [];
    page.on('request', (r) => {
      if (/shepherd\.min\.js/.test(r.url())) requested.push(r.url());
    });
    await setCompletedKey(page, true);
    await gotoDesktop(page);
    expect(requested).toEqual([]);

    // Cancelar la confirmación no inicia nada y re-habilita el botón.
    const btn = page.locator('#dashboardTutorialButton');
    await btn.click();
    await expect(page.locator('#dashboardTutorialStartModal')).toBeVisible();
    await expect(btn).toBeDisabled();
    await page.locator('#dashboardTutorialStartModal').getByRole('button', { name: 'Cancelar' }).click();
    await expect(page.locator('#dashboardTutorialStartModal')).toBeHidden();
    await expect(btn).toBeEnabled();
    await expect(page.locator('.shepherd-element')).toHaveCount(0);

    // Un clic rápido en «Cancelar» mientras el diálogo todavía entra (Bootstrap
    // ignora hide() a media transición) también lo cierra.
    expect(await clickWhileEntering(page, 'dashboardTutorialStartCancel')).toBe(true);
    await expect(page.locator('#dashboardTutorialStartModal')).toBeHidden();
    await expect(btn).toBeEnabled();
    await expect(page.locator('body')).not.toHaveClass(/modal-open/);

    // «Iniciar», también pulsado a media entrada, abre el tour (Shepherd se descargó una sola vez).
    expect(await clickWhileEntering(page, 'dashboardTutorialStartConfirm')).toBe(true);
    await expect(page.locator('#dashboardTutorialStartModal')).toBeHidden();
    await expectStep(page, 'welcome');
    expect(requested.length).toBe(1);

    // Omitir pide confirmación; confirmar la salida deja el escritorio limpio.
    await page.locator(VISIBLE_STEP).getByRole('button', { name: 'Omitir' }).click();
    await expect(page.locator('#dashboardTutorialCancelModal')).toBeVisible();
    if (CAPTURE) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(SHOTS, 'tutorial-salir.png') });
    }
    await page.locator('#dashboardTutorialCancelConfirm').click();
    await expect(page.locator('#dashboardTutorialCancelModal')).toBeHidden();
    await expectCleanDesktop(page);
    expect(errors).toEqual([]);
  });

  test('X o Esc a media ventana/menú/panel: «Continuar» reanuda en el paso que lo vuelve a abrir', async ({ page }) => {
    test.setTimeout(120_000);
    const errors = trackErrors(page);
    await setCompletedKey(page, false);
    await gotoDesktop(page);
    const key = await demoKey(page);
    await expectStep(page, 'welcome');
    const cancelModal = page.locator('#dashboardTutorialCancelModal');
    const resume = cancelModal.getByRole('button', { name: 'Continuar' });

    // X con la ventana demo abierta: se cierra todo; «Continuar» vuelve a open-app.
    await advanceTo(page, 'window-controls', key);
    await expect(windowOf(page, key)).toBeVisible();
    await page.locator(VISIBLE_STEP).locator('.shepherd-cancel-icon').click();
    await expect(cancelModal).toBeVisible();
    await expect(page.locator('.shepherd-element')).toHaveCount(0);
    await expect(page.locator('.app-window[data-app-id]')).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('dashboard_tutorial_mode_active'))).toBeNull();
    await resume.click();
    await expectStep(page, 'open-app');
    await expect(page.locator('.dashboard-tutorial-progress')).toHaveText(`Paso 3 de ${IDS.length}`);

    // Esc con el menú de inicio abierto: «Continuar» vuelve a start-open (menú cerrado).
    await advanceTo(page, 'start-menu', key);
    await expect(page.locator('#startMenu')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(cancelModal).toBeVisible();
    await expect(page.locator('#startMenu')).toBeHidden();
    await resume.click();
    await expectStep(page, 'start-open');
    await expect(page.locator('#startMenu')).toBeHidden();

    // X con el panel de notificaciones abierto: «Continuar» vuelve a notifications.
    await advanceTo(page, 'notifications-panel', key);
    await expect(page.locator('#notification-panel')).toBeVisible();
    await page.locator(VISIBLE_STEP).locator('.shepherd-cancel-icon').click();
    await expect(cancelModal).toBeVisible();
    await expect(page.locator('#notification-panel')).toBeHidden();
    await resume.click();
    await expectStep(page, 'notifications');

    // Esc + «Salir del tutorial»: todo limpio y no vuelve a aparecer solo.
    await page.keyboard.press('Escape');
    await expect(cancelModal).toBeVisible();
    await page.locator('#dashboardTutorialCancelConfirm').click();
    await expectCleanDesktop(page);
    expect(errors).toEqual([]);
  });

  test('«Atrás» rehace lo que cada paso necesita; Enter en la app demo también avanza', async ({ page }) => {
    test.setTimeout(120_000);
    const errors = trackErrors(page);
    await setCompletedKey(page, false);
    await gotoDesktop(page);
    const key = await demoKey(page);
    await expectStep(page, 'welcome');
    await advanceTo(page, 'done', key);

    // Qué debe estar a la vista al volver a cada paso.
    const demo = windowOf(page, key);
    const expectations = {
      'notifications-panel': async () => expect(page.locator('#notification-panel')).toBeVisible(),
      notifications: async () => expect(page.locator('#notification-panel')).toBeHidden(),
      'start-menu': async () => expect(page.locator('#startMenu')).toBeVisible(),
      'start-open': async () => expect(page.locator('#startMenu')).toBeHidden(),
      search: async () => expect(page.locator('#startMenu')).toBeHidden(),
      'close-window': async () => { await expect(demo).toBeVisible(); await expect(demo).not.toHaveClass(/is-minimized/); },
      'taskbar-restore': async () => expect(demo).toHaveClass(/is-minimized/),
      minimize: async () => { await expect(demo).toBeVisible(); await expect(demo).not.toHaveClass(/is-minimized/); },
      'window-controls': async () => expect(demo).toBeVisible(),
      'window-move': async () => expect(demo).toBeVisible(),
      'open-app': async () => expect(page.locator('.app-window[data-app-id]')).toHaveCount(0),
      'desktop-apps': async () => expect(page.locator('.app-window[data-app-id]')).toHaveCount(0)
    };
    for (let i = IDS.length - 1; i > 2; i--) {
      const from = IDS[i];
      const to = IDS[i - 1];
      await page.locator(`.shepherd-element[data-shepherd-step-id="${from}"]`).getByRole('button', { name: 'Atrás' }).click();
      await expectStep(page, to);
      await expectations[to]();
    }

    // En open-app: seleccionar el icono y Enter abre la app y avanza (además del doble clic).
    await page.locator(`.desktop-icon[data-app="${key}"]`).click();
    await page.keyboard.press('Enter');
    await expectStep(page, 'window-move');
    await expect(demo).toBeVisible();

    // Ctrl+K no abre el buscador bajo el atenuado.
    await page.keyboard.press('Control+k');
    await expect(page.locator('#startMenu')).toBeHidden();

    await page.locator(VISIBLE_STEP).locator('.shepherd-cancel-icon').click();
    await page.locator('#dashboardTutorialCancelConfirm').click();
    await expectCleanDesktop(page);
    expect(errors).toEqual([]);
  });

  test.describe('pantalla de 820×640', () => {
    test.use({ viewport: { width: 820, height: 640 } });

    test('cada popover cabe en pantalla y no tapa su objetivo', async ({ page }) => {
      test.setTimeout(120_000);
      const errors = trackErrors(page);
      await setCompletedKey(page, false);
      await gotoDesktop(page);
      const key = await demoKey(page);
      await expectStep(page, 'welcome');

      const visited = [];
      for (let guard = 0; guard < 20; guard++) {
        const id = await currentStepId(page);
        if (!id) break;
        visited.push(id);
        const pop = page.locator(VISIBLE_STEP);
        await page.waitForTimeout(350); // posicionamiento + entrada del popover
        const box = await pop.boundingBox();
        expect(box, id).not.toBeNull();
        const p = rect(box);
        expect(p.l, `${id}: izquierda`).toBeGreaterThanOrEqual(0);
        expect(p.t, `${id}: arriba`).toBeGreaterThanOrEqual(0);
        expect(p.r, `${id}: derecha`).toBeLessThanOrEqual(820);
        expect(p.b, `${id}: abajo`).toBeLessThanOrEqual(640);
        // Los botones del popover se ven completos.
        for (const b of await pop.locator('.shepherd-footer .shepherd-button').all()) {
          const bb = await b.boundingBox();
          expect(bb && bb.x >= 0 && bb.x + bb.width <= 820 && bb.y + bb.height <= 640, `${id}: botón visible`).toBeTruthy();
        }
        await expectNothingAbove(page, id);
        // Un paso con objetivo no lo tapa.
        const target = page.locator('.shepherd-target:not(body)');
        if (await target.count()) {
          const t = rect(await target.first().boundingBox());
          const overlap = Math.max(0, Math.min(p.r, t.r) - Math.max(p.l, t.l)) * Math.max(0, Math.min(p.b, t.b) - Math.max(p.t, t.t));
          expect(overlap, `${id}: el popover tapa su objetivo`).toBe(0);
        }
        if (CAPTURE && id === 'start-menu') {
          await page.screenshot({ path: path.join(SHOTS, 'tutorial-estrecho.png') });
        }
        await act(page, id, key);
        await waitStepChange(page, id, id === 'done');
      }
      expect(visited).toEqual(IDS);
      expect(errors).toEqual([]);
    });
  });
});

// @ts-check
/**
 * Tutorial del escritorio (/itcj/dashboard) — Task 6.
 *
 * Shepherd y dashboard_tutorial.js se cargan bajo demanda (desktop/tutorial-loader.js):
 *  - sin la clave `dashboard_tutorial_completed` el tour aparece solo y se recorre completo;
 *  - con la clave NO se descarga Shepherd ni el script del tutorial;
 *  - el botón "Tutorial" lo inicia (con modal de confirmación).
 */
const { test, expect } = require('@playwright/test');

const STEP = '.shepherd-element[data-shepherd-step-id]';

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
}

/** Id del paso visible ahora mismo. */
async function currentStepId(page) {
  return page.locator(STEP).last().getAttribute('data-shepherd-step-id');
}

/** Espera a que el paso visible sea distinto de `prev`. */
async function waitStepChange(page, prev) {
  await expect.poll(() => currentStepId(page).catch(() => null), { timeout: 8000 }).not.toBe(prev);
}

test.describe('tutorial del escritorio', () => {
  test('sin la clave aparece el tour y se recorre hasta el final sin errores', async ({ page }) => {
    test.setTimeout(90_000);
    const errors = [];
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    page.on('console', (m) => {
      if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text());
    });

    await page.addInitScript(() => {
      try { localStorage.removeItem('dashboard_tutorial_completed'); } catch (e) { /* sin storage */ }
    });
    await gotoDesktop(page);
    await expect(page.locator(STEP).first()).toBeVisible({ timeout: 8000 });

    const visited = [];
    for (let guard = 0; guard < 30; guard++) {
      const id = await currentStepId(page);
      visited.push(id);
      const step = page.locator(`.shepherd-element[data-shepherd-step-id="${id}"]`);
      if (id === 'tutorial-complete') {
        await step.getByRole('button', { name: 'Finalizar' }).click();
        break;
      }
      if (id === 'double-click-demo') {
        await page.locator('.shepherd-target').dblclick();
      } else if (id === 'open-profile-menu') {
        await page.locator('.start-button').click();
        await expect(page.locator('#startMenu')).toBeVisible();
      } else if (id === 'open-profile-demo') {
        await page.locator('#startMenuUser').click();
      } else if (id === 'notifications-demo') {
        await step.getByRole('button', { name: 'Ver Notificaciones' }).click();
      } else if (id === 'welcome') {
        await step.getByRole('button', { name: 'Comenzar' }).click();
      } else {
        await step.getByRole('button', { name: 'Siguiente' }).click();
      }
      await waitStepChange(page, id);
    }

    // El flujo pasó por los pasos que dependían de selectores nuevos.
    for (const id of ['welcome', 'double-click-demo', 'window-opened', 'close-window-demo',
      'profile-menu-options', 'open-profile-demo', 'profile-window', 'tutorial-complete']) {
      expect(visited).toContain(id);
    }

    await expect(page.locator('.shepherd-element')).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('dashboard_tutorial_completed'))).toBe('true');
    await expect(page.locator('.app-window[data-app-id]')).toHaveCount(0);
    await expect(page.locator('#startMenu')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test('con la clave no se descarga Shepherd ni el script del tutorial', async ({ page }) => {
    const requested = [];
    page.on('request', (r) => {
      if (/shepherd|dashboard_tutorial\.js/.test(r.url())) requested.push(r.url());
    });
    await page.addInitScript(() => {
      try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* sin storage */ }
    });
    await gotoDesktop(page);
    await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
    await page.waitForTimeout(4000); // cubre el retraso del auto-inicio (1.5 s + idle)
    expect(requested).toEqual([]);
    await expect(page.locator('.shepherd-element')).toHaveCount(0);
  });

  test('el botón Tutorial lo inicia (carga bajo demanda + confirmación)', async ({ page }) => {
    const requested = [];
    page.on('request', (r) => {
      if (/shepherd\.min\.js/.test(r.url())) requested.push(r.url());
    });
    await page.addInitScript(() => {
      try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* sin storage */ }
    });
    await gotoDesktop(page);
    await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
    expect(requested).toEqual([]);

    await page.locator('#dashboardTutorialButton').click();
    await page.locator('#dashboardTutorialStartConfirm').click();
    await expect(page.locator('.shepherd-element[data-shepherd-step-id="welcome"]')).toBeVisible({ timeout: 8000 });
    expect(requested.length).toBe(1);

    // Salir del tour deja el escritorio operativo.
    await page.locator('.shepherd-element').getByRole('button', { name: 'Omitir Tutorial' }).click();
    await page.locator('#dashboardTutorialCancelConfirm').click();
    await expect(page.locator('.shepherd-element')).toHaveCount(0);
    await expect(page.locator('.start-button')).toHaveCSS('pointer-events', 'auto');
  });

  test('cancelar con la X no deja panel demo ni ventanas; Continuar reanuda el tour', async ({ page }) => {
    test.setTimeout(90_000);
    await page.addInitScript(() => {
      try { localStorage.removeItem('dashboard_tutorial_completed'); } catch (e) { /* sin storage */ }
    });
    await gotoDesktop(page);
    await expect(page.locator(STEP).first()).toBeVisible({ timeout: 8000 });

    // Avanza hasta el panel de notificaciones demo.
    for (let guard = 0; guard < 30; guard++) {
      const id = await currentStepId(page);
      if (id === 'notifications-panel') break;
      const step = page.locator(`.shepherd-element[data-shepherd-step-id="${id}"]`);
      if (id === 'double-click-demo') await page.locator('.shepherd-target').dblclick();
      else if (id === 'notifications-demo') await step.getByRole('button', { name: 'Ver Notificaciones' }).click();
      else if (id === 'welcome') await step.getByRole('button', { name: 'Comenzar' }).click();
      else await step.getByRole('button', { name: 'Siguiente' }).click();
      await waitStepChange(page, id);
    }
    await expect(page.locator('#tutorialNotificationPanel')).toBeVisible();
    // Iconos de las notificaciones demo: del sprite del escritorio (ya no hay lucide).
    await expect(page.locator('#tutorialNotificationPanel [data-lucide]')).toHaveCount(0);
    const demoIcons = page.locator('#tutorialNotificationPanel svg.ico use');
    expect(await demoIcons.count()).toBeGreaterThan(0);
    for (const href of await demoIcons.evaluateAll((els) => els.map((u) => u.getAttribute('href')))) {
      expect(['#i-calendar', '#i-ticket', '#i-bell']).toContain(href);
    }

    // La X del popover debe ser clicable; "Continuar Tutorial" vuelve al tour.
    await page.locator(STEP).last().locator('.shepherd-cancel-icon').click();
    await page.locator('#dashboardTutorialCancelModal .btn-secondary').click();
    await expect(page.locator('#tutorialNotificationPanel')).toHaveCount(0);
    await expect(page.locator('.shepherd-element[data-shepherd-step-id="notifications-demo"]')).toBeVisible({ timeout: 8000 });

    // Cancelar y confirmar la salida deja todo limpio.
    await page.locator(STEP).last().locator('.shepherd-cancel-icon').click();
    await page.locator('#dashboardTutorialCancelConfirm').click();
    await expect(page.locator('.shepherd-element')).toHaveCount(0);
    await expect(page.locator('#tutorialNotificationPanel')).toHaveCount(0);
    await expect(page.locator('.app-window[data-app-id]')).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('dashboard_tutorial_mode_active'))).not.toBe('true');
  });
});

// @ts-check
/**
 * Menú inicio + buscador del escritorio (/itcj/dashboard) — Task 4.
 * Barra estrecha (≤ 960 px, el campo de la barra queda en la lupa): la búsqueda
 * se escribe en un campo visible arriba del menú de inicio (patrón Windows 11).
 * Bandeja vs. centro de la barra de 700 a 1920 px, con y sin un botón extra.
 * Captura: `E2E_CAPTURE=1 npx playwright test core/desktop-start-menu.spec.js`
 * escribe desktop-start-menu.png en .playwright-mcp/images/core/ y
 * buscador-estrecho.png en .playwright-mcp/images/core/temas/.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SHOTS = path.join(__dirname, '..', '..', '..', '.playwright-mcp', 'images', 'core');
const CAPTURE = !!process.env.E2E_CAPTURE;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* iframe sin storage */ }
  });
});

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

const windowOf = (page, key) => page.locator(`.app-window[data-app-id="${key}"]`);

test('clic en el botón de inicio abre y cierra el menú; aria-expanded sincronizado', async ({ page }) => {
  await gotoDesktop(page);
  const btn = page.locator('.start-button');
  await expect(page.locator('#startMenu')).toBeHidden();
  await btn.click();
  await expect(page.locator('#startMenu')).toBeVisible();
  await expect(btn).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#startMenuApps .start-app')).toHaveCount(5);
  await expect(page.locator('#startMenuUser')).toContainText(/\S/);
  await btn.click();
  await expect(page.locator('#startMenu')).toBeHidden();
  await expect(btn).toHaveAttribute('aria-expanded', 'false');
});

test('la tarjeta de usuario abre la ventana de perfil con un clic', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuUser').click();
  await expect(windowOf(page, 'profile')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('una app de la cuadrícula abre su ventana y cierra el menú', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuApps .start-app[data-app="directory"]').click();
  await expect(windowOf(page, 'directory')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('configuración abre la ventana settings', async ({ page }) => {
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await page.locator('#startMenuSettings').click();
  await expect(windowOf(page, 'settings')).toBeVisible();
});

test('buscador: "titu" da un resultado y Enter abre TitulaTec; sin acentos', async ({ page }) => {
  await gotoDesktop(page);
  const search = page.locator('#taskbarSearch');
  await expect(search).toHaveAttribute('placeholder', 'Buscar aplicaciones…');
  await search.click();
  await search.fill('titu');
  await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
  await expect(page.locator('#startMenuResults [role="option"]')).toContainText('TitulaTec');
  await search.press('Enter');
  await expect(windowOf(page, 'titulatec')).toBeVisible();
  await expect(page.locator('#startMenu')).toBeHidden();

  // "Configuración" se encuentra aunque se escriba con mayúsculas y sin acento.
  await search.click();
  await search.fill('CONFIGURACION');
  await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
  await search.fill('zzzz');
  await expect(page.locator('#startMenuEmpty')).toBeVisible();
});

test('buscador: flechas mueven la selección y Esc cierra', async ({ page }) => {
  await gotoDesktop(page);
  const search = page.locator('#taskbarSearch');
  await search.click();
  await search.fill('e'); // varias coincidencias
  const opts = page.locator('#startMenuResults [role="option"]');
  expect(await opts.count()).toBeGreaterThan(1);
  await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');
  await search.press('ArrowDown');
  await expect(opts.nth(1)).toHaveAttribute('aria-selected', 'true');
  await search.press('ArrowUp');
  await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');
  await search.press('Escape');
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('Ctrl+K enfoca el buscador y abre el modo búsqueda; clic fuera cierra', async ({ page }) => {
  await gotoDesktop(page);
  await page.keyboard.press('Control+k');
  await expect(page.locator('#taskbarSearch')).toBeFocused();
  await expect(page.locator('#startMenu')).toBeVisible();
  await expect(page.locator('#startMenuSearch')).toBeVisible();
  await page.mouse.click(300, 200);
  await expect(page.locator('#startMenu')).toBeHidden();
});

test('cerrar sesión: POST al logout, limpia sesión y va a /itcj/login', async ({ page }) => {
  let called = 0;
  // No invalidar el JWT compartido de la suite.
  await page.route('**/api/core/v2/auth/logout', (route) => {
    called += 1;
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' });
  });
  // La cookie sigue viva (logout simulado) y el /itcj/login real redirigiría de vuelta al
  // escritorio: se sirve una página vacía del mismo origen para poder leer su sessionStorage.
  await page.route(/\/itcj\/login(\?|$)/, (route) => {
    if (!route.request().isNavigationRequest()) return route.continue();
    return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>login</title>' });
  });
  await gotoDesktop(page);

  // Con una ventana abierta la sesión del escritorio queda guardada.
  const sessionKey = 'itcj.desktop.session.v1:' + await page.evaluate(() => window.ItcjDesktop.user.id);
  await page.evaluate(() => window.ItcjDesktop.wm.open('directory'));
  await expect(windowOf(page, 'directory')).toBeVisible();
  await page.waitForFunction((k) => !!sessionStorage.getItem(k), sessionKey);

  await page.locator('.start-button').click();
  await Promise.all([
    page.waitForRequest((r) => r.isNavigationRequest() && new URL(r.url()).pathname === '/itcj/login'),
    page.locator('#startMenuLogout').click(),
  ]);
  expect(called).toBe(1);
  await page.waitForURL(/\/itcj\/login$/);
  expect(await page.evaluate((k) => sessionStorage.getItem(k), sessionKey)).toBeNull();
});

test('captura del menú abierto', async ({ page }) => {
  test.skip(!CAPTURE, 'solo con E2E_CAPTURE=1');
  await gotoDesktop(page);
  await page.locator('.start-button').click();
  await expect(page.locator('#startMenu')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, 'desktop-start-menu.png') });
});

test.describe('barra estrecha (900×700): la búsqueda se escribe en el menú de inicio', () => {
  test.use({ viewport: { width: 900, height: 700 } });

  test('clic en la lupa: campo visible arriba del menú y con foco; «help» se ve; ↓ + Enter abre la app', async ({ page }) => {
    await gotoDesktop(page);
    const field = page.locator('#startMenuSearchInput');
    const opts = page.locator('#startMenuResults [role="option"]');
    await expect(field).toBeHidden();

    await page.locator('.taskbar-search').click();
    await expect(page.locator('#startMenu')).toBeVisible();
    await expect(page.locator('#startMenuSearch')).toBeVisible();
    await expect(field).toBeVisible();
    await expect(field).toBeFocused();
    await expect(field).toHaveAttribute('aria-label', 'Buscar aplicaciones');
    await expect(field).toHaveAttribute('aria-controls', 'startMenuResults');

    await page.keyboard.type('help');
    await expect(field).toHaveValue('help');
    const look = await field.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const menu = document.getElementById('startMenu').getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + 20, r.top + r.height / 2);
      return {
        width: r.width,
        opacity: getComputedStyle(el).opacity,
        visibility: getComputedStyle(el).visibility,
        // Arriba del menú: antes que la lista de resultados.
        atTop: r.top - menu.top < 40 && r.bottom <= document.getElementById('startMenuResults').getBoundingClientRect().top,
        onTop: hit === el,
      };
    });
    expect(look.width).toBeGreaterThan(100);
    expect(look.opacity).toBe('1');
    expect(look.visibility).toBe('visible');
    expect(look.atTop).toBe(true);
    expect(look.onTop).toBe(true);
    await expect(opts).toHaveCount(1);
    await expect(opts.first()).toContainText('Help Desk');
    await expect(field).toHaveAttribute('aria-activedescendant', 'startResult-helpdesk');
    if (CAPTURE) {
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(SHOTS, 'temas', 'buscador-estrecho.png') });
    }

    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(windowOf(page, 'helpdesk')).toBeVisible();
    await expect(page.locator('#startMenu')).toBeHidden();
    await expect(field).toHaveValue('');
  });

  test('Ctrl+K y teclear con Inicio enfocado usan el campo del menú; Esc cierra; una sola consulta', async ({ page }) => {
    await gotoDesktop(page);
    const field = page.locator('#startMenuSearchInput');
    const bar = page.locator('#taskbarSearch');
    const opts = page.locator('#startMenuResults [role="option"]');

    await page.keyboard.press('Control+k');
    await expect(page.locator('#startMenuSearch')).toBeVisible();
    await expect(field).toBeVisible();
    await expect(field).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('#startMenu')).toBeHidden();
    await expect(page.locator('.start-button')).toBeFocused();

    // Con Inicio enfocado, una tecla imprimible abre la búsqueda con esa letra.
    await page.keyboard.type('ti');
    await expect(field).toBeFocused();
    await expect(field).toHaveValue('ti');
    await expect(opts).toHaveCount(1);
    await expect(opts.first()).toContainText('TitulaTec');
    await expect(bar).toHaveValue('ti');   // los dos campos reflejan la misma consulta

    // Mismo filtro: mayúsculas y sin acento; flechas mueven la selección.
    await page.keyboard.press('Control+a');
    await page.keyboard.type('CONFIGURACION');
    await expect(opts).toHaveCount(1);
    await field.fill('e');
    expect(await opts.count()).toBeGreaterThan(1);
    await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowDown');
    await expect(opts.nth(1)).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowUp');
    await expect(opts.nth(0)).toHaveAttribute('aria-selected', 'true');

    // Al ensanchar la ventana con la búsqueda abierta, sigue en el campo de la barra.
    await page.setViewportSize({ width: 1366, height: 768 });
    await expect(field).toBeHidden();
    await expect(bar).toBeFocused();
    await expect(bar).toHaveValue('e');
    await page.keyboard.press('Escape');
    await expect(page.locator('#startMenu')).toBeHidden();
    await expect(bar).toHaveValue('');
  });

  test('foco en el campo colapsado de la barra (Tab): lo tecleado va al campo del menú', async ({ page }) => {
    await gotoDesktop(page);
    await page.locator('.start-button').focus();
    await page.keyboard.press('Tab');
    const field = page.locator('#startMenuSearchInput');
    await expect(field).toBeFocused();
    await page.keyboard.type('ext');
    await expect(field).toHaveValue('ext');
    await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
    await expect(page.locator('#startMenuResults [role="option"]')).toContainText('Extensiones');
  });
});

test.describe('barra ancha (1366×768)', () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test('se usa el campo de la barra y el del menú no aparece', async ({ page }) => {
    await gotoDesktop(page);
    const bar = page.locator('#taskbarSearch');
    await bar.click();
    await expect(page.locator('#startMenuSearch')).toBeVisible();
    await expect(bar).toBeFocused();
    await expect(page.locator('#startMenuSearchInput')).toBeHidden();
    await page.keyboard.type('help');
    await expect(bar).toHaveValue('help');
    await expect(page.locator('#startMenuResults [role="option"]')).toHaveCount(1);
    await expect(page.locator('#startMenuSearchInput')).toBeHidden();
    await page.keyboard.press('Escape');
    await page.keyboard.press('Control+k');
    await expect(bar).toBeFocused();
    await expect(page.locator('#startMenuSearchInput')).toBeHidden();
  });
});

test('la bandeja no pisa el centro de la barra de 700 a 1920 px, con y sin un botón extra', async ({ page }) => {
  test.setTimeout(90_000);
  await gotoDesktop(page);
  const widths = [];
  for (let w = 700; w <= 1920; w += 10) widths.push(w);
  widths.push(759, 760, 761, 762, 775, 790, 795, 805, 815, 959, 961, 1099, 1101, 1366, 1536, 1600);

  for (const extra of [false, true]) {
    // Botón extra de 40 px al inicio de la bandeja (como el del tema Mundial).
    await page.evaluate((on) => {
      const tray = document.querySelector('.system-tray');
      document.getElementById('e2e-extra-tray-btn')?.remove();
      if (!on) return;
      const b = document.createElement('button');
      b.type = 'button';
      b.id = 'e2e-extra-tray-btn';
      b.className = 'tray-btn system-icon';
      tray.insertBefore(b, tray.firstChild);
    }, extra);
    const bad = [];
    for (const w of widths) {
      await page.setViewportSize({ width: w, height: 720 });
      const m = await page.evaluate(() => {
        const center = document.querySelector('.taskbar-center');
        const tray = document.querySelector('.system-tray').getBoundingClientRect();
        const right = Math.max(center.getBoundingClientRect().right,
          ...Array.from(center.querySelectorAll('*')).map((el) => el.getBoundingClientRect().right));
        return { gap: tray.left - right, out: tray.right - window.innerWidth };
      });
      if (m.gap < 0 || m.out > 0.5) bad.push(`${w}px: hueco ${m.gap.toFixed(1)}, fuera ${m.out.toFixed(1)}`);
    }
    expect(bad, extra ? 'con botón extra' : 'sin botón extra').toEqual([]);
  }
});

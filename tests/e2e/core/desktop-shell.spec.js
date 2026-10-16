// @ts-check
/**
 * Shell del escritorio (/itcj/dashboard) — Task 2 del rediseño del escritorio.
 *
 * Carga limpia (sin splash en red normal; splash y luego escritorio en red
 * lenta), tiles en filas, ventanas desde la barra y desde los iconos, z-order,
 * minimizar/restaurar por la barra, regresión B1 (scrollIntoView dentro de la
 * app no mueve la ventana), `openUrl` externa y robustez con un iframe de otro
 * origen.
 *
 * Capturas: `E2E_CAPTURE=1 npx playwright test core/desktop-shell.spec.js`
 * escribe desktop-shell.png y desktop-two-windows.png en .playwright-mcp/images/core/.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SHOTS = path.join(__dirname, '..', '..', '..', '.playwright-mcp', 'images', 'core');
const CAPTURE = !!process.env.E2E_CAPTURE;

test.beforeEach(async ({ page }) => {
  // El tour automático taparía los clics.
  // try: el init script corre también en los iframes, y uno `data:` no tiene storage.
  await page.addInitScript(() => {
    try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* iframe sin storage */ }
  });
});

/** Excepciones no atrapadas de la página y diálogos nativos (prohibidos). */
function trackErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('dialog', (d) => {
    errors.push(`diálogo nativo: ${d.type()} ${d.message()}`);
    d.dismiss().catch(() => {});
  });
  return errors;
}

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

function windowOf(page, key) {
  return page.locator(`.app-window[data-app-id="${key}"]`);
}

function taskbarBtn(page, key) {
  return page.locator(`#taskbarApps .taskbar-app[data-app="${key}"]`);
}

async function zIndexOf(page, key) {
  return page.evaluate((k) => Number(document.querySelector(`.app-window[data-app-id="${k}"]`).style.zIndex), key);
}

async function frameMatching(page, re) {
  await expect.poll(() => page.frames().some((f) => re.test(f.url())), { timeout: 15_000 }).toBe(true);
  return page.frames().find((f) => re.test(f.url()));
}

test('(a) carga sin splash en red normal y los tiles salen en una fila', async ({ page }) => {
  const errors = trackErrors(page);
  // Muestrea la opacidad del splash en cada cuadro hasta que el escritorio esté listo.
  await page.addInitScript(() => {
    // @ts-ignore
    window.__splashMax = 0;
    const tick = () => {
      const html = document.documentElement;
      const el = document.getElementById('desktop-splash');
      if (html.classList.contains('desktop-ready')) return;
      // @ts-ignore
      if (el) window.__splashMax = Math.max(window.__splashMax, parseFloat(getComputedStyle(el).opacity) || 0);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  await gotoDesktop(page);

  // @ts-ignore
  expect(await page.evaluate(() => window.__splashMax)).toBe(0);
  // La animación de entrada quedó pausada antes de empezar: el splash nunca se pintó.
  expect(await page.evaluate(() => getComputedStyle(document.getElementById('desktop-splash')).opacity)).toBe('0');
  await expect(page.locator('#desktop-splash')).toBeHidden();

  const tiles = page.locator('#desktop-grid > .desktop-icon[data-app]');
  await expect(tiles).toHaveCount(6);
  expect(await tiles.evaluateAll((els) => els.map((e) => e.getAttribute('data-app'))))
    .toEqual(['papelera', 'agendatec', 'helpdesk', 'maint', 'directory', 'titulatec']);
  const tops = await tiles.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(new Set(tops).size, `tops: ${tops}`).toBe(1);
  // Imágenes optimizadas cargadas (las del servidor, no reacomodadas por JS).
  const loaded = await page.locator('#desktop-grid img').evaluateAll((imgs) => imgs.every((i) => i.complete && i.naturalWidth > 0));
  expect(loaded).toBe(true);
  await expect(page.locator('.desktop-background')).toHaveClass(/is-loaded/);

  if (CAPTURE) await page.screenshot({ path: path.join(SHOTS, 'desktop-shell.png') });
  expect(errors).toEqual([]);
});

test('(b) abrir Help Desk desde la barra', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const btn = taskbarBtn(page, 'helpdesk');
  await btn.click();

  const win = windowOf(page, 'helpdesk');
  await expect(win).toBeVisible();
  await expect(win).toHaveClass(/is-maximized/);
  await expect(win).toHaveClass(/is-active/);
  await expect(btn).toHaveClass(/is-open/);
  await expect(btn).toHaveClass(/is-active/);
  await expect(win.locator('.window-title-text')).toHaveText('Help Desk');
  expect(await page.evaluate(() => window.ItcjDesktop.wm.activeKey())).toBe('helpdesk');
  expect(errors).toEqual([]);
});

test('(c) icono abre Extensiones; la barra trae al frente, minimiza y restaura', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);

  // Doble clic en el icono (el escritorio está despejado).
  await page.locator('#desktop-grid .desktop-icon[data-app="directory"]').dblclick();
  const dir = windowOf(page, 'directory');
  await expect(dir).toBeVisible();
  await expect(dir).toHaveClass(/is-active/);

  // Help Desk por la barra: queda al frente.
  const hdBtn = taskbarBtn(page, 'helpdesk');
  const dirBtn = taskbarBtn(page, 'directory');
  await hdBtn.click();
  const hd = windowOf(page, 'helpdesk');
  await expect(hd).toHaveClass(/is-active/);
  await expect(dir).not.toHaveClass(/is-active/);
  await expect(dirBtn).toHaveClass(/is-open/);
  await expect(dirBtn).not.toHaveClass(/is-active/);

  // Clic en Extensiones (abierta, no al frente) → al frente.
  await dirBtn.click();
  await expect(dir).toHaveClass(/is-active/);
  expect(await zIndexOf(page, 'directory')).toBeGreaterThan(await zIndexOf(page, 'helpdesk'));

  // Clic en Help Desk (abierta, no al frente) → al frente.
  await hdBtn.click();
  await expect(hd).toHaveClass(/is-active/);
  await expect(hdBtn).toHaveClass(/is-active/);
  expect(await zIndexOf(page, 'helpdesk')).toBeGreaterThan(await zIndexOf(page, 'directory'));

  // Clic de nuevo (al frente) → minimiza; la siguiente visible pasa a activa.
  await hdBtn.click();
  await expect(hd).toHaveClass(/is-minimized/);
  await expect(hd).toBeHidden();
  await expect(dir).toHaveClass(/is-active/);
  await expect(hdBtn).toHaveClass(/is-open/);
  await expect(hdBtn).not.toHaveClass(/is-active/);

  // Clic otra vez → restaura y enfoca.
  await hdBtn.click();
  await expect(hd).not.toHaveClass(/is-minimized/);
  await expect(hd).toBeVisible();
  await expect(hd).toHaveClass(/is-active/);

  // Botón de la ventana: minimizar y cerrar.
  await hd.locator('.window-control.minimize').click();
  await expect(hd).toHaveClass(/is-minimized/);
  await dir.locator('.window-control.close').click();
  await expect(windowOf(page, 'directory')).toHaveCount(0);
  await expect(dirBtn).not.toHaveClass(/is-open/);
  expect(errors).toEqual([]);
});

test('(d) B1: scrollIntoView dentro de la app no mueve la ventana', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'helpdesk').click();
  const win = windowOf(page, 'helpdesk');
  await expect(win).toBeVisible();

  await page.evaluate(() => window.desktop.openUrl('/help-desk/admin/assign-tickets'));
  await expect(win.locator('.window-url')).toHaveText('/help-desk/admin/assign-tickets');
  const frame = await frameMatching(page, /\/help-desk\/admin\/assign-tickets/);
  await frame.waitForLoadState('load');
  await expect(win).not.toHaveClass(/is-loading/);
  // Con caché la app carga antes de que termine la animación de apertura (160 ms).
  await win.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));

  const before = await win.locator('.window-titlebar').boundingBox();
  await frame.evaluate(() => {
    const visibles = Array.from(document.querySelectorAll('body *')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
    });
    let lowest = visibles[0];
    let max = -Infinity;
    for (const e of visibles) {
      const bottom = e.getBoundingClientRect().bottom + window.scrollY;
      if (bottom >= max) { max = bottom; lowest = e; }
    }
    lowest.scrollIntoView({ block: 'start' });
  });
  await page.waitForTimeout(700);   // por si la app usa scroll-behavior: smooth

  const after = await win.locator('.window-titlebar').boundingBox();
  expect(after.y).toBe(before.y);
  const scrolls = await page.evaluate(() => {
    const w = document.querySelector('.app-window[data-app-id="helpdesk"]');
    return {
      ventana: w.scrollTop,
      contenido: w.querySelector('.window-content').scrollTop,
      area: document.getElementById('windows-container').scrollTop,
      escritorio: document.getElementById('desktop').scrollTop,
      documento: document.scrollingElement.scrollTop,
    };
  });
  expect(scrolls).toEqual({ ventana: 0, contenido: 0, area: 0, escritorio: 0, documento: 0 });
  expect(errors).toEqual([]);
});

test('(e) openUrl externa no abre ventana ni lanza', async ({ page, context }) => {
  const errors = trackErrors(page);
  await context.route('https://example.org/**', (route) => route.abort());
  const popups = [];
  context.on('page', (p) => popups.push(p));
  await gotoDesktop(page);

  const result = await page.evaluate(() => {
    try {
      window.desktop.openUrl('https://example.org/x');
      window.desktop.openUrl('javascript:alert(1)');
      window.desktop.openUrl('//evil.example/x');
      return 'ok';
    } catch (e) {
      return String(e);
    }
  });
  expect(result).toBe('ok');
  await page.waitForTimeout(300);
  await expect(page.locator('.app-window')).toHaveCount(0);
  for (const p of popups) await p.close().catch(() => {});
  expect(errors).toEqual([]);
});

test('(f) red lenta: el splash llega a verse y luego el escritorio queda listo', async ({ page, context }) => {
  test.setTimeout(90_000);
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 150,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
  });

  await page.goto('/itcj/dashboard', { waitUntil: 'commit', timeout: 60_000 });
  await page.waitForFunction(() => {
    const el = document.getElementById('desktop-splash');
    return !!el && !document.documentElement.classList.contains('desktop-ready')
      && parseFloat(getComputedStyle(el).opacity) > 0.5;
  }, null, { timeout: 30_000, polling: 'raf' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'), null, { timeout: 30_000 });
  await expect(page.locator('#desktop-splash')).toBeHidden({ timeout: 3_000 });
  await expect(page.locator('#desktop-grid .desktop-icon[data-app="helpdesk"]')).toBeVisible();
});

test('(g) iframe de otro origen: enfocar, arrastrar y cerrar sin errores', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'maint').click();
  const win = windowOf(page, 'maint');
  await expect(win).toBeVisible();

  // data: = origen opaco; cualquier acceso a contentWindow/contentDocument lanza.
  await page.evaluate(() => {
    document.querySelector('.app-window[data-app-id="maint"] iframe').src = 'data:text/html,<p>otro origen</p>';
  });
  await page.waitForTimeout(1500);   // deja correr el sondeo de URL (1 s)

  // Arrastrar la maximizada la restaura bajo el cursor.
  const tb = await win.locator('.window-titlebar').boundingBox();
  await page.mouse.move(tb.x + 300, tb.y + 18);
  await page.mouse.down();
  await page.mouse.move(tb.x + 360, tb.y + 140, { steps: 8 });
  await page.mouse.up();
  await expect(win).not.toHaveClass(/is-maximized/);
  expect(await page.evaluate(() => window.ItcjDesktop.wm.getState('maint'))).toBe('normal');
  await expect(page.locator('body')).not.toHaveClass(/desktop-dragging/);

  // Doble clic en la barra de título: maximiza y vuelve.
  await win.locator('.window-title-text').dblclick();
  await expect(win).toHaveClass(/is-maximized/);
  await win.locator('.window-title-text').dblclick();
  await expect(win).not.toHaveClass(/is-maximized/);

  await win.locator('.window-control.reload').click();
  await win.locator('.window-control.close').click();
  await expect(windowOf(page, 'maint')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('(h) clic dentro de la app enfoca su ventana; dos ventanas lado a lado', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'helpdesk').click();
  await taskbarBtn(page, 'directory').click();
  const hd = windowOf(page, 'helpdesk');
  const dir = windowOf(page, 'directory');
  await expect(dir).toHaveClass(/is-active/);

  await page.evaluate(() => {
    window.ItcjDesktop.wm.snap('helpdesk', 'left');
    window.ItcjDesktop.wm.snap('directory', 'right');
  });
  await expect(hd).toHaveClass(/is-snap-left/);
  await expect(dir).toHaveClass(/is-snap-right/);
  await expect(hd).not.toHaveClass(/is-loading/, { timeout: 15_000 });
  await expect(dir).not.toHaveClass(/is-loading/, { timeout: 15_000 });

  // Clic dentro del contenido de Help Desk (inactiva) → pasa al frente.
  const box = await hd.locator('.window-content').boundingBox();
  await page.mouse.click(box.x + box.width - 12, box.y + box.height - 12);
  await expect(hd).toHaveClass(/is-active/);
  await expect(dir).not.toHaveClass(/is-active/);
  await expect(taskbarBtn(page, 'helpdesk')).toHaveClass(/is-active/);

  if (CAPTURE) {
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOTS, 'desktop-two-windows.png') });
  }
  expect(errors).toEqual([]);
});

test('(i) perfil y configuración: botón dinámico en la barra mientras están abiertos', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await page.evaluate(() => window.desktop.openProfile('notifications'));
  const win = windowOf(page, 'profile');
  await expect(win).toBeVisible();
  await expect(win.locator('.window-url')).toHaveText('/itcj/profile?tab=notifications');
  const btn = page.locator('#taskbarApps .taskbar-app[data-app="profile"][data-dynamic="1"]');
  await expect(btn).toHaveClass(/is-active/);
  await btn.click();
  await expect(win).toHaveClass(/is-minimized/);
  await page.evaluate(() => window.ItcjDesktop.wm.close('profile'));
  await expect(btn).toHaveCount(0);
  expect(errors).toEqual([]);
});

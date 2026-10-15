// @ts-check
/**
 * Ventanas avanzadas del escritorio (/itcj/dashboard) — Task 3 del rediseño.
 *
 * Redimensión por manijas (mínimo 420×300), Aero Snap al arrastrar (vista
 * previa + acople), doble clic en la barra de título, geometría recordada por
 * app, restauración de sesión tras recargar (sin animación y antes de quitar el
 * splash), sesión basura o con URLs malas, storage bloqueado, viewport < 900 px,
 * achicar el navegador con ventanas normales/acopladas, manijas por fuera de
 * la ventana y cerrar una ventana a media operación (escudo limpio).
 *
 * Capturas: `E2E_CAPTURE=1 npx playwright test core/desktop-windows.spec.js -g "\(b\)|\(k\)"`
 * escribe desktop-snap.png y final-window-{normal,maximized,snapped}.png en
 * .playwright-mcp/images/core/.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const SHOTS = path.join(__dirname, '..', '..', '..', '.playwright-mcp', 'images', 'core');
const CAPTURE = !!process.env.E2E_CAPTURE;
const GEOM_KEY = 'itcj.desktop.geom.v1';
const SESSION_PREFIX = 'itcj.desktop.session.v1:';

test.beforeEach(async ({ page }) => {
  // El tour automático taparía los clics (try: el init script corre también en iframes).
  await page.addInitScript(() => {
    try { localStorage.setItem('dashboard_tutorial_completed', 'true'); } catch (e) { /* sin storage */ }
  });
});

/**
 * Excepciones, diálogos nativos (prohibidos) y errores de consola del escritorio.
 * La consola se acota por origen del mensaje (el documento del escritorio, los
 * estáticos del core o sin origen): un error propio de una app embebida no es
 * de este spec. Playwright no expone el frame de un ConsoleMessage.
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

async function gotoDesktop(page) {
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

async function reloadDesktop(page) {
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

const windowOf = (page, key) => page.locator(`.app-window[data-app-id="${key}"]`);
const taskbarBtn = (page, key) => page.locator(`#taskbarApps .taskbar-app[data-app="${key}"]`);
const wmState = (page, key) => page.evaluate((k) => window.ItcjDesktop.wm.getState(k), key);

/** Espera a que terminen transiciones/animaciones de la ventana (abrir, maximizar, acoplar). */
async function settle(win) {
  await expect(win).not.toHaveClass(/is-transitioning/);
  await win.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished.catch(() => null))));
}

async function workArea(page) {
  return page.evaluate(() => {
    const r = document.getElementById('windows-container').getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  });
}

async function visibleHandles(win) {
  return win.locator('.window-resize').evaluateAll((els) => els.filter((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).display !== 'none';
  }).length);
}

/** Abre `key` desde la barra y la deja en estado normal (nace maximizada sin geometría). */
async function openNormal(page, key) {
  await taskbarBtn(page, key).click();
  const win = windowOf(page, key);
  await expect(win).toHaveClass(/is-maximized/);
  await settle(win);
  await win.locator('.window-control.maximize').click();
  await expect(win).not.toHaveClass(/is-maximized/);
  await settle(win);
  return win;
}

/** Arrastra de (x, y) a (x + dx, y + dy) con el ratón. */
async function drag(page, x, y, dx, dy, steps = 10) {
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps });
  await page.mouse.up();
}

const near = (a, b, tol = 2) => Math.abs(a - b) <= tol;

test('(a) restaurar y redimensionar por la esquina se; mínimo 420×300', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'helpdesk').click();
  const win = windowOf(page, 'helpdesk');
  const maxBtn = win.locator('.window-control.maximize');
  await expect(win).toHaveClass(/is-maximized/);
  await settle(win);

  // Maximizada: 8 manijas en el DOM pero ninguna visible; el botón dice "Restaurar".
  await expect(win.locator('.window-resize')).toHaveCount(8);
  expect(await visibleHandles(win)).toBe(0);
  await expect(maxBtn).toHaveAttribute('title', 'Restaurar');

  await maxBtn.click();
  await expect(win).not.toHaveClass(/is-maximized/);
  await settle(win);
  expect(await visibleHandles(win)).toBe(8);
  await expect(maxBtn).toHaveAttribute('title', 'Maximizar');

  const before = await win.boundingBox();
  const se = await win.locator('.window-resize[data-dir="se"]').boundingBox();
  const sx = se.x + se.width / 2;
  const sy = se.y + se.height / 2;
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + 120, sy + 80, { steps: 8 });
  // Escudo activo durante la redimensión: el iframe no se traga el puntero.
  await expect(page.locator('body')).toHaveClass(/desktop-dragging/);
  await page.mouse.up();
  await expect(page.locator('body')).not.toHaveClass(/desktop-dragging/);

  const after = await win.boundingBox();
  expect(near(after.width - before.width, 120), `ancho ${before.width} → ${after.width}`).toBe(true);
  expect(near(after.height - before.height, 80), `alto ${before.height} → ${after.height}`).toBe(true);
  expect(near(after.x, before.x) && near(after.y, before.y)).toBe(true);
  expect(await wmState(page, 'helpdesk')).toBe('normal');

  // Por la esquina nw hasta pasarse de la opuesta: se queda en el mínimo, anclada abajo a la derecha.
  const nw = await win.locator('.window-resize[data-dir="nw"]').boundingBox();
  await drag(page, nw.x + nw.width / 2, nw.y + nw.height / 2, after.width + 40, after.height + 40);
  const min = await win.boundingBox();
  expect(near(min.width, 420, 1), `ancho mínimo ${min.width}`).toBe(true);
  expect(near(min.height, 300, 1), `alto mínimo ${min.height}`).toBe(true);
  expect(near(min.x + min.width, after.x + after.width)).toBe(true);
  expect(near(min.y + min.height, after.y + after.height)).toBe(true);
  expect(errors).toEqual([]);
});

test('(a2) manijas por fuera: no tapan la barra de scroll del iframe ni el borde de la barra; "ne" sirve', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  // La ventana no recorta (las manijas viven fuera); el contenido sí (B1).
  expect(await win.evaluate((el) => getComputedStyle(el).overflow)).toBe('visible');
  expect(await win.locator('.window-content').evaluate((el) => getComputedStyle(el).overflowY)).toMatch(/clip|hidden/);

  const box = await win.boundingBox();
  const hit = (x, y) => page.evaluate(([px, py]) => {
    const el = document.elementFromPoint(px, py);
    if (!el) return null;
    const handle = el.closest('.window-resize');
    if (handle) return 'resize-' + handle.dataset.dir;
    if (el.tagName === 'IFRAME') return 'iframe';
    if (el.closest('.window-titlebar')) return 'titlebar';
    return el.tagName.toLowerCase();
  }, [x, y]);
  // Borde derecho por dentro (donde va la barra de scroll de la app): el iframe, no una manija.
  expect(await hit(box.x + box.width - 3, box.y + box.height / 2)).toBe('iframe');
  // Borde inferior por dentro: el iframe.
  expect(await hit(box.x + box.width / 2, box.y + box.height - 3)).toBe('iframe');
  // Borde superior de la barra de título: la barra.
  expect(await hit(box.x + box.width / 2, box.y + 1)).toBe('titlebar');
  // Por fuera: las manijas.
  expect(await hit(box.x + box.width + 3, box.y + box.height / 2)).toBe('resize-e');
  expect(await hit(box.x + box.width / 2, box.y - 3)).toBe('resize-n');
  expect(await hit(box.x + box.width + 3, box.y - 3)).toBe('resize-ne');

  // "ne" redimensiona: más ancha a la derecha y más alta hacia arriba, esquina so fija.
  await drag(page, box.x + box.width + 3, box.y - 3, 40, -30, 8);
  const after = await win.boundingBox();
  expect(near(after.width, box.width + 40), `ancho ${box.width} → ${after.width}`).toBe(true);
  expect(near(after.height, box.height + 30), `alto ${box.height} → ${after.height}`).toBe(true);
  expect(near(after.x, box.x) && near(after.y + after.height, box.y + box.height)).toBe(true);
  expect(errors).toEqual([]);
});

test('(b) arrastrar al borde izquierdo acopla a la mitad; arriba maximiza; despegar mantiene la proporción', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  const area = await workArea(page);
  const normal = await win.boundingBox();

  // Arrastre al borde izquierdo: vista previa de media pantalla mientras se arrastra.
  const gx = normal.x + 220;
  const gy = normal.y + 18;
  await page.mouse.move(gx, gy);
  await page.mouse.down();
  await page.mouse.move(1, gy + 60, { steps: 12 });
  const preview = page.locator('#snapPreview');
  await expect(preview).toHaveClass(/is-visible/);
  await expect(preview).toHaveAttribute('data-side', 'left');
  await page.waitForTimeout(250);   // termina la transición de entrada de la vista previa
  const pbox = await preview.boundingBox();
  expect(pbox.x).toBeLessThan(area.x + 20);
  expect(near(pbox.width, area.w / 2, 24), `vista previa ${pbox.width}`).toBe(true);
  if (CAPTURE) await page.screenshot({ path: path.join(SHOTS, 'desktop-snap.png') });
  await page.mouse.up();

  await expect(win).toHaveClass(/is-snap-left/);
  await settle(win);
  await expect(preview).not.toHaveClass(/is-visible/);
  const snapped = await win.boundingBox();
  expect(near(snapped.x, area.x)).toBe(true);
  expect(near(snapped.width, area.w / 2), `ancho acoplada ${snapped.width} vs ${area.w / 2}`).toBe(true);
  expect(near(snapped.height, area.h)).toBe(true);
  // Ruling 4.1: acoplada ofrece "Maximizar" con el cuadrado (no el glifo de restaurar).
  const maxBtn = win.locator('.window-control.maximize');
  await expect(maxBtn).toHaveAttribute('title', 'Maximizar');
  await expect(maxBtn.locator('.ico-square')).toBeVisible();
  await expect(maxBtn.locator('.ico-restore')).toBeHidden();
  expect(await wmState(page, 'directory')).toBe('snap-left');

  // Despegar: vuelve a su tamaño normal y el cursor queda en la misma proporción de la barra.
  const ratio = 0.25;
  const sx = snapped.x + snapped.width * ratio;
  await drag(page, sx, snapped.y + 18, 700 - sx, 200);
  await expect(win).not.toHaveClass(/is-snap-left/);
  const detached = await win.boundingBox();
  expect(await wmState(page, 'directory')).toBe('normal');
  expect(near(detached.width, normal.width)).toBe(true);
  expect(near(detached.height, normal.height)).toBe(true);
  const newRatio = (700 - detached.x) / detached.width;
  expect(Math.abs(newRatio - ratio), `proporción ${newRatio.toFixed(3)}`).toBeLessThan(0.02);

  // Borde superior: vista previa de pantalla completa → maximizada al soltar.
  const tb = await win.boundingBox();
  await page.mouse.move(tb.x + 200, tb.y + 18);
  await page.mouse.down();
  await page.mouse.move(tb.x + 260, 1, { steps: 10 });
  await expect(preview).toHaveAttribute('data-side', 'max');
  await page.mouse.up();
  await expect(win).toHaveClass(/is-maximized/);
  await expect(preview).not.toHaveClass(/is-visible/);

  // Redimensionar una acoplada (borde interior): pasa a normal en su lugar y crece.
  await page.evaluate(() => window.ItcjDesktop.wm.snap('directory', 'right'));
  await expect(win).toHaveClass(/is-snap-right/);
  await settle(win);
  const right = await win.boundingBox();
  const w = await win.locator('.window-resize[data-dir="w"]').boundingBox();
  await drag(page, w.x + w.width / 2, w.y + w.height / 2, -60, 0);
  expect(await wmState(page, 'directory')).toBe('normal');
  const grown = await win.boundingBox();
  expect(near(grown.x, right.x - 60) && near(grown.width, right.width + 60)).toBe(true);
  expect(near(grown.x + grown.width, area.x + area.w)).toBe(true);
  expect(errors).toEqual([]);
});

test('(c) doble clic en la barra de título maximiza y vuelve al mismo rect', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  const before = await win.boundingBox();
  await win.locator('.window-title-text').dblclick();
  await expect(win).toHaveClass(/is-maximized/);
  await settle(win);
  await win.locator('.window-title-text').dblclick();
  await expect(win).not.toHaveClass(/is-maximized/);
  await settle(win);
  const after = await win.boundingBox();
  expect(near(after.x, before.x) && near(after.y, before.y) && near(after.width, before.width) && near(after.height, before.height)).toBe(true);
  expect(errors).toEqual([]);
});

test('(d) geometría recordada: cerrar y reabrir la app conserva el rect', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  const box = await win.boundingBox();
  await drag(page, box.x + 200, box.y + 18, -120, 50);
  const se = await win.locator('.window-resize[data-dir="se"]').boundingBox();
  await drag(page, se.x + se.width / 2, se.y + se.height / 2, -90, -60);
  const rect1 = await win.boundingBox();
  expect(near(rect1.width, box.width - 90)).toBe(true);

  const saved = await page.evaluate((k) => JSON.parse(localStorage.getItem(k) || '{}'), GEOM_KEY);
  expect(saved.directory, 'geometría guardada en localStorage').toBeTruthy();

  await win.locator('.window-control.close').click();
  await expect(windowOf(page, 'directory')).toHaveCount(0);
  await taskbarBtn(page, 'directory').click();
  const again = windowOf(page, 'directory');
  await expect(again).toBeVisible();
  await settle(again);
  expect(await wmState(page, 'directory')).toBe('normal');
  await expect(again).not.toHaveClass(/is-maximized/);
  const rect2 = await again.boundingBox();
  for (const k of ['x', 'y', 'width', 'height']) {
    expect(near(rect2[k], rect1[k]), `${k}: ${rect1[k]} → ${rect2[k]}`).toBe(true);
  }
  expect(errors).toEqual([]);
});

test('(e) restaurar sesión tras recargar: mismas ventanas, estados y URL, sin animación', async ({ page }) => {
  const errors = trackErrors(page);
  // Fotografía de las ventanas en el instante en que el escritorio queda listo (se quita el splash).
  await page.addInitScript(() => {
    if (window.top !== window) return;
    // Se observa `document` (subárbol): al correr el init script aún no existe <html>.
    new MutationObserver((muts, obs) => {
      const html = document.documentElement;
      if (!html || !html.classList.contains('desktop-ready')) return;
      obs.disconnect();
      // @ts-ignore
      window.__atReady = Array.from(document.querySelectorAll('.app-window[data-app-id]'))
        .map((el) => ({ key: el.dataset.appId, anims: el.getAnimations().length }));
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ['class'] });
  });
  await gotoDesktop(page);

  // Help Desk acoplada a la izquierda y navegada a otra ruta.
  await taskbarBtn(page, 'helpdesk').click();
  const hd = windowOf(page, 'helpdesk');
  await expect(hd).toBeVisible();
  await page.evaluate(() => window.desktop.openUrl('/help-desk/admin/assign-tickets'));
  await expect(hd.locator('.window-url')).toHaveText('/help-desk/admin/assign-tickets');
  await page.evaluate(() => window.ItcjDesktop.wm.snap('helpdesk', 'left'));
  await expect(hd).toHaveClass(/is-snap-left/);

  // Extensiones en normal, movida, y luego minimizada.
  const dir = await openNormal(page, 'directory');
  const dbox = await dir.boundingBox();
  await drag(page, dbox.x + 200, dbox.y + 18, 60, 30);
  const dirRect = await dir.boundingBox();
  await dir.locator('.window-control.minimize').click();
  await expect(dir).toHaveClass(/is-minimized/);
  await expect(hd).toHaveClass(/is-active/);

  const listBefore = await page.evaluate(() => window.ItcjDesktop.wm.list());
  expect(listBefore.map((w) => w.key)).toEqual(['helpdesk', 'directory']);

  await reloadDesktop(page);

  // Las ventanas ya estaban al quitar el splash y ninguna se estaba animando.
  // @ts-ignore
  const atReady = await page.evaluate(() => window.__atReady);
  expect(atReady).toEqual([{ key: 'helpdesk', anims: 0 }, { key: 'directory', anims: 0 }]);

  const listAfter = await page.evaluate(() => window.ItcjDesktop.wm.list());
  expect(listAfter.map((w) => [w.key, w.url, w.state])).toEqual(listBefore.map((w) => [w.key, w.url, w.state]));
  // (Extensiones redirige /directory → /directory/: se compara contra la foto de antes.)
  expect(listAfter.map((w) => [w.key, w.state])).toEqual([['helpdesk', 'snap-left'], ['directory', 'minimized']]);
  expect(listAfter[0].url).toBe('/help-desk/admin/assign-tickets');
  const hd2 = windowOf(page, 'helpdesk');
  await expect(hd2).toHaveClass(/is-snap-left/);
  await expect(hd2).toHaveClass(/is-active/);
  await expect(hd2.locator('.window-url')).toHaveText('/help-desk/admin/assign-tickets');
  expect(await hd2.locator('iframe').getAttribute('src')).toBe('/help-desk/admin/assign-tickets');
  expect(await page.evaluate(() => window.ItcjDesktop.wm.activeKey())).toBe('helpdesk');
  await expect(taskbarBtn(page, 'directory')).toHaveClass(/is-open/);

  // La minimizada recuerda que estaba en normal y en qué rect.
  const dir2 = windowOf(page, 'directory');
  await expect(dir2).toHaveClass(/is-minimized/);
  await taskbarBtn(page, 'directory').click();
  await expect(dir2).not.toHaveClass(/is-minimized/);
  await settle(dir2);
  expect(await wmState(page, 'directory')).toBe('normal');
  const dirRect2 = await dir2.boundingBox();
  for (const k of ['x', 'y', 'width', 'height']) {
    expect(near(dirRect2[k], dirRect[k]), `${k}: ${dirRect[k]} → ${dirRect2[k]}`).toBe(true);
  }
  expect(errors).toEqual([]);
});

/** Siembra sessionStorage UNA vez (antes de que corran los scripts de la página) en el documento principal. */
async function seedOnce(page, key, value, tag) {
  await page.addInitScript(({ k, v, t }) => {
    if (window.top !== window) return;
    const flag = 'e2e-seed-' + t;
    if (sessionStorage.getItem(flag)) return;
    sessionStorage.setItem(flag, '1');
    sessionStorage.setItem(k, v);
  }, { k: key, v: value, t: tag });
}

test('(f) sesión basura o con URLs malas: arranca limpio e ignora solo lo malo', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const uid = await page.evaluate(() => window.ItcjDesktop.user.id);
  expect(uid).toBeTruthy();
  const key = SESSION_PREFIX + uid;

  // 1) JSON roto → sin ventanas, sin errores.
  await seedOnce(page, key, '{no json', 'roto');
  await reloadDesktop(page);
  await expect(page.locator('.app-window')).toHaveCount(0);
  await taskbarBtn(page, 'directory').click();   // el escritorio sigue usable
  await expect(windowOf(page, 'directory')).toBeVisible();
  expect(errors).toEqual([]);

  // 2) Entradas malas mezcladas con buenas.
  const entries = [
    { key: 'helpdesk', url: 'javascript:alert(1)', state: 'normal', z: 10 },
    { key: 'maint', url: 'https://evil.example/maint', state: 'maximized', z: 11 },
    { key: 'agendatec', url: '/help-desk/user', state: 'maximized', z: 12 },
    { key: 'noexiste', url: '/noexiste', state: 'maximized', z: 13 },
    { key: '__proto__', url: '/', state: 'maximized', z: 14 },
    'texto', null, 42, [],
    { key: 'directory', url: '/directory', state: 'normal', z: 15, rect: { x: 'a', y: null, w: -3, h: 1e9 } },
    { key: 'profile', url: '/itcj/profile?tab=info', state: 'minimized', base: 'normal', z: 16, rect: { x: 10, y: 10, w: 50, h: 60 } },
    { key: 'directory', url: '/directory/otra', state: 'maximized', z: 17 },
  ];
  await seedOnce(page, key, JSON.stringify(entries), 'mezcla');
  await reloadDesktop(page);
  await page.waitForTimeout(300);
  expect(await page.locator('.app-window[data-app-id]').evaluateAll((els) => els.map((e) => e.dataset.appId)))
    .toEqual(['directory', 'profile']);
  expect(await wmState(page, 'directory')).toBe('normal');
  expect(await wmState(page, 'profile')).toBe('minimized');
  expect(await page.evaluate(() => window.ItcjDesktop.wm.activeKey())).toBe('directory');
  await expect(windowOf(page, 'profile').locator('.window-url')).toHaveText('/itcj/profile?tab=info');
  // El rect basura no rompe la geometría: queda dentro del área útil.
  const area = await workArea(page);
  const dbox = await windowOf(page, 'directory').boundingBox();
  expect(dbox.width).toBeGreaterThanOrEqual(420);
  expect(dbox.x + dbox.width).toBeLessThanOrEqual(area.x + area.w + 1);
  expect(dbox.y).toBeGreaterThanOrEqual(area.y);
  expect(errors).toEqual([]);
});

test('(f2) storage bloqueado: el escritorio arranca y abre/cierra ventanas sin persistir', async ({ page }) => {
  const errors = trackErrors(page);
  await page.addInitScript(() => {
    if (window.top !== window) return;
    const blocked = () => { throw new DOMException('El acceso al almacenamiento está bloqueado', 'SecurityError'); };
    Object.defineProperty(window, 'sessionStorage', { configurable: true, get: blocked });
    Object.defineProperty(window, 'localStorage', { configurable: true, get: blocked });
  });
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  const box = await win.boundingBox();
  await drag(page, box.x + 200, box.y + 18, -50, 20);
  await win.locator('.window-control.close').click();
  await expect(windowOf(page, 'directory')).toHaveCount(0);
  // Sin storage no se recordó la geometría: vuelve a nacer maximizada.
  await taskbarBtn(page, 'directory').click();
  await expect(windowOf(page, 'directory')).toHaveClass(/is-maximized/);
  await reloadDesktop(page);
  await expect(page.locator('.app-window')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('(i) Ruling 4: navegación solo-hash sin barra de progreso; cerrar no re-arma la carga', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'directory').click();
  const win = windowOf(page, 'directory');
  await expect(win).not.toHaveClass(/is-loading/, { timeout: 15_000 });
  const url = await page.evaluate(() => window.ItcjDesktop.wm.list()[0].url);

  // Mismo documento, otro #hash: no hay `load`, así que tampoco barra de progreso.
  const ok = await page.evaluate((u) => window.ItcjDesktop.wm.navigate('directory', u.split('#')[0] + '#seccion'), url);
  expect(ok).toBe(true);
  expect(await win.evaluate((el) => el.classList.contains('is-loading'))).toBe(false);
  await page.waitForTimeout(400);
  await expect(win).not.toHaveClass(/is-loading/);
  expect(await page.evaluate(() => window.ItcjDesktop.wm.list()[0].url)).toMatch(/#seccion$/);

  // Una navegación completa sí la muestra (y se quita con el `load`).
  await page.evaluate(() => window.ItcjDesktop.wm.reload('directory'));
  await expect(win).not.toHaveClass(/is-loading/, { timeout: 15_000 });

  // Cerrar descarga el iframe (`pagehide`): no debe volver a marcar carga sobre el nodo suelto.
  await page.evaluate(() => {
    // @ts-ignore
    window.__closedWin = document.querySelector('.app-window[data-app-id="directory"]');
    window.ItcjDesktop.wm.close('directory', { animate: false });
  });
  await expect(windowOf(page, 'directory')).toHaveCount(0);
  await page.waitForTimeout(200);
  // @ts-ignore
  expect(await page.evaluate(() => window.__closedWin.classList.contains('is-loading'))).toBe(false);
  expect(errors).toEqual([]);
});

test('(g) viewport < 900 px: todas maximizadas y sin manijas', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const hd = await openNormal(page, 'helpdesk');
  await taskbarBtn(page, 'directory').click();
  const dir = windowOf(page, 'directory');
  await expect(dir).toBeVisible();
  await page.evaluate(() => window.ItcjDesktop.wm.snap('directory', 'right'));
  await expect(dir).toHaveClass(/is-snap-right/);

  await page.setViewportSize({ width: 800, height: 700 });
  await expect(hd).toHaveClass(/is-maximized/);
  await expect(dir).toHaveClass(/is-maximized/);
  expect(await visibleHandles(hd)).toBe(0);
  expect(await visibleHandles(dir)).toBe(0);
  // Ni el doble clic ni el arrastre la sacan de maximizada.
  await dir.locator('.window-title-text').dblclick();
  await expect(dir).toHaveClass(/is-maximized/);
  const tb = await dir.locator('.window-titlebar').boundingBox();
  await drag(page, tb.x + 200, tb.y + 18, 80, 120);
  await expect(dir).toHaveClass(/is-maximized/);
  // Abrir otra app en angosto también nace maximizada.
  await taskbarBtn(page, 'maint').click();
  await expect(windowOf(page, 'maint')).toHaveClass(/is-maximized/);
  expect(errors).toEqual([]);
});

test('(h) achicar el navegador: la ventana pegada a la derecha conserva la barra de título a la vista', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  await taskbarBtn(page, 'directory').click();
  await expect(windowOf(page, 'directory')).toBeVisible();
  await page.evaluate(() => window.ItcjDesktop.wm.snap('directory', 'left'));
  const win = await openNormal(page, 'helpdesk');
  const area = await workArea(page);
  const box = await win.boundingBox();
  // Pegada al borde derecho (agarre lejos del borde: no dispara el acople).
  await drag(page, box.x + 120, box.y + 18, area.x + area.w - (box.x + box.width), 0);
  const pinned = await win.boundingBox();
  expect(near(pinned.x + pinned.width, area.x + area.w), `derecha ${pinned.x + pinned.width}`).toBe(true);
  expect(await wmState(page, 'helpdesk')).toBe('normal');

  await page.setViewportSize({ width: 1100, height: 700 });
  const vw = 1100;
  await expect.poll(async () => {
    const t = await win.locator('.window-titlebar').boundingBox();
    return t.x >= 0 && t.x + t.width <= vw + 0.5 && t.y >= 0;
  }).toBe(true);
  const close = await win.locator('.window-control.close').boundingBox();
  expect(close.x + close.width).toBeLessThanOrEqual(vw + 0.5);
  expect(await wmState(page, 'helpdesk')).toBe('normal');
  // La acoplada se recalcula a la mitad del área nueva.
  const area2 = await workArea(page);
  const left = await windowOf(page, 'directory').boundingBox();
  expect(near(left.width, area2.w / 2)).toBe(true);

  // Más bajo: la barra de título sigue dentro del área útil.
  await page.setViewportSize({ width: 1000, height: 420 });
  await expect.poll(async () => {
    const t = await win.locator('.window-titlebar').boundingBox();
    const a = await workArea(page);
    return t.y >= a.y && t.y + t.height <= a.y + a.h + 0.5 && t.x + t.width <= 1000 + 0.5;
  }).toBe(true);
  expect(errors).toEqual([]);
});

test('(j) cerrar la ventana a media operación no deja el escudo de arrastre ni de redimensión', async ({ page }) => {
  const errors = trackErrors(page);
  await gotoDesktop(page);
  const body = page.locator('body');

  // Arrastre por la barra de título; a media operación la ventana se cierra (p. ej. CLOSE_APP).
  const dir = await openNormal(page, 'directory');
  const box = await dir.boundingBox();
  await page.mouse.move(box.x + 200, box.y + 18);
  await page.mouse.down();
  await page.mouse.move(box.x + 260, box.y + 90, { steps: 6 });
  await expect(body).toHaveClass(/desktop-dragging/);
  // close() cancela el gesto en el acto (sin esperar al respaldo de `lostpointercapture`).
  const dragShield = await page.evaluate(() => {
    window.ItcjDesktop.wm.close('directory');
    return document.body.classList.contains('desktop-dragging');
  });
  expect(dragShield, 'escudo de arrastre justo después de close()').toBe(false);
  await page.mouse.up();
  await expect(body).not.toHaveClass(/desktop-dragging/);
  await expect(page.locator('#snapPreview.is-visible')).toHaveCount(0);
  expect(await page.evaluate(() => window.ItcjDesktop.wm.isOpen('directory'))).toBe(false);
  // Cancelado: ese arrastre no se guarda como geometría de la app.
  const geom = await page.evaluate((k) => JSON.parse(localStorage.getItem(k) || '{}'), GEOM_KEY);
  expect(geom.directory).toBeUndefined();

  // Redimensión por una manija; a media operación la ventana se cierra.
  const hd = await openNormal(page, 'helpdesk');
  const se = await hd.locator('.window-resize[data-dir="se"]').boundingBox();
  await page.mouse.move(se.x + se.width / 2, se.y + se.height / 2);
  await page.mouse.down();
  await page.mouse.move(se.x + 80, se.y + 50, { steps: 6 });
  await expect(body).toHaveClass(/desktop-resizing/);
  const resizeShield = await page.evaluate(() => {
    window.ItcjDesktop.wm.close('helpdesk');
    const b = document.body;
    return { cls: b.className, cursor: b.style.getPropertyValue('--resize-cursor') };
  });
  expect(resizeShield.cls, 'clases de body justo después de close()').not.toMatch(/desktop-(dragging|resizing)/);
  expect(resizeShield.cursor).toBe('');
  await page.mouse.up();
  await expect(body).not.toHaveClass(/desktop-(dragging|resizing)/);

  // El escritorio sigue usable: un arrastre nuevo mueve la ventana y termina limpio.
  const again = await openNormal(page, 'directory');
  const b1 = await again.boundingBox();
  await drag(page, b1.x + 200, b1.y + 18, 40, 30);
  await expect(body).not.toHaveClass(/desktop-dragging/);
  const b2 = await again.boundingBox();
  expect(near(b2.x, b1.x + 40) && near(b2.y, b1.y + 30), `(${b1.x},${b1.y}) → (${b2.x},${b2.y})`).toBe(true);
  expect(errors).toEqual([]);
});

test('(k) captura: esquinas y sombra en normal, maximizada y acoplada', async ({ page }) => {
  test.skip(!CAPTURE, 'solo con E2E_CAPTURE=1');
  await gotoDesktop(page);
  const win = await openNormal(page, 'directory');
  await expect(win).not.toHaveClass(/is-loading/, { timeout: 15_000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, 'final-window-normal.png') });

  await win.locator('.window-title-text').dblclick();
  await expect(win).toHaveClass(/is-maximized/);
  await settle(win);
  await page.screenshot({ path: path.join(SHOTS, 'final-window-maximized.png') });

  await taskbarBtn(page, 'helpdesk').click();
  await expect(windowOf(page, 'helpdesk')).toBeVisible();
  await page.evaluate(() => {
    window.ItcjDesktop.wm.snap('directory', 'left');
    window.ItcjDesktop.wm.snap('helpdesk', 'right');
  });
  await expect(windowOf(page, 'helpdesk')).not.toHaveClass(/is-loading/, { timeout: 15_000 });
  await settle(windowOf(page, 'helpdesk'));
  await settle(win);
  await page.screenshot({ path: path.join(SHOTS, 'final-window-snapped.png') });
});

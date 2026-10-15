// @ts-check
/**
 * Temas estacionales en el escritorio nuevo (/itcj/dashboard) — Task 2 del plan
 * «Temas y tutorial del escritorio».
 *
 * Por tema (Navidad, San Valentin, Mundial 2026) × {1366×768, 1920×1080}:
 *  - sin `pageerror`; las decoraciones viven en #theme-decor (ninguna en <body>);
 *  - las etiquetas de los iconos tienen el mismo rect (respecto a su tile) que
 *    sin tema: nada del tema entra al flujo del tile (Navidad: nieve en iconos);
 *  - ventana de Help Desk maximizada: el centro de cada .window-control y del
 *    título es ese elemento (o un hijo); en 1920 la guirnalda termina antes de
 *    la barra de título (banda reservada);
 *  - orden de pintado: en 1920 la capa (z 900) pinta ENCIMA de la ventana y en
 *    1366 (z 1) DEBAJO; al cruzar 1600 px la capa cambia de modo sin recargar y
 *    la maximizada se reacomoda a la banda;
 *  - Mundial: ningún indicador regional (U+1F1E6–U+1F1FF) en la capa y el botón
 *    de la bandeja con el aspecto de la campana (.tray-btn);
 *  - tutorial (botón Tutorial → confirmar): «Comenzar» es lo que está encima en
 *    su centro.
 * Más: Mundial en el shell móvil (/itcj/m/, iPhone 13): la guirnalda no tapa el
 * saludo.
 *
 * Estado de la BD dev: beforeAll guarda core_themes (is_manually_active,
 * is_enabled) y afterAll lo restaura y borra la clave Redis core:active_theme.
 * Mientras corre, solo el tema bajo prueba queda habilitado (así un tema activo
 * por fechas no se cuela en la línea base «sin tema»).
 */
const { test, expect, devices } = require('@playwright/test');
const { execFileSync } = require('child_process');
const path = require('path');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const STORAGE_STATE = path.join(__dirname, '..', '.auth', 'state.json');
const THEMES = ['Navidad', 'San Valentin', 'Mundial 2026'];
const VIEWPORTS = [
  { name: '1366x768', width: 1366, height: 768, over: false },
  { name: '1920x1080', width: 1920, height: 1080, over: true },
];
// Clases raíz de las decoraciones de los tres temas (deben colgar de #theme-decor).
const DECOR_CLASSES = [
  'christmas-lights', 'christmas-cables-svg', 'snowflake', 'snowman-container',
  'valentine-garland', 'floating-heart', 'cupid-container', 'shot-heart',
  'mundial-garland', 'mundial-float-flag', 'mundial-mexico', 'mundial-ball', 'mundial-confetti', 'mundial-lights',
];
const GARLAND_ITEMS = '.christmas-light, .valentine-heart-light, .mundial-gflag';

const PY_SNAPSHOT = `
import json
from itcj2.database import SessionLocal
from itcj2.core.models.theme import Theme
db = SessionLocal()
try:
    print(json.dumps({t.name: [bool(t.is_manually_active), bool(t.is_enabled)] for t in db.query(Theme).all()}))
finally:
    db.close()
`;

// argv[1] = {"nombre": [manual, enabled], ...}; los que no vengan quedan [False, False].
const PY_APPLY = `
import json, sys
from itcj2.database import SessionLocal
from itcj2.core.models.theme import Theme
from itcj2.core.services.themes_service import invalidate_active_theme_cache
state = json.loads(sys.argv[1])
db = SessionLocal()
try:
    for t in db.query(Theme).all():
        manual, enabled = state.get(t.name, [False, False])
        t.is_manually_active = bool(manual)
        t.is_enabled = bool(enabled)
    db.commit()
finally:
    db.close()
invalidate_active_theme_cache()
print("ok")
`;

function py(src, ...args) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src, ...args], {
    encoding: 'utf8', timeout: 60_000,
  }).trim();
}

/** Deja activo solo `name` (o ningún tema con null). */
function activateOnly(name) {
  py(PY_APPLY, JSON.stringify(name ? { [name]: [true, true] } : {}));
}

/** pageerror y errores de consola de los estáticos de tema. */
function trackErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.stack || e}`));
  page.on('console', (m) => {
    const where = m.location().url || '';
    if (m.type() === 'error' && /\/static\/core\/js\/dashboard\/themes\//.test(where)) {
      errors.push(`console: ${m.text()} @ ${where}`);
    }
  });
  return errors;
}

async function gotoDesktop(page, vp) {
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.addInitScript(() => {
    try {
      localStorage.setItem('dashboard_tutorial_completed', 'true');
      localStorage.removeItem('mundialWidgetOpen');
    } catch (e) { /* sin storage */ }
  });
  await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.documentElement.classList.contains('desktop-ready'));
}

/** Rect de cada etiqueta respecto a su tile (redondeado a 0.1 px), por app. */
function labelRects(page) {
  return page.evaluate(() => {
    const r1 = (n) => Math.round(n * 10) / 10;
    const out = {};
    document.querySelectorAll('.desktop-icon').forEach((tile) => {
      const t = tile.getBoundingClientRect();
      const l = tile.querySelector('.desktop-icon-label').getBoundingClientRect();
      out[tile.dataset.app] = { x: r1(l.left - t.left), y: r1(l.top - t.top), w: r1(l.width), h: r1(l.height), tw: r1(t.width), th: r1(t.height) };
    });
    return out;
  });
}

/** El centro de cada control y del título de la ventana es ese elemento (o un hijo). */
function titlebarHits(page, key) {
  return page.evaluate((k) => {
    const win = document.querySelector(`.app-window[data-app-id="${k}"]`);
    return [...win.querySelectorAll('.window-title, .window-control')].map((el) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { el: el.className, ok: !!hit && (hit === el || el.contains(hit)), hit: hit ? hit.className || hit.tagName : null };
    });
  }, key);
}

/**
 * Orden de pintado real: una sonda con pointer-events dentro de #theme-decor, en
 * el centro de la ventana. Encima → elementFromPoint devuelve la sonda.
 */
function decorPaintsOverWindow(page, key) {
  return page.evaluate((k) => {
    const win = document.querySelector(`.app-window[data-app-id="${k}"]`);
    const r = win.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const probe = document.createElement('div');
    probe.style.cssText = `position:fixed;left:${cx - 10}px;top:${cy - 10}px;width:20px;height:20px;pointer-events:auto;`;
    document.getElementById('theme-decor').appendChild(probe);
    const hit = document.elementFromPoint(cx, cy);
    probe.remove();
    if (hit === probe) return 'decor';
    return win.contains(hit) ? 'window' : `otro: ${hit && (hit.className || hit.tagName)}`;
  }, key);
}

async function openMaximized(page, key) {
  await page.evaluate((k) => window.desktop.openApplication(k), key);
  const win = page.locator(`.app-window[data-app-id="${key}"]`);
  await expect(win).toBeVisible();
  await page.evaluate((k) => {
    const wm = window.ItcjDesktop.wm;
    if (wm.getState(k) !== 'maximized') wm.toggleMaximize(k);
  }, key);
  await expect(win).toHaveClass(/is-maximized/);
  await expect(win).not.toHaveClass(/is-transitioning/);
  await win.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished.catch(() => null))));
  return win;
}

const baseline = {};
let snapshot = null;

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  snapshot = py(PY_SNAPSHOT);
});

// Restaura is_manually_active/is_enabled tal como estaban y borra la clave Redis
// del tema activo (PY_APPLY invalida la caché).
test.afterAll(() => {
  if (snapshot) py(PY_APPLY, snapshot);
});

test.describe('sin tema (línea base)', () => {
  test.beforeAll(() => activateOnly(null));

  for (const vp of VIEWPORTS) {
    test(`etiquetas sin tema ${vp.name}`, async ({ page }) => {
      const errors = trackErrors(page);
      await gotoDesktop(page, vp);
      await expect(page.locator('#theme-decor')).toHaveCount(0);
      baseline[vp.name] = await labelRects(page);
      expect(Object.keys(baseline[vp.name]).length).toBeGreaterThan(1);
      expect(errors).toEqual([]);
    });
  }
});

for (const theme of THEMES) {
  test.describe(`tema ${theme}`, () => {
    test.beforeAll(() => activateOnly(theme));

    for (const vp of VIEWPORTS) {
      test(`${theme} ${vp.name}`, async ({ page }) => {
        test.setTimeout(90_000);
        const errors = trackErrors(page);
        await gotoDesktop(page, vp);
        await expect.poll(() => page.evaluate(() => window.activeTheme && window.activeTheme.name)).toBe(theme);

        // --- Capa: existe, tiene las decoraciones y ninguna quedó en <body> ---
        const decor = page.locator('#theme-decor');
        await expect(decor).toHaveCount(1);
        await expect.poll(() => decor.evaluate((el) => el.childElementCount)).toBeGreaterThan(0);
        const stray = await page.evaluate((classes) => [...document.body.children]
          .filter((el) => classes.some((c) => el.classList && el.classList.contains(c)))
          .map((el) => el.className.baseVal !== undefined ? el.className.baseVal : el.className), DECOR_CLASSES);
        expect(stray, 'decoraciones colgando de <body>').toEqual([]);
        expect(await decor.evaluate((el) => getComputedStyle(el).zIndex)).toBe(vp.over ? '900' : '1');

        // --- Etiquetas: mismo rect respecto a su tile que sin tema ---
        expect(await labelRects(page)).toEqual(baseline[vp.name]);

        // --- Mundial: banderas sin letras y botón de bandeja como la campana ---
        if (theme === 'Mundial 2026') {
          await expect(page.locator('#theme-decor .mundial-float-flag').first()).toBeAttached();
          const regional = await decor.evaluate((el) => /[\u{1F1E6}-\u{1F1FF}]/u.test(el.textContent));
          expect(regional, 'indicadores regionales (emoji de bandera) en la capa').toBe(false);
          const tray = await page.evaluate(() => {
            const b = document.getElementById('mundial-tray-btn');
            const bell = document.getElementById('notificationBell');
            const rb = b.getBoundingClientRect();
            const rr = bell.getBoundingClientRect();
            const cs = getComputedStyle(b);
            return {
              size: [rb.width, rb.height], bell: [rr.width, rr.height], border: cs.borderStyle,
              tray: b.classList.contains('tray-btn'), type: b.type, label: b.getAttribute('aria-label'),
            };
          });
          expect(tray.size).toEqual(tray.bell);
          expect(tray).toMatchObject({ border: 'none', tray: true, type: 'button', label: 'Partidos del Mundial' });
        }

        // --- Ventana maximizada: título y botones son lo que está encima ---
        const win = await openMaximized(page, 'helpdesk');
        const hits = await titlebarHits(page, 'helpdesk');
        expect(hits.length).toBe(6);
        for (const h of hits) expect(h.ok, `${h.el} tapado por ${h.hit}`).toBe(true);

        const band = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--theme-band')) || 0);
        expect(band).toBeGreaterThan(0);
        const winTop = (await win.boundingBox()).y;
        if (vp.over) {
          // La guirnalda termina antes de la barra de título (banda reservada).
          expect(winTop).toBeCloseTo(band, 0);
          const garlandBottom = await page.evaluate((sel) => Math.max(...[...document.querySelectorAll(sel)]
            .map((el) => el.getBoundingClientRect().bottom)), GARLAND_ITEMS);
          expect(garlandBottom).toBeLessThanOrEqual(winTop + 0.5);
        } else {
          expect(winTop).toBe(0);
        }

        // --- Orden de pintado: encima en pantalla grande, debajo en chica ---
        expect(await decorPaintsOverWindow(page, 'helpdesk')).toBe(vp.over ? 'decor' : 'window');

        // --- Cruzar 1600 px: la capa cambia de modo y la maximizada se reacomoda ---
        const other = VIEWPORTS.find((v) => v !== vp);
        await page.setViewportSize({ width: other.width, height: other.height });
        await expect.poll(() => decor.evaluate((el) => getComputedStyle(el).zIndex)).toBe(other.over ? '900' : '1');
        await expect.poll(async () => Math.round((await win.boundingBox()).y)).toBe(other.over ? Math.round(band) : 0);
        expect(await decorPaintsOverWindow(page, 'helpdesk')).toBe(other.over ? 'decor' : 'window');
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await expect.poll(() => decor.evaluate((el) => getComputedStyle(el).zIndex)).toBe(vp.over ? '900' : '1');

        // --- Tutorial: «Comenzar» es lo que está encima en su centro ---
        await page.evaluate(() => window.desktop.closeAllWindows());
        await expect(page.locator('.app-window')).toHaveCount(0);
        await page.locator('#dashboardTutorialButton').click();
        const confirm = page.locator('#dashboardTutorialStartConfirm');
        const start = page.locator('.shepherd-element[data-shepherd-step-id="welcome"]').getByRole('button', { name: 'Comenzar' });
        // Bootstrap ignora hide() mientras el modal aún entra: se espera a que
        // termine de entrar y, si el clic cayó en la transición, se reintenta.
        await expect(async () => {
          if (await confirm.isVisible()) {
            await expect.poll(() => confirm.evaluate((el) => getComputedStyle(el.closest('.modal-dialog')).transform),
              { timeout: 3_000 }).toBe('none');
            await confirm.click({ timeout: 2_000 });
          }
          await expect(start).toBeVisible({ timeout: 4_000 });
        }).toPass({ timeout: 30_000 });
        await start.evaluate((el) => Promise.all(el.closest('.shepherd-element').getAnimations({ subtree: true }).map((a) => a.finished.catch(() => null))));
        const onTop = await start.evaluate((el) => {
          const r = el.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return !!hit && (hit === el || el.contains(hit));
        });
        expect(onTop, '«Comenzar» tapado').toBe(true);

        expect(errors).toEqual([]);
      });
    }
  });
}

test.describe('Mundial en el shell móvil', () => {
  test.beforeAll(() => activateOnly('Mundial 2026'));

  test('la guirnalda no tapa el saludo de /itcj/m/', async ({ browser, baseURL }) => {
    const ctx = await browser.newContext({ ...devices['iPhone 13'], storageState: STORAGE_STATE, baseURL });
    try {
      const page = await ctx.newPage();
      const errors = trackErrors(page);
      await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });
      const greeting = page.locator('.mobile-greeting-text');
      await expect(greeting).toBeVisible();
      await expect(page.locator('.mundial-garland .mundial-gflag').first()).toBeAttached();
      const m = await page.evaluate(() => {
        const g = document.querySelector('.mobile-greeting-text').getBoundingClientRect();
        const flags = [...document.querySelectorAll('.mundial-gflag')].map((f) => f.getBoundingClientRect().bottom);
        return { greetingTop: g.top, garlandBottom: Math.max(...flags) };
      });
      expect(m.garlandBottom).toBeLessThanOrEqual(m.greetingTop);

      // Pantalla chica: las decoraciones solo adornan el inicio; con una app
      // abierta (vista "app") la capa se oculta para no tapar el iframe.
      const decor = page.locator('#theme-decor');
      await expect(decor).toBeVisible();
      await page.evaluate(() => window.mobileApp.setActiveView('app'));
      await expect(decor).toBeHidden();
      expect(errors).toEqual([]);
    } finally {
      await ctx.close();
    }
  });
});

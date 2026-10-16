// @ts-check
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function hexToRgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

function appColor(key) {
  const src = [
    'from itcj2.database import SessionLocal',
    'from itcj2.core.models.app import App',
    'db = SessionLocal()',
    `a = db.query(App).filter_by(key='${key}').first()`,
    "print((a.color or '#6c757d') if a else '#6c757d')",
    'db.close()',
  ].join('\n');
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  }).trim();
}

// Las apps con ícono ráster propio (agendatec, helpdesk) pintan el tile de
// BLANCO a propósito desde bb62f49 — `.mobile-app-card-icon.has-img` — para que
// el logo se lea como app-icon en vez de forzarlo sobre el color de marca. Las
// que además traen su propio tile en la imagen (`.has-own-tile`, p. ej.
// titulatec) van a sangre: fondo TRANSPARENTE, sin el tile blanco (si no, se
// vería un marco dentro de otro). El color de `core_apps.color` sigue viniendo
// de la BD en todos los casos, solo que en esas tarjetas viaja en la custom
// property y no en el `background`.
// Por eso el aserto se parte en tres y ninguno hardcodea una app: qué app tiene
// ícono ráster (o tile propio) es una decisión de diseño que cambia sin avisar
// a este test. Hoy TODAS las apps visibles tienen ráster, así que el camino sin
// imagen (`background: var(--app-badge-color)`) se comprueba en cada tarjeta con
// una sonda: el mismo ícono sin las clases de ráster.
test.describe('mobile app card — DB-driven badge (F7)', () => {
  test('el fondo del icono de la tarjeta viene de core_apps.color', async ({ page }) => {
    await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.mobile-app-card').first()).toBeVisible();

    const cards = await page.locator('.mobile-app-card').evaluateAll((els) =>
      els.map((el) => {
        const icon = el.querySelector('.mobile-app-card-icon');
        // Sonda: el mismo ícono sin las clases de ráster, en la misma tarjeta = lo
        // que pintaría esa app sin imagen (no depende de qué apps tienen ráster).
        const probe = /** @type {HTMLElement} */ (icon.cloneNode(false));
        probe.classList.remove('has-img', 'has-own-tile');
        el.appendChild(probe);
        const plainBg = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return {
          key: el.getAttribute('data-app-key'),
          hasImg: icon.classList.contains('has-img'),
          ownTile: icon.classList.contains('has-own-tile'),
          bg: getComputedStyle(icon).backgroundColor,
          plainBg,
          badgeVar: getComputedStyle(icon).getPropertyValue('--app-badge-color').trim(),
        };
      }),
    );
    expect(cards.length).toBeGreaterThan(0);

    for (const card of cards) {
      const expected = hexToRgb(appColor(card.key));
      // La custom property siempre sale de core_apps.color, tenga o no ráster.
      expect(hexToRgb(card.badgeVar), `--app-badge-color de ${card.key}`).toBe(expected);
      // Sin ráster, `background: var(--app-badge-color)` resuelve al color de la BD.
      expect(card.plainBg, `fondo sin ráster de ${card.key}`).toBe(expected);
      if (card.ownTile) {
        // La imagen ya trae su tile: va a sangre, sin fondo.
        expect(card.bg, `tile de ${card.key} (tile propio)`).toBe('rgba(0, 0, 0, 0)');
      } else if (card.hasImg) {
        // Tile blanco deliberado: el logo se lee mejor que sobre el color.
        expect(card.bg, `tile de ${card.key} (ícono ráster)`).toBe('rgb(255, 255, 255)');
      } else {
        expect(card.bg, `fondo de ${card.key}`).toBe(expected);
      }
    }
  });
});

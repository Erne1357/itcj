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
// el logo se lea como app-icon en vez de forzarlo sobre el color de marca. El
// color de `core_apps.color` sigue viniendo de la BD en ambos casos, solo que
// en esas tarjetas viaja en la custom property y no en el `background`.
// Por eso el aserto se parte en dos y ninguno hardcodea una app: qué app tiene
// ícono ráster es una decisión de diseño que cambia sin avisar a este test.
test.describe('mobile app card — DB-driven badge (F7)', () => {
  test('el fondo del icono de la tarjeta viene de core_apps.color', async ({ page }) => {
    await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.mobile-app-card').first()).toBeVisible();

    const cards = await page.locator('.mobile-app-card').evaluateAll((els) =>
      els.map((el) => {
        const icon = el.querySelector('.mobile-app-card-icon');
        return {
          key: el.getAttribute('data-app-key'),
          hasImg: icon.classList.contains('has-img'),
          bg: getComputedStyle(icon).backgroundColor,
          badgeVar: getComputedStyle(icon).getPropertyValue('--app-badge-color').trim(),
        };
      }),
    );
    expect(cards.length).toBeGreaterThan(0);

    for (const card of cards) {
      const expected = hexToRgb(appColor(card.key));
      // La custom property siempre sale de core_apps.color, tenga o no ráster.
      expect(hexToRgb(card.badgeVar), `--app-badge-color de ${card.key}`).toBe(expected);
      if (card.hasImg) {
        // Tile blanco deliberado: el logo se lee mejor que sobre el color.
        expect(card.bg, `tile de ${card.key} (ícono ráster)`).toBe('rgb(255, 255, 255)');
      } else {
        expect(card.bg, `fondo de ${card.key}`).toBe(expected);
      }
    }

    // El test pierde su razón de ser si TODAS las apps tuvieran ráster: nadie
    // estaría comprobando que `background: var(--app-badge-color)` resuelve.
    expect(cards.some((c) => !c.hasImg), 'ninguna app sin ícono ráster que validar').toBe(true);
  });
});

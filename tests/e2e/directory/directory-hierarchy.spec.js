// @ts-check
const { test, expect } = require('@playwright/test');

/**
 * El defecto original: el nombre del departamento estaba tipografiado como lo
 * MENOS importante de la pantalla (11.52px, mayusculas, #94A3B8 a 2.56:1)
 * mientras las filas que contiene iban a 16px/600 #0F172A. Estos tests fijan que
 * la inversion no vuelva.
 */

test('la banda nunca pesa menos que las filas que agrupa', async ({ page }) => {
  await page.goto('/directory/');
  await page.waitForSelector('.dir-group');

  const violations = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.dir-group').forEach((g) => {
      const band = getComputedStyle(g.querySelector('.dir-dept'));
      const title = g.querySelector('.dir-title-main');
      if (!title) return;
      const t = getComputedStyle(title);
      const bs = parseFloat(band.fontSize);
      const ts = parseFloat(t.fontSize);
      if (bs < ts) out.push(`${g.id}: banda ${bs}px < titulo ${ts}px`);
      if (bs === ts && parseInt(band.fontWeight, 10) <= parseInt(t.fontWeight, 10)) {
        out.push(`${g.id}: mismo tamano y peso no mayor`);
      }
    });
    return out;
  });
  expect(violations).toEqual([]);
});

test('la banda cumple la tabla tipografica por nivel y la sangria topada a 3', async ({ page }) => {
  await page.goto('/directory/');
  await page.waitForSelector('.dir-group');

  const bad = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.dir-group').forEach((g) => {
      const s = getComputedStyle(g.querySelector('.dir-dept'));
      const depth = parseInt(getComputedStyle(g).getPropertyValue('--dir-depth').trim() || '0', 10);
      const wantSize = depth <= 1 ? 18 : 16;
      if (Math.abs(parseFloat(s.fontSize) - wantSize) > 0.5) {
        out.push(`${g.id}: ${s.fontSize} != ${wantSize}px (depth ${depth})`);
      }
      if (parseInt(s.fontWeight, 10) !== 700) out.push(`${g.id}: weight ${s.fontWeight}`);
      const indent = parseFloat(s.paddingLeft) - 12;              // .75rem base
      if (Math.abs(indent - Math.min(depth, 3) * 20) > 1) {
        out.push(`${g.id}: sangria ${indent}px (depth ${depth}, tope 3)`);
      }
    });
    return out;
  });
  expect(bad).toEqual([]);
});

test('las bandas no usan mayusculas ni el gris de 2.56:1', async ({ page }) => {
  await page.goto('/directory/');
  await page.waitForSelector('.dir-dept');
  const bad = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.dir-dept').forEach((b) => {
      const s = getComputedStyle(b);
      if (s.textTransform === 'uppercase') out.push('uppercase');
      if (s.color === 'rgb(148, 163, 184)') out.push('#94A3B8 como texto');
    });
    return out;
  });
  expect(bad).toEqual([]);
});

test('cada grupo anidado nombra a su ancestro visible', async ({ page }) => {
  await page.goto('/directory/');
  await page.waitForSelector('.dir-group');
  const missing = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.dir-group').forEach((g) => {
      const depth = parseInt(getComputedStyle(g).getPropertyValue('--dir-depth').trim() || '0', 10);
      const anc = g.querySelector('.dir-anc');
      if (depth >= 1 && !anc) out.push(`${g.id}: depth ${depth} sin prefijo de ancestro`);
      if (depth === 0 && anc) out.push(`${g.id}: raiz con prefijo`);
    });
    return out;
  });
  expect(missing).toEqual([]);
});

test('copiar la extension deja el valor en el portapapeles', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/directory/');
  await page.waitForSelector('.dir-ext-chip');
  const chip = page.locator('.dir-ext-chip').first();
  const expected = await chip.getAttribute('data-dir-copy');
  await chip.click();
  await expect(page.locator('.toast-body')).toContainText('Copiado');
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toBe(expected);
});

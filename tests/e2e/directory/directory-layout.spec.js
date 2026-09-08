// @ts-check
const { test, expect } = require('@playwright/test');

const VIEWPORTS = [320, 360, 375, 575, 768, 1280];

/**
 * El invariante clasico `documentElement.scrollWidth <= innerWidth` NO detecta
 * este fallo: el desbordamiento queda RECORTADO dentro de .dir-table (que ahora
 * lleva overflow:clip), asi que el documento no crece y el boton simplemente
 * desaparece. Hay que medir la geometria de cada boton contra la caja de la tabla.
 */
for (const width of VIEWPORTS) {
  test(`ninguna fila desborda ni saca botones de la tabla a ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/directory/');
    await page.waitForSelector('.dir-row');

    const bad = await page.evaluate(() => {
      const out = [];
      const table = document.querySelector('.dir-table').getBoundingClientRect();
      document.querySelectorAll('.dir-row').forEach((row, i) => {
        if (row.scrollWidth > row.clientWidth + 1) {
          out.push(`fila ${i}: scrollWidth ${row.scrollWidth} > clientWidth ${row.clientWidth}`);
        }
        row.querySelectorAll('.dir-actions button, [data-dir-copy]').forEach((b) => {
          const r = b.getBoundingClientRect();
          if (r.right > table.right + 1 || r.left < table.left - 1) {
            out.push(`fila ${i}: control fuera de la tabla (${Math.round(r.left)}-${Math.round(r.right)} vs ${Math.round(table.left)}-${Math.round(table.right)})`);
          }
        });
      });
      return out;
    });
    expect(bad).toEqual([]);
  });
}

test('los objetivos tactiles llegan a 40px en movil', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto('/directory/');
  await page.waitForSelector('.dir-row');
  const small = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.dir-actions .btn').forEach((b) => {
      const r = b.getBoundingClientRect();
      if (r.width < 39 || r.height < 39) out.push(`${Math.round(r.width)}x${Math.round(r.height)}`);
    });
    return out;
  });
  expect(small).toEqual([]);
});

test('la cabecera se queda pegada al hacer scroll a >=576px', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 700 });
  await page.goto('/directory/');
  await page.waitForSelector('.dir-head');
  // behavior:'instant' es obligatorio: Bootstrap 5.3 pone scroll-behavior:smooth
  // en :root, asi que un scrollTo normal deja scrollY en 0 al medir enseguida.
  await page.evaluate(() => window.scrollTo({ top: 600, behavior: 'instant' }));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);
  const top = await page.evaluate(
    () => document.querySelector('.dir-head').getBoundingClientRect().top);
  expect(Math.abs(top)).toBeLessThan(4);
});

test('el indicador de carga no empuja la lista', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/directory/');
  await page.waitForSelector('.dir-row');
  const before = await page.evaluate(
    () => document.querySelector('#dir-list').getBoundingClientRect().top);
  await page.evaluate(() => {
    document.querySelector('#dir-skel').classList.add('htmx-request');
  });
  const during = await page.evaluate(
    () => document.querySelector('#dir-list').getBoundingClientRect().top);
  expect(Math.abs(during - before)).toBeLessThan(2);
});

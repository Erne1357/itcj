// @ts-check
/**
 * Barrido de contraste sobre las pantallas REALES de Calidad.
 *
 * Complementa a `visual-contract.spec.js`, que mide botones y badges
 * sintéticos: ese no ve lo que hacen las 20 hojas de página. Este recorre cada
 * pantalla renderizada, busca todo elemento con texto propio visible y compara
 * su color contra el fondo OPACO real, componiendo los tintes con alfa
 * (`--adhoc-primary-tint` y compañía son hex de ocho dígitos: medir contra
 * ellos sin componer da 1:1 y esconde el caso).
 *
 * Umbral: WCAG 2.x AA — 4.5:1 para texto normal, 3:1 para texto grande
 * (>= 24px, o >= 18.66px en negrita).
 *
 * Lo que encontró la primera vez que se corrió, y que las cuatro suites
 * anteriores no veían porque ninguna miraba color:
 *
 *   · el botón "Salir" de la cabecera, en las 30 pantallas: 4.25:1;
 *   · "Media" y "Baja" de la columna de prioridad: 2.19:1 y 2.87:1 — la
 *     columna por la que se prioriza el trabajo del SGC;
 *   · el estado vacío del tablero y el candado de la tarjeta bloqueada: 2.56:1;
 *   · "En Revisión" en el listado de documentos: 4.3:1.
 *
 * QUEDA FUERA a propósito: los controles deshabilitados (WCAG los exime) y
 * todo lo que no sea texto. Los bordes y los iconos decorativos se rigen por
 * 1.4.11 (3:1) y no se miden aquí.
 */
const { test, expect } = require('@playwright/test');
const { gotoAdhoc } = require('./_helpers');

test.use({ viewport: { width: 1600, height: 900 } });

/** Las 14 pantallas que no necesitan un id de entidad en la URL. */
const PANTALLAS = [
  '/adhoc/dashboard',
  '/adhoc/documentos',
  '/adhoc/documentos/panel',
  '/adhoc/documentos/flujos',
  '/adhoc/documentos/categorias',
  '/adhoc/incidencias',
  '/adhoc/programas',
  '/adhoc/indicadores',
  '/adhoc/reportes',
  '/adhoc/panel',
  '/adhoc/panel/usuarios',
  '/adhoc/panel/areas',
  '/adhoc/panel/procesos',
  '/adhoc/panel/configuracion',
  '/adhoc/panel/correo',
];

/**
 * Corre DENTRO de la página. Devuelve un fallo por combinación distinta de
 * (clase, color, tamaño) — no uno por nodo, o una tabla de 200 filas produciría
 * 200 líneas idénticas.
 */
function sonda() {
  const rgba = (v) => {
    const n = String(v).match(/-?[\d.]+/g) || [0, 0, 0, 0];
    return [Number(n[0]), Number(n[1]), Number(n[2]), n[3] === undefined ? 1 : Number(n[3])];
  };
  const componer = (frente, detras) =>
    [0, 1, 2].map((i) => Math.round(frente[i] * frente[3] + detras[i] * (1 - frente[3])));

  /** Fondo opaco real: apila las capas con alfa hasta el primer opaco. */
  const fondoOpaco = (el) => {
    const capas = [];
    let n = el;
    while (n && n.nodeType === 1) {
      const c = rgba(getComputedStyle(n).backgroundColor);
      if (c[3] > 0) {
        capas.push(c);
        if (c[3] === 1) break;
      }
      n = n.parentElement;
    }
    capas.push([255, 255, 255, 1]); // el lienzo
    let acc = capas[capas.length - 1];
    for (let i = capas.length - 2; i >= 0; i--) acc = componer(capas[i], [acc[0], acc[1], acc[2], 1]);
    return acc;
  };

  const canal = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const luminancia = (r) => 0.2126 * canal(r[0]) + 0.7152 * canal(r[1]) + 0.0722 * canal(r[2]);
  const ratio = (a, b) => {
    const l1 = luminancia(a);
    const l2 = luminancia(b);
    const [claro, oscuro] = l1 > l2 ? [l1, l2] : [l2, l1];
    return Math.round(((claro + 0.05) / (oscuro + 0.05)) * 100) / 100;
  };

  const fallos = [];
  const vistos = new Set();

  for (const el of document.querySelectorAll('#adhoc-root *')) {
    const propio = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3 && n.textContent.trim())
      .map((n) => n.textContent.trim())
      .join(' ');
    if (!propio) continue;

    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
    const caja = el.getBoundingClientRect();
    if (caja.width === 0 || caja.height === 0) continue;
    if (el.closest('[disabled]') || (el.matches && el.matches(':disabled'))) continue;

    const px = parseFloat(cs.fontSize);
    const grande = px >= 24 || (px >= 18.66 && Number(cs.fontWeight) >= 700);
    const minimo = grande ? 3 : 4.5;

    const fondo = fondoOpaco(el);
    const fg = rgba(cs.color);
    const tinta = fg[3] < 1 ? componer(fg, [fondo[0], fondo[1], fondo[2], 1]) : [fg[0], fg[1], fg[2]];
    const medido = ratio(tinta, fondo);
    if (medido >= minimo) continue;

    const clave = String(el.className) + '|' + cs.color + '|' + Math.round(px);
    if (vistos.has(clave)) continue;
    vistos.add(clave);

    fallos.push(
      `${medido}:1 (min ${minimo}) ${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)} ` +
        `${px}px ${cs.color} "${propio.slice(0, 28)}"`
    );
  }
  return fallos;
}

for (const ruta of PANTALLAS) {
  test(`${ruta}: todo el texto cumple contraste AA`, async ({ page }) => {
    await gotoAdhoc(page, ruta);
    // El JS de la página pinta filas después del render: hay que dejarle llegar.
    await page.waitForTimeout(1200);

    const fallos = await page.evaluate(sonda);
    expect(fallos, `${ruta} — combinaciones por debajo de AA:\n  ${fallos.join('\n  ')}`).toEqual([]);
  });
}

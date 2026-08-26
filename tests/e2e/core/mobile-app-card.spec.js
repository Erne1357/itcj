// @ts-check
/**
 * Tarjeta de app del panel móvil — el badge sale de `core_apps.color` (F7).
 *
 * OJO CON EL CONTRATO: no todas las tarjetas se pintan igual, y el caso
 * anterior no lo contemplaba. `components/app_card.html` tiene DOS ramas:
 *
 *   · app sin icono propio  → `<i class="bi …">` sobre el color de la app;
 *   · app con icono ráster  → `<img>` sobre un tile BLANCO con borde, porque
 *     un PNG a todo color encima del color de marca no se lee (la regla
 *     `.mobile-app-card-icon.has-img` de mobile-base.css, commit bb62f49).
 *
 * El caso comprobaba el fondo de la tarjeta de `helpdesk`, que es justamente
 * una de las dos con icono ráster, así que exigía el verde de la BD sobre un
 * tile que por diseño es blanco: fallaba desde julio de 2026 contra un
 * comportamiento correcto.
 *
 * Ahora se comprueban las dos ramas, y las apps NO se nombran a mano: se leen
 * del DOM y se contrastan con la BD. Así el caso sigue valiendo cuando alguien
 * añada una app o le ponga icono propio a otra.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

/** '#198754' → 'rgb(25, 135, 84)', que es como lo devuelve getComputedStyle. */
function hexToRgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

/** {clave: color} de TODAS las apps, en una sola ida al contenedor. */
function coloresDeApps() {
  const src = [
    'import json',
    'from itcj2.database import SessionLocal',
    'from itcj2.core.models.app import App',
    'db = SessionLocal()',
    'try:',
    "    print(json.dumps({a.key: (a.color or '#6c757d') for a in db.query(App).all()}))",
    'finally:',
    '    db.close()',
  ].join('\n');
  return JSON.parse(
    execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
      encoding: 'utf8',
      timeout: 60_000,
    }).trim()
  );
}

test.describe('tarjeta de app del panel móvil — badge desde core_apps.color (F7)', () => {
  test('cada tarjeta toma su color de la BD, y el tile blanco es solo para las de icono propio', async ({
    page,
  }) => {
    const colores = coloresDeApps();
    await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });

    const tarjetas = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.mobile-app-card')).map((card) => {
        const icono = card.querySelector('.mobile-app-card-icon');
        const cs = getComputedStyle(icono);
        return {
          clave: card.getAttribute('data-app-key'),
          conImagen: icono.classList.contains('has-img'),
          fondo: cs.backgroundColor,
          // La variable la escribe la plantilla desde `app.color`: es el dato,
          // independientemente de que la rama con imagen lo tape con blanco.
          variable: cs.getPropertyValue('--app-badge-color').trim(),
        };
      })
    );

    expect(tarjetas.length, 'el panel móvil no pintó ninguna tarjeta de app').toBeGreaterThan(0);

    const problemas = [];
    for (const t of tarjetas) {
      const esperado = colores[t.clave];
      if (!esperado) {
        problemas.push(`${t.clave}: la tarjeta existe pero no hay fila en core_apps`);
        continue;
      }
      const esperadoRgb = hexToRgb(esperado);

      // El DATO tiene que llegar siempre, pinte lo que pinte encima.
      if (t.variable !== esperado) {
        problemas.push(`${t.clave}: --app-badge-color es '${t.variable}', la BD dice '${esperado}'`);
      }

      if (t.conImagen) {
        // Icono ráster: tile blanco a propósito, para que el PNG se lea.
        if (t.fondo !== 'rgb(255, 255, 255)') {
          problemas.push(`${t.clave}: tiene icono propio, el tile debería ser blanco y es ${t.fondo}`);
        }
      } else if (t.fondo !== esperadoRgb) {
        problemas.push(`${t.clave}: fondo ${t.fondo}, se esperaba ${esperadoRgb} (${esperado})`);
      }
    }

    expect(problemas, `tarjetas fuera de contrato:\n  ${problemas.join('\n  ')}`).toEqual([]);
  });

  test('las dos ramas de la plantilla están representadas', async ({ page }) => {
    // Si esto falla no hay un defecto de producto, pero el caso de arriba habría
    // dejado de probar una de las dos ramas sin decirlo — que es como el fallo
    // anterior sobrevivió un mes.
    await page.goto('/itcj/m/', { waitUntil: 'domcontentloaded' });

    const reparto = await page.evaluate(() => {
      const iconos = Array.from(document.querySelectorAll('.mobile-app-card-icon'));
      return {
        conImagen: iconos.filter((el) => el.classList.contains('has-img')).length,
        sinImagen: iconos.filter((el) => !el.classList.contains('has-img')).length,
      };
    });

    expect(
      reparto.sinImagen,
      'ninguna tarjeta usa el color de la app: el caso anterior no probaría nada'
    ).toBeGreaterThan(0);
    expect(
      reparto.conImagen,
      'ninguna tarjeta tiene icono propio: la rama del tile blanco quedó sin cubrir'
    ).toBeGreaterThan(0);
  });
});

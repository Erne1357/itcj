// @ts-check
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function runPy(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8',
    timeout: 60_000,
  }).trim();
}

function hexToRgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

async function uidFromCookie(page) {
  const cookies = await page.context().cookies();
  const tok = cookies.find((c) => c.name === 'itcj_token');
  if (!tok) throw new Error('no itcj_token cookie in storageState');
  const payload = JSON.parse(
    Buffer.from(tok.value.split('.')[1], 'base64url').toString('utf8')
  );
  return parseInt(payload.sub, 10);
}

function appColor(key) {
  return runPy(
    [
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.app import App',
      'db = SessionLocal()',
      `a = db.query(App).filter_by(key='${key}').first()`,
      "print((a.color or '#6c757d') if a else '#6c757d')",
      'db.close()',
    ].join('\n')
  );
}

test.describe('profile: DB-driven app badges (F7)', () => {
  test('app tile background comes from core_apps.color', async ({ page }) => {
    const expected = hexToRgb(appColor('helpdesk'));

    await page.goto('/itcj/profile', { waitUntil: 'domcontentloaded' });
    await page.click('#permissions-tab');

    const tile = page.locator('#permissions .app-icon[data-app-key="helpdesk"]');
    await expect(tile).toBeVisible();
    const bg = await tile.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe(expected);
  });

  test('seeded notification renders inline hex app color', async ({ page }) => {
    await page.goto('/itcj/profile', { waitUntil: 'domcontentloaded' });
    const uid = await uidFromCookie(page);
    const expected = hexToRgb(appColor('helpdesk'));

    const notifId = runPy(
      [
        'from itcj2.database import SessionLocal',
        'from itcj2.core.models.notification import Notification',
        'db = SessionLocal()',
        `n = Notification(user_id=${uid}, app_name='helpdesk', type='SYSTEM',`,
        "                 title='E2E F7 badge probe', body='probe', data={})",
        'db.add(n); db.commit(); print(n.id); db.close()',
      ].join('\n')
    );

    try {
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.click('#notifications-tab');

      const item = page.locator(
        `#notificationsContainer .notification-item[data-notif-id="${notifId}"] .notification-icon`
      );
      await expect(item).toBeVisible();

      // profile.js dispara loadNotifications() DOS veces en esta secuencia:
      // init() al cargar la página y el handler shown.bs.tab al hacer click en
      // la pestaña. Cada una reemplaza el innerHTML del contenedor. Un único
      // evaluate() puede resolver el locator contra el nodo del primer render
      // y ejecutar getComputedStyle sobre ese nodo ya DESPRENDIDO por el
      // segundo render (un nodo detached devuelve "" para toda propiedad).
      // En aislamiento ambos fetches llegan casi juntos y no se nota; con la
      // suite completa el backend va más cargado y la ventana se abre — así
      // fallaba este spec (received: ""). expect.poll re-resuelve el locator
      // en cada intento, de modo que siempre termina leyendo el nodo del
      // render vigente. Mismo patrón que badge-consistency.spec.js.
      await expect
        .poll(
          () =>
            item
              .evaluate((el) => getComputedStyle(el).backgroundColor)
              .catch(() => ''), // re-render a mitad de lectura → reintentar
          { timeout: 7_000 }
        )
        .toBe(expected);
    } finally {
      runPy(
        [
          'from itcj2.database import SessionLocal',
          'from itcj2.core.models.notification import Notification',
          'db = SessionLocal()',
          `n = db.get(Notification, ${parseInt(notifId, 10)})`,
          'db.delete(n) if n else None; db.commit(); db.close()',
        ].join('\n')
      );
    }
  });
});

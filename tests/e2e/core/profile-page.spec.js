// @ts-check
/**
 * Perfil (/itcj/profile): deep link ?tab=, embebido en el escritorio, paginación de
 * notificaciones con filtros de servidor y apertura de acciones como ventana.
 *
 * Las notificaciones sembradas usan app_name='e2ecore' y se aserta con el filtro de
 * esa app (nunca conteos absolutos del usuario); se borran en finally.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function runPy(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8',
    timeout: 60_000,
  }).trim();
}

async function uidFromCookie(page) {
  const cookies = await page.context().cookies();
  const tok = cookies.find((c) => c.name === 'itcj_token');
  if (!tok) throw new Error('no itcj_token cookie in storageState');
  const payload = JSON.parse(Buffer.from(tok.value.split('.')[1], 'base64url').toString('utf8'));
  return parseInt(payload.sub, 10);
}

/** Siembra n notificaciones e2ecore; `urls` (opcional) fija data.url por índice. */
function seed(uid, prefix, n, urls = {}) {
  const out = runPy(
    [
      'import json',
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.notification import Notification',
      'db = SessionLocal()',
      `urls = json.loads('${JSON.stringify(urls)}')`,
      'ids = []',
      `for i in range(${n}):`,
      '    u = urls.get(str(i))',
      `    x = Notification(user_id=${uid}, app_name='e2ecore', type='SYSTEM',`,
      `                     title='${prefix} ' + str(i), body='probe', data={'url': u} if u else {})`,
      '    db.add(x); db.flush(); ids.append(x.id)',
      'db.commit(); print(json.dumps(ids)); db.close()',
    ].join('\n')
  );
  return JSON.parse(out);
}

function cleanup(uid) {
  runPy(
    [
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.notification import Notification',
      'db = SessionLocal()',
      `db.query(Notification).filter_by(user_id=${uid}, app_name='e2ecore').delete()`,
      'db.commit(); db.close()',
    ].join('\n')
  );
}

test.describe('perfil', () => {
  test('?tab=notifications activa la pestaña y no hay pestaña Actividad', async ({ page }) => {
    await page.goto('/itcj/profile?tab=notifications', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#notifications-tab')).toHaveClass(/active/);
    await expect(page.locator('#activity-tab')).toHaveCount(0);

    await page.click('#permissions-tab');
    await expect.poll(() => page.url()).toContain('tab=permissions');
  });

  test('permisos: cada app en <details> con icono visible cerrado y filtro', async ({ page }) => {
    await page.goto('/itcj/profile?tab=permissions', { waitUntil: 'domcontentloaded' });
    const first = page.locator('#permissions details.app-permission-section').first();
    test.skip((await first.count()) === 0, 'el usuario e2e no tiene apps');
    await expect(first.locator('summary .app-icon[data-app-key]')).toBeVisible();
    await page.fill('#permissionFilter', 'zzz-no-existe-zzz');
    await expect(page.locator('#permissionFilterEmpty')).toBeVisible();
    await page.fill('#permissionFilter', '');
    await expect(first).toBeVisible();
  });

  test('embebido en el escritorio: sin cabecera móvil y la notificación abre la ventana', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('dashboard_tutorial_completed', 'true'));
    page.on('dialog', async (d) => {
      await d.dismiss();
      throw new Error('diálogo inesperado: ' + d.message());
    });
    await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
    const uid = await uidFromCookie(page);
    seed(uid, 'E2E T7 clic', 2, { 0: '/titulatec/', 1: 'javascript:alert(1)' });

    try {
      await page.waitForFunction(() => !!window.desktop);
      await page.evaluate(() => window.desktop.openProfile('notifications'));

      const profileFrame = page.locator('iframe.window-iframe[src*="/itcj/profile"]');
      await expect(profileFrame).toBeVisible();
      const frame = page.frameLocator('iframe.window-iframe[src*="/itcj/profile"]');

      await expect(frame.locator('#notifications-tab')).toHaveClass(/active/);
      await expect(frame.locator('.profile-mobile-header')).toBeHidden();

      await frame.locator('#notificationFilters .notif-chip[data-app-key="e2ecore"]').click();

      // action_url peligrosa: no hace nada (ni diálogo, ni ventana nueva).
      const bad = frame.locator('#notificationsContainer .notification-item', { hasText: 'E2E T7 clic 1' });
      await expect(bad).toBeVisible();
      await bad.click();
      await expect(page.locator('.app-window[data-app-id="titulatec"]')).toHaveCount(0);

      // action_url válida: abre/enfoca la ventana titulatec sin navegar el iframe del perfil.
      const good = frame.locator('#notificationsContainer .notification-item', { hasText: 'E2E T7 clic 0' });
      await good.click();
      await expect(page.locator('.app-window[data-app-id="titulatec"]')).toHaveCount(1);
      await expect(profileFrame).toHaveAttribute('src', /\/itcj\/profile/);
      await expect(good).not.toHaveClass(/unread/);
    } finally {
      cleanup(uid);
    }
  });

  test('paginación: 20 por página + "Cargar más"; filtro No leídas pide unread=true', async ({ page }) => {
    await page.goto('/itcj/profile', { waitUntil: 'domcontentloaded' });
    const uid = await uidFromCookie(page);
    seed(uid, 'E2E T7 pag', 25);

    try {
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.click('#notifications-tab');

      const chip = page.locator('#notificationFilters .notif-chip[data-app-key="e2ecore"]');
      await expect(chip).toBeVisible();
      await chip.click();

      const items = page.locator('#notificationsContainer .notification-item');
      await expect(items).toHaveCount(20);
      await expect(page.locator('#loadMoreBtn')).toBeVisible();

      await page.click('#loadMoreBtn');
      await expect(items).toHaveCount(25);
      await expect(page.locator('#loadMoreWrap')).toBeHidden();
      await expect(page.locator('.notif-group-header').first()).toHaveText('Hoy');

      const req = page.waitForRequest(
        (r) => r.url().includes('/api/core/v2/notifications?') && r.url().includes('unread=true')
          && r.url().includes('app=e2ecore')
      );
      await page.selectOption('#readStatusFilter', 'unread');
      await req;
      await expect(items).toHaveCount(20);

      // "Marcar todas" respeta el filtro de app y deja la lista sin no leídas.
      const markReq = page.waitForRequest(
        (r) => r.url().includes('/mark-all-read') && r.url().includes('app=e2ecore')
      );
      await page.click('#markAllReadBtn');
      await markReq;
      await expect(items).toHaveCount(0);
    } finally {
      cleanup(uid);
    }
  });
});

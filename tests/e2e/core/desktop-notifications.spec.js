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

async function uidFromCookie(page) {
  const cookies = await page.context().cookies();
  const tok = cookies.find((c) => c.name === 'itcj_token');
  if (!tok) throw new Error('no itcj_token cookie in storageState');
  const payload = JSON.parse(Buffer.from(tok.value.split('.')[1], 'base64url').toString('utf8'));
  return parseInt(payload.sub, 10);
}

function seed(uid, title, actionUrl) {
  return parseInt(
    runPy(
      [
        'from itcj2.database import SessionLocal',
        'from itcj2.core.models.notification import Notification',
        'db = SessionLocal()',
        `n = Notification(user_id=${uid}, app_name='helpdesk', type='SYSTEM',`,
        `                 title='${title}', body='probe', data={'url': '${actionUrl}'})`,
        'db.add(n); db.commit(); print(n.id); db.close()',
      ].join('\n')
    ),
    10
  );
}

function cleanup(ids) {
  runPy(
    [
      'from itcj2.database import SessionLocal',
      'from itcj2.core.models.notification import Notification',
      'db = SessionLocal()',
      `for i in ${JSON.stringify(ids)}:`,
      '    n = db.get(Notification, i)',
      '    if n: db.delete(n)',
      'db.commit(); db.close()',
    ].join('\n')
  );
}

test.describe('escritorio: notificaciones', () => {
  test('campana, badges, clic seguro y "Ver todas"', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('dashboard_tutorial_completed', 'true'));
    page.on('dialog', async (d) => {
      await d.dismiss();
      throw new Error('diálogo inesperado: ' + d.message());
    });
    let dialogSeen = false;
    page.on('dialog', () => { dialogSeen = true; });

    await page.goto('/itcj/dashboard', { waitUntil: 'domcontentloaded' });
    const uid = await uidFromCookie(page);
    const good = seed(uid, 'E2E T5 buena', '/help-desk/');
    const bad = seed(uid, 'E2E T5 mala', 'javascript:alert(1)');

    try {
      await page.reload({ waitUntil: 'domcontentloaded' });

      // Badges: total y el del botón/tile de helpdesk.
      await expect(page.locator('#globalNotificationBadge')).toBeVisible();
      await expect(page.locator('[data-badge-for="helpdesk"]:visible').first()).toBeVisible();

      // Campana abre el panel; Esc lo cierra; aria-expanded acompaña.
      const bell = page.locator('#notificationBell');
      const panel = page.locator('#notification-panel');
      await bell.click();
      await expect(panel).toBeVisible();
      await expect(bell).toHaveAttribute('aria-expanded', 'true');
      await page.keyboard.press('Escape');
      await expect(panel).toBeHidden();
      await expect(bell).toHaveAttribute('aria-expanded', 'false');

      // Clic en la notificación buena → ventana helpdesk.
      await bell.click();
      await page.locator(`.notification-item[data-id="${good}"]`).click();
      await expect(page.locator('[data-app-id="helpdesk"] .window-iframe')).toBeAttached();
      await expect(panel).toBeHidden();

      // Clic en la mala → no navega ni abre diálogos.
      const before = await page.locator('[data-app-id]').count();
      const urlBefore = page.url();
      await bell.click();
      await page.locator(`.notification-item[data-id="${bad}"]`).click();
      await page.waitForTimeout(500);
      expect(page.url()).toBe(urlBefore);
      expect(await page.locator('[data-app-id]').count()).toBe(before);
      expect(dialogSeen).toBe(false);

      // "Ver todas" → ventana profile con ?tab=notifications.
      // (la notificación mala no cierra el panel: abrirlo solo si hace falta)
      if (!(await panel.isVisible())) await bell.click();
      await page.locator('#view-all-notifications-btn').click();
      const frame = page.locator('[data-app-id="profile"] .window-iframe');
      await expect(frame).toBeAttached();
      await expect.poll(async () => (await frame.getAttribute('src')) || '').toContain('tab=notifications');
    } finally {
      cleanup([good, bad]);
    }
  });
});

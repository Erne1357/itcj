// @ts-check
/**
 * F6: el widget "En Línea" de /itcj/config muestra presencia REAL derivada de
 * /notify. Se abre una segunda sesión (otro usuario, mintTokenFor) en una
 * página que conecta /notify (/itcj/profile) y el conteo debe subir.
 */
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { gotoCore, mintTokenFor } = require('./_helpers');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

function adminIdFromState() {
  const statePath = path.join(__dirname, '..', '.auth', 'state.json');
  const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  const token = state.cookies.find((c) => c.name === 'itcj_token').value;
  const payload = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
  return parseInt(payload.sub, 10);
}

function pickOtherActiveUserId(excludeId) {
  const py = [
    'import sys',
    'from itcj2.database import SessionLocal',
    'from itcj2.core.models.user import User',
    'db = SessionLocal()',
    'try:',
    `    u = db.query(User).filter(User.is_active == True, User.id != ${excludeId}).order_by(User.id).first()`,
    '    if u is None:',
    "        sys.stderr.write('E2E: no hay segundo usuario activo'); sys.exit(2)",
    '    print(u.id)',
    'finally:',
    '    db.close()',
  ].join('\n');
  const out = execFileSync('docker', ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py], {
    encoding: 'utf8',
    timeout: 60_000,
  }).trim();
  const id = parseInt(out, 10);
  if (!Number.isInteger(id)) throw new Error(`pickOtherActiveUserId: salida inesperada "${out}"`);
  return id;
}

async function widgetTotal(page) {
  const txt = await page.locator('#active-users-total').textContent();
  const n = parseInt((txt || '').trim(), 10);
  return Number.isNaN(n) ? -1 : n;
}

test('el widget refleja la sesión propia y una segunda sesión /notify', async ({ page, browser }) => {
  await gotoCore(page, '/itcj/config');

  // 1) el propio shell de config conecta /notify (Task 6) => total >= 1
  await expect.poll(() => widgetTotal(page), { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  const baseline = await widgetTotal(page);

  // 2) segunda sesión: OTRO usuario (uid distinto => member distinto del zset)
  const otherId = pickOtherActiveUserId(adminIdFromState());
  const token = mintTokenFor(otherId);
  const ctx2 = await browser.newContext();
  await ctx2.addCookies([
    { name: 'itcj_token', value: token, domain: 'localhost', path: '/', httpOnly: true, secure: false, sameSite: 'Lax' },
  ]);
  const page2 = await ctx2.newPage();
  await page2.goto('/itcj/profile', { waitUntil: 'domcontentloaded' }); // profile.js conecta /notify

  // 3) el broadcast active_users actualiza el widget de la sesión 1 en vivo
  await expect.poll(() => widgetTotal(page), { timeout: 15_000 }).toBeGreaterThanOrEqual(baseline + 1);

  await ctx2.close();

  // 4) al desconectar la 2ª sesión el conteo baja (disconnect => mark_offline)
  await expect.poll(() => widgetTotal(page), { timeout: 15_000 }).toBeLessThanOrEqual(baseline);
});

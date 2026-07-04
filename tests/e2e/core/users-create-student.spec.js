// @ts-check
/**
 * Regresión BUG B: crear ESTUDIANTE desde el modal #newUserModal.
 *
 * HOY FALLA (expected failure): #username está `required` en el markup dentro
 * de #staffFields (display:none) y toggleUserTypeFields solo corre en el
 * evento change de los radios. Al abrir el modal y guardar SIN tocar los
 * radios (student ya viene checked), checkValidity() falla sobre un control
 * oculto y el POST /api/core/v2/users nunca se dispara.
 *
 * MECANISMO expected-failure: test.fail(true, ...) — el test corre siempre;
 * mientras falle, la suite queda verde. Cuando F4 arregle el bug, Playwright
 * reporta "unexpectedly passed" (exit 1): F4 DEBE borrar la línea test.fail()
 * en el mismo commit del fix.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
// 8 dígitos únicos por corrida (create_user exige exactamente 8 para student,
// users_admin.py:160). El backend uppercasea los nombres (users_admin.py:180).
const CONTROL_NUMBER = '98' + Date.now().toString().slice(-6);
const FULL_NAME = 'E2ECfg Estudiante';

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
db = SessionLocal()
try:
    for u in db.query(User).filter(User.first_name == 'E2ECFG').all():
        db.delete(u)
    db.commit()
finally:
    db.close()
`;

function pyInContainer(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  });
}

test.beforeAll(() => { try { pyInContainer(CLEAN_PY); } catch (_) { /* nada que limpiar */ } });
test.afterAll(() => { try { pyInContainer(CLEAN_PY); } catch (_) { /* best-effort */ } });

test('crear estudiante desde el modal dispara el POST y muestra la fila', async ({ page }) => {
  await gotoCore(page, '/itcj/config/users');
  await page.locator('button[data-bs-target="#newUserModal"]').click();
  await expect(page.locator('#newUserModal')).toBeVisible();

  // Escenario exacto del bug: NO tocar los radios (typeStudent ya viene checked).
  await page.fill('#fullName', FULL_NAME);
  await page.fill('#controlNumber', CONTROL_NUMBER);
  await page.fill('#password', 'e2e-Passw0rd!');

  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/api/core/v2/users') && r.request().method() === 'POST',
    { timeout: 5_000 } // hoy el POST nunca sale -> timeout -> FAIL esperado
  );
  await page.locator('#saveNewUserBtn').click();
  const resp = await respPromise;

  expect(resp.ok()).toBeTruthy(); // 201 hoy; sigue 2xx tras el flip de F4
  await expect(page.locator('#newUserModal')).toBeHidden();
  // Promesa de F4 (spec §3.7): refreshUsersTable inserta/recarga la fila nueva.
  // El backend guarda nombres en mayúsculas.
  await expect(page.locator('#usersTable')).toContainText('E2ECFG');
});

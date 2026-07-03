// @ts-check
/**
 * Regresión BUG A: presupuesto de requests del detalle de usuario.
 *
 * user_detail dispara HOY ~50 fetch/XHR a /api/core/v2/* al cargar: 3 GETs por
 * app x 2 elementos [data-app-key] por app (card + botón "Gestionar") + el N+1
 * de positions. Detrás del nginx del host de prod (limit_req 20r/s burst=40 en
 * location /) eso produce 429. El assert primario es el PRESUPUESTO (<=3 por
 * carga, spec §3.7); "cero 429" NO es assert válido (el limiter no vive en dev).
 * Estáticos, CSS y socket.io NO cuentan (el filtro es por URL /api/core/v2/ y
 * resourceType fetch/xhr).
 *
 * MECANISMO expected-failure: test.fail(true, ...) — mientras falle, la suite
 * queda verde; cuando F4 (endpoints batch C3 + selectores scoped) lo arregle,
 * Playwright reporta "unexpectedly passed": F4 DEBE borrar la línea test.fail()
 * en el mismo commit del fix.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const BUDGET = 3; // spec §3.7: <=3 fetch/XHR a /api/core/v2/* por carga

const PICK_USER_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
db = SessionLocal()
try:
    u = db.query(User).filter(User.is_active == True).order_by(User.id).first()
    print(u.id)
finally:
    db.close()
`;

let targetUserId;

test.beforeAll(() => {
  targetUserId = execFileSync(
    'docker', ['exec', '-i', BACKEND, 'python', '-c', PICK_USER_PY],
    { encoding: 'utf8', timeout: 60_000 }
  ).trim();
  if (!/^\d+$/.test(targetUserId)) throw new Error(`pick-user no devolvió id: ${targetUserId}`);
});

test('user_detail carga con <=3 fetch/XHR a /api/core/v2/*', async ({ page }) => {
  test.fail(true, 'BUG A: ~50 requests por carga hoy — F4 introduce batch y quita esta línea');

  /** @type {string[]} */
  const apiCalls = [];
  page.on('request', (req) => {
    const t = req.resourceType();
    if ((t === 'fetch' || t === 'xhr') && req.url().includes('/api/core/v2/')) {
      apiCalls.push(`${req.method()} ${new URL(req.url()).pathname}`);
    }
  });

  await gotoCore(page, `/itcj/config/users/${targetUserId}`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500); // colas secuenciales rezagadas del JS actual

  expect(
    apiCalls.length,
    `presupuesto excedido (${apiCalls.length} > ${BUDGET}):\n${apiCalls.join('\n')}`
  ).toBeLessThanOrEqual(BUDGET);
});

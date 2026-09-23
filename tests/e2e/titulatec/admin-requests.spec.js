// @ts-check
/**
 * Bandeja de solicitudes — aprobar con revisión previa, por los dos caminos.
 *
 * - SIN cuenta: se captura el NIP, se crea el acceso y la solicitud pasa a
 *   «Inscritas» con su folio.
 * - CON cuenta: no se pide NIP; se emite la liga de activación y la solicitud
 *   pasa a «Liga enviada».
 *
 * LA BANDEJA SE ALCANZA DESDE EL MENÚ, no tecleando la URL. Es deliberado: la
 * fila de `_ADMIN_NAV` (`pages/nav.py`) es lo único que hace la página
 * descubrible, `admin_nav_items` filtra con `perms & need` (que es OR), y un
 * código inexistente ahí NO da 403 — esconde la pestaña para siempre, en
 * silencio. Tecleando la URL, esa clase de fallo pasaría desapercibida.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState: undefined`
 * (RULING R1 / ver el encabezado de `_helpers.js`): en Playwright 1.61 un
 * `undefined` es un no-op, así que el contexto heredaría el storageState global
 * del proyecto — un admin de HELPDESK — en vez de quedar sin sesión.
 *
 * Los tests de este archivo corren EN ORDEN y comparten el escenario: el último
 * revisa que el NIP aprobado en el segundo no quedó en ninguna pestaña.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const {
  seedScenario, cleanupScenario, stateFor, seedPendingRequest, processFolioFor,
} = require('./_helpers');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const NIP_APROBADO = '7788';

let ctx;
let reqSinCuenta;
let reqConCuenta;

test.beforeAll(() => {
  ctx = seedScenario();
  reqSinCuenta = seedPendingRequest(ctx);
  reqConCuenta = seedPendingRequest(ctx, { withAccount: true });
});
test.afterAll(() => { cleanupScenario(ctx); });

// El storageState global es un admin de HELPDESK y require_page_app no tiene
// bypass de admin global: recibiría PageForbidden en toda página de titulatec.
test.use({ storageState: { cookies: [], origins: [] } });

/** Estado de una solicitud, leído de la base (la pantalla no es la fuente). */
function requestStatusFor(reqId) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', `
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    print(db.execute(text("SELECT status FROM titulatec_enrollment_requests WHERE id = :i"),
                     {"i": ${parseInt(String(reqId), 10)}}).scalar() or "")
finally:
    db.close()
`],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout: 60_000 }
  ).trim();
}

async function abrirBandejaDesdeElMenu(page) {
  await page.goto('/titulatec/admin/processes', { waitUntil: 'domcontentloaded' });
  await page.locator('#ttSide a[hx-get="/titulatec/admin/solicitudes"]').click();
  await page.waitForURL('**/titulatec/admin/solicitudes');
}

function esperarPost(page, ruta) {
  return page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ruta
  );
}

test('la fila "Solicitudes" del menú admin existe y lleva a su bandeja; "Encuestas" ya no es de la jefatura', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  await page.goto('/titulatec/admin/processes', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#ttSide')).toBeVisible();

  const solicitudes = page.locator('#ttSide a[hx-get="/titulatec/admin/solicitudes"]');
  await expect(solicitudes, 'falta la fila "Solicitudes" en _ADMIN_NAV').toBeVisible();
  // Tarea 8 (liberación GTV, 2026-09-15): `titulatec.survey.page.list` se le
  // REVOCÓ a la jefatura de Servicios Escolares y pasó a GTV
  // (`_helpers.js::HEAD_PERMS`); `_ADMIN_NAV` gatea "Encuestas" solo con ese
  // código, así que ahora debe estar invisible para este rol -no un item más
  // a reclamar, sino la prueba de que el reparto de permisos cambió de verdad.
  const encuestas = page.locator('#ttSide a[hx-get="/titulatec/admin/encuestas"]');
  await expect(encuestas, '"Encuestas" ya no debe ser visible para la jefatura de Escolares').toHaveCount(0);

  await solicitudes.click();
  // hx-push-url="true" en cada item del menú (base_admin.html).
  await page.waitForURL('**/titulatec/admin/solicitudes');
  // «Por revisar» es la pestaña de por omisión y trae las dos solicitudes.
  await expect(page.locator('#tt-req-tab-pending_review[aria-current="true"]')).toBeVisible();
  await expect(
    page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar"]`)
  ).toBeVisible();
  await expect(
    page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqConCuenta}/aprobar"]`)
  ).toBeVisible();

  await c.close();
});

test('aprobar SIN cuenta capturando el NIP crea el acceso y la lista en «Inscritas»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();
  await abrirBandejaDesdeElMenu(page);

  const fila = page.locator(`#tt-req-${reqSinCuenta}`);
  await expect(fila).toContainText('Sin cuenta');
  const form = fila.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar"]`);

  // El NIP es obligatorio y de 4 dígitos (D15).
  await form.locator('[name="nip"]').fill(NIP_APROBADO);
  await form.locator('[name="program_id"]').selectOption(String(ctx.programId));

  const post = esperarPost(page, `/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar`);
  await form.getByRole('button', { name: 'Aprobar y crear acceso' }).click();
  expect((await post).status()).toBe(200);

  // Se vuelve a pintar «Por revisar», donde ya no está.
  await expect(page.locator('#tt-req-tab-pending_review[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-req-${reqSinCuenta}`)).toHaveCount(0);

  // El folio se lee de la BASE, no de una copia inventada aquí.
  const folio = processFolioFor(ctx, '29990777');
  expect(folio, 'la aprobación no creó el proceso').toMatch(/^TT-/);
  await page.locator('#tt-req-tab-converted').click();
  await expect(page.locator('#tt-req-tab-converted[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-req-${reqSinCuenta}`)).toContainText(folio);

  await c.close();
});

test('aprobar CON cuenta no pide NIP y la solicitud pasa a «Liga enviada»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();
  await abrirBandejaDesdeElMenu(page);

  const fila = page.locator(`#tt-req-${reqConCuenta}`);
  await expect(fila).toContainText('Con cuenta');
  await expect(fila).toContainText('La liga de activación irá a este correo');
  const form = fila.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqConCuenta}/aprobar"]`);
  await expect(form.locator('[name="nip"]'), 'a una cuenta existente no se le fija NIP')
    .toHaveCount(0);

  const post = esperarPost(page, `/titulatec/admin/solicitudes/${reqConCuenta}/aprobar`);
  await form.getByRole('button', { name: 'Aprobar y enviar liga' }).click();
  expect((await post).status()).toBe(200);
  expect(requestStatusFor(reqConCuenta)).toBe('approved');

  await page.locator('#tt-req-tab-approved').click();
  await expect(page.locator('#tt-req-tab-approved[aria-current="true"]')).toBeVisible();
  const enviada = page.locator(`#tt-req-${reqConCuenta}`);
  await expect(enviada).toContainText('Liga enviada 1 vez');
  await expect(enviada.getByRole('button', { name: 'Reenviar liga' })).toBeVisible();
  await expect(enviada.getByRole('button', { name: 'Cancelar solicitud' })).toBeVisible();
  // Nadie quedó inscrito todavía: eso ocurre al abrir la liga.
  expect(processFolioFor(ctx, '29990778')).toBe('');

  await c.close();
});

test('el NIP nunca viaja de vuelta al navegador', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  for (const pestana of ['pending_review', 'approved', 'converted', 'all']) {
    await page.goto(`/titulatec/admin/solicitudes?status=${pestana}`,
      { waitUntil: 'domcontentloaded' });
    expect(await page.content(), `el NIP capturado quedó en la pestaña ${pestana}`)
      .not.toContain(NIP_APROBADO);
  }

  await c.close();
});

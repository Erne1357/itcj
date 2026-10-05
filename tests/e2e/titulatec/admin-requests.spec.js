// @ts-check
/**
 * Bandeja de solicitudes — aprobar con revisión previa, por los dos caminos.
 *
 * El contenedor de dev corre el modo POR OMISIÓN (spec
 * 2026-09-27-titulatec-sii-informa-se-decide, D3): no define
 * `TITULATEC_ENROLLMENT_REVIEWER` -> `sii`, ni `TITULATEC_SII_BACKEND` ->
 * `disabled`. Es el caso de producción mientras no haya acceso al SII (D11):
 * la bandeja avisa arriba (`#tt-req-sii-off`), la columna SII dice «Sin
 * consultar» y nada pide confirmación (no hay veredicto que discutir).
 *
 * - SIN cuenta: SE no captura el NIP; «Aprobar y pasar a Accesos» (el
 *   formulario manda `to_access=1`) y la solicitud pasa a «En Cómputo»
 *   (`awaiting_access`). El NIP se lo captura Centro de Cómputo en Accesos
 *   (`/titulatec/admin/accesos`, `admin-access.spec.js`).
 * - CON cuenta: no se pide NIP; se emite la liga de activación y la solicitud
 *   pasa a «Liga enviada».
 *
 * Si el contenedor se levanta con otro modo o con el SII configurado, estas
 * pruebas fallan por la razón correcta: el aviso y el botón dependen de él.
 * Tras cambiar el default hay que reiniciar backend y worker
 * (`get_settings()` vive en `lru_cache`).
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
 * Los tests de este archivo corren EN ORDEN y comparten el escenario: el
 * último revisa que ninguna pestaña de Solicitudes pinte nunca un campo de
 * NIP -ya no es de SE, así que el formulario no debe volver a traerlo.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const {
  seedScenario, cleanupScenario, stateFor, seedPendingRequest, processFolioFor,
} = require('./_helpers');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

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

// El último test lee las pestañas que dejaron los dos de aprobar (la sin
// cuenta en «En Cómputo», la con cuenta en «Liga enviada»): el orden se fija
// AQUÍ, no se hereda del `workers: 1` del config global (mismo criterio que
// `admin-access.spec.js`).
test.describe.configure({ mode: 'serial' });

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
  // La bandeja pagina de 50 en 50 y «Por revisar» va FIFO: en una base con mas
  // de 50 pendientes las dos sembradas (las mas nuevas) no estarian en la
  // pagina 1. Se buscan por prefijo de control (29990777 y 29990778).
  await page.goto('/titulatec/admin/solicitudes?q=2999077', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#tt-req-tab-pending_review[aria-current="true"]')).toBeVisible();
  await expect(
    page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar"]`)
  ).toBeVisible();
  await expect(
    page.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqConCuenta}/aprobar"]`)
  ).toBeVisible();

  await c.close();
});

test('con el SII sin configurar, aprobar SIN cuenta la pasa a Accesos y queda «En Cómputo»', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();
  await abrirBandejaDesdeElMenu(page);

  // D11: el aviso de página, arriba de la tabla. Sin él, SE vería filas «Sin
  // consultar» sin saber que es porque no hay SII, no porque falte consultar.
  const aviso = page.locator('#tt-req-sii-off');
  await expect(aviso, 'falta el aviso de SII sin configurar').toBeVisible();
  await expect(aviso).toContainText(
    'El SII no está configurado: las solicitudes sin cuenta se aprueban pasándolas a Accesos.');

  // La columna SII (sexta, entre «Recibida» y las acciones) existe y, sin
  // consulta posible, dice «Sin consultar» y el NIP «sin revisar»; tampoco
  // ofrece consultar a un SII que no hay.
  await expect(page.locator('table.tt-req-table thead th', { hasText: /^SII$/ })).toHaveCount(1);
  const fila = page.locator(`#tt-req-${reqSinCuenta}`);
  await expect(fila).toContainText('Sin cuenta');
  const celdaSii = fila.locator(`#tt-req-sii-${reqSinCuenta}`);
  await expect(celdaSii).toContainText('Sin consultar');
  await expect(celdaSii).toContainText('NIP sin revisar');
  await expect(celdaSii.getByRole('button', { name: /Consultar al SII|Reintentar consulta/ }),
    'con el SII sin configurar no se ofrece consultarlo').toHaveCount(0);

  const form = fila.locator(`form[hx-post="/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar"]`);
  // SE no captura el NIP al aprobar: se lo captura Centro de Cómputo en Accesos.
  await expect(form.locator('[name="nip"]'), 'SE no captura el NIP al aprobar')
    .toHaveCount(0);
  // El único botón que manda `to_access`, y sin confirmación: con el SII sin
  // configurar no hay veredicto que discutir (un `hx-confirm` aquí abriría el
  // modal y el POST de abajo nunca saldría).
  await expect(form.locator('input[type="hidden"][name="to_access"]')).toHaveValue('1');
  await expect(form, 'sin SII configurado aprobar no pide confirmación')
    .not.toHaveAttribute('hx-confirm');
  await expect(fila).toContainText(
    'Centro de Cómputo le captura el NIP en Accesos; el correo sale entonces.');
  await form.locator('[name="program_id"]').selectOption(String(ctx.programId));

  const post = esperarPost(page, `/titulatec/admin/solicitudes/${reqSinCuenta}/aprobar`);
  await form.getByRole('button', { name: 'Aprobar y pasar a Accesos' }).click();
  const res = await post;
  expect(res.status()).toBe(200);
  expect(res.request().postData() || '', 'el POST debió llevar to_access=1')
    .toContain('to_access=1');

  // Se vuelve a pintar «Por revisar», donde ya no está.
  await expect(page.locator('#tt-req-tab-pending_review[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-req-${reqSinCuenta}`)).toHaveCount(0);

  // Pasarla a Accesos no crea cuenta ni proceso: eso lo hace Centro de
  // Cómputo al capturar el NIP (`admin-access.spec.js`).
  expect(processFolioFor(ctx, '29990777'), 'pasar a Accesos no debe crear el proceso')
    .toBe('');
  expect(requestStatusFor(reqSinCuenta)).toBe('awaiting_access');

  await page.locator('#tt-req-tab-awaiting_access').click();
  await expect(page.locator('#tt-req-tab-awaiting_access[aria-current="true"]')).toBeVisible();
  const enComputo = page.locator(`#tt-req-${reqSinCuenta}`);
  await expect(enComputo).toContainText('En Centro de Cómputo desde');
  // En «En Cómputo» la columna SII va compacta (ya no es trabajo de SE) y SE
  // conserva la salida si nadie opera Accesos: cancelarla (spec §11).
  await expect(enComputo.locator(`#tt-req-sii-${reqSinCuenta}.tt-sii--compact`))
    .toContainText('Sin consultar');
  await expect(enComputo.getByRole('button', { name: 'Cancelar solicitud' })).toBeVisible();

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

// Tarea 8 (2026-09-24): SE ya no captura NI conoce el NIP -lo da Centro de
// Cómputo desde su propia bandeja (`admin-access.spec.js`)-, así que ningún
// formulario de Solicitudes lleva `[name="nip"]`, en ninguna pestaña. Antes
// esta prueba buscaba un NIP concreto que SE capturaba al aprobar; ahora ese
// campo no existe aquí en absoluto, así que la prueba estructural (ningún
// `input[name="nip"]` en ninguna pestaña) es la que de verdad puede fallar si
// alguien reintroduce el campo por error. En el modo `sii` la columna SII
// habla del NIP («NIP sin revisar», «NIP en el SII: disponible»…), pero solo
// de su ESTADO: nunca un campo ni un valor.
//
// Las SEIS pestañas (spec 2026-09-27 §A5). Las que el escenario llenó -«En
// Cómputo» con la sin cuenta, «Liga enviada» con la con cuenta- se comprueban
// con su fila a la vista: sin ella, «no hay campo de NIP» sería cierto sobre
// una pestaña vacía y la prueba pasaría sin medir nada.
test('Solicitudes nunca pinta un campo de NIP, en ninguna pestaña', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('head') });
  const page = await c.newPage();

  const conFila = { awaiting_access: reqSinCuenta, approved: reqConCuenta };
  for (const pestana of ['pending_review', 'awaiting_access', 'approved', 'converted',
    'rejected', 'all']) {
    await page.goto(`/titulatec/admin/solicitudes?status=${pestana}`,
      { waitUntil: 'domcontentloaded' });
    await expect(page.locator(`#tt-req-tab-${pestana}[aria-current="true"]`)).toBeVisible();
    if (conFila[pestana]) {
      await expect(page.locator(`#tt-req-${conFila[pestana]}`),
        `la pestaña ${pestana} debió traer la fila del escenario`).toBeVisible();
    }
    await expect(page.locator('[name="nip"]'), `pestaña ${pestana} pintó un campo de NIP`)
      .toHaveCount(0);
  }

  await c.close();
});

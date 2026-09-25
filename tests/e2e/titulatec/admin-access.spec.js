// @ts-check
/**
 * Bandeja «Accesos» de Centro de Cómputo (Tarea 8, spec
 * 2026-09-24-titulatec-accesos-centro-computo) — la mitad CC del flujo
 * SE → CC. `admin-requests.spec.js` cubre el lado de Servicios Escolares
 * (aprobar sin cuenta y sin NIP → «En Cómputo»); este archivo arranca YA en
 * `awaiting_access` (`seedPendingRequest(ctx, { status: 'awaiting_access' })`)
 * para ejercer directamente `/titulatec/admin/accesos` sin repetir ese primer
 * paso, que ya prueba su propio spec.
 *
 * `TITULATEC_ENROLLMENT_REVIEWER` por omisión es `"school_services"` (modo
 * OFICIAL, `itcj2/config.py`), así que aquí CC solo DA ACCESO y DEVUELVE:
 * aprobar/rechazar/reenviar son del modo alterno y quedan fuera de esta tarea.
 *
 * El actor `cc` (`_helpers.js`) SOLO tiene los 4 permisos de esta bandeja
 * (`titulatec.enrollment_access.*`): no puede abrir `/titulatec/admin/` ni
 * `/processes` (le faltan esos permisos a propósito, a diferencia de la
 * jefatura). Por eso, a diferencia de `admin-requests.spec.js`, no hay una
 * página "hermana" desde la que llegar por el menú: se navega directo a
 * `/titulatec/admin/accesos` -la ÚNICA página que este rol puede abrir- y ahí
 * se verifica que el propio `#ttSide` la trae como su única fila.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `storageState:
 * undefined` (RULING R1 / encabezado de `_helpers.js`): en Playwright 1.61 un
 * `undefined` es un no-op y el contexto heredaría el storageState global del
 * proyecto -un admin de HELPDESK- en vez de quedar sin sesión.
 *
 * Los tests de este archivo corren EN ORDEN (`test.describe.configure({ mode:
 * 'serial' })`, revisión final) y comparten el escenario: el 2º da el NIP
 * sembrado en el 1º, el 3º devuelve la otra solicitud sembrada en el 1º, y el
 * 4º (al final A PROPÓSITO) revisa que ese NIP no quedó en ninguna pestaña de
 * Accesos -incluida "Devueltas", que solo trae una fila de verdad porque el
 * 3º ya corrió-.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const {
  seedScenario, cleanupScenario, stateFor, seedPendingRequest, processFolioFor,
} = require('./_helpers');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const NIP_DADO = '9911';
const NOTA_DEVOLUCION = 'Falta confirmar la CURP con la persona.';

let ctx;
let reqParaAcceso;
let reqParaDevolver;

test.beforeAll(() => {
  ctx = seedScenario();
  // Dos filas SIN cuenta, ya "En Cómputo" (como las deja SE al aprobar sin
  // NIP): una para dar acceso, otra para devolver -no pueden compartir fila
  // porque cada acción es una transición terminal distinta.
  reqParaAcceso = seedPendingRequest(ctx, { status: 'awaiting_access' });
  reqParaDevolver = seedPendingRequest(ctx, { status: 'awaiting_access', control: '29990779' });
});
test.afterAll(() => { cleanupScenario(ctx); });

// El storageState global es un admin de HELPDESK y require_page_app no tiene
// bypass de admin global: recibiría PageForbidden en toda página de titulatec.
test.use({ storageState: { cookies: [], origins: [] } });

// Los 4 tests son UN recorrido encadenado sobre el MISMO escenario (mismo
// patrón que `citas-autoagenda.spec.js`): el 2 da el NIP que el 3 comprueba
// que no vuelve, y el 3 necesita que el 4 (devolver) YA HAYA CORRIDO para que
// la pestaña "Devueltas" tenga una fila de verdad que revisar -si no, esa
// parte de la prueba pasa sin medir nada, con la pestaña vacía-. Eso hoy se
// cumple por el `fullyParallel: false` + `workers: 1` del config GLOBAL, que
// es de otro archivo y no sabe de esta dependencia. `mode: 'serial'` lo fija
// AQUÍ (revisión final de la ola de arreglos, punto F3.7).
test.describe.configure({ mode: 'serial' });

/** Estado + banderas de una solicitud, leídos de la base (la pantalla no es la fuente). */
function requestRowFor(reqId) {
  const out = execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', `
import json
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    row = db.execute(text(
        "SELECT status, (access_granted_at IS NOT NULL), "
        "(returned_at IS NOT NULL), COALESCE(return_note, '') "
        "FROM titulatec_enrollment_requests WHERE id = :i"),
        {"i": ${parseInt(String(reqId), 10)}}).first()
    print(json.dumps({"status": row[0], "granted": bool(row[1]),
                      "returned": bool(row[2]), "note": row[3]}) if row else "null")
finally:
    db.close()
`],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout: 60_000 }
  ).trim();
  return JSON.parse(out);
}

function esperarPost(page, ruta) {
  return page.waitForResponse(
    (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === ruta
  );
}

test('la fila "Accesos" existe en el menú, es la única que ve Centro de Cómputo, y "Por dar acceso" trae la solicitud sembrada', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('cc') });
  const page = await c.newPage();

  await page.goto('/titulatec/admin/accesos', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#ttSide')).toBeVisible();

  const accesos = page.locator('#ttSide a[hx-get="/titulatec/admin/accesos"]');
  await expect(accesos, 'falta la fila "Accesos" en _ADMIN_NAV').toBeVisible();

  // CC solo tiene los 4 permisos de Accesos: Solicitudes (Servicios
  // Escolares) no debe ser visible en su menú.
  const solicitudes = page.locator('#ttSide a[hx-get="/titulatec/admin/solicitudes"]');
  await expect(solicitudes, 'Solicitudes no debe ser visible para Centro de Cómputo')
    .toHaveCount(0);

  // Modo oficial: la pestaña de omisión es "Por dar acceso".
  await expect(page.locator('#tt-acc-tab-awaiting_access[aria-current="true"]')).toBeVisible();

  const fila = page.locator(`#tt-acc-${reqParaAcceso}`);
  await expect(fila).toContainText('Sin cuenta');
  const form = fila.locator(`form[hx-post="/titulatec/admin/accesos/${reqParaAcceso}/dar-acceso"]`);
  await expect(form.getByRole('button', { name: 'Dar acceso' })).toBeVisible();
  // Sin cuenta: hay campo de NIP, y nace vacío (el servidor nunca lo prellena).
  await expect(form.locator('[name="nip"]')).toHaveValue('');

  await c.close();
});

test('dar NIP mueve la solicitud a «Con acceso»; en la base queda "converted" y con el proceso creado', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('cc') });
  const page = await c.newPage();
  await page.goto('/titulatec/admin/accesos', { waitUntil: 'domcontentloaded' });

  // Antes de teclearlo: el NIP que se va a dar no debe estar ya en la página
  // por ningún otro motivo (control previo -mismo criterio que `_sin_nip` del
  // harness de FastAPI-, para que el "no vuelve" de más abajo compare contra
  // algo, no contra una premisa nunca verificada). `innerText`, no
  // `page.content()`: el HTML crudo es frágil -ids, teléfonos, `?v=` del
  // static versioning pueden contener "9911" por coincidencia-.
  expect(await page.locator('body').innerText(), 'el NIP no debe aparecer ANTES de darlo')
    .not.toContain(NIP_DADO);

  const fila = page.locator(`#tt-acc-${reqParaAcceso}`);
  const form = fila.locator(`form[hx-post="/titulatec/admin/accesos/${reqParaAcceso}/dar-acceso"]`);
  await form.locator('[name="nip"]').fill(NIP_DADO);

  const post = esperarPost(page, `/titulatec/admin/accesos/${reqParaAcceso}/dar-acceso`);
  await form.getByRole('button', { name: 'Dar acceso' }).click();
  expect((await post).status()).toBe(200);

  // Se vuelve a pintar "Por dar acceso", donde ya no está.
  await expect(page.locator('#tt-acc-tab-awaiting_access[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-acc-${reqParaAcceso}`)).toHaveCount(0);

  const row = requestRowFor(reqParaAcceso);
  expect(row.status, 'dar-acceso debió convertir la solicitud').toBe('converted');
  expect(row.granted, 'access_granted_at debió quedar sellado').toBe(true);

  // El folio se lee de la BASE, no de una copia inventada aquí.
  const folio = processFolioFor(ctx, '29990777');
  expect(folio, 'dar-acceso no creó el proceso').toMatch(/^TT-/);

  await page.locator('#tt-acc-tab-granted').click();
  await expect(page.locator('#tt-acc-tab-granted[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-acc-${reqParaAcceso}`)).toContainText(folio);

  await c.close();
});

test('devolver regresa la solicitud a Servicios Escolares con la nota, y desaparece de "Por dar acceso"', async ({ browser }) => {
  const c = await browser.newContext({ storageState: stateFor('cc') });
  const page = await c.newPage();
  await page.goto('/titulatec/admin/accesos', { waitUntil: 'domcontentloaded' });

  const fila = page.locator(`#tt-acc-${reqParaDevolver}`);
  const form = fila.locator(`form[hx-post="/titulatec/admin/accesos/${reqParaDevolver}/devolver"]`);
  await form.locator('[name="note"]').fill(NOTA_DEVOLUCION);

  const post = esperarPost(page, `/titulatec/admin/accesos/${reqParaDevolver}/devolver`);
  await form.getByRole('button', { name: 'Devolver a Servicios Escolares' }).click();
  expect((await post).status()).toBe(200);

  await expect(page.locator(`#tt-acc-${reqParaDevolver}`)).toHaveCount(0);

  const row = requestRowFor(reqParaDevolver);
  expect(row.status, 'devolver debe regresar la solicitud a revisión de SE').toBe('pending_review');
  expect(row.returned).toBe(true);
  expect(row.note).toBe(NOTA_DEVOLUCION);

  // "Devueltas" la sigue mostrando: `returned_at` no depende del estado actual.
  await page.locator('#tt-acc-tab-returned').click();
  await expect(page.locator('#tt-acc-tab-returned[aria-current="true"]')).toBeVisible();
  await expect(page.locator(`#tt-acc-${reqParaDevolver}`)).toContainText(NOTA_DEVOLUCION);

  await c.close();

  // Cierra el círculo SE -> CC -> SE: la jefatura la ve de vuelta en "Por
  // revisar", con la nota de Centro de Cómputo.
  const c2 = await browser.newContext({ storageState: stateFor('head') });
  const page2 = await c2.newPage();
  await page2.goto('/titulatec/admin/solicitudes?status=pending_review',
    { waitUntil: 'domcontentloaded' });
  const filaSE = page2.locator(`#tt-req-${reqParaDevolver}`);
  await expect(filaSE).toContainText('Devuelta por Centro de Cómputo');
  await expect(filaSE).toContainText(NOTA_DEVOLUCION);
  await c2.close();
});

test('el NIP nunca vuelve al navegador en ninguna pestaña de Accesos', async ({ browser }) => {
  // Precondición, ANTES de mirar la pantalla: si esto no es 'converted' (el
  // test de "dar NIP" no corrió antes, o falló en silencio) lo que sigue
  // revisa una pestaña vacía y "pasa" sin haber medido nada. Va DESPUÉS del
  // de "devolver" (arriba) a propósito: así "returned" también trae una fila
  // de verdad, no una pestaña vacía donde cualquier "no contiene el NIP" es
  // trivialmente cierto.
  expect(requestRowFor(reqParaAcceso).status,
    'el escenario debió dejar la solicitud "converted" antes de este test')
    .toBe('converted');
  expect(requestRowFor(reqParaDevolver).returned,
    'el escenario debió dejar la otra solicitud devuelta antes de este test')
    .toBe(true);

  const c = await browser.newContext({ storageState: stateFor('cc') });
  const page = await c.newPage();

  for (const pestana of ['awaiting_access', 'granted', 'returned']) {
    await page.goto(`/titulatec/admin/accesos?status=${pestana}`,
      { waitUntil: 'domcontentloaded' });
    if (pestana === 'granted') {
      await expect(page.locator(`#tt-acc-${reqParaAcceso}`), 'la fila con el NIP dado debe estar aquí')
        .toBeVisible();
    }
    if (pestana === 'returned') {
      await expect(page.locator(`#tt-acc-${reqParaDevolver}`), 'la fila devuelta debe estar aquí')
        .toBeVisible();
    }
    expect(await page.locator('body').innerText(), `el NIP dado quedó en la pestaña ${pestana}`)
      .not.toContain(NIP_DADO);
    // Un campo de NIP puede existir (p. ej. "Reasignar NIP" en «Con acceso»,
    // con el correo pausado en dev), pero nunca trae valor: el servidor no lo
    // prellena en ningún caso.
    const nipFields = page.locator('[name="nip"]');
    const n = await nipFields.count();
    for (let i = 0; i < n; i += 1) {
      await expect(nipFields.nth(i)).toHaveValue('');
    }
  }

  await c.close();
});

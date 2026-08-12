// @ts-check
// admin/assign-tickets — #editTicketModal no debe dejar un doble scroll ni
// residuos (body.modal-open, backdrop huérfano, scrollHeight extra) al cerrarse,
// ni tras navegar por morph con el modal todavía abierto.
//
// Contexto del fix: el modal usaba `modal-dialog-centered modal-xl` SIN
// `modal-dialog-scrollable` + un `max-height:70vh;overflow-y:auto` inline en
// `.modal-body` — eso crea DOS scrollbars (la del documento, reservada por
// `html{scrollbar-gutter:stable}`, y la del propio `.modal-body`). El fix usa
// `modal-dialog-scrollable` (scroll único dentro del modal) + libera el canal
// de `scrollbar-gutter` mientras el modal está abierto.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/assign-tickets';

/**
 * Navega a assign-tickets y espera a que cargue el array JS `allPendingTickets`
 * (fetch propio de loadPendingTickets() → GET /tickets?status=PENDING, en
 * paralelo al render server-side inicial). El botón "Vista previa / Editar"
 * busca el ticket en ESE array, no en el DOM — sin esperar el fetch, el primer
 * click puede caer antes de que exista y solo dispara el toast "Ticket no
 * encontrado".
 */
async function gotoAssignTicketsReady(page) {
  const pendingLoaded = page.waitForResponse(
    (r) => r.url().includes('/api/help-desk/v2/tickets') && /status=PENDING/.test(r.url()) && r.request().method() === 'GET'
  );
  await gotoHelpdesk(page, PAGE);
  await pendingLoaded;
}

/** Abre #editTicketModal desde la primera tarjeta de la cola. Asume que
 * gotoAssignTicketsReady() ya corrió. */
async function openEditModalFromFirstCard(page) {
  const editBtn = page.locator('#hd-tab-queue button[title="Vista previa / Editar"]').first();
  await expect(editBtn).toBeVisible();
  await editBtn.click();

  const modal = page.locator('#editTicketModal');
  await expect(modal).toBeVisible();
  return modal;
}

test.describe('assign-tickets — editTicketModal: sin scroll doble ni residuos', () => {
  test.beforeEach(async ({ request }) => {
    // Garantiza al menos un ticket PENDING en la cola (con el botón "Vista
    // previa / Editar" que abre #editTicketModal) sin depender del estado
    // acumulado por otras specs — la suite corre serial (workers: 1) contra
    // la BD dev compartida.
    const catsResp = await request.get('/api/help-desk/v2/categories?area=SOPORTE');
    expect(catsResp.ok()).toBeTruthy();
    const { categories } = await catsResp.json();
    expect(categories.length).toBeGreaterThan(0);

    const createResp = await request.post('/api/help-desk/v2/tickets', {
      data: {
        area: 'SOPORTE',
        category_id: categories[0].id,
        title: 'E2E modal scroll ' + Date.now(),
        description: 'Ticket creado por assign-tickets-modals.spec.js para probar el modal de edición.',
        priority: 'MEDIA',
      },
    });
    expect(createResp.ok()).toBeTruthy();
  });

  test('abrir y cerrar #editTicketModal no deja body.modal-open, backdrop huérfano ni scroll extra', async ({ page }) => {
    await gotoAssignTicketsReady(page);

    // El "scroll extra" del bug (dos scrollbars simultáneas: la del documento
    // — reservada por html{scrollbar-gutter:stable} — y la del propio
    // `.modal-body`) es un problema de ANCHO (dos pistas de scrollbar), no de
    // alto de contenido: el alto vertical del documento fluctúa solo con la
    // BD dev compartida (contadores/badges de otras sesiones), así que no es
    // una señal confiable aquí. Se verifica que nunca aparece scroll
    // horizontal, en vez de comparar scrollHeight antes/después.
    const noHorizontalScroll = () => page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
    );
    expect(await noHorizontalScroll()).toBe(true);

    const modal = await openEditModalFromFirstCard(page);

    // modal-dialog-scrollable: el scroll vive DENTRO del modal, no en el documento.
    await expect(modal.locator('.modal-dialog')).toHaveClass(/modal-dialog-scrollable/);

    // El `max-height:70vh;overflow-y:auto` inline del bug viejo (segunda región
    // de scroll, además de la del documento) ya no debe existir en `.modal-body`.
    const modalBodyStyle = await modal.locator('.modal-body').first().getAttribute('style');
    expect(modalBodyStyle || '').not.toMatch(/overflow|max-height/i);

    expect(await page.evaluate(() => document.body.className)).toMatch(/modal-open/);
    await expect(page.locator('.modal-backdrop')).toHaveCount(1);
    expect(await noHorizontalScroll()).toBe(true);

    await modal.locator('.btn-close').click();
    await expect(modal).toBeHidden();

    // Bootstrap quita backdrop/clase tras la transición fade — poll en vez de
    // assert inmediato.
    await expect.poll(() => page.evaluate(() => document.body.className)).not.toMatch(/modal-open/);
    await expect(page.locator('.modal-backdrop')).toHaveCount(0);
    expect(await noHorizontalScroll()).toBe(true);

    // Sin padding-right inline colgado (el "compensador" de scrollbar que
    // Bootstrap aplica al body mientras el modal está abierto).
    const bodyPaddingRight = await page.evaluate(() => document.body.style.paddingRight);
    expect(bodyPaddingRight === '' || bodyPaddingRight === '0px').toBeTruthy();
  });

  test('navegar por morph con el modal abierto deja el body limpio en la página destino', async ({ page }) => {
    await gotoAssignTicketsReady(page);

    const modal = await openEditModalFromFirstCard(page);
    expect(await page.evaluate(() => document.body.className)).toMatch(/modal-open/);

    // Morph a otra página CON el modal todavía abierto — HelpdeskPage.teardown()
    // debe cerrar modales huérfanos (closeOpenModals(), arreglado en un commit
    // previo) antes de que el nuevo contenido entre.
    await page.evaluate(() => window.HelpdeskPage.navigate('/help-desk/admin/tickets-list'));

    await expect(page).toHaveURL(/\/help-desk\/admin\/tickets-list$/);
    await expect(page.locator('main[data-hd-page="admin_tickets_list"]')).toBeAttached();

    await expect.poll(() => page.evaluate(() => document.body.className)).not.toMatch(/modal-open/);
    await expect(page.locator('.modal-backdrop')).toHaveCount(0);
    // El morph reemplaza el <body> completo: el modal viejo no debe sobrevivir.
    await expect(page.locator('#editTicketModal')).toHaveCount(0);
    void modal; // referenciado solo para dejar constancia de que se abrió antes del morph
  });
});

// Regresión del reporte del 2026-08-11: con modales APILADOS, Bootstrap 5 no
// lleva la cuenta de cuántos hay abiertos y al cerrar el de encima quita
// `modal-open` del <body> aunque el de abajo siga visible. Toda la compensación
// de helpdesk.css cuelga de esa clase, así que al perderla el padding-right
// inline de Bootstrap vuelve a aplicar y el contenido se encoge 15px de golpe
// (medido: main pasa de 1425 a 1410), además de reaparecer el canal de
// scrollbar reservado como una barra inerte.
test.describe('modales apilados — sin salto ni scroll fantasma', () => {
  const PAGINA = '/help-desk/inventory/items/create';

  test('cerrar el modal de encima no encoge el contenido ni pierde modal-open', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoHelpdesk(page, PAGINA);

    const hayDos = await page.evaluate(() =>
      !!document.getElementById('createInactiveUserModal') && !!document.getElementById('successModal'));
    test.skip(!hayDos, 'esta página no tiene dos modales que apilar');

    const medidas = await page.evaluate(async () => {
      const main = document.querySelector('main.container-fluid');
      const ancho = () => Math.round(main.getBoundingClientRect().width);
      const espera = (ms) => new Promise((r) => setTimeout(r, ms));
      const m1 = document.getElementById('createInactiveUserModal');
      const m2 = document.getElementById('successModal');

      const pasos = [{ etapa: 'inicio', ancho: ancho(), modalOpen: document.body.classList.contains('modal-open') }];
      bootstrap.Modal.getOrCreateInstance(m1).show();
      await espera(600);
      pasos.push({ etapa: 'uno', ancho: ancho(), modalOpen: document.body.classList.contains('modal-open') });
      bootstrap.Modal.getOrCreateInstance(m2).show();
      await espera(600);
      pasos.push({ etapa: 'dos', ancho: ancho(), modalOpen: document.body.classList.contains('modal-open') });
      bootstrap.Modal.getOrCreateInstance(m2).hide();
      await espera(800);
      pasos.push({ etapa: 'cierra el de encima', ancho: ancho(), modalOpen: document.body.classList.contains('modal-open') });
      bootstrap.Modal.getOrCreateInstance(m1).hide();
      await espera(800);
      pasos.push({ etapa: 'todo cerrado', ancho: ancho(), modalOpen: document.body.classList.contains('modal-open') });
      return pasos;
    });

    const anchos = medidas.map((m) => m.ancho);
    expect(Math.max(...anchos) - Math.min(...anchos), 'el contenido no debe saltar en ningún paso').toBe(0);

    const trasCerrarElDeEncima = medidas.find((m) => m.etapa === 'cierra el de encima');
    expect(trasCerrarElDeEncima.modalOpen, 'modal-open debe seguir puesto mientras quede un modal abierto').toBe(true);

    const todoCerrado = medidas.find((m) => m.etapa === 'todo cerrado');
    expect(todoCerrado.modalOpen, 'al cerrar el último sí debe quitarse').toBe(false);
  });

  test('al cerrar todos no queda backdrop ni overflow colgado', async ({ page }) => {
    await gotoHelpdesk(page, PAGINA);
    const hayDos = await page.evaluate(() =>
      !!document.getElementById('createInactiveUserModal') && !!document.getElementById('successModal'));
    test.skip(!hayDos, 'esta página no tiene dos modales que apilar');

    const estado = await page.evaluate(async () => {
      const espera = (ms) => new Promise((r) => setTimeout(r, ms));
      const m1 = document.getElementById('createInactiveUserModal');
      const m2 = document.getElementById('successModal');
      bootstrap.Modal.getOrCreateInstance(m1).show();
      await espera(500);
      bootstrap.Modal.getOrCreateInstance(m2).show();
      await espera(500);
      bootstrap.Modal.getOrCreateInstance(m2).hide();
      await espera(700);
      bootstrap.Modal.getOrCreateInstance(m1).hide();
      await espera(900);
      return {
        backdrops: document.querySelectorAll('.modal-backdrop').length,
        modalOpen: document.body.classList.contains('modal-open'),
        overflow: document.body.style.overflow,
        abiertos: document.querySelectorAll('.modal.show').length,
      };
    });

    expect(estado.abiertos).toBe(0);
    expect(estado.backdrops).toBe(0);
    expect(estado.modalOpen).toBe(false);
    expect(estado.overflow).toBe('');
  });
});

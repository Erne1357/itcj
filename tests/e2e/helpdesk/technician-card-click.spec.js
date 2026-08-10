// @ts-check
// Dashboard de técnico: la tarjeta completa (macro ticket_card) ahora es un
// <a href> boosteado al detalle del ticket (antes href=None → <div> + botón
// redundante "Ver Detalle" superpuesto sobre un cursor:pointer que mentía).
//
// El slot de acciones (Iniciar/Resolver/Tomar) vive DENTRO de ese <a>. Su
// wrapper hace stopPropagation() + preventDefault(): stopPropagation() por sí
// solo NO cancela la navegación del <a> ancestro (el navegador decide la
// acción por defecto según el árbol DOM, no según hasta dónde llegó la
// propagación del evento JS) — sin preventDefault() un click en "Iniciar"
// abriría su modal Y ADEMÁS navegaría al detalle. Este spec protege eso.
const { test, expect } = require('@playwright/test');
const { gotoHelpdeskAs } = require('./_helpers');

const PAGE = '/help-desk/technician/dashboard';
const TECH_USER_ID = 8275; // usuario con rol tech_soporte

// Una entrada por pestaña del dashboard: botón de tab, contenedor de tarjetas
// y (si aplica) el botón de acción esperado + cómo verificar su efecto sin
// depender de que exista una pestaña concreta con datos en la BD de prueba.
const TABS = [
  { tabBtn: 'queue-tab', container: 'hd-tab-queue', actionText: 'Iniciar', effect: { kind: 'modal', modalId: 'startWorkModal' } },
  { tabBtn: 'team-tab', container: 'hd-tab-team', actionText: 'Tomar', effect: { kind: 'modal', modalId: 'selfAssignModal' } },
  { tabBtn: 'working-tab', container: 'hd-tab-working', actionText: 'Resolver', effect: { kind: 'tab', paneId: 'resolve', tabItemId: 'resolveTabItem' } },
  { tabBtn: 'history-tab', container: 'hd-tab-history', actionText: null, effect: null },
];

async function activateTab(page, tabBtnId, containerId) {
  if (tabBtnId !== 'queue-tab') {
    await page.click('#' + tabBtnId);
  }
  await expect(page.locator('#' + containerId)).toBeVisible();
}

test.describe('technician dashboard — tarjeta completa clickeable al detalle', () => {
  test('a.hd-ticket-card boosteado con href al detalle; click en el cuerpo navega sin recarga completa', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);

    let card = null;
    for (const t of TABS) {
      await activateTab(page, t.tabBtn, t.container);
      const candidate = page.locator('#' + t.container).locator('.hd-ticket-card').first();
      if (await candidate.count() > 0) { card = candidate; break; }
    }
    test.skip(!card, 'No hay tickets en ninguna pestaña del dashboard de técnico');

    const tagName = await card.evaluate((el) => el.tagName.toLowerCase());
    expect(tagName).toBe('a');
    expect(await card.getAttribute('hx-boost')).toBe('true');
    const href = await card.getAttribute('href');
    expect(href).toMatch(/^\/help-desk\/user\/tickets\/\d+\?from=technician$/);

    // Click en el título (fuera de la zona de acciones) para no disparar un modal.
    await card.locator('.hd-ticket-card__title').click();

    await expect(page).toHaveURL(/\/help-desk\/user\/tickets\/\d+\?from=technician$/);
    await expect(page.locator('main[data-hd-page="user_ticket_detail"]')).toBeAttached();
    expect(await page.evaluate(() => window.__booted)).toBe(true); // sin recarga completa
  });

  test('click en el botón de acción (Iniciar/Resolver/Tomar) abre su modal/tab y NO navega', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);
    const startUrl = page.url();

    let found = null;
    for (const t of TABS) {
      if (!t.actionText) continue;
      await activateTab(page, t.tabBtn, t.container);
      const container = page.locator('#' + t.container);
      const cardWithBtn = container
        .locator('.hd-ticket-card')
        .filter({ has: page.locator('button', { hasText: t.actionText }) })
        .first();
      if (await cardWithBtn.count() > 0) { found = { def: t, card: cardWithBtn }; break; }
    }
    test.skip(!found, 'Ninguna pestaña tiene tickets con botón de acción (Iniciar/Resolver/Tomar)');

    await found.card.locator('button', { hasText: found.def.actionText }).click();

    if (found.def.effect.kind === 'modal') {
      await expect(page.locator('#' + found.def.effect.modalId)).toHaveClass(/show/, { timeout: 5_000 });
    } else {
      // "Resolver" no abre un modal real: activa la pestaña "resolve" (Bootstrap Tab).
      await expect(page.locator('#' + found.def.effect.tabItemId)).not.toHaveClass(/d-none/);
      await expect(page.locator('#' + found.def.effect.paneId)).toHaveClass(/active/);
    }

    expect(page.url()).toBe(startUrl); // NO navegó al detalle — protege el preventDefault()
  });

  test('ya no existe ningún botón "Ver Detalle" dentro de las tarjetas del dashboard de técnico', async ({ page }) => {
    await gotoHelpdeskAs(page, TECH_USER_ID, PAGE);
    const verDetalle = page.locator('#technicianTabContent .hd-ticket-card', { hasText: 'Ver Detalle' });
    await expect(verDetalle).toHaveCount(0);
  });
});

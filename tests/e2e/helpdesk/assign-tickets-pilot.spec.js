// @ts-check
// Piloto de arquitectura de componentes server-side + show/hide client-side
// sobre admin/assign-tickets. Valida: render server-side con macros
// (.hd-ticket-card / .hd-empty-state), que el fragmento HTMX devuelve HTML
// sin <html> y que el GET completo devuelve la página con <html>.
const { test, expect } = require('@playwright/test');
const { gotoHelpdesk } = require('./_helpers');

const PAGE = '/help-desk/admin/assign-tickets';

test.describe('pilot — assign-tickets (componentes server-side + show/hide)', () => {
    test('#hd-tab-queue visible con .hd-ticket-card o .hd-empty-state; si hay tarjetas existe botón Asignar', async ({ page }) => {
        await gotoHelpdesk(page, PAGE);

        const queueContainer = page.locator('#hd-tab-queue');
        await expect(queueContainer).toBeVisible();

        const cards = queueContainer.locator('.hd-ticket-card');
        const cardCount = await cards.count();

        if (cardCount > 0) {
            await expect(cards.first()).toBeVisible();
            // Debe existir al menos un botón "Asignar" en la cola
            await expect(queueContainer.locator('button', { hasText: 'Asignar' }).first()).toBeVisible();
            // La clase legacy de cards JS no debe existir
            await expect(queueContainer.locator('.ticket-queue-card')).toHaveCount(0);
        } else {
            await expect(queueContainer.locator('.hd-empty-state')).toBeVisible();
        }
    });

    test('petición HTMX (HX-Request) a ?tab=queue devuelve fragmento sin <html>', async ({ request }) => {
        const frag = await request.get(PAGE + '?tab=queue', {
            headers: { 'HX-Request': 'true' },
            maxRedirects: 0,
        });
        expect(frag.status()).toBe(200);
        const body = await frag.text();

        // Es un fragmento: no contiene estructura de documento completo
        expect(body).not.toContain('<html');
        expect(body).not.toContain('base_helpdesk');

        // Contiene tarjetas o estado vacío del servidor
        expect(
            body.includes('hd-ticket-card') || body.includes('hd-empty-state')
        ).toBeTruthy();
    });

    test('GET completo (sin HX-Request) devuelve la página con <html>', async ({ request }) => {
        const full = await request.get(PAGE, { maxRedirects: 0 });
        expect(full.status()).toBe(200);
        expect(await full.text()).toContain('<html');
    });
});

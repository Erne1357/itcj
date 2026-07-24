// @ts-check
/**
 * Helpers E2E para las páginas core (/itcj/config...). Contrato C9 del plan
 * maestro core-config-revamp.
 *
 * CORE_SHELL es un selector DUAL a propósito:
 *  - pre-F2 (shell clásico): el layout expone <aside class="config-sidebar">
 *    (itcj2/core/templates/core/config/config_base.html:43).
 *  - post-F2 (shell HTMX): el content-root expone <main id="cfgMain"
 *    data-cfg-page="..."> (contrato C2 del plan maestro).
 * Cuando F2 aterrice, [data-cfg-page] matchea primero y .config-sidebar queda
 * como fallback inofensivo — F2 NO necesita editar este archivo.
 */
const { expect } = require('@playwright/test');
const { mintTokenFor } = require('../helpdesk/_helpers');

const CORE_SHELL = '[data-cfg-page], .config-sidebar';

/**
 * Navega (full navigation) a una página core y espera el shell.
 * Instala window.__booted para que los tests de navegación boosted (F2+)
 * detecten full reloads (un reload borra el marker).
 */
async function gotoCore(page, urlPath) {
  await page.goto(urlPath, { waitUntil: 'domcontentloaded' });
  await expect(page.locator(CORE_SHELL).first()).toBeVisible();
  await page.evaluate(() => { /** @type {any} */ (window).__booted = true; });
}

module.exports = { gotoCore, mintTokenFor, CORE_SHELL };

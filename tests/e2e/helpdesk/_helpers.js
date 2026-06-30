// @ts-check
const { expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

/**
 * Mint a JWT for a specific user id INSIDE the backend container (role:'' so the
 * real DB-backed permission checks apply, not the admin bypass). Used to test
 * role-gated pages (secretary/department/technician) that the default admin
 * storageState cannot reach (those handlers require a department/role context).
 */
function mintTokenFor(userId) {
  const py = [
    'from itcj2.database import SessionLocal',
    'from itcj2.middleware import _encode_jwt',
    'from itcj2.core.models.user import User',
    'db = SessionLocal()',
    'try:',
    `    u = db.get(User, ${parseInt(userId, 10)})`,
    "    name = ' '.join(p for p in [u.first_name or '', u.last_name or ''] if p).strip() or (u.username or 'user')",
    `    print(_encode_jwt({'sub': str(${parseInt(userId, 10)}), 'role': '', 'name': name, 'cn': ''}, 12))`,
    'finally:',
    '    db.close()',
  ].join('\n');
  const out = execFileSync('docker', ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py], {
    encoding: 'utf8',
    timeout: 60_000,
  }).trim();
  if (!out || out.split('.').length !== 3) throw new Error(`mintTokenFor(${userId}) did not return a JWT`);
  return out;
}

/**
 * Navigate to a helpdesk page AUTHENTICATED AS a specific user id (overrides the
 * default admin cookie for this context). Waits for the HTMX shell to settle.
 */
async function gotoHelpdeskAs(page, userId, urlPath) {
  const token = mintTokenFor(userId);
  await page.context().addCookies([
    { name: 'itcj_token', value: token, domain: 'localhost', path: '/', httpOnly: true, secure: false, sameSite: 'Lax' },
  ]);
  await page.goto(urlPath, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-hd-page]')).toBeVisible();
  await page.evaluate(() => { window.__booted = true; });
}

/**
 * Load a helpdesk page (full navigation) and wait until the HTMX/idiomorph
 * stack is settled and the <main data-hd-page> is present.
 * Installs a window.__booted marker so boosted-navigation tests can assert that
 * no full page reload happened afterwards (a reload would clear the marker).
 */
async function gotoHelpdesk(page, urlPath) {
  await page.goto(urlPath, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main[data-hd-page]')).toBeVisible();
  await page.evaluate(() => {
    // @ts-ignore
    window.__booted = true;
  });
}

/**
 * Open a navbar dropdown by its visible label (desktop navbar). Returns the
 * <li.nav-item.dropdown> locator so callers can query items inside it.
 */
function navDropdown(page, label) {
  return page
    .locator('#navbarContent li.nav-item.dropdown')
    .filter({ has: page.locator('a.dropdown-toggle', { hasText: label }) });
}

module.exports = { gotoHelpdesk, navDropdown, mintTokenFor, gotoHelpdeskAs };

// @ts-check
/**
 * Global setup for the Helpdesk E2E suite.
 *
 * Strategy (no secret / no token ever printed to the runner stdout):
 *  1. Mint a JWT INSIDE the backend container via `docker exec ... python -c`.
 *     The inline Python finds the first ACTIVE user that holds BOTH the
 *     `helpdesk.dashboard.admin` permission (so the helpdesk nav populates)
 *     AND the DB role `admin` in app `itcj` (so /itcj/config pages render),
 *     and prints ONLY the signed token to stdout. Diagnostics go to stderr.
 *  2. Capture stdout into a Node variable. It is NEVER logged.
 *  3. Build a Playwright storageState with the `itcj_token` cookie and persist
 *     it to .auth/state.json (which is gitignored).
 *  4. Verify the cookie is accepted: GET /help-desk/ must return 200 (not 302).
 *
 * The SECRET_KEY lives only in the container env; this script never reads it.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { request } = require('@playwright/test');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';
const AUTH_DIR = path.join(__dirname, '.auth');
const STATE_PATH = path.join(AUTH_DIR, 'state.json');

// Inline Python executed inside the container. Prints ONLY the token to stdout.
// Selection is DUAL on purpose: helpdesk.dashboard.admin makes the helpdesk nav
// render, and the DB role admin@itcj is required by _ADMIN_PAGE
// (require_page_roles("itcj", ["admin"])) on every /itcj/config page
// (core/pages/config.py:40 — the JWT claim does NOT bypass it).
const MINT_PY = `
import sys
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import get_user_permissions_for_app, user_roles_in_app

db = SessionLocal()
try:
    target = None
    users = db.query(User).filter(User.is_active == True).all()
    for u in users:
        try:
            perms = get_user_permissions_for_app(db, u.id, "helpdesk")
            if "helpdesk.dashboard.admin" not in perms:
                continue
            if "admin" not in user_roles_in_app(db, u.id, "itcj"):
                continue
        except Exception:
            continue
        target = u
        break
    if target is None:
        sys.stderr.write(
            "E2E_MINT: no active user satisfies BOTH criteria:\\n"
            "  1) permission helpdesk.dashboard.admin (helpdesk nav/specs)\\n"
            "  2) DB role 'admin' in app 'itcj' (config pages use _assert_admin ->\\n"
            "     user_roles_in_app; the JWT role claim does NOT bypass it)\\n"
            "Grant the itcj admin role to your helpdesk admin user and retry.\\n"
        )
        sys.exit(2)
    parts = [target.first_name or "", target.last_name or ""]
    full_name = " ".join(p for p in parts if p).strip() or (target.username or "admin")
    from itcj2.middleware import _encode_jwt
    token = _encode_jwt({"sub": str(target.id), "role": "admin", "name": full_name, "cn": ""}, 12)
    sys.stderr.write("E2E_MINT: user_id=%s ok (dual criteria)\\n" % target.id)
    sys.stdout.write(token)
finally:
    db.close()
`;

function mintTokenInContainer() {
  // execFileSync avoids shell quoting issues with the Python source.
  // stderr is inherited so diagnostics (NOT the token) surface in the log.
  const out = execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', MINT_PY],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout: 120_000 }
  );
  const token = (out || '').trim();
  if (!token || token.split('.').length !== 3) {
    throw new Error(
      'Global setup failed: minted value does not look like a JWT (got length ' +
        (token ? token.length : 0) +
        '). Check that container "' +
        BACKEND_CONTAINER +
        '" is running and a helpdesk admin user exists.'
    );
  }
  return token;
}

async function verifyCookie(token) {
  const ctx = await request.newContext({
    baseURL: BASE_URL,
    extraHTTPHeaders: { Cookie: `itcj_token=${token}` },
  });
  try {
    // maxRedirects:0 so a login redirect surfaces as 3xx instead of following it.
    const checks = [
      ['/help-desk/', 'The minted cookie was not accepted (likely a 302 to login). Verify SECRET_KEY matches and the user has helpdesk access.'],
      ['/itcj/config', 'The minted user must hold the DB role "admin" in app "itcj" — _assert_admin (core/pages/config.py) has no JWT bypass.'],
    ];
    for (const [urlPath, hint] of checks) {
      const res = await ctx.get(urlPath, { maxRedirects: 0 });
      const status = res.status();
      if (status !== 200) {
        throw new Error(
          `Global setup auth check failed: GET ${urlPath} returned ${status} (expected 200). ${hint}`
        );
      }
    }
  } finally {
    await ctx.dispose();
  }
}

module.exports = async () => {
  if (!fs.existsSync(AUTH_DIR)) fs.mkdirSync(AUTH_DIR, { recursive: true });

  const token = mintTokenInContainer(); // captured, never logged

  // Verify BEFORE writing state so a bad token fails fast with a clear message.
  await verifyCookie(token);

  const url = new URL(BASE_URL);
  const storageState = {
    cookies: [
      {
        name: 'itcj_token',
        value: token,
        domain: url.hostname, // 'localhost'
        path: '/',
        httpOnly: true,
        secure: false,
        sameSite: 'Lax',
        // ~11h out, comfortably inside the 12h token lifetime.
        expires: Math.floor(Date.now() / 1000) + 11 * 3600,
      },
    ],
    origins: [],
  };

  fs.writeFileSync(STATE_PATH, JSON.stringify(storageState, null, 2));
  // Confirmation WITHOUT exposing the token.
  console.log(`[global-setup] auth OK — storageState written to ${path.relative(process.cwd(), STATE_PATH)}`);
};

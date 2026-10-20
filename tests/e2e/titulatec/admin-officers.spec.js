// @ts-check
/**
 * Encargados por carrera: el selector de casillas, el aviso de reactivación y
 * la edición en línea (rediseño 2026-09-17).
 *
 * POR QUÉ NO USA `seedScenario()`. Ese escenario crea una jefatura SIN puesto
 * `head_<depto>`, y `pages/officers.py::_managed_department_id` resuelve el
 * departamento gestionado precisamente por ese prefijo: con él, la pestaña le
 * respondería «Sin departamento» y esta spec no vería nada. Añadirle el
 * organigrama al escenario compartido tocaría el fixture del que dependen las
 * otras nueve specs. Así que esta trae su propio sembrado mínimo y lo borra
 * entero en `afterAll`, por id, igual que hace `responsive.spec.js`.
 *
 * QUÉ CUBRE Y QUÉ NO. Lo que pasa en el SERVIDOR -reactivar la cuenta,
 * restablecer la contraseña, no tocar a quien ya estaba activo, no salirse del
 * departamento, 404 antes de escribir- son 14 tests de
 * `tests/fastapi/titulatec/test_officers_reactivacion.py`. Aquí se mide lo
 * único que ellos no pueden ver: el filtro, el contador, el aviso previo con su
 * plural, y que la edición en línea abre con lo ya asignado marcado.
 *
 * `storageState: { cookies: [], origins: [] }`, NUNCA `undefined` (RULING R1,
 * ver el encabezado de `_helpers.js`): en Playwright 1.61 un `undefined` es un
 * no-op y el contexto heredaría el storageState global del proyecto (admin de
 * helpdesk) en vez de quedar sin sesión. La cookie se pone por test.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');

test.use({ storageState: { cookies: [], origins: [] } });

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';
const OFFICERS_URL = '/titulatec/admin/officers';
const TAG = 'E2E_TT_OFFICERS';

let ctx;

function runInContainer(py, { timeout = 90_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

/**
 * Departamento propio + jefa con puesto `head_*` (lo que exige
 * `_managed_department_id`) + tres subordinados: uno activo y dos con la cuenta
 * apagada, que es la forma real de Servicios Escolares (9 de 11 inactivos).
 */
function seed() {
  const py = `
import json
from datetime import date
# itcj2.database va PRIMERO: importar un modelo suelto antes que el paquete
# dispara el import circular de itcj2/models/__init__.py (mismo orden que usa
# el SEED_PY de _helpers.js). Sin comillas invertidas: esto vive dentro de una
# plantilla de JS.
from itcj2.database import SessionLocal
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.middleware import _encode_jwt

TAG = "${TAG}"
db = SessionLocal()
try:
    app = db.query(App).filter_by(key="titulatec").first()

    dept = Department(code=TAG.lower(), name=TAG + " departamento", is_active=True)
    db.add(dept); db.flush()

    rol = Role(name=TAG + "_head")
    db.add(rol); db.flush()
    for code in ("titulatec.officers.page.list", "titulatec.officers.api.manage",
                 "titulatec.dashboard.school_services"):
        perm = db.query(Permission).filter_by(app_id=app.id, code=code).first()
        if perm is not None:
            db.add(RolePermission(role_id=rol.id, perm_id=perm.id))

    # El puesto de la jefa: el prefijo head_ es lo que hace que
    # get_user_primary_managed_department devuelva este departamento.
    pos_head = Position(code="head_" + TAG.lower(), title=TAG + " jefatura",
                        department_id=dept.id, is_active=True, allows_multiple=True)
    db.add(pos_head); db.flush()

    jefa = User(first_name=TAG, last_name="JEFATURA", username=TAG + "_head",
                email=TAG.lower() + ".head@example.invalid", is_active=True)
    db.add(jefa); db.flush()
    db.add(UserAppRole(user_id=jefa.id, app_id=app.id, role_id=rol.id))
    db.add(UserPosition(user_id=jefa.id, position_id=pos_head.id,
                        start_date=date.today(), is_active=True))

    # Personal asignable del departamento. Los dos apagados son los que la
    # pantalla tiene que marcar y el alta tiene que reactivar.
    pos_aux = Position(code="aux_" + TAG.lower(), title=TAG + " auxiliares",
                       department_id=dept.id, is_active=True, allows_multiple=True)
    db.add(pos_aux); db.flush()

    subordinados = {}
    for etiqueta, activo in (("ACTIVA", True), ("APAGADAUNO", False), ("APAGADADOS", False)):
        u = User(first_name=TAG, last_name=etiqueta,
                 username=TAG + "_" + etiqueta.lower(),
                 email=TAG.lower() + "." + etiqueta.lower() + "@example.invalid",
                 is_active=activo)
        db.add(u); db.flush()
        db.add(UserPosition(user_id=u.id, position_id=pos_aux.id,
                            start_date=date.today(), is_active=True))
        subordinados[etiqueta] = u.id

    db.commit()
    print(json.dumps({
        "deptId": dept.id, "roleId": rol.id,
        "headId": jefa.id, "posHeadId": pos_head.id, "posAuxId": pos_aux.id,
        "users": subordinados,
        "headToken": _encode_jwt({"sub": str(jefa.id), "role": "",
                                  "name": TAG + " JEFATURA", "cn": ""}, 12),
    }))
finally:
    db.close()
`;
  return JSON.parse(runInContainer(py).trim());
}

function cleanup(c) {
  if (!c || !c.deptId) { return; }
  const ids = [c.headId].concat(Object.values(c.users)).join(',');
  const py = `
from itcj2.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    # Los puestos de encargado que la propia prueba haya creado por la UI.
    db.execute(text("DELETE FROM core_program_positions WHERE position_id IN "
                    "(SELECT id FROM core_positions WHERE department_id = :d)"), {"d": ${c.deptId}})
    db.execute(text("DELETE FROM core_user_positions WHERE position_id IN "
                    "(SELECT id FROM core_positions WHERE department_id = :d)"), {"d": ${c.deptId}})
    db.execute(text("DELETE FROM core_position_app_roles WHERE position_id IN "
                    "(SELECT id FROM core_positions WHERE department_id = :d)"), {"d": ${c.deptId}})
    db.execute(text("DELETE FROM core_positions WHERE department_id = :d"), {"d": ${c.deptId}})
    db.execute(text("DELETE FROM core_user_app_roles WHERE user_id IN (${ids})"))
    db.execute(text("DELETE FROM core_users WHERE id IN (${ids})"))
    db.execute(text("DELETE FROM core_role_permissions WHERE role_id = :r"), {"r": ${c.roleId}})
    db.execute(text("DELETE FROM core_roles WHERE id = :r"), {"r": ${c.roleId}})
    db.execute(text("DELETE FROM core_departments WHERE id = :d"), {"d": ${c.deptId}})
    db.commit()
finally:
    db.close()
`;
  runInContainer(py);
}

/** Estado de una cuenta en BD: activa y si su contraseña es la por defecto. */
function estadoCuenta(userId) {
  const out = runInContainer(`
import json
from itcj2.database import SessionLocal
from itcj2.core.models.user import User
from itcj2.core.utils.security import DEFAULT_PASSWORD, verify_nip
db = SessionLocal()
try:
    u = db.get(User, ${userId})
    print(json.dumps({"activo": bool(u.is_active),
                      "passDefault": verify_nip(DEFAULT_PASSWORD, u.password_hash or "")}))
finally:
    db.close()
`).trim();
  return JSON.parse(out);
}

test.beforeAll(() => { ctx = seed(); });
test.afterAll(() => { cleanup(ctx); });

test.beforeEach(async ({ context }) => {
  await context.addCookies([{
    name: 'itcj_token', value: ctx.headToken,
    domain: 'localhost', path: '/', httpOnly: true, sameSite: 'Lax',
  }]);
});

test('el selector reemplaza al <select multiple> y marca las cuentas inactivas', async ({ page }) => {
  await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });

  await expect(page.locator('select')).toHaveCount(0);
  const usuarios = page.locator('[data-tt-picker]').first();
  await expect(usuarios.locator('input[type="checkbox"]')).toHaveCount(4);   // jefa + 3
  await expect(usuarios.locator('[data-tt-picker-inactive="1"]')).toHaveCount(2);
  await expect(usuarios.locator('.tt-picker-flag').first()).toHaveText('Inactiva');
});

test('el buscador filtra y no esconde lo ya elegido', async ({ page }) => {
  await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });
  const usuarios = page.locator('[data-tt-picker]').first();

  // Por `value`, no por texto: `User.full_name` es "APELLIDO NOMBRE"
  // (`core/models/user.py:87`), así que la fila dice "APAGADAUNO <TAG>".
  await page.locator('input[value="' + ctx.users.APAGADAUNO + '"]').check();
  await usuarios.locator('[data-tt-picker-search]').fill('activa');

  // Coincide por texto; y el elegido sigue visible aunque NO coincida, o el
  // usuario creería que se deseleccionó.
  await expect(usuarios.locator('.tt-picker-row:visible')).toHaveCount(2);
  await expect(page.locator('input[value="' + ctx.users.APAGADAUNO + '"]')).toBeChecked();
});

test('el contador y el aviso dicen cuántas cuentas se reactivarán, con el plural correcto', async ({ page }) => {
  await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });
  const form = page.locator('[data-tt-officers="form"]');
  const aviso = form.locator('[data-tt-officers="warn"]');
  const contador = form.locator('[data-tt-picker-count]').first();

  await expect(aviso).toBeHidden();
  await expect(contador).toHaveText('0 de 4');

  await page.locator('input[value="' + ctx.users.APAGADAUNO + '"]').check();
  await expect(aviso).toBeVisible();
  await expect(aviso).toContainText('Se reactivará 1 cuenta');
  await expect(aviso).toContainText('tecno#2K');
  await expect(contador).toHaveText('1 de 4 · 1 se reactivará');

  await page.locator('input[value="' + ctx.users.APAGADADOS + '"]').check();
  await expect(aviso).toContainText('Se reactivarán 2 cuentas');

  // Una cuenta ACTIVA no suma al aviso.
  await page.locator('input[value="' + ctx.users.ACTIVA + '"]').check();
  await expect(aviso).toContainText('Se reactivarán 2 cuentas');
  await expect(contador).toHaveText('3 de 4 · 2 se reactivarán');
});

test('crear un encargado con una cuenta apagada la reactiva y lo confirma', async ({ page }) => {
  expect(estadoCuenta(ctx.users.APAGADADOS).activo,
    'la cuenta debe empezar apagada').toBe(false);

  await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('[name="name"]').fill('Encargado E2E');
  await page.locator('input[value="' + ctx.users.APAGADADOS + '"]').check();
  await page.getByRole('button', { name: 'Crear encargado' }).click();

  const tarjeta = page.locator('[data-tt-officers="reactivated"]');
  await expect(tarjeta).toBeVisible();
  await expect(tarjeta).toContainText('1 cuenta reactivada');
  await expect(tarjeta).toContainText('APAGADADOS');

  const estado = estadoCuenta(ctx.users.APAGADADOS);
  expect(estado.activo, 'la cuenta sigue apagada tras nombrarla encargado').toBe(true);
  expect(estado.passDefault, 'no se restableció la contraseña').toBe(true);

  // Y la tarjeta del encargado separa usuarios de carreras, con rótulo.
  const oficial = page.locator('.tt-off').first();
  await expect(oficial.locator('dt', { hasText: 'Usuarios' })).toBeVisible();
  await expect(oficial.locator('dt', { hasText: 'Carreras' })).toBeVisible();
  await expect(oficial).toContainText('Sin carreras asignadas');
});

test('la edición en línea abre con lo ya asignado marcado y guarda', async ({ page }) => {
  await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });

  const oficial = page.locator('.tt-off').first();
  const edicion = oficial.locator('.tt-off-edit');
  await expect(edicion).toBeHidden();

  await oficial.locator('[data-tt-officers="edit"]').click();
  await expect(edicion).toBeVisible();
  // Lo que ya tiene viene marcado: si no, guardar sin tocar nada lo borraría.
  await expect(edicion.locator('input[value="' + ctx.users.APAGADADOS + '"]')).toBeChecked();
  await expect(edicion.locator('[data-tt-picker-count]').first()).toHaveText('1 de 4');

  await edicion.locator('input[value="' + ctx.users.ACTIVA + '"]').check();
  await edicion.getByRole('button', { name: 'Guardar cambios' }).click();

  await expect(page.locator('.tt-off').first()).toContainText('ACTIVA');
  // Sumar a alguien ya activo no dispara el aviso de reactivación.
  await expect(page.locator('[data-tt-officers="reactivated"]')).toHaveCount(0);
});

test('no desborda a 360 ni a 1440', async ({ page }) => {
  for (const [w, h] of [[360, 740], [1440, 900]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto(OFFICERS_URL, { waitUntil: 'domcontentloaded' });
    // Con encargados ya creados el alta nace PLEGADA (eso es lo que devuelve la
    // lista a la primera pantalla). Se abre a propósito: el desborde hay que
    // medirlo con los selectores desplegados, que es el estado más ancho.
    await page.locator('.tt-off-new > summary').click();
    await expect(page.locator('[data-tt-picker]').first()).toBeVisible();
    const m = await page.evaluate(() => ({
      s: document.documentElement.scrollWidth, i: window.innerWidth,
    }));
    expect(m.s, `desborde a ${w}px: ${m.s} > ${m.i}`).toBeLessThanOrEqual(m.i);
  }
});

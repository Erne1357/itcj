// @ts-check
/**
 * E2E F5: organización — árbol interactivo, crear sub-depto nivel 4,
 * confirm fuerte en oficiales, position detail scope-aware.
 * Seed/cleanup con docker exec (patrón scope-inventory.spec.js).
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoCore } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

const SEED_PY = `
import json, sys
from datetime import date, timedelta
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm
from itcj2.core.services.authz_cache import invalidate_dept_map

db = SessionLocal()
def dept(code, name, parent=None, official=False):
    d = Department(code=code, name=name, parent_id=parent, is_active=True, is_official=official)
    db.add(d); db.flush(); return d
try:
    root = dept('e2e_cfg_root', 'E2E CFG ROOT')
    sub = dept('e2e_cfg_sub', 'E2E CFG SUB', root.id)
    leaf = dept('e2e_cfg_leaf', 'E2E CFG LEAF', sub.id)
    official = dept('e2e_cfg_official', 'E2E CFG OFICIAL', root.id, official=True)
    app = db.query(App).filter_by(key='helpdesk').first()
    p_sub = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.inventory.api.read.subtree').first()
    pos = Position(code='e2e_cfg_pos', title='Jefe E2E CFG', department_id=sub.id, is_active=True, allows_multiple=True)
    db.add(pos); db.flush()
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_sub.id, allow=True))
    pos_na = Position(code='e2e_cfg_pos_noanchor', title='Sin Ancla E2E', department_id=None, is_active=True, allows_multiple=True)
    db.add(pos_na); db.flush()
    db.commit()
    invalidate_dept_map()  # el seed crea depts nuevos; el mapa cacheado (TTL 300s) puede quedar stale
    sys.stdout.write(json.dumps({
        'root_id': root.id, 'sub_id': sub.id, 'leaf_id': leaf.id,
        'official_id': official.id, 'pos_id': pos.id, 'pos_na_id': pos_na.id,
    }))
finally:
    db.close()
`;

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.services.authz_cache import invalidate_dept_map
db = SessionLocal()
try:
    for pos in db.query(Position).filter(Position.code.like('e2e_cfg_%')).all():
        for pp in db.query(PositionAppPerm).filter_by(position_id=pos.id).all(): db.delete(pp)
        for up in db.query(UserPosition).filter_by(position_id=pos.id).all(): db.delete(up)
        db.delete(pos)
    depts = db.query(Department).filter(Department.code.like('e2e_cfg_%')).all()
    # hijos antes que padres (profundidad descendente por parent chain)
    def depth(d, seen=None):
        seen = seen or set()
        n, cur = 0, d
        while cur.parent_id and cur.parent_id not in seen and n < 32:
            seen.add(cur.id); cur = db.get(Department, cur.parent_id); n += 1
        return n
    for d in sorted(depts, key=depth, reverse=True):
        db.delete(d)
    db.commit()
    invalidate_dept_map()  # los depts seeded ya no existen; el mapa cacheado quedaría stale para el siguiente run
finally:
    db.close()
`;

function pyInContainer(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  });
}

/** @type {{root_id:number, sub_id:number, leaf_id:number, official_id:number, pos_id:number, pos_na_id:number}} */
let seed;

test.beforeAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* nada que limpiar */ }
  seed = JSON.parse(pyInContainer(SEED_PY).trim());
  if (!seed.root_id) throw new Error('seed no devolvió ids');
});

test.afterAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* best-effort */ }
});

test('árbol: expandir por niveles y búsqueda auto-expande matches', async ({ page }) => {
  await gotoCore(page, '/itcj/config/departments');
  const tree = page.locator('#deptTree');
  await expect(tree.locator(`[data-node-id="${seed.root_id}"]`)).toBeVisible();

  // raíz expandida por defecto → sub visible; leaf (nivel 2) aún oculto
  await expect(tree.getByText('E2E CFG SUB')).toBeVisible();
  await expect(tree.getByText('E2E CFG LEAF')).toBeHidden();

  // expandir sub → leaf visible
  await tree.locator(`[data-tree-action="toggle"][data-dept-id="${seed.sub_id}"]`).click();
  await expect(tree.getByText('E2E CFG LEAF')).toBeVisible();

  // colapsar sub → leaf oculto de nuevo
  await tree.locator(`[data-tree-action="toggle"][data-dept-id="${seed.sub_id}"]`).click();
  await expect(tree.getByText('E2E CFG LEAF')).toBeHidden();

  // búsqueda auto-expande la cadena de ancestros del match
  await page.fill('#deptTreeSearch', 'e2e cfg leaf');
  await expect(tree.getByText('E2E CFG LEAF')).toBeVisible();

  // badge Oficial en el nodo oficial
  await page.fill('#deptTreeSearch', 'e2e cfg oficial');
  const officialNode = tree.locator(`[data-node-id="${seed.official_id}"]`);
  await expect(officialNode.locator('.dept-badge-official')).toHaveText('Oficial');
});

test('crear sub-departamento de nivel 4 desde el nodo hoja', async ({ page }) => {
  await gotoCore(page, '/itcj/config/departments');
  const tree = page.locator('#deptTree');

  // llegar al leaf (nivel 2): buscar lo auto-expande
  await page.fill('#deptTreeSearch', 'e2e cfg leaf');
  await expect(tree.getByText('E2E CFG LEAF')).toBeVisible();

  // abrir el modal de crear con el leaf como padre preseleccionado
  await tree.locator(`[data-tree-action="create-child"][data-dept-id="${seed.leaf_id}"]`).click();
  const modal = page.locator('#createDepartmentModal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#deptParent')).toHaveValue(String(seed.leaf_id));

  // el selector de padre NO está capado: contiene al leaf (nivel 2) indentado
  const leafOption = modal.locator(`#deptParent option[value="${seed.leaf_id}"]`);
  await expect(leafOption).toHaveText(/E2E CFG LEAF/);

  await modal.locator('#deptCode').fill('e2e_cfg_l4');
  await modal.locator('#deptName').fill('E2E CFG NIVEL4');
  await modal.locator('button[type="submit"]').click();
  await expect(modal).toBeHidden();

  // el nodo nuevo (nivel 3 = 4º nivel del árbol) aparece bajo el leaf
  await page.fill('#deptTreeSearch', 'e2e cfg nivel4');
  const newNode = tree.locator('.dept-node', { hasText: 'E2E CFG NIVEL4' }).first();
  await expect(newNode).toBeVisible();
  await expect(newNode.locator('.badge', { hasText: 'Nivel 3' })).toBeVisible();
  // creado desde la UI → NO oficial
  await expect(newNode.locator('.dept-badge-official')).toHaveCount(0);
});

test('editar departamento oficial exige confirmación fuerte (D4)', async ({ page }) => {
  await gotoCore(page, '/itcj/config/departments');
  const tree = page.locator('#deptTree');
  await page.fill('#deptTreeSearch', 'e2e cfg oficial');
  await tree.locator(`[data-tree-action="edit"][data-dept-id="${seed.official_id}"]`).click();

  const modal = page.locator('#editDepartmentModal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('#editDeptName')).toHaveValue('E2E CFG OFICIAL');
  // anti-ciclo: el propio departamento no aparece como padre elegible
  await expect(modal.locator(`#editDeptParent option[value="${seed.official_id}"]`)).toHaveCount(0);

  await modal.locator('#editDeptName').fill('E2E CFG OFICIAL v2');
  await modal.locator('button[type="submit"]').click();

  // AppModal de advertencia fuerte (montado en <body>)
  const confirmDialog = page.locator('.modal.show', { hasText: 'organigrama institucional' });
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole('button', { name: 'Sí, modificar' }).click();

  await expect(modal).toBeHidden();
  await page.fill('#deptTreeSearch', 'e2e cfg oficial');
  await expect(tree.getByText('E2E CFG OFICIAL v2')).toBeVisible();
});

test('desactivar departamento no oficial pide confirmación normal', async ({ page }) => {
  await gotoCore(page, '/itcj/config/departments');
  const tree = page.locator('#deptTree');
  await page.fill('#deptTreeSearch', 'e2e cfg nivel4');
  // Scope al ROW del nodo (no al .dept-node, cuyo subtree incluiría los botones
  // de los ancestros auto-mostrados por la búsqueda → click en múltiples).
  const node = tree.locator('.dept-node-row', { hasText: 'E2E CFG NIVEL4' });
  await expect(node).toBeVisible();
  await node.locator('[data-tree-action="deactivate"]').click();

  const confirmDialog = page.locator('.modal.show', { hasText: 'Desactivar departamento' });
  await expect(confirmDialog).toBeVisible();
  // confirm normal: NO contiene la advertencia institucional
  await expect(confirmDialog).not.toContainText('organigrama institucional');
  await confirmDialog.getByRole('button', { name: 'Desactivar' }).click();
  await expect(confirmDialog).toBeHidden();
});

test('department detail: puestos, badge oficial ausente en no-oficial y user picker vivo', async ({ page }) => {
  await gotoCore(page, `/itcj/config/departments/${seed.sub_id}`);
  const main = page.locator('#cfgMain');

  await expect(main.getByText('E2E CFG SUB').first()).toBeVisible();
  // no-oficial → sin badge
  await expect(main.locator('#deptOfficialBadge')).toBeHidden();

  // card del puesto sembrado con acción de asignar usuario
  const card = main.locator('[data-position-id]', { hasText: 'Jefe E2E CFG' }).first();
  await expect(card).toBeVisible();
  await card.locator('[data-pos-action="assign"]').click();

  const modal = page.locator('#assignUserModal');
  await expect(modal).toBeVisible();
  // el picker carga usuarios reales (staff): más de la opción placeholder
  await expect
    .poll(async () => modal.locator('#userSelect option').count(), { timeout: 7000 })
    .toBeGreaterThan(1);

  // los modales muertos ya no existen en el DOM
  await expect(page.locator('#managePositionModal')).toHaveCount(0);
  await expect(page.locator('#managePositionAppsModal')).toHaveCount(0);
});

test('position detail: render base, modal de apps con roles por fetch, sin confirmModal bespoke', async ({ page }) => {
  await gotoCore(page, `/itcj/config/positions/${seed.pos_id}`);
  const main = page.locator('#cfgMain');

  await expect(main.locator('#positionName')).toHaveText('Jefe E2E CFG');
  await expect(main.locator('#displayCode')).toHaveText('e2e_cfg_pos');

  // el modal bespoke de confirmación ya no existe (se usa AppModal)
  await expect(page.locator('#confirmModal')).toHaveCount(0);

  // gestionar apps: la lista de apps carga y el select de roles se llena por fetch
  await main.locator('#manageAppsBtn').click();
  const modal = page.locator('#manageAppsModal');
  await expect(modal).toBeVisible();
  await modal.locator('.app-item[data-app-key="helpdesk"]').click();
  await expect
    .poll(async () => modal.locator('#roleToAssign option').count(), { timeout: 7000 })
    .toBeGreaterThan(1);
});

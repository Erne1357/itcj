// @ts-check
/**
 * E2E: scope por sub-departamento en el inventario de helpdesk.
 *
 * Siembra (dentro del contenedor) un subárbol e2e_scope_root → sub → leaf y una
 * rama hermana e2e_scope_other, un usuario "jefe" anclado en `sub` con el permiso
 * helpdesk.inventory.api.read.subtree (+ la page perm), y un grupo de inventario
 * por departamento. Verifica en el navegador que el jefe VE los grupos de su
 * subárbol (sub + leaf) pero NO el de la otra rama.
 */
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const { gotoHelpdeskAs } = require('./_helpers');

const BACKEND = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

const SEED_PY = `
import sys
from datetime import date, timedelta
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm
from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup

db = SessionLocal()
def dept(code, parent=None):
    d = Department(code=code, name=code, parent_id=parent, is_active=True)
    db.add(d); db.flush(); return d
def grp(code, name, dept_id, uid):
    g = InventoryGroup(code=code, name=name, department_id=dept_id, group_type='CLASSROOM', is_active=True, created_by_id=uid)
    db.add(g); db.flush(); return g
try:
    app = db.query(App).filter_by(key='helpdesk').first()
    p_sub = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.inventory.api.read.subtree').first()
    p_page = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.inventory_groups.page.list').first()
    root = dept('e2e_scope_root'); sub = dept('e2e_scope_sub', root.id)
    leaf = dept('e2e_scope_leaf', sub.id); other = dept('e2e_scope_other', root.id)
    u = User(first_name='E2E', last_name='ScopeHead', username='e2e_scope_head', is_active=True)
    db.add(u); db.flush()
    pos = Position(code='e2e_scope_pos', title='Jefe e2e', department_id=sub.id, is_active=True, allows_multiple=True)
    db.add(pos); db.flush()
    db.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today()-timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_sub.id, allow=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_page.id, allow=True))
    grp('e2e_scope_sub_grp', 'E2E SUB GRP', sub.id, u.id)
    grp('e2e_scope_leaf_grp', 'E2E LEAF GRP', leaf.id, u.id)
    grp('e2e_scope_other_grp', 'E2E OTHER GRP', other.id, u.id)
    db.commit()
    sys.stdout.write(str(u.id))
finally:
    db.close()
`;

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm
from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
db = SessionLocal()
try:
    for g in db.query(InventoryGroup).filter(InventoryGroup.code.like('e2e_scope_%')).all(): db.delete(g)
    for pos in db.query(Position).filter(Position.code.like('e2e_scope_%')).all():
        for pp in db.query(PositionAppPerm).filter_by(position_id=pos.id).all(): db.delete(pp)
        for up in db.query(UserPosition).filter_by(position_id=pos.id).all(): db.delete(up)
        db.delete(pos)
    for u in db.query(User).filter(User.username.like('e2e_scope_%')).all(): db.delete(u)
    for d in db.query(Department).filter(Department.code.like('e2e_scope_%')).order_by(Department.parent_id.desc().nullslast()).all():
        db.delete(d)
    db.commit()
finally:
    db.close()
`;

function pyInContainer(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  });
}

let headUserId;

test.beforeAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* nada que limpiar */ }
  headUserId = pyInContainer(SEED_PY).trim();
  if (!/^\d+$/.test(headUserId)) throw new Error(`seed no devolvió user id: ${headUserId}`);
});

test.afterAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* best-effort */ }
});

test('jefe de subdepto ve su subárbol pero no la otra rama', async ({ page }) => {
  await gotoHelpdeskAs(page, headUserId, '/help-desk/inventory/groups');
  const body = page.locator('main[data-hd-page]');
  await expect(body).toContainText('E2E SUB GRP');   // su departamento
  await expect(body).toContainText('E2E LEAF GRP');  // sub-departamento (subárbol)
  await expect(body).not.toContainText('E2E OTHER GRP'); // otra rama → invisible
});

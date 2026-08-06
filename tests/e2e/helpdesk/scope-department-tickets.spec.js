// @ts-check
/**
 * E2E: el dashboard del jefe de departamento ve su SUBÁRBOL y nada más.
 *
 * Complementa a scope-inventory.spec.js (que cubre inventario) con el otro
 * consumidor del scope: la lista de tickets del jefe. Siembra
 * root → sub → leaf y una rama hermana bajo el mismo root, con la jefa anclada
 * en `sub`, y verifica en navegador real que ve los tickets de `sub` y `leaf`,
 * pero ni los de la rama hermana ni los del departamento PADRE — el scope mira
 * hacia abajo, nunca hacia arriba.
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
from itcj2.core.models.role import Role
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.services.authz_cache import invalidate_dept_map

db = SessionLocal()
def dept(code, parent=None):
    d = Department(code=code, name=code, parent_id=parent, is_active=True)
    db.add(d); db.flush(); return d
def ticket(number, title, requester_id, dept_id, cat_id):
    t = Ticket(ticket_number=number, requester_id=requester_id, requester_department_id=dept_id,
               area='SOPORTE', category_id=cat_id, priority='MEDIA', title=title,
               description='e2e scope department', status='PENDING',
               created_by_id=requester_id, updated_by_id=requester_id)
    db.add(t); db.flush(); return t
try:
    app = db.query(App).filter_by(key='helpdesk').first()
    role_head = db.query(Role).filter_by(name='department_head').first()
    p_sub = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.tickets.api.read.subtree').first()
    cat = db.query(Category).filter_by(area='SOPORTE', is_active=True).first()

    root = dept('e2e_dt_root')
    sub = dept('e2e_dt_sub', root.id)
    leaf = dept('e2e_dt_leaf', sub.id)
    sibling = dept('e2e_dt_sibling', root.id)

    boss = User(first_name='E2E', last_name='DeptHead', username='e2e_dt_boss', is_active=True)
    other = User(first_name='E2E', last_name='Ajeno', username='e2e_dt_other', is_active=True)
    db.add_all([boss, other]); db.flush()

    # El code debe empezar con head_ : get_user_managed_departments lo exige.
    pos = Position(code='head_e2e_dt_sub', title='Jefa e2e', department_id=sub.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.flush()
    db.add(UserPosition(user_id=boss.id, position_id=pos.id,
                        start_date=date.today()-timedelta(days=1), is_active=True))
    db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role_head.id))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_sub.id, allow=True))

    ticket('E2E-DT-SUB', 'E2E DT MI DEPTO', other.id, sub.id, cat.id)
    ticket('E2E-DT-LEAF', 'E2E DT SUBDEPTO', other.id, leaf.id, cat.id)
    ticket('E2E-DT-SIB', 'E2E DT RAMA HERMANA', other.id, sibling.id, cat.id)
    ticket('E2E-DT-ROOT', 'E2E DT DEPTO PADRE', other.id, root.id, cat.id)
    db.commit()
    invalidate_dept_map()  # el seed crea depts nuevos; el mapa cacheado puede estar stale
    sys.stdout.write(str(boss.id))
finally:
    db.close()
`;

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.services.authz_cache import invalidate_dept_map
db = SessionLocal()
try:
    for t in db.query(Ticket).filter(Ticket.ticket_number.like('E2E-DT-%')).all(): db.delete(t)
    for pos in db.query(Position).filter(Position.code.like('head_e2e_dt_%')).all():
        for pp in db.query(PositionAppPerm).filter_by(position_id=pos.id).all(): db.delete(pp)
        for pr in db.query(PositionAppRole).filter_by(position_id=pos.id).all(): db.delete(pr)
        for up in db.query(UserPosition).filter_by(position_id=pos.id).all(): db.delete(up)
        db.delete(pos)
    db.flush()
    for u in db.query(User).filter(User.username.like('e2e_dt_%')).all(): db.delete(u)
    db.flush()
    for d in db.query(Department).filter(Department.code.like('e2e_dt_%')).order_by(Department.parent_id.desc().nullslast()).all():
        db.delete(d)
    db.commit()
    invalidate_dept_map()
finally:
    db.close()
`;

function pyInContainer(src) {
  return execFileSync('docker', ['exec', '-i', BACKEND, 'python', '-c', src], {
    encoding: 'utf8', timeout: 60_000,
  });
}

let bossUserId;

test.beforeAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* nada que limpiar */ }
  bossUserId = pyInContainer(SEED_PY).trim();
  if (!/^\d+$/.test(bossUserId)) throw new Error(`seed no devolvió user id: ${bossUserId}`);
});

test.afterAll(() => {
  try { pyInContainer(CLEAN_PY); } catch (_) { /* best-effort */ }
});

test('el jefe ve los tickets de su subárbol, no los de la rama hermana ni los del padre', async ({ page }) => {
  await gotoHelpdeskAs(page, bossUserId, '/help-desk/department/');
  const body = page.locator('main[data-hd-page]');

  await expect(body).toContainText('E2E DT MI DEPTO');       // su departamento
  await expect(body).toContainText('E2E DT SUBDEPTO');       // sub-departamento
  await expect(body).not.toContainText('E2E DT RAMA HERMANA');
  await expect(body).not.toContainText('E2E DT DEPTO PADRE'); // nunca hacia arriba
});

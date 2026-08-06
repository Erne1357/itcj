// @ts-check
/**
 * E2E: "Mis Tickets" sobrevive a un cambio de departamento.
 *
 * Reproduce el caso real: una jefa estaba adscrita a un departamento padre y se
 * movió a un sub-departamento nuevo. Sus tickets viejos conservan el
 * `requester_department_id` del padre (snapshot al crear), que ya NO está en su
 * scope `.subtree`. Deben seguir apareciendo en Mis Tickets porque son suyos.
 *
 * Verifica además el otro lado: NO se le cuela el ticket de un tercero que vive
 * en ese mismo departamento padre (la propiedad suma, no abre el subárbol hacia
 * arriba).
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
               description='e2e scope my-tickets', status='PENDING',
               created_by_id=requester_id, updated_by_id=requester_id)
    db.add(t); db.flush(); return t
try:
    app = db.query(App).filter_by(key='helpdesk').first()
    p_sub = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.tickets.api.read.subtree').first()
    p_page = db.query(Permission).filter_by(app_id=app.id, code='helpdesk.tickets.page.my_tickets').first()
    cat = db.query(Category).filter_by(area='SOPORTE', is_active=True).first()
    # padre (adscripcion anterior) -> hijo (sub-departamento nuevo)
    parent = dept('e2e_myt_parent'); child = dept('e2e_myt_child', parent.id)
    u = User(first_name='E2E', last_name='MyTickets', username='e2e_myt_boss', is_active=True)
    other = User(first_name='E2E', last_name='Ajeno', username='e2e_myt_other', is_active=True)
    db.add_all([u, other]); db.flush()
    pos = Position(code='e2e_myt_pos', title='Jefa e2e', department_id=child.id, is_active=True, allows_multiple=True)
    db.add(pos); db.flush()
    db.add(UserPosition(user_id=u.id, position_id=pos.id, start_date=date.today()-timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_sub.id, allow=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=p_page.id, allow=True))
    ticket('E2E-MYT-OLD', 'E2E MYT VIEJO', u.id, parent.id, cat.id)   # creado antes del cambio
    ticket('E2E-MYT-NEW', 'E2E MYT NUEVO', u.id, child.id, cat.id)    # creado despues
    ticket('E2E-MYT-AJN', 'E2E MYT AJENO', other.id, parent.id, cat.id)  # de un tercero, depto padre
    db.commit()
    invalidate_dept_map()  # el seed crea depts nuevos; el mapa cacheado (TTL 300s) puede estar stale
    sys.stdout.write(str(u.id))
finally:
    db.close()
`;

const CLEAN_PY = `
from itcj2.database import SessionLocal
from itcj2.core.models.department import Department
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.core.services.authz_cache import invalidate_dept_map
db = SessionLocal()
try:
    for t in db.query(Ticket).filter(Ticket.ticket_number.like('E2E-MYT-%')).all(): db.delete(t)
    for pos in db.query(Position).filter(Position.code.like('e2e_myt_%')).all():
        for pp in db.query(PositionAppPerm).filter_by(position_id=pos.id).all(): db.delete(pp)
        for up in db.query(UserPosition).filter_by(position_id=pos.id).all(): db.delete(up)
        db.delete(pos)
    db.flush()
    for u in db.query(User).filter(User.username.like('e2e_myt_%')).all(): db.delete(u)
    db.flush()
    for d in db.query(Department).filter(Department.code.like('e2e_myt_%')).order_by(Department.parent_id.desc().nullslast()).all():
        db.delete(d)
    db.commit()
    invalidate_dept_map()  # los depts seeded ya no existen; el mapa cacheado quedaria stale
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

test('los tickets creados desde el departamento anterior siguen en Mis Tickets', async ({ page }) => {
  await gotoHelpdeskAs(page, bossUserId, '/help-desk/user/my-tickets');
  const body = page.locator('main[data-hd-page]');
  await expect(body).toContainText('E2E MYT VIEJO');   // suyo, depto anterior
  await expect(body).toContainText('E2E MYT NUEVO');   // suyo, depto actual
  await expect(body).not.toContainText('E2E MYT AJENO'); // de un tercero, nunca hacia arriba
});

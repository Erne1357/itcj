// @ts-check
/**
 * Helpers de la suite E2E de AgendaTec.
 *
 * A diferencia de la suite de helpdesk, aquí NO sirve el storageState global
 * (un admin de helpdesk): estas pruebas necesitan un COORDINADOR con varias
 * carreras y una cita reservada. El escenario se siembra dentro del contenedor
 * y se limpia al terminar, para no dejar basura en la BD de dev.
 */
const { execFileSync } = require('child_process');

const BACKEND_CONTAINER = process.env.E2E_BACKEND_CONTAINER || 'itcj-backend-1';

/** Corre Python dentro del contenedor y devuelve su stdout. */
function runInContainer(py, { timeout = 120_000 } = {}) {
  return execFileSync(
    'docker',
    ['exec', '-i', BACKEND_CONTAINER, 'python', '-c', py],
    { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', timeout }
  );
}

// Marcador con el que se identifica TODO lo que crea esta suite, para poder
// borrarlo con precisión al final sin tocar datos reales.
const E2E_TAG = 'E2E_AGENDATEC';

const SEED_PY = `
import json, sys
from datetime import date, datetime, time, timedelta

from itcj2.database import SessionLocal
from itcj2.apps.agendatec.helpers import get_app_tz
from itcj2.apps.agendatec.models import (
    AgendaTecPeriodConfig, Appointment, AvailabilityWindow,
    AvailabilityWindowProgram, PeriodEnabledDay, Request, TimeSlot, TimeSlotProgram,
)
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.app import App
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.permission import Permission
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.middleware import _encode_jwt

TAG = "${E2E_TAG}"
DAY = date(2026, 9, 15)
PERMS = [
    "agendatec.slots.api.read", "agendatec.slots.api.create",
    "agendatec.slots.api.delete", "agendatec.coord_dashboard.api.read",
    "agendatec.slots.page.list",
]

db = SessionLocal()
try:
    app = db.query(App).filter_by(key="agendatec").one()

    role = db.query(Role).filter_by(name="coordinator").first()
    if role is None:
        role = Role(name="coordinator"); db.add(role); db.flush()
    for code in PERMS:
        p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
        if p is None:
            p = Permission(app_id=app.id, code=code, name=code); db.add(p); db.flush()
        if db.query(RolePermission).filter_by(role_id=role.id, perm_id=p.id).first() is None:
            db.add(RolePermission(role_id=role.id, perm_id=p.id))

    st_role = db.query(Role).filter_by(name="student").first()
    if st_role is None:
        st_role = Role(name="student"); db.add(st_role); db.flush()

    programs = []
    for name in (TAG + " Industrial", TAG + " Mecatronica", TAG + " Sistemas"):
        p = db.query(Program).filter_by(name=name).first()
        if p is None:
            p = Program(name=name); db.add(p); db.flush()
        programs.append(p)

    coord_user = User(first_name=TAG, last_name="COORD", is_active=True, role_id=role.id)
    db.add(coord_user); db.flush()
    db.add(UserAppRole(user_id=coord_user.id, app_id=app.id, role_id=role.id))
    coord = Coordinator(user_id=coord_user.id); db.add(coord); db.flush()
    for p in programs:
        db.add(ProgramCoordinator(program_id=p.id, coordinator_id=coord.id))

    student = User(first_name=TAG, last_name="ALUMNO", control_number="29990001",
                   is_active=True, role_id=st_role.id)
    db.add(student); db.flush()
    db.add(UserAppRole(user_id=student.id, app_id=app.id, role_id=st_role.id))

    # Periodo propio, ACTIVE. Se desactivan los demas y se restauran al limpiar.
    prev_active = [p.id for p in db.query(AcademicPeriod).filter_by(status="ACTIVE").all()]
    db.query(AcademicPeriod).filter(AcademicPeriod.status == "ACTIVE").update(
        {"status": "INACTIVE"}, synchronize_session=False)
    period = AcademicPeriod(code="29990", name=TAG + " periodo",
                            start_date=date(2026, 8, 1), end_date=date(2026, 12, 31),
                            status="ACTIVE")
    db.add(period); db.flush()
    tz = get_app_tz(); now = datetime.now(tz)
    db.add(AgendaTecPeriodConfig(
        period_id=period.id,
        student_admission_start=now - timedelta(days=1),
        student_admission_deadline=now + timedelta(days=60),
        max_cancellations_per_student=2,
        allow_drop_requests=True, allow_appointment_requests=True))
    db.add(PeriodEnabledDay(period_id=period.id, day=DAY))

    # Rango 09:00-10:00 @10 con las 3 carreras, y una cita en el primer slot.
    w = AvailabilityWindow(coordinator_id=coord.id, day=DAY, start_time=time(9, 0),
                           end_time=time(10, 0), slot_minutes=10)
    db.add(w); db.flush()
    for p in programs:
        db.add(AvailabilityWindowProgram(window_id=w.id, program_id=p.id))

    slots = []
    cur = datetime.combine(DAY, time(9, 0)); end = datetime.combine(DAY, time(10, 0))
    while cur + timedelta(minutes=10) <= end:
        s = TimeSlot(coordinator_id=coord.id, day=DAY, start_time=cur.time(),
                     end_time=(cur + timedelta(minutes=10)).time(), is_booked=False)
        db.add(s); slots.append(s); cur += timedelta(minutes=10)
    db.flush()
    for s in slots:
        for p in programs:
            db.add(TimeSlotProgram(slot_id=s.id, program_id=p.id))

    slots[0].is_booked = True
    r = Request(student_id=student.id, program_id=programs[0].id, period_id=period.id,
                type="APPOINTMENT", status="PENDING")
    db.add(r); db.flush()
    db.add(Appointment(request_id=r.id, student_id=student.id, coordinator_id=coord.id,
                       program_id=programs[0].id, slot_id=slots[0].id, status="SCHEDULED"))
    db.commit()

    coord_token = _encode_jwt(
        {"sub": str(coord_user.id), "role": "staff", "name": TAG + " COORD", "cn": ""}, 12)
    student_token = _encode_jwt(
        {"sub": str(student.id), "role": "student", "name": TAG + " ALUMNO",
         "cn": "29990001"}, 12)

    sys.stdout.write(json.dumps({
        "coordToken": coord_token,
        "studentToken": student_token,
        "day": str(DAY),
        "periodId": period.id,
        "coordId": coord.id,
        "programIds": [p.id for p in programs],
        "prevActivePeriods": prev_active,
    }))
finally:
    db.close()
`;

function cleanupPy(ctx) {
  return `
from itcj2.database import SessionLocal
from sqlalchemy import text

TAG = "${E2E_TAG}"
PREV = ${JSON.stringify(ctx.prevActivePeriods || [])}

db = SessionLocal()
try:
    # Orden hijos -> padres. Todo cuelga del periodo o del coordinador de prueba.
    db.execute(text("""
        DELETE FROM agendatec_appointments WHERE slot_id IN (
            SELECT id FROM agendatec_time_slots WHERE coordinator_id = :c)
    """), {"c": ${ctx.coordId}})
    db.execute(text("DELETE FROM agendatec_requests WHERE period_id = :p"),
               {"p": ${ctx.periodId}})
    db.execute(text("DELETE FROM agendatec_time_slots WHERE coordinator_id = :c"),
               {"c": ${ctx.coordId}})
    db.execute(text("DELETE FROM agendatec_availability_windows WHERE coordinator_id = :c"),
               {"c": ${ctx.coordId}})
    db.execute(text("DELETE FROM agendatec_period_enabled_days WHERE period_id = :p"),
               {"p": ${ctx.periodId}})
    db.execute(text("DELETE FROM agendatec_period_config WHERE period_id = :p"),
               {"p": ${ctx.periodId}})
    db.execute(text("DELETE FROM core_academic_periods WHERE id = :p"), {"p": ${ctx.periodId}})
    db.execute(text("DELETE FROM core_program_coordinator WHERE coordinator_id = :c"),
               {"c": ${ctx.coordId}})
    db.execute(text("DELETE FROM core_notifications WHERE user_id IN "
                    "(SELECT id FROM core_users WHERE first_name = :t)"), {"t": TAG})
    db.execute(text("DELETE FROM core_user_app_roles WHERE user_id IN "
                    "(SELECT id FROM core_users WHERE first_name = :t)"), {"t": TAG})
    db.execute(text("DELETE FROM core_coordinators WHERE id = :c"), {"c": ${ctx.coordId}})
    db.execute(text("DELETE FROM core_users WHERE first_name = :t"), {"t": TAG})
    db.execute(text("DELETE FROM core_programs WHERE name LIKE :t"), {"t": TAG + "%"})

    # Restaurar el periodo que estaba ACTIVE antes de la suite.
    if PREV:
        db.execute(text("UPDATE core_academic_periods SET status='ACTIVE' WHERE id = ANY(:ids)"),
                   {"ids": PREV})
    db.commit()
    print("E2E cleanup OK")
finally:
    db.close()
`;
}

function seedScenario() {
  const out = runInContainer(SEED_PY);
  return JSON.parse(out.trim());
}

function cleanupScenario(ctx) {
  if (!ctx || !ctx.coordId) return;
  runInContainer(cleanupPy(ctx));
}

/** storageState de Playwright a partir de un token. */
function stateFor(token, baseUrl) {
  const url = new URL(baseUrl || process.env.E2E_BASE_URL || 'http://localhost:8080');
  return {
    cookies: [{
      name: 'itcj_token',
      value: token,
      domain: url.hostname,
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax',
      expires: Math.floor(Date.now() / 1000) + 11 * 3600,
    }],
    origins: [],
  };
}

module.exports = { seedScenario, cleanupScenario, stateFor, E2E_TAG };

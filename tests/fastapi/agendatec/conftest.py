"""Fixtures de AgendaTec: BD real de Postgres con rollback por test.

El módulo no tenía ninguna cobertura antes de agosto 2026. Este harness es la
base sobre la que se apoyan el split de horarios, el scope por carrera y los
tests de regresión de los bugs confirmados por auditoría.

QUÉ HACE FALTA SABER ANTES DE ESCRIBIR UN TEST AQUÍ
---------------------------------------------------

1. `client` ata `get_db` a la MISMA sesión que `db_session`, para que los datos
   creados por las factories sean visibles al endpoint. Sin eso la app usa
   `SessionLocal` (otro pool) y no ve nada.

2. Efecto colateral de (1): con `join_transaction_mode="create_savepoint"`, el
   `db.commit()` del endpoint libera un SAVEPOINT en vez de commitear. Sirve
   para casi todo, pero **`pg_advisory_xact_lock` NO se libera dentro del test**
   y `FOR UPDATE` no compite contra nadie. Los tests de locking y concurrencia
   necesitan transacciones reales — márcalos con `@pytest.mark.real_tx` y usa
   `real_db` (ver más abajo), que limpia con DELETE explícito.

3. `auth_headers` (de tests/conftest.py) es un admin GLOBAL, y `user["role"] ==
   "admin"` **bypasea `require_perms`**. Sirve para probar el camino feliz, pero
   NO prueba que los permisos estén bien puestos. Para eso está `coord_headers`,
   que monta un coordinador real con sus filas de rol y permisos.

4. `TestClient` de Starlette **serializa** las requests en su portal: lanzar dos
   `client.post` desde hilos NO produce concurrencia real contra Postgres. Para
   eso hace falta `real_db` y dos conexiones.
"""
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import text

from itcj2.database import get_db

from tests.conftest import make_jwt

# Duraciones y horas usadas por defecto en las factories.
DEFAULT_DAY = date(2026, 9, 1)


@pytest.fixture()
def freeze_app_clock():
    """Congela `now_app` en TODOS los módulos de agendatec que lo tengan.

    `from ...helpers import now_app` COPIA la referencia en el módulo que
    importa, así que parchear solo el origen no congela a nadie más. Cuatro
    fixtures de esta suite hacían eso a mano y cada una listaba un subconjunto
    DISTINTO de módulos; los huecos que dejaban —`api.availability` y
    `api.admin.requests`— son exactamente los que reventaron el CI el
    2026-09-01, en cuanto el reloj real pasó de las horas que fijan los tests.

    Por eso los módulos se DESCUBREN recorriendo `sys.modules` en vez de
    escribirse a mano: el que mañana importe `now_app` queda congelado sin que
    nadie se acuerde de venir a esta lista.

    `request_service` importa `now_app` DENTRO de la función, así que resuelve
    contra `helpers` en cada llamada y queda cubierto por el parche del origen.

    Uso:

        def test_algo(client, freeze_app_clock):
            with freeze_app_clock(time(8, 0)):
                ...

    `at` puede ser un `time` (se combina con `day`, por defecto `DEFAULT_DAY`)
    o un `datetime` aware ya listo.
    """
    import sys
    from contextlib import ExitStack, contextmanager
    from unittest.mock import patch

    @contextmanager
    def _freeze(at, day=DEFAULT_DAY):
        # El orden importa: `itcj2.models` primero, porque importar el router de
        # agendatec en frío entra por `helpers` -> `core.models` a medio
        # inicializar y truena por import circular.
        import itcj2.models  # noqa: F401
        import itcj2.apps.agendatec.router  # noqa: F401
        from itcj2.apps.agendatec.helpers import app_dt

        frozen = app_dt(day, at) if isinstance(at, time) else at
        targets = [
            name for name, mod in list(sys.modules.items())
            if name.startswith("itcj2.apps.agendatec")
            and mod is not None
            and getattr(mod, "now_app", None) is not None
        ]
        with ExitStack() as stack:
            for name in targets:
                stack.enter_context(patch(f"{name}.now_app", return_value=frozen))
            yield frozen

    return _freeze


# ---------------------------------------------------------------------------
# Cliente atado a la sesión de las fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(app_client, db_session):
    """TestClient cuyo `get_db` es la sesión transaccional de las fixtures.

    Sin este override el endpoint abriría su propia sesión contra otro pool y
    no vería nada de lo que crean `make_grid`, `make_booking`, etc.
    """
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """Hace que el código que abre `SessionLocal()` use la sesión del test.

    Varios helpers de agendatec no reciben la sesión por parámetro y abren la
    suya (`require_admission_open`, los ACL de sockets). Sin esto ven la BD de
    dev real en vez de las fixtures — p.ej. `require_admission_open` encuentra
    el periodo real, con la ventana cerrada, y devuelve 503.

    El proxy deja pasar todo menos `close()`: esos helpers cierran la sesión en
    su `finally`, y cerrar la del test rompería cualquier aserción posterior.
    """
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session


# ---------------------------------------------------------------------------
# Semilla de la app agendatec
# ---------------------------------------------------------------------------
# `_seed_minimal_reference_data` (tests/fastapi/conftest.py) siembra itcj,
# helpdesk y maint — no agendatec. Sin la fila en core_apps, `require_app` y
# `require_perms` no resuelven y todo devuelve 404/403.
_AGENDATEC_PERMS = [
    "agendatec.slots.api.read",
    "agendatec.slots.api.create",
    "agendatec.slots.api.delete",
    "agendatec.appointments.api.read.own",
    "agendatec.appointments.api.update.own",
    "agendatec.coord_dashboard.api.read",
    "agendatec.requests.api.create.all",
]


@pytest.fixture()
def agendatec_app(db_session):
    """Fila de `core_apps` para agendatec + sus permisos. Idempotente."""
    from itcj2.core.models.app import App
    from itcj2.core.models.permission import Permission

    app = db_session.query(App).filter_by(key="agendatec").first()
    if app is None:
        app = App(key="agendatec", name="AgendaTec", is_active=True)
        db_session.add(app)
        db_session.flush()

    existing = {
        p.code for p in db_session.query(Permission).filter_by(app_id=app.id).all()
    }
    for code in _AGENDATEC_PERMS:
        if code not in existing:
            db_session.add(Permission(app_id=app.id, code=code, name=code))
    db_session.flush()
    return app


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_user(db_session):
    """Crea un usuario. `role_name` es el rol GLOBAL de core_users."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.user import User

    def _make(first_name="TEST", last_name="USER", control_number=None, role_name="student"):
        role = db_session.query(Role).filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db_session.add(role)
            db_session.flush()
        u = User(
            first_name=first_name,
            last_name=last_name,
            control_number=control_number,
            is_active=True,
            role_id=role.id,
        )
        db_session.add(u)
        db_session.flush()
        return u

    return _make


@pytest.fixture()
def grant_app_role(db_session, agendatec_app):
    """Da a un usuario un rol en agendatec, con los permisos indicados.

    Necesario para probar que los permisos están BIEN PUESTOS: el admin global
    bypasea `require_perms`, así que un test que solo use `auth_headers` pasaría
    aunque faltara la fila de permiso.
    """
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.models.user_app_role import UserAppRole

    def _grant(user, role_name, perm_codes=None):
        role = db_session.query(Role).filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db_session.add(role)
            db_session.flush()

        for code in perm_codes or _AGENDATEC_PERMS:
            perm = (
                db_session.query(Permission)
                .filter_by(app_id=agendatec_app.id, code=code)
                .first()
            )
            if perm is None:
                continue
            exists = (
                db_session.query(RolePermission)
                .filter_by(role_id=role.id, perm_id=perm.id)
                .first()
            )
            if exists is None:
                db_session.add(RolePermission(role_id=role.id, perm_id=perm.id))

        link = (
            db_session.query(UserAppRole)
            .filter_by(user_id=user.id, app_id=agendatec_app.id, role_id=role.id)
            .first()
        )
        if link is None:
            db_session.add(
                UserAppRole(user_id=user.id, app_id=agendatec_app.id, role_id=role.id)
            )
        db_session.flush()
        return role

    return _grant


@pytest.fixture()
def make_student(make_user, grant_app_role):
    """Alumno con el rol `student` EN AGENDATEC.

    `require_roles("agendatec", ["student"])` resuelve contra
    core_user_app_roles, no contra el rol del JWT: un usuario con role=student
    en el token pero sin la fila recibe 403.
    """
    def _make(control_number, first_name="ALUM", last_name="TEST"):
        u = make_user(first_name=first_name, last_name=last_name,
                      control_number=control_number, role_name="student")
        grant_app_role(u, "student", perm_codes=[])
        return u

    return _make


@pytest.fixture()
def make_program(db_session):
    from itcj2.core.models.program import Program

    def _make(name):
        p = db_session.query(Program).filter_by(name=name).first()
        if p is None:
            p = Program(name=name)
            db_session.add(p)
            db_session.flush()
        return p

    return _make


@pytest.fixture()
def make_coordinator(db_session, make_user, grant_app_role):
    """Coordinador con sus carreras asignadas y su rol en agendatec."""
    from itcj2.core.models.coordinator import Coordinator
    from itcj2.core.models.program_coordinator import ProgramCoordinator

    def _make(program_ids, first_name="COORD", last_name="TEST"):
        u = make_user(first_name=first_name, last_name=last_name, role_name="staff")
        grant_app_role(u, "coordinator")
        c = Coordinator(user_id=u.id)
        db_session.add(c)
        db_session.flush()
        for pid in program_ids:
            db_session.add(ProgramCoordinator(program_id=pid, coordinator_id=c.id))
        db_session.flush()
        return c, u

    return _make


@pytest.fixture()
def make_period(db_session):
    """Periodo ACTIVE con su config de agendatec y sus días habilitados."""
    from itcj2.apps.agendatec.models import AgendaTecPeriodConfig, PeriodEnabledDay
    from itcj2.core.models.academic_period import AcademicPeriod

    def _make(days=(DEFAULT_DAY,), code="29991", admission_open=True):
        from itcj2.apps.agendatec.helpers import get_app_tz

        # La BD de dev ya trae un periodo ACTIVE real. `get_active_period()`
        # devolvería ese en vez del nuestro, y los endpoints rechazarían el día
        # con `day_not_enabled`. Se desactivan dentro del savepoint, así que la
        # BD queda intacta al terminar el test.
        db_session.query(AcademicPeriod).filter(
            AcademicPeriod.status == "ACTIVE"
        ).update({"status": "INACTIVE"}, synchronize_session=False)
        db_session.flush()

        p = AcademicPeriod(
            code=code,
            name=f"Periodo test {code}",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 12, 31),
            status="ACTIVE",
        )
        db_session.add(p)
        db_session.flush()

        tz = get_app_tz()
        now = datetime.now(tz)
        if admission_open:
            start, deadline = now - timedelta(days=1), now + timedelta(days=30)
        else:
            start, deadline = now - timedelta(days=30), now - timedelta(days=1)

        db_session.add(AgendaTecPeriodConfig(
            period_id=p.id,
            student_admission_start=start,
            student_admission_deadline=deadline,
            max_cancellations_per_student=2,
            allow_drop_requests=True,
            allow_appointment_requests=True,
        ))
        for d in days:
            db_session.add(PeriodEnabledDay(period_id=p.id, day=d))
        db_session.flush()
        return p

    return _make


@pytest.fixture()
def make_grid(db_session):
    """Ventana + slots + proyección de scope, como los dejaría SlotService.

    Devuelve (window, [slots]). NO hace commit: vive dentro del savepoint.
    """
    def _make(coord_id, start, end, minutes, program_ids, day=DEFAULT_DAY):
        from itcj2.apps.agendatec.models import AvailabilityWindow, TimeSlot

        w = AvailabilityWindow(
            coordinator_id=coord_id, day=day,
            start_time=start, end_time=end, slot_minutes=minutes,
        )
        db_session.add(w)
        db_session.flush()

        slots = []
        cur = datetime.combine(day, start)
        end_dt = datetime.combine(day, end)
        step = timedelta(minutes=minutes)
        while (cur + step) <= end_dt:
            s = TimeSlot(
                coordinator_id=coord_id, day=day,
                start_time=cur.time(), end_time=(cur + step).time(),
                is_booked=False,
            )
            db_session.add(s)
            slots.append(s)
            cur += step
        db_session.flush()

        _link_scope(db_session, w, slots, program_ids)
        return w, slots

    return _make


def _link_scope(db, window, slots, program_ids):
    """Materializa el scope por carrera, si las tablas puente ya existen.

    Tolerante a que aún no exista la migración: el harness debe poder correr
    antes y después de que se añadan `agendatec_*_programs`.
    """
    try:
        from itcj2.apps.agendatec.models import (  # noqa: F401
            AvailabilityWindowProgram, TimeSlotProgram,
        )
    except ImportError:
        return

    for pid in program_ids:
        db.add(AvailabilityWindowProgram(window_id=window.id, program_id=pid))
    for s in slots:
        for pid in program_ids:
            db.add(TimeSlotProgram(slot_id=s.id, program_id=pid))
    db.flush()


@pytest.fixture()
def make_booking(db_session):
    """Reserva un slot: `is_booked=True` + Request + Appointment.

    `ap_status` permite montar los casos que dejan `is_booked=True` sin cita
    viva (DONE, NO_SHOW), que el split debe acortar pero NO notificar.
    """
    def _make(slot, student, program_id, period_id,
              ap_status="SCHEDULED", req_status="PENDING"):
        from itcj2.apps.agendatec.models import Appointment, Request

        slot.is_booked = True
        r = Request(
            student_id=student.id, program_id=program_id, period_id=period_id,
            type="APPOINTMENT", status=req_status,
        )
        db_session.add(r)
        db_session.flush()
        ap = Appointment(
            request_id=r.id, student_id=student.id,
            coordinator_id=slot.coordinator_id, program_id=program_id,
            slot_id=slot.id, status=ap_status,
        )
        db_session.add(ap)
        db_session.flush()
        return r, ap

    return _make


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
@pytest.fixture()
def headers_for():
    """Cookie JWT para un usuario concreto. `role` es el rol del token."""
    def _make(user, role="staff"):
        token = make_jwt(user_id=user.id, role=role, name=user.full_name)
        return {"Cookie": f"itcj_token={token}"}

    return _make


@pytest.fixture()
def coord_setup(make_program, make_coordinator, make_period, headers_for):
    """Escenario base: coordinador con 3 carreras + periodo activo.

    Devuelve un dict para que los tests tomen solo lo que necesitan.
    """
    def _make(n_programs=3):
        names = ["Industrial", "Mecatronica", "Sistemas", "Quimica"][:n_programs]
        programs = [make_program(n) for n in names]
        coord, user = make_coordinator([p.id for p in programs])
        period = make_period()
        return {
            "coord": coord,
            "user": user,
            "headers": headers_for(user, role="staff"),
            "programs": programs,
            "program_ids": [p.id for p in programs],
            "period": period,
        }

    return _make


# ---------------------------------------------------------------------------
# Transacción real, para locking y concurrencia
# ---------------------------------------------------------------------------
_AGENDATEC_TABLES = (
    "agendatec_appointments",
    "agendatec_requests",
    "agendatec_time_slots",
    "agendatec_availability_windows",
    "agendatec_period_enabled_days",
    "agendatec_period_config",
)


@pytest.fixture()
def real_db(_pg_engine):
    """Sesión que COMMITEA de verdad, con limpieza acotada al final.

    Necesaria para `pg_advisory_xact_lock` y `FOR UPDATE`: bajo el savepoint de
    `db_session` el commit del endpoint no libera el lock, así que un test de
    concurrencia pasaría en falso.

    Limpieza: se anota `max(id)` de cada tabla ANTES del test y se borran solo
    las filas con id mayor. Es acotado y determinista — no hace TRUNCATE, que
    se llevaría los datos reales de la BD de dev. El orden de borrado respeta
    las FK (hijos primero).

    CONTRAPARTIDA: si el test falla a la mitad, las filas creadas se borran
    igual, así que no queda rastro para depurar. Para depurar, comenta el
    bloque de limpieza puntualmente.
    """
    from sqlalchemy.orm import sessionmaker

    with _pg_engine.begin() as conn:
        marks = {
            tbl: (conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {tbl}")).scalar() or 0)
            for tbl in _AGENDATEC_TABLES
        }

    Maker = sessionmaker(bind=_pg_engine, expire_on_commit=False, future=True)
    session = Maker()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with _pg_engine.begin() as conn:
            for tbl in _AGENDATEC_TABLES:   # ya está en orden hijos -> padres
                conn.execute(text(f"DELETE FROM {tbl} WHERE id > :m"), {"m": marks[tbl]})

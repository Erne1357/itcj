"""Harness de tests de TitulaTec: Postgres real, transaccion + rollback por test.

Hasta 2026-09 esta suite eran 32 tests unitarios con `MagicMock` y cero
`TestClient`: ni una sola ruta de `pages/` estaba cubierta. Este conftest es la
base para probar rutas de verdad, con datos SINTETICOS creados por el propio
test (nada de depender de filas reales de la BD de dev, nada de PII en el repo).

LA TRAMPA DE ESTA APP (leer antes de escribir el primer test de ruta)
---------------------------------------------------------------------
TitulaTec es pages-only y **cada handler abre su propia sesion**::

    from itcj2.database import SessionLocal   # import LOCAL, dentro de la funcion
    db = SessionLocal()

Hay 52 llamadas asi en `pages/{admin,appointments,documents,officers,roles,
student}.py`, mas `nav.py:79` (`get_titulatec_roles`) y `nav.py:108-111`
(`admin_nav_items`, que ademas usa `with SessionLocal() as db:`). El UNICO
`Depends(get_db)` de la cadena es el gate de autorizacion, dentro de
`require_page_app` (`itcj2/dependencies.py:118`).

Consecuencia: `dependency_overrides[get_db]` cubre **solo la autorizacion**. Si
te quedas ahi, el cuerpo de la ruta abre una sesion contra el pool REAL, no ve
nada de lo que creo el test y consulta la BD de dev — el test pasa o falla por
razones que no tienen que ver con lo que crees estar probando.

Por eso `client` hace las DOS cosas a la vez y no se puede aplicar a medias:

  1. `dependency_overrides[get_db]` -> la sesion del test (gate).
  2. `monkeypatch` de `itcj2.database.SessionLocal` -> proxy sobre la MISMA
     sesion (cuerpo). Funciona precisamente porque el import es local: el
     nombre se resuelve en cada llamada, no al importar el modulo.

El proxy (`_TestSession`) neutraliza `close()` **y** el protocolo de context
manager: `Session.__exit__` llama a `close()`, y cerrar la sesion del test
dejaria invalidas todas las aserciones posteriores. Ojo: los metodos especiales
se buscan en el TIPO, no via `__getattr__`, asi que `__enter__`/`__exit__` estan
declarados explicitamente. Un proxy que solo tape `close()` revienta con
`TypeError: object does not support the context manager protocol` en cuanto la
ruta pasa por `admin_nav_items`.

`rollback()` SI pasa al inner a proposito (hoy titulatec no lo llama en ningun
lado; `grep -rn "rollback" itcj2/apps/titulatec/` no devuelve nada). Si algun
dia lo hace, ojo: bajo `join_transaction_mode="create_savepoint"` un rollback
del handler descarta tambien las filas que sembraron las factories.

AUTORIZACION: no hay atajos
---------------------------
El 100% de las rutas usa `require_page_app("titulatec", perms=[...])`, que **NO
bypasea al admin global** (`dependencies.py:104-139`): resuelve todo contra BD
via `cached_has_assignment` + `cached_perms`. Un JWT con `role="admin"` no abre
nada por si solo, asi que los clientes de este harness emiten el token con
`role=""`: si un test pasa, es porque las filas de permisos estan bien puestas.
`perms=[...]` es OR — basta UNA coincidencia.

Los helpers de concesion invalidan el cache de authz en Redis del usuario
tocado. El autouse `_clear_authz_cache` global (tests/fastapi/conftest.py:65)
limpia entre tests, pero no dentro de uno: si un test pega a la ruta ANTES de
conceder el permiso, el "no" queda cacheado 300s y la concesion posterior no se
ve. Por eso los helpers llaman a `invalidate_user_app` despues de cada flush.

DATOS
-----
Todo es inventado: nombres ficticios, numeros de control `99xxxxxx`, correos
`@example.invalid`, roles `tt_test_*` (NO los roles reales `titulatec_*`, que en
la BD de dev ya traen sus 20-27 permisos y falsearian cualquier negativo).
Ninguna fixture depende de gbarron/fleon/ahernandez ni del alumno 23110952.
"""
from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta

import pytest

# Eager import: resuelve los mappers antes de instanciar cualquier modelo.
import itcj2.models  # noqa: F401
import itcj2.apps.titulatec.models  # noqa: F401

from itcj2.database import get_db
from tests.conftest import make_jwt

APP_KEY = "titulatec"

# Roles FICTICIOS. Nunca uses aqui los reales (`titulatec_school_services_head`,
# etc.): en la BD de dev ya existen con sus permisos, el helper los reutilizaria
# por nombre y el actor "sin permisos" heredaria 27 permisos de verdad.
ROLE_HEAD = "tt_test_head"
ROLE_OFFICER = "tt_test_officer"
ROLE_STUDENT = "tt_test_student"
ROLE_NOPERMS = "tt_test_noperms"

# Sets por defecto de cada actor. Son subconjuntos de los 66 codigos reales
# (`database/DML/titulatec/02_insert_permissions.sql`); que esos codigos existan
# de verdad lo verifica test_permissions_contract.py.
HEAD_PERMS = (
    "titulatec.dashboard.school_services",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.process.api.read.all",      # -> officer_programs() == "ALL"
    "titulatec.document.page.list",
    "titulatec.document.api.read.all",
    "titulatec.cohort.page.list",
    "titulatec.cohort.api.import_csv",
    "titulatec.cohort.api.review_days",
    "titulatec.appointment.page.list",
    "titulatec.officers.page.list",
    "titulatec.officers.api.manage",
)

# Encargado: MISMOS permisos de bandeja pero SIN `process.api.read.all`, que es
# justo lo que lo deja acotado a sus carreras (`scope_service.py:32`).
OFFICER_PERMS = (
    "titulatec.dashboard.school_services",
    "titulatec.process.page.list",
    "titulatec.process.page.detail",
    "titulatec.document.page.list",
    "titulatec.document.api.read.all",
    "titulatec.appointment.page.list",
)

STUDENT_PERMS = (
    "titulatec.dashboard.student",
    "titulatec.process.page.my",
    "titulatec.process.api.read.own",
    "titulatec.document.api.read.own",
    "titulatec.document.api.upload.own",
    "titulatec.appointment.page.my",
)

# Permiso que NO abre ninguna pagina admin: sirve para el actor que tiene acceso
# a la app (pasa `cached_has_assignment`) pero le falta el permiso de la pagina.
INERT_PERM = "titulatec.notifications.api.read.own"

_seq = itertools.count(1)


def _n() -> int:
    """Contador para valores unicos (usuarios, folios, codigos de puesto)."""
    return next(_seq)


# ---------------------------------------------------------------------------
# Sesion compartida: proxy + overrides
# ---------------------------------------------------------------------------
class _TestSession:
    """Proxy sobre la sesion del test que ignora `close()` y el `with`.

    Ver el docstring del modulo: `__enter__`/`__exit__` van declarados porque
    Python busca los metodos especiales en el TIPO, no via `__getattr__`.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):  # el handler cierra en su `finally`; el test sigue vivo
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """`SessionLocal()` -> la sesion del test. Cubre el CUERPO de las rutas.

    Uselo suelto solo para services/helpers que abren su propia sesion sin pasar
    por HTTP (p. ej. `nav.get_titulatec_roles`). Para rutas use `client`, que ya
    lo incluye.
    """
    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _TestSession(db_session))
    return db_session


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    """TestClient con la sesion del test atada por AMBOS caminos (gate + cuerpo).

    No existe una version "solo gate" a proposito: es el error que este harness
    esta hecho para hacer imposible.
    """
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


def _invalidate(user_id: int) -> None:
    """Tira el cache de authz del usuario en titulatec. Best-effort."""
    try:
        from itcj2.core.services.authz_cache import invalidate_user_app
        invalidate_user_app(user_id, APP_KEY)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App + permisos, DENTRO de la transaccion del test
# ---------------------------------------------------------------------------
@pytest.fixture()
def titulatec_app(db_session):
    """Fila de `core_apps` para titulatec. Idempotente.

    Va aqui y no en `_seed_minimal_reference_data` (tests/fastapi/conftest.py:95)
    a proposito: aquel fixture COMMITEA fuera de la transaccion del test, contra
    la BD de dev. Este vive y muere dentro del savepoint.
    """
    from itcj2.core.models.app import App

    app = db_session.query(App).filter_by(key=APP_KEY).first()
    if app is None:
        app = App(
            key=APP_KEY, name="TitulaTec", is_active=True,
            visible_to_students=True, mobile_enabled=True,
        )
        db_session.add(app)
        db_session.flush()
    return app


@pytest.fixture()
def make_perms(db_session, titulatec_app):
    """Asegura filas de `core_permissions` para los codigos dados -> {code: Permission}."""
    from itcj2.core.models.permission import Permission

    def _make(codes):
        out = {}
        for code in codes:
            perm = (
                db_session.query(Permission)
                .filter_by(app_id=titulatec_app.id, code=code)
                .first()
            )
            if perm is None:
                perm = Permission(app_id=titulatec_app.id, code=code, name=code[:120])
                db_session.add(perm)
                db_session.flush()
            out[code] = perm
        return out

    return _make


@pytest.fixture()
def make_role(db_session, make_perms):
    """Rol (por nombre) con los permisos indicados en titulatec. Idempotente."""
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    def _make(name, perm_codes=()):
        role = db_session.query(Role).filter_by(name=name).first()
        if role is None:
            role = Role(name=name)
            db_session.add(role)
            db_session.flush()
        for perm in make_perms(perm_codes).values():
            exists = (
                db_session.query(RolePermission)
                .filter_by(role_id=role.id, perm_id=perm.id)
                .first()
            )
            if exists is None:
                db_session.add(RolePermission(role_id=role.id, perm_id=perm.id))
        db_session.flush()
        return role

    return _make


# ---------------------------------------------------------------------------
# Piezas del organigrama
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_user(db_session):
    """Usuario sintetico. Nombres ficticios, control `99xxxxxx`, correo .invalid."""
    from itcj2.core.models.user import User

    def _make(first_name="ACTOR", last_name="PRUEBA", control_number=None,
              username=None, email=None, global_role=None, is_active=True):
        n = _n()
        role_id = None
        if global_role:
            from itcj2.core.models.role import Role
            role = db_session.query(Role).filter_by(name=global_role).first()
            if role is None:
                role = Role(name=global_role)
                db_session.add(role)
                db_session.flush()
            role_id = role.id
        user = User(
            first_name=first_name,
            last_name=last_name,
            username=username or f"tt_test_{n}",
            control_number=control_number,
            email=email or f"tt.test.{n}@example.invalid",
            is_active=is_active,
            role_id=role_id,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture()
def make_program(db_session):
    """Carrera (`core_programs`). Idempotente por nombre."""
    from itcj2.core.models.program import Program

    def _make(name):
        prog = db_session.query(Program).filter_by(name=name).first()
        if prog is None:
            prog = Program(name=name)
            db_session.add(prog)
            db_session.flush()
        return prog

    return _make


@pytest.fixture()
def make_department(db_session):
    """Departamento del organigrama (opcional: `Position.department_id` es nullable)."""
    from itcj2.core.models.department import Department

    def _make(code=None, name="Depto de prueba", parent_id=None):
        code = code or f"tt_test_dept_{_n()}"
        dept = db_session.query(Department).filter_by(code=code).first()
        if dept is None:
            dept = Department(code=code, name=name, parent_id=parent_id,
                              is_active=True, is_official=False)
            db_session.add(dept)
            db_session.flush()
        return dept

    return _make


@pytest.fixture()
def make_position(db_session):
    """Puesto (`core_positions`)."""
    from itcj2.core.models.position import Position

    def _make(code=None, title="Puesto de prueba", department=None):
        code = code or f"tt_test_pos_{_n()}"
        pos = db_session.query(Position).filter_by(code=code).first()
        if pos is None:
            pos = Position(
                code=code, title=title, is_active=True,
                department_id=department.id if department is not None else None,
            )
            db_session.add(pos)
            db_session.flush()
        return pos

    return _make


@pytest.fixture()
def assign_position(db_session):
    """`UserPosition` VIGENTE.

    `_active_position_filter()` (`authz_service.py:21-31`) exige `is_active` **y**
    `start_date <= hoy` **y** (`end_date` NULL o >= hoy). Con `start_date` en el
    futuro el usuario no hereda nada y el 403 resultante desconcierta.
    """
    from itcj2.core.models.position import UserPosition

    def _make(user, position, start_date=None, end_date=None, is_active=True):
        link = UserPosition(
            user_id=user.id, position_id=position.id,
            start_date=start_date or (date.today() - timedelta(days=1)),
            end_date=end_date, is_active=is_active,
        )
        db_session.add(link)
        db_session.flush()
        _invalidate(user.id)
        return link

    return _make


@pytest.fixture()
def link_programs(db_session):
    """`ProgramPosition`: las carreras que el puesto atiende (eje del scope)."""
    from itcj2.core.models.position import ProgramPosition

    def _make(position, programs):
        out = []
        for prog in programs:
            pid = getattr(prog, "id", prog)
            exists = (
                db_session.query(ProgramPosition)
                .filter_by(position_id=position.id, program_id=pid)
                .first()
            )
            if exists is None:
                exists = ProgramPosition(position_id=position.id, program_id=pid)
                db_session.add(exists)
            out.append(exists)
        db_session.flush()
        return out

    return _make


@pytest.fixture()
def bind_position_role(db_session, titulatec_app):
    """`PositionAppRole`: el rol que el puesto otorga en titulatec.

    Es la via real de la app: 11 filas en `core_position_app_roles`
    (`05_insert_position_app_roles.sql`), casi nada por `core_user_app_roles`.
    """
    from itcj2.core.models.position import PositionAppRole

    def _make(position, role):
        exists = (
            db_session.query(PositionAppRole)
            .filter_by(position_id=position.id, app_id=titulatec_app.id, role_id=role.id)
            .first()
        )
        if exists is None:
            exists = PositionAppRole(
                position_id=position.id, app_id=titulatec_app.id, role_id=role.id,
            )
            db_session.add(exists)
            db_session.flush()
        return exists

    return _make


@pytest.fixture()
def grant_user_role(db_session, titulatec_app):
    """`UserAppRole`: rol DIRECTO en la app.

    Es la via que usa el importador de CSV para los alumnos
    (`import_service.py:298` -> `authz_service.grant_role`).
    """
    from itcj2.core.models.user_app_role import UserAppRole

    def _make(user, role):
        exists = (
            db_session.query(UserAppRole)
            .filter_by(user_id=user.id, app_id=titulatec_app.id, role_id=role.id)
            .first()
        )
        if exists is None:
            exists = UserAppRole(
                user_id=user.id, app_id=titulatec_app.id, role_id=role.id,
            )
            db_session.add(exists)
            db_session.flush()
        _invalidate(user.id)
        return exists

    return _make


# ---------------------------------------------------------------------------
# Actores compuestos
# ---------------------------------------------------------------------------
@pytest.fixture()
def make_head(make_user, make_role, make_position, assign_position, bind_position_role):
    """Jefa de Servicios Escolares sintetica: ve TODO (`process.api.read.all`).

    Rol por PUESTO, como en produccion. Devuelve el `User`.
    """
    def _make(perm_codes=HEAD_PERMS, first_name="JEFA", last_name="FICTICIA"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role(ROLE_HEAD, perm_codes)
        pos = make_position(title="Jefatura de prueba")
        bind_position_role(pos, role)
        assign_position(user, pos)
        return user

    return _make


@pytest.fixture()
def make_officer(make_user, make_role, make_position, assign_position,
                 bind_position_role, link_programs):
    """Encargado acotado a N carreras: puesto + `ProgramPosition` + rol SIN read.all.

    Devuelve `(user, position)` — el puesto hace falta para reasignar carreras a
    media prueba (`officer_service.set_programs`).
    """
    def _make(programs, perm_codes=OFFICER_PERMS, first_name="ENCARGADO",
              last_name="FICTICIO"):
        user = make_user(first_name=first_name, last_name=last_name)
        role = make_role(ROLE_OFFICER, perm_codes)
        pos = make_position(title="Encargado de prueba")
        bind_position_role(pos, role)
        link_programs(pos, programs)
        assign_position(user, pos)
        return user, pos

    return _make


@pytest.fixture()
def make_student(make_user, make_role, grant_user_role):
    """Alumno sintetico con rol DIRECTO en la app (como lo deja el importador)."""
    def _make(control_number=None, perm_codes=STUDENT_PERMS,
              first_name="ALUMNO", last_name="FICTICIO"):
        control_number = control_number or f"99{_n():06d}"
        user = make_user(first_name=first_name, last_name=last_name,
                         control_number=control_number, username=control_number,
                         global_role="student")
        role = make_role(ROLE_STUDENT, perm_codes)
        grant_user_role(user, role)
        return user

    return _make


@pytest.fixture()
def make_app_user_without_perms(make_user, make_role, grant_user_role):
    """Actor CON acceso a la app pero SIN el permiso de ninguna pagina admin.

    Ejerce la rama `PageForbidden(has_app_access=True)` de `require_page_app`
    (`dependencies.py:133-137`), distinta del outsider sin asignacion alguna.
    """
    def _make(perm_codes=(INERT_PERM,)):
        user = make_user(first_name="SIN", last_name="PERMISOS")
        role = make_role(ROLE_NOPERMS, perm_codes)
        grant_user_role(user, role)
        return user

    return _make


@pytest.fixture()
def make_outsider(make_user):
    """Usuario SIN ninguna asignacion en titulatec.

    Dispara `PageForbidden(has_app_access=False)` (`dependencies.py:126-128`).
    """
    def _make():
        return make_user(first_name="AJENO", last_name="FICTICIO")

    return _make


# ---------------------------------------------------------------------------
# Clientes autenticados por actor
# ---------------------------------------------------------------------------
@pytest.fixture()
def cookies_for():
    """Header Cookie con el JWT del actor.

    `role=""` a proposito: `require_page_app` no bypasea al admin global, pero
    `resolve_dashboard_url` (`nav.py:66-74`) SI cortocircuita con
    `jwt_role == "admin"`. Con el rol vacio ningun test pasa por un atajo.
    """
    def _make(user, role=""):
        token = make_jwt(user_id=user.id, role=role, name=user.full_name,
                         cn=user.control_number)
        return {"Cookie": f"itcj_token={token}"}

    return _make


@pytest.fixture()
def client_as(client):
    """Cliente ya autenticado como `user`. Llamarlo de nuevo cambia de actor.

    Uso::

        resp = client_as(head).get("/titulatec/admin/documents")
    """
    def _as(user, role=""):
        token = make_jwt(user_id=user.id, role=role, name=user.full_name,
                         cn=user.control_number)
        client.cookies.set("itcj_token", token)
        return client

    return _as


# ---------------------------------------------------------------------------
# Catalogos y arbol de datos del proceso
# ---------------------------------------------------------------------------
# Copia de `06_seed_catalogs.sql` (catalogo, sin datos personales).
PHASE_DEFS = (
    (0, "cohort_intake", "Convocatoria", "school_services"),
    (1, "initial_docs", "Documentos iniciales", "student"),
    (2, "review_appointment", "Cita de cotejo", "school_services"),
    (3, "format_b", "Formato B", "titulaciones"),
    (4, "synodal_assignment", "Asignacion de sinodales", "vinculacion"),
    (5, "synodal_review", "Revision de sinodales", "synodals"),
    (6, "anexo_iii", "Anexo III", "titulaciones"),
    (7, "final_docs", "Entrega final", "student"),
    (8, "ceremony", "Acto protocolario", "titulaciones"),
)

INITIAL_DOC_TYPES = (
    ("birth_certificate", "Acta de nacimiento", 1),
    ("high_school_cert", "Certificado de bachillerato", 1),
    ("curp", "CURP certificada", 1),
)


@pytest.fixture()
def seed_phase_defs(db_session):
    """Las 9 filas de `titulatec_phase_definitions` (0-8). Idempotente."""
    from itcj2.apps.titulatec.models import PhaseDefinition

    def _seed():
        out = []
        for number, code, name, responsible in PHASE_DEFS:
            row = db_session.query(PhaseDefinition).filter_by(number=number).first()
            if row is None:
                row = PhaseDefinition(number=number, code=code, name=name,
                                      responsible=responsible, order_index=number,
                                      is_active=True)
                db_session.add(row)
            out.append(row)
        db_session.flush()
        return out

    return _seed


@pytest.fixture()
def seed_document_types(db_session):
    """Tipos de documento. Por defecto los 3 iniciales de la fase 1."""
    from itcj2.apps.titulatec.models import DocumentType

    def _seed(types=INITIAL_DOC_TYPES):
        out = []
        for code, name, phase in types:
            row = db_session.query(DocumentType).filter_by(code=code).first()
            if row is None:
                row = DocumentType(code=code, name=name, phase_number=phase,
                                   file_kind="pdf", is_versionable=True, is_active=True)
                db_session.add(row)
            out.append(row)
        db_session.flush()
        return out

    return _seed


@pytest.fixture()
def make_modality(db_session):
    """Modalidad. `skips_phases` es lo que hace saltar fases (p. ej. EGEL)."""
    from itcj2.apps.titulatec.models import Modality

    def _make(code=None, name="Modalidad de prueba", requires_synodals=True,
              signature_rule="president_only", skips_phases=None):
        code = code or f"tt_test_mod_{_n()}"
        row = db_session.query(Modality).filter_by(code=code).first()
        if row is None:
            row = Modality(code=code, name=name, requires_synodals=requires_synodals,
                           signature_rule=signature_rule, skips_phases=skips_phases,
                           is_active=True)
            db_session.add(row)
            db_session.flush()
        return row

    return _make


@pytest.fixture()
def make_period(db_session):
    """`core_academic_periods`. `code` es String(6) y `name` es UNIQUE.

    NO se toca el periodo ACTIVE real: titulatec no resuelve por periodo activo
    (a diferencia de agendatec), la convocatoria apunta al periodo por FK.
    """
    from itcj2.core.models.academic_period import AcademicPeriod

    def _make(code=None, status="INACTIVE"):
        code = code or f"29{_n():03d}A"[:6]
        row = db_session.query(AcademicPeriod).filter_by(code=code).first()
        if row is None:
            row = AcademicPeriod(
                code=code, name=f"Periodo de prueba {code}",
                start_date=date(2029, 1, 1), end_date=date(2029, 6, 30),
                status=status,
            )
            db_session.add(row)
            db_session.flush()
        return row

    return _make


@pytest.fixture()
def make_cohort(db_session, make_period):
    """Convocatoria. `period_id` es UNIQUE: una convocatoria por periodo."""
    from itcj2.apps.titulatec.models import Cohort

    def _make(period=None, name=None, status="open", opens_at=None, closes_at=None,
              created_by=None):
        period = period if period is not None else make_period()
        row = Cohort(
            period_id=period.id,
            name=name or f"Convocatoria {period.code}",
            status=status,
            opens_at=opens_at or date.today(),
            closes_at=closes_at or (date.today() + timedelta(days=30)),
            created_by_id=getattr(created_by, "id", created_by),
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture()
def make_review_day(db_session):
    """Dia habilitado para cotejo en una convocatoria (UNIQUE cohort+date)."""
    from itcj2.apps.titulatec.models import CohortReviewDay

    def _make(cohort, day=None, created_by=None):
        row = CohortReviewDay(
            cohort_id=cohort.id,
            date=day or (date.today() + timedelta(days=7)),
            created_by_id=getattr(created_by, "id", created_by),
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture()
def make_process(db_session, make_cohort):
    """Proceso + sus 9 `ProcessPhase`, con la misma forma que deja el importador.

    Reparto de estados (espejo de `import_service.py:309-311`):
    fase < current_phase -> approved | == -> in_progress | > -> pending.
    `phases=False` crea el proceso pelado (para probar el camino sin fases).
    """
    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess

    def _make(student, cohort=None, program=None, modality=None, current_phase=1,
              status="active", phases=True, folio=None, is_app_active=True):
        cohort = cohort if cohort is not None else make_cohort()
        period_code = cohort.period_code or str(cohort.period_id)
        proc = TitulationProcess(
            folio=folio or f"TT-{period_code}-{_n():04d}",
            student_id=student.id,
            cohort_id=cohort.id,
            program_id=getattr(program, "id", program),
            modality_id=getattr(modality, "id", modality),
            current_phase=current_phase,
            status=status,
            is_app_active=is_app_active,
        )
        db_session.add(proc)
        db_session.flush()
        if phases:
            for n in range(9):
                st = ("approved" if n < current_phase
                      else "in_progress" if n == current_phase else "pending")
                db_session.add(ProcessPhase(process_id=proc.id, phase_number=n, status=st))
            db_session.flush()
        return proc

    return _make


@pytest.fixture()
def make_document(db_session):
    """Fila de `titulatec_documents` (UNIQUE process+type_code).

    NO escribe en disco: `file_path` es relativa a `TITULATEC_UPLOAD_PATH` y solo
    la ruta de servir archivo (`documents.py:142`) la resuelve. Si el test la
    necesita en disco, creala el mismo con `tmp_path`.
    """
    from itcj2.apps.titulatec.models import Document

    def _make(process, type_code="birth_certificate", phase_number=1,
              review_status="pending", uploaded_by=None, note=None,
              file_path=None, original_name="documento.pdf"):
        row = Document(
            process_id=process.id,
            phase_number=phase_number,
            type_code=type_code,
            file_path=file_path or f"tt-test/{process.id}/{type_code}.pdf",
            original_name=original_name,
            mime_type="application/pdf",
            size_bytes=1024,
            review_status=review_status,
            review_note=note,
            uploaded_by_id=getattr(uploaded_by, "id", uploaded_by) or process.student_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture()
def make_appointment(db_session):
    """Cita de cotejo.

    Dominio real de `status` (`appointment_service.py:172-235`):
    scheduled|confirmed|in_progress|attended|no_show. NO existe `rescheduled`.
    """
    from itcj2.apps.titulatec.models import ReviewAppointment

    def _make(process, when=None, status="scheduled", created_by=None,
              location="Edificio de prueba", note=None):
        default_when = datetime.combine(
            date.today() + timedelta(days=7), datetime.min.time()
        ).replace(hour=10)
        row = ReviewAppointment(
            process_id=process.id,
            scheduled_at=when or default_when,
            location=location,
            status=status,
            note=note,
            created_by_id=getattr(created_by, "id", created_by) or process.student_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


# ---------------------------------------------------------------------------
# Escenario listo para usar
# ---------------------------------------------------------------------------
@pytest.fixture()
def titulatec_scenario(seed_phase_defs, seed_document_types, make_program,
                       make_cohort, make_head, make_officer, make_student,
                       make_process):
    """Arbol minimo completo y componible.

    Catalogos + 2 carreras + jefa + encargado (solo carrera A) + 2 alumnos con
    proceso, uno por carrera. Sirve para probar el eje de scope sin re-escribir
    el andamiaje en cada test.
    """
    def _build():
        seed_phase_defs()
        seed_document_types()
        prog_a = make_program("Ingenieria Ficticia A")
        prog_b = make_program("Ingenieria Ficticia B")
        cohort = make_cohort()
        head = make_head()
        officer, officer_pos = make_officer([prog_a])
        student_a = make_student()
        student_b = make_student()
        proc_a = make_process(student_a, cohort=cohort, program=prog_a)
        proc_b = make_process(student_b, cohort=cohort, program=prog_b)
        return {
            "cohort": cohort,
            "programs": {"a": prog_a, "b": prog_b},
            "head": head,
            "officer": officer,
            "officer_position": officer_pos,
            "students": {"a": student_a, "b": student_b},
            "processes": {"a": proc_a, "b": proc_b},
        }

    return _build

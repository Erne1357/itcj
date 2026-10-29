"""Fixtures de Prórrogas.

Las pruebas corren contra el Postgres de dev dentro de un savepoint
(`tests/fastapi/conftest.py::db_session`): lo que crean se descarta al final,
pero SÍ ven lo que ya esté commiteado en dev. Por eso las pruebas de plantillas
usan años lejanos (2089–2095), donde no hay plantillas reales.
"""
from io import BytesIO
from itertools import count

import pytest

import itcj2.models  # noqa: F401  (resuelve mappers antes de tocar servicios)
from itcj2.database import get_db
from tests.conftest import make_jwt

APP_KEY = "prorrogas_tec"

SECRETARIA_PERMS = [
    "prorrogas_tec.secretaria.page.view",
    "prorrogas_tec.templates.api.read",
    "prorrogas_tec.templates.api.upload",
    "prorrogas_tec.invitations.api.create",
    "prorrogas_tec.requests.api.read.all",
    "prorrogas_tec.requests.api.decide",
    "prorrogas_tec.plans.api.manage",
    "prorrogas_tec.payments.api.record",
    "prorrogas_tec.payments.api.void",
    "prorrogas_tec.students.api.remind",
    "prorrogas_tec.students.api.export",
]

STUDENT_PERMS = [
    "prorrogas_tec.student.page.view",
    "prorrogas_tec.requests.api.create.own",
    "prorrogas_tec.requests.api.read.own",
    "prorrogas_tec.requests.api.cancel.own",
    "prorrogas_tec.documents.api.sign.own",
]

_seq = count(1)


# ---------------------------------------------------------------------------
# Sesión y cliente (mismo arnés que tests/fastapi/titulatec/conftest.py)
# ---------------------------------------------------------------------------

class _TestSession:
    """Proxy sobre la sesión del test que ignora `close()` y el `with`."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """`SessionLocal()` -> la sesión del test (rutas que abren su propia sesión)."""
    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _TestSession(db_session))
    return db_session


@pytest.fixture()
def client(app_client, db_session, patched_session_local):
    def _override():
        yield db_session

    app_client.app.dependency_overrides[get_db] = _override
    yield app_client
    app_client.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client_as(client):
    """Cliente autenticado como `user`; `role=""` para que no haya atajo de admin."""
    def _as(user, role=""):
        token = make_jwt(user_id=user.id, role=role, name=user.full_name, cn=user.control_number)
        client.cookies.set("itcj_token", token)
        return client

    return _as


# ---------------------------------------------------------------------------
# App, permisos y roles de Prórrogas
# ---------------------------------------------------------------------------

def _invalidate(user_id: int) -> None:
    try:
        from itcj2.core.services.authz_cache import invalidate_user_app
        invalidate_user_app(user_id, APP_KEY)
    except Exception:
        pass


@pytest.fixture()
def prorrogas_app(db_session):
    from itcj2.core.models.app import App

    app = db_session.query(App).filter_by(key=APP_KEY).first()
    if app is None:
        app = App(key=APP_KEY, name="Prórrogas", is_active=True)
        db_session.add(app)
        db_session.flush()
    return app


@pytest.fixture()
def make_role(db_session, prorrogas_app):
    """Rol (por nombre) con los permisos indicados en prorrogas_tec. Idempotente."""
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission

    def _make(name, perm_codes=()):
        role = db_session.query(Role).filter_by(name=name).first()
        if role is None:
            role = Role(name=name)
            db_session.add(role)
            db_session.flush()
        for code in perm_codes:
            perm = db_session.query(Permission).filter_by(app_id=prorrogas_app.id, code=code).first()
            if perm is None:
                perm = Permission(app_id=prorrogas_app.id, code=code, name=code[:120])
                db_session.add(perm)
                db_session.flush()
            if db_session.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first() is None:
                db_session.add(RolePermission(role_id=role.id, perm_id=perm.id))
        db_session.flush()
        return role

    return _make


@pytest.fixture()
def grant(db_session, prorrogas_app):
    """`UserAppRole`: rol directo del usuario en prorrogas_tec."""
    from itcj2.core.models.user_app_role import UserAppRole

    def _grant(user, role):
        if db_session.query(UserAppRole).filter_by(
                user_id=user.id, app_id=prorrogas_app.id, role_id=role.id).first() is None:
            db_session.add(UserAppRole(user_id=user.id, app_id=prorrogas_app.id, role_id=role.id))
            db_session.flush()
        _invalidate(user.id)

    return _grant


@pytest.fixture()
def secretaria(make_user, make_role, grant):
    user = make_user(first_name="SECRETARIA", last_name="PRUEBA")
    grant(user, make_role("secretaria", SECRETARIA_PERMS))
    return user


@pytest.fixture()
def estudiante(make_user, make_role, grant):
    user = make_user(first_name="ESTUDIANTE", last_name="PRUEBA", control_number=f"99{next(_seq):06d}")
    grant(user, make_role("student", STUDENT_PERMS))
    return user


@pytest.fixture(autouse=True)
def almacen(tmp_path, monkeypatch):
    """Los archivos de plantillas van a `tmp_path`, nunca a `instance/` real."""
    from itcj2.apps.prorrogas_tec.services import storage

    base = tmp_path / "prorrogas_tec"
    monkeypatch.setattr(storage, "_base", lambda: base)
    return base


@pytest.fixture()
def make_user(db_session):
    """Usuario sintético. Nombres ficticios, correo .invalid."""
    from itcj2.core.models.user import User

    def _make(first_name="ACTOR", last_name="PRUEBA", middle_name=None, control_number=None,
              username=None, email=None):
        n = next(_seq)
        user = User(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            username=username or f"pr_test_{n}_{id(db_session)}",
            control_number=control_number,
            email=email or f"pr.test.{n}@example.invalid",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make


@pytest.fixture()
def docx_con():
    """`.docx` con un párrafo por línea."""
    from docx import Document

    def _make(*lines: str) -> bytes:
        d = Document()
        for line in lines:
            d.add_paragraph(line)
        buf = BytesIO()
        d.save(buf)
        return buf.getvalue()

    return _make


@pytest.fixture()
def periodo(db_session):
    """Semestre sintetico en 2091 (sin choque con semestres reales)."""
    from datetime import date
    from itcj2.core.models.academic_period import AcademicPeriod

    n = next(_seq)
    p = AcademicPeriod(code=f"T{n:05d}", name=f"Prórrogas prueba {n}", start_date=date(2091, 1, 10),
                       end_date=date(2091, 6, 20), status="INACTIVE")
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture()
def periodo_hoy(db_session):
    """Semestre vigente hoy; el de inicio más reciente, así que `period_for` lo elige."""
    from datetime import timedelta
    from itcj2.core.models.academic_period import AcademicPeriod
    from itcj2.core.utils.timezone import db_now

    hoy = db_now().date()
    n = next(_seq)
    p = AcademicPeriod(code=f"H{n:05d}", name=f"Prórrogas hoy {n}", start_date=hoy - timedelta(days=1),
                       end_date=hoy + timedelta(days=60), status="INACTIVE")
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture()
def alumno_unido(db_session, estudiante, periodo_hoy):
    """Estudiante que ya se unió (por QR) hace un minuto, dentro del semestre."""
    from datetime import timedelta
    from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaJoin
    from itcj2.core.utils.timezone import db_now

    db_session.add(ProrrogaJoin(user_id=estudiante.id, via="qr", joined_at=db_now() - timedelta(minutes=1)))
    db_session.flush()
    return estudiante


@pytest.fixture()
def firma_png():
    from itcj2.apps.prorrogas_tec.documents.catalog import sample_signature_png

    return sample_signature_png()


@pytest.fixture()
def make_program(db_session):
    """Carrera (`core_programs`), idempotente por nombre (como en TitulaTec)."""
    from itcj2.core.models.program import Program

    def _make(name, level="licenciatura"):
        prog = db_session.query(Program).filter_by(name=name).first()
        if prog is None:
            prog = Program(name=name, level=level)
            db_session.add(prog)
        elif prog.level != level:
            prog.level = level
        db_session.flush()
        return prog

    return _make


@pytest.fixture()
def solicitud(db_session, make_user, periodo):
    """Solicitud pendiente de un estudiante sintético (con flush + refresh para los defaults del servidor)."""
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest

    u = make_user(first_name="ESTUDIANTE", last_name="PRUEBA", control_number="99400001")
    req = ProrrogaRequest(
        student_id=u.id, period_id=periodo.id, period_label="enero – junio 2091", status="pendiente",
        requested_terms=2, reason="Motivo de prueba de treinta c.", control_number="99400001",
        student_name="ESTUDIANTE PRUEBA", program_name="Ingeniería en Sistemas Computacionales",
        email="L99400001@cdjuarez.tecnm.mx",
    )
    db_session.add(req)
    db_session.flush()
    db_session.refresh(req)
    return req


@pytest.fixture()
def make_aceptada(db_session, make_user, periodo):
    """Solicitud `aceptada` de un estudiante sintético (control 99410xxx por secuencia)."""
    from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
    from itcj2.core.utils.timezone import db_now

    def _make(control_number=None):
        control = control_number or f"99410{next(_seq):03d}"
        u = make_user(first_name="ESTUDIANTE", last_name="PRUEBA", control_number=control)
        req = ProrrogaRequest(
            student_id=u.id, period_id=periodo.id, period_label="enero – junio 2091", status="aceptada",
            requested_terms=2, reason="Motivo de prueba de treinta c.", control_number=control,
            student_name="ESTUDIANTE PRUEBA", program_name="Ingeniería en Sistemas Computacionales",
            email=f"L{control}@cdjuarez.tecnm.mx", decided_at=db_now(),
        )
        db_session.add(req)
        db_session.flush()
        db_session.refresh(req)
        return req

    return _make


@pytest.fixture()
def aceptada(make_aceptada):
    return make_aceptada()


@pytest.fixture()
def pdf_falso(monkeypatch):
    """Parcha la conversión a PDF; `.calls` guarda los marcadores que quedaron y el kind."""
    from types import SimpleNamespace

    from itcj2.apps.prorrogas_tec.services.docx_fill import find_placeholders
    from itcj2.core.utils import docx_pdf

    calls = []

    def fake(data, *, kind):
        calls.append({"placeholders": find_placeholders(data), "kind": kind})
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(docx_pdf, "docx_to_pdf", fake)
    return SimpleNamespace(calls=calls)


@pytest.fixture()
def enviar_correo(monkeypatch):
    """Parcha `notify.send_email`; `.calls` guarda los kwargs de cada envío."""
    from types import SimpleNamespace

    from itcj2.apps.prorrogas_tec.services import notify

    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(notify, "send_email", fake)
    return SimpleNamespace(calls=calls)


@pytest.fixture()
def avisos(monkeypatch):
    """Parcha `notify.notify_student`; `.calls` guarda `(kind, req.id, link)`."""
    from types import SimpleNamespace

    from itcj2.apps.prorrogas_tec.services import notify

    calls = []
    monkeypatch.setattr(notify, "notify_student",
                        lambda db, req, *, kind, link: calls.append((kind, req.id, link)))
    return SimpleNamespace(calls=calls)

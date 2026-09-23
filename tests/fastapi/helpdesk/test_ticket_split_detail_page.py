"""
Tests de página del botón "Partir" en el DETALLE del ticket
(`GET /help-desk/{user,technician,department}/tickets/{id}`).

Fase 2, tarea 11 (docs/superpowers/specs/2026-09-22-helpdesk-partir-ticket-design.md
§2-bis, D19): las tres rutas de detalle (una por rol: solicitante/técnico/jefe
de depto) renderizan la MISMA plantilla (`helpdesk/user/ticket_detail.html`) y
le pasan `split_scope` (el valor de `can_split()`, `pages/nav.py`, ya probado
en `test_ticket_split_page.py`/`test_ticket_split_tech_page.py`). A diferencia
de esas dos pantallas, el botón "Partir" del detalle lo pinta JS puro
(`renderQuickActions()` en `ticket_detail.js`, contra el JSON que trae
`loadTicketDetail()`), no Jinja — así que el servidor no puede probarse por la
presencia del botón en el HTML. Lo que SÍ puede (y debe) probarse por HTTP es
que `split_scope` de verdad LLEGA a la plantilla: el atributo
`data-split-scope="..."` del `[data-hd-page]` y el modal `#splitTicketModal`
(`{% if split_scope %}`). El botón en sí (client-side) queda cubierto por el
QA de navegador de esta misma tarea.

El VALOR importa, no solo que sea verdadero: el cliente distingue "all" (puede
partir cualquier ticket que vea) de "own" (solo lo suyo o la cola sin asignar
de su equipo, D17). Por eso cada ruta se prueba con los DOS alcances — una
errata en el `return` de `can_split()` dejaría el botón muerto para todos los
técnicos (que solo tienen `.split.own`) con la suite en verde.

Ninguna de las tres rutas de detalle consulta el ticket en el servidor (todo
el fetch es client-side vía `HelpdeskUtils.api.getTicket`), así que estos tests
no necesitan sembrar un `Ticket` — solo lo que cada `require_page_app` exige
para dejar pasar la página, más (para department) un puesto "jefe" real
(`_get_managed_department`, código `head_%`) o la ruta responde 403 antes de
renderizar nada.

Infraestructura: mismo patrón que las dos suites hermanas — `patched_session_local`
parchea `itcj2.database.SessionLocal` (las rutas y `can_split()` abren su propia
sesión) y `require_page_app` NO bypasea al admin del JWT (gotcha #6 de
CLAUDE.md no aplica aquí: hace falta el permiso real).
"""
from datetime import date, timedelta
from uuid import uuid4
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

SPLIT_PERM_ALL = "helpdesk.tickets.api.split.all"
SPLIT_PERM_OWN = "helpdesk.tickets.api.split.own"
USER_PAGE_PERM = "helpdesk.tickets.api.read.own"
TECH_DEPT_PAGE_PERM = "helpdesk.tickets.page.my_tickets"
MODAL_MARK = 'id="splitTicketModal"'


def _scope_mark(scope: str) -> str:
    """El alcance viaja en el `[data-hd-page]`, NO en un `<script>` inline: el
    <body> lo reemplaza htmx con morph y un `const` de nivel superior
    reejecutado en la revisita es un SyntaxError que aborta el swap."""
    return f'data-split-scope="{scope}"'


def _team_mark(team: str) -> str:
    return f'data-split-team="{team}"'


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real; `get_db` (lo usa `require_page_app`) apunta a
    la sesión transaccional del test."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def patched_session_local(db_session, monkeypatch):
    """El código que abre `SessionLocal()` por su cuenta usa la sesión del test.

    El proxy deja pasar todo menos `close()` y `rollback()`: cerrar la sesión del
    test rompería el resto del test, y un rollback volvería al SAVEPOINT y
    borraría las filas que sembró (ver `tests/fastapi/core/conftest.py`). También
    soporta el protocolo de context manager (`__enter__`/`__exit__`):
    `department.py::_get_managed_department` abre la sesión con
    `with SessionLocal() as db:`, a diferencia de las rutas de user/technician
    (`SessionLocal(); try/finally: close()`).
    """
    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

        def rollback(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("itcj2.database.SessionLocal", lambda: _NoClose(db_session))
    return db_session


def _jwt_cookie(user_id: int, role: str | None = None) -> dict:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": role, "cn": None, "name": "Test",
        "iat": now, "exp": now + 24 * 3600,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _dept(db, code) -> Department:
    d = Department(code=code, name=code, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _perm(db, app, code) -> Permission:
    """Get-or-create: en CI (BD vacía por create_all) la fila del permiso no
    existe hasta que corre el DML, así que el test la siembra."""
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _grant_position_perms(db, user, department, codes, code_prefix="tksplit_det_") -> Position:
    """Puesto con `codes` DIRECTOS vía `PositionAppPerm` (sin ningún rol de
    helpdesk) — mismo patrón que `test_ticket_split_page.py::_grant_position_perms`.

    `code_prefix="head_"` además hace que el puesto cuente como "departamento
    gestionado" (`positions_service.get_user_managed_departments`, que exige
    `Position.code LIKE 'head_%'`): lo usan los tests de la ruta `department.py`.
    """
    app = db.query(App).filter_by(key="helpdesk").first()
    pos = Position(code=f"{code_prefix}{user.id}_{uuid4().hex[:6]}", title="Puesto de prueba",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    for code in codes:
        perm = _perm(db, app, code)
        db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _grant_role(db, user, role_name) -> Role:
    """Rol LITERAL del usuario en helpdesk (`UserAppRole`), sin permisos: aquí
    solo interesa el nombre, que es de donde `utils/teams.py::tech_team()` saca
    el equipo. Los permisos siguen viniendo del puesto para que el test valga
    igual en la BD de dev (donde `tech_soporte` ya trae `.split.own` por el DML)
    y en la de CI (vacía, donde no trae nada)."""
    app = db.query(App).filter_by(key="helpdesk").first()
    role = db.query(Role).filter_by(name=role_name).first()
    if not role:
        role = Role(name=role_name)
        db.add(role)
        db.commit()
        db.refresh(role)
    exists = db.query(UserAppRole).filter_by(user_id=user.id, app_id=app.id, role_id=role.id).first()
    if not exists:
        db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
        db.commit()
    return role


# ─────────────────────────────────── tests ────────────────────────────────────

class TestSplitScopeInUserDetailPage:
    """GET /help-desk/user/tickets/{id} — solicitante/técnico genérico."""

    URL = "/help-desk/user/tickets/999999"

    def test_reaches_template_with_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_u_ok")
        user = _user(db, "SplitDetUOK")
        _grant_position_perms(db, user, dept, [USER_PAGE_PERM, SPLIT_PERM_ALL])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("all") in resp.text
        assert MODAL_MARK in resp.text

    def test_own_scope_reaches_template(self, client, patched_session_local):
        """Solo `.split.own` → la página lleva "own", no "all" ni vacío. Es el
        caso de TODOS los técnicos: una errata en el `return` de `can_split()`
        les dejaría el botón muerto sin romper el caso `.all`."""
        db = patched_session_local
        dept = _dept(db, "tksplitdet_u_own")
        user = _user(db, "SplitDetUOWN")
        _grant_position_perms(db, user, dept, [USER_PAGE_PERM, SPLIT_PERM_OWN])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _scope_mark("all") not in resp.text
        assert MODAL_MARK in resp.text

    def test_omits_scope_without_split_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_u_no")
        user = _user(db, "SplitDetUNO")
        _grant_position_perms(db, user, dept, [USER_PAGE_PERM])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("") in resp.text
        assert MODAL_MARK not in resp.text


class TestSplitScopeInTechnicianDetailPage:
    """GET /help-desk/technician/tickets/{id}."""

    URL = "/help-desk/technician/tickets/999999"

    def test_reaches_template_with_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_t_ok")
        user = _user(db, "SplitDetTOK")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM, SPLIT_PERM_ALL])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("all") in resp.text
        assert MODAL_MARK in resp.text

    def test_own_scope_reaches_template(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_t_own")
        user = _user(db, "SplitDetTOWN")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM, SPLIT_PERM_OWN])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _scope_mark("all") not in resp.text
        assert MODAL_MARK in resp.text

    def test_omits_scope_without_split_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_t_no")
        user = _user(db, "SplitDetTNO")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM])

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("") in resp.text
        assert MODAL_MARK not in resp.text


class TestSplitScopeInDepartmentDetailPage:
    """GET /help-desk/department/tickets/{id} — exige además un puesto "jefe"
    real (`_get_managed_department`), no solo el permiso de página."""

    URL = "/help-desk/department/tickets/999999"

    def test_reaches_template_with_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_d_ok")
        user = _user(db, "SplitDetDOK")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM, SPLIT_PERM_ALL], code_prefix="head_")

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("all") in resp.text
        assert MODAL_MARK in resp.text

    def test_own_scope_reaches_template(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_d_own")
        user = _user(db, "SplitDetDOWN")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM, SPLIT_PERM_OWN], code_prefix="head_")

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _scope_mark("all") not in resp.text
        assert MODAL_MARK in resp.text

    def test_omits_scope_without_split_permission(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_d_no")
        user = _user(db, "SplitDetDNO")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM], code_prefix="head_")

        resp = client.get(self.URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("") in resp.text
        assert MODAL_MARK not in resp.text


class TestSplitTeamInDetailPage:
    """El EQUIPO del actor también viaja a la plantilla (I2).

    Con alcance `.own` el guard de `POST /tickets/{id}/split` solo deja partir
    lo propio o lo que siga SIN ASIGNAR en la cola de ESE equipo (D17). Sin el
    equipo en la página, el cliente ofrecía "Partir" para la cola de CUALQUIER
    equipo y el técnico cobraba el 403 con el modal ya lleno.
    """

    TECH_URL = "/help-desk/technician/tickets/999999"
    USER_URL = "/help-desk/user/tickets/999999"

    def test_technician_detail_carries_actor_team(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_team_t")
        user = _user(db, "SplitDetTeamT")
        _grant_position_perms(db, user, dept, [TECH_DEPT_PAGE_PERM, SPLIT_PERM_OWN])
        _grant_role(db, user, "tech_soporte")

        resp = client.get(self.TECH_URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _team_mark("soporte") in resp.text

    def test_user_detail_carries_actor_team(self, client, patched_session_local):
        db = patched_session_local
        dept = _dept(db, "tksplitdet_team_u")
        user = _user(db, "SplitDetTeamU")
        _grant_position_perms(db, user, dept, [USER_PAGE_PERM, SPLIT_PERM_OWN])
        _grant_role(db, user, "tech_desarrollo")

        resp = client.get(self.USER_URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _team_mark("desarrollo") in resp.text

    def test_non_technician_carries_empty_team(self, client, patched_session_local):
        """Sin rol `tech_*` no hay cola de equipo que mirar: el atributo llega
        vacío y el cliente solo ofrece "Partir" sobre lo asignado a uno mismo."""
        db = patched_session_local
        dept = _dept(db, "tksplitdet_team_none")
        user = _user(db, "SplitDetTeamNone")
        _grant_position_perms(db, user, dept, [USER_PAGE_PERM, SPLIT_PERM_OWN])

        resp = client.get(self.USER_URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert _scope_mark("own") in resp.text
        assert _team_mark("") in resp.text

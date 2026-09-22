"""
Tests de página del botón "Partir" en el dashboard del técnico
(`GET /help-desk/technician/dashboard`).

Fase 2, tarea 10 (docs/superpowers/specs/2026-09-22-helpdesk-partir-ticket-design.md
§2-bis, D19): el técnico también puede partir, desde SU dashboard, el ticket
que atiende (pestañas Asignados/En Proceso) o uno de la cola de su equipo
(pestaña Equipo). El botón sigue el MISMO criterio `can_split` que la pantalla
de asignación (ahora compartido en `pages/nav.py`, tarea 10) — aquí se prueba
con el permiso `helpdesk.tickets.api.split.own` (roles `tech_desarrollo` /
`tech_soporte` en el DML real), no `.split.all`: es el alcance que de verdad
tienen los técnicos. El guard fino de la API (D17: solo lo propio o la cola de
su equipo) ya lo cubre `test_ticket_split_api.py::TestSplitOwnScope`; aquí solo
se verifica que el botón se pinte (o no) en el DOM.

Se verifica en los DOS caminos del route (`technician.py::dashboard`):
- el FRAGMENTO HTMX de cada pestaña (`?tab=` + `HX-Request`), que cada tab
  recarga por su cuenta: si `can_split` solo llegara a la página completa, el
  botón desaparecería al cambiar de pestaña;
- la PÁGINA completa, que además trae el modal `#splitTicketModal`.

Infraestructura:
- El route (y `_helpdesk_roles`, `_query_tech_tickets`, `can_split`) abre
  `SessionLocal()` con import LOCAL: se parchea `itcj2.database.SessionLocal`
  con un proxy de la sesión del test sin `close()` ni `rollback()` (patrón de
  `tests/fastapi/core/conftest.py::patched_session_local`, copiado aquí como en
  `test_ticket_split_page.py`). Sin eso el fragmento leería la BD de dev real y
  en CI saldría vacío.
- `require_page_app` NO bypasea al admin del JWT: el usuario de estos tests
  necesita el permiso de página real `helpdesk.dashboard.technician` — se
  siembra por `RolePermission` (rol + permiso, la forma real en que
  `tech_desarrollo`/`tech_soporte` lo reciben en el DML), igual que
  `.split.own` en `test_ticket_split_api.py::_grant_role_with_perm`.
- El técnico debe ser el ASIGNADO del ticket sembrado (pestañas Asignados/En
  Proceso) o el ticket debe estar en la cola de SU equipo sin técnico
  (pestaña Equipo, `assigned_to_team` == su equipo vía el rol `tech_soporte`)
  para que el dashboard lo liste — `_query_tech_tickets` filtra por eso.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

DASH_PERM = "helpdesk.dashboard.technician"
SPLIT_PERM_OWN = "helpdesk.tickets.api.split.own"
PAGE_URL = "/help-desk/technician/dashboard"
SPLIT_CALL = "openSplitTicketModal("


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
    borraría las filas que sembró (ver `tests/fastapi/core/conftest.py`).
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


def _htmx_headers(user_id: int, role: str | None = None) -> dict:
    return {**_jwt_cookie(user_id, role), "HX-Request": "true"}


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


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


def _grant_role_with_perm(db, user, role_name, codes) -> Role:
    """Rol del usuario en helpdesk (`UserAppRole`) CON `codes` unidos por
    `RolePermission` — la forma real en que `tech_desarrollo`/`tech_soporte`
    reciben sus permisos en el DML real (mismo helper que
    `test_ticket_split_api.py::_grant_role_with_perm`)."""
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
    for code in codes:
        perm = _perm(db, app, code)
        exists_rp = db.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first()
        if not exists_rp:
            db.add(RolePermission(role_id=role.id, perm_id=perm.id))
    db.commit()
    return role


def _ticket(db, number, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=None,
        area="SOPORTE",
        category_id=category.id,
        priority="MEDIA",
        title=f"{number} - ticket de prueba",
        description="Descripción de prueba con longitud suficiente para pasar validaciones.",
        status="PENDING",
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    defaults.update(overrides)
    t = Ticket(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _seed_tech(db, suffix, codes, role_name="tech_soporte") -> tuple[User, User]:
    """Solicitante + técnico con `codes` por rol (`tech_soporte` por defecto,
    para que `assigned_to_team='soporte'` case con `_tech_team()`). Devuelve
    (requester, tech)."""
    requester = _user(db, f"ReqSplitTech{suffix}")
    tech = _user(db, f"SplitTech{suffix}")
    _grant_role_with_perm(db, tech, role_name, codes)
    ensure_helpdesk_category(db, area="SOPORTE")
    ensure_helpdesk_priority(db, "MEDIA")
    return requester, tech


def _seed_tech_no_split(db, suffix, codes) -> tuple[User, User]:
    """Igual que `_seed_tech`, pero con un rol SINTÉTICO (no `tech_soporte`
    literal): en la BD de dev real `tech_soporte`/`tech_desarrollo` YA traen
    `.split.own` por el DML de la tarea 8 (verificado: 108 permisos, incluido
    `helpdesk.tickets.api.split.own`), así que atar al usuario a ese rol
    literal SIEMPRE le daría el permiso de verdad sin importar qué `codes` se
    pidan aquí. Un rol con otro nombre, nunca tocado por ningún DML, sí
    permite construir "tiene la página pero no el permiso de partir" en las
    dos bases (dev poblada y CI vacía). Válido para assigned/inProgress
    (`assigned_to_me` no depende del nombre del rol); NO sirve para la
    pestaña Equipo (`_tech_team()` exige el nombre literal)."""
    requester = _user(db, f"ReqSplitTech{suffix}")
    tech = _user(db, f"SplitTech{suffix}")
    _grant_role_with_perm(db, tech, f"tksplit_notech_{suffix}", codes)
    ensure_helpdesk_category(db, area="SOPORTE")
    ensure_helpdesk_priority(db, "MEDIA")
    return requester, tech


# ─────────────────────────────────── tests ────────────────────────────────────

class TestSplitButtonInDashboardFragment:
    """El fragmento HTMX que cada pestaña recarga por su cuenta."""

    def test_assigned_fragment_shows_split_button_with_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        requester, tech = _seed_tech(db, "AOK", [DASH_PERM, SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-AOK", requester, category,
                          status="ASSIGNED", assigned_to_user_id=tech.id)

        resp = client.get(f"{PAGE_URL}?tab=assigned", headers=_htmx_headers(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text

    def test_assigned_fragment_hides_split_button_without_permission(
        self, client, patched_session_local,
    ):
        """Tiene `dashboard.technician` (abre la página) pero no `.split.own`:
        la tarjeta sale, el botón no. Rol sintético (`_seed_tech_no_split`):
        en dev real `tech_soporte` YA trae `.split.own` por el DML de la
        tarea 8, así que ese rol literal no sirve para probar "sin permiso"."""
        db = patched_session_local
        requester, tech = _seed_tech_no_split(db, "ANO", [DASH_PERM])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-ANO", requester, category,
                          status="ASSIGNED", assigned_to_user_id=tech.id)

        resp = client.get(f"{PAGE_URL}?tab=assigned", headers=_htmx_headers(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert SPLIT_CALL not in resp.text

    def test_inprogress_fragment_shows_split_button_with_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        requester, tech = _seed_tech(db, "IOK", [DASH_PERM, SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-IOK", requester, category,
                          status="IN_PROGRESS", assigned_to_user_id=tech.id)

        resp = client.get(f"{PAGE_URL}?tab=inProgress", headers=_htmx_headers(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text

    def test_team_fragment_shows_split_button_with_permission(
        self, client, patched_session_local,
    ):
        """La pestaña Equipo (cola sin técnico de SU equipo) también lo lleva."""
        db = patched_session_local
        requester, tech = _seed_tech(db, "TOK", [DASH_PERM, SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-TOK", requester, category,
                          status="ASSIGNED", assigned_to_team="soporte",
                          assigned_to_user_id=None)

        resp = client.get(f"{PAGE_URL}?tab=team", headers=_htmx_headers(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text

    # No hay caso "team sin permiso": `_tech_team()` exige el nombre de rol
    # LITERAL `tech_soporte`/`tech_desarrollo` para resolver la cola del
    # equipo, y en dev real ese rol ya trae `.split.own` (DML de la tarea 8) —
    # no hay forma de construir esa combinación sin borrar un grant real. El
    # caso ya cubierto (`test_assigned_fragment_hides_split_button_without_permission`)
    # prueba lo mismo (mismo `can_split`, ambas ramas del route).


class TestSplitButtonInFullDashboardPage:
    """La página completa: botón en la tarjeta y el modal que abre."""

    def test_full_page_renders_button_and_modal_with_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        requester, tech = _seed_tech(db, "FOK", [DASH_PERM, SPLIT_PERM_OWN])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-FOK", requester, category,
                          status="ASSIGNED", assigned_to_user_id=tech.id)

        resp = client.get(PAGE_URL, headers=_jwt_cookie(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text
        assert 'id="splitTicketModal"' in resp.text

    def test_full_page_omits_button_and_modal_without_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        requester, tech = _seed_tech_no_split(db, "FNO", [DASH_PERM])
        category = ensure_helpdesk_category(db, area="SOPORTE")
        ticket = _ticket(db, "TKSTD-FNO", requester, category,
                          status="ASSIGNED", assigned_to_user_id=tech.id)

        resp = client.get(PAGE_URL, headers=_jwt_cookie(tech.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert SPLIT_CALL not in resp.text
        assert 'id="splitTicketModal"' not in resp.text

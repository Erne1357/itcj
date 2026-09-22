"""
Tests de página del botón "Partir" en la pantalla de asignación
(`GET /help-desk/admin/assign-tickets`).

El botón solo se pinta con `can_split`: admin global del JWT o el permiso
efectivo `helpdesk.tickets.api.split` — el mismo criterio que el guard del
endpoint `POST /tickets/{id}/split`. Se verifica en los DOS caminos del route:

- el FRAGMENTO HTMX de cada lista (`?tab=` + `HX-Request`), que `refreshLists()`
  recarga tras cada acción: si `can_split` solo llegara a la página completa, el
  botón desaparecería tras el primer refresco;
- la PÁGINA completa, que además trae el modal `#splitTicketModal`.

Infraestructura:
- El route (y `_helpdesk_roles`, `_query_assign_lists_ctx`, `_can_split`) abre
  `SessionLocal()` con import LOCAL: se parchea `itcj2.database.SessionLocal`
  con un proxy de la sesión del test sin `close()` ni `rollback()` (patrón de
  `tests/fastapi/core/conftest.py::patched_session_local`). Sin eso el
  fragmento leería la BD de dev real y en CI saldría vacío.
- `require_page_app` NO bypasea al admin del JWT: todo usuario de estos tests
  necesita el permiso de página real `helpdesk.assignments.page.list`.
- Para que la lista pinte una tarjeta también en CI (BD vacía), el usuario del
  test es el SOLICITANTE del ticket sembrado: `list_tickets` le da visibilidad
  por propiedad aunque no tenga ningún rol de helpdesk. Cada test afirma que la
  tarjeta está, para que la ausencia del botón nunca pase por una lista vacía.
"""
from datetime import date, timedelta
from uuid import uuid4
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category, ensure_helpdesk_priority

PAGE_PERM = "helpdesk.assignments.page.list"
SPLIT_PERM = "helpdesk.tickets.api.split"
PAGE_URL = "/help-desk/admin/assign-tickets"
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


def _grant_position_perms(db, user, department, codes) -> Position:
    """Puesto con los permisos DIRECTOS vía `PositionAppPerm`, sin ningún rol de
    helpdesk — la forma en que `secretary_comp_center` recibe tanto la página
    como el permiso de partir en el DML real."""
    app = db.query(App).filter_by(key="helpdesk").first()
    pos = Position(code=f"tksplit_page_{user.id}_{uuid4().hex[:6]}", title="Secretaria",
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


def _ticket(db, number, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=None,
        area="DESARROLLO",
        category_id=category.id,
        priority="MEDIA",
        title=f"{number} - cuentas de Moodle, correo y SII",
        description="Solicitud con varias cosas que debería partirse en varios tickets.",
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


def _seed(db, suffix, codes, **ticket_overrides):
    """Usuario con `codes` por puesto + un ticket suyo (él es el solicitante).
    Devuelve (user, ticket)."""
    dept = _dept(db, f"tksplit_page_{suffix}")
    user = _user(db, f"SplitPage{suffix}")
    _grant_position_perms(db, user, dept, codes)
    category = ensure_helpdesk_category(db, area="DESARROLLO")
    ensure_helpdesk_priority(db, "MEDIA")
    ticket = _ticket(db, f"TKSP-{suffix}", user, category, **ticket_overrides)
    return user, ticket


# ─────────────────────────────────── tests ────────────────────────────────────

class TestSplitButtonInFragment:
    """El fragmento HTMX que recarga `refreshLists()` tras cada acción."""

    def test_queue_fragment_shows_split_button_with_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        user, ticket = _seed(db, "QOK", [PAGE_PERM, SPLIT_PERM])

        resp = client.get(f"{PAGE_URL}?tab=queue", headers=_htmx_headers(user.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text

    def test_queue_fragment_hides_split_button_without_permission(
        self, client, patched_session_local,
    ):
        """Abre la página (tiene `assignments.page.list`) pero no puede partir:
        la tarjeta sale, el botón no."""
        db = patched_session_local
        user, ticket = _seed(db, "QNO", [PAGE_PERM])

        resp = client.get(f"{PAGE_URL}?tab=queue", headers=_htmx_headers(user.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert SPLIT_CALL not in resp.text

    def test_assigned_fragment_shows_split_button_with_permission(
        self, client, patched_session_local,
    ):
        """El segundo juego de acciones (Asignado / En Proceso) también lo lleva."""
        db = patched_session_local
        tech = _user(db, "SplitPageTech")
        user, ticket = _seed(
            db, "AOK", [PAGE_PERM, SPLIT_PERM],
            status="ASSIGNED", assigned_to_user_id=tech.id,
        )

        resp = client.get(f"{PAGE_URL}?tab=assigned", headers=_htmx_headers(user.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text

    def test_global_admin_sees_split_button_without_db_permission(
        self, client, patched_session_local,
    ):
        """Mismo bypass que `require_perms`: el admin global del JWT puede partir
        aunque su permiso no esté en BD (p. ej. antes de correr el DML)."""
        db = patched_session_local
        user, ticket = _seed(db, "ADM", [PAGE_PERM])

        resp = client.get(f"{PAGE_URL}?tab=queue", headers=_htmx_headers(user.id, role="admin"))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text


class TestSplitButtonInFullPage:
    """La página completa: botón en la tarjeta y el modal que abre."""

    def test_full_page_renders_button_and_modal_with_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        user, ticket = _seed(db, "FOK", [PAGE_PERM, SPLIT_PERM])

        resp = client.get(PAGE_URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert f"{SPLIT_CALL}{ticket.id})" in resp.text
        assert 'id="splitTicketModal"' in resp.text

    def test_full_page_omits_button_and_modal_without_permission(
        self, client, patched_session_local,
    ):
        db = patched_session_local
        user, ticket = _seed(db, "FNO", [PAGE_PERM])

        resp = client.get(PAGE_URL, headers=_jwt_cookie(user.id))

        assert resp.status_code == 200, resp.text
        assert ticket.ticket_number in resp.text
        assert SPLIT_CALL not in resp.text
        assert 'id="splitTicketModal"' not in resp.text

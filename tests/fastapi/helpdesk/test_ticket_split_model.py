"""Vinculo `split_from_ticket_id` entre un ticket y los tickets partidos de el
(feature "Partir ticket"). Este task (1/7) solo cubre la columna, la relacion
ORM y la serializacion — el endpoint que crea los hijos llega en una tarea
posterior.

Cubre:
  * `to_dict()` trae `split_from_ticket_id` SIEMPRE (con o sin padre).
  * `to_dict(include_relations=True)` trae `split_from` = {id, ticket_number}
    del padre, o None si no tiene.
  * `GET /tickets/{padre}` trae `split_children` con los hijos, en orden de id.
  * Borrar al padre deja a los hijos con `split_from_ticket_id = NULL`
    (valida el `ON DELETE SET NULL` de la migracion `hd20260922a`, no solo el
    nullify que haria el ORM por su cuenta).
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

from ._catalog import ensure_helpdesk_category


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, `get_db` apunta a la sesion transaccional del
    test (mismo patron que test_broadcast_single_emit.py)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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


def _ticket(db, number, requester, category, **overrides) -> Ticket:
    defaults = dict(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=None,
        area="DESARROLLO",
        category_id=category.id,
        priority="MEDIA",
        title=f"{number} - ticket de prueba",
        description="Descripcion de prueba con longitud suficiente para pasar validaciones.",
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


# ─────────────────────────────────── tests ────────────────────────────────────

class TestSplitFromSerialization:
    def test_to_dict_always_includes_split_from_ticket_id_with_parent(self, db_session):
        requester = _user(db_session, "ReqSplitDict")
        category = ensure_helpdesk_category(db_session)
        padre = _ticket(db_session, "TSP-DICT-PADRE", requester, category)
        hijo = _ticket(
            db_session, "TSP-DICT-HIJO", requester, category,
            split_from_ticket_id=padre.id,
        )

        data = hijo.to_dict()
        assert data["split_from_ticket_id"] == padre.id

    def test_to_dict_split_from_ticket_id_is_none_without_parent(self, db_session):
        requester = _user(db_session, "ReqSplitDictNone")
        category = ensure_helpdesk_category(db_session)
        suelto = _ticket(db_session, "TSP-DICT-SUELTO", requester, category)

        data = suelto.to_dict()
        assert data["split_from_ticket_id"] is None

    def test_include_relations_serializes_split_from_parent(self, db_session):
        requester = _user(db_session, "ReqSplitRel")
        category = ensure_helpdesk_category(db_session)
        padre = _ticket(db_session, "TSP-REL-PADRE", requester, category)
        hijo = _ticket(
            db_session, "TSP-REL-HIJO", requester, category,
            split_from_ticket_id=padre.id,
        )

        data = hijo.to_dict(include_relations=True)
        assert data["split_from"] == {"id": padre.id, "ticket_number": padre.ticket_number}

    def test_include_relations_split_from_is_none_without_parent(self, db_session):
        requester = _user(db_session, "ReqSplitRelNone")
        category = ensure_helpdesk_category(db_session)
        suelto = _ticket(db_session, "TSP-REL-SUELTO", requester, category)

        data = suelto.to_dict(include_relations=True)
        assert data["split_from"] is None


class TestSplitChildrenRelationship:
    def test_split_children_returns_children_ordered_by_id(self, db_session):
        requester = _user(db_session, "ReqSplitChildren")
        category = ensure_helpdesk_category(db_session)
        padre = _ticket(db_session, "TSP-CHILDREN-PADRE", requester, category)
        hijo_1 = _ticket(
            db_session, "TSP-CHILDREN-HIJO-1", requester, category,
            split_from_ticket_id=padre.id,
        )
        hijo_2 = _ticket(
            db_session, "TSP-CHILDREN-HIJO-2", requester, category,
            split_from_ticket_id=padre.id,
        )
        assert hijo_1.id < hijo_2.id  # precondicion: el orden por id es significativo

        children = padre.split_children.all()
        assert [c.id for c in children] == [hijo_1.id, hijo_2.id]

    def test_split_children_empty_for_ticket_without_children(self, db_session):
        requester = _user(db_session, "ReqSplitNoChildren")
        category = ensure_helpdesk_category(db_session)
        suelto = _ticket(db_session, "TSP-NOCHILDREN", requester, category)

        assert suelto.split_children.all() == []


class TestGetTicketEndpointSplitChildren:
    def test_get_ticket_returns_split_children_in_order(self, client, db_session):
        requester = _user(db_session, "ReqSplitApi")
        category = ensure_helpdesk_category(db_session)
        padre = _ticket(db_session, "TSP-API-PADRE", requester, category)
        hijo_1 = _ticket(
            db_session, "TSP-API-HIJO-1", requester, category,
            split_from_ticket_id=padre.id, title="Hijo uno", status="PENDING",
        )
        hijo_2 = _ticket(
            db_session, "TSP-API-HIJO-2", requester, category,
            split_from_ticket_id=padre.id, title="Hijo dos", status="PENDING",
        )

        # `requester` es el dueno del ticket padre -> can_user_view_ticket lo deja
        # pasar por `ticket.requester_id == user_id`, sin depender de roles en BD.
        # `role="admin"` en el JWT solo cubre el bypass de `require_perms` (gotcha
        # #6 de CLAUDE.md) — can_user_view_ticket es un chequeo APARTE que lee
        # roles de BD, no el claim del JWT.
        resp = client.get(
            f"/api/help-desk/v2/tickets/{padre.id}",
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 200, resp.text

        ticket_dict = resp.json()["ticket"]
        assert ticket_dict["split_children"] == [
            {
                "id": hijo_1.id,
                "ticket_number": hijo_1.ticket_number,
                "title": hijo_1.title,
                "status": hijo_1.status,
            },
            {
                "id": hijo_2.id,
                "ticket_number": hijo_2.ticket_number,
                "title": hijo_2.title,
                "status": hijo_2.status,
            },
        ]

    def test_get_ticket_split_children_empty_list_without_children(self, client, db_session):
        requester = _user(db_session, "ReqSplitApiEmpty")
        category = ensure_helpdesk_category(db_session)
        suelto = _ticket(db_session, "TSP-API-SUELTO", requester, category)

        resp = client.get(
            f"/api/help-desk/v2/tickets/{suelto.id}",
            headers=_jwt_cookie(requester.id, role="admin"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ticket"]["split_children"] == []


class TestSplitFromDeleteSetsNull:
    def test_deleting_parent_sets_child_split_from_ticket_id_null(self, db_session):
        """Valida el `ON DELETE SET NULL` de la FK creada en `hd20260922a`: al
        borrar al padre, el hijo no se borra en cascada ni bloquea el borrado —
        solo pierde la referencia."""
        requester = _user(db_session, "ReqSplitDelete")
        category = ensure_helpdesk_category(db_session)
        padre = _ticket(db_session, "TSP-DELETE-PADRE", requester, category)
        hijo = _ticket(
            db_session, "TSP-DELETE-HIJO", requester, category,
            split_from_ticket_id=padre.id,
        )

        db_session.delete(padre)
        db_session.flush()
        db_session.refresh(hijo)

        assert hijo.split_from_ticket_id is None

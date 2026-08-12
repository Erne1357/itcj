"""`recent_comments[i]["id"]` en `GET /api/help-desk/v2/stats/ratings-detail`.

Antes el endpoint devolvía `{ticket_number, rating, comment, date}` SIN `id`,
así que el frontend no podía ligar el comentario a su ticket (ni modal de
resumen ni navegación al detalle). Este test fija el contrato: cada entrada de
`recent_comments` trae `id` y apunta al ticket correcto (no solo "algún id").
"""
import time
from datetime import datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app
from itcj2.core.utils.timezone import db_now

API = "/api/help-desk/v2/stats"
SUBTREE = "helpdesk.stats.api.read.subtree"


@pytest.fixture()
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jwt_cookie(user_id: int) -> dict:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": None, "cn": None, "name": "Test",
        "iat": now, "exp": now + 24 * 3600,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _helpdesk(db) -> App:
    app = db.query(App).filter_by(key="helpdesk").first()
    assert app is not None, "helpdesk app debe existir en la BD dev"
    return app


def _perm(db, app, code) -> Permission:
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _dept(db, code) -> Department:
    d = Department(code=code, name=code, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _user(db, last) -> User:
    u = User(first_name="T", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db) -> Category:
    c = db.query(Category).filter_by(code="rid_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="rid_cat", name="rid", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _grant(db, user, department, *, code=SUBTREE) -> Position:
    """`.subtree` (no `.read`) A PROPÓSITO: acota el endpoint a `department`,
    aislando la aserción de los tickets/comentarios reales que ya existen en
    la BD de dev (`.read` = acceso total = ve TODO lo que haya en la tabla)."""
    app = _helpdesk(db)
    pos = Position(code=f"ridpos_{user.id}", title="Admin",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    from datetime import date, timedelta as td
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=date.today() - td(days=1), is_active=True,
    ))
    perm = _perm(db, app, code)
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _rated_ticket(db, number, requester, department, rating, comment):
    now = db_now()
    t = Ticket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        area="SOPORTE",
        category_id=_category(db).id,
        priority="MEDIA",
        title=f"Título {number}",
        description="x",
        status="CLOSED",
        rating_attention=rating,
        rating_comment=comment,
        rated_at=now,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


class TestRecentCommentsIncludeTicketId:

    def test_id_present_and_matches_correct_ticket(self, client, db_session):
        dept = _dept(db_session, "rid_dept1")
        requester = _user(db_session, "Req1")
        boss = _user(db_session, "Boss1")
        _grant(db_session, boss, dept)

        t = _rated_ticket(db_session, "RID-1", requester, dept, 5, "Excelente atención")

        resp = client.get(f"{API}/ratings-detail", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        comments = resp.json()["data"]["recent_comments"]
        assert len(comments) == 1
        assert comments[0]["id"] == t.id
        assert comments[0]["ticket_number"] == "RID-1"

    def test_multiple_comments_each_id_matches_its_own_ticket(self, client, db_session):
        dept = _dept(db_session, "rid_dept2")
        requester = _user(db_session, "Req2")
        boss = _user(db_session, "Boss2")
        _grant(db_session, boss, dept)

        now = db_now()
        t1 = _rated_ticket(db_session, "RID-2A", requester, dept, 5, "Comentario A")
        t1.rated_at = now - timedelta(minutes=1)
        t2 = _rated_ticket(db_session, "RID-2B", requester, dept, 3, "Comentario B")
        t2.rated_at = now
        db_session.commit()

        resp = client.get(f"{API}/ratings-detail", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        comments = resp.json()["data"]["recent_comments"]
        by_number = {c["ticket_number"]: c for c in comments}
        assert len(by_number) == 2
        assert by_number["RID-2A"]["id"] == t1.id
        assert by_number["RID-2B"]["id"] == t2.id
        # No deben cruzarse (cada id apunta a SU comentario, no al del otro).
        assert by_number["RID-2A"]["id"] != by_number["RID-2B"]["id"]

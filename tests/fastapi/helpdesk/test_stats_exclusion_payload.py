"""`exclusion_info` de `_exclude_outlier_tickets` (`api/stats.py`) trae las
CUATRO claves que el frontend lee.

Antes solo devolvía `{excluded_count, upper_fence}`; stats.js:116-118 y
analysis.js:66-69 también leen `original_count`/`filtered_count`/`pct_excluded`
-> el banner de "modo sin outliers" imprimía literalmente "undefined". Como
`_exclude_outlier_tickets` es la fuente única para TODOS los endpoints con
`exclude_outliers` (stats y analysis), un solo test por endpoint alcanza para
cubrir ambos consumidores.

Escenario determinista: 5 tickets resueltos con horas de resolución
[1, 2, 3, 4, 100]. IQR: q1=sv[5//4]=2, q3=sv[(3*5)//4]=4, iqr=2,
upper_fence=4+1.5*2=7 -> excluye solo el de 100h.
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
    c = db.query(Category).filter_by(code="excl_cat").first()
    if not c:
        c = Category(area="SOPORTE", code="excl_cat", name="excl", is_active=True)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def _grant(db, user, department, *, code=SUBTREE) -> Position:
    """`.subtree` (no `.read`) A PROPÓSITO: acota el endpoint a `department`,
    aislando el escenario de outliers (5 tickets exactos) de los tickets
    resueltos reales que ya existen en la BD de dev (`.read` = acceso total =
    los cuenta a todos y el IQR deja de ser el determinista que este test
    calcula a mano)."""
    app = _helpdesk(db)
    pos = Position(code=f"exclpos_{user.id}", title="Admin",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    from datetime import date
    db.add(UserPosition(
        user_id=user.id, position_id=pos.id,
        start_date=date.today() - timedelta(days=1), is_active=True,
    ))
    perm = _perm(db, app, code)
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _resolved_ticket(db, number, requester, department, hours):
    created = db_now() - timedelta(hours=hours + 1)
    resolved = created + timedelta(hours=hours)
    t = Ticket(
        ticket_number=number,
        requester_id=requester.id,
        requester_department_id=department.id,
        area="SOPORTE",
        category_id=_category(db).id,
        priority="MEDIA",
        title=f"Título {number}",
        description="x",
        status="RESOLVED_SUCCESS",
        created_at=created,
        resolved_at=resolved,
        created_by_id=requester.id,
        updated_by_id=requester.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _seed_outlier_scenario(db, prefix):
    dept = _dept(db, f"{prefix}_dept")
    requester = _user(db, f"Req_{prefix}")
    boss = _user(db, f"Boss_{prefix}")
    _grant(db, boss, dept)
    for i, hours in enumerate([1, 2, 3, 4, 100]):
        _resolved_ticket(db, f"{prefix}-{i}", requester, dept, hours)
    return boss


def _assert_exclusion_info_shape(info):
    assert info is not None
    for key in ("excluded_count", "upper_fence", "original_count", "filtered_count", "pct_excluded"):
        assert key in info, f"falta la clave {key}"

    assert info["original_count"] == 5
    assert info["excluded_count"] == 1
    assert info["filtered_count"] == 4
    assert info["filtered_count"] + info["excluded_count"] == info["original_count"]
    assert info["pct_excluded"] == 20.0
    assert info["upper_fence"] == 7.0


class TestGlobalStatsExclusionInfo:

    def test_four_keys_present_and_coherent(self, client, db_session):
        boss = _seed_outlier_scenario(db_session, "exclg")

        resp = client.get(f"{API}/global?exclude_outliers=1", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        _assert_exclusion_info_shape(resp.json()["data"]["exclusion_info"])


class TestAnalysisDistributionExclusionInfo:

    def test_four_keys_present_and_coherent(self, client, db_session):
        """analysis.js:67-69 lee las mismas tres claves nuevas en los endpoints
        de `/analysis/*` — `_exclude_outlier_tickets` es la fuente única, así
        que basta con un endpoint representativo (distribution) para
        confirmar que el fix no quedó aislado a `/stats/global`."""
        boss = _seed_outlier_scenario(db_session, "excld")

        resp = client.get(f"{API}/analysis/distribution?exclude_outliers=1", headers=_jwt_cookie(boss.id))
        assert resp.status_code == 200
        _assert_exclusion_info_shape(resp.json()["data"]["exclusion_info"])

"""Asignación de usuario durante la verificación física de inventario.

Motivación (ver CAMBIOS pedidos): el modal de verificar hoy permite confirmar
ubicación/estado/marca/modelo/series/grupo/specs, pero NO la asignación a
usuario — justo el dato que más se desfasa en campo. Se agrega el campo
`assigned_to_user_id` al mismo submit de verificación.

TRAMPA CRÍTICA cubierta explícitamente: `verify_item` NO debe delegar en
`InventoryService.assign_to_user` / `unassign_from_user` — ambos comprometen
el patrón porque (1) hacen commit propio (partirían la transacción), (2)
`assign_to_user` exige `status == 'ACTIVE'` (revienta si el mismo submit marca
el equipo como DAMAGED) y (3) `unassign_from_user` revienta si el equipo ya
está sin asignar (el caso "sin asignar" sobre global no podría llamarlo).
"""
from datetime import date, timedelta
from uuid import uuid4

import time

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401 (resuelve mappers)
from itcj2.apps.helpdesk.models import InventoryHistory, InventoryItem
from itcj2.apps.helpdesk.models.inventory_category import InventoryCategory
from itcj2.apps.helpdesk.models.inventory_verification import InventoryVerification
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.position import Position, PositionAppPerm, UserPosition
from itcj2.core.models.user import User
from itcj2.database import get_db
from itcj2.main import create_app

VERIFY = "helpdesk.inventory.api.verify"


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real; `get_db` apunta a la sesión transaccional de
    Postgres del test (rollback al final)."""
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
    u = User(first_name="W", last_name=last, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _category(db) -> InventoryCategory:
    c = db.query(InventoryCategory).filter_by(code="va_cat").first()
    if c:
        return c
    c = InventoryCategory(code="va_cat", name="Cat", inventory_prefix="VA")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _item(db, number, department, registered_by, **kw) -> InventoryItem:
    it = InventoryItem(
        inventory_number=number,
        category_id=_category(db).id,
        department_id=department.id,
        registered_by_id=registered_by.id,
        status=kw.pop("status", "ACTIVE"),
        is_active=True,
        **kw,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _grant_verify(db, user, department) -> None:
    """Ancla `user` en `department` con un puesto que otorga VERIFY."""
    app = _helpdesk(db)
    pos = Position(code=f"verifpos_{user.id}_{uuid4().hex[:8]}", title="Verificador",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    perm = _perm(db, app, VERIFY)
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _assign_membership(db, user, department) -> None:
    """Ancla a `user` en `department` con un puesto activo SIN permisos — mismo
    criterio que GET /departments/{id}/users (el combo "Asignado a" del modal)."""
    pos = Position(code=f"memberpos_{user.id}_{uuid4().hex[:8]}", title="Staff",
                   department_id=department.id, is_active=True, allows_multiple=True)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                         start_date=date.today() - timedelta(days=1), is_active=True))
    db.commit()


def _verify_url(item_id: int) -> str:
    return f"/api/help-desk/v2/inventory/verification/items/{item_id}/verify"


def _history_events(db, item_id, *event_types):
    q = db.query(InventoryHistory).filter(InventoryHistory.item_id == item_id)
    if event_types:
        q = q.filter(InventoryHistory.event_type.in_(event_types))
    return q.all()


# ───────────────────────────────── tests ─────────────────────────────────────

class TestVerificationAssignment:

    def test_verify_assigns_user_writes_fields_and_history(self, client, db_session):
        dept = _dept(db_session, "va1")
        registrar = _user(db_session, "Reg1")
        verifier = _user(db_session, "Ver1")
        _grant_verify(db_session, verifier, dept)
        target = _user(db_session, "Target1")
        _assign_membership(db_session, target, dept)
        item = _item(db_session, "VA1-ITEM", dept, registrar, status="ACTIVE")

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": target.id, "status": "ACTIVE"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["item"]["assigned_to_user_id"] == target.id
        assert data["item"]["assigned_by"]["id"] == verifier.id
        assert data["item"]["assigned_at"] is not None
        assert data["verification"]["changes_applied"]["assigned_to_user_id"] == {
            "old": None, "new": target.id,
        }

        events = _history_events(db_session, item.id, "ASSIGNED_TO_USER")
        assert len(events) == 1
        assert events[0].performed_by_id == verifier.id
        assert events[0].new_value.get("assigned_to_user_id") == target.id

    def test_verify_unassign_releases_item(self, client, db_session):
        dept = _dept(db_session, "va2")
        registrar = _user(db_session, "Reg2")
        verifier = _user(db_session, "Ver2")
        _grant_verify(db_session, verifier, dept)
        current = _user(db_session, "Current2")
        _assign_membership(db_session, current, dept)
        item = _item(
            db_session, "VA2-ITEM", dept, registrar, status="ACTIVE",
            assigned_to_user_id=current.id, assigned_by_id=registrar.id,
        )

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": None, "status": "ACTIVE"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["item"]["assigned_to_user_id"] is None
        assert data["item"]["assigned_at"] is None

        events = _history_events(db_session, item.id, "UNASSIGNED")
        assert len(events) == 1

    def test_verify_unassign_noop_when_already_unassigned(self, client, db_session):
        dept = _dept(db_session, "va3")
        registrar = _user(db_session, "Reg3")
        verifier = _user(db_session, "Ver3")
        _grant_verify(db_session, verifier, dept)
        item = _item(db_session, "VA3-ITEM", dept, registrar, status="ACTIVE")
        assert item.assigned_to_user_id is None

        before = len(_history_events(db_session, item.id))

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": None, "status": "ACTIVE"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["item"]["assigned_to_user_id"] is None
        # No-op: ni entra a changes_applied ni deja historial de (re)asignación.
        changes = data["verification"]["changes_applied"]
        if changes:
            assert "assigned_to_user_id" not in changes

        assert _history_events(db_session, item.id, "ASSIGNED_TO_USER", "UNASSIGNED", "REASSIGNED") == []
        # Solo se agregó la entrada VERIFIED genérica (siempre se registra).
        after = len(_history_events(db_session, item.id))
        assert after == before + 1

    def test_verify_assignment_and_damaged_status_same_submit(self, client, db_session):
        """El caso que motiva todo el diseño: reasignar Y marcar DAMAGED en el
        MISMO submit. Con `InventoryService.assign_to_user` esto reventaría
        (exige status == 'ACTIVE')."""
        dept = _dept(db_session, "va4")
        registrar = _user(db_session, "Reg4")
        verifier = _user(db_session, "Ver4")
        _grant_verify(db_session, verifier, dept)
        old_user = _user(db_session, "Old4")
        new_user = _user(db_session, "New4")
        _assign_membership(db_session, old_user, dept)
        _assign_membership(db_session, new_user, dept)
        item = _item(
            db_session, "VA4-ITEM", dept, registrar, status="ACTIVE",
            assigned_to_user_id=old_user.id, assigned_by_id=registrar.id,
        )

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": new_user.id, "status": "DAMAGED"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["item"]["status"] == "DAMAGED"
        assert data["item"]["assigned_to_user_id"] == new_user.id

        db_session.refresh(item)
        assert item.status == "DAMAGED"
        assert item.assigned_to_user_id == new_user.id

    def test_verify_updates_last_verified_and_creates_verification_row(self, client, db_session):
        dept = _dept(db_session, "va5")
        registrar = _user(db_session, "Reg5")
        verifier = _user(db_session, "Ver5")
        _grant_verify(db_session, verifier, dept)
        item = _item(db_session, "VA5-ITEM", dept, registrar, status="ACTIVE")
        assert item.last_verified_at is None

        before = db_session.query(InventoryVerification).filter_by(inventory_item_id=item.id).count()

        resp = client.post(
            _verify_url(item.id),
            json={"status": "ACTIVE", "observations": "Todo en orden"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 200, resp.text

        db_session.refresh(item)
        assert item.last_verified_at is not None
        assert item.last_verified_by_id == verifier.id

        after = db_session.query(InventoryVerification).filter_by(inventory_item_id=item.id).count()
        assert after == before + 1

    def test_verify_rejects_assigned_user_outside_department(self, client, db_session):
        dept = _dept(db_session, "va6")
        other_dept = _dept(db_session, "va6_other")
        registrar = _user(db_session, "Reg6")
        verifier = _user(db_session, "Ver6")
        _grant_verify(db_session, verifier, dept)
        outsider = _user(db_session, "Outsider6")
        _assign_membership(db_session, outsider, other_dept)
        item = _item(db_session, "VA6-ITEM", dept, registrar, status="ACTIVE")

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": outsider.id, "status": "ACTIVE"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 400, resp.text

        db_session.refresh(item)
        assert item.assigned_to_user_id is None

    def test_verify_assignment_is_atomic_on_later_failure(self, client, db_session):
        """Si algo falla DESPUÉS de aplicar la asignación (estado inválido), la
        asignación no debe quedar a medias — todo vive en el commit final."""
        dept = _dept(db_session, "va7")
        registrar = _user(db_session, "Reg7")
        verifier = _user(db_session, "Ver7")
        _grant_verify(db_session, verifier, dept)
        old_user = _user(db_session, "Old7")
        new_user = _user(db_session, "New7")
        _assign_membership(db_session, old_user, dept)
        _assign_membership(db_session, new_user, dept)
        item = _item(
            db_session, "VA7-ITEM", dept, registrar, status="ACTIVE",
            assigned_to_user_id=old_user.id, assigned_by_id=registrar.id,
        )

        resp = client.post(
            _verify_url(item.id),
            json={"assigned_to_user_id": new_user.id, "status": "NOT_A_REAL_STATUS"},
            headers=_jwt_cookie(verifier.id),
        )
        assert resp.status_code == 400, resp.text

        # Nada de lo intentado en esta request quedó persistido.
        db_session.rollback()
        fresh = db_session.get(InventoryItem, item.id)
        assert fresh.assigned_to_user_id == old_user.id

        events = _history_events(db_session, item.id, "ASSIGNED_TO_USER", "REASSIGNED")
        assert events == []

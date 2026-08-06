"""Maint debe anclar el departamento del ticket por PROCEDENCIA (qué puesto
otorga acceso a `maint`), no por "cualquier puesto vigente" (resolver agnóstico).

Bug de fondo (ver `itcj2/core/services/departments_service.py::app_departments`):
alguien con un puesto en un depto que NO otorga maint (p. ej. Cafetería) y otro
puesto en un depto que SÍ lo otorga podía crear/ver un ticket "de Cafetería"
porque el resolver agnóstico (`get_user_departments`/`get_primary_user_department`)
no mira qué puesto realmente ancla el acceso a la app.

Cubre los 3 puntos tocados por el fix (fix/org-scope-coherence):
  - `department_dashboard_service._resolve_user_departments` (usado por
    `list_tickets`, `can_user_view_ticket`, dashboards y ACL de sockets).
  - `GET /api/maint/v2/tickets/my-departments` (selector al crear ticket).
  - `ticket_service.create_ticket` (sella `requester_department_id`).

Modelo PROCEDENCIA con RESPALDO: si ALGÚN puesto vigente otorga maint (por rol
o permiso), solo cuentan esos deptos; si NINGUNO lo otorga (acceso directo al
usuario, sin ancla departamental), se respalda con TODOS sus deptos — igual que
hoy, para no dejar sin depto a quien entra a maint por asignación directa.
"""
import time
from datetime import date, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

import itcj2.models  # noqa: F401
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.services import department_dashboard_service as dds
from itcj2.apps.maint.services import ticket_service
from itcj2.config import get_settings
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.role_permission import RolePermission
from itcj2.core.models.user import User
from itcj2.core.models.user_app_role import UserAppRole
from itcj2.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm
from itcj2.database import get_db
from itcj2.main import create_app

TODAY = date.today()


# ─────────────────────────── infraestructura de test ───────────────────────────

@pytest.fixture()
def client(db_session):
    """TestClient con la app real, pero `get_db` apunta a la sesión transaccional
    de Postgres del test (mismo patrón que `test_ticket_guards_scope.py`)."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _jwt_cookie(user_id: int, role: str | None = "admin") -> dict:
    """Admin global: abre el guard de `require_perms` sin tener que sembrar
    permisos reales — lo que se prueba aquí es la RESOLUCIÓN de departamento
    (`uid = int(user["sub"])`), no el gate de autorización en sí."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "role": role, "cn": None, "name": "Test",
        "iat": now, "exp": now + 24 * 3600,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Cookie": f"itcj_token={token}"}


def _maint(db) -> App:
    app = db.query(App).filter_by(key="maint").first()
    assert app is not None, "maint app debe existir en la BD dev"
    return app


def _dept(db, code, parent_id=None) -> Department:
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last) -> User:
    u = User(first_name="A", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _category(db) -> MaintCategory:
    c = db.query(MaintCategory).filter_by(code="ads_cat").first()
    if not c:
        c = MaintCategory(code="ads_cat", name="ads", is_active=True)
        db.add(c); db.commit(); db.refresh(c)
    return c


def _position(db, code, dept, user, start, end=None, *, grants_maint=False, via="perm"):
    """Puesto en `dept` con asignación [start, end]. Si `grants_maint`, otorga
    acceso a la app maint (por rol o por permiso del puesto, según `via`)."""
    pos = Position(code=code, title=code, department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=start, end_date=end, is_active=True))
    if grants_maint:
        app = _maint(db)
        if via == "role":
            role = db.query(Role).filter_by(name="ads_role").first()
            if not role:
                role = Role(name="ads_role"); db.add(role); db.commit(); db.refresh(role)
            db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=role.id))
        else:
            perm = db.query(Permission).filter_by(app_id=app.id, code="maint.tickets.api.create").first()
            if not perm:
                perm = Permission(app_id=app.id, code="maint.tickets.api.create", name="create")
                db.add(perm); db.commit(); db.refresh(perm)
            db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()
    return pos


def _direct_maint_role(db, user) -> None:
    """Asignación DIRECTA al usuario (sin puesto): igual que las ~37 personas
    con acceso a maint sin ancla departamental."""
    app = _maint(db)
    role = db.query(Role).filter_by(name="ads_direct_role").first()
    if not role:
        role = Role(name="ads_direct_role"); db.add(role); db.commit(); db.refresh(role)
    db.add(UserAppRole(user_id=user.id, app_id=app.id, role_id=role.id))
    db.commit()


# ─────────────────────────── (a)/(c) create_ticket valida contra app_departments ───────────────────────────

class TestCreateTicketDepartmentValidation:

    def test_rejects_department_whose_position_does_not_grant_maint(self, db_session):
        """El depto de un puesto AJENO a maint (Cafetería) no puede sellarse en
        el ticket, aunque el usuario tenga otro puesto que sí otorga maint."""
        cafeteria = _dept(db_session, "ads_cafeteria")
        gestion = _dept(db_session, "ads_gestion")
        u = _user(db_session, "Mixed")
        _position(db_session, "ads_pos_cafe", cafeteria, u, TODAY - timedelta(days=500))
        _position(db_session, "ads_pos_gest", gestion, u, TODAY - timedelta(days=10),
                  grants_maint=True)

        with pytest.raises(Exception) as exc_info:
            ticket_service.create_ticket(
                db=db_session, requester_id=u.id, category_id=_category(db_session).id,
                title="T", description="D", department_id=cafeteria.id,
            )
        assert getattr(exc_info.value, "status_code", None) == 400

    def test_accepts_department_that_grants_maint(self, db_session):
        """El depto cuyo puesto SÍ otorga maint se sella correctamente,
        aunque el usuario tenga otro puesto ajeno más antiguo."""
        cafeteria = _dept(db_session, "ads_cafeteria2")
        gestion = _dept(db_session, "ads_gestion2")
        u = _user(db_session, "Mixed2")
        _position(db_session, "ads_pos_cafe2", cafeteria, u, TODAY - timedelta(days=500))
        _position(db_session, "ads_pos_gest2", gestion, u, TODAY - timedelta(days=10),
                  grants_maint=True)

        ticket = ticket_service.create_ticket(
            db=db_session, requester_id=u.id, category_id=_category(db_session).id,
            title="T", description="D", department_id=gestion.id,
        )
        assert ticket.requester_department_id == gestion.id

    def test_auto_resolves_single_granting_department_without_explicit_id(self, db_session):
        """Sin `department_id`, se resuelve automáticamente al ÚNICO depto que
        otorga maint — NO al más antiguo entre TODOS sus puestos."""
        cafeteria = _dept(db_session, "ads_cafeteria3")
        gestion = _dept(db_session, "ads_gestion3")
        u = _user(db_session, "Mixed3")
        # El puesto de Cafetería es el MÁS ANTIGUO — antes del fix hubiera ganado.
        _position(db_session, "ads_pos_cafe3", cafeteria, u, TODAY - timedelta(days=500))
        _position(db_session, "ads_pos_gest3", gestion, u, TODAY - timedelta(days=10),
                  grants_maint=True, via="role")

        ticket = ticket_service.create_ticket(
            db=db_session, requester_id=u.id, category_id=_category(db_session).id,
            title="T", description="D",
        )
        assert ticket.requester_department_id == gestion.id


# ─────────────────────────── (d) respaldo por acceso directo ───────────────────────────

class TestDirectAccessFallback:

    def test_direct_access_without_granting_position_keeps_todays_behavior(self, db_session):
        """Sin NINGÚN puesto que otorgue maint (acceso directo al usuario), el
        respaldo sigue siendo TODOS sus deptos — igual que hoy. Con un solo
        depto, se auto-resuelve igual que antes del fix."""
        unico = _dept(db_session, "ads_unico")
        u = _user(db_session, "DirectOnly")
        _position(db_session, "ads_pos_unico", unico, u, TODAY - timedelta(days=20))
        _direct_maint_role(db_session, u)

        ticket = ticket_service.create_ticket(
            db=db_session, requester_id=u.id, category_id=_category(db_session).id,
            title="T", description="D",
        )
        assert ticket.requester_department_id == unico.id

    def test_direct_access_with_multiple_departments_still_requires_explicit_id(self, db_session):
        """Respaldo con >1 depto: sigue exigiendo `department_id` explícito
        (comportamiento de hoy), y acepta cualquiera de sus deptos reales."""
        a = _dept(db_session, "ads_fb_a")
        b = _dept(db_session, "ads_fb_b")
        u = _user(db_session, "DirectMulti")
        _position(db_session, "ads_pos_fb_a", a, u, TODAY - timedelta(days=100))
        _position(db_session, "ads_pos_fb_b", b, u, TODAY - timedelta(days=50))
        _direct_maint_role(db_session, u)

        with pytest.raises(Exception) as exc_info:
            ticket_service.create_ticket(
                db=db_session, requester_id=u.id, category_id=_category(db_session).id,
                title="T", description="D",
            )
        assert getattr(exc_info.value, "status_code", None) == 400

        ticket = ticket_service.create_ticket(
            db=db_session, requester_id=u.id, category_id=_category(db_session).id,
            title="T", description="D", department_id=b.id,
        )
        assert ticket.requester_department_id == b.id


# ─────────────────────────── (e) puesto vencido no cuenta ───────────────────────────

class TestExpiredPositionDoesNotAnchor:

    def test_expired_granting_position_falls_back(self, db_session):
        """Un puesto VENCIDO que otorgaba maint deja de anclar: si era el único
        que otorgaba, se respalda con el resto de deptos vigentes del usuario."""
        vencido = _dept(db_session, "ads_exp_vencido")
        otro = _dept(db_session, "ads_exp_otro")
        u = _user(db_session, "Expired")
        _position(db_session, "ads_pos_exp", vencido, u, TODAY - timedelta(days=100),
                  end=TODAY - timedelta(days=1), grants_maint=True)
        _position(db_session, "ads_pos_exp_otro", otro, u, TODAY - timedelta(days=10))

        with pytest.raises(Exception) as exc_info:
            ticket_service.create_ticket(
                db=db_session, requester_id=u.id, category_id=_category(db_session).id,
                title="T", description="D", department_id=vencido.id,
            )
        assert getattr(exc_info.value, "status_code", None) == 400

        # El respaldo (otro) sí funciona.
        ticket = ticket_service.create_ticket(
            db=db_session, requester_id=u.id, category_id=_category(db_session).id,
            title="T", description="D",
        )
        assert ticket.requester_department_id == otro.id


# ─────────────────────────── (b) GET /my-departments ───────────────────────────

class TestMyDepartmentsEndpoint:

    def test_excludes_department_whose_position_does_not_grant_maint(self, client, db_session):
        cafeteria = _dept(db_session, "ads_ep_cafeteria")
        gestion = _dept(db_session, "ads_ep_gestion")
        u = _user(db_session, "EpMixed")
        _position(db_session, "ads_ep_pos_cafe", cafeteria, u, TODAY - timedelta(days=500))
        _position(db_session, "ads_ep_pos_gest", gestion, u, TODAY - timedelta(days=10),
                  grants_maint=True)

        resp = client.get("/api/maint/v2/tickets/my-departments", headers=_jwt_cookie(u.id))
        assert resp.status_code == 200
        codes = {d["code"] for d in resp.json()["data"]}
        assert codes == {"ads_ep_gestion"}

    def test_direct_access_falls_back_to_all_departments(self, client, db_session):
        """(d) también a nivel endpoint: sin ancla, se listan TODOS sus deptos."""
        a = _dept(db_session, "ads_ep_fb_a")
        b = _dept(db_session, "ads_ep_fb_b")
        u = _user(db_session, "EpDirect")
        _position(db_session, "ads_ep_pos_fb_a", a, u, TODAY - timedelta(days=100))
        _position(db_session, "ads_ep_pos_fb_b", b, u, TODAY - timedelta(days=50))
        _direct_maint_role(db_session, u)

        resp = client.get("/api/maint/v2/tickets/my-departments", headers=_jwt_cookie(u.id))
        assert resp.status_code == 200
        codes = {d["code"] for d in resp.json()["data"]}
        assert codes == {"ads_ep_fb_a", "ads_ep_fb_b"}

    def test_expired_position_is_excluded(self, client, db_session):
        vencido = _dept(db_session, "ads_ep_vencido")
        u = _user(db_session, "EpExpired")
        _position(db_session, "ads_ep_pos_exp", vencido, u, TODAY - timedelta(days=100),
                  end=TODAY - timedelta(days=1), grants_maint=True)

        resp = client.get("/api/maint/v2/tickets/my-departments", headers=_jwt_cookie(u.id))
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ─────────────────────────── list_tickets / can_user_view_ticket (mismo resolver) ───────────────────────────

class TestResolverSharedWithListAndDetail:

    def test_resolve_user_departments_only_counts_granting_department(self, db_session):
        """`_resolve_user_departments` (consumido por `list_tickets`,
        `can_user_view_ticket`, dashboards y ACL de sockets) debe usar el mismo
        criterio de procedencia."""
        cafeteria = _dept(db_session, "ads_rud_cafeteria")
        gestion = _dept(db_session, "ads_rud_gestion")
        u = _user(db_session, "RudMixed")
        _position(db_session, "ads_rud_pos_cafe", cafeteria, u, TODAY - timedelta(days=500))
        _position(db_session, "ads_rud_pos_gest", gestion, u, TODAY - timedelta(days=10),
                  grants_maint=True)

        depts = dds._resolve_user_departments(db_session, u.id)

        assert {d["id"] for d in depts} == {gestion.id}

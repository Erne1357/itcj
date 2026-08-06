"""Qué departamentos "cuentan" para una app concreta.

Los resolvers canónicos (`get_user_departments` / `get_primary_user_department`)
son agnósticos de la app: devuelven todos los departamentos donde hay un puesto
vigente. Con multi-puesto eso mezcla departamentos que no tienen nada que ver con
la app — alguien con un puesto en Cafetería y otro en Gestión podía terminar
operando helpdesk "como Cafetería", que es quien ganaba el desempate.

Modelo: PROCEDENCIA con RESPALDO.
  - Si algún puesto vigente otorga acceso a la app (rol o permiso), solo cuentan
    los departamentos de ESOS puestos.
  - Si ninguno lo otorga (el acceso viene de una asignación directa al usuario,
    que no tiene ancla departamental), se respalda con todos sus departamentos:
    de lo contrario esas personas se quedarían sin departamento y no podrían ni
    levantar un ticket.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.core.services.departments_service import (
    app_departments, primary_app_department,
)
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.models.position import (
    Position, UserPosition, PositionAppRole, PositionAppPerm,
)

TODAY = date.today()


def _dept(db, code):
    d = Department(code=code, name=code, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _user(db, last):
    u = User(first_name="A", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _role(db, name):
    r = db.query(Role).filter_by(name=name).first()
    if not r:
        r = Role(name=name); db.add(r); db.commit(); db.refresh(r)
    return r


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p); db.commit(); db.refresh(p)
    return p


def _position(db, code, dept, user, start, *, grants_app=None, via="role"):
    pos = Position(code=code, title=code, department_id=dept.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=start, is_active=True))
    if grants_app:
        app = db.query(App).filter_by(key=grants_app).first()
        if via == "role":
            db.add(PositionAppRole(position_id=pos.id, app_id=app.id,
                                   role_id=_role(db, "apd_role").id))
        else:
            db.add(PositionAppPerm(position_id=pos.id, app_id=app.id,
                                   perm_id=_perm(db, app, "apd.perm").id, allow=True))
    db.commit()
    return pos


def _codes(departments):
    return {d.code for d in departments}


def test_only_departments_whose_position_grants_the_app_count(db_session):
    """El departamento ajeno a la app desaparece, aunque su puesto sea más antiguo."""
    cafeteria = _dept(db_session, "apd_cafeteria")
    gestion = _dept(db_session, "apd_gestion")
    u = _user(db_session, "Mixed")

    _position(db_session, "apd_pos_cafe", cafeteria, u, TODAY - timedelta(days=500))
    _position(db_session, "apd_pos_gest", gestion, u, TODAY - timedelta(days=10),
              grants_app="helpdesk")

    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {"apd_gestion"}
    assert primary_app_department(db_session, u.id, "helpdesk").code == "apd_gestion"


def test_all_granting_departments_count(db_session):
    """Secretaria de dos departamentos, ambos con acceso: cuentan los dos."""
    a = _dept(db_session, "apd_a")
    b = _dept(db_session, "apd_b")
    u = _user(db_session, "Secretary")

    _position(db_session, "apd_pos_a", a, u, TODAY - timedelta(days=100), grants_app="helpdesk")
    _position(db_session, "apd_pos_b", b, u, TODAY - timedelta(days=50), grants_app="helpdesk")

    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {"apd_a", "apd_b"}
    # El primario sigue siendo determinista: el puesto más antiguo de los que otorgan.
    assert primary_app_department(db_session, u.id, "helpdesk").code == "apd_a"


def test_permission_granted_by_position_also_anchors(db_session):
    """El ancla vale igual si el puesto otorga un PERMISO en vez de un rol."""
    otro = _dept(db_session, "apd_otro")
    propio = _dept(db_session, "apd_propio")
    u = _user(db_session, "ByPerm")

    _position(db_session, "apd_pos_otro", otro, u, TODAY - timedelta(days=300))
    _position(db_session, "apd_pos_propio", propio, u, TODAY - timedelta(days=5),
              grants_app="helpdesk", via="perm")

    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {"apd_propio"}


def test_falls_back_when_no_position_grants_the_app(db_session):
    """Acceso directo al usuario: sin ancla, se respalda con sus departamentos.

    Son 47 personas hoy entre helpdesk y maint; sin respaldo se quedarían sin
    departamento y no podrían ni levantar un ticket.
    """
    a = _dept(db_session, "apd_fb_a")
    b = _dept(db_session, "apd_fb_b")
    u = _user(db_session, "DirectGrant")

    _position(db_session, "apd_pos_fb_a", a, u, TODAY - timedelta(days=100))
    _position(db_session, "apd_pos_fb_b", b, u, TODAY - timedelta(days=50))

    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {"apd_fb_a", "apd_fb_b"}
    assert primary_app_department(db_session, u.id, "helpdesk").code == "apd_fb_a"


def test_user_without_positions_has_no_department(db_session):
    u = _user(db_session, "NoPos")

    assert app_departments(db_session, u.id, "helpdesk") == []
    assert primary_app_department(db_session, u.id, "helpdesk") is None


def test_expired_granting_position_does_not_count(db_session):
    """Un puesto vencido no ancla — y si era el único que otorgaba, se respalda."""
    gestion = _dept(db_session, "apd_exp_gestion")
    otro = _dept(db_session, "apd_exp_otro")
    u = _user(db_session, "Expired")

    pos = _position(db_session, "apd_pos_exp", gestion, u, TODAY - timedelta(days=100),
                    grants_app="helpdesk")
    up = db_session.query(UserPosition).filter_by(position_id=pos.id, user_id=u.id).first()
    up.end_date = TODAY - timedelta(days=1)
    _position(db_session, "apd_pos_exp_otro", otro, u, TODAY - timedelta(days=10))
    db_session.commit()

    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {"apd_exp_otro"}


def test_other_app_grant_does_not_anchor(db_session):
    """Un puesto que otorga MAINT no ancla para HELPDESK."""
    solo_maint = _dept(db_session, "apd_only_maint")
    neutro = _dept(db_session, "apd_neutro")
    u = _user(db_session, "OtherApp")

    _position(db_session, "apd_pos_maint", solo_maint, u, TODAY - timedelta(days=100),
              grants_app="maint")
    _position(db_session, "apd_pos_neutro", neutro, u, TODAY - timedelta(days=10))

    # Para maint ancla; para helpdesk no hay ancla → respaldo con ambos.
    assert _codes(app_departments(db_session, u.id, "maint")) == {"apd_only_maint"}
    assert _codes(app_departments(db_session, u.id, "helpdesk")) == {
        "apd_only_maint", "apd_neutro"
    }

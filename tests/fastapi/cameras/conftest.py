"""Fixtures de cameras: llave Fernet y un mundo mínimo de roles/puestos/usuarios."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

PERMS = {
    "cameras.dvrs.page.list": ("admin", "tech_soporte", "department_head"),
    "cameras.dvrs.api.read.all": ("admin", "tech_soporte"),
    "cameras.dvrs.api.read.department": ("department_head",),
    "cameras.dvrs.api.manage": ("admin", "tech_soporte"),
    "cameras.credentials.api.update.department": ("department_head",),
    "cameras.audit.page.list": ("admin", "tech_soporte"),
}


@pytest.fixture
def cameras_key(monkeypatch):
    from cryptography.fernet import Fernet
    from itcj2.config import get_settings
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "CAMERAS_SECRET_KEY", key)
    return key


@pytest.fixture
def cam_world(db_session):
    from itcj2.core.models.app import App
    from itcj2.core.models.department import Department
    from itcj2.core.models.permission import Permission
    from itcj2.core.models.position import Position, PositionAppRole, UserPosition
    from itcj2.core.models.role import Role
    from itcj2.core.models.role_permission import RolePermission
    from itcj2.core.models.user import User
    from itcj2.core.models.user_app_role import UserAppRole

    db = db_session
    app = db.query(App).filter_by(key="cameras").first()
    if not app:
        app = App(key="cameras", name="Cámaras", is_active=True)
        db.add(app)
        db.flush()

    roles = {}
    for name in ("admin", "tech_soporte", "department_head"):
        r = db.query(Role).filter_by(name=name).first()
        if not r:
            r = Role(name=name)
            db.add(r)
            db.flush()
        roles[name] = r

    for code, role_names in PERMS.items():
        p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
        if not p:
            p = Permission(app_id=app.id, code=code, name=code)
            db.add(p)
            db.flush()
        for rn in role_names:
            if not db.query(RolePermission).filter_by(role_id=roles[rn].id, perm_id=p.id).first():
                db.add(RolePermission(role_id=roles[rn].id, perm_id=p.id))

    def dept(code, parent=None):
        d = Department(code=code, name=code, parent_id=parent, is_active=True)
        db.add(d)
        db.flush()
        return d

    dept_a = dept("cam_a")
    dept_b = dept("cam_b")
    dept_a1 = dept("cam_a1", parent=dept_a.id)

    def user(tag):
        u = User(first_name=tag, last_name="Cam", is_active=True)
        db.add(u)
        db.flush()
        return u

    def head_of(d, u):
        pos = Position(code=f"cam_head_{d.code}", title=f"Jefe {d.code}",
                       department_id=d.id, is_active=True, allows_multiple=True)
        db.add(pos)
        db.flush()
        db.add(PositionAppRole(position_id=pos.id, app_id=app.id, role_id=roles["department_head"].id))
        db.add(UserPosition(user_id=u.id, position_id=pos.id,
                            start_date=date.today() - timedelta(days=1), is_active=True))

    head_a, head_b, head_a1, tech, nobody = (user(t) for t in ("head_a", "head_b", "head_a1", "tech", "nobody"))
    head_of(dept_a, head_a)
    head_of(dept_b, head_b)
    head_of(dept_a1, head_a1)
    db.add(UserAppRole(user_id=tech.id, app_id=app.id, role_id=roles["tech_soporte"].id))
    db.commit()

    return SimpleNamespace(
        app_id=app.id, dept_a=dept_a.id, dept_b=dept_b.id, dept_a1=dept_a1.id,
        head_a=head_a.id, head_b=head_b.id, head_a1=head_a1.id,
        tech=tech.id, nobody=nobody.id,
    )

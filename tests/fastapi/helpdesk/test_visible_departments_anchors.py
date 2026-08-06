"""`visible_department_ids` debe poder anclarse en más de un permiso `.subtree`.

El scope de inventario se resolvía SOLO con `helpdesk.inventory.api.read.subtree`,
así que los módulos con su propio permiso —grupos, campañas, bajas, estadísticas,
exportación— no tenían forma de otorgar subárbol: darles su `.subtree` pasaba el
guard pero dejaba el scope vacío. La resolución es por PROCEDENCIA, o sea que cada
permiso aporta el subárbol de LOS PUESTOS QUE LO OTORGAN, no una unión global.
"""
from datetime import date, timedelta

import itcj2.models  # noqa: F401
from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids
from itcj2.core.models.app import App
from itcj2.core.models.department import Department
from itcj2.core.models.permission import Permission
from itcj2.core.models.user import User
from itcj2.core.models.position import Position, UserPosition, PositionAppPerm

ITEMS = "helpdesk.inventory.api.read.subtree"
GROUPS = "helpdesk.inventory_groups.api.read.subtree"


def _dept(db, code, parent_id=None):
    d = Department(code=code, name=code, parent_id=parent_id, is_active=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _perm(db, app, code):
    p = db.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not p:
        p = Permission(app_id=app.id, code=code, name=code)
        db.add(p); db.commit(); db.refresh(p)
    return p


def _anchor(db, user, department, perm_code, pos_code):
    """Puesto en `department` que otorga `perm_code`."""
    app = db.query(App).filter_by(key="helpdesk").first()
    perm = _perm(db, app, perm_code)
    pos = Position(code=pos_code, title=pos_code, department_id=department.id,
                   is_active=True, allows_multiple=True)
    db.add(pos); db.commit(); db.refresh(pos)
    db.add(UserPosition(user_id=user.id, position_id=pos.id,
                        start_date=date.today() - timedelta(days=1), is_active=True))
    db.add(PositionAppPerm(position_id=pos.id, app_id=app.id, perm_id=perm.id, allow=True))
    db.commit()


def _user(db, last):
    u = User(first_name="V", last_name=last, is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_groups_perm_alone_is_inert_for_the_default_anchor(db_session):
    """Solo con el permiso de GRUPOS, el scope de items sigue vacío."""
    root = _dept(db_session, "vda_root")
    _dept(db_session, "vda_leaf", root.id)
    u = _user(db_session, "OnlyGroups")
    _anchor(db_session, u, root, GROUPS, "vda_pos_groups")

    assert visible_department_ids(db_session, {"sub": str(u.id), "role": "x"}) == set()


def test_extra_anchor_grants_its_own_subtree(db_session):
    """Pidiendo explícitamente el ancla de grupos, sí resuelve su subárbol."""
    root = _dept(db_session, "vdb_root")
    leaf = _dept(db_session, "vdb_leaf", root.id)
    _dept(db_session, "vdb_other")
    u = _user(db_session, "Groups")
    _anchor(db_session, u, root, GROUPS, "vdb_pos_groups")

    visible = visible_department_ids(
        db_session, {"sub": str(u.id), "role": "x"}, extra_subtree_perms={GROUPS}
    )

    assert visible == {root.id, leaf.id}


def test_anchors_are_resolved_by_provenance_not_unioned(db_session):
    """Cada permiso aporta el subárbol de SU puesto, no el de todos.

    Puesto A otorga el de items, puesto B el de grupos. Pedir solo el de items
    debe dar la rama de A; pedir ambos, las dos ramas.
    """
    a_root = _dept(db_session, "vdc_a")
    a_leaf = _dept(db_session, "vdc_a_leaf", a_root.id)
    b_root = _dept(db_session, "vdc_b")
    u = _user(db_session, "Both")
    _anchor(db_session, u, a_root, ITEMS, "vdc_pos_items")
    _anchor(db_session, u, b_root, GROUPS, "vdc_pos_groups")

    user = {"sub": str(u.id), "role": "x"}

    assert visible_department_ids(db_session, user) == {a_root.id, a_leaf.id}
    assert visible_department_ids(db_session, user, extra_subtree_perms={GROUPS}) == {
        a_root.id, a_leaf.id, b_root.id
    }


def test_default_behaviour_unchanged(db_session):
    """Sin `extra_subtree_perms`, el resultado es exactamente el de antes."""
    root = _dept(db_session, "vdd_root")
    leaf = _dept(db_session, "vdd_leaf", root.id)
    u = _user(db_session, "Items")
    _anchor(db_session, u, root, ITEMS, "vdd_pos_items")

    assert visible_department_ids(db_session, {"sub": str(u.id), "role": "x"}) == {root.id, leaf.id}

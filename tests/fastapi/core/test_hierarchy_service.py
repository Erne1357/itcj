"""Tests del hierarchy_service: descendientes/ancestros recursivos + cycle-safe."""
from itcj2.core.services import hierarchy_service as hs
from itcj2.core.models.department import Department


def _mk(db, code, parent=None, active=True):
    d = Department(code=code, name=code, parent_id=parent, is_active=active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_descendants_include_self(db_session):
    root = _mk(db_session, "hs_root")
    sub = _mk(db_session, "hs_sub", parent=root.id)
    dep = _mk(db_session, "hs_dep", parent=sub.id)
    ids = hs.descendant_department_ids(db_session, root.id)
    assert ids == {root.id, sub.id, dep.id}


def test_descendants_exclude_self(db_session):
    root = _mk(db_session, "hs_root2")
    sub = _mk(db_session, "hs_sub2", parent=root.id)
    assert hs.descendant_department_ids(db_session, root.id, include_self=False) == {sub.id}


def test_descendants_skip_inactive(db_session):
    root = _mk(db_session, "hs_root3")
    _mk(db_session, "hs_inactivo", parent=root.id, active=False)
    assert hs.descendant_department_ids(db_session, root.id) == {root.id}


def test_descendants_cycle_safe(db_session):
    # El CHECK de BD ya impide self-parent; probamos un ciclo de 2 nodos (A->B->A)
    # armado directo por ORM (evitando la validación del service). El depth-cap del
    # CTE debe evitar el loop infinito y devolver un set acotado.
    a = _mk(db_session, "hs_cyc_a")
    b = _mk(db_session, "hs_cyc_b", parent=a.id)
    a.parent_id = b.id  # cierra el ciclo (permitido por el CHECK: b != a)
    db_session.commit()
    ids = hs.descendant_department_ids(db_session, a.id)  # no debe colgarse
    assert a.id in ids and b.id in ids


def test_leaf_returns_self(db_session):
    leaf = _mk(db_session, "hs_leaf")
    assert hs.descendant_department_ids(db_session, leaf.id) == {leaf.id}


def test_ancestors(db_session):
    root = _mk(db_session, "hs_r4")
    sub = _mk(db_session, "hs_s4", parent=root.id)
    dep = _mk(db_session, "hs_d4", parent=sub.id)
    assert hs.ancestor_department_ids(db_session, dep.id) == {root.id, sub.id}
    assert hs.ancestor_department_ids(db_session, dep.id, include_self=True) == {root.id, sub.id, dep.id}


def test_descendants_map(db_session):
    root = _mk(db_session, "hs_m_root")
    sub = _mk(db_session, "hs_m_sub", parent=root.id)
    dep = _mk(db_session, "hs_m_dep", parent=sub.id)
    m = hs.department_descendants_map(db_session)
    assert m[root.id] >= {root.id, sub.id, dep.id}
    assert m[sub.id] >= {sub.id, dep.id}
    assert m[dep.id] == {dep.id} or dep.id in m[dep.id]

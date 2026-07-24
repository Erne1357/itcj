"""Task 1.2: el árbol de departamentos recurre a profundidad arbitraria."""
from itcj2.core.models.department import Department


def _mk(db, code, parent=None, active=True):
    d = Department(code=code, name=code, parent_id=parent, is_active=active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_level4_children_expand(db_session):
    root = _mk(db_session, "dd_root")
    sub = _mk(db_session, "dd_sub", parent=root.id)
    dep = _mk(db_session, "dd_dep", parent=sub.id)
    subdep = _mk(db_session, "dd_subdep", parent=dep.id)
    # dep está en nivel 3 (0-indexed): hoy is_direction/is_subdirection son False
    # y to_dict truncaba sus hijos. Debe incluir subdep.
    data = dep.to_dict(include_children=True)
    codes = [c["code"] for c in data.get("children", [])]
    assert "dd_subdep" in codes
    assert dep.get_children_count() == 1


def test_depth_helper(db_session):
    root = _mk(db_session, "dp_root")
    sub = _mk(db_session, "dp_sub", parent=root.id)
    dep = _mk(db_session, "dp_dep", parent=sub.id)
    assert root.depth() == 0
    assert sub.depth() == 1
    assert dep.depth() == 2

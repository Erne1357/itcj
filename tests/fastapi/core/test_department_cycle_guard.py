"""Task 1.3: update_department rechaza ciclos en parent_id."""
import pytest

from itcj2.core.services import departments_service as ds


def _mk(db, code, parent=None):
    return ds.create_department(db, code=code, name=code, parent_id=parent)


def test_self_parent_rejected(db_session):
    d = _mk(db_session, "cg_self")
    with pytest.raises(ValueError):
        ds.update_department(db_session, d.id, parent_id=d.id)


def test_descendant_as_parent_rejected(db_session):
    root = _mk(db_session, "cg_root")
    sub = _mk(db_session, "cg_sub", parent=root.id)
    dep = _mk(db_session, "cg_dep", parent=sub.id)
    # root no puede tener como parent a su descendiente dep (crearía ciclo)
    with pytest.raises(ValueError):
        ds.update_department(db_session, root.id, parent_id=dep.id)


def test_valid_reparent_ok(db_session):
    root = _mk(db_session, "cg_r2")
    a = _mk(db_session, "cg_a2", parent=root.id)
    b = _mk(db_session, "cg_b2", parent=root.id)
    # mover a bajo b (ambos hijos de root, sin ciclo) es válido
    updated = ds.update_department(db_session, a.id, parent_id=b.id)
    assert updated.parent_id == b.id

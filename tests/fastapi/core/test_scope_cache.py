"""Task 3.3: cache del mapa de descendientes + invalidación en mutaciones de dept."""
from itcj2.core.services import authz_cache as ac
from itcj2.core.services import departments_service as ds
from itcj2.core.models.department import Department


def _mk(db, code, parent=None):
    return ds.create_department(db, code=code, name=code, parent_id=parent)


def test_cached_descendants_map_matches(db_session):
    root = _mk(db_session, "scch_root")
    sub = _mk(db_session, "scch_sub", parent=root.id)
    m = ac.cached_descendants_map(db_session)
    assert set(m[root.id]) >= {root.id, sub.id}


def test_invalidation_after_new_dept(db_session):
    root = _mk(db_session, "scch_r2")
    m1 = ac.cached_descendants_map(db_session)
    assert root.id in m1
    # nuevo hijo + invalidación → el mapa recomputado lo incluye
    child = _mk(db_session, "scch_c2", parent=root.id)
    ac.invalidate_dept_map()
    m2 = ac.cached_descendants_map(db_session)
    assert child.id in set(m2[root.id])


def test_subtree_scope_uses_cache_consistent(db_session):
    # subtree_scope_for debe dar el mismo resultado apoyado en el cache
    from itcj2.core.services import hierarchy_service as hs
    root = _mk(db_session, "scch_r3")
    sub = _mk(db_session, "scch_s3", parent=root.id)
    ac.invalidate_dept_map()
    direct = hs.descendant_department_ids(db_session, root.id)
    cached = set(ac.cached_descendants_map(db_session)[root.id])
    assert cached == direct

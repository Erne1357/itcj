"""list_parent_options sin cap: árbol completo aplanado + exclude_subtree_of."""
from itcj2.core.api import departments as departments_api
from itcj2.core.models.department import Department
from itcj2.core.services import departments_service as ds


def _mk(db, code, parent=None, active=True):
    d = Department(code=code, name=code, parent_id=parent, is_active=active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _ids(options):
    return {o["id"] for o in options}


def test_uncapped_includes_deep_departments(db_session):
    r = _mk(db_session, "po_root")
    l1 = _mk(db_session, "po_l1", parent=r.id)
    l2 = _mk(db_session, "po_l2", parent=l1.id)
    l3 = _mk(db_session, "po_l3", parent=l2.id)
    opts = ds.list_parent_options(db_session)
    # el cap viejo ([direction]+subdirections) jamás incluiría estos nodos
    assert {r.id, l1.id, l2.id, l3.id} <= _ids(opts)


def test_depth_and_preorder(db_session):
    r = _mk(db_session, "po_d_root")
    l1 = _mk(db_session, "po_d_l1", parent=r.id)
    l2 = _mk(db_session, "po_d_l2", parent=l1.id)
    opts = ds.list_parent_options(db_session)
    by_id = {o["id"]: o for o in opts}
    assert by_id[r.id]["depth"] == 0
    assert by_id[l1.id]["depth"] == 1
    assert by_id[l2.id]["depth"] == 2
    idx = [o["id"] for o in opts]
    assert idx.index(r.id) < idx.index(l1.id) < idx.index(l2.id)  # preorden DFS


def test_exclude_subtree_of(db_session):
    r = _mk(db_session, "po_x_root")
    l1 = _mk(db_session, "po_x_l1", parent=r.id)
    l2 = _mk(db_session, "po_x_l2", parent=l1.id)
    sibling = _mk(db_session, "po_x_sib", parent=r.id)
    opts = ds.list_parent_options(db_session, exclude_subtree_of=l1.id)
    ids = _ids(opts)
    assert l1.id not in ids and l2.id not in ids  # self + descendientes fuera
    assert r.id in ids and sibling.id in ids


def test_legacy_keys_preserved(db_session):
    # departments.js:83-108 lee id/name/parent_id — no romper el JS viejo (F5 lo reescribe)
    _mk(db_session, "po_k_root")
    o = next(x for x in ds.list_parent_options(db_session) if x["code"] == "po_k_root")
    for key in ("id", "name", "code", "parent_id", "depth", "is_official"):
        assert key in o


def test_endpoint_param_and_legacy_envelope(db_session):
    r = _mk(db_session, "po_e_root")
    l1 = _mk(db_session, "po_e_l1", parent=r.id)
    resp = departments_api.list_parent_options(exclude_subtree_of=l1.id,
                                               user={"sub": "1"}, db=db_session)
    assert resp["status"] == "ok"  # envelope legacy hasta el flip de F5
    assert l1.id not in {o["id"] for o in resp["data"]}

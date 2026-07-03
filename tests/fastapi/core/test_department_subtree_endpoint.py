"""GET /departments/{id}/subtree (C3) + hierarchy_service.subtree_nodes."""
import pytest
from fastapi import HTTPException

from itcj2.core.api import departments as departments_api
from itcj2.core.models.department import Department
from itcj2.core.services import hierarchy_service as hs


def _mk(db, code, parent=None, active=True):
    d = Department(code=code, name=code, parent_id=parent, is_active=active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_subtree_nodes_dfs_relative_depth(db_session):
    r = _mk(db_session, "st_r")
    a = _mk(db_session, "st_a", parent=r.id)
    b = _mk(db_session, "st_b", parent=a.id)
    c = _mk(db_session, "st_c", parent=b.id)  # árbol de 4 niveles
    nodes = hs.subtree_nodes(db_session, a.id)  # subtree pedido desde nivel 1
    assert [n["id"] for n in nodes] == [a.id, b.id, c.id]  # orden DFS
    assert [n["depth"] for n in nodes] == [0, 1, 2]        # RELATIVA al root pedido


def test_subtree_nodes_skips_inactive(db_session):
    r = _mk(db_session, "st_r2")
    _mk(db_session, "st_off", parent=r.id, active=False)
    assert [n["id"] for n in hs.subtree_nodes(db_session, r.id)] == [r.id]


def test_subtree_nodes_missing_root_empty(db_session):
    assert hs.subtree_nodes(db_session, 99999999) == []


def test_subtree_endpoint_contract(db_session):
    r = _mk(db_session, "st_r3")
    s = _mk(db_session, "st_s3", parent=r.id)
    resp = departments_api.get_department_subtree(dept_id=r.id,
                                                  user={"sub": "1"}, db=db_session)
    assert resp["success"] is True
    assert resp["data"]["department_ids"] == sorted([r.id, s.id])
    assert resp["data"]["departments"][0] == {"id": r.id, "name": "st_r3", "depth": 0}


def test_subtree_endpoint_404_detail_string(db_session):
    with pytest.raises(HTTPException) as exc:
        departments_api.get_department_subtree(dept_id=99999999,
                                               user={"sub": "1"}, db=db_session)
    assert exc.value.status_code == 404
    assert isinstance(exc.value.detail, str)  # D6: detail string, no dict

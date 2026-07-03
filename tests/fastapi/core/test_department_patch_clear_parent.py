"""PATCH /departments/{id}: null explícito limpia parent (F1b-D2, exclude_unset)."""
import pytest
from fastapi import HTTPException

from itcj2.core.api import departments as departments_api
from itcj2.core.api.departments import DepartmentUpdateBody
from itcj2.core.models.department import Department


def _mk(db, code, parent=None):
    d = Department(code=code, name=code, parent_id=parent, is_active=True)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_explicit_null_clears_parent(db_session):
    r = _mk(db_session, "pc_root")
    child = _mk(db_session, "pc_child", parent=r.id)
    body = DepartmentUpdateBody(parent_id=None)  # null EXPLÍCITO → en fields_set
    resp = departments_api.update_department(dept_id=child.id, body=body,
                                             user={"sub": "1"}, db=db_session)
    assert resp["data"]["parent_id"] is None
    db_session.refresh(child)
    assert child.parent_id is None  # promovido a raíz


def test_absent_parent_id_untouched(db_session):
    r = _mk(db_session, "pc_root2")
    child = _mk(db_session, "pc_child2", parent=r.id)
    body = DepartmentUpdateBody(name="renamed child")  # parent_id AUSENTE
    departments_api.update_department(dept_id=child.id, body=body,
                                      user={"sub": "1"}, db=db_session)
    db_session.refresh(child)
    assert child.parent_id == r.id
    assert child.name == "renamed child"


def test_explicit_null_name_ignored(db_session):
    d = _mk(db_session, "pc_name")
    body = DepartmentUpdateBody(name=None)  # null explícito en campo NO anulable
    departments_api.update_department(dept_id=d.id, body=body,
                                      user={"sub": "1"}, db=db_session)
    db_session.refresh(d)
    assert d.name == "pc_name"  # ignorado; sin violación NOT NULL


def test_reparent_cycle_still_guarded(db_session):
    r = _mk(db_session, "pc_cyc_r")
    child = _mk(db_session, "pc_cyc_c", parent=r.id)
    body = DepartmentUpdateBody(parent_id=child.id)  # r bajo su propio hijo
    with pytest.raises(HTTPException):
        departments_api.update_department(dept_id=r.id, body=body,
                                          user={"sub": "1"}, db=db_session)

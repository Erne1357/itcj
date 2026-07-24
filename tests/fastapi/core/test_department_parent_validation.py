"""Validación de parent (existe + activo) en create/update (spec §3.2)."""
import pytest

from itcj2.core.models.department import Department
from itcj2.core.services import departments_service as ds


def _mk(db, code, parent=None, active=True):
    d = Department(code=code, name=code, parent_id=parent, is_active=active)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_create_rejects_missing_parent(db_session):
    with pytest.raises(ValueError):
        ds.create_department(db_session, code="pv_orphan", name="x", parent_id=99999999)


def test_create_rejects_inactive_parent(db_session):
    dead = _mk(db_session, "pv_dead", active=False)
    with pytest.raises(ValueError):
        ds.create_department(db_session, code="pv_child", name="x", parent_id=dead.id)


def test_create_valid_parent_ok(db_session):
    p = _mk(db_session, "pv_ok_parent")
    d = ds.create_department(db_session, code="pv_ok_child", name="x", parent_id=p.id)
    assert d.parent_id == p.id


def test_update_rejects_missing_parent(db_session):
    d = _mk(db_session, "pv_up")
    with pytest.raises(ValueError):
        ds.update_department(db_session, d.id, parent_id=99999999)


def test_update_rejects_inactive_parent(db_session):
    d = _mk(db_session, "pv_up2")
    dead = _mk(db_session, "pv_up2_dead", active=False)
    with pytest.raises(ValueError):
        ds.update_department(db_session, d.id, parent_id=dead.id)

"""Modelos de cameras: llave, tablas, cascada e inmutabilidad de la bitácora."""
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_settings_rejects_bad_key():
    from itcj2.config import Settings
    with pytest.raises(ValidationError) as exc:
        Settings(CAMERAS_SECRET_KEY="nope")
    assert "nope" not in str(exc.value)


def test_tables_exist(db_session):
    rows = db_session.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'cameras_%'")).scalars().all()
    assert {"cameras_dvrs", "cameras_dvr_departments", "cameras_audit_log"} <= set(rows)


def test_dvr_departments_cascade(db_session, cam_world):
    from itcj2.apps.cameras.models import Dvr
    dvr = Dvr(name="DVR 1", created_by_id=cam_world.tech)
    db_session.add(dvr)
    db_session.flush()
    db_session.execute(text(
        "INSERT INTO cameras_dvr_departments (dvr_id, department_id) VALUES (:d, :a), (:d, :b)"),
        {"d": dvr.id, "a": cam_world.dept_a, "b": cam_world.dept_b})
    db_session.refresh(dvr)
    assert {d.id for d in dvr.departments} == {cam_world.dept_a, cam_world.dept_b}
    db_session.execute(text("DELETE FROM cameras_dvrs WHERE id = :d"), {"d": dvr.id})
    n = db_session.execute(text(
        "SELECT count(*) FROM cameras_dvr_departments WHERE dvr_id = :d"), {"d": dvr.id}).scalar()
    assert n == 0


def test_audit_log_is_immutable(db_session):
    from itcj2.apps.cameras.models import CamerasAuditLog
    row = CamerasAuditLog(dvr_id=1, dvr_name="x", actor_id=1, action="create")
    db_session.add(row)
    db_session.flush()
    with pytest.raises(DBAPIError, match="inmutable"):
        db_session.execute(text("UPDATE cameras_audit_log SET action = 'x' WHERE id = :i"), {"i": row.id})


def test_cam_world_scope(db_session, cam_world):
    from itcj2.core.services.scope_service import granting_departments
    perm = "cameras.dvrs.api.read.department"
    assert granting_departments(db_session, cam_world.head_a, "cameras", perm) == {cam_world.dept_a}
    assert granting_departments(db_session, cam_world.head_a1, "cameras", perm) == {cam_world.dept_a1}
    assert granting_departments(db_session, cam_world.tech, "cameras", perm) == set()

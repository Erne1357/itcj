"""Flag is_official: oficial (organigrama) vs sub-departamento creado por admin."""
from itcj2.core.services import departments_service as ds
from itcj2.core.models.department import Department


def test_existing_seed_is_official(db_session):
    # Los departamentos sembrados quedaron is_official=TRUE por la migración.
    direction = db_session.query(Department).filter_by(code="direction").first()
    if direction is not None:  # depende del seed de la BD dev
        assert direction.is_official is True


def test_create_defaults_to_not_official(db_session):
    d = ds.create_department(db_session, code="off_sub1", name="sub mia")
    assert d.is_official is False           # lo creado por la UI = tuyo
    assert d.to_dict()["is_official"] is False


def test_create_can_mark_official(db_session):
    d = ds.create_department(db_session, code="off_oficial1", name="oficial", is_official=True)
    assert d.is_official is True


def test_update_can_promote(db_session):
    d = ds.create_department(db_session, code="off_sub2", name="sub")
    assert d.is_official is False
    ds.update_department(db_session, d.id, is_official=True)
    db_session.refresh(d)
    assert d.is_official is True

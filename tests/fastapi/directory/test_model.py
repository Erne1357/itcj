from itcj2.apps.directory.models import DirectoryEntry


def test_tablename():
    assert DirectoryEntry.__tablename__ == "directory_entries"


def test_required_and_optional_columns():
    cols = DirectoryEntry.__table__.columns
    assert cols["department_id"].nullable is False
    assert cols["extension"].nullable is False
    assert cols["label"].nullable is False
    assert cols["position_id"].nullable is True
    assert cols["holder_name"].nullable is True
    assert cols["notes"].nullable is True
    assert cols["is_active"].nullable is False

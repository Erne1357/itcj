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


def test_entry_has_email_column():
    from itcj2.apps.directory.models import DirectoryEntry
    col = DirectoryEntry.__table__.c.email
    assert col.nullable is True
    assert col.type.length == 150


def test_settings_table_shape():
    from itcj2.apps.directory.models import DirectorySettings
    t = DirectorySettings.__table__
    assert t.name == "directory_settings"
    flag = t.c.show_unofficial_departments
    assert flag.nullable is False
    assert flag.server_default is not None
    assert t.c.id.autoincrement is False
    assert any("singleton" in (c.name or "") for c in t.constraints if c.name)

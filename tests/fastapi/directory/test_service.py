from unittest.mock import MagicMock

import pytest

from itcj2.apps.directory.services import directory_service as svc


class _Dept:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def test_group_by_department_orders_by_hierarchy_and_head_first():
    rows = [
        {"department_id": 2, "department": "Sistemas", "title": "A", "holder": "", "extension": "2002", "notes": "", "source": "position", "position_id": 1, "entry_id": None, "is_head": False},
        {"department_id": 1, "department": "Dirección", "title": "B", "holder": "", "extension": "2001", "notes": "", "source": "entry", "position_id": None, "entry_id": 5, "is_head": False},
        {"department_id": 2, "department": "Sistemas", "title": "C (jefe)", "holder": "", "extension": "2000", "notes": "", "source": "position", "position_id": 2, "entry_id": None, "is_head": True},
    ]
    # dept_order fija jerarquía: Sistemas (0) antes que Dirección (1), sin importar nombre/id
    dept_order = {2: 0, 1: 1}
    groups = svc.group_by_department(rows, dept_order)
    assert [g["department"] for g in groups] == ["Sistemas", "Dirección"]
    # dentro de Sistemas: el jefe primero aunque su extensión ordene después
    assert [r["title"] for r in groups[0]["rows"]] == ["C (jefe)", "A"]


def test_group_by_department_drops_rows_outside_official_order():
    rows = [
        {"department_id": 1, "department": "Dirección", "title": "A", "holder": "", "extension": "2001", "notes": "", "source": "entry", "position_id": None, "entry_id": 5, "is_head": False},
        {"department_id": 9, "department": "No oficial", "title": "B", "holder": "", "extension": "2002", "notes": "", "source": "entry", "position_id": None, "entry_id": 6, "is_head": False},
    ]
    groups = svc.group_by_department(rows, {1: 0})
    assert [g["department"] for g in groups] == ["Dirección"]


def test_set_position_extension_writes_and_commits():
    pos = MagicMock()
    pos.phone_extension = None
    pos.phone_notes = None
    db = MagicMock()
    db.get.return_value = pos
    out = svc.set_position_extension(db, 7, " 2099 ", " piso 2 ", 200)
    assert pos.phone_extension == "2099"
    assert pos.phone_notes == "piso 2"
    db.commit.assert_called_once()
    assert out is pos


def test_set_position_extension_missing_raises():
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(ValueError):
        svc.set_position_extension(db, 99, "2000", None, 200)


def test_create_entry_validates_department():
    db = MagicMock()
    db.get.return_value = None  # depto no existe
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="Recepción", extension="2000", by_user_id=200)


def test_create_entry_adds_and_commits():
    db = MagicMock()
    db.get.return_value = _Dept(1, "Dirección")
    svc.create_entry(db, department_id=1, label=" Recepción ", extension=" 2000 ", holder_name=" Ana ", notes=" x ", by_user_id=200)
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_delete_entry_missing_raises():
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(ValueError):
        svc.delete_entry(db, 123)

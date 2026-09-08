from unittest.mock import MagicMock

import pytest

from itcj2.apps.directory.services import directory_service as svc


class _Dept:
    def __init__(self, id, name, *, is_active=True, code=None):
        self.id = id
        self.name = name
        self.is_active = is_active
        self.code = code


class _Pos:
    def __init__(self, code, title, dept=None):
        self.code = code
        self.title = title
        self.department = dept


def _meta(id, name, *, official=True, depth=0, ancestors=None):
    return {"id": id, "name": name, "is_official": official,
            "depth": depth, "ancestors": ancestors or []}


# ── agrupación y orden ───────────────────────────────────────────────────────
def test_group_by_department_orders_by_hierarchy_and_head_first():
    rows = [
        {"department_id": 2, "department": "Sistemas", "title": "A", "holder": "", "extension": "2002", "notes": "", "source": "position", "position_id": 1, "entry_id": None, "rank": "other"},
        {"department_id": 1, "department": "Dirección", "title": "B", "holder": "", "extension": "2001", "notes": "", "source": "entry", "position_id": None, "entry_id": 5, "rank": "other"},
        {"department_id": 2, "department": "Sistemas", "title": "C (jefe)", "holder": "", "extension": "2000", "notes": "", "source": "position", "position_id": 2, "entry_id": None, "rank": "head"},
    ]
    # El esqueleto fija la jerarquía: Sistemas antes que Dirección, sin importar nombre/id
    meta = [_meta(2, "Sistemas"), _meta(1, "Dirección")]
    groups = svc.group_by_department(rows, meta)
    assert [g["department"] for g in groups] == ["Sistemas", "Dirección"]
    # dentro de Sistemas: el jefe primero aunque su extensión ordene después
    assert [r["title"] for r in groups[0]["rows"]] == ["C (jefe)", "A"]


def test_group_by_department_drops_rows_outside_skeleton():
    rows = [
        {"department_id": 1, "department": "Dirección", "title": "A", "holder": "", "extension": "2001", "notes": "", "source": "entry", "position_id": None, "entry_id": 5, "rank": "other"},
        {"department_id": 9, "department": "No oficial", "title": "B", "holder": "", "extension": "2002", "notes": "", "source": "entry", "position_id": None, "entry_id": 6, "rank": "other"},
    ]
    groups = svc.group_by_department(rows, [_meta(1, "Dirección")])
    assert [g["department"] for g in groups] == ["Dirección"]


def test_group_orders_head_then_secretary_then_other_with_entries():
    rows = [
        {"department_id": 1, "department": "D", "title": "Z", "extension": "2009", "rank": "other", "source": "entry"},
        {"department_id": 1, "department": "D", "title": "S", "extension": "2001", "rank": "secretary", "source": "position"},
        {"department_id": 1, "department": "D", "title": "H", "extension": "2005", "rank": "head", "source": "position"},
        {"department_id": 1, "department": "D", "title": "E", "extension": "2000", "source": "entry"},  # sin rank
    ]
    groups = svc.group_by_department(rows, [_meta(1, "D")])
    assert [r["title"] for r in groups[0]["rows"]] == ["H", "S", "E", "Z"]


def test_empty_unofficial_group_emitted_only_when_asked():
    meta = [
        _meta(1, "Oficial"),
        _meta(2, "No oficial", official=False, depth=1, ancestors=[{"id": 1, "name": "Oficial"}]),
    ]
    rows = [{"department_id": 1, "department": "Oficial", "title": "A",
             "extension": "2000", "source": "entry", "rank": "other"}]
    assert [g["department"] for g in svc.group_by_department(rows, meta)] == ["Oficial"]
    assert [g["department"] for g in svc.group_by_department(
        rows, meta, include_empty_unofficial=True)] == ["Oficial", "No oficial"]


def test_empty_official_group_never_emitted():
    assert svc.group_by_department([], [_meta(7, "Oficial vacío")],
                                   include_empty_unofficial=True) == []


# ── short_title ──────────────────────────────────────────────────────────────
# TRAMPA DEL REPO: core_departments.name guarda el nombre CORTO
# («Sistemas y Computación»); el largo con «Departamento de …» vive en la columna
# `description` y short_title NUNCA lo ve, porque el call site pasa
# position.department.name. Ver database/DML/core/init/01_insert_departments.sql.
@pytest.mark.parametrize("title,dept,expected", [
    ("Secretaria del Depto. de Sistemas y Computación", "Sistemas y Computación", "Secretaria"),
    ("Jefe del Depto. de Ciencias Básicas", "Ciencias Básicas", "Jefe"),
    ("Jefe de la División de Estudios Profesionales", "División de Estudios Profesionales", "Jefe"),
    # La cola NO casa (secretary_info_resources): se conserva el título completo
    ("Secretaria del Depto. de Centro de Información", "Recursos de Información",
     "Secretaria del Depto. de Centro de Información"),
    # El resto quedaría demasiado corto: título completo
    ("Depto. de Planeación", "Planeación", "Depto. de Planeación"),
    # Acentos y mayúsculas se preservan del original
    ("Coordinadora de Lenguas Extranjeras", "Lenguas Extranjeras", "Coordinadora"),
    # Regresión: si alguien captura `name` con el prefijo largo, NO debe recortar
    ("Jefe del Depto. de Ciencias Básicas", "Departamento de Ciencias Básicas",
     "Jefe del Depto. de Ciencias Básicas"),
    # Prefijo largo real (los puestos aux_*)
    ("Auxiliar Administrativo del Depto. de Servicios Escolares", "Servicios Escolares",
     "Auxiliar Administrativo"),
    ("Secretaria de Subdirección Académica", "Subdirección Académica", "Secretaria"),
    # head_union_delegation: el título no tiene nada que ver con el depto
    ("Secretario General", "Delegación Sindical", "Secretario General"),
])
def test_short_title(title, dept, expected):
    assert svc.short_title(title, dept) == expected


# ── rank ─────────────────────────────────────────────────────────────────────
def test_rank_head_wins_over_title():
    """head_union_delegation se titula «Secretario General»."""
    dept = _Dept(1, "Delegación Sindical", code="union_delegation")
    assert svc._position_rank(_Pos("head_union_delegation", "Secretario General", dept)) == "head"


def test_rank_secretary_by_code_prefix():
    dept = _Dept(1, "Dirección", code="direction")
    assert svc._position_rank(
        _Pos("secretary_direction_1", "Secretaria de Dirección", dept)) == "secretary"


def test_rank_other():
    dept = _Dept(1, "Servicios Escolares", code="school_services")
    assert svc._position_rank(_Pos("aux_school_services", "Auxiliar", dept)) == "other"


# ── escritura ────────────────────────────────────────────────────────────────
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


def test_extension_too_long_raises():
    db = MagicMock()
    db.get.return_value = MagicMock()
    with pytest.raises(ValueError):
        svc.set_position_contact(db, 7, extension="12345678901", notes=None, email=None)


def test_create_entry_validates_department():
    db = MagicMock()
    db.get.return_value = None  # depto no existe
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="Recepción", extension="2000", by_user_id=200)


def test_create_entry_rejects_inactive_department():
    db = MagicMock()
    db.get.return_value = _Dept(1, "Inactivo", is_active=False)
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="X", extension="2000", by_user_id=200)


def test_create_entry_adds_and_commits():
    db = MagicMock()
    db.get.return_value = _Dept(1, "Dirección")
    svc.create_entry(db, department_id=1, label=" Recepción ", extension=" 2000 ",
                     holder_name=" Ana ", notes=" x ", by_user_id=200)
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_entry_field_length_guards():
    db = MagicMock()
    db.get.return_value = _Dept(1, "Dirección")
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="x" * 121, extension="2000", by_user_id=1)
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="ok", extension="12345678901", by_user_id=1)


def test_entry_email_format_validated():
    db = MagicMock()
    db.get.return_value = _Dept(1, "Dirección")
    with pytest.raises(ValueError):
        svc.create_entry(db, department_id=1, label="ok", extension="2000",
                         email="no-es-correo", by_user_id=1)


def test_delete_entry_missing_raises():
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(ValueError):
        svc.delete_entry(db, 123)

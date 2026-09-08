"""Validación y unicidad del correo de puesto (core).

Antes de esto `update_position` metía `email` en allowed_fields y no validaba
nada: un duplicado desde /itcj/config reventaba con IntegrityError -> 500.
"""
import pytest

from itcj2.core.models.position import Position
from itcj2.core.services import positions_service as svc
from itcj2.core.utils.email_tools import is_valid_email, normalize_email


@pytest.mark.parametrize("raw,expected", [
    ("  jefatura@cdjuarez.tecnm.mx ", "jefatura@cdjuarez.tecnm.mx"),
    ("", None),
    ("   ", None),
    (None, None),
    ("Jefatura@CdJuarez.TecNM.mx", "Jefatura@CdJuarez.TecNM.mx"),   # NO se lowercasea
])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("value", [
    "a@b.mx", "jefatura_syc@cdjuarez.tecnm.mx", "nombre.apellido@cdjuarez.tecnm.mx",
])
def test_valid_emails(value):
    assert is_valid_email(value) is True


@pytest.mark.parametrize("value", [
    "sin-arroba.mx", "a@b", "a@@b.mx", "a b@c.mx", "@b.mx", "a@.mx", "a@b.",
])
def test_invalid_emails(value):
    assert is_valid_email(value) is False


def test_conflict_carries_other_position(db_session):
    a = Position(code="tst_email_a", title="A", email="dup@cdjuarez.tecnm.mx", is_active=True)
    db_session.add(a)
    db_session.flush()
    b = Position(code="tst_email_b", title="B", is_active=True)
    db_session.add(b)
    db_session.flush()

    with pytest.raises(svc.PositionEmailConflict) as exc:
        svc.validate_position_email(db_session, "DUP@cdjuarez.tecnm.mx", exclude_position_id=b.id)
    assert exc.value.other_position_id == a.id
    assert exc.value.other_position_title == "A"


def test_same_position_keeps_its_own_email(db_session):
    a = Position(code="tst_email_c", title="C", email="own@cdjuarez.tecnm.mx", is_active=True)
    db_session.add(a)
    db_session.flush()
    assert svc.validate_position_email(
        db_session, "own@cdjuarez.tecnm.mx", exclude_position_id=a.id
    ) == "own@cdjuarez.tecnm.mx"


def test_invalid_format_raises(db_session):
    with pytest.raises(svc.PositionEmailInvalid):
        svc.validate_position_email(db_session, "no-es-correo", exclude_position_id=None)


def test_empty_email_becomes_none(db_session):
    assert svc.validate_position_email(db_session, "   ", exclude_position_id=None) is None


def test_update_position_clears_email(db_session):
    p = Position(code="tst_email_d", title="D", email="borrame@cdjuarez.tecnm.mx", is_active=True)
    db_session.add(p)
    db_session.flush()
    svc.update_position(db_session, p.id, email="")
    assert p.email is None

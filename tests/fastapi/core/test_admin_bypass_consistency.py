"""Task 2.3: is_global_admin reconoce el rol global tanto string como lista."""
from itcj2.dependencies import is_global_admin


def test_string_admin():
    assert is_global_admin({"sub": "1", "role": "admin"}) is True


def test_list_admin():
    # tokens refrescados (bug histórico) traían role como lista
    assert is_global_admin({"sub": "1", "role": ["admin", "tech"]}) is True


def test_non_admin_string():
    assert is_global_admin({"sub": "1", "role": "student"}) is False


def test_non_admin_list():
    assert is_global_admin({"sub": "1", "role": ["tech", "coord"]}) is False


def test_missing_role():
    assert is_global_admin({"sub": "1"}) is False
    assert is_global_admin(None) is False

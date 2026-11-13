"""Cifrado Fernet y normalización del patrón de Cámaras."""
import pytest

from itcj2.apps.cameras.services import secrets as sec


def test_roundtrip(cameras_key):
    assert sec.decrypt(sec.encrypt("Ab 1ñ ")) == "Ab 1ñ "


def test_no_key_raises(monkeypatch):
    from itcj2.config import get_settings
    monkeypatch.setattr(get_settings(), "CAMERAS_SECRET_KEY", None)
    with pytest.raises(sec.CamerasKeyMissing):
        sec.encrypt("x")
    with pytest.raises(sec.CamerasKeyMissing):
        sec.decrypt("x")


def test_normalize_pattern_ok():
    assert sec.normalize_pattern("1-2-5-9") == "1259"
    assert sec.normalize_pattern("7 5 3 6") == "7536"
    assert sec.normalize_pattern("1→2→3→4") == "1234"


@pytest.mark.parametrize("raw", ["123", "1123", "1230", "12a4", "1234567891"])
def test_normalize_pattern_rejects(raw):
    with pytest.raises(ValueError) as e:
        sec.normalize_pattern(raw)
    assert raw not in str(e.value)

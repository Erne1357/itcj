"""Regresión del bug: _get_active_theme debe abrir sesión y cachear en Redis."""
from unittest.mock import MagicMock, patch


def test_get_active_theme_returns_theme_and_passes_db():
    fake_theme = MagicMock()
    fake_theme.to_dict.return_value = {"id": 1, "name": "Mundial 2026"}

    fake_redis = MagicMock()
    fake_redis.get.return_value = None  # cache miss

    with patch("itcj2.templates.get_redis", return_value=fake_redis), \
         patch("itcj2.database.SessionLocal") as mock_sl, \
         patch("itcj2.core.services.themes_service.get_active_theme",
               return_value=fake_theme) as mock_get:
        from itcj2.templates import _get_active_theme
        result = _get_active_theme()

    assert result == {"id": 1, "name": "Mundial 2026"}
    # Se llamó con la sesión producida por el context manager de SessionLocal
    mock_sl.assert_called_once()
    assert mock_get.call_args.args[0] is mock_sl.return_value.__enter__.return_value
    # Se escribió el cache
    assert fake_redis.set.called or fake_redis.setex.called


def test_get_active_theme_uses_cache_hit():
    fake_redis = MagicMock()
    fake_redis.get.return_value = '{"id": 9, "name": "Cached"}'

    with patch("itcj2.templates.get_redis", return_value=fake_redis), \
         patch("itcj2.core.services.themes_service.get_active_theme") as mock_get:
        from itcj2.templates import _get_active_theme
        result = _get_active_theme()

    assert result == {"id": 9, "name": "Cached"}
    mock_get.assert_not_called()  # no tocó la BD

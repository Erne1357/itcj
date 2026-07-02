"""Task 2.3: delete_app/role/perm invalidan el caché de authz."""
from unittest.mock import MagicMock, patch

from itcj2.core.api import authz as authz_api


def _mock_db_with_obj(obj):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = obj
    return db


def test_delete_role_busts_cache():
    db = _mock_db_with_obj(MagicMock(name="role"))
    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        authz_api.delete_role(role_name="x", user={"sub": "1"}, db=db)
    inv.assert_called_once()


def test_delete_app_busts_cache():
    db = _mock_db_with_obj(MagicMock(name="app"))
    with patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        authz_api.delete_app(app_key="x", user={"sub": "1"}, db=db)
    inv.assert_called_once()


def test_delete_perm_busts_cache():
    app_obj = MagicMock(id=1)
    perm_obj = MagicMock(name="perm")
    db = MagicMock()
    # get_or_404_app -> app; luego Permission query -> perm
    with patch("itcj2.core.services.authz_service.get_or_404_app", return_value=app_obj), \
         patch("itcj2.core.services.authz_cache.invalidate_all") as inv:
        db.query.return_value.filter_by.return_value.first.return_value = perm_obj
        authz_api.delete_perm(app_key="x", code="c", user={"sub": "1"}, db=db)
    inv.assert_called_once()

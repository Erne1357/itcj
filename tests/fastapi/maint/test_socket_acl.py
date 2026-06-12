"""H10 — ACL de los rooms WS de maint.

Verifica que _can_join_dispatcher / _can_join_dept / _can_join_ticket
apliquen rol / pertenencia / visibilidad antes de unir un socket a un room.
"""
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.sockets import maint as maint_sockets


class TestCanJoinDispatcher:
    def test_none_user_denied(self):
        assert maint_sockets._can_join_dispatcher(None) is False

    def test_jwt_global_admin_allowed_without_db(self):
        # role admin del JWT → no debe tocar la BD
        with patch("itcj2.database.SessionLocal") as mock_sl:
            assert maint_sockets._can_join_dispatcher({"sub": "1", "role": "admin"}) is True
            mock_sl.assert_not_called()

    def test_dispatcher_role_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["dispatcher"]):
            assert maint_sockets._can_join_dispatcher({"sub": "7674", "role": "user"}) is True

    def test_plain_staff_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["staff"]):
            assert maint_sockets._can_join_dispatcher({"sub": "999", "role": "user"}) is False

    def test_coordinator_denied(self):
        # coordinadores NO escuchan la bandeja global del dispatcher
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["maint_general_coordinator"]):
            assert maint_sockets._can_join_dispatcher({"sub": "8284", "role": "user"}) is False


class TestCanJoinDept:
    def test_full_access_role_any_dept(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["dispatcher"]):
            assert maint_sockets._can_join_dept({"sub": "1", "role": "user"}, 5) is True

    def test_member_of_dept_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["department_head"]), \
             patch("itcj2.apps.maint.services.department_dashboard_service._resolve_user_departments",
                   return_value=[{"id": 5}, {"id": 9}]):
            assert maint_sockets._can_join_dept({"sub": "7650", "role": "user"}, 5) is True

    def test_other_dept_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["department_head"]), \
             patch("itcj2.apps.maint.services.department_dashboard_service._resolve_user_departments",
                   return_value=[{"id": 5}]):
            assert maint_sockets._can_join_dept({"sub": "7650", "role": "user"}, 99) is False


class TestCanJoinTicket:
    def test_none_user_denied(self):
        assert maint_sockets._can_join_ticket(None, 1) is False

    def test_missing_ticket_denied(self):
        db = MagicMock()
        db.get.return_value = None
        with patch("itcj2.database.SessionLocal", return_value=db):
            assert maint_sockets._can_join_ticket({"sub": "10", "role": "user"}, 123) is False

    def test_delegates_to_can_user_view_ticket(self):
        db = MagicMock()
        db.get.return_value = MagicMock()  # ticket existe
        with patch("itcj2.database.SessionLocal", return_value=db), \
             patch("itcj2.apps.maint.services.ticket_service.can_user_view_ticket",
                   return_value=True) as mock_view:
            assert maint_sockets._can_join_ticket({"sub": "10", "role": "user"}, 123) is True
            mock_view.assert_called_once()

    def test_not_visible_denied(self):
        db = MagicMock()
        db.get.return_value = MagicMock()
        with patch("itcj2.database.SessionLocal", return_value=db), \
             patch("itcj2.apps.maint.services.ticket_service.can_user_view_ticket",
                   return_value=False):
            assert maint_sockets._can_join_ticket({"sub": "10", "role": "user"}, 123) is False

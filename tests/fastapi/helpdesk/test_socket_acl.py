"""ACL de los rooms WS de helpdesk.

Los rooms reparten eventos con título, solicitante, prioridad y área de cada
ticket. Unirse a uno tiene que exigir lo mismo que la API equivalente: el room de
ticket, la visibilidad del ticket; el de departamento, el scope departamental
(subárbol incluido); el de equipo, ser técnico de esa área; el de admin, ser admin.

Espejo de tests/fastapi/maint/test_socket_acl.py, que cubre el namespace gemelo.
"""
from unittest.mock import MagicMock, patch

import itcj2.models  # noqa: F401

from itcj2.sockets import helpdesk as hd_sockets


class TestCanJoinAdmin:
    def test_none_user_denied(self):
        assert hd_sockets._can_join_admin(None) is False

    def test_jwt_global_admin_allowed_without_db(self):
        with patch("itcj2.database.SessionLocal") as mock_sl:
            assert hd_sockets._can_join_admin({"sub": "1", "role": "admin"}) is True
            mock_sl.assert_not_called()

    def test_helpdesk_admin_role_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["admin"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]):
            assert hd_sockets._can_join_admin({"sub": "50", "role": "user"}) is True

    def test_secretary_comp_center_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["secretary"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[50]):
            assert hd_sockets._can_join_admin({"sub": "50", "role": "user"}) is True

    def test_plain_staff_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["staff"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]):
            assert hd_sockets._can_join_admin({"sub": "999", "role": "user"}) is False

    def test_technician_allowed(self):
        """Un técnico ya lee cualquier ticket por la API y usa /admin/tickets:
        el room no puede ser más estricto que el endpoint equivalente."""
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["tech_soporte"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]):
            assert hd_sockets._can_join_admin({"sub": "77", "role": "user"}) is True

    def test_department_head_denied(self):
        """Un jefe de departamento solo ve su subárbol: el room global no es suyo."""
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["department_head"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]):
            assert hd_sockets._can_join_admin({"sub": "7650", "role": "user"}) is False


class TestCanJoinDept:
    def test_none_user_denied(self):
        assert hd_sockets._can_join_dept(None, 5) is False

    def test_technician_any_dept(self):
        """tech_* ya ve cualquier ticket en la API — el room no puede ser más estricto."""
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["tech_desarrollo"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]):
            assert hd_sockets._can_join_dept({"sub": "1", "role": "user"}, 5) is True

    def test_subtree_dept_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["department_head"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]), \
             patch("itcj2.sockets.helpdesk._visible_dept_ids", return_value={5, 9}):
            assert hd_sockets._can_join_dept({"sub": "7650", "role": "user"}, 9) is True

    def test_other_branch_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["department_head"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]), \
             patch("itcj2.sockets.helpdesk._visible_dept_ids", return_value={5}):
            assert hd_sockets._can_join_dept({"sub": "7650", "role": "user"}, 99) is False

    def test_plain_staff_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["staff"]), \
             patch("itcj2.core.services.authz_service._get_users_with_position",
                   return_value=[]), \
             patch("itcj2.sockets.helpdesk._visible_dept_ids", return_value=set()):
            assert hd_sockets._can_join_dept({"sub": "999", "role": "user"}, 5) is False


class TestCanJoinTeam:
    def test_none_user_denied(self):
        assert hd_sockets._can_join_team(None, "desarrollo") is False

    def test_jwt_global_admin_allowed_without_db(self):
        with patch("itcj2.database.SessionLocal") as mock_sl:
            assert hd_sockets._can_join_team({"sub": "1", "role": "admin"}, "soporte") is True
            mock_sl.assert_not_called()

    def test_matching_area_allowed(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["tech_desarrollo"]):
            assert hd_sockets._can_join_team({"sub": "77", "role": "user"}, "desarrollo") is True

    def test_other_area_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["tech_desarrollo"]):
            assert hd_sockets._can_join_team({"sub": "77", "role": "user"}, "soporte") is False

    def test_plain_staff_denied(self):
        with patch("itcj2.database.SessionLocal", return_value=MagicMock()), \
             patch("itcj2.core.services.authz_service.user_roles_in_app",
                   return_value=["staff"]):
            assert hd_sockets._can_join_team({"sub": "999", "role": "user"}, "desarrollo") is False


class TestCanJoinTicket:
    def test_none_user_denied(self):
        assert hd_sockets._can_join_ticket(None, 1) is False

    def test_jwt_global_admin_allowed_without_db(self):
        with patch("itcj2.database.SessionLocal") as mock_sl:
            assert hd_sockets._can_join_ticket({"sub": "1", "role": "admin"}, 42) is True
            mock_sl.assert_not_called()

    def test_missing_ticket_denied(self):
        db = MagicMock()
        db.get.return_value = None
        with patch("itcj2.database.SessionLocal", return_value=db):
            assert hd_sockets._can_join_ticket({"sub": "5", "role": "user"}, 42) is False

    def test_delegates_to_can_user_view_ticket(self):
        db = MagicMock()
        db.get.return_value = object()
        with patch("itcj2.database.SessionLocal", return_value=db), \
             patch("itcj2.apps.helpdesk.services.ticket_service.can_user_view_ticket",
                   return_value=False) as mock_can:
            assert hd_sockets._can_join_ticket({"sub": "5", "role": "user"}, 42) is False
            mock_can.assert_called_once()

    def test_visible_ticket_allowed(self):
        db = MagicMock()
        db.get.return_value = object()
        with patch("itcj2.database.SessionLocal", return_value=db), \
             patch("itcj2.apps.helpdesk.services.ticket_service.can_user_view_ticket",
                   return_value=True):
            assert hd_sockets._can_join_ticket({"sub": "5", "role": "user"}, 42) is True

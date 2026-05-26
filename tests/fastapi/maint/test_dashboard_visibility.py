"""Tests para los helpers de visibilidad en dashboard_service."""
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services import dashboard_service as ds


class TestApplyVisibility:
    def _make_query(self):
        """Mock de un query SQLAlchemy donde .filter(...) retorna otro mock chainable."""
        q = MagicMock()
        q.filter.return_value = q  # chainable
        return q

    def test_admin_no_filter(self):
        q = self._make_query()
        result = ds._apply_visibility(q, user_id=1, user_roles=["admin"], db=MagicMock())
        # Sin filter
        q.filter.assert_not_called()
        assert result is q

    def test_dispatcher_no_filter(self):
        q = self._make_query()
        ds._apply_visibility(q, user_id=1, user_roles=["dispatcher"], db=MagicMock())
        q.filter.assert_not_called()

    def test_tech_maint_no_filter(self):
        q = self._make_query()
        ds._apply_visibility(q, user_id=1, user_roles=["tech_maint"], db=MagicMock())
        q.filter.assert_not_called()

    def test_dept_head_filters_by_department(self):
        q = self._make_query()
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.services.dashboard_service._resolve_dept_id",
            return_value=42,
        ):
            ds._apply_visibility(q, user_id=10, user_roles=["department_head"], db=db)
        q.filter.assert_called_once()

    def test_dept_head_without_dept_returns_empty(self):
        """Si no se puede resolver el dept_id, debe filtrar por id=-1 (no resultados)."""
        q = self._make_query()
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.services.dashboard_service._resolve_dept_id",
            return_value=None,
        ):
            ds._apply_visibility(q, user_id=10, user_roles=["department_head"], db=db)
        q.filter.assert_called_once()

    def test_secretary_filters_like_dept_head(self):
        q = self._make_query()
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.services.dashboard_service._resolve_dept_id",
            return_value=7,
        ):
            ds._apply_visibility(q, user_id=10, user_roles=["secretary"], db=db)
        q.filter.assert_called_once()

    def test_staff_filters_by_owner(self):
        q = self._make_query()
        ds._apply_visibility(q, user_id=42, user_roles=["staff"], db=MagicMock())
        q.filter.assert_called_once()

    def test_no_role_filters_by_owner(self):
        """Sin roles maint conocidos → solo propios (mismo trato que staff)."""
        q = self._make_query()
        ds._apply_visibility(q, user_id=99, user_roles=[], db=MagicMock())
        q.filter.assert_called_once()


class TestResolveDeptId:
    def test_returns_dept_when_active_position(self):
        db = MagicMock()
        position = MagicMock(department_id=15)
        user_pos = MagicMock(position=position)
        # patch del import dentro de la función
        with patch("itcj2.core.models.position.UserPosition") as MockUP:
            db.query.return_value.filter_by.return_value.first.return_value = user_pos
            result = ds._resolve_dept_id(db, user_id=1)
        assert result == 15

    def test_returns_none_when_no_position(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        result = ds._resolve_dept_id(db, user_id=1)
        assert result is None

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("boom")
        result = ds._resolve_dept_id(db, user_id=1)
        assert result is None

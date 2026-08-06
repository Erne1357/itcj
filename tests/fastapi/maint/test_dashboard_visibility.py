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

    def test_tech_maint_scoped_by_area(self):
        """D-G/H3: tech_maint YA NO es full-access en el dashboard.

        Ve solo asignados/propios/de su área → se aplica un filter (condición
        construida por _visibility_cond), no pasa sin restricción.
        """
        q = self._make_query()
        ds._apply_visibility(q, user_id=1, user_roles=["tech_maint"], db=MagicMock())
        q.filter.assert_called_once()

    def test_dept_head_filters_by_department(self):
        """department_head siempre termina en un único filter() aditivo —
        propio ∨ asignado ∨ departamento/subárbol (_visibility_cond), sin
        importar si `_resolve_user_departments`/`subtree_scope_for` resuelven
        algo o no (real, no mockeado aquí — ambos toleran MagicMock db)."""
        q = self._make_query()
        db = MagicMock()
        ds._apply_visibility(q, user_id=10, user_roles=["department_head"], db=db)
        q.filter.assert_called_once()

    def test_dept_head_without_dept_returns_single_additive_filter(self):
        """Aunque no se resuelva ningún departamento, sigue habiendo UN filter()
        — ya no cae a `id == -1` (eso escondía los tickets propios): al menos
        queda la condición de propiedad/asignación de `_visibility_cond`."""
        q = self._make_query()
        db = MagicMock()
        with patch(
            "itcj2.apps.maint.services.department_dashboard_service._resolve_user_departments",
            return_value=[],
        ):
            ds._apply_visibility(q, user_id=10, user_roles=["department_head"], db=db)
        q.filter.assert_called_once()

    def test_secretary_filters_like_dept_head(self):
        q = self._make_query()
        db = MagicMock()
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

    def test_area_coordinator_scoped_by_visibility_cond(self):
        """maint_area_coordinator YA NO es full-access (issue #1/#4): un solo
        filter() aditivo, igual que el resto de roles acotados."""
        q = self._make_query()
        ds._apply_visibility(q, user_id=1, user_roles=["maint_area_coordinator"], db=MagicMock())
        q.filter.assert_called_once()


# `_resolve_dept_id` (mono-depto, sin ventana start/end_date, sin orden) se
# eliminó de dashboard_service.py: ya no lo llamaba ninguna ruta de producción
# (_apply_visibility usa _resolve_user_departments, el resolver canónico
# multi-puesto) y era código muerto peligroso si alguien volvía a engancharlo.
# Ver itcj2/apps/maint/services/department_dashboard_service.py::_resolve_user_departments.

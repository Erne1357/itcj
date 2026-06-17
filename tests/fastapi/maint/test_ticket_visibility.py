"""
Tests para la visibilidad de tickets por rol en `ticket_service`.

Cubre el cambio que limita a `tech_maint`:
- Con áreas (maint_technician_areas): ve tickets cuya categoría está en sus áreas
  (más asignados + propios).
- Sin áreas: solo ve asignados a sí mismo (+ propios).

`admin` y `dispatcher` siguen viendo todo. `department_head` / `secretary` por
departamento. `staff` (y resto) solo propios.
"""
from unittest.mock import MagicMock, patch

import pytest

import itcj2.models  # noqa: F401

from itcj2.apps.maint.services import ticket_service


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _chainable_query():
    """MagicMock cuyo .filter(...) y .order_by(...) devuelven el mismo mock."""
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    return q


def _ticket(requester_id=1, category_code='TRANSPORT', technicians=None, coordinator_id=None):
    t = MagicMock()
    t.requester_id = requester_id
    t.coordinator_id = coordinator_id
    t.category = MagicMock(code=category_code)
    t.technicians = technicians or []
    return t


def _active_tech(user_id):
    """Helper: técnico activo (unassigned_at=None)."""
    tt = MagicMock()
    tt.user_id = user_id
    tt.unassigned_at = None
    return tt


def _unassigned_tech(user_id):
    tt = MagicMock()
    tt.user_id = user_id
    tt.unassigned_at = "2026-01-01"
    return tt


# ─────────────────────────────────────────────────────────────────────
# _get_tech_maint_area_codes
# ─────────────────────────────────────────────────────────────────────

class TestGetTechMaintAreaCodes:
    def test_returns_area_codes_for_user(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            ('TRANSPORT',), ('ELECTRICAL',),
        ]
        result = ticket_service._get_tech_maint_area_codes(db, user_id=10)
        assert result == ['TRANSPORT', 'ELECTRICAL']

    def test_returns_empty_when_no_areas(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        result = ticket_service._get_tech_maint_area_codes(db, user_id=10)
        assert result == []


# ─────────────────────────────────────────────────────────────────────
# list_tickets — scope por rol
# ─────────────────────────────────────────────────────────────────────

class TestListTicketsScope:
    """
    Mockeamos `db.query(MaintTicket)` para verificar QUÉ filtros aplica.
    No comparamos SQL — solo que la rama correcta se ejecutó (vía spy en helper).
    """

    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_admin_sin_restriccion(self, mock_paginate):
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['admin'],
        )
        # admin nunca debe consultar áreas del técnico
        # (asegura que no se llama _get_tech_maint_area_codes)
        # En cambio sí debe haber llamado a order_by (no filter por scope)
        # No assertions estrictas: smoke test de que no crashea.
        assert mock_paginate.called

    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_dispatcher_sin_restriccion(self, mock_paginate):
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['dispatcher'],
        )
        assert mock_paginate.called

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_tech_maint_con_areas_consulta_areas(self, mock_paginate, mock_areas):
        """tech_maint con áreas: debe consultar sus áreas y filtrar."""
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        mock_areas.return_value = ['TRANSPORT', 'ELECTRICAL']
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=42, user_roles=['tech_maint'],
        )

        mock_areas.assert_called_once_with(db, 42)
        # Verifica que sí se filtra (no es FULL_ACCESS)
        assert db.query.return_value.filter.called

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_tech_maint_sin_areas_solo_asignados(self, mock_paginate, mock_areas):
        """tech_maint sin áreas: filtra a asignados/propios."""
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        mock_areas.return_value = []
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=42, user_roles=['tech_maint'],
        )

        mock_areas.assert_called_once_with(db, 42)
        # Filter aplicado (no FULL_ACCESS)
        assert db.query.return_value.filter.called

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_admin_no_consulta_areas(self, mock_paginate, mock_areas):
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['admin'],
        )

        mock_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_dispatcher_no_consulta_areas(self, mock_paginate, mock_areas):
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['dispatcher'],
        )

        mock_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_staff_no_consulta_areas(self, mock_paginate, mock_areas):
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['staff'],
        )

        mock_areas.assert_not_called()
        assert db.query.return_value.filter.called

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_general_coord_sin_restriccion(self, mock_paginate, mock_coord_areas):
        """Coordinador GENERAL → full access (read.all), no consulta áreas."""
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=1, user_roles=['maint_general_coordinator'],
        )
        mock_coord_areas.assert_not_called()

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    @patch("itcj2.apps.maint.services.ticket_service.paginate")
    def test_area_coord_consulta_sus_areas(self, mock_paginate, mock_coord_areas):
        """Coordinador de ÁREA → NO es full access; scopea por sus áreas."""
        mock_paginate.return_value = MagicMock(
            items=[], total=0, pages=0, has_next=False, has_prev=False,
        )
        mock_coord_areas.return_value = ['ELECTRICAL']
        db = MagicMock()
        db.query.return_value = _chainable_query()

        ticket_service.list_tickets(
            db=db, user_id=42, user_roles=['maint_area_coordinator'],
        )
        mock_coord_areas.assert_called_once_with(db, 42)
        assert db.query.return_value.filter.called


# ─────────────────────────────────────────────────────────────────────
# can_user_view_ticket
# ─────────────────────────────────────────────────────────────────────

class TestCanUserViewTicket:
    def _patch_roles(self, roles):
        return patch(
            "itcj2.core.services.authz_service.user_roles_in_app",
            return_value=list(roles),
        )

    def test_admin_ve_todo(self):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC')
        with self._patch_roles(['admin']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=1) is True

    def test_dispatcher_ve_todo(self):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC')
        with self._patch_roles(['dispatcher']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=1) is True

    def test_propio_siempre_visible(self):
        db = MagicMock()
        ticket = _ticket(requester_id=5, category_code='AC')
        with self._patch_roles(['staff']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=5) is True

    def test_tecnico_asignado_activo_visible(self):
        db = MagicMock()
        ticket = _ticket(
            requester_id=99,
            category_code='AC',
            technicians=[_active_tech(7)],
        )
        with self._patch_roles(['tech_maint']):
            with patch(
                "itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes",
                return_value=[],
            ):
                assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is True

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_maint_con_area_coincidente_ve_ticket(self, mock_areas):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='TRANSPORT')
        mock_areas.return_value = ['TRANSPORT', 'AC']
        with self._patch_roles(['tech_maint']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is True

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_maint_con_area_diferente_no_ve_ticket(self, mock_areas):
        db = MagicMock()
        ticket = _ticket(
            requester_id=99,
            category_code='TRANSPORT',
            technicians=[_active_tech(2)],  # otro tech, no el user
        )
        mock_areas.return_value = ['ELECTRICAL', 'AC']
        with self._patch_roles(['tech_maint']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is False

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_maint_sin_area_y_sin_asignacion_no_ve(self, mock_areas):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='TRANSPORT')
        mock_areas.return_value = []
        with self._patch_roles(['tech_maint']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is False

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_maint_sin_area_pero_asignado_si_ve(self, mock_areas):
        db = MagicMock()
        ticket = _ticket(
            requester_id=99,
            category_code='TRANSPORT',
            technicians=[_active_tech(7)],
        )
        mock_areas.return_value = []
        with self._patch_roles(['tech_maint']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is True

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_maint_tecnico_desasignado_no_cuenta(self, mock_areas):
        """Si el tech fue desasignado y su área no coincide → no ve."""
        db = MagicMock()
        ticket = _ticket(
            requester_id=99,
            category_code='TRANSPORT',
            technicians=[_unassigned_tech(7)],
        )
        mock_areas.return_value = ['AC']
        with self._patch_roles(['tech_maint']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is False

    def test_staff_no_propio_no_visible(self):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC')
        with self._patch_roles(['staff']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=1) is False

    def test_general_coord_ve_todo(self):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC')
        with self._patch_roles(['maint_general_coordinator']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=1) is True

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_area_coord_categoria_de_su_area_ve(self, mock_coord_areas):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='ELECTRICAL')
        mock_coord_areas.return_value = ['ELECTRICAL', 'TRANSPORT']
        with self._patch_roles(['maint_area_coordinator']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is True

    @patch("itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas")
    def test_area_coord_categoria_distinta_no_ve(self, mock_coord_areas):
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC', technicians=[_active_tech(2)])
        mock_coord_areas.return_value = ['ELECTRICAL']
        with self._patch_roles(['maint_area_coordinator']):
            assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is False

    def test_area_coord_ruteado_a_el_ve(self):
        """Ticket ruteado al coordinador de área (coordinator_id) → visible aunque
        la categoría no sea de su área (debe poder devolverlo/operarlo)."""
        db = MagicMock()
        ticket = _ticket(requester_id=99, category_code='AC', coordinator_id=7)
        with self._patch_roles(['maint_area_coordinator']):
            with patch(
                "itcj2.apps.maint.services.coordinator_service.CoordinatorService.get_coordinator_areas",
                return_value=['ELECTRICAL'],
            ):
                assert ticket_service.can_user_view_ticket(db, ticket, user_id=7) is True


# ─────────────────────────────────────────────────────────────────────
# start_progress — permisos por área
# ─────────────────────────────────────────────────────────────────────

class TestStartProgressArea:
    def _make_ticket(self, status='ASSIGNED', category_code='TRANSPORT', technicians=None):
        t = MagicMock()
        t.status = status
        t.id = 1
        t.ticket_number = 'MANT-2026-000001'
        t.category = MagicMock(code=category_code)
        t.technicians = technicians or []
        return t

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_area_puede_iniciar_aunque_no_asignado(self, mock_areas):
        db = MagicMock()
        ticket = self._make_ticket(category_code='TRANSPORT')
        db.get.return_value = ticket
        mock_areas.return_value = ['TRANSPORT']

        result = ticket_service.start_progress(
            db=db, ticket_id=1, user_id=7,
            user_roles=['tech_maint'],
        )
        assert result.status == 'IN_PROGRESS'

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_area_distinta_no_puede_iniciar(self, mock_areas):
        from fastapi import HTTPException
        db = MagicMock()
        ticket = self._make_ticket(category_code='TRANSPORT')
        db.get.return_value = ticket
        mock_areas.return_value = ['AC']

        with pytest.raises(HTTPException) as exc:
            ticket_service.start_progress(
                db=db, ticket_id=1, user_id=7,
                user_roles=['tech_maint'],
            )
        assert exc.value.status_code == 403

    @patch("itcj2.apps.maint.services.ticket_service._get_tech_maint_area_codes")
    def test_tech_sin_area_pero_asignado_puede_iniciar(self, mock_areas):
        db = MagicMock()
        ticket = self._make_ticket(
            category_code='TRANSPORT',
            technicians=[_active_tech(7)],
        )
        db.get.return_value = ticket
        mock_areas.return_value = []

        result = ticket_service.start_progress(
            db=db, ticket_id=1, user_id=7,
            user_roles=['tech_maint'],
        )
        assert result.status == 'IN_PROGRESS'

    def test_dispatcher_siempre_puede_iniciar(self):
        db = MagicMock()
        ticket = MagicMock(
            status='ASSIGNED', id=1, ticket_number='MANT-2026-000001',
            category=MagicMock(code='TRANSPORT'), technicians=[],
        )
        db.get.return_value = ticket
        result = ticket_service.start_progress(
            db=db, ticket_id=1, user_id=99,
            user_roles=['dispatcher'],
        )
        assert result.status == 'IN_PROGRESS'

"""
Tests exhaustivos para /api/help-desk/v2/config/statuses

Cubre:
- GET /           lista activos (default) e inactivos
- GET /{id}       200 existente, 404 inexistente
- PATCH /{id}     actualiza label/color/badge_class/icon/display_order;
                  rechaza code/progress_pct/stage/is_open/is_resolved/is_terminal (schema los filtra)
- POST /{id}/toggle  previene desactivar estado no-terminal con tickets activos
- POST /reorder   actualiza display_order de múltiples estados
- NO existe POST create ni DELETE — 404/405 esperado
- Audit: cada write inserta ConfigChangeLog con entity_type='status'
- Cache: invalidate_statuses() llamado tras cada write
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.helpdesk.config.conftest import make_status, make_config_log

BASE = "/api/help-desk/v2/config/statuses"


# =============================================================================
# GET / — listar estados
# =============================================================================

class TestListStatuses:
    def test_returns_only_active_by_default(self, app_client, db_session, admin_headers):
        make_status(db_session, code="STA_ACT", label="Activo", is_active=True)
        make_status(db_session, code="STA_INA", label="Inactivo", is_active=False)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        codes = [s["code"] for s in r.json()["statuses"]]
        assert "STA_ACT" in codes
        assert "STA_INA" not in codes

    def test_include_inactive_returns_all(self, app_client, db_session, admin_headers):
        make_status(db_session, code="STA_I2", label="Inactivo2", is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}?include_inactive=true", headers=admin_headers)
        assert r.status_code == 200
        codes = [s["code"] for s in r.json()["statuses"]]
        assert "STA_I2" in codes

    def test_response_shape(self, app_client, db_session, admin_headers):
        make_status(db_session, code="STA_SHP", label="Shape")
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "statuses" in body
        assert "total" in body

    def test_ordered_by_display_order(self, app_client, db_session, admin_headers):
        make_status(db_session, code="STA_ORD3", label="Z", display_order=30)
        make_status(db_session, code="STA_ORD1", label="A", display_order=10)
        make_status(db_session, code="STA_ORD2", label="M", display_order=20)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        relevant = [s for s in r.json()["statuses"] if s["code"] in {"STA_ORD1", "STA_ORD2", "STA_ORD3"}]
        orders = [s["display_order"] for s in relevant]
        assert orders == sorted(orders)

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /{id} — detalle de estado
# =============================================================================

class TestGetStatus:
    def test_existing_returns_200(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="STA_DET", label="Detail Status")
        db_session.flush()

        r = app_client.get(f"{BASE}/{s.id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"]["code"] == "STA_DET"

    def test_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "not_found"

    def test_response_includes_all_flags(self, app_client, db_session, admin_headers):
        s = make_status(
            db_session,
            code="STA_FLAGS",
            label="Flags",
            is_terminal=True,
            is_resolved=True,
            is_open=False,
            stage="closed",
            progress_pct=100,
        )
        db_session.flush()

        r = app_client.get(f"{BASE}/{s.id}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()["status"]
        assert body["is_terminal"] is True
        assert body["is_resolved"] is True
        assert body["is_open"] is False
        assert body["progress_pct"] == 100

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PATCH /{id} — actualizar metadata del estado
# =============================================================================

class TestUpdateStatus:
    def test_update_label_succeeds(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="UPD_LBL_S", label="Old Label")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{s.id}", json={"label": "New Label"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"]["label"] == "New Label"

    def test_update_color_icon_badge(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="UPD_VIS_S", label="Visual")
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{s.id}",
            json={"color": "#abcdef", "icon": "fa-star", "badge_class": "bg-success"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()["status"]
        assert body["color"] == "#abcdef"
        assert body["icon"] == "fa-star"
        assert body["badge_class"] == "bg-success"

    def test_code_field_filtered_by_schema(self, app_client, db_session, admin_headers):
        """El schema UpdateStatusRequest no incluye 'code' — Pydantic lo descarta."""
        s = make_status(db_session, code="IMMUTABLE_CODE", label="Immutable")
        db_session.flush()
        original_code = s.code

        r = app_client.patch(
            f"{BASE}/{s.id}",
            json={"code": "CHANGED", "label": "New"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["status"]["code"] == original_code

    def test_progress_pct_filtered_by_schema(self, app_client, db_session, admin_headers):
        """progress_pct no está en el schema → Pydantic lo ignora (no error 422)."""
        s = make_status(db_session, code="IMM_PCT", label="Pct", progress_pct=0)
        db_session.flush()

        # Enviar progress_pct en el payload — Pydantic lo ignora (no 422)
        r = app_client.patch(
            f"{BASE}/{s.id}",
            json={"progress_pct": 99, "label": "Still Valid"},
            headers=admin_headers,
        )
        # El request debe aceptarse (campo extra ignorado)
        assert r.status_code == 200
        # progress_pct no debe haber cambiado
        assert r.json()["status"]["progress_pct"] == 0

    def test_stage_filtered_by_schema(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="IMM_STG", label="Stage", stage="created")
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{s.id}",
            json={"stage": "closed", "label": "Updated"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["status"]["stage"] == "created"

    def test_is_terminal_filtered_by_schema(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="IMM_TERM", label="Terminal", is_terminal=False)
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{s.id}",
            json={"is_terminal": True, "label": "Updated"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["status"]["is_terminal"] is False

    def test_update_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.patch(f"{BASE}/99999", json={"label": "NoExist"}, headers=admin_headers)
        assert r.status_code == 404

    def test_update_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s = make_status(db_session, code="AUD_UPD_S", label="Audit Update Status")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{s.id}", json={"label": "Updated"}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status", action="update", entity_id=s.id)
            .first()
        )
        assert log is not None
        assert log.before_data["label"] == "Audit Update Status"
        assert log.after_data["label"] == "Updated"

    def test_update_calls_invalidate_statuses_cache(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="INV_STA", label="Inv Status")
        db_session.flush()

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_statuses") as mock_inv:
            r = app_client.patch(f"{BASE}/{s.id}", json={"label": "Updated"}, headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.patch(f"{BASE}/1", json={"label": "X"}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /{id}/toggle — activar/desactivar estado
# =============================================================================

class TestToggleStatus:
    def test_deactivate_terminal_status_with_tickets_allowed(
        self, app_client, db_session, admin_headers
    ):
        """Estado terminal puede desactivarse aunque tenga tickets (no hay restricción)."""
        s = make_status(
            db_session,
            code="TERM_TOG",
            label="Terminal Toggle",
            is_terminal=True,
            is_active=True,
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{s.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"]["is_active"] is False

    def test_deactivate_nonterminal_with_active_tickets_returns_400(
        self, app_client, db_session, admin_headers
    ):
        """Estado no-terminal con tickets activos → 400."""
        s = make_status(
            db_session,
            code="NONTERM_TOG",
            label="NonTerminal Toggle",
            is_terminal=False,
            is_active=True,
        )
        db_session.flush()

        from itcj2.apps.helpdesk.models.ticket import Ticket as RealTicket

        mock_q_chain = MagicMock()
        mock_q_chain.filter.return_value = mock_q_chain
        mock_q_chain.count.return_value = 5

        original_query = db_session.query

        def patched_query(cls):
            if cls is RealTicket:
                return mock_q_chain
            return original_query(cls)

        db_session.query = patched_query
        try:
            r = app_client.post(
                f"{BASE}/{s.id}/toggle",
                json={"is_active": False},
                headers=admin_headers,
            )
            assert r.status_code == 400
            assert r.json()["error"]["error"] == "has_active_tickets"
        finally:
            db_session.query = original_query

    def test_activate_inactive_status_succeeds(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="STA_REAC", label="Reactivate", is_active=False)
        db_session.flush()

        r = app_client.post(f"{BASE}/{s.id}/toggle", json={"is_active": True}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"]["is_active"] is True

    def test_toggle_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.post(f"{BASE}/99999/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 404

    def test_toggle_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s = make_status(
            db_session, code="AUD_TOG_S", label="Audit Toggle Status", is_terminal=True
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{s.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status", action="toggle", entity_id=s.id)
            .first()
        )
        assert log is not None

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/1/toggle", json={"is_active": False}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /reorder — reordenar estados
# =============================================================================

class TestReorderStatuses:
    def test_reorder_updates_display_order(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.ticket_status import TicketStatus

        s1 = make_status(db_session, code="SORD1", label="Sort1", display_order=1)
        s2 = make_status(db_session, code="SORD2", label="Sort2", display_order=2)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [
                {"id": s1.id, "display_order": 20},
                {"id": s2.id, "display_order": 5},
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        db_session.expire_all()
        assert db_session.get(TicketStatus, s1.id).display_order == 20
        assert db_session.get(TicketStatus, s2.id).display_order == 5

    def test_reorder_missing_display_order_returns_400(self, app_client, db_session, admin_headers):
        s = make_status(db_session, code="SORD_BAD", label="Sort Bad")
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": s.id}]},  # falta display_order
            headers=admin_headers,
        )
        assert r.status_code == 400

    def test_reorder_nonexistent_id_returns_404(self, app_client, admin_headers):
        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": 99999, "display_order": 1}]},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_reorder_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s = make_status(db_session, code="SORD_AUD", label="Sort Audit", display_order=1)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": s.id, "display_order": 50}]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        log = db_session.query(ConfigChangeLog).filter_by(entity_type="status", action="reorder").first()
        assert log is not None


# =============================================================================
# No-create / No-delete — verificar que los métodos no existen
# =============================================================================

class TestNoCreateNoDelete:
    def test_post_create_returns_405_or_422(self, app_client, admin_headers):
        """No existe POST / para crear estado — debe devolver 404 o 405."""
        r = app_client.post(
            BASE,
            json={"code": "NEW_STA", "label": "New", "stage": "created"},
            headers=admin_headers,
        )
        # FastAPI devuelve 405 (Method Not Allowed) si la ruta existe pero no el método,
        # o 422 si hay una ruta parecida que no acepta ese cuerpo.
        # Lo importante: no debe ser 200 ni 201.
        assert r.status_code in (404, 405, 422)

    def test_delete_returns_405_or_404(self, app_client, db_session, admin_headers):
        """No existe DELETE /{id} para estados."""
        s = make_status(db_session, code="NO_DEL_S", label="No Delete")
        db_session.flush()

        r = app_client.delete(f"{BASE}/{s.id}", headers=admin_headers)
        assert r.status_code in (404, 405)

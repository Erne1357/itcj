"""
Tests exhaustivos para /api/help-desk/v2/config/areas

Cubre:
- GET /           lista activas (default) e inactivas
- GET /{id}       200 existente, 404 inexistente
- PATCH /{id}     actualiza label/icon/color/description/display_order; NO permite cambiar code
- POST /{id}/toggle  falla si hay tickets activos del área
- POST /reorder   actualiza display_order
- NO existe POST create ni DELETE — 404/405 esperado
- Cache: invalidate_areas() llamado tras cada write
- Audit: entity_type='area'
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.helpdesk.config.conftest import make_area

BASE = "/api/help-desk/v2/config/areas"


# =============================================================================
# GET / — listar áreas
# =============================================================================

class TestListAreas:
    def test_returns_only_active_by_default(self, app_client, db_session, admin_headers):
        make_area(db_session, code="AREA_ACT", label="Activa", is_active=True)
        make_area(db_session, code="AREA_INA", label="Inactiva", is_active=False)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        codes = [a["code"] for a in r.json()["areas"]]
        assert "AREA_ACT" in codes
        assert "AREA_INA" not in codes

    def test_include_inactive_returns_all(self, app_client, db_session, admin_headers):
        make_area(db_session, code="AREA_I2", label="Inactiva2", is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}?include_inactive=true", headers=admin_headers)
        assert r.status_code == 200
        codes = [a["code"] for a in r.json()["areas"]]
        assert "AREA_I2" in codes

    def test_response_has_areas_and_total(self, app_client, db_session, admin_headers):
        make_area(db_session, code="AREA_SHP", label="Shape")
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "areas" in body
        assert "total" in body

    def test_ordered_by_display_order(self, app_client, db_session, admin_headers):
        make_area(db_session, code="AREA_Z", label="Z Area", display_order=30)
        make_area(db_session, code="AREA_A", label="A Area", display_order=10)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        areas = r.json()["areas"]
        relevant = [a for a in areas if a["code"] in {"AREA_Z", "AREA_A"}]
        orders = [a["display_order"] for a in relevant]
        assert orders == sorted(orders)

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /{id} — detalle de área
# =============================================================================

class TestGetArea:
    def test_existing_returns_200(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="AREA_DET", label="Detail Area")
        db_session.flush()

        r = app_client.get(f"{BASE}/{a.id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["area"]["code"] == "AREA_DET"

    def test_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "not_found"

    def test_response_includes_all_fields(self, app_client, db_session, admin_headers):
        a = make_area(
            db_session,
            code="AREA_FULL",
            label="Full Area",
            icon="fa-laptop",
            color="#green",
            description="Desc",
        )
        db_session.flush()

        r = app_client.get(f"{BASE}/{a.id}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()["area"]
        assert body["icon"] == "fa-laptop"
        assert body["description"] == "Desc"

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PATCH /{id} — actualizar metadata del área
# =============================================================================

class TestUpdateArea:
    def test_update_label_succeeds(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="AREA_LBL", label="Old Label")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{a.id}", json={"label": "New Label"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["area"]["label"] == "New Label"

    def test_update_icon_color_description(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="AREA_VIS", label="Visual Area")
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{a.id}",
            json={"icon": "fa-wrench", "color": "#ff5733", "description": "Updated desc"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()["area"]
        assert body["icon"] == "fa-wrench"
        assert body["color"] == "#ff5733"
        assert body["description"] == "Updated desc"

    def test_code_filtered_by_schema_not_changed(self, app_client, db_session, admin_headers):
        """El schema UpdateAreaRequest no incluye 'code' — Pydantic lo descarta."""
        a = make_area(db_session, code="IMMUT_CODE_A", label="Immutable")
        db_session.flush()
        original_code = a.code

        r = app_client.patch(
            f"{BASE}/{a.id}",
            json={"code": "HACKED_AREA", "label": "Changed"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["area"]["code"] == original_code

    def test_update_display_order(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="AREA_ORD", label="Order Area", display_order=5)
        db_session.flush()

        r = app_client.patch(f"{BASE}/{a.id}", json={"display_order": 99}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["area"]["display_order"] == 99

    def test_update_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.patch(f"{BASE}/99999", json={"label": "NoExist"}, headers=admin_headers)
        assert r.status_code == 404

    def test_update_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        a = make_area(db_session, code="AUD_AREA", label="Audit Area")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{a.id}", json={"label": "Updated"}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="area", action="update", entity_id=a.id)
            .first()
        )
        assert log is not None
        assert log.before_data["label"] == "Audit Area"
        assert log.after_data["label"] == "Updated"

    def test_update_calls_invalidate_areas_cache(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="INV_AREA", label="Inv Area")
        db_session.flush()

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_areas") as mock_inv:
            r = app_client.patch(f"{BASE}/{a.id}", json={"label": "Updated"}, headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.patch(f"{BASE}/1", json={"label": "X"}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /{id}/toggle — activar/desactivar área
# =============================================================================

class TestToggleArea:
    def test_deactivate_with_no_active_tickets_succeeds(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="TOG_AREA_OK", label="Toggle OK", is_active=True)
        db_session.flush()

        r = app_client.post(f"{BASE}/{a.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["area"]["is_active"] is False

    def test_deactivate_with_active_tickets_returns_400(self, app_client, db_session, admin_headers):
        """Área con tickets activos no puede desactivarse."""
        a = make_area(db_session, code="TOG_AREA_T", label="Toggle Tickets", is_active=True)
        db_session.flush()

        from itcj2.apps.helpdesk.models.ticket import Ticket as RealTicket

        mock_q_chain = MagicMock()
        mock_q_chain.filter.return_value = mock_q_chain
        mock_q_chain.count.return_value = 4

        original_query = db_session.query

        def patched_query(cls):
            if cls is RealTicket:
                return mock_q_chain
            return original_query(cls)

        db_session.query = patched_query
        try:
            r = app_client.post(
                f"{BASE}/{a.id}/toggle",
                json={"is_active": False},
                headers=admin_headers,
            )
            assert r.status_code == 400
            assert r.json()["error"]["error"] == "has_active_tickets"
        finally:
            db_session.query = original_query

    def test_activate_inactive_area_succeeds(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="TOG_AREA_ACT", label="Toggle Activate", is_active=False)
        db_session.flush()

        r = app_client.post(f"{BASE}/{a.id}/toggle", json={"is_active": True}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["area"]["is_active"] is True

    def test_toggle_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.post(f"{BASE}/99999/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 404

    def test_toggle_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        a = make_area(db_session, code="AUD_TOG_A", label="Audit Toggle Area", is_active=True)
        db_session.flush()

        r = app_client.post(f"{BASE}/{a.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="area", action="toggle", entity_id=a.id)
            .first()
        )
        assert log is not None
        assert log.before_data["is_active"] is True
        assert log.after_data["is_active"] is False

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/1/toggle", json={"is_active": False}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /reorder — reordenar áreas
# =============================================================================

class TestReorderAreas:
    def test_reorder_updates_display_order(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.area import Area

        a1 = make_area(db_session, code="AORD1", label="AO1", display_order=1)
        a2 = make_area(db_session, code="AORD2", label="AO2", display_order=2)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [
                {"id": a1.id, "display_order": 15},
                {"id": a2.id, "display_order": 3},
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        db_session.expire_all()
        assert db_session.get(Area, a1.id).display_order == 15
        assert db_session.get(Area, a2.id).display_order == 3

    def test_reorder_missing_fields_returns_400(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="AORD_BAD", label="AO Bad")
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": a.id}]},  # falta display_order
            headers=admin_headers,
        )
        assert r.status_code == 400

    def test_reorder_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": 99999, "display_order": 1}]},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_reorder_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        a = make_area(db_session, code="AORD_AUD", label="AO Audit", display_order=1)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": a.id, "display_order": 8}]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        log = db_session.query(ConfigChangeLog).filter_by(entity_type="area", action="reorder").first()
        assert log is not None


# =============================================================================
# No-create / No-delete — verificar que los métodos no existen
# =============================================================================

class TestNoCreateNoDelete:
    def test_post_create_not_allowed(self, app_client, admin_headers):
        r = app_client.post(
            BASE,
            json={"code": "NEW_AREA", "label": "New"},
            headers=admin_headers,
        )
        assert r.status_code in (404, 405, 422)

    def test_delete_not_allowed(self, app_client, db_session, admin_headers):
        a = make_area(db_session, code="NO_DEL_A", label="No Delete")
        db_session.flush()

        r = app_client.delete(f"{BASE}/{a.id}", headers=admin_headers)
        assert r.status_code in (404, 405)

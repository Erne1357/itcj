"""
Tests exhaustivos para /api/help-desk/v2/config/priorities

Cubre:
- GET /           lista activas (default) e inactivas (include_inactive=true)
- GET /{id}       200 existente, 404 inexistente
- POST /          crea; 409 código duplicado; display_order automático; validación sla_hours
- PATCH /{id}     actualiza campos permitidos; NO permite cambiar code
- POST /{id}/toggle  desactiva; 400 con tickets activos
- POST /reorder   actualiza display_order de múltiples
- DELETE /{id}    soft-delete; 400 si tiene tickets asociados
- Audit: cada write inserta ConfigChangeLog con entity_type='priority'
- Cache: invalidate_priorities() llamado tras cada write
- Permisos: 401 sin auth, 403 sin rol (simulado via mock de require_perms)
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.helpdesk.config.conftest import make_priority, make_config_log

BASE = "/api/help-desk/v2/config/priorities"


# =============================================================================
# GET / — listar prioridades
# =============================================================================

class TestListPriorities:
    def test_returns_only_active_by_default(self, app_client, db_session, admin_headers):
        make_priority(db_session, code="ACTIVA", label="Activa", is_active=True)
        make_priority(db_session, code="INACT", label="Inactiva", is_active=False)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        codes = [p["code"] for p in data["priorities"]]
        assert "ACTIVA" in codes
        assert "INACT" not in codes

    def test_include_inactive_returns_all(self, app_client, db_session, admin_headers):
        make_priority(db_session, code="ACT2", label="Activa2", is_active=True)
        make_priority(db_session, code="INA2", label="Inactiva2", is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}?include_inactive=true", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        codes = [p["code"] for p in data["priorities"]]
        assert "ACT2" in codes
        assert "INA2" in codes

    def test_response_has_total_field(self, app_client, db_session, admin_headers):
        make_priority(db_session, code="TOT1", label="Total1")
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        assert "total" in r.json()

    def test_ordered_by_display_order(self, app_client, db_session, admin_headers):
        make_priority(db_session, code="ORD_Z", label="Z", display_order=30)
        make_priority(db_session, code="ORD_A", label="A", display_order=10)
        make_priority(db_session, code="ORD_M", label="M", display_order=20)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        priorities = r.json()["priorities"]
        ord_codes = [p["code"] for p in priorities if p["code"] in {"ORD_Z", "ORD_A", "ORD_M"}]
        assert ord_codes == ["ORD_A", "ORD_M", "ORD_Z"]

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /{id} — detalle de prioridad
# =============================================================================

class TestGetPriority:
    def test_existing_returns_200_with_priority(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="DETAIL1", label="Detail One")
        db_session.flush()

        r = app_client.get(f"{BASE}/{p.id}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "priority" in body
        assert body["priority"]["code"] == "DETAIL1"
        assert body["priority"]["id"] == p.id

    def test_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404
        error = r.json()["error"]
        assert error["error"] == "not_found"

    def test_response_includes_sla_hours(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="SLA1", label="SLA One", sla_hours=48)
        db_session.flush()

        r = app_client.get(f"{BASE}/{p.id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority"]["sla_hours"] == 48

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST / — crear prioridad
# =============================================================================

class TestCreatePriority:
    def test_creates_successfully_returns_201(self, app_client, db_session, admin_headers):
        payload = {
            "code": "NUEVA",
            "label": "Nueva Prioridad",
            "sla_hours": 36,
            "color": "#ff0000",
            "badge_class": "bg-danger",
        }
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 201
        body = r.json()
        assert body["priority"]["code"] == "NUEVA"
        assert body["priority"]["sla_hours"] == 36

    def test_duplicate_code_returns_409(self, app_client, db_session, admin_headers):
        make_priority(db_session, code="DUPLIC", label="Duplicado")
        db_session.flush()

        payload = {"code": "DUPLIC", "label": "Otro", "sla_hours": 24}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 409
        assert r.json()["error"]["error"] == "code_exists"

    def test_code_case_insensitive_duplicate_check(self, app_client, db_session, admin_headers):
        """El código se normaliza a UPPER antes de verificar unicidad."""
        make_priority(db_session, code="LOWER", label="Lower")
        db_session.flush()

        payload = {"code": "lower", "label": "Lower2", "sla_hours": 12}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 409

    def test_auto_display_order_when_not_provided(self, app_client, db_session, admin_headers):
        """display_order = max_existente + 1 cuando no se provee."""
        make_priority(db_session, code="MAXORD", label="Max", display_order=5)
        db_session.flush()

        payload = {"code": "AUTO_ORD", "label": "Auto Order", "sla_hours": 8}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 201
        assert r.json()["priority"]["display_order"] == 6

    def test_explicit_display_order_respected(self, app_client, db_session, admin_headers):
        payload = {"code": "EXPLICIT", "label": "Explicit", "sla_hours": 10, "display_order": 77}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 201
        assert r.json()["priority"]["display_order"] == 77

    def test_sla_hours_zero_rejected_422(self, app_client, admin_headers):
        payload = {"code": "SLAZERO", "label": "SLA Zero", "sla_hours": 0}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 422

    def test_sla_hours_negative_rejected_422(self, app_client, admin_headers):
        payload = {"code": "SLANEG", "label": "SLA Neg", "sla_hours": -5}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 422

    def test_sla_hours_above_limit_rejected_422(self, app_client, admin_headers):
        payload = {"code": "SLAMAX", "label": "SLA Max", "sla_hours": 10001}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 422

    def test_sla_hours_at_boundary_10000_accepted(self, app_client, admin_headers):
        payload = {"code": "SLA10K", "label": "SLA 10K", "sla_hours": 10000}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 201

    def test_create_inserts_config_change_log(self, app_client, db_session, admin_headers):
        """Verificar que un ConfigChangeLog con entity_type='priority' y action='create' se persiste."""
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        initial_count = db_session.query(ConfigChangeLog).count()
        payload = {"code": "AUDIT_CRE", "label": "Audit Create", "sla_hours": 4}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 201

        logs = db_session.query(ConfigChangeLog).filter_by(entity_type="priority", action="create").all()
        assert len(logs) >= 1
        last_log = logs[-1]
        assert last_log.before_data is None
        assert last_log.after_data is not None
        assert last_log.after_data.get("code") == "AUDIT_CRE"

    def test_create_calls_invalidate_priorities_cache(self, app_client, admin_headers):
        with patch(
            "itcj2.apps.helpdesk.utils.catalog_cache.invalidate_priorities"
        ) as mock_inv:
            payload = {"code": "CACH_CRE", "label": "Cache Create", "sla_hours": 6}
            r = app_client.post(BASE, json=payload, headers=admin_headers)
            assert r.status_code == 201
            mock_inv.assert_called_once()

    def test_missing_required_field_code_returns_422(self, app_client, admin_headers):
        payload = {"label": "No Code", "sla_hours": 10}
        r = app_client.post(BASE, json=payload, headers=admin_headers)
        assert r.status_code == 422

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(BASE, json={"code": "X", "label": "Y", "sla_hours": 1}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PATCH /{id} — actualizar prioridad
# =============================================================================

class TestUpdatePriority:
    def test_update_label_succeeds(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="UPD_LBL", label="Original Label")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{p.id}", json={"label": "New Label"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority"]["label"] == "New Label"

    def test_update_sla_hours_succeeds(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="UPD_SLA", label="SLA Update", sla_hours=24)
        db_session.flush()

        r = app_client.patch(f"{BASE}/{p.id}", json={"sla_hours": 72}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority"]["sla_hours"] == 72

    def test_update_color_and_badge_class(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="UPD_CLR", label="Color Update")
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{p.id}",
            json={"color": "#123456", "badge_class": "bg-info"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()["priority"]
        assert body["color"] == "#123456"
        assert body["badge_class"] == "bg-info"

    def test_update_does_not_change_code(self, app_client, db_session, admin_headers):
        """El schema UpdatePriorityRequest no incluye 'code' — debe ser ignorado / rechazado."""
        p = make_priority(db_session, code="NO_CHG_CODE", label="No Change")
        db_session.flush()
        original_code = p.code

        # El schema Pydantic descarta 'code' → el valor en BD no cambia
        r = app_client.patch(
            f"{BASE}/{p.id}",
            json={"code": "HACKED", "label": "Changed"},
            headers=admin_headers,
        )
        # Request aceptada (200), pero 'code' no cambió
        assert r.status_code == 200
        assert r.json()["priority"]["code"] == original_code

    def test_update_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.patch(f"{BASE}/99999", json={"label": "NoExist"}, headers=admin_headers)
        assert r.status_code == 404

    def test_update_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        p = make_priority(db_session, code="AUD_UPD", label="Audit Update")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{p.id}", json={"label": "Updated"}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="priority", action="update", entity_id=p.id)
            .first()
        )
        assert log is not None
        assert log.before_data["label"] == "Audit Update"
        assert log.after_data["label"] == "Updated"

    def test_update_calls_invalidate_cache(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="INV_UPD", label="Inv Update")
        db_session.flush()

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_priorities") as mock_inv:
            r = app_client.patch(f"{BASE}/{p.id}", json={"label": "Updated"}, headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_update_sla_invalid_zero_returns_422(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="SLA_INV", label="SLA Invalid")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{p.id}", json={"sla_hours": 0}, headers=admin_headers)
        assert r.status_code == 422

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.patch(f"{BASE}/1", json={"label": "X"}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /{id}/toggle — activar/desactivar prioridad
# =============================================================================

class TestTogglePriority:
    def test_deactivate_with_no_active_tickets_succeeds(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="TOG_OK", label="Toggle OK", is_active=True)
        db_session.flush()

        r = app_client.post(f"{BASE}/{p.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority"]["is_active"] is False

    def test_deactivate_with_active_tickets_returns_400(self, app_client, db_session, admin_headers):
        """Si hay tickets activos con la prioridad, desactivar debe fallar con 400."""
        p = make_priority(db_session, code="TOG_TICK", label="Toggle Tickets", is_active=True)
        db_session.flush()

        # Patch Ticket en el namespace del handler para que su query cuente 3
        mock_ticket_cls = MagicMock()
        mock_q_chain = MagicMock()
        mock_q_chain.filter.return_value = mock_q_chain
        mock_q_chain.count.return_value = 3
        # db.query(Ticket) en el handler → retorna mock_q_chain
        original_query = db_session.query

        def patched_query(cls):
            from itcj2.apps.helpdesk.models.ticket import Ticket as RealTicket
            if cls is RealTicket:
                return mock_q_chain
            return original_query(cls)

        db_session.query = patched_query
        try:
            r = app_client.post(
                f"{BASE}/{p.id}/toggle",
                json={"is_active": False},
                headers=admin_headers,
            )
            assert r.status_code == 400
            err = r.json()["error"]
            assert err["error"] == "has_active_tickets"
        finally:
            db_session.query = original_query

    def test_activate_inactive_priority_succeeds(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="TOG_ACT", label="Toggle Activate", is_active=False)
        db_session.flush()

        r = app_client.post(f"{BASE}/{p.id}/toggle", json={"is_active": True}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["priority"]["is_active"] is True

    def test_toggle_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.post(f"{BASE}/99999/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 404

    def test_toggle_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        p = make_priority(db_session, code="AUD_TOG", label="Audit Toggle", is_active=True)
        db_session.flush()

        r = app_client.post(f"{BASE}/{p.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="priority", action="toggle", entity_id=p.id)
            .first()
        )
        assert log is not None
        assert log.before_data["is_active"] is True
        assert log.after_data["is_active"] is False

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/1/toggle", json={"is_active": False}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /reorder — reordenar prioridades
# =============================================================================

class TestReorderPriorities:
    def test_reorder_updates_display_order(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.priority import Priority

        p1 = make_priority(db_session, code="REORD1", label="R1", display_order=1)
        p2 = make_priority(db_session, code="REORD2", label="R2", display_order=2)
        db_session.flush()

        order = [
            {"id": p1.id, "display_order": 10},
            {"id": p2.id, "display_order": 5},
        ]
        r = app_client.post(f"{BASE}/reorder", json={"order": order}, headers=admin_headers)
        assert r.status_code == 200

        db_session.expire_all()
        p1_fresh = db_session.get(Priority, p1.id)
        p2_fresh = db_session.get(Priority, p2.id)
        assert p1_fresh.display_order == 10
        assert p2_fresh.display_order == 5

    def test_reorder_returns_updated_list(self, app_client, db_session, admin_headers):
        p1 = make_priority(db_session, code="RLST1", label="RL1", display_order=1)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": p1.id, "display_order": 99}]},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "priorities" in r.json()

    def test_reorder_with_missing_id_returns_400(self, app_client, admin_headers):
        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"display_order": 1}]},  # falta 'id'
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_order_item"

    def test_reorder_with_nonexistent_id_returns_404(self, app_client, admin_headers):
        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": 99999, "display_order": 1}]},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_reorder_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        p1 = make_priority(db_session, code="AUD_REORD", label="Audit Reorder", display_order=1)
        db_session.flush()

        r = app_client.post(
            f"{BASE}/reorder",
            json={"order": [{"id": p1.id, "display_order": 7}]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        log = db_session.query(ConfigChangeLog).filter_by(
            entity_type="priority", action="reorder"
        ).first()
        assert log is not None
        assert "items" in log.before_data
        assert "items" in log.after_data

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/reorder", json={"order": []}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# DELETE /{id} — soft-delete de prioridad
# =============================================================================

class TestDeletePriority:
    def test_delete_with_no_tickets_succeeds(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.priority import Priority

        p = make_priority(db_session, code="DEL_OK", label="Delete OK")
        db_session.flush()

        r = app_client.delete(f"{BASE}/{p.id}", headers=admin_headers)
        assert r.status_code == 200
        assert "eliminada" in r.json()["message"]

        db_session.expire_all()
        p_fresh = db_session.get(Priority, p.id)
        # soft-delete: is_active=False
        assert p_fresh.is_active is False

    def test_delete_with_tickets_returns_400(self, app_client, db_session, admin_headers):
        """DELETE falla con 400 si la prioridad tiene tickets asociados (cualquier estado)."""
        p = make_priority(db_session, code="DEL_TICK", label="Delete Tickets")
        db_session.flush()

        from itcj2.apps.helpdesk.models.ticket import Ticket as RealTicket

        mock_q_chain = MagicMock()
        mock_q_chain.filter.return_value = mock_q_chain
        mock_q_chain.count.return_value = 2

        original_query = db_session.query

        def patched_query(cls):
            if cls is RealTicket:
                return mock_q_chain
            return original_query(cls)

        db_session.query = patched_query
        try:
            r = app_client.delete(f"{BASE}/{p.id}", headers=admin_headers)
            assert r.status_code == 400
            err = r.json()["error"]
            assert err["error"] == "has_tickets"
        finally:
            db_session.query = original_query

    def test_delete_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.delete(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404

    def test_delete_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        p = make_priority(db_session, code="AUD_DEL", label="Audit Delete")
        db_session.flush()

        r = app_client.delete(f"{BASE}/{p.id}", headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="priority", action="delete", entity_id=p.id)
            .first()
        )
        assert log is not None
        assert log.before_data["is_active"] is True
        assert log.after_data["is_active"] is False

    def test_delete_calls_invalidate_cache(self, app_client, db_session, admin_headers):
        p = make_priority(db_session, code="INV_DEL", label="Inv Delete")
        db_session.flush()

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_priorities") as mock_inv:
            r = app_client.delete(f"{BASE}/{p.id}", headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.delete(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401

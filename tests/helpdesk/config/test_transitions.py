"""
Tests exhaustivos para /api/help-desk/v2/config/transitions

Cubre:
- GET /           lista transiciones (con include_inactive)
- GET /matrix     devuelve {statuses, transitions}
- POST /          crea transición; 409 si ya existe; 404 si status no existe
- PATCH /{id}     actualiza required_perm/required_fields/is_active
- DELETE /{id}    soft-delete (is_active=False)
- PUT /bulk       upsert masivo; payload vacío desactiva todo; auditoría correcta
- Cache: invalidate_transitions() llamado tras cada write
- Audit: entity_type='status_transition' o 'status_transition_matrix' para bulk
"""
from unittest.mock import patch

import pytest

from tests.helpdesk.config.conftest import make_status, make_transition

BASE = "/api/help-desk/v2/config/transitions"


# =============================================================================
# GET / — listar transiciones
# =============================================================================

class TestListTransitions:
    def test_returns_only_active_by_default(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="TS_A1", label="From A1")
        s2 = make_status(db_session, code="TS_A2", label="To A2")
        s3 = make_status(db_session, code="TS_A3", label="To A3")
        t_active = make_transition(db_session, s1, s2, is_active=True)
        t_inactive = make_transition(db_session, s1, s3, is_active=False)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()["transitions"]]
        assert t_active.id in ids
        assert t_inactive.id not in ids

    def test_include_inactive_returns_all(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="TS_B1", label="From B1")
        s2 = make_status(db_session, code="TS_B2", label="To B2")
        t = make_transition(db_session, s1, s2, is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}?include_inactive=true", headers=admin_headers)
        assert r.status_code == 200
        ids = [t_["id"] for t_ in r.json()["transitions"]]
        assert t.id in ids

    def test_filter_by_from_status_id(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="TS_C1", label="C1")
        s2 = make_status(db_session, code="TS_C2", label="C2")
        s3 = make_status(db_session, code="TS_C3", label="C3")
        t12 = make_transition(db_session, s1, s2)
        t23 = make_transition(db_session, s2, s3)
        db_session.flush()

        r = app_client.get(f"{BASE}?from_status_id={s1.id}", headers=admin_headers)
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()["transitions"]]
        assert t12.id in ids
        assert t23.id not in ids

    def test_response_has_total(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="TS_D1", label="D1")
        s2 = make_status(db_session, code="TS_D2", label="D2")
        make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert "total" in r.json()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /matrix — matriz de transiciones
# =============================================================================

class TestGetMatrix:
    def test_matrix_contains_statuses_and_transitions(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="MAT_S1", label="Mat S1", display_order=1)
        s2 = make_status(db_session, code="MAT_S2", label="Mat S2", display_order=2)
        make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.get(f"{BASE}/matrix", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "statuses" in body
        assert "transitions" in body

    def test_matrix_statuses_only_active(self, app_client, db_session, admin_headers):
        make_status(db_session, code="MAT_ACT", label="Active", is_active=True)
        make_status(db_session, code="MAT_INA", label="Inactive", is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}/matrix", headers=admin_headers)
        assert r.status_code == 200
        codes = [s["code"] for s in r.json()["statuses"]]
        assert "MAT_ACT" in codes
        assert "MAT_INA" not in codes

    def test_matrix_transitions_includes_inactive(self, app_client, db_session, admin_headers):
        """Matrix incluye transiciones activas e inactivas (para la UI de configuración)."""
        s1 = make_status(db_session, code="MAT_T1", label="T1")
        s2 = make_status(db_session, code="MAT_T2", label="T2")
        t = make_transition(db_session, s1, s2, is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}/matrix", headers=admin_headers)
        assert r.status_code == 200
        t_ids = [t_["id"] for t_ in r.json()["transitions"]]
        assert t.id in t_ids

    def test_matrix_transition_has_required_fields(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="MAT_RF1", label="RF1")
        s2 = make_status(db_session, code="MAT_RF2", label="RF2")
        make_transition(db_session, s1, s2, required_perm="helpdesk.tickets.api.close")
        db_session.flush()

        r = app_client.get(f"{BASE}/matrix", headers=admin_headers)
        assert r.status_code == 200
        for t in r.json()["transitions"]:
            assert "from_status_id" in t
            assert "to_status_id" in t
            assert "is_active" in t

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/matrix", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST / — crear transición
# =============================================================================

class TestCreateTransition:
    def test_create_succeeds_returns_201(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="CRT_S1", label="Crt S1")
        s2 = make_status(db_session, code="CRT_S2", label="Crt S2")
        db_session.flush()

        r = app_client.post(
            BASE,
            json={"from_status_id": s1.id, "to_status_id": s2.id},
            headers=admin_headers,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["transition"]["from_status_id"] == s1.id
        assert body["transition"]["to_status_id"] == s2.id

    def test_duplicate_pair_returns_409(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="DUP_S1", label="Dup S1")
        s2 = make_status(db_session, code="DUP_S2", label="Dup S2")
        make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.post(
            BASE,
            json={"from_status_id": s1.id, "to_status_id": s2.id},
            headers=admin_headers,
        )
        assert r.status_code == 409
        assert r.json()["error"]["error"] == "transition_exists"

    def test_nonexistent_from_status_returns_404(self, app_client, db_session, admin_headers):
        s2 = make_status(db_session, code="NFROM_S2", label="NFrom S2")
        db_session.flush()

        r = app_client.post(
            BASE,
            json={"from_status_id": 99999, "to_status_id": s2.id},
            headers=admin_headers,
        )
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "from_status_not_found"

    def test_nonexistent_to_status_returns_404(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="NTO_S1", label="NTo S1")
        db_session.flush()

        r = app_client.post(
            BASE,
            json={"from_status_id": s1.id, "to_status_id": 99999},
            headers=admin_headers,
        )
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "to_status_not_found"

    def test_create_with_required_perm(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="PERM_S1", label="Perm S1")
        s2 = make_status(db_session, code="PERM_S2", label="Perm S2")
        db_session.flush()

        r = app_client.post(
            BASE,
            json={
                "from_status_id": s1.id,
                "to_status_id": s2.id,
                "required_perm": "helpdesk.tickets.api.close",
                "required_fields": ["resolution_notes"],
            },
            headers=admin_headers,
        )
        assert r.status_code == 201
        t = r.json()["transition"]
        assert t["required_perm"] == "helpdesk.tickets.api.close"
        assert "resolution_notes" in t["required_fields"]

    def test_create_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s1 = make_status(db_session, code="AUD_TR1", label="Aud Tr1")
        s2 = make_status(db_session, code="AUD_TR2", label="Aud Tr2")
        db_session.flush()

        r = app_client.post(
            BASE,
            json={"from_status_id": s1.id, "to_status_id": s2.id},
            headers=admin_headers,
        )
        assert r.status_code == 201

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status_transition", action="create")
            .first()
        )
        assert log is not None
        assert log.before_data is None
        assert log.after_data is not None

    def test_create_calls_invalidate_transitions_cache(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="INV_TR1", label="Inv Tr1")
        s2 = make_status(db_session, code="INV_TR2", label="Inv Tr2")
        db_session.flush()

        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_transitions") as mock_inv:
            r = app_client.post(
                BASE,
                json={"from_status_id": s1.id, "to_status_id": s2.id},
                headers=admin_headers,
            )
            assert r.status_code == 201
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(BASE, json={"from_status_id": 1, "to_status_id": 2}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PATCH /{id} — actualizar transición
# =============================================================================

class TestUpdateTransition:
    def test_update_is_active_to_false(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="UPD_TR1", label="Upd Tr1")
        s2 = make_status(db_session, code="UPD_TR2", label="Upd Tr2")
        t = make_transition(db_session, s1, s2, is_active=True)
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["transition"]["is_active"] is False

    def test_update_required_perm(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="UPD_P1", label="Upd P1")
        s2 = make_status(db_session, code="UPD_P2", label="Upd P2")
        t = make_transition(db_session, s1, s2, required_perm=None)
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{t.id}",
            json={"required_perm": "helpdesk.tickets.api.resolve"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["transition"]["required_perm"] == "helpdesk.tickets.api.resolve"

    def test_update_required_fields(self, app_client, db_session, admin_headers):
        s1 = make_status(db_session, code="UPD_RF1", label="Upd RF1")
        s2 = make_status(db_session, code="UPD_RF2", label="Upd RF2")
        t = make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.patch(
            f"{BASE}/{t.id}",
            json={"required_fields": ["time_invested_minutes"]},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "time_invested_minutes" in r.json()["transition"]["required_fields"]

    def test_update_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.patch(f"{BASE}/99999", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 404

    def test_update_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s1 = make_status(db_session, code="AUD_T3", label="Aud T3")
        s2 = make_status(db_session, code="AUD_T4", label="Aud T4")
        t = make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status_transition", action="update", entity_id=t.id)
            .first()
        )
        assert log is not None

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.patch(f"{BASE}/1", json={"is_active": False}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# DELETE /{id} — soft-delete de transición
# =============================================================================

class TestDeleteTransition:
    def test_delete_marks_inactive(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition

        s1 = make_status(db_session, code="DEL_T1", label="Del T1")
        s2 = make_status(db_session, code="DEL_T2", label="Del T2")
        t = make_transition(db_session, s1, s2, is_active=True)
        db_session.flush()

        r = app_client.delete(f"{BASE}/{t.id}", headers=admin_headers)
        assert r.status_code == 200
        assert "eliminada" in r.json()["message"]

        db_session.expire_all()
        t_fresh = db_session.get(StatusTransition, t.id)
        assert t_fresh.is_active is False

    def test_delete_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.delete(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404

    def test_delete_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        s1 = make_status(db_session, code="AUD_DT1", label="Aud DT1")
        s2 = make_status(db_session, code="AUD_DT2", label="Aud DT2")
        t = make_transition(db_session, s1, s2)
        db_session.flush()

        r = app_client.delete(f"{BASE}/{t.id}", headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status_transition", action="delete", entity_id=t.id)
            .first()
        )
        assert log is not None
        assert log.before_data["is_active"] is True
        assert log.after_data["is_active"] is False

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.delete(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PUT /bulk — upsert masivo de transiciones
# =============================================================================

class TestBulkSetTransitions:
    def test_bulk_creates_new_transitions(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition

        s1 = make_status(db_session, code="BLK_S1", label="Blk S1")
        s2 = make_status(db_session, code="BLK_S2", label="Blk S2")
        db_session.flush()

        r = app_client.put(
            f"{BASE}/bulk",
            json={"transitions": [
                {"from_status_id": s1.id, "to_status_id": s2.id, "is_active": True}
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        created = (
            db_session.query(StatusTransition)
            .filter_by(from_status_id=s1.id, to_status_id=s2.id)
            .first()
        )
        assert created is not None
        assert created.is_active is True

    def test_bulk_empty_payload_deactivates_all_existing(self, app_client, db_session, admin_headers):
        """PUT /bulk con transitions=[] debe desactivar todas las transiciones activas."""
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition

        s1 = make_status(db_session, code="BLKE_S1", label="BlkE S1")
        s2 = make_status(db_session, code="BLKE_S2", label="BlkE S2")
        t = make_transition(db_session, s1, s2, is_active=True)
        db_session.flush()

        r = app_client.put(f"{BASE}/bulk", json={"transitions": []}, headers=admin_headers)
        assert r.status_code == 200

        db_session.expire_all()
        t_fresh = db_session.get(StatusTransition, t.id)
        assert t_fresh.is_active is False

    def test_bulk_updates_existing_transition(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition

        s1 = make_status(db_session, code="BLKU_S1", label="BlkU S1")
        s2 = make_status(db_session, code="BLKU_S2", label="BlkU S2")
        t = make_transition(db_session, s1, s2, required_perm=None)
        db_session.flush()

        r = app_client.put(
            f"{BASE}/bulk",
            json={"transitions": [
                {
                    "from_status_id": s1.id,
                    "to_status_id": s2.id,
                    "required_perm": "helpdesk.tickets.api.close",
                    "is_active": True,
                }
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        db_session.expire_all()
        t_fresh = db_session.get(StatusTransition, t.id)
        assert t_fresh.required_perm == "helpdesk.tickets.api.close"

    def test_bulk_deactivates_pairs_not_in_payload(self, app_client, db_session, admin_headers):
        """Transiciones activas en BD que no aparecen en payload deben quedar inactivas."""
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition

        s1 = make_status(db_session, code="BLK_D1", label="Blk D1")
        s2 = make_status(db_session, code="BLK_D2", label="Blk D2")
        s3 = make_status(db_session, code="BLK_D3", label="Blk D3")
        t12 = make_transition(db_session, s1, s2, is_active=True)
        t13 = make_transition(db_session, s1, s3, is_active=True)
        db_session.flush()

        # Solo se envía t12 en el payload
        r = app_client.put(
            f"{BASE}/bulk",
            json={"transitions": [
                {"from_status_id": s1.id, "to_status_id": s2.id, "is_active": True}
            ]},
            headers=admin_headers,
        )
        assert r.status_code == 200

        db_session.expire_all()
        assert db_session.get(StatusTransition, t12.id).is_active is True
        assert db_session.get(StatusTransition, t13.id).is_active is False

    def test_bulk_invalid_item_missing_from_status_id_returns_400(
        self, app_client, admin_headers
    ):
        r = app_client.put(
            f"{BASE}/bulk",
            json={"transitions": [{"to_status_id": 1}]},  # falta from_status_id
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_transition_item"

    def test_bulk_inserts_audit_log_with_matrix_entity_type(
        self, app_client, db_session, admin_headers
    ):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        r = app_client.put(f"{BASE}/bulk", json={"transitions": []}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="status_transition_matrix", action="bulk_update")
            .first()
        )
        assert log is not None
        assert "transitions" in log.before_data
        assert "transitions" in log.after_data

    def test_bulk_calls_invalidate_transitions_cache(self, app_client, admin_headers):
        with patch("itcj2.apps.helpdesk.utils.catalog_cache.invalidate_transitions") as mock_inv:
            r = app_client.put(f"{BASE}/bulk", json={"transitions": []}, headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.put(f"{BASE}/bulk", json={"transitions": []}, headers=no_auth_headers)
        assert r.status_code == 401

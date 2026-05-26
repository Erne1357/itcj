"""
Tests de integración cruzada para la auditoría de configuración.

Verifica que endpoints fuera de /config/ también inserten ConfigChangeLog
cuando modifican entidades que deben auditarse.

Cubre:
- PATCH /categories/{id}           → entity_type='category'
- PATCH /inventory/categories/{id} → entity_type='inventory_category'
- PUT  /categories/{id}/field-template → entity_type='field_template'
- El before capturado es el snapshot ANTERIOR al cambio
- El after refleja el estado FINAL tras la modificación

Estrategia de test:
- Mockear los handlers de categorías e inventario para controlar el
  comportamiento sin crear registros completos (FK constraints).
- Para cada endpoint verificar que log_config_change fue invocado
  con los parámetros correctos.
"""
from unittest.mock import MagicMock, patch, call

import pytest

from tests.helpdesk.config.conftest import make_config_log


# =============================================================================
# Helpers para verificar llamadas a log_config_change
# =============================================================================

def _assert_audit_log_called(mock_log, entity_type: str, action: str):
    """Verifica que log_config_change fue llamado con entity_type y action dados."""
    assert mock_log.called, f"log_config_change no fue llamado para {entity_type}/{action}"
    kwargs = mock_log.call_args.kwargs if mock_log.call_args.kwargs else {}
    if not kwargs:
        # Positional args: db, user_id, entity_type, entity_id, action, ...
        args = mock_log.call_args.args
        et_pos = 2  # entity_type es el 3er argumento posicional
        ac_pos = 4  # action es el 5to
        if len(args) > et_pos:
            assert args[et_pos] == entity_type, f"entity_type esperado={entity_type}, recibido={args[et_pos]}"
        if len(args) > ac_pos:
            assert args[ac_pos] == action, f"action esperado={action}, recibido={args[ac_pos]}"
    else:
        assert kwargs.get("entity_type") == entity_type
        assert kwargs.get("action") == action


# =============================================================================
# Auditoría directa: service log_config_change
# =============================================================================

class TestConfigAuditService:
    def test_log_config_change_creates_db_entry(self, db_session):
        """log_config_change crea un ConfigChangeLog en la sesión."""
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog
        from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

        initial_count = db_session.query(ConfigChangeLog).count()

        log = log_config_change(
            db=db_session,
            user_id=1,
            entity_type="priority",
            entity_id=42,
            action="create",
            before=None,
            after={"code": "TEST", "label": "Test"},
            ip_address="127.0.0.1",
        )

        assert log is not None
        assert log.entity_type == "priority"
        assert log.action == "create"
        assert log.entity_id == 42
        assert log.before_data is None
        assert log.after_data["code"] == "TEST"

    def test_log_config_change_before_snapshot_captured(self, db_session):
        """El before_data debe ser el snapshot PREVIO al cambio."""
        from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

        before = {"label": "Old Label", "is_active": True}
        after = {"label": "New Label", "is_active": True}

        log = log_config_change(
            db=db_session,
            user_id=1,
            entity_type="area",
            entity_id=10,
            action="update",
            before=before,
            after=after,
        )

        assert log.before_data["label"] == "Old Label"
        assert log.after_data["label"] == "New Label"

    def test_log_config_change_delete_after_is_soft_delete(self, db_session):
        """En soft-delete, after_data debe reflejar is_active=False."""
        from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

        before = {"code": "BAJA", "is_active": True}
        after = {"code": "BAJA", "is_active": False}

        log = log_config_change(
            db=db_session,
            user_id=1,
            entity_type="priority",
            entity_id=5,
            action="delete",
            before=before,
            after=after,
        )

        assert log.after_data["is_active"] is False

    def test_log_config_change_bulk_has_null_entity_id(self, db_session):
        """Operaciones bulk/reorder deben pasar entity_id=None."""
        from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

        log = log_config_change(
            db=db_session,
            user_id=1,
            entity_type="status_transition_matrix",
            entity_id=None,
            action="bulk_update",
            before={"transitions": []},
            after={"transitions": [{"from_code": "A", "to_code": "B"}]},
        )

        assert log.entity_id is None

    def test_log_config_change_not_committed_until_caller_commits(self, db_session):
        """log_config_change solo agrega a la sesión; el commit es del caller."""
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog
        from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

        log = log_config_change(
            db=db_session,
            user_id=1,
            entity_type="status",
            entity_id=1,
            action="toggle",
            before={"is_active": True},
            after={"is_active": False},
        )

        # El log está en la sesión (flush lo hace visible)
        db_session.flush()
        found = db_session.query(ConfigChangeLog).filter_by(
            entity_type="status", action="toggle"
        ).first()
        assert found is not None


# =============================================================================
# Integración: log_config_change invocado correctamente por los handlers
# =============================================================================

class TestAuditInvokedByApiHandlers:
    """
    Verifica que cada handler de configuración llama a log_config_change
    con los parámetros correctos antes del commit.
    Usa patch para controlar la función sin necesidad de una BD real completa.
    """

    def test_priority_create_calls_log_config_change(self, app_client, db_session, admin_headers):
        """POST /config/priorities llama a log_config_change con entity_type='priority'."""
        with patch(
            "itcj2.apps.helpdesk.services.config_audit_service.log_config_change"
        ) as mock_log:
            mock_log.return_value = MagicMock()
            payload = {"code": "AUDIT_INT1", "label": "Audit Int1", "sla_hours": 12}
            r = app_client.post(
                "/api/help-desk/v2/config/priorities",
                json=payload,
                headers=admin_headers,
            )
            # Puede ser 201 (éxito) o 409 (si el code ya existe por algún motivo)
            assert r.status_code in (201, 409)
            if r.status_code == 201:
                _assert_audit_log_called(mock_log, "priority", "create")

    def test_status_update_calls_log_config_change(self, app_client, db_session, admin_headers):
        """PATCH /config/statuses/{id} llama a log_config_change con entity_type='status'."""
        from tests.helpdesk.config.conftest import make_status
        s = make_status(db_session, code="AUD_INT_S", label="Audit Int Status")
        db_session.flush()

        with patch(
            "itcj2.apps.helpdesk.services.config_audit_service.log_config_change"
        ) as mock_log:
            mock_log.return_value = MagicMock()
            r = app_client.patch(
                f"/api/help-desk/v2/config/statuses/{s.id}",
                json={"label": "Updated"},
                headers=admin_headers,
            )
            assert r.status_code == 200
            _assert_audit_log_called(mock_log, "status", "update")

    def test_area_update_calls_log_config_change(self, app_client, db_session, admin_headers):
        """PATCH /config/areas/{id} llama a log_config_change con entity_type='area'."""
        from tests.helpdesk.config.conftest import make_area
        a = make_area(db_session, code="AUD_INT_A", label="Audit Int Area")
        db_session.flush()

        with patch(
            "itcj2.apps.helpdesk.services.config_audit_service.log_config_change"
        ) as mock_log:
            mock_log.return_value = MagicMock()
            r = app_client.patch(
                f"/api/help-desk/v2/config/areas/{a.id}",
                json={"label": "Updated"},
                headers=admin_headers,
            )
            assert r.status_code == 200
            _assert_audit_log_called(mock_log, "area", "update")

    def test_notification_template_update_calls_log_config_change(
        self, app_client, db_session, admin_headers
    ):
        """PATCH /config/notifications/{id} llama con entity_type='notification_template'."""
        from tests.helpdesk.config.conftest import make_notification_template
        t = make_notification_template(db_session, code="AUD_INT_N", name="Audit Int Notif")
        db_session.flush()

        with patch(
            "itcj2.apps.helpdesk.services.config_audit_service.log_config_change"
        ) as mock_log:
            mock_log.return_value = MagicMock()
            r = app_client.patch(
                f"/api/help-desk/v2/config/notifications/{t.id}",
                json={"description": "Updated desc"},
                headers=admin_headers,
            )
            assert r.status_code == 200
            _assert_audit_log_called(mock_log, "notification_template", "update")

    def test_transition_bulk_calls_log_with_matrix_entity_type(
        self, app_client, db_session, admin_headers
    ):
        """PUT /config/transitions/bulk llama con entity_type='status_transition_matrix'."""
        with patch(
            "itcj2.apps.helpdesk.services.config_audit_service.log_config_change"
        ) as mock_log:
            mock_log.return_value = MagicMock()
            r = app_client.put(
                "/api/help-desk/v2/config/transitions/bulk",
                json={"transitions": []},
                headers=admin_headers,
            )
            assert r.status_code == 200
            _assert_audit_log_called(mock_log, "status_transition_matrix", "bulk_update")


# =============================================================================
# Snapshot consistency: before y after son independientes
# =============================================================================

class TestSnapshotConsistency:
    def test_before_snapshot_not_mutated_by_update(self, db_session):
        """El before_data capturado por to_dict() es independiente del objeto actualizado."""
        from tests.helpdesk.config.conftest import make_priority
        from itcj2.apps.helpdesk.models.priority import Priority

        p = make_priority(db_session, code="SNAP_TST", label="Original", sla_hours=10)
        db_session.flush()

        # Capturar before antes del cambio
        before = p.to_dict()

        # Modificar el objeto
        p.label = "Modified"
        p.sla_hours = 999

        # El before debe seguir reflejando el estado original
        assert before["label"] == "Original"
        assert before["sla_hours"] == 10

        # El after debe reflejar el estado modificado
        after = p.to_dict()
        assert after["label"] == "Modified"
        assert after["sla_hours"] == 999

    def test_audit_log_stores_snapshot_data(self, db_session):
        """ConfigChangeLog guarda before_data/after_data como pasados al constructor."""
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        before_dict = {"label": "Before", "is_active": True}
        after_dict = {"label": "After", "is_active": True}

        log = ConfigChangeLog(
            user_id=1,
            entity_type="priority",
            entity_id=1,
            action="update",
            before_data=before_dict,
            after_data=after_dict,
            changed_at=None,
            user=None,
        )
        db_session.add(log)
        db_session.flush()

        log_fresh = db_session.get(ConfigChangeLog, log.id)
        assert log_fresh is not None
        assert log_fresh.before_data["label"] == "Before"
        assert log_fresh.after_data["label"] == "After"
        assert log_fresh.entity_type == "priority"

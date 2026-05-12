"""
Tests exhaustivos para /api/help-desk/v2/config/notifications

Cubre:
- GET /           lista activas (default) e inactivas
- GET /{id}       200 existente, 404 inexistente
- PATCH /{id}     actualiza description/channel/subject_template/body_template
- PATCH /{id}     Jinja inválido en body_template → 400 con error='invalid_template_syntax'
- PATCH /{id}     Jinja inválido en subject_template → 400
- POST /{id}/toggle
- POST /{id}/preview sin payload → renderiza con dummy context
- POST /{id}/preview con sample_data custom → renderiza con ese context
- POST /{id}/preview con variables no definidas → warning, no falla
- NO existe POST create ni DELETE
- Audit: entity_type='notification_template'
- Cache: invalidate_notification_templates() llamado
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.helpdesk.config.conftest import make_notification_template

BASE = "/api/help-desk/v2/config/notifications"


# =============================================================================
# GET / — listar plantillas de notificación
# =============================================================================

class TestListNotificationTemplates:
    def test_returns_only_active_by_default(self, app_client, db_session, admin_headers):
        make_notification_template(db_session, code="NOTIF_ACT", name="Active", is_active=True)
        make_notification_template(db_session, code="NOTIF_INA", name="Inactive", is_active=False)
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        codes = [t["code"] for t in r.json()["templates"]]
        assert "NOTIF_ACT" in codes
        assert "NOTIF_INA" not in codes

    def test_include_inactive_returns_all(self, app_client, db_session, admin_headers):
        make_notification_template(db_session, code="NOTIF_I2", name="Inactive2", is_active=False)
        db_session.flush()

        r = app_client.get(f"{BASE}?include_inactive=true", headers=admin_headers)
        assert r.status_code == 200
        codes = [t["code"] for t in r.json()["templates"]]
        assert "NOTIF_I2" in codes

    def test_response_has_templates_and_total(self, app_client, db_session, admin_headers):
        make_notification_template(db_session, code="NOTIF_SHP", name="Shape")
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "templates" in body
        assert "total" in body

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /{id} — detalle de plantilla
# =============================================================================

class TestGetNotificationTemplate:
    def test_existing_returns_200_with_template(self, app_client, db_session, admin_headers):
        t = make_notification_template(db_session, code="NOTIF_DET", name="Detail Template")
        db_session.flush()

        r = app_client.get(f"{BASE}/{t.id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["code"] == "NOTIF_DET"

    def test_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "not_found"

    def test_response_includes_body_template(self, app_client, db_session, admin_headers):
        t = make_notification_template(
            db_session,
            code="NOTIF_BODY",
            name="Body Template",
            body_template="Hello {{ name }}",
        )
        db_session.flush()

        r = app_client.get(f"{BASE}/{t.id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["body_template"] == "Hello {{ name }}"

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# PATCH /{id} — actualizar plantilla
# =============================================================================

class TestUpdateNotificationTemplate:
    def test_update_description_succeeds(self, app_client, db_session, admin_headers):
        t = make_notification_template(
            db_session, code="NOTIF_UPD", name="Upd Template", description="Old desc"
        )
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"description": "New desc"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["description"] == "New desc"

    def test_update_channel_to_email_succeeds(self, app_client, db_session, admin_headers):
        t = make_notification_template(db_session, code="NOTIF_CH", name="Channel", channel="inapp")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"channel": "email"}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["channel"] == "email"

    def test_update_channel_invalid_value_returns_422(self, app_client, db_session, admin_headers):
        t = make_notification_template(db_session, code="NOTIF_CH2", name="Channel2")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"channel": "sms"}, headers=admin_headers)
        assert r.status_code == 422

    def test_update_valid_body_template_succeeds(self, app_client, db_session, admin_headers):
        t = make_notification_template(db_session, code="NOTIF_VBT", name="Valid Body")
        db_session.flush()

        new_body = "Ticket {{ ticket.title }} updated by {{ requester.name }}"
        r = app_client.patch(f"{BASE}/{t.id}", json={"body_template": new_body}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["body_template"] == new_body

    def test_update_invalid_jinja_body_returns_400(self, app_client, db_session, admin_headers):
        """Jinja2 con sintaxis rota en body_template → 400 con error='invalid_template_syntax'."""
        t = make_notification_template(db_session, code="NOTIF_IJ", name="Invalid Jinja")
        db_session.flush()

        # Jinja sintaxis inválida: block sin cierre
        invalid_body = "{% for x in items %} {{ x.name }}"  # falta {% endfor %}
        r = app_client.patch(f"{BASE}/{t.id}", json={"body_template": invalid_body}, headers=admin_headers)
        assert r.status_code == 400
        err = r.json()["error"]
        assert err["error"] == "invalid_template_syntax"

    def test_update_invalid_jinja_subject_returns_400(self, app_client, db_session, admin_headers):
        """Jinja2 con sintaxis rota en subject_template → 400."""
        t = make_notification_template(
            db_session, code="NOTIF_ISJ", name="Invalid Subject Jinja"
        )
        db_session.flush()

        invalid_subject = "{% if x %} {{ x"  # sin cierre
        r = app_client.patch(
            f"{BASE}/{t.id}",
            json={"subject_template": invalid_subject},
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_template_syntax"

    def test_update_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.patch(f"{BASE}/99999", json={"description": "X"}, headers=admin_headers)
        assert r.status_code == 404

    def test_update_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        t = make_notification_template(db_session, code="AUD_NOTIF", name="Audit Notif")
        db_session.flush()

        r = app_client.patch(f"{BASE}/{t.id}", json={"description": "New"}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="notification_template", action="update", entity_id=t.id)
            .first()
        )
        assert log is not None

    def test_update_calls_invalidate_notification_templates_cache(
        self, app_client, db_session, admin_headers
    ):
        t = make_notification_template(db_session, code="INV_NOTIF", name="Inv Notif")
        db_session.flush()

        with patch(
            "itcj2.apps.helpdesk.utils.catalog_cache.invalidate_notification_templates"
        ) as mock_inv:
            r = app_client.patch(f"{BASE}/{t.id}", json={"description": "X"}, headers=admin_headers)
            assert r.status_code == 200
            mock_inv.assert_called_once()

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.patch(f"{BASE}/1", json={"description": "X"}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /{id}/toggle — activar/desactivar plantilla
# =============================================================================

class TestToggleNotificationTemplate:
    def test_deactivate_succeeds(self, app_client, db_session, admin_headers):
        t = make_notification_template(
            db_session, code="TOG_NOTIF", name="Toggle Notif", is_active=True
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["is_active"] is False

    def test_activate_succeeds(self, app_client, db_session, admin_headers):
        t = make_notification_template(
            db_session, code="TOG_ACT_N", name="Toggle Activate Notif", is_active=False
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/toggle", json={"is_active": True}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["template"]["is_active"] is True

    def test_toggle_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.post(f"{BASE}/99999/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 404

    def test_toggle_inserts_audit_log(self, app_client, db_session, admin_headers):
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        t = make_notification_template(
            db_session, code="AUD_TOG_N", name="Audit Toggle Notif", is_active=True
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/toggle", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200

        log = (
            db_session.query(ConfigChangeLog)
            .filter_by(entity_type="notification_template", action="toggle", entity_id=t.id)
            .first()
        )
        assert log is not None

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/1/toggle", json={"is_active": False}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# POST /{id}/preview — previsualizar plantilla
# =============================================================================

class TestPreviewNotificationTemplate:
    def test_preview_without_payload_uses_dummy_context(self, app_client, db_session, admin_headers):
        """Sin payload → renderiza con el contexto dummy interno."""
        t = make_notification_template(
            db_session,
            code="PREV_DUMMY",
            name="Preview Dummy",
            body_template="Ticket: {{ ticket.ticket_number }}",
            subject_template="Subject: {{ ticket.title }}",
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        # El dummy context tiene ticket_number = "HD-2026-00042"
        assert "HD-2026-00042" in body["body"]
        assert "subject" in body
        assert "warnings" in body
        assert isinstance(body["warnings"], list)

    def test_preview_with_sample_data_renders_custom_context(
        self, app_client, db_session, admin_headers
    ):
        """sample_data sobreescribe el contexto de renderizado.
        Se usa subject_template=None para evitar conflicto con variables de ticket
        en el contexto personalizado (BUG: DebugUndefined lanza en acceso a atributo).
        """
        t = make_notification_template(
            db_session,
            code="PREV_SAMP",
            name="Preview Sample",
            body_template="Hello {{ user.name }}",
            subject_template=None,  # Sin subject para evitar bug DebugUndefined
        )
        db_session.flush()

        r = app_client.post(
            f"{BASE}/{t.id}/preview",
            json={"sample_data": {"user": {"name": "Juan"}}},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert "Juan" in r.json()["body"]

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG EN PRODUCCIÓN: jinja2.DebugUndefined lanza UndefinedError "
            "en acceso de atributo ({{ undefined_var.some_field }}) en lugar de "
            "renderizar el placeholder. Debería devolver 200 con warning."
        ),
    )
    def test_preview_undefined_variables_warns_not_fails(
        self, app_client, db_session, admin_headers
    ):
        """Variables no definidas en el contexto producen warning, no excepción.
        ACTUALMENTE FALLA: DebugUndefined lanza UndefinedError en lugar de renderizar.
        """
        t = make_notification_template(
            db_session,
            code="PREV_UNDEF",
            name="Preview Undefined",
            body_template="{{ undefined_var.some_field }} text",
            subject_template=None,
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        body_json = r.json()
        # Debe haber al menos un warning
        assert len(body_json["warnings"]) >= 1
        # El cuerpo renderizado debe contener el placeholder sin resolver (DebugUndefined)
        assert "{{" in body_json["body"]

    def test_preview_nonexistent_template_returns_404(self, app_client, admin_headers):
        r = app_client.post(f"{BASE}/99999/preview", json={}, headers=admin_headers)
        assert r.status_code == 404

    def test_preview_returns_channel(self, app_client, db_session, admin_headers):
        t = make_notification_template(
            db_session, code="PREV_CH", name="Preview Channel", channel="email"
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["channel"] == "email"

    def test_preview_with_no_subject_template(self, app_client, db_session, admin_headers):
        """Plantillas sin subject_template deben devolver subject=None sin error."""
        t = make_notification_template(
            db_session,
            code="PREV_NOSUB",
            name="Preview No Subject",
            subject_template=None,
            body_template="Body only {{ ticket.status }}",
        )
        db_session.flush()

        r = app_client.post(f"{BASE}/{t.id}/preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["subject"] is None

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.post(f"{BASE}/1/preview", json={}, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# No-create / No-delete — verificar que los métodos no existen
# =============================================================================

class TestNoCreateNoDelete:
    def test_post_create_not_allowed(self, app_client, admin_headers):
        r = app_client.post(
            BASE,
            json={"code": "NEW_NOTIF", "name": "New Template", "body_template": "X"},
            headers=admin_headers,
        )
        assert r.status_code in (404, 405, 422)

    def test_delete_not_allowed(self, app_client, db_session, admin_headers):
        t = make_notification_template(db_session, code="NO_DEL_N", name="No Delete")
        db_session.flush()

        r = app_client.delete(f"{BASE}/{t.id}", headers=admin_headers)
        assert r.status_code in (404, 405)

"""
Tests exhaustivos para /api/help-desk/v2/config/audit

Cubre:
- GET /            lista paginada; filtros (entity_type, action, user_id, date_from, date_to)
- GET /{id}        detalle con before_data y after_data
- GET /export.csv  CSV con BOM UTF-8; headers correctos
- GET /export.csv  > 50,000 filas → 400 con error='too_many_rows'
- Permisos: 401 sin auth
- Filtros de fecha inválidos → 400
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tests.helpdesk.config.conftest import make_config_log

BASE = "/api/help-desk/v2/config/audit"


# =============================================================================
# GET / — lista paginada de logs de auditoría
# =============================================================================

class TestListAuditLogs:
    def test_returns_paginated_list(self, app_client, db_session, admin_headers):
        for i in range(5):
            make_config_log(db_session, entity_type="priority", action="create")
        db_session.flush()

        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "logs" in body
        assert "total" in body
        assert "page" in body
        assert "per_page" in body
        assert "pages" in body

    def test_filter_by_entity_type(self, app_client, db_session, admin_headers):
        make_config_log(db_session, entity_type="priority", action="create")
        make_config_log(db_session, entity_type="status", action="update")
        db_session.flush()

        r = app_client.get(f"{BASE}?entity_type=priority", headers=admin_headers)
        assert r.status_code == 200
        logs = r.json()["logs"]
        for log in logs:
            assert log["entity_type"] == "priority"

    def test_filter_by_action(self, app_client, db_session, admin_headers):
        make_config_log(db_session, action="create")
        make_config_log(db_session, action="delete")
        db_session.flush()

        r = app_client.get(f"{BASE}?action=create", headers=admin_headers)
        assert r.status_code == 200
        for log in r.json()["logs"]:
            assert log["action"] == "create"

    def test_filter_by_user_id(self, app_client, db_session, admin_headers):
        make_config_log(db_session, user_id=42)
        make_config_log(db_session, user_id=99)
        db_session.flush()

        r = app_client.get(f"{BASE}?user_id=42", headers=admin_headers)
        assert r.status_code == 200
        for log in r.json()["logs"]:
            assert log["user_id"] == 42

    def test_filter_by_date_from(self, app_client, db_session, admin_headers):
        old_date = datetime.utcnow() - timedelta(days=30)
        new_date = datetime.utcnow()
        make_config_log(db_session, changed_at=old_date, entity_type="priority")
        make_config_log(db_session, changed_at=new_date, entity_type="area")
        db_session.flush()

        threshold = (datetime.utcnow() - timedelta(days=7)).isoformat()
        r = app_client.get(f"{BASE}?date_from={threshold}", headers=admin_headers)
        assert r.status_code == 200
        # Los logs de hace 30 días no deben aparecer; los de hoy sí
        for log in r.json()["logs"]:
            changed = datetime.fromisoformat(log["changed_at"])
            assert changed >= datetime.fromisoformat(threshold)

    def test_filter_by_date_to(self, app_client, db_session, admin_headers):
        future_date = datetime.utcnow() + timedelta(days=1)
        make_config_log(db_session, changed_at=future_date)
        db_session.flush()

        threshold = datetime.utcnow().isoformat()
        r = app_client.get(f"{BASE}?date_to={threshold}", headers=admin_headers)
        assert r.status_code == 200
        # El log con fecha futura no debe aparecer
        for log in r.json()["logs"]:
            changed = datetime.fromisoformat(log["changed_at"])
            assert changed <= datetime.fromisoformat(threshold)

    def test_invalid_date_from_returns_400(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}?date_from=not-a-date", headers=admin_headers)
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_date_from"

    def test_invalid_date_to_returns_400(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}?date_to=not-a-date", headers=admin_headers)
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_date_to"

    def test_pagination_defaults(self, app_client, db_session, admin_headers):
        r = app_client.get(BASE, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 50

    def test_pagination_custom_page(self, app_client, db_session, admin_headers):
        for _ in range(60):
            make_config_log(db_session)
        db_session.flush()

        r = app_client.get(f"{BASE}?page=2&per_page=20", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["page"] == 2

    def test_per_page_above_200_rejected_422(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}?per_page=201", headers=admin_headers)
        assert r.status_code == 422

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(BASE, headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /{id} — detalle de un log de auditoría
# =============================================================================

class TestGetAuditLog:
    def test_existing_returns_200_with_data(self, app_client, db_session, admin_headers):
        log = make_config_log(
            db_session,
            entity_type="priority",
            action="create",
            before=None,
            after={"code": "TEST", "label": "Test"},
        )
        db_session.flush()

        r = app_client.get(f"{BASE}/{log.id}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()["log"]
        assert body["entity_type"] == "priority"
        assert body["action"] == "create"
        assert body["after_data"]["code"] == "TEST"

    def test_nonexistent_returns_404(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/99999", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["error"] == "not_found"

    def test_response_includes_before_and_after_data(self, app_client, db_session, admin_headers):
        log = make_config_log(
            db_session,
            entity_type="status",
            action="update",
            before={"label": "Old"},
            after={"label": "New"},
        )
        db_session.flush()

        r = app_client.get(f"{BASE}/{log.id}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()["log"]
        assert body["before_data"]["label"] == "Old"
        assert body["after_data"]["label"] == "New"

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/1", headers=no_auth_headers)
        assert r.status_code == 401


# =============================================================================
# GET /export.csv — exportar logs como CSV
# =============================================================================

class TestExportAuditCsv:
    def test_export_returns_csv_content_type(self, app_client, db_session, admin_headers):
        make_config_log(db_session, entity_type="priority", action="create")
        db_session.flush()

        r = app_client.get(f"{BASE}/export.csv", headers=admin_headers)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/csv" in ct

    def test_export_has_content_disposition_header(self, app_client, db_session, admin_headers):
        make_config_log(db_session)
        db_session.flush()

        r = app_client.get(f"{BASE}/export.csv", headers=admin_headers)
        assert r.status_code == 200
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".csv" in cd

    def test_export_contains_bom_utf8(self, app_client, db_session, admin_headers):
        """El CSV debe comenzar con BOM UTF-8 (﻿) para compatibilidad con Excel."""
        make_config_log(db_session)
        db_session.flush()

        r = app_client.get(f"{BASE}/export.csv", headers=admin_headers)
        assert r.status_code == 200
        # BOM UTF-8 = \xef\xbb\xbf en bytes / ﻿ como char
        content = r.text
        assert content.startswith("﻿") or r.content.startswith(b"\xef\xbb\xbf")

    def test_export_csv_headers_row(self, app_client, db_session, admin_headers):
        """Primera fila del CSV debe contener las columnas esperadas."""
        make_config_log(db_session)
        db_session.flush()

        r = app_client.get(f"{BASE}/export.csv", headers=admin_headers)
        assert r.status_code == 200
        # Ignorar el BOM al leer
        content = r.text.lstrip("﻿")
        header_line = content.splitlines()[0]
        expected_columns = ["id", "changed_at", "user_id", "entity_type", "action"]
        for col in expected_columns:
            assert col in header_line

    def test_export_with_entity_type_filter(self, app_client, db_session, admin_headers):
        make_config_log(db_session, entity_type="priority")
        make_config_log(db_session, entity_type="area")
        db_session.flush()

        r = app_client.get(f"{BASE}/export.csv?entity_type=priority", headers=admin_headers)
        assert r.status_code == 200
        content = r.text.lstrip("﻿")
        lines = [l for l in content.splitlines() if l.strip()]
        # Primera línea es header; las demás deben contener "priority"
        data_lines = lines[1:]
        for line in data_lines:
            assert "priority" in line

    def test_export_too_many_rows_returns_400(self, app_client, db_session, admin_headers):
        """Si hay más de 50,000 filas, debe devolver 400 con error='too_many_rows'."""
        from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

        with patch.object(db_session, "query") as mock_q:
            mock_chain = MagicMock()
            mock_chain.options.return_value = mock_chain
            mock_chain.filter.return_value = mock_chain
            mock_chain.count.return_value = 50001
            mock_q.return_value = mock_chain

            r = app_client.get(f"{BASE}/export.csv", headers=admin_headers)
            assert r.status_code == 400
            assert r.json()["error"]["error"] == "too_many_rows"

    def test_export_invalid_date_from_returns_400(self, app_client, admin_headers):
        r = app_client.get(f"{BASE}/export.csv?date_from=bad-date", headers=admin_headers)
        assert r.status_code == 400
        assert r.json()["error"]["error"] == "invalid_date_from"

    def test_no_auth_returns_401(self, app_client, no_auth_headers):
        r = app_client.get(f"{BASE}/export.csv", headers=no_auth_headers)
        assert r.status_code == 401

    def test_export_empty_result_has_only_header(self, app_client, db_session, admin_headers):
        """Sin logs en BD → CSV con solo la fila de encabezados."""
        r = app_client.get(
            f"{BASE}/export.csv?entity_type=nonexistent_type_xyz",
            headers=admin_headers,
        )
        assert r.status_code == 200
        content = r.text.lstrip("﻿")
        lines = [l for l in content.splitlines() if l.strip()]
        # Solo la fila de encabezados, sin datos
        assert len(lines) == 1
        assert "entity_type" in lines[0]

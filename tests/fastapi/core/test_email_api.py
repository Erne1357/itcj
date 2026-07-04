"""F1a (C3): /api/core/v2/email/{status,logout} — envelope success, admin-gated."""
from unittest.mock import patch


class TestEmailStatus:
    @patch("itcj2.core.utils.msgraph_mail.read_account_info",
           return_value={"username": "correo@itcj.mx", "name": "Cuenta ITCJ"})
    @patch("itcj2.core.utils.msgraph_mail.acquire_token_silent", return_value="tok")
    def test_connected(self, mock_token, mock_acct, app_client, auth_headers):
        resp = app_client.get("/api/core/v2/email/status?app=helpdesk",
                              headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["connected"] is True
        assert body["data"]["account"]["username"] == "correo@itcj.mx"

    @patch("itcj2.core.utils.msgraph_mail.read_account_info", return_value=None)
    @patch("itcj2.core.utils.msgraph_mail.acquire_token_silent", return_value=None)
    def test_disconnected(self, mock_token, mock_acct, app_client, auth_headers):
        resp = app_client.get("/api/core/v2/email/status?app=helpdesk",
                              headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == {"connected": False, "account": None}

    def test_missing_app_param(self, app_client, auth_headers):
        resp = app_client.get("/api/core/v2/email/status?app=", headers=auth_headers)
        assert resp.status_code == 400
        assert isinstance(resp.json()["error"], str)

    def test_requires_auth(self, app_client):
        resp = app_client.get("/api/core/v2/email/status?app=helpdesk")
        assert resp.status_code == 401

    def test_requires_admin_perm(self, app_client, student_headers):
        with patch("itcj2.core.services.authz_cache.cached_has_assignment",
                   return_value=False):
            resp = app_client.get("/api/core/v2/email/status?app=helpdesk",
                                  headers=student_headers)
        assert resp.status_code == 403


class TestEmailLogout:
    @patch("itcj2.core.utils.msgraph_mail.clear_account_and_cache")
    def test_logout(self, mock_clear, app_client, auth_headers):
        resp = app_client.post("/api/core/v2/email/logout?app=helpdesk",
                               headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["message"], str)
        mock_clear.assert_called_once_with("helpdesk")

    def test_requires_auth(self, app_client):
        resp = app_client.post("/api/core/v2/email/logout?app=helpdesk")
        assert resp.status_code == 401

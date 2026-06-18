from unittest.mock import patch


class TestMundialMatches:
    def test_today_ok(self, app_client, auth_headers):
        fake = {"scope": "today", "date": "2026-06-18", "tz": "America/Ciudad_Juarez",
                "matches": [{"id": "A", "status": "scheduled"}], "next_match": None}
        with patch("itcj2.core.api.mundial.mundial_service") as svc:
            svc.is_theme_active.return_value = True
            svc.get_matches.return_value = fake
            resp = app_client.get("/api/core/v2/mundial/matches", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["date"] == "2026-06-18"
        assert len(data["matches"]) == 1
        svc.get_matches.assert_called_once_with("today")

    def test_past_scope(self, app_client, auth_headers):
        with patch("itcj2.core.api.mundial.mundial_service") as svc:
            svc.is_theme_active.return_value = True
            svc.get_matches.return_value = {"scope": "past", "matches": [], "next_match": None}
            resp = app_client.get("/api/core/v2/mundial/matches?scope=past", headers=auth_headers)
        assert resp.status_code == 200
        svc.get_matches.assert_called_once_with("past")

    def test_empty_when_theme_inactive(self, app_client, auth_headers):
        with patch("itcj2.core.api.mundial.mundial_service") as svc:
            svc.is_theme_active.return_value = False
            resp = app_client.get("/api/core/v2/mundial/matches", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["matches"] == []
        svc.get_matches.assert_not_called()

    def test_invalid_scope_rejected(self, app_client, auth_headers):
        resp = app_client.get("/api/core/v2/mundial/matches?scope=bogus", headers=auth_headers)
        assert resp.status_code == 422

    def test_never_500_on_service_error(self, app_client, auth_headers):
        with patch("itcj2.core.api.mundial.mundial_service") as svc:
            svc.is_theme_active.return_value = True
            svc.get_matches.side_effect = RuntimeError("boom")
            resp = app_client.get("/api/core/v2/mundial/matches", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["matches"] == []
        assert data["next_match"] is None
        assert data["scope"] == "today"

    def test_unauthenticated(self, app_client):
        resp = app_client.get("/api/core/v2/mundial/matches")
        assert resp.status_code == 401

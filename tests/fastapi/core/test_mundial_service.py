from datetime import datetime
from zoneinfo import ZoneInfo


def test_load_fixtures_returns_list():
    from itcj2.core.services import mundial_service
    fixtures = mundial_service.load_fixtures()
    assert isinstance(fixtures, list)
    assert len(fixtures) >= 1
    assert "kickoff_utc" in fixtures[0]


def test_compute_today_filters_by_cj_date_and_formats_local():
    from itcj2.core.services import mundial_service
    fixtures = [
        {"id": "A", "kickoff_utc": "2026-06-18T19:00:00Z", "stage": "group",
         "group": "A", "home": {"code": "MEX", "name": "Mexico", "flag": "x"},
         "away": {"code": "TBD", "name": "Por definir", "flag": "y"}, "venue": "v"},
        {"id": "B", "kickoff_utc": "2026-06-20T19:00:00Z", "stage": "group",
         "group": "B", "home": {"code": "CAN", "name": "Canada", "flag": "x"},
         "away": {"code": "TBD", "name": "Por definir", "flag": "y"}, "venue": "v"},
    ]
    # 2026-06-18 12:00 en Cd. Juárez (MDT, UTC-6) == 18:00Z; el partido A (19:00Z) es hoy y futuro
    now = datetime(2026, 6, 18, 12, 0, tzinfo=ZoneInfo("America/Ciudad_Juarez"))
    result = mundial_service.compute_today(fixtures, now=now)

    assert result["date"] == "2026-06-18"
    assert len(result["matches"]) == 1
    m = result["matches"][0]
    assert m["id"] == "A"
    assert m["kickoff_local"] == "13:00"
    assert m["status"] == "scheduled"
    # next_match apunta al de mañana
    assert result["next_match"]["id"] == "B"
